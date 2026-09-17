"""Native RGB HALFTONE: 13-bit area weights, sharpening and tent expansion.

See docs/gdi-dib-stretching.md for the arithmetic and Windows measurements.
Includes the native colour census and fast replication-run enlargement filter.
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


def replication_content(bitmap, x, y, width, height):
    """CheckBMPNeedFixup's bounded colour census of the source rectangle.

    Small images bypass the census. Medium images discount rows introducing
    no new colours; large images sample every sixth row with a 20-colour cap.
    The native key coarsens channels when red equals blue (not just greys).
    """
    remaining = width * height
    if remaining <= 2304:
        return True
    stride = 6 if remaining > 16384 else 1
    limit = 20 if stride == 6 else remaining >> 3
    colours = set()
    for sy in range(y, y + height, stride):
        before = len(colours)
        for sx in range(x, x + width):
            colour = bitmap.pixel(sx, sy)
            if colour[0] == colour[2]:
                colour = tuple(c & 252 for c in colour)
            colours.add(colour)
            if len(colours) > limit:
                break
        if limit != 20 and len(colours) == before:
            remaining -= width
            if remaining <= 2304:
                return True
            limit = remaining >> 4
        if len(colours) > limit:
            break
    return len(colours) < 20


def halftone_bitmap(bitmap, x, y, sw, sh, width, height):
    """Return a filtered bitmap view, or None to use existing scan replication."""
    if min(sw, sh, width, height) <= 0:
        raise UnsupportedOperation("HALFTONE reflected extents")
    left, top = max(0, x), max(0, y)
    right, bottom = min(bitmap.width, x + sw), min(bitmap.height, y + sh)
    if replication_candidate(sw, sh, width, height) and replication_content(
        bitmap, left, top, max(0, right - left), max(0, bottom - top)
    ):
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


class RunExpansionAxis:
    """Native FastExpAA's five replication-run stencils, in units of 1/32."""

    kernels = (
        (),
        ((5, 22, 5),),
        ((8, 24, 0), (0, 24, 8)),
        ((12, 20, 0), (2, 28, 2), (0, 20, 12)),
        ((12, 20, 0), (6, 24, 2), (2, 24, 6), (0, 20, 12)),
        ((13, 19, 0), (6, 25, 1), (3, 26, 3), (1, 25, 6), (0, 19, 13)),
    )

    def __init__(self, source, destination):
        self.source, self.destination = source, destination

    def weights(self, index):
        source = ((2 * index + 1) * self.source - 1) // (2 * self.destination)
        start = (2 * source * self.destination + self.source) // (2 * self.source)
        end = (2 * (source + 1) * self.destination + self.source) // (2 * self.source)
        return tuple(
            (source + offset - 1, weight * 256)
            for offset, weight in enumerate(self.kernels[end - start][index - start])
        )


class HalftoneExpansion:
    """Source Laplacian, then horizontal and vertical fixed-point expansion."""

    def __init__(self, bitmap, width, height):
        self.bitmap = bitmap
        self.width, self.height = width, height
        self.fast = bitmap.width < width <= 5 * bitmap.width and bitmap.height < height <= 5 * bitmap.height
        axis = RunExpansionAxis if self.fast else ExpansionAxis
        self.x_axis = axis(bitmap.width, width) if width > bitmap.width else None
        self.y_axis = axis(bitmap.height, height) if height > bitmap.height else None
        self.sharp = lru_cache(maxsize=2048)(self._sharp)
        self.horizontal = lru_cache(maxsize=2048)(self._horizontal)
        self.vertical = lru_cache(maxsize=2048)(self._vertical)

    def _sharp(self, x, y):
        # FastExpAA extends raw rows before sharpening; a virtual boundary
        # row has different vertical neighbours from the actual edge row.
        # General tent expansion instead repeats the sharpened edge sample.
        row = max(0, min(self.bitmap.height - 1, y))
        center = self.bitmap.pixel(x, row)
        neighbours = []
        if self.x_axis:
            neighbours.extend(
                (self.bitmap.pixel(max(0, x - 1), row), self.bitmap.pixel(min(self.bitmap.width - 1, x + 1), row))
            )
        if self.y_axis:
            neighbours.extend(
                (
                    self.bitmap.pixel(x, max(0, min(self.bitmap.height - 1, y - 1))),
                    self.bitmap.pixel(x, max(0, min(self.bitmap.height - 1, y + 1))),
                )
            )
        coefficient, shift = (12, 3) if self.x_axis and self.y_axis else (6, 2)
        return tuple(
            max(0, min(255, (coefficient * center[c] - sum(n[c] for n in neighbours)) >> shift)) for c in range(3)
        )

    def _horizontal(self, x, y):
        if not self.x_axis:
            return self.sharp(x, y)
        value = weighted((self.sharp(sx, y), weight) for sx, weight in self.x_axis.weights(x))
        return tuple((v + SCALE // 2) >> 13 for v in value)

    def _vertical(self, x, y):
        value = weighted((self.sharp(x, sy), weight) for sy, weight in self.y_axis.weights(y))
        return tuple((v + SCALE // 2) >> 13 for v in value)

    def pixel(self, x, y):
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError("Bitmap pixel outside bounds")
        if not self.y_axis:
            return self.horizontal(x, y)
        if self.fast:
            # The fast implementation materializes vertical results as bytes
            # first; general two-axis enlargement materializes horizontal ones.
            value = weighted(
                (self.vertical(max(0, min(self.bitmap.width - 1, sx)), y), weight)
                for sx, weight in self.x_axis.weights(x)
            )
        else:
            value = weighted((self.horizontal(x, sy), weight) for sy, weight in self.y_axis.weights(y))
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
