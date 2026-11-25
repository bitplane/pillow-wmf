"""The world transform native EMF playback gives the target DC.

PlayEnhMetaFile leaves the DC in MM_TEXT and GM_ADVANCED. It keeps the
metafile's own page state (mapping mode, window and viewport), layout and
world transform itself, and after each change sets the DC's world transform to

    world, then page, then right-to-left mirror, then frame fit

as one float32 matrix. The frame fit maps the header's picture frame, in
0.01 mm, onto the target rectangle. Physical mapping modes take their
extents from the header's millimetre size, not from a display's DPI.
"""

import math
import struct
from copy import copy
from fractions import Fraction

from ..constants import MM_ANISOTROPIC, MM_ISOTROPIC, MM_TEXT
from ..mapping import IDENTITY_TRANSFORM, Mapping, ReferenceDevice
from ..numeric import float32
from ..playback import PlaybackError
from . import fixed
from .file import Header

Transform = tuple[float, float, float, float, float, float]

MWT_IDENTITY = 1
MWT_LEFTMULTIPLY = 2
MWT_RIGHTMULTIPLY = 3
MWT_SET = 4
# Frame fits this close to 1:1 on both axes use an exact unit scale.
UNIT_SCALE_BOUNDS = (float32(0.999), float32(1.001))


def _f32(value) -> float:
    """Round an exact (rational) value once to binary32, ties to even."""
    value = Fraction(value)
    candidate = float32(float(value))
    if Fraction(candidate) == value or not math.isfinite(candidate):
        return candidate
    bits = struct.unpack("<i", struct.pack("<f", candidate))[0]
    neighbours = [struct.unpack("<f", struct.pack("<i", bits + step))[0] for step in (-1, 1)]
    best = candidate
    for neighbour in neighbours:
        if not math.isfinite(neighbour):
            continue
        distance, current = abs(Fraction(neighbour) - value), abs(Fraction(best) - value)
        if distance < current or (
            distance == current and struct.unpack("<i", struct.pack("<f", neighbour))[0] % 2 == 0
        ):
            best = neighbour
    return best


def divide(numerator, denominator) -> float:
    """A binary32 division of two binary32 values, correctly rounded."""
    return _f32(Fraction(float32(numerator)) / Fraction(float32(denominator)))


def fits_long(value: float) -> bool:
    """Whether GDI's float-to-long conversion accepts ``value``: magnitude below 2**32."""
    exponent = (struct.unpack("<I", struct.pack("<f", value))[0] >> 23) & 0xFF
    return exponent < 159


def multiply(first: Transform, second: Transform, *, checked: bool = True) -> Transform | None:
    """``first`` then ``second`` as native GDI multiplies them, in binary32.

    Without off-diagonal terms on either side the diagonal is a single
    product. Each offset is the second's off-diagonal term on the first's
    other offset, plus the second's offset, plus the diagonal product, in
    that order; a first with no offset passes the second's through. A
    checked product fails (None) when an offset reaches 2**32.
    """
    a11, a12, a21, a22, adx, ady = first
    b11, b12, b21, b22, bdx, bdy = second
    f = float32
    if not (a12 or a21 or b12 or b21):
        m11, m12, m21, m22 = f(b11 * a11), 0.0, 0.0, f(b22 * a22)
    else:
        m11 = f(f(b21 * a12) + f(b11 * a11))
        m12 = f(f(b22 * a12) + f(b12 * a11))
        m21 = f(f(b21 * a22) + f(b11 * a21))
        m22 = f(f(b22 * a22) + f(b12 * a21))
    if not adx and not ady:
        return m11, m12, m21, m22, bdx, bdy
    dx = f(f(f(b21 * ady) + bdx) + f(b11 * adx))
    dy = f(f(f(b22 * ady) + bdy) + f(b12 * adx))
    if checked and not (fits_long(dx) and fits_long(dy)):
        return None
    return m11, m12, m21, m22, dx, dy


def in_range(transform: Transform) -> bool:
    """GDI's acceptance of a world transform: invertible, judged in binary32."""
    m11, m12, m21, m22 = transform[:4]
    if not m12 and not m21:
        return bool(m11) and bool(m22)
    if not m11 and not m22:
        return bool(m12) and bool(m21)
    return float32(float32(m22 * m11) - float32(m12 * m21)) != 0


def _check_device(header: Header) -> None:
    if any(value <= 0 for value in (*header.device, *header.millimetres)):
        raise PlaybackError("EMF header has no reference device size")


def frame_fit(header: Header, rect: tuple[int, int, int, int], parent: Transform = IDENTITY_TRANSFORM) -> Transform:
    """Map reference-device logical units onto ``rect`` through the picture frame.

    A logical unit is one header device pixel, ``millimetres * 100 / pixels``
    frame units across. The frame width is ``right - left``; an empty axis
    counts as one frame unit over a target one pixel wider. A reversed frame
    makes native playback fail. The fit is composed with the target DC's
    transform (``parent``) and then, when neither has off-diagonal terms and
    both scales lie within [0.999, 1.001] in binary32, the scales become
    exactly 1.
    """
    _check_device(header)
    axes = []
    frame = header.frame
    f = float32
    for axis in range(2):
        low, high = frame[axis], frame[axis + 2]
        target = rect[axis + 2] - rect[axis]
        if high < low:
            raise PlaybackError("EMF picture frame is reversed")
        ratio = f(target + 1) if high == low else divide(target, high - low)
        scale = f(divide(f(f(header.millimetres[axis]) * 100), header.device[axis]) * ratio)
        origin = f(f(rect[axis]) - f(f(low) * ratio))
        axes.append((scale, origin))
    (sx, ox), (sy, oy) = axes
    p11, p12, p21, p22, pdx, pdy = parent
    fit = [f(p11 * sx), f(p12 * sx), f(p21 * sy), f(p22 * sy)]
    fit += [f(f(f(p21 * oy) + f(p11 * ox)) + pdx), f(f(f(p22 * oy) + f(p12 * ox)) + pdy)]
    low, high = UNIT_SCALE_BOUNDS
    if not (p12 or p21 or fit[1] or fit[2]) and low <= fit[0] <= high and low <= fit[3] <= high:
        fit[0] = fit[3] = 1.0
    return tuple(fit)


def natural_size(header: Header) -> tuple[int, int]:
    """The picture frame in header device pixels, at least one pixel."""
    _check_device(header)
    left, top, right, bottom = header.frame
    return tuple(
        max(1, round((high - low) * pixels / (millimetres * 100)))
        for low, high, pixels, millimetres in zip(
            (left, top), (right, bottom), header.device, header.millimetres, strict=True
        )
    )


class _Rejected(Exception):
    pass


class MetafilePage(Mapping):
    """The metafile's own page state as playback emulates it.

    An isotropic adjustment that would collapse an axis rejects the record,
    leaving the extents unchanged, where a DC keeps one unit instead.
    """

    def _fix_isotropic(self) -> None:
        if self.mode != MM_ISOTROPIC:
            return
        viewport = self.isotropic_viewport()
        if 0 in viewport:
            raise _Rejected
        self.viewport_extent = viewport

    def set_extent(self, *, window: bool, x: int, y: int) -> None:
        before = self.window_extent, self.viewport_extent
        try:
            super().set_extent(window=window, x=x, y=y)
        except _Rejected:
            self.window_extent, self.viewport_extent = before

    def scale_extent(self, *, window: bool, xn: int, xd: int, yn: int, yd: int) -> None:
        before = self.window_extent, self.viewport_extent
        try:
            super().scale_extent(window=window, xn=xn, xd=xd, yn=yn, yd=yd)
        except _Rejected:
            self.window_extent, self.viewport_extent = before

    def matrix(self) -> Transform:
        (scale_x, origin_x), (scale_y, origin_y) = self._transform()
        return scale_x, 0.0, 0.0, scale_y, origin_x, origin_y


class PlaybackTransform:
    """Track mapping records and the target DC's world transform (``device``).

    Native playback keeps the metafile's page state and world transform in a
    hidden DC. After a record changes them it reads that DC's world-to-device
    transform, multiplies it by the frame fit and sets the product on the
    target; a product whose offset overflows, or that is not invertible,
    leaves the target unchanged. A left-multiplying ModifyWorldTransform is
    instead applied to the target's own transform directly.
    """

    MAPPING_RECORDS = (
        fixed.SetMapMode,
        fixed.SetWindowOrgEx,
        fixed.SetWindowExtEx,
        fixed.SetViewportOrgEx,
        fixed.SetViewportExtEx,
        fixed.ScaleWindowExtEx,
        fixed.ScaleViewportExtEx,
        fixed.SetWorldTransform,
        fixed.ModifyWorldTransform,
        fixed.SetLayout,
    )

    def __init__(self, header: Header, rect: tuple[int, int, int, int], *, parent: Transform | None = None):
        # An embedded metafile's rectangle is in its parent's logical units.
        self.fit = frame_fit(header, rect, parent or IDENTITY_TRANSFORM)
        device = ReferenceDevice(tuple(header.device), tuple(header.millimetres), dpi=None)
        self.page = MetafilePage(mode=MM_TEXT, window_extent=(1, 1), viewport_extent=(1, 1), device=device)
        self.world: Transform = IDENTITY_TRANSFORM
        # Playback realizes a right-to-left layout as a mirror about the
        # metafile's reference device width; the DC's own layout is unchanged.
        self.mirror: Transform = IDENTITY_TRANSFORM
        self._width = header.device[0]
        self.device: Transform = self.fit
        self._saved: list[tuple[MetafilePage, Transform, Transform, Transform]] = []

    def matrix(self) -> Transform | None:
        """The hidden DC's world-to-device transform times the fit; None when that overflows."""
        page = multiply(multiply(self.world, self.page.matrix(), checked=False), self.mirror, checked=False)
        return multiply(page, self.fit)

    def save(self) -> None:
        self._saved.append((copy(self.page), self.world, self.mirror, self.device))

    def restore(self, level: int) -> None:
        """Restore a relative level the file reached; others leave the state unchanged."""
        if level >= 0 or -level > len(self._saved):
            return
        self.page, self.world, self.mirror, self.device = self._saved[level]
        del self._saved[level:]

    def apply(self, record) -> None:
        if isinstance(record, fixed.ModifyWorldTransform) and record.mode == MWT_LEFTMULTIPLY:
            matrix = _record_matrix(record)
            if self._modify_world(MWT_LEFTMULTIPLY, matrix):
                self.device = _modified(self.device, MWT_LEFTMULTIPLY, matrix) or self.device
            return
        if not self._apply_page(record):
            return
        candidate = self.matrix()
        if candidate is not None and (candidate == IDENTITY_TRANSFORM or in_range(candidate)):
            self.device = candidate

    def _apply_page(self, record) -> bool:
        """Update the hidden DC; whether native playback goes on to set the target's transform."""
        page = self.page
        if isinstance(record, fixed.SetLayout):
            if record.layout & ~9:  # Other layout bits fail natively.
                return False
            rtl = record.layout & 1
            self.mirror = (-1.0, 0.0, 0.0, 1.0, float32(self._width - 1), 0.0) if rtl else IDENTITY_TRANSFORM
            return True
        if isinstance(record, fixed.SetMapMode):
            page.set_mode(record.mode)
        elif isinstance(record, fixed.SetWindowOrgEx):
            page.window_origin = (record.x, record.y)
        elif isinstance(record, fixed.SetViewportOrgEx):
            page.viewport_origin = (record.x, record.y)
        elif isinstance(record, (fixed.SetWindowExtEx, fixed.SetViewportExtEx)):
            page.set_extent(window=isinstance(record, fixed.SetWindowExtEx), x=record.cx, y=record.cy)
        elif isinstance(record, (fixed.ScaleWindowExtEx, fixed.ScaleViewportExtEx)):
            if page.mode not in (MM_ISOTROPIC, MM_ANISOTROPIC):
                return False  # Native playback skips the record.
            page.scale_extent(
                window=isinstance(record, fixed.ScaleWindowExtEx),
                xn=record.x_num,
                xd=record.x_denom,
                yn=record.y_num,
                yd=record.y_denom,
            )
        else:
            mode = MWT_SET if isinstance(record, fixed.SetWorldTransform) else record.mode
            return self._modify_world(mode, _record_matrix(record))
        return True

    def _modify_world(self, mode: int, matrix: Transform) -> bool:
        world = _modified(self.world, mode, matrix)
        if world is None:
            return False
        self.world = world
        return True


def _record_matrix(record) -> Transform:
    return tuple(float32(value) for value in (record.m11, record.m12, record.m21, record.m22, record.dx, record.dy))


def _modified(current: Transform, mode: int, matrix: Transform) -> Transform | None:
    """ModifyWorldTransform on a DC holding ``current``; None when it fails."""
    if mode == MWT_IDENTITY or (mode == MWT_SET and matrix == IDENTITY_TRANSFORM):
        return IDENTITY_TRANSFORM
    if mode == MWT_SET:
        result = matrix
    elif mode in (MWT_LEFTMULTIPLY, MWT_RIGHTMULTIPLY):
        if current == IDENTITY_TRANSFORM:
            result = matrix
        elif mode == MWT_LEFTMULTIPLY:
            result = multiply(matrix, current)
        else:
            result = multiply(current, matrix)
    else:
        return None
    return result if result is not None and in_range(result) else None
