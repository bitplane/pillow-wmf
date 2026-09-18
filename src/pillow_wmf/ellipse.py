"""Construct the exclusive-bound ellipse as a fixed-point device path."""

from itertools import pairwise
from math import floor
from typing import Literal

from .gdi_math import SHORT_ANGLE, arc_control_normals, atan2_degrees, circle_control, float32, sincos_degrees
from .geometry import DevicePath, Point, Polygon, flatten_cubic

_SCALE = 16


def box_corners(bounds):
    """Native box traversal: retain the upper edge, reflect about its centre."""
    left, top, right, bottom = bounds
    cx, cy = (left + right) // 2, (top + bottom) // 2
    upper = ((right, top), (left, top))
    return (*upper, *((2 * cx - x, 2 * cy - y) for x, y in upper))


def box_axes(bounds):
    """Quantize the box's half-edge vectors before angular/corner scaling."""
    top_right, top_left, _, bottom_right = box_corners(bounds)
    horizontal = tuple((a - b + 1) // 2 for a, b in zip(top_right, top_left))
    north = tuple((a - b + 1) // 2 for a, b in zip(top_right, bottom_right))
    centre = tuple(a + (b - a + 1) // 2 + (d - a + 1) // 2 for a, b, d in zip(top_right, top_left, bottom_right))
    return centre, horizontal, north


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
    left: int, top: int, right: int, bottom: int, *, null_pen=False, drawing_bounds=None, clockwise=False
) -> tuple[tuple[Point, Point, Point, Point], ...]:
    """Four GDI-style cubics, with orientation applied before quantization."""
    left_fixed, top_fixed, right_fixed, bottom_fixed = drawing_bounds or _ellipse_bounds(
        left, top, right, bottom, null_pen=null_pen
    )
    cx, cy = (left_fixed + right_fixed) // 2, (top_fixed + bottom_fixed) // 2
    rx, lx, ry = right_fixed - cx, cx - left_fixed, cy - top_fixed
    if clockwise:
        ry = -ry
    cy_control = circle_control(ry, upward=False)
    # Translate the same horizontal control inset from both upper corners.
    # An odd box span must not independently round its shorter left radius.
    x_inset = rx - circle_control(rx, upward=True)
    upper = (
        ((rx, 0), (rx, -cy_control), (rx - x_inset, -ry), (0, -ry)),
        ((0, -ry), (-lx + x_inset, -ry), (-lx, -cy_control), (-rx, 0)),
    )
    curves = (*upper, *(tuple((-x, -y) for x, y in curve) for curve in upper))
    return tuple(tuple((cx + x, cy + y) for x, y in curve) for curve in curves)


def round_rect_figure(
    left, top, right, bottom, ellipse_width, ellipse_height, *, null_pen=False, drawing_bounds=None, clockwise=False
) -> DevicePath:
    """Place canonical ellipse quarters at four centres and connect the edges."""
    if not ellipse_width or not ellipse_height:
        bounds = drawing_bounds or (left * 16, top * 16, (right - 1) * 16, (bottom - 1) * 16)
        return DevicePath.polyline(box_corners(bounds), closed=True)
    x0, y0, x1, y1 = drawing_bounds or _ellipse_bounds(left, top, right, bottom, null_pen=null_pen)
    # Corner diameters are fractions of the original logical box. Quantize
    # the adjusted box axes first, then scale them by those proportions.
    top_right, top_left, _, _ = box_corners((x0, y0, x1, y1))
    _, horizontal, north = box_axes((x0, y0, x1, y1))

    def scale(vector, proportion):
        return tuple(floor(value * proportion + 0.5) for value in vector)

    horizontal = scale(horizontal, min(abs(ellipse_width), right - left) / (right - left))
    north = scale(north, min(abs(ellipse_height), bottom - top) / (bottom - top))
    vertical = tuple(-value for value in north)

    def add(point, vector, sign=1):
        return tuple(a + sign * b for a, b in zip(point, vector))

    def control(point, corner):
        # Apply oriented X/Y control rounding before reflecting the lower
        # half. Rounding final transformed coordinates loses that bias.
        rounding = (horizontal[0] >= 0, (vertical[1] >= 0) == clockwise)
        return tuple(
            a + (1 if b >= a else -1) * circle_control(abs(b - a), upward=upward)
            for a, b, upward in zip(point, corner, rounding)
        )

    upper = []
    for corner, start, end in (
        (top_right, add(top_right, vertical), add(top_right, horizontal, -1)),
        (top_left, add(top_left, horizontal), add(top_left, vertical)),
    ):
        upper.append((start, control(start, corner), control(end, corner), end))
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    curves = (*upper, *(tuple((2 * cx - x, 2 * cy - y) for x, y in curve) for curve in upper))
    if clockwise:
        curves = tuple(tuple((x, 2 * cy - y) for x, y in curve) for curve in curves)
    commands = tuple(
        command for i, curve in enumerate(curves) for command in (curve, (curve[-1], curves[(i + 1) % 4][0]))
    )
    return DevicePath(commands, closed=True)


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
    drawing_bounds=None,
    radial_bounds=None,
    clockwise=False,
) -> tuple[tuple[Point, Point, Point, Point], ...]:
    """Cut an exclusive-bound ellipse at two radial directions.

    Normalize radials in the inclusive device box, then construct cubics in
    the exclusive-bound drawing box. WMF stores points on the radials, not
    points required to lie on the ellipse.
    """
    x0, y0, x1, y1 = drawing_bounds or _ellipse_bounds(left, top, right, bottom, null_pen=null_pen)
    centre, horizontal, north = box_axes((x0, y0, x1, y1))
    radial_left, radial_top, radial_right, radial_bottom = radial_bounds or (left, top, right, bottom)
    radial_cx = (radial_left + radial_right) / 2
    radial_cy = (radial_top + radial_bottom) / 2
    radial_rx = (radial_right - radial_left) / 2
    radial_ry = (radial_bottom - radial_top) / 2
    if clockwise:
        north = tuple(-value for value in north)
        radial_ry = -radial_ry

    def angle(point: tuple[int, int]):
        offset_x = float32(float32(point[0]) - radial_cx)
        offset_y = float32(radial_cy - float32(point[1]))
        x, y = float32(offset_x / radial_rx), float32(offset_y / radial_ry)
        # vArctan retains the radial's quadrant separately from its rounded
        # angle. Axis ties belong according to coordinate signs, not floor
        # of angle/90; this preserves native zero-length boundary pieces.
        quadrant = (0, 1, 3, 2)[(x < 0) + 2 * (y < 0)]
        return atan2_degrees(y, x), quadrant

    (first, first_quadrant), (last, last_quadrant) = angle(start), angle(end)
    # Choose endpoint precision before unwrapping. Nearly coincident angles
    # that compare equal request a full sweep, not the short-angle mode.
    accurate = 0 < abs(float32(last - first)) < SHORT_ANGLE
    first_normal = tuple(reversed(sincos_degrees(first, accurate=accurate)))
    last_normal = tuple(reversed(sincos_degrees(last, accurate=accurate)))
    axis_normals = ((1, 0), (0, 1), (-1, 0), (0, -1))
    boundaries = [first]
    if first_quadrant != last_quadrant or last <= first:
        quadrant = (first_quadrant + 1) % 4
        boundaries.append(quadrant * 90)
        while quadrant != last_quadrant:
            quadrant = (quadrant + 1) % 4
            boundaries.append(quadrant * 90)
    boundaries.append(last)

    def device_point(nx: float, ny: float) -> Point:
        result = []
        for origin, horizontal_axis, vertical_axis in zip(centre, horizontal, north, strict=True):
            horizontal_offset = float32(float32(horizontal_axis) * nx)
            vertical_offset = float32(float32(vertical_axis) * ny)
            offset = float32(horizontal_offset + vertical_offset)
            # EBOX rounds the relative vector away from zero at ties, then
            # adds its integer centre. Translation must not change tie sense.
            rounded_offset = (1 if offset >= 0 else -1) * floor(abs(offset) + 0.5)
            result.append(origin + rounded_offset)
        return tuple(result)

    cubics = []
    quadrants = ellipse_cubics(
        left, top, right, bottom, null_pen=null_pen, drawing_bounds=drawing_bounds, clockwise=clockwise
    )
    for index, (a, b) in enumerate(pairwise(boundaries)):
        if 0 < index < len(boundaries) - 2:
            cubic = quadrants[round(a / 90) % 4]
            # Native BezierTo inherits the previous endpoint; a rounded
            # terminal point need not equal the canonical quadrant start.
            cubics.append((cubics[-1][-1], *cubic[1:]))
            continue
        # Only the radial endpoints use trigonometry. Quadrant boundaries
        # carry exact axis normals, even when the endpoints use Taylor mode.
        start_normal = first_normal if index == 0 else axis_normals[round(a / 90) % 4]
        end_normal = last_normal if index == len(boundaries) - 2 else axis_normals[round(b / 90) % 4]
        normals = arc_control_normals(a, b, start_normal, end_normal)
        # Quantize terminal-piece controls before flattening. Intermediate
        # quadrants use the ellipse construction, not this trigonometric cut.
        cubic = tuple(device_point(*normal) for normal in normals)
        if cubics:
            cubic = (cubics[-1][-1], *cubic[1:])
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
    drawing_bounds=None,
    radial_bounds=None,
    clockwise=False,
) -> DevicePath:
    """Retain one arc figure, optionally closed directly or through its centre."""
    curves = arc_cubics(
        left,
        top,
        right,
        bottom,
        start,
        end,
        null_pen=null_pen,
        drawing_bounds=drawing_bounds,
        radial_bounds=radial_bounds,
        clockwise=clockwise,
    )
    if closure == "open":
        return DevicePath(curves, closed=start == end)
    if closure == "chord":
        closing = ((curves[-1][-1], curves[0][0]),)
    elif closure == "pie":
        x0, y0, x1, y1 = drawing_bounds or _ellipse_bounds(left, top, right, bottom, null_pen=null_pen)
        centre, _, _ = box_axes((x0, y0, x1, y1))
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
