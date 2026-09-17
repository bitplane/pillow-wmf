"""Native RGB HALFTONE: 13-bit area weights, sharpening and tent expansion.

See docs/gdi-dib-stretching.md for the arithmetic and Windows measurements.
Large-image colour classification and source-boundary realization are not guessed.
"""

from functools import lru_cache

from .gdi import UnsupportedOperation
from .halftone_power import FD6, round_ratio, tent_power

SCALE = 8192
MAX_FILTER_TAPS = 65536


def replication_candidate(sw, sh, width, height):
    """ComputeAABBP's integer eligibility test, before image classification.

    The +500 is literal: it is not half of the source dimension. A decrease
    in total pixel area overrides the small-image replication decision.
    """
    return width * height >= sw * sh and (width * 1000 + 500) // sw > 667 and (height * 1000 + 500) // sh > 667


def halftone_bitmap(bitmap, x, y, sw, sh, width, height):
    """Return a filtered bitmap view, or None to use existing scan replication."""
    if min(sw, sh, width, height) <= 0:
        raise UnsupportedOperation("HALFTONE reflected extents")
    if x < 0 or y < 0 or x + sw > bitmap.width or y + sh > bitmap.height:
        raise UnsupportedOperation("HALFTONE source clipping")
    if replication_candidate(sw, sh, width, height):
        # The native classifier bypasses colour counting for small bitmaps.
        # Larger images require its content-dependent palette classification;
        # choosing nearest solely from the scale ratio would be incorrect.
        if sw * sh > 2304:
            raise UnsupportedOperation("HALFTONE large-image colour classification")
        return None
    reduced = HalftoneReduction(bitmap, x, y, sw, sh, min(sw, width), min(sh, height))
    if width <= sw and height <= sh:
        return reduced
    return HalftoneExpansion(reduced, width, height)


class ExpansionAxis:
    """Integrate a power-adjusted discrete tent over source pixel cells."""

    def __init__(self, source, destination):
        self.source, self.destination = source, destination
        self.radius = (destination + source - 1) // source - 1
        taps = 2 * self.radius + 1
        if taps > MAX_FILTER_TAPS:
            raise UnsupportedOperation("HALFTONE filter tap limit")
        self.kernel = tuple(
            tent_power(round_ratio((destination - abs(k) * source) * FD6, destination))
            for k in range(-self.radius, self.radius + 1)
        )
        self.prefix = [0]
        for value in self.kernel:
            self.prefix.append(self.prefix[-1] + value)
        self.total = self.prefix[-1] * source
        self.weights = lru_cache(maxsize=2048)(self._weights)

    def integral(self, position):
        position += self.radius * self.source
        if position <= 0:
            return 0
        if position >= len(self.kernel) * self.source:
            return self.total
        cell, remainder = divmod(position, self.source)
        return self.prefix[cell] * self.source + self.kernel[cell] * remainder

    def _weights(self, index):
        left = (index - self.radius) * self.source // self.destination
        right = ((index + self.radius + 1) * self.source - 1) // self.destination
        cumulative = previous = 0
        result = []
        for scan in range(right, left - 1, -1):
            start = scan * self.destination - index * self.source
            cumulative += self.integral(start + self.destination) - self.integral(start)
            boundary = cumulative * SCALE // self.total
            result.append((max(0, min(self.source - 1, scan)), boundary - previous))
            previous = boundary
        return tuple(result)


class HalftoneExpansion:
    """One-axis source sharpening and filtering, after any opposite reduction."""

    def __init__(self, bitmap, width, height):
        self.bitmap = bitmap
        self.width, self.height = width, height
        self.horizontal = width > bitmap.width
        source, destination = (bitmap.width, width) if self.horizontal else (bitmap.height, height)
        self.axis = ExpansionAxis(source, destination)
        self.sharp = lru_cache(maxsize=2048)(self._sharp)

    def _sharp(self, scan, other):
        values = [
            self.bitmap.pixel(i, other) if self.horizontal else self.bitmap.pixel(other, i)
            for i in (max(0, scan - 1), scan, min(self.axis.source - 1, scan + 1))
        ]
        return tuple(max(0, min(255, (6 * values[1][c] - values[0][c] - values[2][c]) >> 2)) for c in range(3))

    def pixel(self, x, y):
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError("Bitmap pixel outside bounds")
        index, other = (x, y) if self.horizontal else (y, x)
        value = weighted((self.sharp(scan, other), weight) for scan, weight in self.axis.weights(index))
        return tuple((v + SCALE // 2) >> 13 for v in value)


def area_weights(source_length, destination_length, index):
    """Integrate source cells using quantized *cumulative* boundaries.

    Taking differences after quantization carries the division remainder across
    contributions. Rounding independently computed overlap weights does not.
    Coordinates use the common integer grid: source cells are D units wide,
    destination cells S units wide. Each output's weights sum to exactly 8192.
    """
    left, right = index * source_length, (index + 1) * source_length
    for source in range(left // destination_length, (right - 1) // destination_length + 1):
        start = max(left, source * destination_length)
        end = min(right, (source + 1) * destination_length)
        yield source, end * SCALE // source_length - start * SCALE // source_length


def weighted(samples):
    red = green = blue = 0
    for (r, g, b), weight in samples:
        red += r * weight
        green += g * weight
        blue += b * weight
    return red, green, blue


class HalftoneReduction:
    """Lazy bitmap view; destination clipping does not change filtering phase.

    Bounded per-transfer caches avoid allocating the destination or a potentially
    large source-height intermediate image. Output pixels remain ordinary RGB
    samples consumed by the shared transfer compositor.
    """

    def __init__(self, bitmap, x, y, source_width, source_height, width, height):
        if not (0 < width <= source_width and 0 < height <= source_height):
            raise UnsupportedOperation("HALFTONE enlargement or reflected extents")
        if x < 0 or y < 0 or x + source_width > bitmap.width or y + source_height > bitmap.height:
            raise UnsupportedOperation("HALFTONE source clipping")
        self.bitmap = bitmap
        self.x, self.y = x, y
        self.source_width, self.source_height = source_width, source_height
        self.width, self.height = width, height
        self.shrink_x, self.shrink_y = width < source_width, height < source_height
        self.both = self.shrink_x and self.shrink_y
        self.horizontal = lru_cache(maxsize=2048)(self._horizontal)
        self.area = lru_cache(maxsize=2048)(self._area)

    def _horizontal(self, x, y):
        value = weighted(
            (self.bitmap.pixel(self.x + sx, self.y + y), weight)
            for sx, weight in area_weights(self.source_width, self.width, x)
        )
        # Only the two-axis reducer materializes horizontal results as bytes.
        return tuple((v + SCALE // 2) >> 13 for v in value) if self.both else value

    def _area(self, x, y):
        if not self.shrink_y:
            return self.horizontal(x, y)
        return weighted(
            (
                self.horizontal(x, sy) if self.both else self.bitmap.pixel(self.x + x, self.y + sy),
                weight,
            )
            for sy, weight in area_weights(self.source_height, self.height, y)
        )

    def pixel(self, x, y):
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError("Bitmap pixel outside bounds")
        center = self.area(x, y)
        neighbours = []
        if self.shrink_x:
            neighbours.extend((self.area(max(0, x - 1), y), self.area(min(self.width - 1, x + 1), y)))
        if self.shrink_y:
            neighbours.extend((self.area(x, max(0, y - 1)), self.area(x, min(self.height - 1, y + 1))))
        if not neighbours:
            return tuple(v >> 13 for v in center)
        # Gain 1/8 for the 2D Laplacian, 1/4 for its 1D counterpart. Preserve
        # the area accumulator's fractional bits through the final arithmetic
        # shift, then saturate. Clamp neighbour addresses, not accumulators.
        coefficient, shift = (12, 16) if self.both else (6, 15)
        return tuple(
            max(0, min(255, (coefficient * center[c] - sum(n[c] for n in neighbours)) >> shift)) for c in range(3)
        )
