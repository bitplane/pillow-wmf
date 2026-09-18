"""Immutable region algebra and application clipping.

The bitmap bounds are applied when pixels are written. They must not trim an
application clip: a later OffsetClipRgn can move an off-surface clip into view.
"""

from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import cached_property
from itertools import pairwise
from math import ceil, floor

type Rectangle = tuple[int, int, int, int]


@dataclass(frozen=True)
class RegionMask:
    """Finite union of half-open rectangles, indexed as disjoint y bands."""

    bands: tuple[tuple[int, int, tuple[int, ...]], ...] = ()

    @classmethod
    def from_rectangles(cls, rectangles):
        events = defaultdict(list)
        for left, top, right, bottom in rectangles:
            left, right = sorted((left, right))
            top, bottom = sorted((top, bottom))
            if left != right and top != bottom:
                events[top].append(((left, right), 1))
                events[bottom].append(((left, right), -1))
        active = Counter()
        bands = []
        previous = None
        for y in sorted(events):
            if active and previous is not None:
                endpoints = []
                for left, right in sorted(active):
                    if endpoints and left <= endpoints[-1]:
                        endpoints[-1] = max(endpoints[-1], right)
                    else:
                        endpoints.extend((left, right))
                endpoints = tuple(endpoints)
                if bands and bands[-1][1] == previous and bands[-1][2] == endpoints:
                    bands[-1] = (bands[-1][0], y, endpoints)
                else:
                    bands.append((previous, y, endpoints))
            for interval, change in events[y]:
                active[interval] += change
                if not active[interval]:
                    del active[interval]
            previous = y
        return cls(tuple(bands))

    @cached_property
    def tops(self):
        return tuple(top for top, _, _ in self.bands)

    def contains(self, x, y):
        index = bisect_right(self.tops, y) - 1
        if index < 0:
            return False
        _, bottom, endpoints = self.bands[index]
        return y < bottom and bisect_right(endpoints, x) % 2 == 1

    def offset(self, dx, dy):
        return RegionMask(
            tuple((top + dy, bottom + dy, tuple(x + dx for x in endpoints)) for top, bottom, endpoints in self.bands)
        )

    def rectangles(self):
        for top, bottom, endpoints in self.bands:
            for left, right in zip(endpoints[::2], endpoints[1::2], strict=True):
                yield left, top, right, bottom

    def transformed(self, point):
        return RegionMask.from_rectangles(
            (*point(left, top), *point(right, bottom)) for left, top, right, bottom in self.rectangles()
        )

    def difference(self, other):
        """Subtract bands without introducing pixel-sized storage."""
        rectangles = []
        for top, bottom, endpoints in self.bands:
            boundaries = sorted({top, bottom} | {y for band in other.bands for y in band[:2] if top < y < bottom})
            for y0, y1 in pairwise(boundaries):
                index = bisect_right(other.tops, y0) - 1
                cuts = other.bands[index][2] if index >= 0 and y0 < other.bands[index][1] else ()
                for left, right in zip(endpoints[::2], endpoints[1::2], strict=True):
                    cursor = left
                    for start, end in zip(cuts[::2], cuts[1::2], strict=True):
                        if end <= cursor:
                            continue
                        if start >= right:
                            break
                        if cursor < start:
                            rectangles.append((cursor, y0, start, y1))
                        cursor = max(cursor, end)
                    if cursor < right:
                        rectangles.append((cursor, y0, right, y1))
        return RegionMask.from_rectangles(rectangles)

    def frame(self, width, height, *, point=None):
        """Inner rectangular border: subtract the rectangular erosion.

        Dilating the complement includes holes and concave corners, without
        exposing the artificial boundaries between a region's scan bands.
        Half-integral device thickness represents an odd full footprint;
        the extra pixel belongs to the left/top side of the inner border.
        """
        if not self.bands or not width or not height:
            return RegionMask()
        width, height = abs(width), abs(height)
        x0, x1, y0, y1 = floor(width), ceil(width), floor(height), ceil(height)
        left = min(e[0] for _, _, e in self.bands)
        right = max(e[-1] for _, _, e in self.bands)
        top, bottom = self.bands[0][0], self.bands[-1][1]
        outside = RegionMask.from_rectangles(((left - 1, top - 1, right + 1, bottom + 1),))
        complement = outside.difference(self)
        rectangles = []
        for left, top, right, bottom in complement.rectangles():
            if point is not None:
                left, top = point(left, top)
                right, bottom = point(right, bottom)
                left, right = sorted((left, right))
                top, bottom = sorted((top, bottom))
            # Widen even collapsed gaps: native framing transforms the source
            # boundary path, retaining seams that disappear from a device union.
            # A collapsed area is a retraced segment with flat ends, not an
            # area to dilate beyond those ends. A collapsed point has no edge.
            if left == right and top == bottom:
                continue
            rectangles.append(
                (
                    left - (x0 if top != bottom else 0),
                    top - (y0 if left != right else 0),
                    right + (x1 if top != bottom else 0),
                    bottom + (y1 if left != right else 0),
                )
            )
        expanded = RegionMask.from_rectangles(rectangles)
        region = self.transformed(point) if point is not None else self
        return region.difference(region.difference(expanded))


@dataclass(frozen=True)
class ClipRegion:
    constraints: tuple[tuple[bool, Rectangle], ...] = ()
    mask: RegionMask | None = None

    def contains(self, x: int, y: int) -> bool:
        return (self.mask is None or self.mask.contains(x, y)) and all(
            (left <= x < right and top <= y < bottom) == include
            for include, (left, top, right, bottom) in self.constraints
        )

    def intersect(self, rectangle: Rectangle) -> "ClipRegion":
        return ClipRegion(self.constraints + ((True, rectangle),), self.mask)

    def exclude(self, rectangle: Rectangle) -> "ClipRegion":
        return ClipRegion(self.constraints + ((False, rectangle),), self.mask)

    def offset(self, dx: int, dy: int) -> "ClipRegion":
        return ClipRegion(
            tuple(
                (include, (left + dx, top + dy, right + dx, bottom + dy))
                for include, (left, top, right, bottom) in self.constraints
            ),
            self.mask.offset(dx, dy) if self.mask is not None else None,
        )
