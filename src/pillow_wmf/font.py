"""Pinned font bytes, device metrics, FreeType realization and glyph masks."""

from ctypes import byref
from dataclasses import dataclass, field
from fractions import Fraction
from importlib.resources import files
from io import BytesIO
from math import ceil
from pathlib import Path

import freetype as ft
from fontTools.ttLib import TTFont

from .gdi import UnsupportedOperation
from .mapping import fixed, rounded
from .numeric import float32
from .symbol import WINDOWS_SYMBOL_BYTES
from .text_math import text_rotation


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
    missing_glyph: str = "error"
    em_width: float = 0
    escapement: int = 0
    synthetic_bold: bool = False
    synthetic_italic: bool = False
    decorations: tuple[tuple[int, int], ...] = ()
    background_cell: tuple[int, int] = (0, 0)
    _glyphs: dict[int, Glyph] = field(default_factory=dict)

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
        if not 0 <= index < self.font.num_glyphs:
            index = 0
        if index not in self._glyphs:
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
                else rounded(self.design_advances[index] * self.advance_scale)
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
                raise ValueError("Glyph pixel limit exceeded")
            slot.render(
                {3: ft.FT_RENDER_MODE_MONO, 4: ft.FT_RENDER_MODE_NORMAL}.get(self.quality, ft.FT_RENDER_MODE_LCD)
            )
            bitmap = slot.bitmap
            packed = bitmap.buffer
            channels = 1 if self.quality in (3, 4) else 3
            expected_mode = {3: ft.FT_PIXEL_MODE_MONO, 4: ft.FT_PIXEL_MODE_GRAY}.get(self.quality, ft.FT_PIXEL_MODE_LCD)
            if bitmap.pixel_mode != expected_mode:
                raise UnsupportedOperation("Unexpected glyph bitmap format")
            if self.quality == 3:
                pixels = bytes(
                    255 if packed[y * bitmap.pitch + x // 8] & (128 >> (x % 8)) else 0
                    for y in range(bitmap.rows)
                    for x in range(bitmap.width)
                )
            else:
                pixels = bytes(packed[y * bitmap.pitch + x] for y in range(bitmap.rows) for x in range(bitmap.width))
            ink_span = rounded(Fraction(ink_bounds.xMin, 64)), rounded(Fraction(ink_bounds.xMax, 64))
            # Unhinted oblique realization encloses ink in whole pixels;
            # decoration placement retains its separate nearest-pixel span.
            background_ink_span = (
                (ink_bounds.xMin // 64, ceil(Fraction(ink_bounds.xMax, 64))) if self.escapement % 900 else ink_span
            )
            self._glyphs[index] = Glyph(
                (bitmap.width // channels, bitmap.rows),
                (slot.bitmap_left, -slot.bitmap_top),
                pixels,
                advance,
                index,
                channels,
                ink_span=ink_span,
                background_ink_span=background_ink_span,
            )
        glyph = self._glyphs[index]
        if glyph.size[0] * glyph.size[1] > max_pixels:
            raise ValueError("Glyph pixel limit exceeded")
        return glyph


class FontFace:
    """A pinned TrueType face with its Windows metrics, not Pillow's metrics."""

    def __init__(self, data: bytes, *, index=0):
        self.data = bytes(data)
        self.index = index
        with TTFont(BytesIO(self.data), fontNumber=index) as font:
            if "glyf" not in font or "fvar" in font:
                raise UnsupportedOperation("Only static TrueType outlines are supported")
            self.family = font["name"].getBestFamilyName()
            self.weight = font["OS/2"].usWeightClass
            self.italic = bool(font["OS/2"].fsSelection & 1)
            self.units_per_em = font["head"].unitsPerEm
            self.outline_cell = font["head"].yMax, -font["head"].yMin
            self.ascent = font["OS/2"].usWinAscent
            self.descent = font["OS/2"].usWinDescent
            if not self.ascent + self.descent:
                self.ascent, self.descent = font["hhea"].ascent, -font["hhea"].descent
            self.average_width = font["OS/2"].xAvgCharWidth
            self.underline_metrics = font["post"].underlinePosition, font["post"].underlineThickness
            self.strikeout_metrics = font["OS/2"].yStrikeoutPosition, font["OS/2"].yStrikeoutSize
            first = font["OS/2"].usFirstCharIndex
            self.break_character = first + 2 if first <= 1 else 32
            self.design_advances = {i: font["hmtx"][name][0] for i, name in enumerate(font.getGlyphOrder())}
            self.hinted = "fpgm" in font or any(
                getattr(glyph, "program", None) and glyph.program.getBytecode()
                for glyph in (font["glyf"][name] for name in font.getGlyphOrder())
            )
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

    def realize(self, request, scale, *, missing_glyph="error"):
        """Classic compatible-mode realization; natural width follows height."""
        sx, sy = scale
        height = abs(request.height) * sy if request.height else 16
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
        missing_glyph="error",
        escapement=0,
        synthetic_bold=False,
        synthetic_italic=False,
        underline=False,
        strikeout=False,
    ):
        # Draft/proof affect legacy bitmap strike selection. For the static
        # TrueType outlines supported here, they share default smoothing.
        # Keep the requested value in the realized font and its cache key.
        if quality not in range(7):
            raise UnsupportedOperation("Unsupported font quality")
        if missing_glyph not in ("error", "notdef"):
            raise ValueError("Missing-glyph policy must be 'error' or 'notdef'")
        if size <= 0:
            raise ValueError("Font pixel size must be positive")
        mask_width = rounded(size) if width is None else width
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
        if key not in self._sizes:
            # Bound the cache independently of the number of WMF font objects.
            if len(self._sizes) >= 32:
                self._sizes.pop(next(iter(self._sizes)))
            try:
                font = ft.Face.from_bytes(self.data, index=self.index)
                # Glyph IDs come from the selected cmap; FreeType only rasterizes.
                font.set_char_size(max(1, int(mask_width * 64)), max(1, rounded(size) * 64), 72, 72)
            except ft.FT_Exception as error:
                raise UnsupportedOperation(f"Cannot realize font {self.family!r} at {size} pixels: {error}") from error

            def metric(units):
                return (units * size * 2 + self.units_per_em) // (2 * self.units_per_em)

            ascent, bottom = self.device_metrics.get(rounded(size), (metric(self.ascent), -metric(self.descent)))
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
                escapement=escapement,
                background_cell=background_cell,
                synthetic_bold=synthetic_bold,
                synthetic_italic=synthetic_italic,
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
