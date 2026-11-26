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

    def _device_matrix(self):
        """The matrix glyph outlines are realized through.

        A scale-only transform realizes the font at a whole pixel em height,
        keeping its horizontal scale; others use the exact matrix.
        """
        a, b, c, d = self.matrix
        if b or c or not d:
            return self.matrix
        em = abs(Fraction(d)) * self.units_per_em
        whole = int(em + Fraction(1, 2))
        return (a, b, c, d * whole / em) if whole else self.matrix

    def _render(self, index, max_pixels):
        if self.quality == 3:
            return self._scan(index, max_pixels)
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

    def _scan(self, index, max_pixels):
        """A monochrome mask by the native TrueType scan rules; see ``scan_outline``."""
        face = self._ft_face()
        if not 0 <= index < face.num_glyphs:
            index = 0
        try:
            face.load_glyph(index, ft.FT_LOAD_NO_SCALE | ft.FT_LOAD_NO_BITMAP)
        except ft.FT_Exception as error:
            raise UnsupportedOperation(f"Cannot realize glyph {index}: {error}") from error
        outline = face.glyph.outline
        a, b, c, d = self._device_matrix()

        def device(point):
            # Each product is rounded to 26.6 before the sum, as fixed-point
            # multiplication does.
            u, v = point
            return (
                _round_half_away(64 * a * u) + _round_half_away(64 * b * v),
                _round_half_away(64 * c * u) + _round_half_away(64 * d * v),
            )

        contours = [[device(point) for point in contour] for contour in _contours(outline)]
        # A mirroring transform reverses the outline's orientation.
        closed = Fraction(a) * Fraction(d) - Fraction(b) * Fraction(c) < 0
        pixels = scan_outline(contours, closed=closed)
        if not pixels:
            return Glyph((0, 0), (0, 0), b"", 0, index, 1)
        xs, ys = [x for x, _ in pixels], [y for _, y in pixels]
        left, top, width, height = min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        if width * height > max_pixels:
            raise ResourceLimitError("Glyph pixel limit exceeded")
        mask = bytearray(width * height)
        for x, y in pixels:
            mask[(y - top) * width + x - left] = 255
        return Glyph((width, height), (left, top), bytes(mask), 0, index, 1)

    def advance(self, index: int) -> tuple[int, int]:
        """The glyph's device advance vector in 28.4 units scaled by 2^32.

        Advances are whole pixels. A scale-only transform scales the design
        width by its 16.16 pixels per unit and rounds; others round the width
        at the whole pixels per em of the transformed x axis, half up, and
        lay it along that axis.
        """
        a, b, c, d = self._device_matrix()
        units = self.design_advances.get(index, 0)
        if not b and not c:
            scale = Fraction(_round_half_away(abs(Fraction(a)) * 65536), 65536)
            pixels = _round_half_away(units * scale)
            return ((pixels if a >= 0 else -pixels) * 16 << 32, 0)
        length = sqrt(float(a) ** 2 + float(c) ** 2)
        em = int(length * self.units_per_em + 0.5)
        pixels = int(Fraction(units * em, self.units_per_em) + Fraction(1, 2))
        return tuple(_round_half_away(Fraction(pixels * value / length) * 16 * (1 << 32)) for value in (a, c))

    def vertical(self, units: int) -> tuple[int, int]:
        """A notional vertical offset as a 28.4 device vector.

        A scale-only transform takes whole pixels at its 16.16 vertical scale.
        """
        a, b, c, d = self._device_matrix()
        if not b and not c:
            scale = Fraction(_round_half_away(abs(Fraction(d)) * 65536), 65536)
            pixels = _round_half_away(abs(units) * scale)
            return (0, pixels * 16 if (d < 0) == (units < 0) else -pixels * 16)
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
        sx = sy = 0
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


def _contours(outline):
    """Contours of notional points, with quadratic arcs approximated by eight lines each."""
    points, tags, ends = outline.points, outline.tags, outline.contours
    start = 0
    for end in ends:
        raw = [(points[i], tags[i] & 1) for i in range(start, end + 1)]
        start = end + 1
        if not raw:
            continue
        # Begin at an on-curve point, inserting implied midpoints between offs.
        expanded = []
        for i, (point, on) in enumerate(raw):
            previous, previous_on = raw[i - 1]
            if not on and not previous_on:
                expanded.append((((point[0] + previous[0]) / 2, (point[1] + previous[1]) / 2), 1))
            expanded.append((point, on))
        first = next((i for i, (_, on) in enumerate(expanded) if on), None)
        if first is None:
            continue
        expanded = expanded[first:] + expanded[:first]
        contour = []
        for i, (point, on) in enumerate(expanded):
            if on:
                contour.append(point)
                continue
            p0, p2 = expanded[i - 1][0], expanded[(i + 1) % len(expanded)][0]
            for step in range(1, 8):
                t = step / 8
                contour.append(tuple((1 - t) ** 2 * p0[k] + 2 * (1 - t) * t * point[k] + t * t * p2[k] for k in (0, 1)))
        yield contour


def _on_segment(p, q, x, y):
    (x0, y0), (x1, y1) = p, q
    if (x1 - x0) * (y - y0) != (y1 - y0) * (x - x0):
        return False
    return min(x0, x1) <= x <= max(x0, x1) and min(y0, y1) <= y <= max(y0, y1)


def _crossings(segments, value, axis):
    """Where segments cross the line ``axis == value``, with their winding directions."""
    other = 1 - axis
    found = []
    for p, q in segments:
        if p[axis] == q[axis]:
            continue
        low, high = sorted((p[axis], q[axis]))
        if low <= value < high:
            position = p[other] + Fraction(value - p[axis]) * (q[other] - p[other]) / (q[axis] - p[axis])
            found.append((position, 1 if q[axis] > p[axis] else -1))
    return found


def _spans(crossings):
    out, winding, start = [], 0, None
    for position, direction in sorted(crossings):
        before = winding
        winding += direction
        if not before and winding:
            start = position
        elif before and not winding:
            out.append((start, position))
    return out


def scan_outline(contours, *, closed):
    """Pixels a TrueType outline of 26.6 device points covers, y down.

    A pixel is covered when its centre lies inside the outline by the nonzero
    rule. A centre exactly on the outline is covered when ``closed`` (the
    font's own orientation) and not when the outline is mirrored. Smart
    dropout control then fills, along every row and column centre line, each
    stretch of interior that holds no pixel centre, at the pixel nearest its
    middle.
    """
    segments = [(p, q) for contour in contours for p, q in zip(contour, contour[1:] + contour[:1], strict=True)]
    if not segments:
        return set()
    xs = [p[0] for p, _ in segments]
    ys = [p[1] for p, _ in segments]
    columns = range(min(xs) // 64 - 1, max(xs) // 64 + 2)
    rows = range(min(ys) // 64 - 1, max(ys) // 64 + 2)
    covered = set()
    for row in rows:
        centre_y = 64 * row + 32
        crossings = _crossings(segments, centre_y, 1)
        for column in columns:
            centre_x = 64 * column + 32
            if any(_on_segment(p, q, centre_x, centre_y) for p, q in segments):
                if closed:
                    covered.add((column, row))
            elif sum(direction for position, direction in crossings if position < centre_x):
                covered.add((column, row))
    for row in rows:
        for start, end in _dropout_spans(contours, segments, 64 * row + 32, 1):
            first = -((32 - start) // 64)  # the first pixel whose centre is at or after the start
            if first * 64 + 32 > end:
                covered.add((first - 1, row))  # the pixel to the left
    for column in columns:
        for start, end in _dropout_spans(contours, segments, 64 * column + 32, 0):
            first = -((32 - start) // 64)
            if first * 64 + 32 > end:
                covered.add((column, first))  # the pixel below
    return covered


def _dropout_spans(contours, segments, value, axis):
    """Interior stretches along a centre line, with vertices that only touch it as empty stretches."""
    found = _spans(_crossings(segments, value, axis))
    other = 1 - axis
    for contour in contours:
        for index, point in enumerate(contour):
            if point[axis] != value:
                continue
            before, after = contour[index - 1][axis], contour[(index + 1) % len(contour)][axis]
            if (before - value) * (after - value) > 0:
                found.append((point[other], point[other]))
    return found
