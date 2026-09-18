"""Device paths in 28.4 fixed point, retained through scan conversion."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from itertools import pairwise

type Point = tuple[int, int]
type Polygon = list[Point]
type Cubic = tuple[Point, Point, Point, Point]


@dataclass(frozen=True)
class StrokeSegment:
    start: Point
    end: Point
    direction: Point

    @classmethod
    def line(cls, start: Point, end: Point):
        return cls(start, end, (end[0] - start[0], end[1] - start[1]))


@dataclass(frozen=True)
class DevicePath:
    """Connected line/cubic commands, retained until the stroke is realized."""

    commands: tuple[tuple[Point, Point] | Cubic, ...]
    closed: bool = False

    @classmethod
    def polyline(cls, points, *, closed=False):
        points = tuple(points)
        return cls(tuple(zip(points, points[1:] + (points[:1] if closed else ()))), closed)

    @classmethod
    def rectangle(cls, left: int, top: int, right: int, bottom: int):
        """A closed rectangle in fixed device coordinates, starting top-right."""
        return cls.polyline(((right, top), (left, top), (left, bottom), (right, bottom)), closed=True)

    @cached_property
    def segments(self) -> tuple[StrokeSegment, ...]:
        segments = []
        for command in self.commands:
            points = [command[0]] + (flatten_cubic(command) if len(command) == 4 else [command[1]])
            for start, end in pairwise(points):
                segments.append(StrokeSegment.line(start, end))
            if len(command) == 4 and len(points) > 2:
                # A subdivided cubic retains its endpoint tangents for pen
                # support; a cubic reduced to one chord has no tangent joins.
                start = command[0]
                after = next((point for point in command[1:] if point != start), start)
                first = len(segments) - len(points) + 1
                segments[first] = StrokeSegment(start, segments[first].end, (after[0] - start[0], after[1] - start[1]))
                end = command[-1]
                before = next((point for point in reversed(command[:-1]) if point != end), end)
                segments[-1] = StrokeSegment(segments[-1].start, end, (end[0] - before[0], end[1] - before[1]))
        # Repeated vertices do not interrupt a join or choose an end-cap
        # direction. Retain one segment for a wholly zero-length stroke.
        nonzero = tuple(segment for segment in segments if segment.start != segment.end)
        return nonzero or tuple(segments[:1])

    @cached_property
    def vertices(self) -> Polygon:
        return [self.segments[0].start, *(segment.end for segment in self.segments)] if self.segments else []

    def flattened(self) -> DevicePath:
        points = self.vertices[:-1] if self.closed else self.vertices
        return DevicePath.polyline(points, closed=self.closed)


_INITIAL_CURVE_PRECISION = 10
_CURVE_PRECISION = 13
_INITIAL_CURVE_ERROR = 0xFFC0
_CURVE_ERROR = _INITIAL_CURVE_ERROR << (_CURVE_PRECISION - _INITIAL_CURVE_PRECISION)
_LARGE_CURVE_PRECISION = 28
_LARGE_CURVE_ERROR = 64 << _LARGE_CURVE_PRECISION
_COARSE_CURVE_ERROR = 196608 << _LARGE_CURVE_PRECISION
_SMALL_CURVE_SPAN = 16384


@dataclass
class _CurveAxis:
    """One axis of an adaptive forward-difference cubic.

    Curvature terms describe the end and start of the current interval.
    Keeping them alongside position and advance lets us walk the curve or
    change interval size without repeatedly evaluating its polynomial.
    """

    position: int
    advance: int
    end_curvature: int
    start_curvature: int
    precision: int = _INITIAL_CURVE_PRECISION

    @classmethod
    def from_controls(cls, a: int, b: int, c: int, d: int, *, precision: int = _INITIAL_CURVE_PRECISION):
        scale = 1 << precision
        return cls(a * scale, (d - a) * scale, 6 * (b - 2 * c + d) * scale, 6 * (a - 2 * b + c) * scale, precision)

    @property
    def error(self) -> int:
        return max(abs(self.start_curvature), abs(self.end_curvature))

    @property
    def parent_error(self) -> int:
        return 4 * max(abs(self.start_curvature), abs(2 * self.end_curvature - self.start_curvature))

    @property
    def rounded_position(self) -> int:
        return (self.position + (1 << (self.precision - 1))) >> self.precision

    def controls(self) -> tuple[int, int, int, int]:
        """Recover rounded controls for one coarse interval of a large curve."""
        common = 6 * self.advance - self.end_curvature
        numerators = (common - 2 * self.start_curvature, 2 * common - self.start_curvature)
        # The inverse basis divides towards zero, before fixed-point rounding.
        handles = tuple(value // 18 if value >= 0 else -(-value // 18) for value in numerators)
        rounding = 1 << (self.precision - 1)
        return tuple((self.position + delta + rounding) >> self.precision for delta in (0, *handles, self.advance))

    def step(self):
        self.position += self.advance
        self.advance += self.end_curvature
        self.end_curvature, self.start_curvature = 2 * self.end_curvature - self.start_curvature, self.end_curvature

    def halve_initial(self, deferred_shift: int):
        # Delay rescaling the curvature terms while finding the first step.
        self.end_curvature = (self.end_curvature + self.start_curvature) >> 1
        self.advance = (self.advance - (self.end_curvature >> deferred_shift)) >> 1

    def finish_initializing(self, deferred_shift: int):
        extra_bits = _CURVE_PRECISION - _INITIAL_CURVE_PRECISION
        self.precision = _CURVE_PRECISION
        self.position <<= extra_bits
        self.advance <<= extra_bits
        shift = deferred_shift - extra_bits
        if shift >= 0:
            self.end_curvature >>= shift
            self.start_curvature >>= shift
        else:
            self.end_curvature <<= -shift
            self.start_curvature <<= -shift

    def halve(self):
        self.end_curvature = (self.end_curvature + self.start_curvature) >> 3
        self.advance = (self.advance - self.end_curvature) >> 1
        self.start_curvature >>= 2

    def double(self):
        self.advance = 2 * self.advance + self.end_curvature
        self.start_curvature *= 4
        self.end_curvature = 8 * self.end_curvature - self.start_curvature


def _advance_curve(x: _CurveAxis, y: _CurveAxis, steps: int, error: int) -> int:
    """Walk one interval, then adapt the next interval on the dyadic grid."""
    x.step()
    y.step()
    steps -= 1
    if not steps:
        return 0
    if max(x.error, y.error) > error:
        x.halve()
        y.halve()
        steps *= 2
    while steps % 2 == 0 and max(x.parent_error, y.parent_error) <= error:
        x.double()
        y.double()
        steps //= 2
    return steps


def _initial_curve_steps(x: _CurveAxis, y: _CurveAxis, error: int) -> int:
    steps = 1
    while max(x.error, y.error) > error:
        x.halve()
        y.halve()
        steps *= 2
    return steps


def _flatten_large_cubic(control: Cubic) -> Polygon:
    """GDI's two-level walk: round coarse controls, then flatten each interval."""
    x, y = (_CurveAxis.from_controls(*(p[axis] for p in control), precision=_LARGE_CURVE_PRECISION) for axis in (0, 1))
    steps = _initial_curve_steps(x, y, _COARSE_CURVE_ERROR)
    points: Polygon = []
    while steps:
        inner_x = _CurveAxis.from_controls(*x.controls(), precision=_LARGE_CURVE_PRECISION)
        inner_y = _CurveAxis.from_controls(*y.controls(), precision=_LARGE_CURVE_PRECISION)
        inner_steps = _initial_curve_steps(inner_x, inner_y, _LARGE_CURVE_ERROR)
        while inner_steps:
            inner_steps = _advance_curve(inner_x, inner_y, inner_steps, _LARGE_CURVE_ERROR)
            points.append((inner_x.rounded_position, inner_y.rounded_position))
        steps = _advance_curve(x, y, steps, _COARSE_CURVE_ERROR)
    return points


def flatten_cubic(control: Cubic) -> Polygon:
    """Flatten using GDI's integer adaptive curve walk; see gdi-curves.md.

    Arithmetic shifts during step changes are observable. Exact recursive
    subdivision can choose identical sample parameters but different vertices.
    """
    if any(max(p[axis] for p in control) - min(p[axis] for p in control) >= _SMALL_CURVE_SPAN for axis in (0, 1)):
        return _flatten_large_cubic(control)
    x, y = (_CurveAxis.from_controls(*(point[axis] for point in control)) for axis in (0, 1))
    deferred_shift = 0
    steps = 1
    while max(x.error, y.error) > (_INITIAL_CURVE_ERROR << deferred_shift):
        deferred_shift += 2
        x.halve_initial(deferred_shift)
        y.halve_initial(deferred_shift)
        steps *= 2
    x.finish_initializing(deferred_shift)
    y.finish_initializing(deferred_shift)

    points: Polygon = []
    while steps:
        steps = _advance_curve(x, y, steps, _CURVE_ERROR)
        points.append((x.rounded_position, y.rounded_position))
    return points


def contains(polygons: tuple[Polygon, ...], x: int, y: int, *, fill_mode: int = 1) -> bool:
    """Evaluate alternate or winding coverage at a device-pixel coordinate."""
    px, py = x * 16, y * 16
    winding = 0
    for polygon in polygons:
        for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
            if (y1 > py) == (y2 > py):
                continue
            cross = (px - x1) * (y2 - y1) - (py - y1) * (x2 - x1)
            direction = 1 if y2 > y1 else -1
            if cross * direction < 0:
                winding += direction
    return winding != 0 if fill_mode == 2 else winding % 2 != 0
