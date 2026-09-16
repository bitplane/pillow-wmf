"""Construct the exclusive-bound ellipse as a fixed-point device path."""

from itertools import pairwise
from math import atan2, ceil, cos, floor, pi, sin, sqrt
from struct import pack, unpack

from .geometry import Point, Polygon, flatten_cubic

_SCALE = 16
_CUBIC_CIRCLE_CONTROL = 4 * (sqrt(2) - 1) / 3
# FLOAT pi in the degree conversion reproduces native quadrant ownership at
# cardinal radials. Do not snap the resulting angles to multiples of 90.
# This precision model is inferred from GetPath; see docs/gdi-arcs.md.
_FLOAT_PI = unpack("<f", pack("<f", pi))[0]


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


def arc_cubics(
    left: int,
    top: int,
    right: int,
    bottom: int,
    start: tuple[int, int],
    end: tuple[int, int],
) -> tuple[tuple[Point, Point, Point, Point], ...]:
    """Cut an exclusive-bound ellipse at two radial directions.

    Normalize radials in the inclusive device box, then construct cubics in
    the exclusive-bound drawing box. WMF stores points on the radials, not
    points required to lie on the ellipse.
    """
    if start == end:
        return ellipse_cubics(left, top, right, bottom)
    cx = (left + right - 1) / 2
    cy = (top + bottom - 1) / 2
    rx = (right - left - 1) / 2
    ry = (bottom - top - 1) / 2
    radial_cx = (left + right) / 2
    radial_cy = (top + bottom) / 2
    radial_rx = (right - left) / 2
    radial_ry = (bottom - top) / 2

    def angle(point: tuple[int, int]) -> float:
        value = atan2((radial_cy - point[1]) / radial_ry, (point[0] - radial_cx) / radial_rx) * 180 / _FLOAT_PI
        return value if value >= 0 else value + 360

    first, last = angle(start), angle(end)
    if last <= first:
        last += 360
    boundaries = [first]
    for quadrant in range(1, 8):
        boundary = quadrant * 90
        if first < boundary < last:
            boundaries.append(boundary)
    boundaries.append(last)

    def device_point(nx: float, ny: float) -> tuple[float, float]:
        return (cx + rx * nx) * 16, (cy + ry * ny) * 16

    cubics = []
    quadrants = ellipse_cubics(left, top, right, bottom)
    for index, (a, b) in enumerate(pairwise(boundaries)):
        if 0 < index < len(boundaries) - 2:
            cubics.append(quadrants[round(a / 90) % 4])
            continue
        a, b = a * pi / 180, b * pi / 180
        half = (b - a) / 2
        factor = 4 / 3 * (1 - cos(half)) / sin(half)
        cubic = (
            device_point(cos(a), -sin(a)),
            device_point(cos(a) - factor * sin(a), -sin(a) - factor * cos(a)),
            device_point(cos(b) + factor * sin(b), -sin(b) + factor * cos(b)),
            device_point(cos(b), -sin(b)),
        )
        # Quantize terminal-piece controls before flattening. Intermediate
        # quadrants use the ellipse construction, not this trigonometric cut.
        cubic = tuple(tuple(round(value) for value in point) for point in cubic)
        cubics.append(cubic)
    return tuple(cubics)


def arc_path(left: int, top: int, right: int, bottom: int, start: Point, end: Point) -> Polygon:
    """Flatten Arc geometry for cosmetic coverage or path diagnostics."""
    cubics = arc_cubics(left, top, right, bottom, start, end)
    path = [cubics[0][0]]
    for cubic in cubics:
        path.extend(flatten_cubic(cubic))
    return path[:-1] if start == end else path
