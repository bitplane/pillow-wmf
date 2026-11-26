"""Geometric pen outlines: end caps, joins and the cap perpendicular.

Extended geometric pens widen each figure into closed outlines that are
filled with the winding rule. Round caps with round joins keep the support
vertex construction shared with wide CreatePen strokes. Every other
combination places the body edges on a perpendicular vector chosen from the
realized pen polygon, so flat and square caps, bevels and miters share it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from fractions import Fraction
from math import atan2, floor, hypot, pi

from .geometry import Point, Polygon, StrokeSegment
from .numeric import float32
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
    # The linear world transform and logical width, under a rotating transform.
    transform: tuple[float, float, float, float] | None = None
    width: int = 0


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


def _pen_record(pen: PenGeometry) -> list[Point]:
    """The pen as native widening stores it: its first half, from a vertex to
    the opposite one, after the vertex that precedes the half around the pen."""
    vertices = list(pen.vertices)
    for index in range(1, len(vertices)):
        if vertices[index] == vertices[index - 1]:
            half = vertices[:index]
            break
    else:
        half = vertices[: len(vertices) // 2 + 1]
    return [(-half[-2][0], -half[-2][1]), *half]


def perpendicular(pen: PenGeometry, direction: Point) -> Point:
    """The half-width vector on the left of ``direction``, as native widening computes it.

    The record's first edge is the reverse of its last, so the signs of the
    two edges' cross products with the direction differ, and a binary search
    finds the draw vertex where the sign changes. The vector runs from half
    the adjacent edge before that vertex along the edge with the smaller
    cross product, by the share of the other cross product, divided with
    rounding at the half. A record found from a negative first edge negates
    the vector. Each component then snaps to a multiple of half a pixel,
    x ties toward zero and y ties away from it.
    """
    dx, dy = direction
    record = _pen_record(pen)

    def cross(index):
        start, end = record[index], record[index + 1]
        return (end[1] - start[1]) * dx - (end[0] - start[0]) * dy

    low, high = 0, len(record) - 2
    before, after = cross(low), cross(high)
    negative = before < 0
    while True:
        middle = low + (high - low) // 2
        value = cross(middle)
        if (value < 0) == negative:
            before = value
            if high == middle + 1:
                break
            low = middle
        else:
            after = value
            high = middle
            if middle == low + 1:
                break
    vertex = record[high]
    before, after = abs(before), abs(after)
    if after < before:
        edge = (record[high + 1][0] - vertex[0], record[high + 1][1] - vertex[1])
    else:
        edge = (vertex[0] - record[high - 1][0], vertex[1] - record[high - 1][1])
    total = before + after

    def share(component):
        if not total:
            return 0
        quotient, remainder = divmod(abs(component) * before, total)
        quotient += remainder >= total >> 1
        return quotient if component >= 0 else -quotient

    x = share(edge[0]) + vertex[0] - (edge[0] >> 1)
    y = share(edge[1]) + vertex[1] - (edge[1] >> 1)
    if not negative:
        x, y = -x, -y
    return ((x + 3 + (x < 0)) & ~7, (y + 4 - (y < 0)) & ~7)


def _perpendicular_edge(pen: PenGeometry, direction: Point) -> tuple[Point, Point]:
    """The pen edge whose keyframe interval holds ``direction``: its keyed vertex, then the other end.

    Vertex keys hold the integer vertex, edge keys a Fraction midpoint.
    """
    keys = _keyframes(pen)
    for index, (start_key, start) in enumerate(keys):
        end_key, end = keys[(index + 1) % len(keys)]
        if _cross(start_key, direction) >= 0 and _cross(direction, end_key) > 0:
            vertex, middle = (end, start) if isinstance(start[0], Fraction) else (start, end)
            return vertex, (int(2 * middle[0] - vertex[0]), int(2 * middle[1] - vertex[1]))
    raise AssertionError("Pen keys do not surround the direction")


def _perpendicular(pen: PenGeometry, direction: Point) -> Point:
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


def _world_vector(shape: PenShape, vector: Point) -> tuple[int, int]:
    """A 28.4 device vector taken back through the pen's world transform, in whole world units.

    An identity transform converts the 28.4 components directly, rounding
    down; others round the transformed components half away from zero.
    """
    if shape.transform is None and shape.scale == (1.0, 1.0):
        return (vector[0] >> 4, vector[1] >> 4)
    vx, vy = vector[0] / 16, vector[1] / 16
    if shape.transform is not None:
        m11, m12, m21, m22 = shape.transform
    else:
        (m11, m22), m12, m21 = shape.scale, 0.0, 0.0
    determinant = m11 * m22 - m12 * m21
    if not determinant:
        return (0, 0)
    return (
        _round_half_away((vx * m22 - vy * m21) / determinant),
        _round_half_away((vy * m11 - vx * m12) / determinant),
    )


def square_vector(shape: PenShape, direction: Point) -> Point:
    """Half-width extension along the line, for square caps.

    The 28.4 direction is scaled, in single precision, by half the pen's
    world width over the direction's length in whole world units, and each
    component rounded half away from zero.
    """
    wx, wy = _world_vector(shape, direction)
    if not wx and not wy:
        return (0, 0)
    length = float32(math.sqrt(float32(float32(float32(wy) * float32(wy)) + float32(float32(wx) * float32(wx)))))
    ratio = float32(float32(shape.width * 0.5) / length)
    return (
        _round_half_away(float32(float32(direction[0]) * ratio)),
        _round_half_away(float32(float32(direction[1]) * ratio)),
    )


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
    # The forward walker enters the pen's second half at its head vertex, so
    # a sweep reaching that vertex in index order also emits it at the end.
    ring = shape.pen.vertices
    head = ring[len(ring) // 2]
    previous = next(vertex for vertex in reversed(ring[: len(ring) // 2]) if vertex != head)
    if _cross(end, head) == 0 and _dot(end, head) > 0 and sweep(previous) < limit:
        vertices.append(head)
    return [(origin[0] + _cap(x, origin), origin[1] + _cap(y, origin)) for x, y in vertices]


def _offset(point, vector, sign=1):
    return (point[0] + sign * vector[0], point[1] + sign * vector[1])


def _miter(first: Point, first_direction, second: Point, second_direction) -> Point | None:
    denominator = _cross(first_direction, second_direction)
    if not denominator:
        return None
    t = Fraction(_cross((second[0] - first[0], second[1] - first[1]), second_direction), denominator)
    return tuple(floor(first[axis] + first_direction[axis] * t + Fraction(1, 2)) for axis in (0, 1))


def _round_half_away(value: float) -> int:
    return int(floor(abs(value) + 0.5)) * (1 if value >= 0 else -1)


def _miter_in_limit(shape: PenShape, vertex: Point, tip: Point) -> bool:
    """Whether the miter tip lies within the miter limit, measured in world units.

    The vertex-to-tip vector is taken back through the pen's world-to-device
    transform, rounded to whole world units, and its squared length compared,
    in single precision, with the square of half the pen width times the limit.
    """
    wx, wy = _world_vector(shape, (tip[0] - vertex[0], tip[1] - vertex[1]))
    threshold = float32(float32(float32(shape.width * 0.5) * float32(shape.miter_limit)) ** 2)
    return float32(float32(float32(wy) * float32(wy)) + float32(float32(wx) * float32(wx))) <= threshold


def _sweep(shape: PenShape, origin: Point, start: Point, start_edge, end_edge, through: Point, *, join=True) -> Polygon:
    """Inset pen vertices walked from one offset's pen edge to another's.

    Each edge is the pen edge holding an offset, as (keyed vertex, other
    end). The walk turns from ``start`` toward ``through``, from the start
    edge's leading end to the end edge's trailing end, and is empty when both
    offsets share an edge. A join's walk ending on the head of the pen's
    second half emits it twice when that head is the end edge's keyed vertex.
    """
    if set(start_edge) == set(end_edge):
        return []
    vertices = _polygon(shape.pen)
    count = len(vertices)
    step = 1 if (_cross(vertices[0], vertices[1]) < 0) == (_cross(start, through) < 0) else -1

    def ends(edge):
        first, second = (vertices.index(vertex) for vertex in edge)
        return (second, first) if (first + step) % count == second else (first, second)

    lead, trail = ends(start_edge)[0], ends(end_edge)[1]
    swept = [vertices[(lead + step * offset) % count] for offset in range(((trail - lead) * step) % count + 1)]
    ring = shape.pen.vertices
    if join and swept[-1] == ring[len(ring) // 2] == end_edge[0]:
        swept.append(swept[-1])
    return [_offset(origin, (_cap(x, origin), _cap(y, origin))) for x, y in swept]


def _negate_edge(edge):
    return tuple((-x, -y) for x, y in edge)


def _join(shape, vertex, incoming, outgoing, offset_in, offset_out, outer, arc=None, edges=None):
    """Points from ``vertex + offset_in`` to ``vertex + offset_out``.

    ``arc`` gives the pen vertices bounding a round join that is built on
    support vertices; it is exclusive of both and adds no inner sweep.
    ``edges`` gives the pen edges holding the two offsets, for other round
    joins.
    """
    start, end = _offset(vertex, offset_in), _offset(vertex, offset_out)
    if not outer:
        points = [start, vertex, end]
        if shape.join == JOIN_ROUND and arc is None:
            back = (-incoming[0], -incoming[1])
            points += _sweep(shape, vertex, offset_out, edges[1], edges[0], back) + [start, vertex, end]
        return points
    if arc is not None:
        return [start, *_arc(shape, vertex, *arc, incoming, exclusive=True), end]
    if shape.join == JOIN_MITER:
        tip = _miter(start, incoming, end, outgoing)
        if tip is not None and _miter_in_limit(shape, vertex, tip):
            return [start, tip, end]
    if shape.join == JOIN_ROUND:
        return [start, *_sweep(shape, vertex, offset_in, *edges, incoming), end]
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
    # Round caps sweep through the back of the line at the start, the front at
    # the end, between the pen edges holding the two offsets.
    through = (-direction[0], -direction[1]) if start else direction
    edge = _perpendicular_edge(shape.pen, direction)
    edges = (edge, _negate_edge(edge)) if start else (_negate_edge(edge), edge)
    return [_offset(point, first), *_sweep(shape, point, first, *edges, through, join=False), _offset(point, second)]


def outline(
    shape: PenShape,
    segments: tuple[StrokeSegment, ...],
    closed: bool,
    *,
    perps: list[Point] | None = None,
    seam: int = 0,
) -> list[Polygon]:
    """Native widened outlines of one figure, for winding-rule filling.

    ``perps`` overrides each segment's left half-width vector, as a box
    frame does by sharing one perpendicular between parallel edges. An open
    figure with a ``seam`` joint starts its outline at that joint's left side.
    """
    if perps is None:
        segments = tuple(segment for segment in segments if segment.direction != (0, 0))
    if not segments:
        return []
    perps = perps or [perpendicular(shape.pen, segment.direction) for segment in segments]
    count = len(segments)
    # Round joins between square caps keep wide CreatePen bodies: the body
    # passes through rounded support vertices and joins sweep between them.
    support = shape.join == JOIN_ROUND and shape.cap == CAP_SQUARE
    raw = [shape.pen.vertices[_support_index(shape.pen, *segment.direction)] for segment in segments] if support else []
    bodies = [(_body(x), _body(y)) for x, y in raw] if support else perps
    # Other round joins walk between the pen edges holding each offset, found
    # from the direction itself even where the perpendicular is mirrored.
    swept = shape.join == JOIN_ROUND and not support
    edges = [_perpendicular_edge(shape.pen, segment.direction) for segment in segments] if swept else []

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
                joint = (_negate_edge(edges[before]), _negate_edge(edges[after])) if swept else None
                outer = turn < 0
            else:
                incoming, outgoing = negate(segments[after].direction), negate(segments[before].direction)
                offset_in, offset_out = bodies[after], bodies[before]
                arc = (raw[after], raw[before]) if support else None
                joint = (edges[after], edges[before]) if swept else None
                outer = turn > 0
            if turn == 0 or offset_in == offset_out:
                points += [_offset(vertex, offset_in), _offset(vertex, offset_out)]
                continue
            points += _join(shape, vertex, incoming, outgoing, offset_in, offset_out, outer, arc, joint)
        return points

    if closed:
        right = side(-1, [*range(1, count), 0])
        left = side(1, [0, *range(count - 1, 0, -1)])
        return [right, left]
    first, last = segments[0], segments[-1]
    points = _cap_points(shape, first.start, first.direction, perps[0], start=True)
    points += side(-1, range(1, count))
    points += _cap_points(shape, last.end, last.direction, perps[-1], start=False)
    points += side(1, range(count - 1, seam, -1))
    return [side(1, range(seam, 0, -1)) + points]


def dash_figures(segments, pattern, scale, *, shorten=0, closed=False, logical=None):
    """Split a figure into dashes measured in logical units along its segments.

    Lengths divide the device segment by ``scale``, or with ``logical``,
    measure between the logical points it maps each device point back to.
    Returns ``(segments, seam)`` pairs. On a ``closed`` figure a dash still
    drawing at the closing vertex runs on into the first dash; ``seam`` is
    the index of the closing vertex's joint in that merged dash, else zero.

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
        return [(tuple(segments), 0)]

    def measure(start, end):
        if logical is not None:
            (x0, y0), (x1, y1) = logical(*start), logical(*end)
            return hypot(x1 - x0, y1 - y0)
        (x0, y0), (x1, y1) = start, end
        return hypot((x1 - x0) / sx if sx else 0.0, (y1 - y0) / sy if sy else 0.0)

    spans, offset = [], 0.0
    for segment in segments:
        length = measure(segment.start, segment.end)
        spans.append((offset, length, segment))
        offset += length
    total = offset
    intervals, position, index, drawing = [], 0.0, 0, True
    wraps = False
    while position < total:
        length = lengths[index]
        if drawing:
            intervals.append((position, min(total, max(position, position + length - shorten))))
            wraps = position + length >= total
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
                chord = segment.chord or (segment.end[0] - segment.start[0], segment.end[1] - segment.start[1])
                figure.append(replace(segment, start=a, end=b, curve=segment.curve and a == segment.start, chord=chord))
            if start + length >= high:
                break
        if figure:
            figures.append(tuple(figure))
    pairs = [(figure, 0) for figure in figures]
    if closed and wraps and len(figures) > 1:
        tail = figures.pop()
        pairs = [(tail + figures[0], len(tail))] + pairs[1:-1]
    return pairs
