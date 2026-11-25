"""The drawing area a metafile declares, used to size and fit an image."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Placement:
    """Bounds in units of ``units_per_inch``, and an optional default pixel size.

    Without a default size, an image is sized from the bounds at 72 DPI.
    """

    bounds: tuple[int, int, int, int]
    units_per_inch: int
    size: tuple[int, int] | None = None
