"""Immutable application clipping in device coordinates.

The bitmap bounds are applied when pixels are written. They must not trim an
application clip: a later OffsetClipRgn can move an off-surface clip into view.
"""

from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import cached_property

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
