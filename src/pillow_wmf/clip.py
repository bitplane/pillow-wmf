"""Immutable region algebra and application clipping.

The bitmap bounds are applied when pixels are written. They must not trim an
application clip: a later OffsetClipRgn can move an off-surface clip into view.
"""

from bisect import bisect_left, bisect_right
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

    def spans(self, y):
        """Disjoint half-open intervals on a scan line."""
        index = bisect_right(self.tops, y) - 1
        if index >= 0:
            _, bottom, endpoints = self.bands[index]
            if y < bottom:
                yield from zip(endpoints[::2], endpoints[1::2], strict=True)

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

    def intersection(self, other):
        return self.difference(self.difference(other))

    def _edit_rows(self, top, bottom, edit, fill=None):
        """Apply ``edit`` to each row's endpoints in ``[top, bottom)``.

        Rows outside the range are shared unchanged. Uncovered rows in range
        receive ``fill`` when given. The result keeps ``from_rectangles``'
        canonical form: no empty bands and no equal adjacent bands.
        """
        bands = self.bands
        start = max(0, bisect_right(self.tops, top) - 1)
        if start < len(bands) and bands[start][1] <= top:
            start += 1
        end = start
        edited = []
        cursor = top
        while end < len(bands) and bands[end][0] < bottom:
            band_top, band_bottom, endpoints = bands[end]
            if band_top < top:
                edited.append((band_top, top, endpoints))
                band_top = top
            if fill is not None and cursor < band_top:
                edited.append((cursor, band_top, fill))
            edited.append((band_top, min(band_bottom, bottom), edit(endpoints)))
            if band_bottom > bottom:
                edited.append((bottom, band_bottom, endpoints))
            cursor = band_bottom
            end += 1
        if fill is not None and cursor < bottom:
            edited.append((cursor, bottom, fill))
        # Re-merge with one unchanged neighbour on each side.
        head, tail = bands[: max(0, start - 1)], bands[end + 1 :]
        merged = []
        for band in (*bands[max(0, start - 1) : start], *edited, *bands[end : end + 1]):
            if not band[2] or band[0] == band[1]:
                continue
            if merged and merged[-1][1] == band[0] and merged[-1][2] == band[2]:
                merged[-1] = (merged[-1][0], band[1], band[2])
            else:
                merged.append(band)
        return RegionMask((*head, *merged, *tail))

    def with_rectangle(self, rectangle: Rectangle):
        """Union with one ordered, non-empty half-open rectangle."""
        left, top, right, bottom = rectangle

        def edit(endpoints):
            low = bisect_left(endpoints, left)
            high = bisect_right(endpoints, right)
            # Touching intervals merge, as in ``from_rectangles``.
            start = endpoints[low - 1] if low % 2 else left
            end = endpoints[high] if high % 2 else right
            return (*endpoints[: low - low % 2], start, end, *endpoints[high + high % 2 :])

        return self._edit_rows(top, bottom, edit, (left, right))

    def without_rectangle(self, rectangle: Rectangle):
        """Difference with one ordered, non-empty half-open rectangle."""
        left, top, right, bottom = rectangle

        def edit(endpoints):
            low = bisect_right(endpoints, left)
            high = bisect_left(endpoints, right)
            head = endpoints[:low]
            if low % 2:
                head = head[:-1] if head[-1] == left else (*head, left)
            tail = endpoints[high:]
            if high % 2:
                tail = tail[1:] if tail[0] == right else (right, *tail)
            return (*head, *tail)

        return self._edit_rows(top, bottom, edit)

    def clipped(self, rectangle: Rectangle):
        """Intersection with one ordered, non-empty half-open rectangle."""
        left, top, right, bottom = rectangle
        merged = []
        for band_top, band_bottom, endpoints in self.bands:
            band_top, band_bottom = max(band_top, top), min(band_bottom, bottom)
            if band_top >= band_bottom:
                continue
            low = bisect_right(endpoints, left)
            high = bisect_left(endpoints, right)
            endpoints = (*((left,) if low % 2 else ()), *endpoints[low:high], *((right,) if high % 2 else ()))
            if not endpoints:
                continue
            if merged and merged[-1][1] == band_top and merged[-1][2] == endpoints:
                merged[-1] = (merged[-1][0], band_bottom, endpoints)
            else:
                merged.append((band_top, band_bottom, endpoints))
        return RegionMask(tuple(merged))

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
        return region.intersection(expanded)


@dataclass(frozen=True)
class ClipRegion:
    """Application clip: ``mask`` (``None`` is unbounded) less ``excluded``.

    Intersect and exclude rectangles are folded into the band representation
    when applied, so pixel tests never rescan the clip's history. Clipping is
    conjunctive, so the folded region is independent of application order.
    Once ``mask`` is finite, exclusions are subtracted from it directly.
    Rectangles are half-open; an empty or reversed one contains no pixels.
    """

    mask: RegionMask | None = None
    excluded: RegionMask = RegionMask()

    def within(self, bounds: Rectangle) -> RegionMask:
        """Resolve the application clip inside finite device bounds."""
        region = RegionMask.from_rectangles((bounds,))
        if self.mask is not None:
            region = region.intersection(self.mask)
        if self.excluded.bands:
            region = region.difference(self.excluded)
        return region

    def contains(self, x: int, y: int) -> bool:
        if self.mask is not None:
            return self.mask.contains(x, y)
        return not self.excluded.contains(x, y)

    def intersect(self, rectangle: Rectangle) -> "ClipRegion":
        left, top, right, bottom = rectangle
        if left >= right or top >= bottom:
            return ClipRegion(RegionMask())
        if self.mask is None:
            return ClipRegion(RegionMask.from_rectangles((rectangle,)).difference(self.excluded))
        return ClipRegion(self.mask.clipped(rectangle))

    def exclude(self, rectangle: Rectangle) -> "ClipRegion":
        left, top, right, bottom = rectangle
        if left >= right or top >= bottom:
            return self
        if self.mask is None:
            return ClipRegion(None, self.excluded.with_rectangle(rectangle))
        return ClipRegion(self.mask.without_rectangle(rectangle))

    def offset(self, dx: int, dy: int) -> "ClipRegion":
        return ClipRegion(
            self.mask.offset(dx, dy) if self.mask is not None else None,
            self.excluded.offset(dx, dy),
        )
