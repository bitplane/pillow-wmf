"""Native path widening: the exact outlines WidenPath builds.

Each figure is walked line by line. A Bézier is flattened as it is walked:
its first piece takes the curve's start tangent and its last piece the end
tangent as the direction that chooses pen vectors, and the joints between
its pieces are always round. Every other joint uses the pen's own join.

Two point lists grow on either side of the figure. Each line contributes a
vector on its left (``+``) and right (``-``) side: the pen perpendicular, or,
for round joins and caps of a pen with round joins and round or square caps,
the rounded pen vertex the line's direction selects (its draw vertex). A
closed figure becomes its left side and its reversed right side; an open one
becomes a single outline, its start cap first and its right side reversed
last. Round joins and caps walk pen vertices between draw vertices, moved one
unit toward the vertex when the joint lies on a whole pixel.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .geometry import Point, StrokeSegment, flatten_cubic
from .numeric import float32
from .widen import CAP_FLAT, CAP_ROUND, CAP_SQUARE, JOIN_BEVEL, JOIN_ROUND, PenShape, _miter_in_limit, _pen_record
from .widen import square_vector as _square_vector

# A figure as WidenPath reads it: start point, commands (a line's end point,
# or a Bézier's three control points) and whether it is closed.
Figure = tuple[Point, tuple, bool]


def _round8_draw(value: int) -> int:
    return (value - (value < 0) + 4) & ~7


@dataclass
class _Line:
    """One flattened piece: its chord and the direction that chooses pen vectors."""

    chord: Point
    tangent: Point
    vertex: int = 0
    negative: bool = False
    before: int = 0
    after: int = 0
    found: bool = False
    _perp: Point | None = field(default=None, repr=False)
    _draw: Point | None = field(default=None, repr=False)
    _square: Point | None = field(default=None, repr=False)


class _Widener:
    def __init__(self, shape: PenShape):
        self.shape = shape
        self.record = _pen_record(shape.pen)
        self.support = shape.join == JOIN_ROUND and shape.cap in (CAP_ROUND, CAP_SQUARE)
        self.figures: list[tuple[list[Point], bool]] = []
        self.left: list[Point] = []
        self.right: list[Point] = []
        self.vertex: Point = (0, 0)

    # Pen vectors

    def _find(self, line: _Line) -> None:
        """The draw vertex: the record vertex where edge cross products change sign."""
        if line.found:
            return
        record = self.record
        tx, ty = line.tangent

        def cross(index):
            start, end = record[index], record[index + 1]
            return (end[1] - start[1]) * tx - (end[0] - start[0]) * ty

        first = cross(0)
        negative = first < 0
        before, after = first, -first
        low, high = 0, len(record) - 2
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
        line.vertex, line.negative = high, negative
        line.before, line.after, line.found = abs(before), abs(after), True

    def _raw(self, index: int, negative: bool) -> Point:
        x, y = self.record[index]
        return (-x, -y) if negative else (x, y)

    def draw(self, line: _Line) -> Point:
        if line._draw is None:
            self._find(line)
            x, y = self._raw(line.vertex, line.negative)
            line._draw = (_round8_draw(x), _round8_draw(y))
        return line._draw

    def perp(self, line: _Line) -> Point:
        if line._perp is None:
            self._find(line)
            record, index = self.record, line.vertex
            before, after = line.before, line.after
            vertex = record[index]
            if after < before:
                edge = (record[index + 1][0] - vertex[0], record[index + 1][1] - vertex[1])
            else:
                edge = (vertex[0] - record[index - 1][0], vertex[1] - record[index - 1][1])
            total = before + after

            def share(component):
                if not total:
                    return 0
                quotient, remainder = divmod(abs(component) * before, total)
                quotient += remainder >= total >> 1
                return quotient if component >= 0 else -quotient

            x = share(edge[0]) + vertex[0] - (edge[0] >> 1)
            y = share(edge[1]) + vertex[1] - (edge[1] >> 1)
            if line.negative:
                x, y = -x, -y
            line._perp = ((x + 3 + (x < 0)) & ~7, (y + 4 - (y < 0)) & ~7)
        return line._perp

    def square(self, line: _Line) -> Point:
        if line._square is None:
            line._square = _square_vector(self.shape, line.tangent)
        return line._square

    # Output

    def add_left(self, vector: Point, sign: int = 1) -> None:
        v = self.vertex
        self.left.append((v[0] + sign * vector[0], v[1] + sign * vector[1]))

    def add_right(self, vector: Point) -> None:
        v = self.vertex
        self.right.append((v[0] - vector[0], v[1] - vector[1]))

    def _nice(self, target: list[Point], raw: Point, negative: bool, sign: int) -> None:
        """A pen vertex, moved one unit toward the joint when it lies on a whole pixel."""
        v = self.vertex
        x, y = (-raw[0], -raw[1]) if negative else raw
        x, y = sign * x, sign * y
        if not (v[0] | v[1]) & 15:
            x -= (x > 0) - (x < 0)
            y -= (y > 0) - (y < 0)
        target.append((v[0] + x, v[1] + y))

    def _walk(self, first: _Line, second: _Line, forward: bool, include_first: bool, include_last: bool) -> int:
        """Pen vertices from one line's draw vertex to another's (cptAddRound)."""
        self._find(first)
        self._find(second)
        if first.vertex == second.vertex and first.negative == second.negative:
            return 0
        record, last = self.record, len(self.record) - 1
        index, negative, count = first.vertex, first.negative, 0
        if forward:
            target, sign = self.left, 1
            if include_first and first.before <= first.after:
                self._nice(target, record[index], negative, sign)
            index += 1
            while not (index <= second.vertex and negative == second.negative):
                while index < last:
                    self._nice(target, record[index], negative, sign)
                    count += 1
                    index += 1
                negative, index = not negative, 1
            while index < second.vertex:
                self._nice(target, record[index], negative, sign)
                count += 1
                index += 1
            if include_last and second.after < second.before:
                self._nice(target, record[index], negative, sign)
        else:
            target, sign = self.right, -1
            if include_first and first.after < first.before:
                self._nice(target, record[index], negative, sign)
            index -= 1
            while not (index >= second.vertex and negative == second.negative):
                while index > 1:
                    self._nice(target, record[index], negative, sign)
                    count += 1
                    index -= 1
                negative, index = not negative, last
            while index > second.vertex:
                self._nice(target, record[index], negative, sign)
                count += 1
                index -= 1
            if include_last and second.before <= second.after:
                self._nice(target, record[index], negative, sign)
        return count

    def _round_cap(self, line: _Line, start: bool) -> None:
        """Half a turn of pen vertices around an end (vAddRoundEndCap)."""
        self._find(line)
        record, last = self.record, len(self.record) - 1
        negative = line.negative != start
        index = line.vertex
        if not self.support and line.before <= line.after:
            self._nice(self.left, record[index], negative, 1)
        index += 1
        while index > line.vertex:
            while index < last:
                self._nice(self.left, record[index], negative, 1)
                index += 1
            negative, index = not negative, 1
        while index < line.vertex:
            self._nice(self.left, record[index], negative, 1)
            index += 1
        if not self.support and line.after < line.before:
            self._nice(self.left, record[index], negative, 1)

    # Joints and ends

    @staticmethod
    def _turns_left(a: Point, b: Point) -> bool:
        if (b[0] ^ a[0] ^ b[1] ^ a[1]) < 0:
            return (a[0] < 0) != (b[1] < 0)
        return a[0] * b[1] < b[0] * a[1]

    def join(self, incoming: _Line, outgoing: _Line, curve: bool) -> None:
        join = self.shape.join
        if join == JOIN_ROUND or curve:
            self.round_join(incoming, outgoing, curve)
            return
        left = self._turns_left(incoming.tangent, outgoing.tangent)
        a, b = self.perp(incoming), self.perp(outgoing)
        self.add_right(a)
        self.add_left(a)
        if a == b:
            return
        if join == JOIN_BEVEL:
            (self.right if left else self.left).append(self.vertex)
            self.add_left(b)
            self.add_right(b)
            return
        tip = _intersect(a, incoming.chord, b, outgoing.chord)
        if tip is not None and _miter_in_limit(self.shape, (0, 0), tip):
            if left:
                self.add_left(tip)
            else:
                self.add_right(tip)
        (self.right if left else self.left).append(self.vertex)
        self.add_right(b)
        self.add_left(b)

    def round_join(self, incoming: _Line, outgoing: _Line, curve: bool) -> None:
        left = self._turns_left(incoming.tangent, outgoing.tangent)
        drawn = self.support or curve
        a = self.draw(incoming) if drawn else self.perp(incoming)
        b = self.draw(outgoing) if drawn else self.perp(outgoing)
        ends = not drawn
        self.add_left(a)
        self.add_right(a)
        if a == b:
            return
        if not left:
            count = self._walk(incoming, outgoing, False, ends, ends)
            self.left.append(self.vertex)
            if not self.support:
                self.add_left(b)
                if count:
                    self._walk(outgoing, incoming, True, ends, ends)
                self.add_left(a)
                self.left.append(self.vertex)
        else:
            count = self._walk(incoming, outgoing, True, ends, ends)
            self.right.append(self.vertex)
            if not self.support:
                self.add_right(b)
                if count:
                    self._walk(outgoing, incoming, False, ends, ends)
                self.add_right(a)
                self.right.append(self.vertex)
        self.add_left(b)
        self.add_right(b)

    def start_cap(self, line: _Line) -> None:
        cap = self.shape.cap
        if cap == CAP_ROUND:
            vector = self.draw(line) if self.support else self.perp(line)
            self.add_left(vector, -1)
            self._round_cap(line, True)
            self.add_left(vector)
        elif cap == CAP_SQUARE:
            sx, sy = self.square(line)
            px, py = self.perp(line)
            self.add_left((-sx - px, -sy - py))
            self.add_left((-sx + px, -sy + py))
        elif cap == CAP_FLAT:
            perp = self.perp(line)
            self.add_left(perp, -1)
            self.add_left(perp)

    def end_cap(self, line: _Line) -> None:
        cap = self.shape.cap
        if cap == CAP_ROUND:
            vector = self.draw(line) if self.support else self.perp(line)
            self.add_left(vector)
            self._round_cap(line, False)
            self.add_left(vector, -1)
        elif cap == CAP_SQUARE:
            sx, sy = self.square(line)
            px, py = self.perp(line)
            self.add_left((sx + px, sy + py))
            self.add_left((sx - px, sy - py))
        elif cap == CAP_FLAT:
            perp = self.perp(line)
            self.add_left(perp)
            self.add_left(perp, -1)

    # Figures

    def figure(self, segments: tuple[StrokeSegment, ...], closed: bool, seam: int = 0, *, dash: bool = False) -> None:
        """Widen one figure of segments carrying native directions and joint kinds.

        A ``seam`` is the closing joint of a closed figure whose last dash runs
        on into its first: the right side up to it is moved to the front. A
        ``dash`` of zero length still has caps, in its segment's direction.
        """
        start = segments[0].start
        lines = [
            (
                segment.start,
                _Line(segment.chord or chord, segment.direction if segment.direction != (0, 0) else chord),
                segment.curve,
            )
            for segment in segments
            if (chord := (segment.end[0] - segment.start[0], segment.end[1] - segment.start[1])) != (0, 0)
        ]
        position = segments[-1].end
        if closed and position != start:
            chord = (start[0] - position[0], start[1] - position[1])
            lines.append((position, _Line(chord, chord), False))
        if not lines:
            if dash and segments[0].direction != (0, 0):
                lines = [(start, _Line((0, 0), segments[0].direction), False)]
            else:
                # A figure of one point: round caps draw the pen there.
                if self.shape.cap == CAP_ROUND:
                    line = _Line((16, 0), (16, 0))
                    self.vertex, self.left = start, []
                    self.start_cap(line)
                    self.end_cap(line)
                    self.figures.append((self.left, True))
                return
        self.left, self.right = [], []
        front = 0
        for index, ((vertex, line, curve), (_, previous, _)) in enumerate(zip(lines[1:], lines, strict=False), 1):
            self.vertex = vertex
            self.join(previous, line, curve and index != seam)
            if index == seam:
                front = len(self.right)
        if closed:
            self.vertex = start
            self.join(lines[-1][1], lines[0][1], False)
            self.figures.append((self.left, True))
            self.figures.append((self.right[::-1], True))
            return
        self.vertex = position
        self.end_cap(lines[-1][1])
        body = self.left + self.right[front:][::-1]
        moved = self.right[:front][::-1]
        self.vertex, self.left = start, []
        self.start_cap(lines[0][1])
        self.figures.append((moved + self.left + body, True))


def _intersect(a: Point, first: Point, b: Point, second: Point) -> Point | None:
    """The miter tip relative to the joint, in single precision (bComputeIntersect)."""
    f = float32
    denominator = f(f(f(first[1]) * f(second[0])) + f(f(first[0]) * f(-second[1])))
    if denominator == 0:
        return None
    numerator = f(f(f(b[1] - a[1]) * f(second[0])) + f(f(b[0] - a[0]) * f(-second[1])))
    t = f(numerator / denominator)
    x, y = (_round_half_away(f(t * f(component))) for component in first)
    limit = 0x3FFFFFFF
    if not (-limit <= x < limit and -limit <= y < limit):
        return None
    if not (-limit <= a[0] + x < limit and -limit <= a[1] + y < limit):
        return None
    return (a[0] + x, a[1] + y)


def _round_half_away(value: float) -> int:
    magnitude = int(abs(value) + 0.5)
    return magnitude if value >= 0 else -magnitude


def segments(path) -> tuple[StrokeSegment, ...]:
    """A device path's flattened segments as the native widener walks them.

    A Bézier's first piece takes its start tangent and its last piece its end
    tangent (or the piece's own chord where that is zero), and the joints
    between its pieces are curve joints.
    """
    result = []
    for command in path.commands:
        position = command[0]
        if len(command) == 2:
            result.append(StrokeSegment.line(position, command[1]))
            continue
        p0, p1, p2, p3 = command
        points = flatten_cubic(command)
        if len(points) == 1:
            result.append(StrokeSegment.line(p0, p3))
            continue
        for index, point in enumerate(points):
            if index == 0:
                tangent = (p1[0] - p0[0], p1[1] - p0[1])
            elif index == len(points) - 1:
                tangent = (p3[0] - p2[0], p3[1] - p2[1])
            else:
                tangent = (point[0] - position[0], point[1] - position[1])
            result.append(StrokeSegment(position, point, tangent, index > 0))
            position = point
    return tuple(result)


def widen(shape: PenShape, paths: Iterable) -> list[tuple[list[Point], bool]]:
    """WidenPath's figures for device paths (``DevicePath``) widened by ``shape``."""
    widener = _Widener(shape)
    for path in paths:
        figure = segments(path)
        if figure:
            widener.figure(figure, path.closed)
    return widener.figures


def widen_dashes(shape: PenShape, dashes: Iterable[tuple[tuple[StrokeSegment, ...], int]]):
    """WidenPath's figures for the dashes of a styled pen, as ``(segments, seam)`` pairs."""
    widener = _Widener(shape)
    for figure, seam in dashes:
        if figure:
            widener.figure(figure, False, seam, dash=True)
    return widener.figures
