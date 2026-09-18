"""Logical-to-device coordinate state for the Windows reference bitmap profile."""

from dataclasses import dataclass
from fractions import Fraction
from math import floor
from struct import pack, unpack


def single(value: float) -> float:
    """Round a transform intermediate to IEEE-754 binary32."""
    return unpack("f", pack("f", value))[0]


def rounded(value: float) -> int:
    return floor(value + 0.5)


def fixed(value: float) -> int:
    """Convert to signed 28.4; exact half-unit ties go away from zero."""
    magnitude = floor(abs(value) * 16 + 0.5)
    return -magnitude if value < 0 else magnitude


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
    layout: int = 0
    surface_width: int = 128

    @property
    def rtl(self):
        return bool(self.layout & 1)

    @property
    def linear_scale(self):
        """Signed linear transform for pen support and logical directions.

        Point mapping separately preserves native product/translation rounding.
        """
        x, y = (Fraction(v, w) for v, w in zip(self.viewport_extent, self.window_extent, strict=True))
        return (-x if self.rtl else x), y

    def set_layout(self, layout):
        self.layout = layout
        if self.rtl:
            self.mode = 8

    def _axes(self):
        for i in range(2):
            viewport, window = self.viewport_extent[i], self.window_extent[i]
            origin = self.viewport_origin[i] - self.window_origin[i] * viewport / window
            if i == 0 and self.rtl:
                # GDI's MirrorWindowOrg converts the last device pixel to a
                # logical integer with signed truncation before mapping back.
                # At 3/2 scale the reflection origin is 126, not 127.
                last = scaled(self.surface_width - 1, window, viewport)
                origin = last * viewport / window - origin
                viewport = -viewport
            yield viewport, window, origin

    def point(self, x: int, y: int) -> tuple[int, int]:
        if self.rtl:
            return tuple(
                rounded(value * viewport / window + origin)
                for value, (viewport, window, origin) in zip((x, y), self._axes(), strict=True)
            )
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
            rounded(x * self.viewport_extent[0] / self.window_extent[0] * (-1 if self.rtl else 1)),
            rounded(y * self.viewport_extent[1] / self.window_extent[1]),
        )

    def clip_point(self, x: int, y: int) -> tuple[int, int]:
        """Rectangular clip edges use the driver's fixed-point transform."""
        return self.edge_point(x, y)

    def edge_point(self, x: int, y: int) -> tuple[int, int]:
        """Map half-open device edges, rather than inclusive pixel centres."""
        x, y = self.device_point(x, y)
        return x + self.rtl, y

    def device_point(self, x: int, y: int) -> tuple[int, int]:
        """Driver coordinates: quantize translation and product to 28.4.

        The translation is realized separately, not reassociated with the
        logical coordinate as (value - window_origin) * scale. Both stages
        precede pixel rounding, which matters near half-pixel boundaries.
        Driver scale coefficients and products are single precision before
        fixed-point conversion; retaining Python doubles can miss a tie.
        ``point`` retains the separate LPtoDP-style integer conversion.
        """
        return tuple(
            (fixed(single(value * single(viewport / window))) + fixed(single(origin)) + 8) // 16
            for value, (viewport, window, origin) in zip((x, y), self._axes(), strict=True)
        )

    def clip_displacement(self, x: int, y: int) -> tuple[int, int]:
        """OffsetClipRgn rounds transformed distances symmetrically at ties."""
        result = []
        for value, viewport, window in zip((x, y), self.viewport_extent, self.window_extent, strict=True):
            numerator = value * viewport
            magnitude = (2 * abs(numerator) + abs(window)) // (2 * abs(window))
            result.append(-magnitude if numerator * window < 0 else magnitude)
        if self.rtl:
            result[0] = -result[0]
        return tuple(result)

    def set_mode(self, mode: int) -> None:
        self.mode = 8 if self.rtl else mode
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
