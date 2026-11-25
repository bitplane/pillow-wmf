"""Geometric pen outlines: end caps, joins and the cap perpendicular.

Extended geometric pens widen each figure into closed outlines that are
filled with the winding rule. Round caps with round joins keep the support
vertex construction shared with wide CreatePen strokes. Every other
combination places the body edges on a perpendicular vector chosen from the
realized pen polygon, so flat and square caps, bevels and miters share it.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import atan2, floor, hypot, pi

from .geometry import Point, Polygon, StrokeSegment
from .stroke import PenGeometry, _body, _cap, _support_index

CAP_ROUND, CAP_SQUARE, CAP_FLAT = 0, 1, 2
JOIN_ROUND, JOIN_BEVEL, JOIN_MITER = 0, 1, 2


@dataclass(frozen=True)
class PenShape:
    """A realized geometric pen: its polygon, device half-widths, mapping scale and style."""

    pen: PenGeometry
    radius: tuple[float, float]
    scale: tuple[float, float]
    cap: int = CAP_ROUND
    join: int = JOIN_ROUND
    miter_limit: float = 10.0


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _polygon(pen: PenGeometry) -> list[Point]:
    vertices: list[Point] = []
    for vertex in pen.vertices:
        if not vertices or vertices[-1] != vertex:
            vertices.append(vertex)
    while len(vertices) > 1 and vertices[0] == vertices[-1]:
        vertices.pop()
    return vertices


def _keyframes(pen: PenGeometry):
    """Direction keys around the pen: edge midpoints and chord-keyed vertices.

    A line parallel to a pen edge takes that edge's midpoint. A vertex is
    reached when the line is parallel to the chord joining its neighbours,
    weighted as the mean of its two incident edges.
    """
    vertices = _polygon(pen)
    count = len(vertices)
    keys = []
    for index, vertex in enumerate(vertices):
        following = vertices[(index + 1) % count]
        previous = vertices[index - 1]
        chord = (Fraction(previous[0] - following[0], 2), Fraction(previous[1] - following[1], 2))
        keys.append((chord, vertex))
        edge = (vertex[0] - following[0], vertex[1] - following[1])
        keys.append((edge, (Fraction(vertex[0] + following[0], 2), Fraction(vertex[1] + following[1], 2))))
    keys.sort(key=lambda key: atan2(key[0][1], key[0][0]))
    return keys


def _snap(value) -> int:
    """Half-pixel snap of a perpendicular component."""
    return floor((Fraction(value) + Fraction(7, 2)) / 8) * 8


def _round_half_toward_zero(value: Fraction) -> int:
    magnitude = abs(value)
    rounded = floor(magnitude) + (1 if magnitude - floor(magnitude) > Fraction(1, 2) else 0)
    return rounded if value >= 0 else -rounded


def perpendicular(pen: PenGeometry, direction: Point) -> Point:
    """The half-width vector on the left of ``direction``, on the pen polygon."""
    keys = _keyframes(pen)
    for index, (start_key, start) in enumerate(keys):
        end_key, end = keys[(index + 1) % len(keys)]
        before, after = _cross(start_key, direction), _cross(direction, end_key)
        if before >= 0 and after > 0:
            weight = Fraction(after) / (before + after)
            return tuple(
                _snap(end[axis] + _round_half_toward_zero((start[axis] - end[axis]) * weight)) for axis in (0, 1)
            )
    raise AssertionError("Pen keys do not surround the direction")


def square_vector(shape: PenShape, direction: Point) -> Point:
    """Half-width extension along the line, for square caps.

    It is rounded to 28.4 in logical space along the logical direction, then
    mapped to the device and rounded again.
    """
    (rx, ry), (sx, sy) = shape.radius, shape.scale
    lx, ly = direction[0] / sx if sx else 0.0, direction[1] / sy if sy else 0.0
    length = hypot(lx, ly)
    if not length:
        return (0, 0)
    half = rx / sx if sx else ry / sy
    return (round(round(lx / length * half) * sx), round(round(ly / length * half) * sy))


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _arc(shape: PenShape, origin: Point, start: Point, end: Point, through: Point, *, exclusive=False) -> Polygon:
    """Inset pen vertices swept from ``start`` to ``end`` past ``through``.

    A vertex in the direction of ``start`` is included unless ``exclusive``;
    one in the direction of ``end`` never is.
    """
    clockwise = _cross(start, through) < 0
    base = atan2(start[1], start[0])

    def sweep(vector):
        if _cross(start, vector) == 0 and _dot(start, vector) > 0:
            return 0.0
        value = atan2(vector[1], vector[0]) - base
        return (-value if clockwise else value) % (2 * pi)

    limit = sweep(end) if not (_cross(start, end) == 0 and _dot(start, end) > 0) else 2 * pi
    vertices = [
        vertex
        for vertex in _polygon(shape.pen)
        if sweep(vertex) < limit
        and not (_cross(end, vertex) == 0 and _dot(end, vertex) > 0)
        and not (exclusive and _cross(start, vertex) == 0 and _dot(start, vertex) > 0)
    ]
    vertices.sort(key=sweep)
    return [(origin[0] + _cap(x, origin), origin[1] + _cap(y, origin)) for x, y in vertices]


def _offset(point, vector, sign=1):
    return (point[0] + sign * vector[0], point[1] + sign * vector[1])


def _miter(first: Point, first_direction, second: Point, second_direction) -> Point | None:
    denominator = _cross(first_direction, second_direction)
    if not denominator:
        return None
    t = Fraction(_cross((second[0] - first[0], second[1] - first[1]), second_direction), denominator)
    return tuple(floor(first[axis] + first_direction[axis] * t + Fraction(1, 2)) for axis in (0, 1))


def _miter_fits(first_direction, second_direction, limit) -> bool:
    # Miter length over line width is 1 / sin(half the interior angle).
    dot = -_dot(first_direction, second_direction)
    lengths = hypot(*first_direction) * hypot(*second_direction)
    if not lengths:
        return False
    cosine = max(-1.0, min(1.0, dot / lengths))
    half_sine_squared = (1 - cosine) / 2
    return half_sine_squared > 0 and 1 / half_sine_squared <= limit * limit


def _join(shape, vertex, incoming, outgoing, offset_in, offset_out, outer, arc=None):
    """Points from ``vertex + offset_in`` to ``vertex + offset_out``.

    ``arc`` gives the pen vertices bounding a round join that is built on
    support vertices; it is exclusive of both and adds no inner sweep.
    """
    start, end = _offset(vertex, offset_in), _offset(vertex, offset_out)
    if not outer:
        points = [start, vertex, end]
        if shape.join == JOIN_ROUND and arc is None:
            back = (-incoming[0], -incoming[1])
            points += _arc(shape, vertex, offset_out, offset_in, back) + [start, vertex, end]
        return points
    if arc is not None:
        return [start, *_arc(shape, vertex, *arc, incoming, exclusive=True), end]
    if shape.join == JOIN_MITER and _miter_fits(incoming, outgoing, shape.miter_limit):
        tip = _miter(start, incoming, end, outgoing)
        if tip is not None:
            return [start, tip, end]
    if shape.join == JOIN_ROUND:
        return [start, *_arc(shape, vertex, offset_in, offset_out, incoming), end]
    return [start, end]


def _turn(incoming, outgoing) -> int:
    """Negative for a left turn on screen; reversals turn right."""
    turn = _cross(incoming, outgoing)
    if turn:
        return turn
    return 0 if _dot(incoming, outgoing) > 0 else 1


def _cap_points(shape, point, direction, perp, *, start):
    """Cap from the arriving side to the leaving side of an endpoint."""
    first, second = (perp, (-perp[0], -perp[1])) if start else ((-perp[0], -perp[1]), perp)
    if shape.cap == CAP_FLAT:
        return [_offset(point, first), _offset(point, second)]
    if shape.cap == CAP_SQUARE:
        extension = square_vector(shape, direction)
        sign = -1 if start else 1
        return [_offset(_offset(point, first), extension, sign), _offset(_offset(point, second), extension, sign)]
    # Round caps sweep through the back of the line at the start, the front at the end.
    through = (-direction[0], -direction[1]) if start else direction
    return [_offset(point, first), *_arc(shape, point, first, second, through), _offset(point, second)]


def outline(shape: PenShape, segments: tuple[StrokeSegment, ...], closed: bool) -> list[Polygon]:
    """Native widened outlines of one figure, for winding-rule filling."""
    segments = tuple(segment for segment in segments if segment.direction != (0, 0))
    if not segments:
        return []
    perps = [perpendicular(shape.pen, segment.direction) for segment in segments]
    count = len(segments)
    # Round joins between square caps keep wide CreatePen bodies: the body
    # passes through rounded support vertices and joins sweep between them.
    support = shape.join == JOIN_ROUND and shape.cap == CAP_SQUARE
    raw = [shape.pen.vertices[_support_index(shape.pen, *segment.direction)] for segment in segments] if support else []
    bodies = [(_body(x), _body(y)) for x, y in raw] if support else perps

    def negate(vector):
        return (-vector[0], -vector[1])

    def side(sign, order):
        """Joins along one side. ``sign`` is -1 for the right, +1 for the left."""
        points = []
        for index in order:
            before, after = (index - 1) % count, index
            vertex = segments[after].start
            turn = _turn(segments[before].direction, segments[after].direction)
            if sign < 0:
                incoming, outgoing = segments[before].direction, segments[after].direction
                offset_in, offset_out = negate(bodies[before]), negate(bodies[after])
                arc = (negate(raw[before]), negate(raw[after])) if support else None
                outer = turn < 0
            else:
                incoming, outgoing = negate(segments[after].direction), negate(segments[before].direction)
                offset_in, offset_out = bodies[after], bodies[before]
                arc = (raw[after], raw[before]) if support else None
                outer = turn > 0
            if turn == 0 or offset_in == offset_out:
                points += [_offset(vertex, offset_in), _offset(vertex, offset_out)]
                continue
            points += _join(shape, vertex, incoming, outgoing, offset_in, offset_out, outer, arc)
        return points

    if closed:
        right = side(-1, [*range(1, count), 0])
        left = side(1, [0, *range(count - 1, 0, -1)])
        return [right, left]
    first, last = segments[0], segments[-1]
    points = _cap_points(shape, first.start, first.direction, perps[0], start=True)
    points += side(-1, range(1, count))
    points += _cap_points(shape, last.end, last.direction, perps[-1], start=False)
    points += side(1, range(count - 1, 0, -1))
    return [points]


def dash_figures(segments, pattern, scale, *, shorten=0):
    """Split a figure into dashes measured in logical units along its segments.

    ``pattern`` alternates dash and gap lengths, starting with a dash at the
    figure's start; an odd pattern swaps roles on each repeat. Each dash end
    is pulled back by ``shorten`` (the pen width, for caps that extend past
    the end), leaving at least a zero-length dash. Dash ends are interpolated
    along the device segment and rounded to 28.4 points; a dash keeps the
    direction of the segment it lies on.
    """
    sx, sy = (abs(float(value)) * 16 for value in scale)
    lengths = [float(value) for value in pattern]
    if sum(lengths) <= 0:
        return [tuple(segments)]
    spans, offset = [], 0.0
    for segment in segments:
        (x0, y0), (x1, y1) = segment.start, segment.end
        length = hypot((x1 - x0) / sx if sx else 0.0, (y1 - y0) / sy if sy else 0.0)
        spans.append((offset, length, segment))
        offset += length
    total = offset
    intervals, position, index, drawing = [], 0.0, 0, True
    while position < total:
        length = lengths[index]
        if drawing:
            intervals.append((position, min(total, max(position, position + length - shorten))))
        position += length
        # Roles alternate through the pattern, so an odd pattern swaps them on repeat.
        drawing, index = not drawing, (index + 1) % len(lengths)
    figures = []

    def point(span, at):
        start, length, segment = span
        if at <= start:
            return segment.start
        if at >= start + length:
            return segment.end
        t = (at - start) / length
        (x0, y0), (x1, y1) = segment.start, segment.end
        return (floor(x0 + (x1 - x0) * t + 0.5), floor(y0 + (y1 - y0) * t + 0.5))

    for low, high in intervals:
        figure = []
        for span in spans:
            start, length, segment = span
            if start + length < low or start > high or (length and start + length == low):
                continue
            a, b = point(span, low), point(span, high)
            if a != b or not figure and low == high:
                figure.append(StrokeSegment(a, b, segment.direction))
            if start + length >= high:
                break
        if figure:
            figures.append(tuple(figure))
    return figures
