"""Solid GDI strokes: realized polygonal pens and cosmetic grid lines.

The pen is realized once from the mapping. Every wide segment then uses the
same support-vertex sweep, independent of its slope or the mapping scale.
Native measurement details and limitations are in docs/gdi-strokes.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import ceil, floor

from .gdi_math import circle_control
from .geometry import Point, Polygon, StrokeSegment, flatten_cubic
from .numeric import float32

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

# Cosmetic CreatePen styles, in device pixels: alternating foreground and gap.
_DASHES = {
    1: (18, 6),
    2: (3, 3),
    3: (9, 6, 3, 6),
    4: (9, 3, 3, 3, 3, 3),
}


def dash_is_foreground(style: int, position: int) -> bool:
    pattern = _DASHES[style]
    phase = position % sum(pattern)
    for index, length in enumerate(pattern):
        if phase < length:
            return index % 2 == 0
        phase -= length
    raise AssertionError("Dash phase outside pattern")


@dataclass(frozen=True)
class PenGeometry:
    vertices: tuple[Point, ...]
    cosmetic: bool


def realize_pen(width: int, scale_x=1, scale_y=1, *, geometric=False) -> PenGeometry:
    """Realize CreatePen width in device space, including the hairline rule."""
    device_width = floor(width * abs(scale_x) + 0.5)
    cosmetic = not geometric and device_width <= 1
    diameters = tuple(floor(width * abs(scale) * 16 + 0.5) for scale in (scale_x, scale_y))
    circular = abs(scale_x) == abs(scale_y) if geometric else diameters[0] == diameters[1]
    if cosmetic or (circular and device_width <= 6):
        half = [(x * 8, y * 8) for x, y in _SMALL_PENS[max(1, device_width)]]
    else:
        # Preserve the orientation of the first transformed basis vector.
        # The other radius has that same sign so the contour stays CCW.
        sign = 1 if scale_x >= 0 else -1
        if geometric:

            def half_fixed(value):
                # Transform the full signed basis to 28.4 first, then halve
                # away from zero. Scaling a positive radius is not equivalent.
                fixed = floor(value + 0.5)
                return (fixed + (fixed >= 0)) // 2

            rx = half_fixed(width * scale_x * 16)
            ry = sign * abs(half_fixed(-width * scale_y * 16))
        else:
            # Quantize the full diameter before halving outward.
            rx, ry = (sign * ((diameter + 1) // 2) for diameter in diameters)
        # bThicken uses bounded integer products: half-basis components must
        # fit in 12 bits. Larger pens retain their ordinary cubic silhouette,
        # including subpixel minor axes, rather than being thickened.
        thicken = not geometric and max(abs(rx), abs(ry)) < 4096 and min(abs(rx), abs(ry)) <= 4
        if thicken:
            rx, ry = (sign * max(8, abs(radius)) for radius in (rx, ry))
            # A collapsed CreatePen axis selects a diamond, not a cubic
            # ellipse enlarged to the minimum thickness. Retain the same
            # half-contour seam layout used by the ordinary pen constructor.
            half = [(rx, 0), (0, -ry), (-rx, 0)]
        else:
            cx, cy = circle_control(rx, upward=True), circle_control(ry, upward=False)
            half = [(rx, 0)]
            half += flatten_cubic(((rx, 0), (rx, -cy), (cx, -ry), (0, -ry)))
            half += flatten_cubic(((0, -ry), (-cx, -ry), (-rx, -cy), (-rx, 0)))
        # Keep the semicircle's terminal vertex: reflection duplicates both
        # seam vertices. Native contour traversal visits those duplicates;
        # they matter when rounded body support differs from the pen vertex.
    return PenGeometry(tuple(half + [(-x, -y) for x, y in half]), cosmetic)


def frame_footprint(width, height, scale_x, scale_y):
    """Rectangular frame support realized through GDI's geometric pen."""
    width, height = abs(width), abs(height)
    if not width or not height:
        return 0, 0

    radius = max(width, height)
    scale_x = float32(float32(width / radius) * float32(scale_x))
    scale_y = float32(float32(height / radius) * float32(scale_y))
    pen = realize_pen(2 * radius, scale_x, scale_y, geometric=True)
    half = pen.vertices[: len(pen.vertices) // 2]
    extreme = min if half[0][0] >= 0 else max
    vertical_index = extreme(range(len(half)), key=lambda index: half[index][1])
    indices = (0, vertical_index)
    supports = []
    for axis, index in enumerate(indices):
        for step in range(1, len(pen.vertices)):
            adjacent = (index + step) % len(pen.vertices)
            if pen.vertices[adjacent] != pen.vertices[index]:
                break
        else:
            return 0, 0
        value = pen.vertices[index][axis]
        delta = value - pen.vertices[adjacent][axis]
        # The native normal/pen-edge intersection rounds its midpoint and
        # interpolation separately. An odd positive edge delta consequently
        # advances the endpoint by one fixed unit.
        value = value - (delta >> 1) + (1 if delta >= 0 else -1) * ((abs(delta) + 1) // 2)
        supports.append(Fraction(abs(_body(value, miter=axis == 0)), 16))
    return tuple(supports)


def _support_index(pen: PenGeometry, dx: int, dy: int) -> int:
    if dx == dy == 0:
        dx = 1
    vertices = pen.vertices
    half = len(vertices) // 2

    # Native support selection bisects edge cross-product signs on a stored
    # semicircle, bracketed by reflected seam neighbours. A global maximum
    # is not equivalent when fixed-point flattening produces collinear edges.
    terminal = int(vertices[half - 1] == vertices[half])
    count = half - terminal

    def point(index):
        return vertices[half + count - 1] if index == 0 else vertices[index - 1]

    def negative_edge(index):
        a, b = point(index), point(index + 1)
        return dx * (b[1] - a[1]) - dy * (b[0] - a[0]) < 0

    negative = negative_edge(0)
    low, high = 0, count
    while high - low > 1:
        middle = (low + high) // 2
        if negative_edge(middle) == negative:
            low = middle
        else:
            high = middle
    return high - 1 + (0 if negative else half)


def _body(value, *, miter=False):
    # Direct GDI mitered frames own horizontal half-step ties inward;
    # other support coordinates own them outward on the half-pixel grid.
    return (1 if value >= 0 else -1) * ((abs(value) + (3 if miter else 4)) // 8) * 8


def _cap(value, origin: Point):
    # Native cap contours inset by one fixed unit only at integer centers.
    # All 255 fractional phases retain the realized pen vertices unchanged.
    inset = origin[0] % 16 == origin[1] % 16 == 0
    return value - (1 if value > 0 else -1 if value < 0 else 0) * inset


def widen_segment(segment: StrokeSegment, pen: PenGeometry, *, cap_start=True, cap_end=True, miter=False) -> Polygon:
    """Construct a stroke body and requested endpoint caps in 28.4 units."""
    vertices = pen.vertices
    half = len(vertices) // 2
    index = _support_index(pen, *segment.direction)

    outline = []
    for origin, cap in ((segment.start, cap_start), (segment.end, cap_end)):
        for offset in range(half + 1) if cap else (0, half):
            position = (index + offset) % len(vertices)
            # Forward cap enumeration excludes each half's terminal sentinel.
            if offset not in (0, half) and vertices[position] == vertices[(position + 1) % len(vertices)]:
                continue
            x, y = vertices[position]
            x, y = (_body(x, miter=miter), _body(y)) if offset in (0, half) else (_cap(x, origin), _cap(y, origin))
            outline.append((origin[0] + x, origin[1] + y))
        index = (index + half) % len(vertices)
    return outline


def join_outline(first: StrokeSegment, second: StrokeSegment, pen: PenGeometry, *, miter=False) -> Polygon:
    """Cover the exterior turn between two incident stroke bodies."""
    vertex = first.end
    dx1, dy1 = first.direction
    dx2, dy2 = second.direction
    turn = dx1 * dy2 - dy1 * dx2
    # Zero cross product can mean straight ahead or a 180-degree reversal.
    # A round reversal walks half the pen contour, just like any other turn.
    if not turn and (dx1 * dx2 + dy1 * dy2 >= 0 or miter):
        return []
    vertices = pen.vertices
    count = len(vertices)
    i = (_support_index(pen, dx1, dy1) + (count // 2 if turn < 0 else 0)) % count
    j = (_support_index(pen, dx2, dy2) + (count // 2 if turn < 0 else 0)) % count
    start = tuple(vertex[axis] + _body(vertices[i][axis], miter=miter and axis == 0) for axis in (0, 1))
    end = tuple(vertex[axis] + _body(vertices[j][axis], miter=miter and axis == 0) for axis in (0, 1))
    outline = [vertex, start]
    if miter:
        t = Fraction((end[0] - start[0]) * dy2 - (end[1] - start[1]) * dx2, turn)
        outline.append((start[0] + dx1 * t, start[1] + dy1 * t))
    else:
        step = 1 if turn < 0 else -1
        while i != j:
            i = (i + step) % count
            if i != j:
                # The reverse walker visits terminal sentinels; the forward
                # walker starts the next half at its head instead.
                if step > 0 and vertices[i] == vertices[(i + 1) % count]:
                    continue
                outline.append((vertex[0] + _cap(vertices[i][0], vertex), vertex[1] + _cap(vertices[i][1], vertex)))
    outline.append(end)
    return outline


def line_outline(start: Point, end: Point, width: int, scale_x, scale_y) -> Polygon:
    """Device-integer convenience entry point for diagnostic path probes."""
    return widen_segment(
        StrokeSegment.line((start[0] * 16, start[1] * 16), (end[0] * 16, end[1] * 16)),
        realize_pen(width, scale_x, scale_y),
    )


def _inside_diamond(x, y, dx: int, dy: int) -> bool:
    """Legacy GIQ membership relative to a pixel center, in sixteenths."""
    distance = abs(x) + abs(y)
    return distance < 8 or (
        distance == 8
        and (
            (x == 0 and y == 8)
            or (y == 0 and x == (-8 if dx == dy else 8))
            or (y > 0 and (dx == dy and x < 0 or dx == -dy and x > 0))
        )
    )


def _cosmetic_pixel(start: Point, end: Point, value: int):
    """Return the GIQ pixel at one major coordinate, without surface clipping."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    if dx == dy == 0:
        return None
    transpose = abs(dy) > abs(dx)
    major, minor = (1, 0) if transpose else (0, 1)
    delta = end[major] - start[major]
    numerator = start[minor] * delta + (value * 16 - start[major]) * (end[minor] - start[minor])
    other = ceil(Fraction(numerator, delta * 16) - Fraction(1, 2))
    x, y = (other, value) if transpose else (value, other)
    enter, leave = None, None
    # Transform the diamond into an axis-aligned square with u=x+y, v=x-y.
    for origin, change, center in (
        (start[0] + start[1], dx + dy, (x + y) * 16),
        (start[0] - start[1], dx - dy, (x - y) * 16),
    ):
        if not change:
            if not center - 8 <= origin <= center + 8:
                return None
            continue
        lower, upper = sorted((Fraction(center - 8 - origin, change), Fraction(center + 8 - origin, change)))
        enter = lower if enter is None else max(enter, lower)
        leave = upper if leave is None else min(leave, upper)
    if enter <= leave and 0 <= leave <= 1 and not _inside_diamond(end[0] - x * 16, end[1] - y * 16, dx, dy):
        middle = (max(enter, 0) + leave) / 2
        if _inside_diamond(start[0] + middle * dx - x * 16, start[1] + middle * dy - y * 16, dx, dy):
            return x, y
    return None


def cosmetic_span(start: Point, end: Point) -> range:
    """Unclipped, directed major-axis pixel span, in constant time.

    Only endpoint diamonds can shorten the span; interior grid intersections
    each own a pixel. This counts style steps even when the whole line is off
    screen, without enumerating arbitrarily distant coordinates.
    """
    major = int(abs(end[1] - start[1]) > abs(end[0] - start[0]))
    lower, upper = sorted((start[major] // 16, end[major] // 16))
    first = next((v for v in range(lower - 1, lower + 3) if _cosmetic_pixel(start, end, v) is not None), None)
    last = next((v for v in range(upper + 1, upper - 3, -1) if _cosmetic_pixel(start, end, v) is not None), None)
    if first is None or last is None:
        return range(0)
    return range(first, last + 1) if end[major] >= start[major] else range(last, first - 1, -1)


def cosmetic_line(start: Point, end: Point, width: int, height: int):
    """GIQ coverage for a 28.4 segment, including fractional curve vertices.

    Choose the closest minor-coordinate pixel at each major grid intersection
    (ties to the smaller coordinate). A pixel is emitted when the segment exits
    its half-pixel diamond. Endpoint ownership uses the legacy GIQ boundary
    rules (including slope +/-1 edges), not a blanket start/end convention.
    See docs/gdi-strokes.md for the specification and native measurements.
    Bounds restrict grid enumeration without changing the original line.
    """
    dx, dy = end[0] - start[0], end[1] - start[1]
    if dx == dy == 0:
        return
    transpose = abs(dy) > abs(dx)
    major = 1 if transpose else 0
    a, b = start[major], end[major]
    extent = height if transpose else width
    for value in range(max(0, min(a, b) // 16 - 1), min(extent, max(a, b) // 16 + 2)):
        pixel = _cosmetic_pixel(start, end, value)
        if pixel is not None and 0 <= pixel[0] < width and 0 <= pixel[1] < height:
            yield pixel
