"""Construct the exclusive-bound ellipse as a fixed-point device path."""

from itertools import pairwise
from math import atan2, ceil, cos, floor, pi, sin, sqrt

from .geometry import Point, Polygon, flatten_cubic

_SCALE = 16
_CUBIC_CIRCLE_CONTROL = 4 * (sqrt(2) - 1) / 3


def ellipse_cubics(left: int, top: int, right: int, bottom: int) -> tuple[tuple[Point, Point, Point, Point], ...]:
    """The four counterclockwise GDI-style cubics of an exclusive-bound ellipse."""
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
    return arcs


def ellipse_path(left: int, top: int, right: int, bottom: int) -> Polygon:
    """Flatten the four GDI-style cubic arcs of an exclusive-bound ellipse."""
    arcs = ellipse_cubics(left, top, right, bottom)
    vertices = [arcs[0][0]]
    for arc in arcs:
        vertices.extend(flatten_cubic(arc))
    return vertices[:-1]


def arc_path(
    left: int,
    top: int,
    right: int,
    bottom: int,
    start: tuple[int, int],
    end: tuple[int, int],
) -> Polygon:
    """Cut an exclusive-bound ellipse at two radial directions.

    Normalize radials in the inclusive device box, then construct cubics in
    the exclusive-bound drawing box. WMF stores points on the radials, not
    points required to lie on the ellipse.
    """
    if start == end:
        return ellipse_path(left, top, right, bottom)
    cx = (left + right - 1) / 2
    cy = (top + bottom - 1) / 2
    rx = (right - left - 1) / 2
    ry = (bottom - top - 1) / 2
    radial_cx = (left + right) / 2
    radial_cy = (top + bottom) / 2
    radial_rx = (right - left) / 2
    radial_ry = (bottom - top) / 2

    def angle(point: tuple[int, int]) -> float:
        value = atan2((radial_cy - point[1]) / radial_ry, (point[0] - radial_cx) / radial_rx)
        return value if value >= 0 else value + 2 * pi

    first, last = angle(start), angle(end)
    if last <= first:
        last += 2 * pi
    boundaries = [first]
    for quadrant in range(1, 8):
        boundary = quadrant * pi / 2
        if first < boundary < last:
            boundaries.append(boundary)
    boundaries.append(last)

    def device_point(nx: float, ny: float) -> tuple[float, float]:
        return (cx + rx * nx) * 16, (cy + ry * ny) * 16

    path = []
    whole_quadrants = ellipse_cubics(left, top, right, bottom)
    for a, b in pairwise(boundaries):
        if abs(a / (pi / 2) - round(a / (pi / 2))) < 1e-12 and abs(b - a - pi / 2) < 1e-12:
            cubic = whole_quadrants[round(a / (pi / 2)) % 4]
        else:
            half = (b - a) / 2
            factor = 4 / 3 * (1 - cos(half)) / sin(half)
            cubic = (
                device_point(cos(a), -sin(a)),
                device_point(cos(a) - factor * sin(a), -sin(a) - factor * cos(a)),
                device_point(cos(b) + factor * sin(b), -sin(b) + factor * cos(b)),
                device_point(cos(b), -sin(b)),
            )
            # GDI keeps the generated controls in 28.4 fixed point before
            # flattening. Rounding only the emitted vertices shifts the curve.
            cubic = tuple(tuple(round(value) for value in point) for point in cubic)
        if not path:
            path.append(tuple(round(value) for value in cubic[0]))
        path.extend(flatten_cubic(cubic))
    return path
