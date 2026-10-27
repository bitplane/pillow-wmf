"""Default allocation/work policy, separate from WMF field sizes and GDI arithmetic.

Codec and playback Limits bound input structures and backend bookkeeping.
Raster-specific allowances bound decoded pixels and expanded geometry.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Limits:
    """Allocation/work limits; these are policy, not WMF format limits."""

    max_bytes: int = 64 * 1024 * 1024
    max_records: int = 100_000
    max_points: int = 1_000_000
    max_objects: int = 65_535
    max_saved_states: int = 1024

    def __post_init__(self):
        if any(value < 0 for value in vars(self).values()):
            raise ValueError("Limits must be nonnegative")


DEFAULT_LIMITS = Limits()
DEFAULT_MAX_BITMAP_PIXELS = 16_777_216
DEFAULT_MAX_GEOMETRY_POINTS = 1_000_000
MAX_CURVE_POINTS = 65_536
MAX_FILTER_TAPS = 65_536
