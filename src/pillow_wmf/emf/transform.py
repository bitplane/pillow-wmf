"""The world transform native EMF playback gives the target DC.

PlayEnhMetaFile leaves the DC in MM_TEXT and GM_ADVANCED. It keeps the
metafile's own page state (mapping mode, window and viewport) and world
transform itself, and after each change sets the DC's world transform to

    world, then page, then frame fit

as one float32 matrix. The frame fit maps the header's picture frame, in
0.01 mm, onto the target rectangle. Physical mapping modes take their
extents from the header's millimetre size, not from a display's DPI.
"""

from copy import copy

from ..constants import MM_ISOTROPIC, MM_TEXT
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
UNIT_SCALE_TOLERANCE = 0.001


def multiply(first: Transform, second: Transform) -> Transform:
    """``first`` then ``second``, realizing each float32 product and sum.

    Axis-aligned products are exact under any evaluation order; the order
    of rotated or sheared terms is not verified against native output.
    """
    a11, a12, a21, a22, adx, ady = first
    b11, b12, b21, b22, bdx, bdy = second
    f = float32
    return (
        f(f(a11 * b11) + f(a12 * b21)),
        f(f(a11 * b12) + f(a12 * b22)),
        f(f(a21 * b11) + f(a22 * b21)),
        f(f(a21 * b12) + f(a22 * b22)),
        f(f(f(adx * b11) + f(ady * b21)) + bdx),
        f(f(f(adx * b12) + f(ady * b22)) + bdy),
    )


def _check_device(header: Header) -> None:
    if any(value <= 0 for value in (*header.device, *header.millimetres)):
        raise PlaybackError("EMF header has no reference device size")


def frame_fit(header: Header, rect: tuple[int, int, int, int]) -> Transform:
    """Map reference-device logical units onto ``rect`` through the picture frame.

    A logical unit is one header device pixel, ``millimetres * 100 / pixels``
    frame units across. The frame width is ``right - left``; an empty axis
    counts as one frame unit over a target one pixel wider. A reversed frame
    makes native playback fail.
    """
    _check_device(header)
    axes = []
    frame = header.frame
    for axis in range(2):
        low, high = frame[axis], frame[axis + 2]
        target = rect[axis + 2] - rect[axis]
        width = high - low
        if width < 0:
            raise PlaybackError("EMF picture frame is reversed")
        if width == 0:
            width, target = 1, target + 1
        ratio = float32(target / width)
        scale = float32(ratio * float32(header.millimetres[axis] * 100 / header.device[axis]))
        origin = float32(rect[axis] - float32(low * ratio))
        axes.append((scale, origin))
    (scale_x, origin_x), (scale_y, origin_y) = axes
    if abs(scale_x - 1) < UNIT_SCALE_TOLERANCE and abs(scale_y - 1) < UNIT_SCALE_TOLERANCE:
        scale_x = scale_y = 1.0
    return scale_x, 0.0, 0.0, scale_y, origin_x, origin_y


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


def _nonsingular(transform: Transform) -> bool:
    return transform[0] * transform[3] - transform[1] * transform[2] != 0


class PlaybackTransform:
    """Track mapping records; ``matrix`` is the DC world transform to set."""

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
    )

    def __init__(self, header: Header, rect: tuple[int, int, int, int], *, parent: Transform | None = None):
        # An embedded metafile's rectangle is in its parent's logical units.
        self.fit = frame_fit(header, rect) if parent is None else multiply(frame_fit(header, rect), parent)
        device = ReferenceDevice(tuple(header.device), tuple(header.millimetres), dpi=None)
        self.page = MetafilePage(mode=MM_TEXT, window_extent=(1, 1), viewport_extent=(1, 1), device=device)
        self.world: Transform = IDENTITY_TRANSFORM
        self._saved: list[tuple[MetafilePage, Transform]] = []

    def matrix(self) -> Transform:
        return multiply(multiply(self.world, self.page.matrix()), self.fit)

    def save(self) -> None:
        self._saved.append((copy(self.page), self.world))

    def restore(self, level: int) -> None:
        """Restore a relative level the file reached; others leave the state unchanged."""
        if level >= 0 or -level > len(self._saved):
            return
        self.page, self.world = self._saved[level]
        del self._saved[level:]

    def apply(self, record) -> None:
        page = self.page
        if isinstance(record, fixed.SetMapMode):
            page.set_mode(record.mode)
        elif isinstance(record, fixed.SetWindowOrgEx):
            page.window_origin = (record.x, record.y)
        elif isinstance(record, fixed.SetViewportOrgEx):
            page.viewport_origin = (record.x, record.y)
        elif isinstance(record, (fixed.SetWindowExtEx, fixed.SetViewportExtEx)):
            page.set_extent(window=isinstance(record, fixed.SetWindowExtEx), x=record.cx, y=record.cy)
        elif isinstance(record, (fixed.ScaleWindowExtEx, fixed.ScaleViewportExtEx)):
            page.scale_extent(
                window=isinstance(record, fixed.ScaleWindowExtEx),
                xn=record.x_num,
                xd=record.x_denom,
                yn=record.y_num,
                yd=record.y_denom,
            )
        else:
            self._apply_world(record)

    def _apply_world(self, record) -> None:
        matrix = tuple(
            float32(value) for value in (record.m11, record.m12, record.m21, record.m22, record.dx, record.dy)
        )
        mode = MWT_SET if isinstance(record, fixed.SetWorldTransform) else record.mode
        if mode == MWT_IDENTITY:
            self.world = IDENTITY_TRANSFORM
            return
        if mode not in (MWT_LEFTMULTIPLY, MWT_RIGHTMULTIPLY, MWT_SET) or not _nonsingular(matrix):
            return  # Native playback rejects the record.
        if mode == MWT_LEFTMULTIPLY:
            matrix = multiply(matrix, self.world)
        elif mode == MWT_RIGHTMULTIPLY:
            matrix = multiply(self.world, matrix)
        if _nonsingular(matrix):
            self.world = matrix
