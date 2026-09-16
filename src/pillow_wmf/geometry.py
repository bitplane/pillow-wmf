"""Device paths in 28.4 fixed point, retained through scan conversion."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from itertools import pairwise
from math import floor

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


def flatten_cubic(control: tuple[Point, Point, Point, Point]) -> Polygon:
    """Subdivide a cubic to a half-pixel chord-error bound.

    A cubic's deviation is bounded by 3/4 of its largest second difference.
    Eight fixed-point units are half a pixel, hence 3 * difference <= 32.
    Subdivision uses exact dyadic values; only emitted vertices are rounded.
    """
    points: Polygon = []

    def recurse(curve):
        deviation = max(
            abs(curve[index][axis] - 2 * curve[index + 1][axis] + curve[index + 2][axis])
            for index in (0, 1)
            for axis in (0, 1)
        )
        if 3 * deviation <= 32:
            points.append((floor(curve[3][0] + 0.5), floor(curve[3][1] + 0.5)))
            return

        def midpoint(a, b):
            return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2

        a, b, c = (midpoint(curve[i], curve[i + 1]) for i in range(3))
        d, e = midpoint(a, b), midpoint(b, c)
        middle = midpoint(d, e)
        recurse((curve[0], a, d, middle))
        recurse((middle, e, c, curve[3]))

    recurse(control)
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
            if (cross < 0) if y2 > y1 else (cross > 0):
                winding += 1 if y2 > y1 else -1
    return winding != 0 if fill_mode == 2 else winding % 2 != 0
