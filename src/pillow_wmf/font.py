"""Pinned font bytes, device metrics, FreeType realization and glyph masks."""

from ctypes import byref, string_at
from dataclasses import dataclass, field
from fractions import Fraction
from importlib.resources import files
from io import BytesIO
from math import ceil, floor
from pathlib import Path
from threading import Lock, RLock

import freetype as ft
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont
from PIL import Image

from .binary import ResourceLimitError
from .gdi import UnsupportedOperation
from .mapping import fixed, rounded
from .numeric import efloat_sqrt, float32
from .symbol import WINDOWS_SYMBOL_BYTES
from .text_math import text_rotation

# freetype-py shares one FT_Library, whose face list is not thread-safe:
# creating and destroying faces is serialized. Faces are destroyed by the
# garbage collector in whichever thread releases them, hence re-entrancy.
_FREETYPE = RLock()


class _Face(ft.Face):
    def __del__(self):
        with _FREETYPE:
            super().__del__()


@dataclass(frozen=True)
class Glyph:
    size: tuple[int, int]
    bearing: tuple[int, int]
    pixels: bytes
    advance: int | Fraction
    index: int = 0
    channels: int = 1
    ink_span: tuple[int, int] = (0, 0)
    background_ink_span: tuple[int, int] = (0, 0)
    # The exact left edge of the black box, in pixels from the origin.
    ink_left: Fraction = Fraction(0)


GLYPH_CACHE_BYTES = 4 << 20


class GlyphCache(dict):
    """Least-recently-used glyph masks for one realized font, bounded in bytes.

    Evicted glyphs are re-rendered identically on demand. The most recent
    glyph is always retained, even when it alone exceeds the budget.
    """

    def __init__(self, glyphs=(), *, limit=GLYPH_CACHE_BYTES):
        super().__init__()
        self.limit = limit
        self.size = 0
        for index, glyph in dict(glyphs).items():
            self.store(index, glyph)

    def lookup(self, index):
        glyph = super().pop(index, None)
        if glyph is not None:
            super().__setitem__(index, glyph)
        return glyph

    def store(self, index, glyph):
        previous = super().pop(index, None)
        if previous is not None:
            self.size -= len(previous.pixels)
        super().__setitem__(index, glyph)
        self.size += len(glyph.pixels)
        while self.size > self.limit and len(self) > 1:
            self.size -= len(super().pop(next(iter(self))).pixels)


@dataclass
class RasterFont:
    """Glyph generation is independent of GDI alignment and DC state."""

    font: ft.Face
    ascent: int
    descent: int
    hinted: bool = True
    design_advances: dict[int, int] = field(default_factory=dict)
    advance_scale: float = 1
    quality: int = 3
    break_character: int = 32
    cmap: dict[int, int] = field(default_factory=dict)
    symbol: bool = False
    missing_glyph: str = "notdef"
    em_width: float = 0
    escapement: int = 0
    synthetic_bold: bool = False
    synthetic_italic: bool = False
    decorations: tuple[tuple[int, int], ...] = ()
    background_cell: tuple[int, int] = (0, 0)
    # The horizontal pixels per design unit as the scaler quantizes it, 16.16.
    advance_fixed: Fraction = Fraction(1)
    # Monochrome glyphs of an unhinted face are drawn by the TrueType scan
    # rules (and simulated styles by the scaler's emboldening): a transformed
    # font supplies the mask.
    scan_masks: object = None
    _glyphs: dict[int, Glyph] = field(default_factory=GlyphCache)
    # One FreeType face has one glyph slot: glyph realization is serialized.
    # Copies made with dataclasses.replace share the face, cache and lock.
    _lock: Lock = field(default_factory=Lock, repr=False, compare=False)

    def __post_init__(self):
        if not isinstance(self._glyphs, GlyphCache):
            self._glyphs = GlyphCache(self._glyphs)

    def shape(self, characters, max_pixels, *, raw=False):
        return tuple(self.glyph(character, max_pixels) for character in characters)

    def glyph(self, character, max_pixels):
        codepoint = ord(character)
        index = self.cmap.get(codepoint, 0)
        if not index and self.symbol and 0xF000 <= codepoint <= 0xF0FF:
            index = self.cmap.get(codepoint - 0xF000, 0)
        if not index and self.missing_glyph == "error":
            raise UnsupportedOperation(f"Missing glyph for U+{ord(character):04X}")
        return self.glyph_index(index, max_pixels)

    def glyph_index(self, index, max_pixels):
        """Realize a physical glyph without character mapping or font linking."""
        try:
            with self._lock:
                return self._glyph_index(index, max_pixels)
        except ft.FT_Exception as error:
            # FreeType rejects some degenerate outlines, e.g. at extreme
            # widths; the glyph is unrenderable, not an internal failure.
            raise UnsupportedOperation(f"Cannot realize glyph {index}: {error}") from error

    def _glyph_index(self, index, max_pixels):
        if not 0 <= index < self.font.num_glyphs:
            index = 0
        glyph = self._glyphs.lookup(index)
        if glyph is None:
            # Honour TrueType instructions without inventing auto-hints for
            # unhinted glyphs. Keep bitmap strikes outside this outline slice.
            target = {3: ft.FT_LOAD_TARGET_MONO, 4: ft.FT_LOAD_TARGET_NORMAL}.get(self.quality, ft.FT_LOAD_TARGET_LCD)
            flags = target | ft.FT_LOAD_NO_AUTOHINT | ft.FT_LOAD_NO_BITMAP
            if self.escapement % 900:
                flags |= ft.FT_LOAD_NO_HINTING
            self.font.load_glyph(index, flags)
            slot = self.font.glyph
            advance = (
                (slot.advance.x + 32) // 64
                if self.hinted
                else rounded(self.design_advances[index] * self.advance_fixed)
            )
            if self.escapement % 900:
                advance = self.design_advances[index] * Fraction(self.advance_scale)
            if self.synthetic_bold:
                ft.FT_Outline_EmboldenXY(byref(slot.outline._FT_Outline), 64, 0)
                advance += 1
            if self.synthetic_italic:
                # Measured native outline shear, distinct from FreeType's
                # default oblique angle. Real-font masks remain approximate.
                shear = ft.Matrix(65536, rounded(0.34 * 65536), 0, 65536)
                ft.FT_Outline_Transform(byref(slot.outline._FT_Outline), byref(shear))
            ink_bounds = slot.get_glyph().get_cbox(ft.FT_GLYPH_BBOX_SUBPIXELS)
            if self.escapement:
                sine, cosine = text_rotation(self.escapement)
                matrix = ft.Matrix(
                    rounded(cosine * 65536),
                    rounded(-sine * 65536),
                    rounded(sine * 65536),
                    rounded(cosine * 65536),
                )
                ft.FT_Outline_Transform(byref(slot.outline._FT_Outline), byref(matrix))
            bounds = slot.get_glyph().get_cbox(ft.FT_GLYPH_BBOX_PIXELS)
            padding = 0 if self.quality in (3, 4) else 2  # LCD filtering can extend the mask horizontally.
            if (max(1, bounds.xMax - bounds.xMin) + padding) * max(1, bounds.yMax - bounds.yMin) > max_pixels:
                raise ResourceLimitError("Glyph pixel limit exceeded")
            slot.render(
                {3: ft.FT_RENDER_MODE_MONO, 4: ft.FT_RENDER_MODE_NORMAL}.get(self.quality, ft.FT_RENDER_MODE_LCD)
            )
            bitmap = slot.bitmap
            channels = 1 if self.quality in (3, 4) else 3
            expected_mode = {3: ft.FT_PIXEL_MODE_MONO, 4: ft.FT_PIXEL_MODE_GRAY}.get(self.quality, ft.FT_PIXEL_MODE_LCD)
            if bitmap.pixel_mode != expected_mode:
                raise UnsupportedOperation("Unexpected glyph bitmap format")
            pixels = _unpack_bitmap(bitmap, mono=self.quality == 3)
            ink_span = rounded(Fraction(ink_bounds.xMin, 64)), rounded(Fraction(ink_bounds.xMax, 64))
            # Unhinted oblique realization encloses ink in whole pixels;
            # decoration placement retains its separate nearest-pixel span.
            background_ink_span = (
                (ink_bounds.xMin // 64, ceil(Fraction(ink_bounds.xMax, 64))) if self.escapement % 900 else ink_span
            )
            size, bearing = (bitmap.width // channels, bitmap.rows), (slot.bitmap_left, -slot.bitmap_top)
            if self.scan_masks is not None:
                styled = self.scan_masks.glyph(index, max_pixels)
                size, bearing, pixels = styled.size, styled.bearing, styled.pixels
            glyph = Glyph(
                size,
                bearing,
                pixels,
                advance,
                index,
                channels,
                ink_span=ink_span,
                background_ink_span=background_ink_span,
                ink_left=Fraction(ink_bounds.xMin, 64),
            )
            self._glyphs.store(index, glyph)
        if glyph.size[0] * glyph.size[1] > max_pixels:
            raise ResourceLimitError("Glyph pixel limit exceeded")
        return glyph


def _unpack_bitmap(bitmap, *, mono):
    """Copy a rendered FreeType bitmap to one byte per sample, row-major.

    Monochrome bits become 0 or 255. Read the raw buffer once rather than
    through freetype-py's per-byte ``buffer`` list.
    """
    width, rows, pitch = bitmap.width, bitmap.rows, bitmap.pitch
    if not width or not rows:
        return b""
    if pitch <= 0:
        raise UnsupportedOperation("Unexpected glyph bitmap format")
    data = string_at(bitmap._FT_Bitmap.buffer, rows * pitch)
    if mono:
        return Image.frombytes("1", (width, rows), data, "raw", "1", pitch).convert("L").tobytes()
    if pitch == width:
        return data
    return b"".join(data[row : row + width] for row in range(0, rows * pitch, pitch))


def whole_em(size, units_per_em) -> int:
    """The scaler's whole-pixel em: the pixels per notional unit held in
    16.16, times the em square, rounded."""
    per_unit = Fraction(floor(Fraction(size) * 65536 / units_per_em + Fraction(1, 2)), 65536)
    return floor(per_unit * units_per_em + Fraction(1, 2))


def default_em_height(m21, m22) -> Fraction:
    """The logical em of a zero font height: the device's 16 pixel default
    through the world y axis (whose device image is (m21, m22)), rounded to
    whole logical units with GDI's single-precision arithmetic."""
    a, b = float32(16 * m21), float32(16 * m22)
    length = efloat_sqrt(float32(float32(a * a) + float32(b * b)))
    if not length:
        return Fraction(24)
    value = float32(float32(1 / length) * 256)
    return Fraction(int(abs(value) + 0.5) or 24)


class FontFace:
    """A pinned font face with its Windows metrics, not Pillow's metrics.

    TrueType, CFF and CFF2 outlines are accepted; FreeType rasterizes CFF
    glyphs, and a variable font draws its default instance.
    """

    def __init__(self, data: bytes, *, index=0):
        self.data = bytes(data)
        self.index = index
        with TTFont(BytesIO(self.data), fontNumber=index) as font:
            # Variable fonts draw their default instance; CFF and CFF2 outlines
            # are rasterized by FreeType like TrueType ones.
            outlines = next((tag for tag in ("glyf", "CFF ", "CFF2") if tag in font), None)
            if outlines is None:
                raise UnsupportedOperation("Font has no TrueType or CFF outlines")
            self.family = font["name"].getBestFamilyName()
            self.weight = font["OS/2"].usWeightClass
            self.italic = bool(font["OS/2"].fsSelection & 1)
            self.units_per_em = font["head"].unitsPerEm
            self.outline_cell = font["head"].yMax, -font["head"].yMin
            self.ascent = font["OS/2"].usWinAscent
            self.descent = font["OS/2"].usWinDescent
            if not self.ascent + self.descent:
                self.ascent, self.descent = font["hhea"].ascent, -font["hhea"].descent
            # Realization divides by the em square and the Windows cell height.
            if self.units_per_em <= 0 or self.ascent + self.descent <= 0:
                raise UnsupportedOperation("Font has no usable vertical metrics")
            self.average_width = font["OS/2"].xAvgCharWidth
            self.underline_metrics = font["post"].underlinePosition, font["post"].underlineThickness
            self.strikeout_metrics = font["OS/2"].yStrikeoutPosition, font["OS/2"].yStrikeoutSize
            first = font["OS/2"].usFirstCharIndex
            self.break_character = first + 2 if first <= 1 else 32
            self.design_advances = {i: font["hmtx"][name][0] for i, name in enumerate(font.getGlyphOrder())}
            # Black boxes along the baseline: the left side bearing to it plus the box width.
            # Black boxes across it: the box bottom and top.
            self.ink_spans, self.ink_heights = {}, {}
            if outlines == "glyf":
                glyf = font["glyf"]
                for i, name in enumerate(font.getGlyphOrder()):
                    glyph = glyf[name]
                    if getattr(glyph, "numberOfContours", 0):
                        bearing = font["hmtx"][name][1]
                        self.ink_spans[i] = (bearing, bearing + glyph.xMax - glyph.xMin)
                        self.ink_heights[i] = (glyph.yMin, glyph.yMax)
                self.hinted = "fpgm" in font or any(
                    getattr(glyph, "program", None) and glyph.program.getBytecode()
                    for glyph in (glyf[name] for name in font.getGlyphOrder())
                )
            else:
                glyphs = font.getGlyphSet()
                for i, name in enumerate(font.getGlyphOrder()):
                    pen = BoundsPen(glyphs)
                    glyphs[name].draw(pen)
                    if pen.bounds is not None:
                        x_min, y_min, x_max, y_max = (round(value) for value in pen.bounds)
                        bearing = font["hmtx"][name][1]
                        self.ink_spans[i] = (bearing, bearing + x_max - x_min)
                        self.ink_heights[i] = (y_min, y_max)
                # FreeType's own CFF engine draws horizontal glyphs at every quality.
                self.hinted = True
            symbol_map = next(
                (table.cmap for table in font["cmap"].tables if table.platformID == 3 and table.platEncID == 0), None
            )
            self.symbol = symbol_map is not None
            if self.symbol:
                self.break_character |= 0xF000
            mapping = symbol_map if self.symbol else font.getBestCmap() or {}
            self.cmap = {codepoint: font.getGlyphID(name) for codepoint, name in mapping.items()}
            self.codepages = getattr(font["OS/2"], "ulCodePageRange1", 0) | (
                getattr(font["OS/2"], "ulCodePageRange2", 0) << 32
            )
            self.device_metrics = {}
            if "VDMX" in font:
                table = font["VDMX"]
                # RasterContext has square device pixels. These ratios describe
                # the device, not the logical mapping or requested font width.
                for ratio in table.ratRanges:
                    aspect = ratio["xRatio"], ratio["yStartRatio"], ratio["yEndRatio"]
                    if ratio["bCharSet"] == 1 and (
                        aspect == (0, 0, 0) or aspect[0] == 1 and aspect[1] <= 1 <= aspect[2]
                    ):
                        self.device_metrics = dict(sorted(table.groups[ratio["groupIndex"]].items()))
                        break
        self._sizes = {}
        self._lock = Lock()

    def __getstate__(self):
        # Realized sizes hold FreeType handles; they are rebuilt on demand.
        return {key: value for key, value in vars(self).items() if key not in ("_sizes", "_lock")}

    def __setstate__(self, state):
        vars(self).update(state)
        self._sizes = {}
        self._lock = Lock()

    @classmethod
    def from_path(cls, path, *, index=0):
        return cls(Path(path).read_bytes(), index=index)

    @classmethod
    def bundled_wingdings(cls):
        """Load the prebuilt Unicode Wingdings fallback; selection stays explicit."""
        return cls(files("pillow_wmf").joinpath("fonts", "PillowWMFWingdingsFallback.ttf").read_bytes())

    @classmethod
    def bundled_symbol(cls):
        """Wine's unmodified Symbol face, retaining its legacy symbol cmap."""
        face = cls(files("pillow_wmf").joinpath("fonts", "symbol", "symbol.ttf").read_bytes())
        face.cmap = {0xF000 | byte: face.cmap[0xF000 | byte] for byte in WINDOWS_SYMBOL_BYTES}
        return face

    def realize(self, request, scale, *, missing_glyph="notdef", advanced=False, aspect=1):
        """Classic compatible-mode realization; natural width follows height.

        In GM_ADVANCED the world transform stretches the glyphs: a natural
        width follows the horizontal scale and the height the vertical one,
        the width also multiplied by ``aspect`` (a metafile text record's
        font transform).
        """
        sx, sy = scale
        height = abs(request.height) * sy if request.height else default_em_height(0, sy) * abs(sy)
        device_scale = 1
        if request.height > 0:
            # Cell-to-em conversion retains a fractional size for metrics;
            # the outline grid is realized separately at integer ppem.
            fitted = self._em_for_cell(height)
            if fitted is not None:
                device_scale = Fraction(fitted * (self.ascent + self.descent), self.units_per_em) / height
                height = fitted
            else:
                height *= Fraction(self.units_per_em, self.ascent + self.descent)
                height = Fraction(int(height * 65536), 65536)
        if request.width and self.average_width <= 0:
            raise UnsupportedOperation("Font has no usable average-width metric")
        width = (
            abs(request.width) * sx * Fraction(self.units_per_em, self.average_width) * device_scale
            if request.width
            else None
        )
        if advanced and not request.width and (abs(sx) != abs(sy) or aspect != 1):
            width = height * Fraction(abs(sx)) / Fraction(abs(sy)) * Fraction(aspect)
        return self.at_size(
            height,
            width=width,
            quality=request.quality,
            missing_glyph=missing_glyph,
            escapement=request.escapement,
            synthetic_bold=request.weight >= 700 and self.weight < 700,
            synthetic_italic=bool(request.italic) and not self.italic,
            underline=bool(request.underline),
            strikeout=bool(request.strikeout),
        )

    def _scan_masks(self, size, width, quality, escapement, bold, italic):
        if quality != 3 or escapement or self.hinted:
            return None
        from .text_transform import TransformedFont  # noqa: PLC0415 - text_transform builds on this module

        return TransformedFont(
            self.data,
            self.index,
            # An isotropic scale realizes both axes at the whole-pixel em.
            (
                Fraction(width)
                * (whole_em(size, self.units_per_em) / Fraction(size) if width == size else 1)
                / self.units_per_em,
                0,
                0,
                -Fraction(whole_em(size, self.units_per_em)) / self.units_per_em,
            ),
            self.units_per_em,
            self.ascent,
            self.descent,
            self.design_advances,
            quality=3,
            oblique=italic,
            embolden=bold,
        )

    def _em_for_cell(self, height):
        """Use the first exact VDMX cell, or the entry before an overshoot.

        Device heights can repeat or even decrease as hinting changes. Search
        in ppem order, rather than sorting by cell height or interpolating.
        Outside the table's coverage, retain ordinary outline scaling.
        """
        previous = None
        for em, (ascent, bottom) in self.device_metrics.items():
            cell = ascent - bottom
            if cell == height:
                return em
            if cell > height:
                return previous
            previous = em
        return None

    def at_size(
        self,
        size,
        *,
        width=None,
        quality=3,
        missing_glyph="notdef",
        escapement=0,
        synthetic_bold=False,
        synthetic_italic=False,
        underline=False,
        strikeout=False,
    ):
        # Draft/proof affect legacy bitmap strike selection. For the static
        # TrueType outlines supported here, they share default smoothing.
        # Keep the requested value in the realized font and its cache key.
        if quality not in range(256):
            raise ValueError("Font quality is a byte")
        if quality > 6:
            quality = 0  # Undefined qualities render as DEFAULT_QUALITY.
        if missing_glyph not in ("error", "notdef"):
            raise ValueError("Missing-glyph policy must be 'error' or 'notdef'")
        if size <= 0:
            raise ValueError("Font pixel size must be positive")
        mask_width = whole_em(size, self.units_per_em) if width is None else width
        width = size if width is None else width
        escapement %= 3600
        key = (
            size,
            width,
            mask_width,
            quality,
            missing_glyph,
            escapement,
            synthetic_bold,
            synthetic_italic,
            underline,
            strikeout,
        )
        with self._lock:
            if key in self._sizes:
                # Least recently used: a hit moves the size to the end of eviction.
                self._sizes[key] = self._sizes.pop(key)
            else:
                # Bound the cache independently of the number of WMF font objects.
                if len(self._sizes) >= 32:
                    self._sizes.pop(next(iter(self._sizes)))
                try:
                    with _FREETYPE:
                        font = _Face.from_bytes(self.data, index=self.index)
                    # Glyph IDs come from the selected cmap; FreeType only rasterizes.
                    font.set_char_size(
                        max(1, int(mask_width * 64)), max(1, whole_em(size, self.units_per_em) * 64), 72, 72
                    )
                except ft.FT_Exception as error:
                    raise UnsupportedOperation(
                        f"Cannot realize font {self.family!r} at {size} pixels: {error}"
                    ) from error

                # The scaler holds the vertical pixels per design unit in 16.16.
                vertical = Fraction(round(Fraction(size) * 65536 / self.units_per_em), 65536)

                def metric(units):
                    return rounded(units * vertical)

                ascent, bottom = self.device_metrics.get(
                    whole_em(size, self.units_per_em), (metric(self.ascent), -metric(self.descent))
                )
                background_cell = ascent, -bottom
                if escapement % 1800:
                    # General transforms bound the font's ink with an em/64
                    # safety margin. Quarter turns retain the Windows cell;
                    # oblique transforms use the font-wide outline bounding box.
                    cell = self.outline_cell if escapement % 900 else (self.ascent, self.descent)
                    margin = self.units_per_em // 64
                    background_cell = tuple(
                        ceil(Fraction(fixed(float32((units + margin) * float32(size / self.units_per_em))), 16))
                        for units in cell
                    )
                self._sizes[key] = RasterFont(
                    font,
                    ascent,
                    -bottom,
                    self.hinted,
                    self.design_advances,
                    float32(width / self.units_per_em),
                    quality,
                    self.break_character,
                    self.cmap,
                    self.symbol,
                    missing_glyph,
                    em_width=width,
                    advance_fixed=Fraction(round(Fraction(width) * 65536 / self.units_per_em), 65536),
                    escapement=escapement,
                    background_cell=background_cell,
                    synthetic_bold=synthetic_bold,
                    synthetic_italic=synthetic_italic,
                    scan_masks=self._scan_masks(size, width, quality, escapement, synthetic_bold, synthetic_italic),
                    decorations=tuple(
                        (
                            rounded(position * size / self.units_per_em),
                            # Axis-aligned rules have a one-pixel minimum. An
                            # oblique rule is a filled contour: a thickness that
                            # realizes to zero remains degenerate and paints nothing.
                            max(int(escapement % 900 == 0), rounded(thickness * size / self.units_per_em)),
                        )
                        for enabled, (position, thickness) in (
                            (underline, self.underline_metrics),
                            (strikeout, self.strikeout_metrics),
                        )
                        if enabled
                    ),
                )
            return self._sizes[key]
