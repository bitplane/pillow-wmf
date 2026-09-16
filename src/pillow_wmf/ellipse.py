"""Fixed-point ellipse paths and one-device-pixel path widening.

Coordinates are in sixteenths of a device pixel.  The path is retained at
that precision through flattening and scan conversion; rounding its vertices
to ``POINT`` coordinates changes which boundary pixels GDI owns.
"""

from __future__ import annotations

from math import ceil, floor, sqrt

type Point = tuple[int, int]
type Polygon = list[Point]

_SCALE = 16
_HALF_PIXEL = _SCALE // 2
_CUBIC_CIRCLE_CONTROL = 4 * (sqrt(2) - 1) / 3


def _flatten_cubic(control: tuple[Point, Point, Point, Point]) -> Polygon:
    points: Polygon = []

    def recurse(curve: tuple[tuple[float, float], ...]) -> None:
        deviation = max(
            abs(curve[index][axis] - 2 * curve[index + 1][axis] + curve[index + 2][axis])
            for index in (0, 1)
            for axis in (0, 1)
        )
        if deviation <= 10:
            points.append((floor(curve[3][0] + 0.5), floor(curve[3][1] + 0.5)))
            return

        p0, p1, p2, p3 = curve
        a = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
        b = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
        c = ((p2[0] + p3[0]) / 2, (p2[1] + p3[1]) / 2)
        d = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        e = ((b[0] + c[0]) / 2, (b[1] + c[1]) / 2)
        middle = ((d[0] + e[0]) / 2, (d[1] + e[1]) / 2)
        recurse((p0, a, d, middle))
        recurse((middle, e, c, p3))

    recurse(tuple((float(x), float(y)) for x, y in control))
    return points


def ellipse_path(left: int, top: int, right: int, bottom: int) -> Polygon:
    """Flatten the four GDI-style cubic arcs of an exclusive-bound ellipse."""
    left_fixed, top_fixed = left * _SCALE, top * _SCALE
    right_fixed, bottom_fixed = (right - 1) * _SCALE, (bottom - 1) * _SCALE
    cx, cy = (left_fixed + right_fixed) // 2, (top_fixed + bottom_fixed) // 2
    rx, ry = (right_fixed - left_fixed) // 2, (bottom_fixed - top_fixed) // 2
    horizontal_control = ceil(_CUBIC_CIRCLE_CONTROL * rx)
    vertical_control = floor(_CUBIC_CIRCLE_CONTROL * ry)
    arcs = (
        (
            (right_fixed, cy),
            (right_fixed, cy - vertical_control),
            (cx + horizontal_control, top_fixed),
            (cx, top_fixed),
        ),
        ((cx, top_fixed), (cx - horizontal_control, top_fixed), (left_fixed, cy - vertical_control), (left_fixed, cy)),
        (
            (left_fixed, cy),
            (left_fixed, cy + vertical_control),
            (cx - horizontal_control, bottom_fixed),
            (cx, bottom_fixed),
        ),
        (
            (cx, bottom_fixed),
            (cx + horizontal_control, bottom_fixed),
            (right_fixed, cy + vertical_control),
            (right_fixed, cy),
        ),
    )
    vertices = [arcs[0][0]]
    for arc in arcs:
        vertices.extend(_flatten_cubic(arc))
    return vertices[:-1]


def widen_pixel_path(path: Polygon) -> tuple[Polygon, Polygon]:
    """Return exterior and interior contours of a closed one-pixel stroke."""
    offsets: Polygon = []
    for start, end in zip(path, path[1:] + path[:1]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        if abs(dx) >= abs(dy):
            offsets.append((0, _HALF_PIXEL if dx > 0 else -_HALF_PIXEL))
        else:
            offsets.append((_HALF_PIXEL if dy < 0 else -_HALF_PIXEL, 0))

    exterior: Polygon = []
    interior: Polygon = []
    for index, (x, y) in enumerate(path):
        before, after = offsets[index - 1], offsets[index]
        if before == after:
            exterior.append((x + after[0], y + after[1]))
            interior.append((x - after[0], y - after[1]))
        else:
            exterior.extend(((x + before[0], y + before[1]), (x + after[0], y + after[1])))
            interior.append((x - before[0], y - before[1]))
            interior.append((x - after[0], y - after[1]))
    interior.reverse()
    return exterior, interior


def contains(polygons: tuple[Polygon, ...], x: int, y: int) -> bool:
    """Evaluate an even-odd fixed-point path at a device-pixel coordinate."""
    px, py = x * _SCALE, y * _SCALE
    enclosed = False
    for polygon in polygons:
        for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
            if (y1 > py) == (y2 > py):
                continue
            cross = (px - x1) * (y2 - y1) - (py - y1) * (x2 - x1)
            if (cross < 0) if y2 > y1 else (cross > 0):
                enclosed = not enclosed
    return enclosed
