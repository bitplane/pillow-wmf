"""Logical-to-device coordinate state; the default device is the Windows reference bitmap."""

from dataclasses import dataclass
from fractions import Fraction
from math import floor, hypot

from .constants import (
    GM_COMPATIBLE,
    MM_ANISOTROPIC,
    MM_HIENGLISH,
    MM_HIMETRIC,
    MM_ISOTROPIC,
    MM_LOENGLISH,
    MM_LOMETRIC,
    MM_TEXT,
    MM_TWIPS,
)
from .numeric import float32


def rounded(value: float) -> int:
    return floor(value + 0.5)


def fixed(value: float) -> int:
    """Convert to signed 28.4; exact half-unit ties go away from zero."""
    magnitude = floor(abs(value) * 16 + 0.5)
    return -magnitude if value < 0 else magnitude


def _int32(value: int) -> int:
    return (value + 2**31) % 2**32 - 2**31


def scaled(value: int, numerator: int, denominator: int) -> int:
    if denominator == 0:
        raise ValueError("Zero extent divisor")
    product = value * numerator
    sign = -1 if (product < 0) != (denominator < 0) else 1
    return sign * (abs(product) // abs(denominator))


# Logical units per inch of each physical mapping mode. A new isotropic
# mapping starts from the low-metric extents.
UNITS_PER_INCH = {
    MM_LOMETRIC: 254,
    MM_HIMETRIC: 2540,
    MM_LOENGLISH: 100,
    MM_HIENGLISH: 1000,
    MM_TWIPS: 1440,
    MM_ISOTROPIC: 254,
}


# World transforms are (m11, m12, m21, m22, dx, dy): x' = x*m11 + y*m21 + dx.
IDENTITY_TRANSFORM = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass(frozen=True)
class ReferenceDevice:
    """Device capabilities behind the physical mapping modes.

    These describe the device a DC belongs to, not the canvas being drawn.
    The default is the Windows reference bitmap device, the only profile
    with native references; others follow the same arithmetic unverified.

    Without a ``dpi``, physical window extents derive from the millimetre
    size instead, as native EMF playback does for the metafile's reference
    device.
    """

    pixels: tuple[int, int] = (1024, 768)
    millimetres: tuple[int, int] = (271, 203)
    dpi: tuple[int, int] | None = (96, 96)

    def __post_init__(self):
        if any(value <= 0 for value in (*self.pixels, *self.millimetres, *(self.dpi or ()))):
            raise ValueError("Device capabilities must be positive")

    def extents(self, mode: int) -> tuple[tuple[int, int], tuple[int, int]]:
        """Window and viewport extents selected by a physical mapping mode."""
        units = UNITS_PER_INCH[mode]
        if self.dpi is None:
            window = tuple(rounded(size * units / 25.4) for size in self.millimetres)
        else:
            window = tuple(rounded(pixels * units / dpi) for pixels, dpi in zip(self.pixels, self.dpi, strict=True))
        return window, (self.pixels[0], -self.pixels[1])


REFERENCE_DEVICE = ReferenceDevice()


@dataclass
class Mapping:
    mode: int = MM_ANISOTROPIC
    window_origin: tuple[int, int] = (0, 0)
    viewport_origin: tuple[int, int] = (0, 0)
    window_extent: tuple[int, int] = (128, 128)
    viewport_extent: tuple[int, int] = (128, 128)
    layout: int = 0
    surface_width: int = 128
    device: ReferenceDevice = REFERENCE_DEVICE
    graphics_mode: int = GM_COMPATIBLE
    # Float32 world transform applied before the page mapping; GM_ADVANCED
    # is required. A rotating or shearing transform needs an identity page.
    world: tuple[float, float, float, float, float, float] = IDENTITY_TRANSFORM

    @property
    def rtl(self):
        return bool(self.layout & 1)

    @property
    def rotated(self) -> bool:
        """Whether the world transform mixes the axes (rotates or shears)."""
        return bool(self.world[1] or self.world[2])

    @property
    def uniform_rotation(self) -> bool:
        """Whether the world transform keeps circles round: orthogonal axes of equal length."""
        m11, m12, m21, m22 = self.world[:4]
        lengths = (hypot(m11, m12), hypot(m21, m22))
        return (
            abs(m11 * m21 + m12 * m22) <= 1e-3 * lengths[0] * lengths[1]
            and abs(lengths[0] - lengths[1]) <= 1e-3 * lengths[0]
        )

    def rotated_pen_scale(self, width: int) -> tuple[Fraction, Fraction]:
        """Device scales realizing a pen of ``width`` under a uniform rotation.

        Each device axis takes the logical width vector along that axis,
        rounds both components to 28.4 and truncates its length, so a pen
        narrows slightly at oblique angles.
        """
        m11, m12, m21, m22 = self.world[:4]
        if not width:
            return self.linear_scale
        return tuple(
            Fraction(floor(hypot(floor(width * a * 16 + 0.5), floor(width * b * 16 + 0.5))), 16 * width)
            for a, b in ((m11, m21), (m12, m22))
        )

    @property
    def identity_page(self) -> bool:
        return (
            not self.rtl
            and self.window_origin == self.viewport_origin == (0, 0)
            and self.window_extent == self.viewport_extent
        )

    @property
    def linear_scale(self):
        """Signed linear transform for pen support and logical directions.

        Point mapping separately preserves native product/translation rounding.
        Under a rotating or shearing transform these are the lengths of the
        transformed unit vectors, which a rotation preserves.
        """
        if self.rotated:
            m11, m12, m21, m22 = (Fraction(value) for value in self.world[:4])
            return tuple(Fraction(hypot(a, b)) for a, b in ((m11, m12), (m21, m22)))
        x, y = (Fraction(v, w) for v, w in zip(self.viewport_extent, self.window_extent, strict=True))
        x, y = x * Fraction(self.world[0]), y * Fraction(self.world[3])
        return (-x if self.rtl else x), y

    @property
    def translation_only(self) -> bool:
        """Whether the realized FLOAT transform leaves both axes unchanged."""
        return all(float32(scale) == 1 for scale in self.linear_scale)

    def set_layout(self, layout):
        self.layout = layout
        if self.rtl:
            self.mode = MM_ANISOTROPIC

    def _axes(self):
        for i in range(2):
            viewport, window = self.viewport_extent[i], self.window_extent[i]
            window_origin, viewport_origin = self.window_origin[i], self.viewport_origin[i]
            if i == 0 and self.rtl:
                # GDI's MirrorWindowOrg converts the last device pixel to a
                # logical integer with signed truncation before mapping back.
                # At 3/2 scale the reflection origin is 126, not 127.
                last = scaled(self.surface_width - 1, window, viewport)
                window_origin += last
                viewport = -viewport
                viewport_origin = -viewport_origin
            # Realize each FLOAT operation separately.
            # Rounding only the completed translation moves boundary pixels.
            scale = float32(viewport / window)
            window_translation = float32(-window_origin * scale)
            origin = float32(window_translation + viewport_origin)
            yield viewport, window, origin

    def _transform(self):
        """Per-axis float32 (scale, origin): the world transform, then the page mapping.

        Each FLOAT product and sum is realized separately. With an identity
        page, as during EMF playback, these are the world transform itself.
        """
        for axis, (viewport, window, origin) in enumerate(self._axes()):
            scale = float32(viewport / window)
            if self.world != IDENTITY_TRANSFORM:
                world_scale, world_origin = self.world[3 * axis], self.world[4 + axis]
                scale, origin = float32(world_scale * scale), float32(float32(world_origin * scale) + origin)
            yield scale, origin

    def point(self, x: int, y: int) -> tuple[int, int]:
        if self.rtl or self.world != IDENTITY_TRANSFORM:
            return tuple(
                rounded(value * scale + origin)
                for value, (scale, origin) in zip((x, y), self._transform(), strict=True)
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
        scale_x, scale_y = self.linear_scale
        return rounded(x * scale_x), rounded(y * scale_y)

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
        return tuple((coordinate + 8) // 16 for coordinate in self.fixed_point(x, y))

    def fixed_point(self, x, y):
        """Map a point without discarding its device-space sixteenths.

        Under a rotating or shearing transform each coordinate is the float32
        sum of its two float32 products, converted to 28.4, plus the 28.4
        translation.
        """
        if self.rotated:
            m11, m12, m21, m22, dx, dy = self.world
            return (
                fixed(float32(float32(x * m11) + float32(y * m21))) + fixed(dx),
                fixed(float32(float32(x * m12) + float32(y * m22))) + fixed(dy),
            )
        result = []
        for value, (scale, origin) in zip((x, y), self._transform(), strict=True):
            product = float32(value * scale)
            coordinate = fixed(product) + fixed(origin)
            result.append(coordinate)
        return tuple(result)

    def rotated_logical_point(self, x, y) -> tuple[int, int]:
        """The nearest logical point to a 28.4 device point under a rotating transform."""
        m11, m12, m21, m22, dx, dy = self.world
        x, y = x / 16 - dx, y / 16 - dy
        det = m11 * m22 - m12 * m21
        return rounded((x * m22 - y * m21) / det), rounded((y * m11 - x * m12) / det)

    def logical_point(self, x, y) -> tuple[int, int]:
        """DPtoLP: the nearest logical point to a device point."""
        return tuple(
            rounded((value - origin) / scale) for value, (scale, origin) in zip((x, y), self._transform(), strict=True)
        )

    def clip_displacement(self, x: int, y: int) -> tuple[int, int]:
        """OffsetClipRgn rounds transformed distances symmetrically at ties."""
        if self.world != IDENTITY_TRANSFORM:
            result = []
            for value, scale in zip((x, y), self.linear_scale, strict=True):
                distance = value * scale
                magnitude = floor(abs(distance) + Fraction(1, 2))
                result.append(-magnitude if distance < 0 else magnitude)
            return tuple(result)
        result = []
        for value, viewport, window in zip((x, y), self.viewport_extent, self.window_extent, strict=True):
            numerator = value * viewport
            magnitude = (2 * abs(numerator) + abs(window)) // (2 * abs(window))
            result.append(-magnitude if numerator * window < 0 else magnitude)
        if self.rtl:
            result[0] = -result[0]
        return tuple(result)

    def advance_logical_position(self, logical_origin, device_origin, device_position):
        """Map a text-layout displacement back to the logical current position.

        Retain the fractional logical start. Native current-position updates
        floor the displaced device coordinate before inverse mapping.
        """
        result = []
        for axis, scale in enumerate(self.linear_scale):
            coordinate = (logical_origin[axis] - self.window_origin[axis]) * scale + self.viewport_origin[axis]
            delta = device_position[axis] - device_origin[axis]
            result.append(((coordinate + delta) // 1 - self.viewport_origin[axis]) / scale + self.window_origin[axis])
        return tuple(result)

    def set_mode(self, mode: int) -> None:
        self.mode = MM_ANISOTROPIC if self.rtl else mode
        if mode == MM_TEXT:
            self.window_extent = (1, 1)
            self.viewport_extent = (1, 1)
        elif mode in UNITS_PER_INCH:
            self.window_extent, self.viewport_extent = self.device.extents(mode)

    def set_extent(self, *, window: bool, x: int, y: int) -> None:
        if self.mode not in (MM_ISOTROPIC, MM_ANISOTROPIC) or not x or not y:
            return
        if window:
            self.window_extent = (x, y)
        else:
            self.viewport_extent = (x, y)
        self._fix_isotropic()

    def scale_extent(self, *, window: bool, xn: int, xd: int, yn: int, yd: int) -> None:
        """ScaleWindowExtEx and ScaleViewportExtEx, in GDI's 32-bit integers.

        Each product wraps to 32 bits and divides truncating toward zero; a
        zero divisor, a zero result or the one overflowing quotient fails.
        """
        if self.mode not in (MM_ISOTROPIC, MM_ANISOTROPIC) or not xd or not yd:
            return
        old = self.window_extent if window else self.viewport_extent
        x, y = _int32(old[0] * xn), _int32(old[1] * yn)
        if (x == -(2**31) and xd == -1) or (y == -(2**31) and yd == -1):
            return
        x, y = scaled(x, 1, xd), scaled(y, 1, yd)
        if not x or not y:
            return
        if window:
            self.window_extent = (x, y)
        else:
            self.viewport_extent = (x, y)
        self._fix_isotropic()

    def isotropic_viewport(self) -> tuple[int, int]:
        """The viewport extent with the window's physical aspect ratio.

        The shrunk axis can round to zero; callers decide how to treat that.
        """
        wx, wy = self.window_extent
        vx, vy = self.viewport_extent
        (width_mm, height_mm), (width, height) = self.device.millimetres, self.device.pixels
        xdim = abs(vx * width_mm / (width * wx))
        ydim = abs(vy * height_mm / (height * wy))
        if xdim > ydim:
            return rounded(vx * ydim / xdim), vy
        return vx, rounded(vy * xdim / ydim)

    def _fix_isotropic(self) -> None:
        if self.mode != MM_ISOTROPIC:
            return
        # GDI keeps a collapsed axis at one unit in its original direction.
        self.viewport_extent = tuple(
            value or (1 if original > 0 else -1)
            for value, original in zip(self.isotropic_viewport(), self.viewport_extent, strict=True)
        )
