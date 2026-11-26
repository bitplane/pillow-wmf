"""Text under general GM_ADVANCED transforms: transformed glyphs and native placement.

A run is realized from the font's notional outlines through one matrix that
takes notional units to device pixels: the logical em size, the glyph
orientation and the world-to-device transform together. Glyph origins are
placed in 28.4 device units as native general-transform placement does:

- without explicit advances, each glyph's advance vector is the notional
  advance through the matrix, in 32.32 fixed point; the vectors accumulate
  from one half, and each origin takes the accumulator's whole part;
- with explicit advances, the running logical sum is scaled to 28.4 along
  the baseline in single precision and rounded, then multiplied by the
  unit baseline vector and rounded again, both half away from zero.

The vertical alignment moves the origin by the ascent or descent vector, the
horizontal alignment by the whole or half total advance (halved toward zero),
and each origin then rounds to a pixel, ``(p + 8) >> 4``.
"""

from ctypes import byref
from dataclasses import dataclass, field
from fractions import Fraction
from math import sqrt
from threading import Lock

import freetype as ft

from .binary import ResourceLimitError
from .font import _FREETYPE, Glyph, _Face, _unpack_bitmap
from .gdi import UnsupportedOperation
from .numeric import float32


def _round_half_away(value) -> int:
    magnitude = int(abs(value) + Fraction(1, 2)) if isinstance(value, Fraction) else int(abs(value) + 0.5)
    return magnitude if value >= 0 else -magnitude


@dataclass
class TransformedFont:
    """A face realized through a notional-to-device matrix.

    ``matrix`` is (a, b, c, d): a notional point (u, v), y up, lands at
    device (a u + b v, c u + d v), y down, in pixels.
    """

    data: bytes
    index: int
    matrix: tuple
    units_per_em: int
    ascent: int
    descent: int
    design_advances: dict
    quality: int = 3
    _glyphs: dict = field(default_factory=dict, repr=False)
    _lock: Lock = field(default_factory=Lock, repr=False, compare=False)
    _face: object = field(default=None, repr=False)

    def _ft_face(self):
        if self._face is None:
            with _FREETYPE:
                self._face = _Face.from_bytes(self.data, index=self.index)
        return self._face

    def glyph(self, index: int, max_pixels: int) -> Glyph:
        with self._lock:
            glyph = self._glyphs.get(index)
            if glyph is None:
                glyph = self._glyphs[index] = self._render(index, max_pixels)
        if glyph.size[0] * glyph.size[1] > max_pixels:
            raise ResourceLimitError("Glyph pixel limit exceeded")
        return glyph

    def _render(self, index, max_pixels):
        face = self._ft_face()
        if not 0 <= index < face.num_glyphs:
            index = 0
        try:
            face.load_glyph(index, ft.FT_LOAD_NO_SCALE | ft.FT_LOAD_NO_BITMAP)
            slot = face.glyph
            a, b, c, d = self.matrix
            # Notional units become 26.6 device units; FreeType's y is up.
            matrix = ft.Matrix(*(_round_half_away(Fraction(value) * 64 * 65536) for value in (a, b, -c, -d)))
            ft.FT_Outline_Transform(byref(slot.outline._FT_Outline), byref(matrix))
            bounds = slot.get_glyph().get_cbox(ft.FT_GLYPH_BBOX_PIXELS)
            padding = 0 if self.quality in (3, 4) else 2
            if (max(1, bounds.xMax - bounds.xMin) + padding) * max(1, bounds.yMax - bounds.yMin) > max_pixels:
                raise ResourceLimitError("Glyph pixel limit exceeded")
            slot.render(
                {3: ft.FT_RENDER_MODE_MONO, 4: ft.FT_RENDER_MODE_NORMAL}.get(self.quality, ft.FT_RENDER_MODE_LCD)
            )
        except ft.FT_Exception as error:
            raise UnsupportedOperation(f"Cannot realize glyph {index}: {error}") from error
        bitmap = slot.bitmap
        channels = 1 if self.quality in (3, 4) else 3
        pixels = _unpack_bitmap(bitmap, mono=self.quality == 3)
        return Glyph(
            (bitmap.width // channels, bitmap.rows),
            (slot.bitmap_left, -slot.bitmap_top),
            pixels,
            0,
            index,
            channels,
        )

    def advance(self, index: int) -> tuple[int, int]:
        """The glyph's device advance vector in 28.4 units scaled by 2^32."""
        a, _, c, _ = self.matrix
        units = self.design_advances.get(index, 0)
        return tuple(_round_half_away(Fraction(value) * units * 16 * (1 << 32)) for value in (a, c))

    def vertical(self, units: int) -> tuple[int, int]:
        """A notional vertical offset as a 28.4 device vector."""
        _, b, _, d = self.matrix
        return tuple(_round_half_away(Fraction(value) * units * 16) for value in (b, d))


@dataclass(frozen=True)
class TransformedRun:
    """Glyph pixel origins and the 28.4 total advance of a placed run."""

    glyphs: tuple
    advance: tuple[int, int]


def place_run(font: TransformedFont, indices, origin, alignment, *, advances=(), baseline=None, max_pixels):
    """Place glyphs by native general-transform placement; ``origin`` is 28.4.

    ``baseline`` gives, for explicit advances, the unit baseline vector and
    the logical-to-28.4 scale along it.
    """
    horizontal, vertical = alignment & 6, alignment & 24
    origin_x, origin_y = origin
    if vertical == 0:
        up = font.vertical(font.ascent)
        origin_x, origin_y = origin_x - up[0], origin_y - up[1]
    elif vertical == 8:
        down = font.vertical(-font.descent)
        origin_x, origin_y = origin_x - down[0], origin_y - down[1]
    positions = [(0, 0)]
    if advances:
        ux, uy, scale = baseline
        total = 0
        for value in advances:
            total += value
            along = _round_half_away(float32(float32(total) * float32(scale)))
            positions.append(
                (_round_half_away(float32(ux * float32(along))), _round_half_away(float32(uy * float32(along))))
            )
    else:
        sx = sy = 1 << 31
        for index in indices:
            dx, dy = font.advance(index)
            sx, sy = sx + dx, sy + dy
            positions.append((sx >> 32, sy >> 32))
    total = positions.pop()
    if horizontal == 2:
        shift = total
    elif horizontal == 6:
        shift = tuple(int(value / 2) for value in total)
    else:
        shift = (0, 0)
    glyphs = []
    for index, (px, py) in zip(indices, positions, strict=True):
        glyph = font.glyph(index, max_pixels)
        x = (origin_x + px - shift[0] + 8) >> 4
        y = (origin_y + py - shift[1] + 8) >> 4
        glyphs.append((x + glyph.bearing[0], y + glyph.bearing[1], glyph))
    return TransformedRun(tuple(glyphs), total)


def baseline_vector(matrix, world_baseline):
    """The unit device baseline and the logical-to-28.4 scale along it, in single precision."""
    a, _, c, _ = matrix
    length = float32(sqrt(float32(float32(a) * float32(a)) + float32(float32(c) * float32(c))))
    ux, uy = float32(float32(a) / length), float32(float32(c) / length)
    wx, wy = world_baseline
    scale = float32(float32(sqrt(float32(float32(wx * wx) + float32(wy * wy)))) * 16)
    return ux, uy, scale
