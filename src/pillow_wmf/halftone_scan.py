"""HALFTONE source addressing, separate from filter weights and arithmetic.

These are random-access descriptions of the native scan readers: evaluating a
destination pixel out of order must not change the reader's history. None is an
unfilled buffer slot, not a black pixel fetched from the source bitmap.
"""

from dataclasses import dataclass


def has_source(bitmap, x, y, width, height):
    """Physical intersection, independent of filter output's closing cells."""
    return max(0, x) < min(bitmap.width, x + width) and max(0, y) < min(bitmap.height, y + height)


@dataclass(frozen=True)
class ExpansionWindow:
    stop: int

    def fetch(self, weights):
        # The cursor stops fetching at the source boundary, but the filter's
        # fractional phase continues. Earlier slots may still be unfilled.
        shift = max(0, max(scan for scan, _ in weights) - max(1, self.stop - 1))
        return tuple(
            (slot if (slot := min(self.stop - 1, scan - shift)) >= 0 else None, weight) for scan, weight in weights
        )


class ExpansionSamples:
    def __init__(self, bitmap, fast):
        self.bitmap, self.fast = bitmap, fast
        self.left = getattr(bitmap, "left", 0)
        self.top = getattr(bitmap, "top", 0)
        self.right = getattr(bitmap, "right", bitmap.width)
        self.bottom = getattr(bitmap, "bottom", bitmap.height)

    def stencil(self, x, y, horizontal, vertical):
        if x is None or y is None or x < 0 or (y < 0 and not self.fast):
            return None
        row = max(self.top, min(self.bottom - 1, y))
        column = max(self.left, min(self.right - 1, x))
        center = self.bitmap.pixel(column, row)
        neighbours = []
        if horizontal:
            neighbours.extend(
                (self.bitmap.pixel(max(self.left, x - 1), row), self.bitmap.pixel(min(self.right - 1, x + 1), row))
            )
        if vertical:
            # FastExpAA extends raw rows before sharpening. General expansion
            # instead repeats sharpened endpoint samples in its fetch window.
            neighbours.extend(
                self.bitmap.pixel(column, max(self.top, min(self.bottom - 1, sy))) for sy in (y - 1, y + 1)
            )
        return center, neighbours


class ReductionScanReader:
    def __init__(self, bitmap, x, y, source_height, height, *, fixup):
        self.bitmap, self.x, self.y = bitmap, x, y
        self.first = max(0, -y)
        stop = min(source_height, bitmap.height - y)
        self.current = self.first if self.first < stop else None
        # Priming a two-row fixup reader fills current first. Only a second
        # available scan advances current and gives previous its first row.
        self.previous = None
        if self.first + 1 < stop:
            self.previous, self.current = self.current, self.first + 1
        prefill = (self.first * height % source_height) * 8192 // source_height
        self.replay = fixup and bool(prefill)

    def row(self, scan):
        if self.replay and scan == self.first:
            return self.previous
        return scan

    def pixel(self, x, y, *, closing_horizontal=False):
        if y is None or (closing_horizontal and self.x + x >= self.bitmap.width):
            return (0, 0, 0)
        return self.bitmap.pixel(
            max(0, min(self.bitmap.width - 1, self.x + x)), max(0, min(self.bitmap.height - 1, self.y + y))
        )
