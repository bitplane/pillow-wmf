"""Explicit font inputs, monochrome glyph masks and horizontal GDI layout.

This first slice deliberately has no host-font discovery, substitution or
automatic shaping. Font files are supplied by the caller, not by a WMF.
"""

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import freetype as ft
from fontTools.ttLib import TTFont

from .gdi import UnsupportedOperation


@dataclass(frozen=True)
class Glyph:
    size: tuple[int, int]
    bearing: tuple[int, int]
    pixels: bytes
    advance: int
    index: int = 0


@dataclass
class MonochromeFont:
    """Glyph generation is independent of GDI alignment and DC state."""

    font: ft.Face
    ascent: int
    descent: int
    characters: frozenset[int]
    _glyphs: dict[str, Glyph] = field(default_factory=dict)

    def glyph(self, character, max_pixels):
        index = self.font.get_char_index(ord(character))
        if ord(character) not in self.characters or not index:
            raise UnsupportedOperation(f"Missing glyph for U+{ord(character):04X}")
        if character not in self._glyphs:
            # Honour TrueType instructions without inventing auto-hints for
            # unhinted glyphs. Keep bitmap strikes outside this outline slice.
            self.font.load_glyph(index, ft.FT_LOAD_TARGET_MONO | ft.FT_LOAD_NO_AUTOHINT | ft.FT_LOAD_NO_BITMAP)
            slot = self.font.glyph
            bounds = slot.get_glyph().get_cbox(ft.FT_GLYPH_BBOX_PIXELS)
            if max(1, bounds.xMax - bounds.xMin) * max(1, bounds.yMax - bounds.yMin) > max_pixels:
                raise ValueError("Glyph pixel limit exceeded")
            slot.render(ft.FT_RENDER_MODE_MONO)
            bitmap = slot.bitmap
            if bitmap.pixel_mode != ft.FT_PIXEL_MODE_MONO:
                raise UnsupportedOperation("Non-monochrome glyph bitmap")
            packed = bitmap.buffer
            pixels = bytes(
                255 if packed[y * bitmap.pitch + x // 8] & (128 >> (x % 8)) else 0
                for y in range(bitmap.rows)
                for x in range(bitmap.width)
            )
            self._glyphs[character] = Glyph(
                (bitmap.width, bitmap.rows),
                (slot.bitmap_left, -slot.bitmap_top),
                pixels,
                (slot.advance.x + 32) // 64,
                index,
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
            self.characters = frozenset(font.getBestCmap() or ())
        self._sizes = {}

    @classmethod
    def from_path(cls, path, *, index=0):
        return cls(Path(path).read_bytes(), index=index)

    def at_size(self, size):
        if size <= 0:
            raise ValueError("Font pixel size must be positive")
        if size not in self._sizes:
            # Bound the cache independently of the number of WMF font objects.
            if len(self._sizes) >= 32:
                self._sizes.pop(next(iter(self._sizes)))
            font = ft.Face.from_bytes(self.data, index=self.index)
            font.select_charmap(ft.FT_ENCODING_UNICODE)
            font.set_pixel_sizes(0, size)

            def rounded(units):
                return (units * size * 2 + self.units_per_em) // (2 * self.units_per_em)

            self._sizes[size] = MonochromeFont(font, rounded(self.ascent), rounded(self.descent), self.characters)
        return self._sizes[size]


class FontCollection:
    """Exact family/style resolution among supplied faces; never substitute."""

    def __init__(self, faces=()):
        self._faces = {}
        for face in faces:
            key = (face.family.casefold(), face.weight, face.italic)
            if key in self._faces:
                raise ValueError(f"Ambiguous font face: {face.family}")
            self._faces[key] = face

    def resolve(self, request):
        if request is None:
            raise UnsupportedOperation("Default font resolution")
        try:
            family = request.face_name.split(b"\0", 1)[0].decode("ascii").casefold()
        except UnicodeDecodeError as error:
            raise UnsupportedOperation("Non-ASCII font face-name encoding") from error
        key = family, request.weight or 400, bool(request.italic)
        try:
            return self._faces[key]
        except KeyError as error:
            raise UnsupportedOperation(
                f"Font face unavailable: {family!r}, weight={key[1]}, italic={key[2]}"
            ) from error


@dataclass(frozen=True)
class TextLayout:
    glyphs: tuple[tuple[int, int, Glyph], ...] = ()
    background: tuple[int, int, int, int] | None = None
    position: tuple[int, int] | None = None


def layout_text(font, text, x, y, alignment, advances, *, opaque, max_pixels):
    """Place independently realized glyphs; explicit advances replace metrics."""
    if any(byte < 32 or byte > 126 for byte in text):
        raise UnsupportedOperation("Only printable ASCII text is supported")
    horizontal, vertical = alignment & 6, alignment & 24
    if alignment & ~31 or horizontal not in (0, 2, 6) or vertical not in (0, 8, 24):
        raise UnsupportedOperation("Text alignment")
    if alignment & 1 and horizontal != 0:
        raise UnsupportedOperation("Non-left TA_UPDATECP alignment")
    if advances and len(advances) != len(text):
        raise ValueError("Text advance count must match the byte count")
    if any(value < 0 for value in advances):
        raise UnsupportedOperation("Negative text advances")
    glyphs = tuple(font.glyph(chr(byte), max_pixels) for byte in text)
    steps = advances or tuple(glyph.advance for glyph in glyphs)
    width = sum(steps)
    # Monochrome GDI places cached glyphs at integer origins. Centering an
    # odd-width run chooses the lower coordinate, not a fractional mask phase.
    origin_x = x - (width if horizontal == 2 else (width + 1) // 2 if horizontal == 6 else 0)
    baseline = y + (font.ascent if vertical == 0 else -font.descent if vertical == 8 else 0)
    position = (x + width, y) if alignment & 1 else None
    background = (origin_x, baseline - font.ascent, origin_x + width, baseline + font.descent) if opaque else None
    positioned = []
    for glyph, advance in zip(glyphs, steps, strict=True):
        positioned.append((origin_x + glyph.bearing[0], baseline + glyph.bearing[1], glyph))
        origin_x += advance
    return TextLayout(tuple(positioned), background, position)
