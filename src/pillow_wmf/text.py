"""Explicit font inputs, glyph masks and horizontal GDI layout.

Font files, aliases and missing-glyph policy are supplied by the caller, not by
a WMF. There is no host-font discovery, font linking or automatic shaping.
"""

from dataclasses import dataclass, field
from fractions import Fraction
from io import BytesIO
from math import ceil
from pathlib import Path

import freetype as ft
from fontTools.ttLib import TTFont

from .gdi import UnsupportedOperation
from .mapping import rounded
from .numeric import float32


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
    advance: int
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
    _glyphs: dict[str, Glyph] = field(default_factory=dict)

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
            self.font.load_glyph(index, target | ft.FT_LOAD_NO_AUTOHINT | ft.FT_LOAD_NO_BITMAP)
            slot = self.font.glyph
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
                (slot.advance.x + 32) // 64
                if self.hinted
                else rounded(self.design_advances[index] * self.advance_scale),
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
        self._sizes = {}

    @classmethod
    def from_path(cls, path, *, index=0):
        return cls(Path(path).read_bytes(), index=index)

    def realize(self, request, scale, *, missing_glyph="error"):
        """Classic compatible-mode realization; natural width follows height."""
        sx, sy = scale
        height = abs(request.height) * sy if request.height else 16
        if request.height > 0:
            # Cell-to-em conversion retains a fractional size for metrics;
            # the outline grid is realized separately at integer ppem.
            height *= Fraction(self.units_per_em, self.ascent + self.descent)
            height = Fraction(int(height * 65536), 65536)
        if request.width and self.average_width <= 0:
            raise UnsupportedOperation("Font has no usable average-width metric")
        width = abs(request.width) * sx * Fraction(self.units_per_em, self.average_width) if request.width else None
        return self.at_size(height, width=width, quality=request.quality, missing_glyph=missing_glyph)

    def at_size(self, size, *, width=None, quality=3, missing_glyph="error"):
        if missing_glyph not in ("error", "notdef"):
            raise ValueError("Missing-glyph policy must be 'error' or 'notdef'")
        if size <= 0:
            raise ValueError("Font pixel size must be positive")
        mask_width = rounded(size) if width is None else width
        width = size if width is None else width
        key = size, width, mask_width, quality, missing_glyph
        if key not in self._sizes:
            # Bound the cache independently of the number of WMF font objects.
            if len(self._sizes) >= 32:
                self._sizes.pop(next(iter(self._sizes)))
            font = ft.Face.from_bytes(self.data, index=self.index)
            # Glyph IDs come from the selected cmap; FreeType only rasterizes.
            font.set_char_size(max(1, int(mask_width * 64)), max(1, rounded(size) * 64), 72, 72)

            def metric(units):
                return (units * size * 2 + self.units_per_em) // (2 * self.units_per_em)

            self._sizes[key] = RasterFont(
                font,
                metric(self.ascent),
                metric(self.descent),
                self.hinted,
                self.design_advances,
                float32(width / self.units_per_em),
                quality,
                self.break_character,
                self.cmap,
                self.symbol,
                missing_glyph,
            )
        return self._sizes[key]


class FontCollection:
    """Supplied faces and explicit aliases; never discover or silently replace."""

    def __init__(self, faces=(), *, ansi_codepage=1252, aliases=None, missing_glyph="error"):
        if ansi_codepage not in (1252, 1251):
            raise ValueError("ANSI environment must be Windows-1252 or Windows-1251")
        if missing_glyph not in ("error", "notdef"):
            raise ValueError("Missing-glyph policy must be 'error' or 'notdef'")
        self.ansi_codepage = ansi_codepage
        self.missing_glyph = missing_glyph
        self.aliases = {name.casefold(): target.casefold() for name, target in (aliases or {}).items()}
        self._faces = {}
        for face in faces:
            key = (face.family.casefold(), face.weight, face.italic)
            if key in self._faces:
                raise ValueError(f"Ambiguous font face: {face.family}")
            self._faces[key] = face

    def resolve(self, request):
        if request is None:
            raise UnsupportedOperation("Default font resolution")
        family = decode_single_byte(request.face_name.split(b"\0", 1)[0], self.ansi_codepage).casefold()
        family = self.aliases.get(family, family)
        key = family, request.weight or 400, bool(request.italic)
        try:
            return self._faces[key]
        except KeyError as error:
            raise UnsupportedOperation(
                f"Font face unavailable: {family!r}, weight={key[1]}, italic={key[2]}"
            ) from error

    def decode(self, request, face, data):
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
class TextLayout:
    glyphs: tuple[tuple[int, int, Glyph], ...] = ()
    background: tuple[int, int, int, int] | None = None
    position: tuple[int | Fraction, int | Fraction] | None = None


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
):
    """Place independently realized glyphs; explicit advances replace metrics."""
    if characters is None:
        characters = decode_single_byte(text, 1252)
    if len(characters) != len(text):
        raise UnsupportedOperation("Multibyte text layout is not implemented")
    horizontal, vertical = alignment & 6, alignment & 24
    if alignment & ~31 or horizontal not in (0, 2, 6) or vertical not in (0, 8, 24):
        raise UnsupportedOperation("Text alignment")
    if advances and len(advances) != len(text):
        raise ValueError("Text advance count must match the byte count")
    glyphs = tuple(font.glyph(character, max_pixels) for character in characters)
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
            if ord(characters[index]) == getattr(font, "break_character", 32):
                total += break_step
            # The accumulated device advance uses nearest-even ties before
            # conversion to logical coordinates, whose rounding is distinct.
            device_offset = round(Fraction(total, 65536))
            mapped_offsets.append(rounded(device_offset / scale) * scale)
        offsets.append(rounded(mapped_offsets[-1]))
    run_width = total * scale if advances else rounded((total // 65536) / scale) * scale
    width = rounded(run_width)
    # Monochrome GDI places cached glyphs at integer origins. Centering an
    # odd-width run chooses the lower coordinate, not a fractional mask phase.
    origin_x = x - (width if horizontal == 2 else (width + 1) // 2 if horizontal == 6 else 0)
    baseline = y + (font.ascent if vertical == 0 else -font.descent if vertical == 8 else 0)
    position = (x + (run_width if horizontal == 0 else -run_width), y) if alignment & 1 and horizontal != 6 else None
    positioned = []
    for glyph, offset in zip(glyphs, offsets[:-1], strict=True):
        positioned.append((origin_x + offset + glyph.bearing[0], baseline + glyph.bearing[1], glyph))
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
    background = (origin_x, baseline - font.ascent, right, baseline + font.descent) if opaque else None
    return TextLayout(tuple(positioned), background, position)
