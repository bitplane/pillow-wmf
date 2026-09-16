"""Solid GDI strokes: realized polygonal pens and cosmetic grid lines.

The pen is realized once from the mapping. Every wide segment then uses the
same support-vertex sweep, independent of its slope or the mapping scale.
Native measurement details and limitations are in docs/gdi-strokes.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import ceil, floor, sqrt

from .geometry import Point, Polygon, flatten_cubic

_CIRCLE_CONTROL = 4 * (sqrt(2) - 1) / 3

# Native circular pen silhouettes, in half-pixel units. Only one half is
# stored; each opposite vertex is its exact negation. These are pen shapes,
# shared by all slopes and primitives, not raster masks stamped along a line.
_SMALL_PENS = {
    1: ((1, 0), (0, -1)),
    2: ((2, 0), (1, -2), (-1, -2)),
    3: ((3, -1), (1, -3), (-1, -3), (-3, -1)),
    4: ((4, -1), (3, -3), (1, -4), (-1, -4), (-3, -3), (-4, -1)),
    5: ((5, -1), (4, -3), (3, -4), (1, -5), (-1, -5), (-3, -4), (-4, -3), (-5, -1)),
    6: ((6, -1), (5, -3), (3, -5), (1, -6), (-1, -6), (-3, -5), (-5, -3), (-6, -1)),
}


@dataclass(frozen=True)
class PenGeometry:
    vertices: tuple[Point, ...]
    cosmetic: bool


def realize_pen(width: int, scale_x=1, scale_y=1) -> PenGeometry:
    """Realize CreatePen width in device space, including the hairline rule."""
    device_width = floor(width * abs(scale_x) + 0.5)
    cosmetic = device_width <= 1
    if cosmetic or (abs(scale_x) == abs(scale_y) and device_width <= 6):
        half = [(x * 8, y * 8) for x, y in _SMALL_PENS[max(1, device_width)]]
    else:
        # Preserve the orientation of the first transformed basis vector.
        # The other radius has that same sign so the contour stays CCW.
        sign = 1 if scale_x >= 0 else -1
        rx = sign * ceil(width * abs(scale_x) * 8)
        ry = sign * ceil(width * abs(scale_y) * 8)
        cx, cy = ceil(rx * _CIRCLE_CONTROL), floor(ry * _CIRCLE_CONTROL)
        half = [(rx, 0)]
        half += flatten_cubic(((rx, 0), (rx, -cy), (cx, -ry), (0, -ry)))
        half += flatten_cubic(((0, -ry), (-cx, -ry), (-rx, -cy), (-rx, 0)))
        half.pop()
    return PenGeometry(tuple(half + [(-x, -y) for x, y in half]), cosmetic)


def _support_index(pen: PenGeometry, dx: int, dy: int) -> int:
    if dx == dy == 0:
        dx = 1
    vertices = pen.vertices
    half = len(vertices) // 2

    def support(index):
        x, y = vertices[index]
        # Native diamond and hexagonal pen contours resolve equal support
        # in Y; the other contours resolve it in X. The choice matters
        # because support vertices are subsequently rounded to half pixels.
        tie = (y, x) if half <= 3 else (x, y)
        return (x * dy - y * dx, *tie)

    return max(range(len(vertices)), key=support)


def _body(value):
    return (1 if value >= 0 else -1) * ((abs(value) + 4) // 8) * 8


def _cap(value):
    return value - (1 if value > 0 else -1 if value < 0 else 0)


def widen_segment(start: Point, end: Point, pen: PenGeometry) -> Polygon:
    """Sweep a round-ended pen along one segment, all in 28.4 coordinates."""
    vertices = pen.vertices
    half = len(vertices) // 2
    index = _support_index(pen, end[0] - start[0], end[1] - start[1])

    outline = []
    for origin in (start, end):
        for offset in range(half + 1):
            x, y = vertices[(index + offset) % len(vertices)]
            quantize = _body if offset in (0, half) else _cap
            outline.append((origin[0] + quantize(x), origin[1] + quantize(y)))
        index = (index + half) % len(vertices)
    return outline


def join_outline(before: Point, vertex: Point, after: Point, pen: PenGeometry, *, miter=False) -> Polygon:
    """Cover the exterior turn between two incident stroke bodies."""
    dx1, dy1 = vertex[0] - before[0], vertex[1] - before[1]
    dx2, dy2 = after[0] - vertex[0], after[1] - vertex[1]
    turn = dx1 * dy2 - dy1 * dx2
    if not turn:
        return []
    vertices = pen.vertices
    count = len(vertices)
    i = (_support_index(pen, dx1, dy1) + (count // 2 if turn < 0 else 0)) % count
    j = (_support_index(pen, dx2, dy2) + (count // 2 if turn < 0 else 0)) % count
    start = tuple(vertex[axis] + _body(vertices[i][axis]) for axis in (0, 1))
    end = tuple(vertex[axis] + _body(vertices[j][axis]) for axis in (0, 1))
    outline = [vertex, start]
    if miter:
        t = Fraction((end[0] - start[0]) * dy2 - (end[1] - start[1]) * dx2, turn)
        outline.append((start[0] + dx1 * t, start[1] + dy1 * t))
    else:
        step = 1 if turn < 0 else -1
        while i != j:
            i = (i + step) % count
            if i != j:
                outline.append((vertex[0] + _cap(vertices[i][0]), vertex[1] + _cap(vertices[i][1])))
    outline.append(end)
    return outline


def line_outline(start: Point, end: Point, width: int, scale_x, scale_y) -> Polygon:
    """Device-integer convenience entry point for diagnostic path probes."""
    return widen_segment(
        (start[0] * 16, start[1] * 16), (end[0] * 16, end[1] * 16), realize_pen(width, scale_x, scale_y)
    )


def cosmetic_line(start: Point, end: Point, width: int, height: int):
    """GIQ coverage for a 28.4 segment, including fractional curve vertices.

    Choose the closest minor-coordinate pixel at each major grid intersection
    (ties to the smaller coordinate). A pixel is emitted when the segment exits
    its half-pixel diamond. A shared vertex belongs to the following segment.
    Bounds restrict grid enumeration without changing the original line.
    """
    dx, dy = end[0] - start[0], end[1] - start[1]
    if dx == dy == 0:
        return
    transpose = abs(dy) > abs(dx)
    major, minor = (1, 0) if transpose else (0, 1)
    a, b = start[major], end[major]
    delta = b - a
    extent = height if transpose else width
    for value in range(max(0, min(a, b) // 16 - 1), min(extent, max(a, b) // 16 + 2)):
        numerator = start[minor] * delta + (value * 16 - a) * (end[minor] - start[minor])
        other = ceil(Fraction(numerator, delta * 16) - Fraction(1, 2))
        x, y = (other, value) if transpose else (value, other)
        if not (0 <= x < width and 0 <= y < height):
            continue
        enter, leave = None, None
        # Transform the diamond into an axis-aligned square with u=x+y, v=x-y.
        for origin, change, center in (
            (start[0] + start[1], dx + dy, (x + y) * 16),
            (start[0] - start[1], dx - dy, (x - y) * 16),
        ):
            if not change:
                if not center - 8 <= origin <= center + 8:
                    break
                continue
            lower, upper = sorted((Fraction(center - 8 - origin, change), Fraction(center + 8 - origin, change)))
            enter = lower if enter is None else max(enter, lower)
            leave = upper if leave is None else min(leave, upper)
        else:
            if enter <= leave and 0 <= leave < 1:
                yield x, y
