"""Logical-to-device coordinate state for the Windows reference bitmap profile."""

from dataclasses import dataclass
from math import floor


def rounded(value: float) -> int:
    return floor(value + 0.5)


def scaled(value: int, numerator: int, denominator: int) -> int:
    if denominator == 0:
        raise ValueError("Zero extent divisor")
    product = value * numerator
    sign = -1 if (product < 0) != (denominator < 0) else 1
    return sign * (abs(product) // abs(denominator))


# Measured on the project's windows-2025 reference DC, run 35071353163.
PHYSICAL_EXTENTS = {
    2: ((2709, 2032), (1024, -768)),
    3: ((27093, 20320), (1024, -768)),
    4: ((1067, 800), (1024, -768)),
    5: ((10667, 8000), (1024, -768)),
    6: ((15360, 11520), (1024, -768)),
    7: ((2709, 2032), (1024, -768)),
}


@dataclass
class Mapping:
    mode: int = 8
    window_origin: tuple[int, int] = (0, 0)
    viewport_origin: tuple[int, int] = (0, 0)
    window_extent: tuple[int, int] = (128, 128)
    viewport_extent: tuple[int, int] = (128, 128)

    def point(self, x: int, y: int) -> tuple[int, int]:
        return (
            rounded(
                self.viewport_origin[0] + (x - self.window_origin[0]) * self.viewport_extent[0] / self.window_extent[0]
            ),
            rounded(
                self.viewport_origin[1] + (y - self.window_origin[1]) * self.viewport_extent[1] / self.window_extent[1]
            ),
        )

    def vector(self, x: int, y: int) -> tuple[int, int]:
        return (
            rounded(x * self.viewport_extent[0] / self.window_extent[0]),
            rounded(y * self.viewport_extent[1] / self.window_extent[1]),
        )

    def clip_displacement(self, x: int, y: int) -> tuple[int, int]:
        """OffsetClipRgn rounds transformed distances symmetrically at ties."""
        result = []
        for value, viewport, window in zip((x, y), self.viewport_extent, self.window_extent, strict=True):
            numerator = value * viewport
            magnitude = (2 * abs(numerator) + abs(window)) // (2 * abs(window))
            result.append(-magnitude if numerator * window < 0 else magnitude)
        return tuple(result)

    def set_mode(self, mode: int) -> None:
        self.mode = mode
        if mode == 1:
            self.window_extent = (1, 1)
            self.viewport_extent = (1, 1)
        elif mode in PHYSICAL_EXTENTS:
            self.window_extent, self.viewport_extent = PHYSICAL_EXTENTS[mode]

    def set_extent(self, *, window: bool, x: int, y: int) -> None:
        if self.mode not in (7, 8) or not x or not y:
            return
        if window:
            self.window_extent = (x, y)
        else:
            self.viewport_extent = (x, y)
        self._fix_isotropic()

    def scale_extent(self, *, window: bool, xn: int, xd: int, yn: int, yd: int) -> None:
        if self.mode not in (7, 8) or not xn or not xd or not yn or not yd:
            return
        old = self.window_extent if window else self.viewport_extent
        x, y = scaled(old[0], xn, xd), scaled(old[1], yn, yd)
        if not x or not y:
            return
        if window:
            self.window_extent = (x, y)
        else:
            self.viewport_extent = (x, y)
        self._fix_isotropic()

    def _fix_isotropic(self) -> None:
        if self.mode != 7:
            return
        wx, wy = self.window_extent
        vx, vy = self.viewport_extent
        xdim = abs(vx * 271 / (1024 * wx))
        ydim = abs(vy * 203 / (768 * wy))
        if xdim > ydim:
            vx = rounded(vx * ydim / xdim)
            vx = vx or (1 if self.viewport_extent[0] > 0 else -1)
        else:
            vy = rounded(vy * xdim / ydim)
            vy = vy or (1 if self.viewport_extent[1] > 0 else -1)
        self.viewport_extent = (vx, vy)
