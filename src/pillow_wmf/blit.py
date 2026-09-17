"""Integer geometry for unscaled source transfers."""

from dataclasses import dataclass

from .gdi import UnsupportedOperation


@dataclass(frozen=True)
class BlitAxis:
    destination: int
    source: int
    length: int
    step: int = 1

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
