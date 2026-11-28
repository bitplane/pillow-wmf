"""Construct the exclusive-bound ellipse as a fixed-point device path."""

from fractions import Fraction
from itertools import pairwise
from math import floor
from typing import Literal

from .gdi_math import SHORT_ANGLE, arc_control_normals, atan2_degrees, circle_control, float32, sincos_degrees
from .geometry import DevicePath, Point, Polygon, flatten_cubic

_SCALE = 16


def inside_frame_bounds(logical_bounds, device_bounds, width, scale):
    """Return full coverage and the 28.4 centreline for an inside-frame pen.

    Logical equality retains a degenerate centreline, even when quantized
    device bounds invert. Half-width rounding keeps the native asymmetry.
    """
    x0, y0, x1, y1 = logical_bounds
    left, top, right, bottom = device_bounds
    covered = width > min(abs(x1 - x0), abs(y1 - y0))
    if covered:
        return True, (left * 16, top * 16, right * 16, bottom * 16)
    dx, dy = (floor(width * abs(value) * 16 + 0.5) for value in scale)
    return False, (
        left * 16 + (dx + 1) // 2,
        top * 16 + (dy + 1) // 2,
        right * 16 - dx // 2,
        bottom * 16 - (dy + 1) // 2,
    )


# GDI's 0.32 circle-inset constant; see gdi_math.circle_control.
_CIRCLE_INSET = 0x729D7775


def box_corners(bounds):
    """Native box traversal: retain the upper edge, reflect about its centre."""
    left, top, right, bottom = bounds
    cx, cy = (left + right) // 2, (top + bottom) // 2
    upper = ((right, top), (left, top))
    return (*upper, *((2 * cx - x, 2 * cy - y) for x, y in upper))


def box_axes(bounds):
    """Quantize the box's half-edge vectors before angular/corner scaling."""
    top_right, top_left, _, bottom_right = box_corners(bounds)
    horizontal = tuple((a - b + 1) // 2 for a, b in zip(top_right, top_left, strict=False))
    north = tuple((a - b + 1) // 2 for a, b in zip(top_right, bottom_right, strict=False))
    centre = tuple(
        a + (b - a + 1) // 2 + (d - a + 1) // 2 for a, b, d in zip(top_right, top_left, bottom_right, strict=False)
    )
    return centre, horizontal, north


def advanced_box_axes(bounds):
    """Centre and half-axis vectors of a GM_ADVANCED box, as its ellipse uses them."""
    return corner_axes(box_parallelogram(bounds))


def box_parallelogram(bounds):
    """The (left-top, right-top, right-bottom, left-bottom) corners of an oriented box."""
    left, top, right, bottom = bounds
    return (left, top), (right, top), (right, bottom), (left, bottom)


def _half(vector, *, up=False):
    return tuple(-((-value) >> 1) if up else value >> 1 for value in vector)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def _corner_middles(corners):
    """Top and left edge midpoints, and the right one reflected through RT + LB."""
    lt, rt, _, lb = corners
    top = _add(lt, _half(_sub(rt, lt)))
    left = _add(lt, _half(_sub(lb, lt)))
    return top, left, _sub(_add(rt, lb), left)


def corner_axes(corners):
    """Centre, horizontal and north half-axis vectors of a transformed box.

    The four 28.4 corners are mapped separately, so they need not form an
    exact parallelogram; each quantity uses the corners native GDI does.
    """
    lt, rt, _, lb = corners
    _, _, right = _corner_middles(corners)
    horizontal = _half(_sub(rt, lt), up=True)
    return _sub(right, _half(_sub(rt, lt))), horizontal, tuple(-value for value in _half(_sub(lb, lt)))


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


def advanced_ellipse_cubics(
    left: int, top: int, right: int, bottom: int
) -> tuple[tuple[Point, Point, Point, Point], ...]:
    """GM_ADVANCED ellipse cubics from a transformed, lower-right-inclusive 28.4 box.

    Edges keep their world orientation, so a mirrored transform gives
    ``right < left``. See ``corner_ellipse_cubics``.
    """
    return corner_ellipse_cubics(box_parallelogram((left, top, right, bottom)))


def corner_ellipse_cubics(corners) -> tuple[tuple[Point, Point, Point, Point], ...]:
    """GM_ADVANCED ellipse cubics from the four transformed corners of its box.

    The upper half starts at the right edge's midpoint. Control insets are
    GDI's circle constant times half an edge: half the top edge rounded up
    with its inset rounded down, half the left edge rounded down with its
    inset rounded up, per device component. The lower half reflects the
    upper through the sum of the right-top and left-bottom corners, so odd
    spans place opposite points a sixteenth apart. For an axis-aligned even
    integer box this is the compatible-mode construction.
    """
    lt, rt, _, lb = corners
    top, left, right = _corner_middles(corners)

    def inset(vector, *, up):
        return tuple(-((-value * _CIRCLE_INSET) >> 32) if up else (value * _CIRCLE_INSET) >> 32 for value in vector)

    across = inset(_half(_sub(rt, lt), up=True), up=False)
    down = inset(_half(_sub(lb, lt)), up=True)
    upper = (right, _add(rt, down), _sub(rt, across), top, _add(lt, across), _add(lt, down))
    centre = _add(rt, lb)
    points = (*upper, *(_sub(centre, point) for point in upper), upper[0])
    return tuple(tuple(points[index : index + 4]) for index in range(0, 12, 3))


def round_rect_figure(
    left,
    top,
    right,
    bottom,
    ellipse_width,
    ellipse_height,
    *,
    null_pen=False,
    drawing_bounds=None,
    clockwise=False,
    advanced=False,
    corners=None,
) -> DevicePath:
    """Place canonical ellipse quarters at four centres and connect the edges.

    ``advanced`` reflects the upper half through the exact centre of the
    inclusive GM_ADVANCED box, as its ellipse does. ``corners`` gives the
    transformed box of a rotating or shearing transform instead.
    """
    if corners is not None:
        return corner_round_rect_figure(corners, ellipse_width, ellipse_height, right - left, bottom - top)
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
        return tuple(a + sign * b for a, b in zip(point, vector, strict=False))

    def control(point, corner):
        # Apply oriented X/Y control rounding before reflecting the lower
        # half. Rounding final transformed coordinates loses that bias.
        rounding = (horizontal[0] >= 0, (vertical[1] >= 0) == clockwise)
        return tuple(
            a + (1 if b >= a else -1) * circle_control(abs(b - a), upward=upward)
            for a, b, upward in zip(point, corner, rounding, strict=False)
        )

    upper = []
    for corner, start, end in (
        (top_right, add(top_right, vertical), add(top_right, horizontal, -1)),
        (top_left, add(top_left, horizontal), add(top_left, vertical)),
    ):
        upper.append((start, control(start, corner), control(end, corner), end))
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    sum_x, sum_y = (x0 + x1, y0 + y1) if advanced else (2 * cx, 2 * cy)
    curves = (*upper, *(tuple((sum_x - x, sum_y - y) for x, y in curve) for curve in upper))
    if clockwise:
        curves = tuple(tuple((x, 2 * cy - y) for x, y in curve) for curve in curves)
    commands = tuple(
        command for i, curve in enumerate(curves) for command in (curve, (curve[-1], curves[(i + 1) % 4][0]))
    )
    return DevicePath(commands, closed=True)


def corner_round_rect_figure(corners, ellipse_width, ellipse_height, width, height) -> DevicePath:
    """A GM_ADVANCED rounded rectangle on the four transformed corners of its box.

    Corner radii are the logical proportions of half the top edge and half
    the right edge, each rounded up and then scaled to the nearest 28.4
    unit. Controls round each device component by the sign of its axis, as
    the axis-aligned construction does, and the lower half reflects the
    upper through the sum of the right-top and left-bottom corners.
    """
    lt, rt, rb, lb = corners
    if not ellipse_width or not ellipse_height:
        return DevicePath.polyline((rt, lt, lb, rb), closed=True)

    def scale(vector, proportion):
        return tuple(floor(value * proportion + Fraction(1, 2)) for value in vector)

    horizontal = scale(_half(_sub(rt, lt), up=True), Fraction(min(abs(ellipse_width), width), width))
    north = scale(_half(_sub(rt, rb), up=True), Fraction(min(abs(ellipse_height), height), height))
    vertical = (-north[0], -north[1])
    across = tuple(value >= 0 for value in horizontal)
    down = tuple(value < 0 for value in vertical)

    def control(point, corner, upward):
        return tuple(
            a + (1 if b >= a else -1) * circle_control(abs(b - a), upward=up)
            for a, b, up in zip(point, corner, upward, strict=True)
        )

    start, end = _add(rt, vertical), _sub(rt, horizontal)
    upper = [(start, control(start, rt, down), control(end, rt, across), end)]
    start, end = _add(lt, horizontal), _add(lt, vertical)
    upper.append((start, control(start, lt, across), control(end, lt, down), end))
    centre = _add(rt, lb)
    curves = (*upper, *(tuple(_sub(centre, point) for point in curve) for curve in upper))
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
    advanced=False,
    corners=None,
    angles=None,
) -> tuple[tuple[Point, Point, Point, Point], ...]:
    """Cut an exclusive-bound ellipse at two radial directions.

    Normalize radials in the inclusive device box, then construct cubics in
    the exclusive-bound drawing box. WMF stores points on the radials, not
    points required to lie on the ellipse. ``advanced`` takes the
    GM_ADVANCED ellipse from the inclusive 28.4 ``drawing_bounds``, or from
    the transformed box ``corners`` under a rotating or shearing transform.
    ``angles`` gives the two directions in degrees instead, as AngleArc
    does; each then lies in the quadrant of its angle's floor.
    """
    x0, y0, x1, y1 = drawing_bounds or _ellipse_bounds(left, top, right, bottom, null_pen=null_pen)
    if advanced and corners is None:
        corners = box_parallelogram((x0, y0, x1, y1))
    centre, horizontal, north = corner_axes(corners) if advanced else box_axes((x0, y0, x1, y1))
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

    if angles is None and not (radial_rx and radial_ry):
        # A radial box without width or height cuts nowhere: the arc is the
        # whole degenerate ellipse, from and back to its zero-angle point.
        (first, first_quadrant), (last, last_quadrant) = (float32(0), 0), (float32(0), 0)
    elif angles is None:
        (first, first_quadrant), (last, last_quadrant) = angle(start), angle(end)
    else:
        first, last = (float32(value % 360) for value in angles)
        first_quadrant, last_quadrant = int(first // 90) % 4, int(last // 90) % 4
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
    if advanced:
        quadrants = corner_ellipse_cubics(corners)
    else:
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
    advanced=False,
    corners=None,
    angles=None,
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
        advanced=advanced,
        corners=corners,
        angles=angles,
    )
    if closure == "open":
        return DevicePath(curves, closed=start == end)
    if closure == "chord":
        closing = ((curves[-1][-1], curves[0][0]),)
    elif closure == "pie":
        x0, y0, x1, y1 = drawing_bounds or _ellipse_bounds(left, top, right, bottom, null_pen=null_pen)
        if corners is not None:
            centre, _, _ = corner_axes(corners)
        else:
            centre, _, _ = (advanced_box_axes if advanced else box_axes)((x0, y0, x1, y1))
        # Native Pie appends the centre after the cubics and closes there,
        # including full revolutions. Preserve that order for styled pens.
        closing = ((curves[-1][-1], centre), (centre, curves[0][0]))
    else:
        raise ValueError(f"Unknown arc closure: {closure}")
    return DevicePath((*curves, *closing), closed=True)


def advanced_arc(
    mapping,
    box,
    start,
    end,
    *,
    direction=1,
    closure="open",
    null_pen=False,
    angles=None,
    inside_frame=0,
    radial_box=None,
):
    """A GM_ADVANCED arc figure in world orientation, from a logical box.

    A clockwise arc is the y-mirror image of a counterclockwise one, as a
    mirroring transform gives. ``angles`` gives the arc's directions in
    degrees in place of the radial points. ``inside_frame`` is the width of
    a wide inside-frame pen, which insets the box at its corners; a box
    narrower than the pen gives None, as the native call then does nothing.
    ``radial_box`` normalizes the radials when it differs from the drawn box.
    """
    left, right = sorted(box[0::2])
    top, bottom = sorted(box[1::2])
    radial_left, radial_right = sorted((radial_box or box)[0::2])
    radial_top, radial_bottom = sorted((radial_box or box)[1::2])
    if inside_frame and inside_frame > min(right - left, bottom - top):
        return None
    lt, rt, lb = (mapping.fixed_point(*point) for point in ((left, top), (right, top), (left, bottom)))
    if inside_frame:
        lt, rt, lb = mapping.inside_frame_corners(lt, rt, lb, inside_frame)
    rb = (rt[0] + lb[0] - lt[0], rt[1] + lb[1] - lt[1])
    if direction == 2:
        # The mirror image swaps the box's top and bottom corners.
        lt, rt, lb, rb = lb, rb, lt, rt
        mirror = radial_top + radial_bottom
        start, end = (start[0], mirror - start[1]), (end[0], mirror - end[1])
        angles = angles and tuple(-value for value in angles)
    corners = (lt, rt, rb, lb) if mapping.rotated else None
    (x0, y0), (x1, y1) = lt, rb
    xs, ys = (lt[0], rt[0], rb[0], lb[0]), (lt[1], rt[1], rb[1], lb[1])
    ceil = [(value + 15) // 16 for value in (min(xs), min(ys), max(xs), max(ys))]
    return arc_figure(
        *ceil[:2],
        ceil[2] + 1,
        ceil[3] + 1,
        start,
        end,
        closure=closure,
        null_pen=null_pen,
        drawing_bounds=(x0, y0, x1, y1),
        radial_bounds=(radial_left, radial_top, radial_right, radial_bottom),
        advanced=True,
        corners=corners,
        angles=angles,
    )
