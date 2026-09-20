"""Explicit font inputs, glyph masks and compatible-mode GDI text layout.

Font files, aliases and missing-glyph policy are supplied by the caller, not by
a WMF. There is no host-font discovery or registry-based font substitution.
"""

from ctypes import byref
from dataclasses import dataclass, field, replace
from fractions import Fraction
from importlib.resources import files
from io import BytesIO
from itertools import groupby
from math import ceil
from pathlib import Path

import freetype as ft
from fontTools.ttLib import TTFont

from .gdi import UnsupportedOperation
from .gdi_math import sincos_degrees
from .mapping import rounded
from .numeric import float32
from .wingdings import decode_wingdings
from .wmf.objects import Font

C1_CONTROLS = "".join(map(chr, range(0x80, 0xA0)))


def text_rotation(escapement):
    """Share the font scaler's 16.16 rotation with baseline placement."""
    angle = (escapement + 1800) % 3600 - 1800
    sine, cosine = sincos_degrees(angle / 10, accurate=bool(angle % 900))
    return rounded(sine * 65536) / 65536, rounded(cosine * 65536) / 65536


def decode_single_byte(data, codepage):
    """Windows preserves undefined SBCS bytes as their same-valued controls."""
    if codepage not in (1252, 1251):
        raise UnsupportedOperation(f"Unsupported text code page: {codepage}")
    decoded = data.decode(f"cp{codepage}", errors="surrogateescape")
    return "".join(chr(ord(c) - 0xDC00) if 0xDC80 <= ord(c) <= 0xDCFF else c for c in decoded)


@dataclass(frozen=True)
class Glyph:
    size: tuple[int, int]
    bearing: tuple[int, int]
    pixels: bytes
    advance: int | Fraction
    index: int = 0
    channels: int = 1


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
    _glyphs: dict[str, Glyph] = field(default_factory=dict)

    def shape(self, characters, max_pixels):
        return tuple(self.glyph(character, max_pixels) for character in characters)

    def glyph(self, character, max_pixels):
        codepoint = ord(character)
        index = self.cmap.get(codepoint, 0)
        if not index and self.symbol and 0xF000 <= codepoint <= 0xF0FF:
            index = self.cmap.get(codepoint - 0xF000, 0)
        if not index and self.missing_glyph == "error":
            raise UnsupportedOperation(f"Missing glyph for U+{ord(character):04X}")
        if character not in self._glyphs:
            # Honour TrueType instructions without inventing auto-hints for
            # unhinted glyphs. Keep bitmap strikes outside this outline slice.
            target = ft.FT_LOAD_TARGET_MONO if self.quality == 3 else ft.FT_LOAD_TARGET_LCD
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
            padding = 2 if self.quality != 3 else 0  # LCD filtering can extend the mask horizontally.
            if (max(1, bounds.xMax - bounds.xMin) + padding) * max(1, bounds.yMax - bounds.yMin) > max_pixels:
                raise ValueError("Glyph pixel limit exceeded")
            slot.render(ft.FT_RENDER_MODE_MONO if self.quality == 3 else ft.FT_RENDER_MODE_LCD)
            bitmap = slot.bitmap
            packed = bitmap.buffer
            channels = 1 if self.quality == 3 else 3
            expected_mode = ft.FT_PIXEL_MODE_MONO if channels == 1 else ft.FT_PIXEL_MODE_LCD
            if bitmap.pixel_mode != expected_mode:
                raise UnsupportedOperation("Unexpected glyph bitmap format")
            if channels == 1:
                pixels = bytes(
                    255 if packed[y * bitmap.pitch + x // 8] & (128 >> (x % 8)) else 0
                    for y in range(bitmap.rows)
                    for x in range(bitmap.width)
                )
            else:
                pixels = bytes(packed[y * bitmap.pitch + x] for y in range(bitmap.rows) for x in range(bitmap.width))
            self._glyphs[character] = Glyph(
                (bitmap.width // channels, bitmap.rows),
                (slot.bitmap_left, -slot.bitmap_top),
                pixels,
                advance,
                index,
                channels,
            )
        glyph = self._glyphs[character]
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
            self.codepages = getattr(font["OS/2"], "ulCodePageRange1", 0)
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
        if quality not in (0, 1, 2, 3):
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
            font = ft.Face.from_bytes(self.data, index=self.index)
            # Glyph IDs come from the selected cmap; FreeType only rasterizes.
            font.set_char_size(max(1, int(mask_width * 64)), max(1, rounded(size) * 64), 72, 72)

            def metric(units):
                return (units * size * 2 + self.units_per_em) // (2 * self.units_per_em)

            ascent, bottom = self.device_metrics.get(rounded(size), (metric(self.ascent), -metric(self.descent)))
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


class FontCollection:
    """Supplied faces and explicit aliases; never discover or silently replace."""

    def __init__(
        self,
        faces=(),
        *,
        ansi_codepage=1252,
        aliases=None,
        fallbacks=None,
        missing_glyph="error",
        synthesize_styles=False,
        wingdings_fallback=False,
        default_font: Font | None = None,
    ):
        if ansi_codepage not in (1252, 1251):
            raise ValueError("ANSI environment must be Windows-1252 or Windows-1251")
        if missing_glyph not in ("error", "notdef"):
            raise ValueError("Missing-glyph policy must be 'error' or 'notdef'")
        self.ansi_codepage = ansi_codepage
        self.missing_glyph = missing_glyph
        self.synthesize_styles = synthesize_styles
        self.wingdings_fallback = wingdings_fallback
        self.default_font = default_font
        self._wingdings_face = None
        self.aliases = {name.casefold(): target.casefold() for name, target in (aliases or {}).items()}
        self.fallbacks = {name.casefold(): tuple(targets) for name, targets in (fallbacks or {}).items()}
        self._faces = {}
        for face in faces:
            key = (face.family.casefold(), face.weight, face.italic)
            if key in self._faces:
                raise ValueError(f"Ambiguous font face: {face.family}")
            self._faces[key] = face
        if default_font is not None:
            self.resolve(default_font)

    def realize(self, request, face, scale):
        primary = face.realize(request, scale, missing_glyph=self.missing_glyph)
        fallback_faces = []
        for family in self.fallbacks.get(face.family.casefold(), ()):
            key = family.casefold(), request.weight or 400, bool(request.italic)
            fallback = self._select_face(key)
            if fallback is None:
                raise UnsupportedOperation(f"Fallback font unavailable: {family!r}")
            if fallback.symbol:
                raise UnsupportedOperation("A symbol face cannot be a Unicode fallback")
            fallback_faces.append(fallback)
        linked = tuple(f.realize(request, scale, missing_glyph=self.missing_glyph) for f in fallback_faces)
        control_fallback = None
        if fallback_faces:
            # Shaping fallback preserves the realized cell, not the original
            # em request. Its GDI links follow the replacement's realized em.
            cell = Fraction(primary.ascent + primary.descent) / scale[1]
            raw_request = replace(request, height=cell)
            raw = fallback_faces[0].realize(raw_request, scale, missing_glyph=self.missing_glyph)
            raw_links = tuple(
                f.at_size(
                    raw.font.size.y_ppem,
                    width=raw.em_width if request.width else None,
                    quality=request.quality,
                    missing_glyph=self.missing_glyph,
                    escapement=request.escapement,
                    synthetic_bold=request.weight >= 700 and f.weight < 700,
                    synthetic_italic=bool(request.italic) and not f.italic,
                )
                for f in fallback_faces[1:]
            )
            control_fallback = FontRun(raw, raw_links)
        return FontRun(primary, linked, control_fallback)

    def resolve(self, request):
        request = self.default_font if request is None else request
        if request is None:
            raise UnsupportedOperation("Default font resolution")
        family = decode_single_byte(request.face_name.split(b"\0", 1)[0], self.ansi_codepage).casefold()
        family = self.aliases.get(family, family)
        key = family, request.weight or 400, bool(request.italic)
        face = self._select_face(key)
        if (
            face is None
            and self.wingdings_fallback
            and family == "wingdings"
            and (key[1:] == (400, False) or self.synthesize_styles and key[1] in (400, 700))
        ):
            if self._wingdings_face is None:
                self._wingdings_face = FontFace.bundled_wingdings()
            face = self._wingdings_face
        if face is None:
            raise UnsupportedOperation(f"Font face unavailable: {family!r}, weight={key[1]}, italic={key[2]}")
        return face

    def _select_face(self, key):
        face = self._faces.get(key)
        if face is None and self.synthesize_styles and key[1] in (400, 700):
            face = self._faces.get((key[0], 400, False))
        return face

    def decode(self, request, face, data):
        if face is self._wingdings_face:
            if request.charset not in (1, 2):
                raise UnsupportedOperation("Unsupported Wingdings fallback charset request")
            return decode_wingdings(data)
        if face.symbol:
            if request.charset not in (1, 2):
                raise UnsupportedOperation("Unsupported symbol font charset request")
            return "".join(chr(0xF000 | byte) for byte in data)
        codepage = {0: 1252, 1: self.ansi_codepage, 204: 1251}.get(request.charset)
        if codepage is None:
            raise UnsupportedOperation(f"Unsupported text charset: {request.charset}")
        bit = 0 if codepage == 1252 else 2
        if not face.codepages & (1 << bit):
            raise UnsupportedOperation("Font does not advertise the requested charset; explicit selection is required")
        return decode_single_byte(data, codepage)


@dataclass(frozen=True)
class FontRun:
    """Use base line metrics, selecting supplied fallback faces only for holes."""

    primary: RasterFont
    fallbacks: tuple[RasterFont, ...] = ()
    control_fallback: "FontRun | None" = None

    @property
    def ascent(self):
        return self.primary.ascent

    @property
    def descent(self):
        return self.primary.descent

    @property
    def break_character(self):
        return self.primary.break_character

    @property
    def decorations(self):
        return self.primary.decorations

    def glyph(self, character, max_pixels):
        return self.shape(character, max_pixels)[0]

    def shape(self, characters, max_pixels):
        """Shape SBCS control runs before choosing masks and advances.

        A control run containing an unshapable character falls back to raw
        character output. Its formerly invisible controls then participate in
        font linking too. Separators terminate runs; they are not tab stops or
        multiline layout commands.
        """
        if self.primary.symbol:
            return self.primary.shape(characters, max_pixels)
        glyphs = []
        for kind, group in groupby(characters, key=_text_run_kind):
            run = "".join(group)
            if kind == "text":
                glyphs.extend(self._linked_glyph(c, max_pixels) for c in run)
                continue
            missing = [c for c in run if not _blank_control(c) and not self.primary.cmap.get(ord(c))]
            fallback = self
            if missing and self.fallbacks:
                fallback = self.control_fallback or FontRun(self.fallbacks[0], self.fallbacks[1:])
            # Uniscribe accepts DEL's default glyph; it does not make an
            # otherwise shapeable control run switch to raw character output.
            if any(c != "\x7f" for c in missing):
                # GDI suppresses linking for a suffix made entirely of C1
                # controls, not for a C1 character preceding another class.
                link_end = len(run.rstrip(C1_CONTROLS))
                glyphs.extend(
                    fallback._linked_glyph(c, max_pixels, replacement="\u30fb")
                    if i < link_end
                    else fallback.primary.glyph(c, max_pixels)
                    for i, c in enumerate(run)
                )
            else:
                glyphs.extend(
                    Glyph((0, 0), (0, 0), b"", 0) if _blank_control(c) else fallback.primary.glyph(c, max_pixels)
                    for c in run
                )
        return tuple(glyphs)

    def _linked_glyph(self, character, max_pixels, *, replacement=None):
        codepoint = ord(character)
        if self.primary.cmap.get(codepoint):
            return self.primary.glyph(character, max_pixels)
        for fallback in self.fallbacks:
            if fallback.cmap.get(codepoint):
                glyph = fallback.glyph(character, max_pixels)
                # GDI's linked-font lookup rejects zero-advance candidates,
                # even when their cmap contains the requested character.
                if glyph.advance:
                    return glyph
        if replacement is not None:
            # Raw GDI output retries the linking chain with the default link
            # character (Katakana middle dot) before using the base .notdef.
            codepoint = ord(replacement)
            for fallback in (self.primary, *self.fallbacks):
                if fallback.cmap.get(codepoint):
                    glyph = fallback.glyph(replacement, max_pixels)
                    if glyph.advance:
                        return glyph
        return self.primary.glyph(character, max_pixels)


def _text_run_kind(character):
    codepoint = ord(character)
    if character in "\t\n\v\r\x1c\x1d\x1e\x1f\x85":
        return character
    if (codepoint < 32 and character != "\f") or 0x7F <= codepoint <= 0x9F:
        return "control"
    return "text"


def _blank_control(character):
    return character in "\t\n\r\x1c\x1d\x1e\x1f" or 0x80 <= ord(character) <= 0x9F


@dataclass(frozen=True)
class TextLayout:
    glyphs: tuple[tuple[int, int, Glyph], ...] = ()
    background: tuple[tuple[int, int], ...] | None = None
    position: tuple[int | Fraction | float, int | Fraction | float] | None = None
    decorations: tuple[tuple[tuple[int, int], ...], ...] = ()


def layout_text(
    font,
    text,
    x,
    y,
    alignment,
    advances,
    *,
    opaque,
    max_pixels,
    scale=1,
    extra=0,
    justification=(0, 0),
    characters=None,
    escapement=0,
):
    """Place independently realized glyphs; explicit advances replace metrics."""
    if characters is None:
        characters = decode_single_byte(text, 1252)
    if len(characters) != len(text):
        raise UnsupportedOperation("Multibyte text layout is not implemented")
    sine, cosine = text_rotation(escapement)

    def project(px, py, *, snap=True):
        if not escapement % 3600:
            return px, py
        dx, dy = float32(px - x), float32(py - y)
        dx, dy = (
            float32(float32(dx * cosine) + float32(dy * sine)),
            float32(float32(dy * cosine) - float32(dx * sine)),
        )
        return (x + rounded(dx), y + rounded(dy)) if snap else (x + dx, y + dy)

    horizontal, vertical = alignment & 6, alignment & 24
    if alignment & ~31 or horizontal not in (0, 2, 6) or vertical not in (0, 8, 24):
        raise UnsupportedOperation("Text alignment")
    if advances and len(advances) != len(text):
        raise ValueError("Text advance count must match the byte count")
    glyphs = font.shape(characters, max_pixels)
    offsets = [0]
    mapped_offsets = [0]
    total = 0
    break_count, break_extra = justification
    # Spacing accumulates before pixel placement. Preserve fractional remainders
    # instead of distributing rounded per-character additions.
    break_step = int(Fraction(break_extra * scale * 65536, break_count)) if break_count > 0 else 0
    for index, glyph in enumerate(glyphs):
        if advances:
            total += advances[index] + extra
            mapped_offsets.append(total * scale)
        else:
            total += glyph.advance * 65536 + int(extra * scale * 65536)
            if ord(characters[index]) == font.break_character:
                total += break_step
            # The accumulated device advance uses nearest-even ties before
            # conversion to logical coordinates, whose rounding is distinct.
            device_offset = round(Fraction(total, 65536))
            mapped_offsets.append(rounded(device_offset / scale) * scale)
        offsets.append(rounded(mapped_offsets[-1]))
    run_width = total * scale if advances else rounded((total // 65536) / scale) * scale
    if escapement % 900 and not advances:
        run_width = Fraction(total, 65536)
    width = rounded(run_width)
    # Monochrome GDI places cached glyphs at integer origins. Centering an
    # odd-width run chooses the lower coordinate, not a fractional mask phase.
    origin_x = x - (width if horizontal == 2 else (width + 1) // 2 if horizontal == 6 else 0)
    baseline = y + (font.ascent if vertical == 0 else -font.descent if vertical == 8 else 0)
    position = (x + (run_width if horizontal == 0 else -run_width), y) if alignment & 1 and horizontal != 6 else None
    if position is not None:
        position = project(*position, snap=False)
    positioned = []
    for glyph, offset in zip(glyphs, offsets[:-1], strict=True):
        gx, gy = project(origin_x + offset, baseline)
        positioned.append((gx + glyph.bearing[0], gy + glyph.bearing[1], glyph))
    background_width = ceil(total * scale) if advances else ceil((Fraction(total, 65536) // scale) * scale)
    # An opaque run must also cover protruding ink, even with negative spacing
    # or a final explicit advance smaller than the glyph's black box.
    right = max(
        [origin_x + background_width]
        + [
            ceil(origin_x + offset + glyph.bearing[0] + glyph.size[0])
            for glyph, offset in zip(glyphs, mapped_offsets[:-1], strict=True)
        ]
    )
    background = (
        tuple(
            project(px, py)
            for px, py in (
                (origin_x, baseline - font.ascent),
                (right, baseline - font.ascent),
                (right, baseline + font.descent),
                (origin_x, baseline + font.descent),
            )
        )
        if opaque
        else None
    )
    decorations = tuple(
        tuple(
            project(px, py)
            for px, py in (
                (origin_x, baseline - offset),
                (origin_x + width, baseline - offset),
                (origin_x + width, baseline - offset + thickness),
                (origin_x, baseline - offset + thickness),
            )
        )
        for offset, thickness in font.decorations
    )
    return TextLayout(tuple(positioned), background, position, decorations)
