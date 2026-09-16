"""Construct the exclusive-bound ellipse as a fixed-point device path."""

from itertools import pairwise
from math import ceil, floor, sqrt
from typing import Literal

from .gdi_math import SHORT_ANGLE, atan2_degrees, sincos_degrees
from .geometry import DevicePath, Point, Polygon, flatten_cubic

_SCALE = 16
_CUBIC_CIRCLE_CONTROL = 4 * (sqrt(2) - 1) / 3


def _ellipse_bounds(left, top, right, bottom, *, null_pen=False):
    # Native compatible-mode paths with PS_NULL move the center by -1/2
    # pixel and reduce each radius by 1/4 pixel. This is path geometry,
    # independent of the pen's requested width or subsequent scan conversion.
    return (
        left * _SCALE - (4 if null_pen else 0),
        top * _SCALE - (4 if null_pen else 0),
        (right - 1) * _SCALE - (12 if null_pen else 0),
        (bottom - 1) * _SCALE - (12 if null_pen else 0),
    )


def ellipse_cubics(
    left: int, top: int, right: int, bottom: int, *, null_pen=False
) -> tuple[tuple[Point, Point, Point, Point], ...]:
    """The four counterclockwise GDI-style cubics of an exclusive-bound ellipse."""
    left_fixed, top_fixed, right_fixed, bottom_fixed = _ellipse_bounds(left, top, right, bottom, null_pen=null_pen)
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
    *,
    null_pen=False,
) -> tuple[tuple[Point, Point, Point, Point], ...]:
    """Cut an exclusive-bound ellipse at two radial directions.

    Normalize radials in the inclusive device box, then construct cubics in
    the exclusive-bound drawing box. WMF stores points on the radials, not
    points required to lie on the ellipse.
    """
    x0, y0, x1, y1 = _ellipse_bounds(left, top, right, bottom, null_pen=null_pen)
    cx, cy = (x0 + x1) / 32, (y0 + y1) / 32
    rx, ry = (x1 - x0) / 32, (y1 - y0) / 32
    radial_cx = (left + right) / 2
    radial_cy = (top + bottom) / 2
    radial_rx = (right - left) / 2
    radial_ry = (bottom - top) / 2

    def angle(point: tuple[int, int]) -> float:
        return atan2_degrees((radial_cy - point[1]) / radial_ry, (point[0] - radial_cx) / radial_rx)

    first, last = angle(start), angle(end)
    # Choose endpoint precision before unwrapping. Nearly coincident angles
    # that compare equal request a full sweep, not the short-angle mode.
    accurate = 0 < abs(last - first) < SHORT_ANGLE
    if last <= first:
        last += 360
    boundaries = [first]
    for quadrant in range(1, 8):
        boundary = quadrant * 90
        if first < boundary <= last:
            boundaries.append(boundary)
    boundaries.append(last)

    def device_point(nx: float, ny: float) -> tuple[float, float]:
        return (cx + rx * nx) * 16, (cy + ry * ny) * 16

    cubics = []
    quadrants = ellipse_cubics(left, top, right, bottom, null_pen=null_pen)
    for index, (a, b) in enumerate(pairwise(boundaries)):
        if 0 < index < len(boundaries) - 2:
            cubics.append(quadrants[round(a / 90) % 4])
            continue
        s0, c0 = sincos_degrees(a, accurate=accurate)
        s3, c3 = sincos_degrees(b, accurate=accurate)
        determinant = c0 * s3 - c3 * s0
        if determinant == 0:
            cubic = (device_point(c0, -s0),) * 4
        else:
            # Intersect the endpoint tangent lines n.T = 1. With table
            # trigonometry this is not interchangeable with tan(sweep/4).
            tx, ty = (s3 - s0) / determinant, (c0 - c3) / determinant
            _, half_cosine = sincos_degrees((b - a) / 2)
            weight = 4 * half_cosine / (3 * (1 + half_cosine))
            cubic = (
                device_point(c0, -s0),
                device_point(c0 + weight * (tx - c0), -s0 - weight * (ty - s0)),
                device_point(c3 + weight * (tx - c3), -s3 - weight * (ty - s3)),
                device_point(c3, -s3),
            )
        # Quantize terminal-piece controls before flattening. Intermediate
        # quadrants use the ellipse construction, not this trigonometric cut.
        cubic = tuple(tuple(round(value) for value in point) for point in cubic)
        cubics.append(cubic)
    return tuple(cubics)


def arc_figure(
    left: int,
    top: int,
    right: int,
    bottom: int,
    start: Point,
    end: Point,
    *,
    closure: Literal["open", "chord", "pie"] = "open",
    null_pen=False,
) -> DevicePath:
    """Retain one arc figure, optionally closed directly or through its centre."""
    curves = arc_cubics(left, top, right, bottom, start, end, null_pen=null_pen)
    if closure == "open":
        return DevicePath(curves, closed=start == end)
    if closure == "chord":
        closing = ((curves[-1][-1], curves[0][0]),)
    elif closure == "pie":
        x0, y0, x1, y1 = _ellipse_bounds(left, top, right, bottom, null_pen=null_pen)
        centre = ((x0 + x1) // 2, (y0 + y1) // 2)
        # Native Pie appends the centre after the cubics and closes there,
        # including full revolutions. Preserve that order for styled pens.
        closing = ((curves[-1][-1], centre), (centre, curves[0][0]))
    else:
        raise ValueError(f"Unknown arc closure: {closure}")
    return DevicePath((*curves, *closing), closed=True)


def arc_path(left: int, top: int, right: int, bottom: int, start: Point, end: Point) -> Polygon:
    """Flatten Arc geometry for cosmetic coverage or path diagnostics."""
    cubics = arc_cubics(left, top, right, bottom, start, end)
    path = [cubics[0][0]]
    for cubic in cubics:
        path.extend(flatten_cubic(cubic))
    return path[:-1] if start == end else path
