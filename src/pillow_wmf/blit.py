"""Integer source-transfer geometry and scan selection."""

from dataclasses import dataclass

from .gdi import UnsupportedOperation


@dataclass(frozen=True)
class BlitAxis:
    destination: int
    source: int
    length: int
    step: int = 1

    def samples(self, coordinate, mode):
        return (self.source + (coordinate - self.destination) * self.step,)

    @classmethod
    def unscaled(cls, destination: int, extent: int, source: int, source_extent: int, limit: int, *, anchor_pixel=True):
        if abs(extent) != abs(source_extent):
            raise UnsupportedOperation("Scaled DIB transfers")
        # Copy/mirror realization addresses pixels, so a negative extent
        # includes the anchor. Unreflected ternary BitBlt uses half-open edges.
        if extent < 0:
            destination += extent + int(anchor_pixel)
        if source_extent < 0:
            source += source_extent + int(anchor_pixel)
        length = abs(source_extent)
        left, right = max(0, -source), min(length, limit - source)
        length = max(0, right - left)
        destination += left
        source += left
        mirrored = (extent < 0) != (source_extent < 0)
        return cls(destination, source + length - 1 if mirrored else source, length, -1 if mirrored else 1)


@dataclass(frozen=True)
class StretchAxis:
    destination: int
    source: int
    length: int
    source_length: int
    mirrored: bool
    limit: int

    @classmethod
    def create(cls, destination, extent, source, source_extent, limit):
        return cls(
            destination + min(0, extent + 1),
            source + min(0, source_extent + 1),
            abs(extent),
            abs(source_extent),
            (extent < 0) != (source_extent < 0),
            limit,
        )

    def samples(self, coordinate, mode):
        """Centre-phase DDA; reduction modes accumulate through each chosen scan."""
        if not self.length or not self.source_length:
            return ()
        index = coordinate - self.destination
        if mode == 4 and self.mirrored:
            # HALFTONE reflects the realized output, not the source DDA.
            index = self.length - 1 - index
        last = ((2 * index + 1) * self.source_length) // (2 * self.length)
        if mode == 4 and self.source_length <= self.length:
            # BuildRepData assigns an exact centre tie to the earlier scan.
            last = ((2 * index + 1) * self.source_length - 1) // (2 * self.length)
        if mode == 4 and self.source_length > self.length:
            # HALFTONE's replication path builds the inverse enlargement's
            # run lengths and keeps the final source scan in each run. It is
            # not COLORONCOLOR's centre sample (e.g. 7 -> 5 keeps 0,2,3,5,6).
            last = (2 * (index + 1) * self.source_length - self.length - 1) // (2 * self.length)
            first = 0 if index == 0 else (2 * index * self.source_length - self.length - 1) // (2 * self.length) + 1
            # Keep the last available scan of a partially clipped run.
            last = min(last, self.limit - self.source - 1)
            if last < first:
                return ()
        if not 0 <= self.source + last < self.limit:
            return ()  # The scan selected by the DDA must survive source clipping.
        first = last
        if mode in (1, 2) and self.source_length > self.length:
            first = 0 if index == 0 else ((2 * index - 1) * self.source_length) // (2 * self.length) + 1
        values = range(max(0, self.source + first), min(self.limit, self.source + last + 1))
        if self.mirrored and mode != 4:
            low, high = max(0, self.source), min(self.limit, self.source + self.source_length)
            return (low + high - 1 - value for value in values if low <= value < high)
        return values
