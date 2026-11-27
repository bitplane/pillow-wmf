"""Text under general GM_ADVANCED transforms: transformed glyphs and native placement.

A run is realized from the font's notional outlines through one matrix that
takes notional units to device pixels: the logical em size, the glyph
orientation and the world-to-device transform together. Glyph origins are
placed in 28.4 device units as native general-transform placement does:

- without explicit advances, each glyph's advance vector is the notional
  advance through the matrix, in 32.32 fixed point; the vectors accumulate
  and each origin takes the accumulator's whole part;
- with explicit advances, the running logical sum is scaled to 28.4 along
  the baseline in single precision and rounded, then multiplied by the
  unit baseline vector and rounded again, both half away from zero.

The vertical alignment moves the origin by the ascent or descent vector, the
horizontal alignment by the whole or half total advance (halved toward zero),
and each origin then rounds to a pixel, ``(p + 8) >> 4``.
"""

from ctypes import byref
from dataclasses import dataclass, field
from fractions import Fraction
from math import sqrt
from threading import Lock

import freetype as ft

from .binary import ResourceLimitError
from .embolden import embolden
from .font import _FREETYPE, Glyph, _Face, _unpack_bitmap, whole_em
from .gdi import UnsupportedOperation
from .numeric import efloat_sqrt, float32


def _round_half_away(value) -> int:
    magnitude = int(abs(value) + Fraction(1, 2)) if isinstance(value, Fraction) else int(abs(value) + 0.5)
    return magnitude if value >= 0 else -magnitude


@dataclass
class TransformedFont:
    """A face realized through a notional-to-device matrix.

    ``matrix`` is (a, b, c, d): a notional point (u, v), y up, lands at
    device (a u + b v, c u + d v), y down, in pixels.
    """

    data: bytes
    index: int
    matrix: tuple
    units_per_em: int
    ascent: int
    descent: int
    design_advances: dict
    quality: int = 3
    # Notional black-box start and end along the baseline, by glyph.
    ink_spans: dict = field(default_factory=dict)
    # Notional black-box bottom and top, by glyph.
    ink_heights: dict = field(default_factory=dict)
    # The matrix advances follow when the baseline (escapement) differs from
    # the glyph orientation; None when they agree.
    advance_matrix: tuple | None = None
    # Simulated styles: italic shears the notional outline; bold widens the
    # ink by a pixel along the baseline and adds a pixel to each advance.
    oblique: bool = False
    embolden: bool = False
    _frame: object = field(default=None, repr=False)
    _glyphs: dict = field(default_factory=dict, repr=False)
    _lock: Lock = field(default_factory=Lock, repr=False, compare=False)
    _face: object = field(default=None, repr=False)

    def _ft_face(self):
        if self._face is None:
            with _FREETYPE:
                self._face = _Face.from_bytes(self.data, index=self.index)
        return self._face

    def glyph(self, index: int, max_pixels: int) -> Glyph:
        with self._lock:
            glyph = self._glyphs.get(index)
            if glyph is None:
                glyph = self._glyphs[index] = self._render(index, max_pixels)
        if glyph.size[0] * glyph.size[1] > max_pixels:
            raise ResourceLimitError("Glyph pixel limit exceeded")
        return glyph

    def _device_matrix(self):
        """The matrix glyph outlines are realized through.

        A scale-only transform realizes the font at a whole pixel em height,
        keeping its horizontal scale; others use the exact matrix.
        """
        a, b, c, d = self.matrix
        if b or c or not d:
            return self.matrix
        em = abs(Fraction(d)) * self.units_per_em
        whole = whole_em(em, self.units_per_em)
        return (a, b, c, d * whole / em) if whole else self.matrix

    def _render(self, index, max_pixels):
        if self.quality == 3:
            return self._scan(index, max_pixels)
        face = self._ft_face()
        if not 0 <= index < face.num_glyphs:
            index = 0
        try:
            face.load_glyph(index, ft.FT_LOAD_NO_SCALE | ft.FT_LOAD_NO_BITMAP)
            slot = face.glyph
            a, b, c, d = self.matrix
            if self.oblique:
                b, d = b + OBLIQUE * a, d + OBLIQUE * c
            # Notional units become 26.6 device units; FreeType's y is up.
            matrix = ft.Matrix(*(_round_half_away(Fraction(value) * 64 * 65536) for value in (a, b, -c, -d)))
            ft.FT_Outline_Transform(byref(slot.outline._FT_Outline), byref(matrix))
            if self.embolden:
                ft.FT_Outline_EmboldenXY(byref(slot.outline._FT_Outline), 64, 0)
            bounds = slot.get_glyph().get_cbox(ft.FT_GLYPH_BBOX_PIXELS)
            padding = 0 if self.quality in (3, 4) else 2
            if (max(1, bounds.xMax - bounds.xMin) + padding) * max(1, bounds.yMax - bounds.yMin) > max_pixels:
                raise ResourceLimitError("Glyph pixel limit exceeded")
            slot.render(
                {3: ft.FT_RENDER_MODE_MONO, 4: ft.FT_RENDER_MODE_NORMAL}.get(self.quality, ft.FT_RENDER_MODE_LCD)
            )
        except ft.FT_Exception as error:
            raise UnsupportedOperation(f"Cannot realize glyph {index}: {error}") from error
        bitmap = slot.bitmap
        channels = 1 if self.quality in (3, 4) else 3
        pixels = _unpack_bitmap(bitmap, mono=self.quality == 3)
        return Glyph(
            (bitmap.width // channels, bitmap.rows),
            (slot.bitmap_left, -slot.bitmap_top),
            pixels,
            0,
            index,
            channels,
        )

    def _scan(self, index, max_pixels):
        """A monochrome mask by the native TrueType scan rules; see ``scan_outline``."""
        face = self._ft_face()
        if not 0 <= index < face.num_glyphs:
            index = 0
        try:
            face.load_glyph(index, ft.FT_LOAD_NO_SCALE | ft.FT_LOAD_NO_BITMAP)
        except ft.FT_Exception as error:
            raise UnsupportedOperation(f"Cannot realize glyph {index}: {error}") from error
        outline = face.glyph.outline
        a, b, c, d = self._device_matrix()
        if self.oblique:
            b, d = b + OBLIQUE * a, d + OBLIQUE * c

        ma, _, _, md = self.matrix
        exact_x = Fraction(ma) > 0 > Fraction(md) and Fraction(ma) == -Fraction(md)

        # The italic shear is added exactly to the driver's 16.16 world matrix.
        world = self._device_matrix() if self.oblique else None

        def device(point):
            return _device_rule(a, b, c, d, *point, exact_x=exact_x, world=world)

        # A mirroring transform reverses the outline's orientation.
        closed = Fraction(a) * Fraction(d) - Fraction(b) * Fraction(c) < 0
        if self.embolden:
            # The scaler's first stage scales each axis by its matrix column's
            # larger component (16.16 per unit), where it emboldens the
            # points; the remaining 16.16 matrix (the world part rounded to
            # 16.16, plus the exact italic shear) then maps them and the arcs
            # are flattened in device space.
            sx = _q16(max(abs(Fraction(a)), abs(Fraction(c))))
            sy = _q16(max(abs(Fraction(b)), abs(Fraction(d))))
            wa, wb, wc, wd = self._device_matrix()
            if exact_x and not wb and not wc:
                sx = abs(Fraction(wa))  # as for the plain outline
            # The driver asks for 20 per mille on both axes: the horizontal
            # strength keeps a minimum pixel, the vertical one does not.
            # The strength follows the unsheared y column's length in pixels.
            strength = (EMBOLDEN_PER_MILLE * _ppem(wb, wd, self.units_per_em) - 10) // 1000
            # Once the vertical scale asks for a vertical strength, the outline
            # is realized that many pixels per em smaller: along x by the
            # world's vertical scale, along y by the vertical scale with the
            # italic shear (the cross terms keep their full size).

            def reduced(scale, vertical):
                em = _ppem(0, vertical, self.units_per_em)
                pixels = (EMBOLDEN_PER_MILLE * em - 10) // 1000
                return scale * Fraction(em - pixels, em) if pixels > 0 else scale

            rx = reduced(sx, wd)
            ry = reduced(sy, Fraction(wd) + (OBLIQUE * Fraction(wc) if self.oblique else 0))
            stage = [
                [(_round_half_away(64 * rx * u), _round_half_away(64 * ry * v), on) for (u, v), on in contour]
                for contour in _raw_contours(outline)
            ]
            moved = embolden(stage, strength + 1, max(0, strength), grid_fitted=True)
            ma, mb, mc, md = (_q16(value) for value in (wa, wb, wc, wd))
            if self.oblique:
                mb, md = mb + OBLIQUE * ma, md + OBLIQUE * mc
            qa, qb, qc, qd = (
                _round_half_away(Fraction(m) / scale * 65536) for m, scale in ((ma, sx), (mb, ry), (mc, rx), (md, sy))
            )
            flat = (
                _flatten(
                    [
                        (
                            (
                                ((x * qa + 0x8000) >> 16) + ((y * qb + 0x8000) >> 16),
                                ((x * qc + 0x8000) >> 16) + ((y * qd + 0x8000) >> 16),
                            ),
                            on,
                        )
                        for x, y, on in contour
                    ],
                    half=lambda value: Fraction(value, 2),
                )
                for contour in moved
            )
            contours = [contour for contour in flat if contour is not None]
        else:
            contours = [[device(point) for point in contour] for contour in _contours(outline)]
        # The rasterizer's default scan control keeps dropout control to 32
        # pixels per em and below.
        _, eb, _, ed = self._device_matrix()
        pixels = scan_outline(contours, closed=closed, dropout=_ppem(eb, ed, self.units_per_em) <= 32)
        return self._mask(pixels, index, max_pixels)

    def _mask(self, pixels, index, max_pixels):
        if not pixels:
            return Glyph((0, 0), (0, 0), b"", 0, index, 1)
        xs, ys = [x for x, _ in pixels], [y for _, y in pixels]
        left, top, width, height = min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        if width * height > max_pixels:
            raise ResourceLimitError("Glyph pixel limit exceeded")
        mask = bytearray(width * height)
        for x, y in pixels:
            mask[(y - top) * width + x - left] = 255
        return Glyph((width, height), (left, top), bytes(mask), 0, index, 1)

    def advance(self, index: int) -> tuple[int, int]:
        """The glyph's device advance vector in 28.4 units scaled by 2^32.

        A scale-only transform scales the design width by its 16.16 pixels
        per unit and rounds to whole pixels; others round it to whole pixels
        at the transformed x axis's pixels per em and lay it along that axis.
        Runs place glyphs by logical extents instead; see ``RasterContext``.
        """
        return self._advance(index, self._device_matrix() if self.advance_matrix is None else self.advance_matrix)

    def glyph_advance(self, index: int) -> tuple[int, tuple[int, int]]:
        """The driver's 28.4 advance length (fxD) and vector (ptqD) along the glyph's own baseline.

        A scale-only realization rounds the advance to whole pixels; others
        scale the notional width without rounding.
        """
        matrix = self._device_matrix()
        a, b, c, _ = matrix
        if not b and not c:
            return 16 * self._advance_pixels(index, matrix), tuple(v >> 32 for v in self._advance(index, matrix))
        units = self.design_advances.get(index, 0)
        length = float32(sqrt(float(a) ** 2 + float(c) ** 2) * 16)
        width = _round_half_away(float32(units * length))
        vector = tuple(int(Fraction(units) * Fraction(float32(16 * value))) for value in (a, c))
        return width, vector

    def _advance(self, index, matrix):
        a, b, c, _ = matrix
        pixels = self._advance_pixels(index, matrix)
        if not b and not c:
            return ((pixels if a >= 0 else -pixels) * 16 << 32, 0)
        # Whole pixels laid along the transformed x axis.
        length = sqrt(float(a) ** 2 + float(c) ** 2)
        return tuple(_round_half_away(Fraction(pixels * float(value) / length) * 16 * (1 << 32)) for value in (a, c))

    def _advance_pixels(self, index, matrix):
        a, b, c, _ = matrix
        units = self.design_advances.get(index, 0)
        bold = 1 if self.embolden and units else 0
        if not b and not c:
            scale = Fraction(_round_half_away(abs(Fraction(a)) * 65536), 65536)
            return _round_half_away(units * scale) + bold
        # Rounded half up at the transformed x axis's whole pixels per em.
        em = int(sqrt(float(a) ** 2 + float(c) ** 2) * self.units_per_em + 0.5)
        return int(Fraction(units * em, self.units_per_em) + Fraction(1, 2)) + bold

    def vertical(self, units: int) -> tuple[int, int]:
        """A notional vertical offset as a 28.4 device vector.

        A scale-only transform takes whole pixels at its 16.16 vertical scale,
        from the unrounded em as the horizontal path does.
        """
        a, b, c, d = self._device_matrix()
        if not b and not c:
            d = self.matrix[3]
            scale = Fraction(_round_half_away(abs(Fraction(d)) * 65536), 65536)
            pixels = _round_half_away(abs(units) * scale)
            return (0, pixels * 16 if (d < 0) == (units < 0) else -pixels * 16)
        return tuple(_round_half_away(Fraction(value) * units * 16) for value in (b, d))

    def ink_extent(self, index: int) -> tuple[int, int]:
        """The glyph's 28.4 ink top and bottom along the ascender, in whole pixels.

        A scale-only realization takes them from the glyph's bitmap; others
        round the notional black box out along the side vector. An empty glyph
        reports a top of 0 and a bottom of one pixel, as the driver does.
        """
        span = self.ink_heights.get(index)
        if span is None:
            return 0, 16
        _, b, c, d = self._device_matrix()
        if not b and not c:
            glyph = self.glyph(index, 1 << 30)
            top = -glyph.bearing[1] if d < 0 else glyph.bearing[1] + glyph.size[1]
            return top * 16, (top - glyph.size[1]) * 16
        length = float32(sqrt(float(b) ** 2 + float(d) ** 2) * 16)
        low, high = span
        return (_round_half_away(float32(high * length)) + 15) & ~15, _round_half_away(float32(low * length)) & ~15

    def frame(self) -> "Frame":
        """The realized font's unit vectors, cell extents and alignment vectors."""
        if self._frame is None:
            self._frame = self._compute_frame()
        return self._frame

    def _compute_frame(self):
        a, b, c, d = (float32(value) for value in self._device_matrix())
        if not b and not c:
            ascent = abs(self.vertical(self.ascent)[1])
            descent = abs(self.vertical(self.descent)[1])
            side = (0.0, 1.0 if d > 0 else -1.0)
            return Frame(
                (1.0 if a >= 0 else -1.0, 0.0),
                side,
                float32(abs(a) * 16),
                ascent,
                descent,
                self.vertical(self.ascent),
                self.vertical(-self.descent),
            )
        # The driver bounds the em box by the head table's yMax and yMin, each
        # widened by 1/64 em, and rounds each extent out to whole pixels along
        # the side vector.
        if self.advance_matrix is not None:
            a, c = float32(self.advance_matrix[0]), float32(self.advance_matrix[2])
        base_length, base = _unit(a * 16, c * 16)
        side_length, side = _unit(b * 16, d * 16)
        margin = self.units_per_em >> 6
        top = _round_half_away(float32(float32(-(self.ascent + margin)) * side_length))
        bottom = _round_half_away(float32(float32(self.descent + margin) * side_length))
        ascent, descent = ((15 - top) >> 4) * 16, ((bottom + 15) >> 4) * 16
        return Frame(
            base,
            side,
            base_length,
            ascent,
            descent,
            tuple(_round_half_away(float32(ascent * value)) for value in side),
            tuple(_round_half_away(float32(-descent * value)) for value in side),
        )

    def offset(self, units: int) -> tuple[int, int]:
        """A notional vertical offset (y up) as whole device pixels, as the driver places decorations."""
        _, b, c, d = (float32(value) for value in self._device_matrix())
        if not b and not c:
            return (0, -((_y_scale(d) * units >> 15) + 1 >> 1))
        return tuple(((_round_half_away(16 * float32(units * value)) >> 3) + 1) >> 1 for value in (b, d))

    def thickness(self, units: int) -> tuple[int, int]:
        """A decoration's thickness vector; a scale-only cell keeps at least one pixel."""
        _, b, c, d = (float32(value) for value in self._device_matrix())
        if not b and not c:
            scale = _y_scale(d)
            pixels = (scale * units >> 15) + 1 >> 1
            return (0, pixels or (1 if scale >= 1 else -1))
        return self.offset(-units)

    def ink(self, index: int) -> tuple[int, int]:
        """The glyph's black-box start and end along the baseline, 28.4."""
        left, right = self.ink_spans.get(index, (0, 0))
        length = self.frame().base_length
        return _round_half_away(float32(left * length)), _round_half_away(float32(right * length))


def _ppem(b, d, units_per_em) -> int:
    """The whole pixels per em along a matrix column (b, d), as the driver rounds them."""
    return int(sqrt(float(b) ** 2 + float(d) ** 2) * units_per_em + 0.5)


def _y_scale(d) -> int:
    """The driver's 16.16 notional-to-device y scale, notional y pointing down."""
    return _round_half_away(-Fraction(d) * 65536)


# The driver's simulated italic shears x by this much of y (0x5700 in 16.16).
OBLIQUE = Fraction(0x5700, 0x10000)
# The horizontal emboldening strength, per mille of the em: a whole pixel
# up to 50 pixels per em.
EMBOLDEN_PER_MILLE = 20


def _unit(x, y):
    """A vector's single-precision length and unit vector."""
    x, y = float32(x), float32(y)
    length = float32(sqrt(float32(float32(x * x) + float32(y * y))))
    return length, (float32(x / length), float32(y / length))


@dataclass(frozen=True)
class Frame:
    """Unit baseline and ascender vectors, the 28.4 baseline length of a
    notional unit, the 28.4 cell ascent and descent, and the alignment
    vectors from the baseline to the cell's top and bottom."""

    base: tuple[float, float]
    side: tuple[float, float]
    base_length: float
    ascent: int
    descent: int
    ascent_vector: tuple[int, int]
    descent_vector: tuple[int, int]


@dataclass(frozen=True)
class TransformedRun:
    """Glyph pixel origins, the 28.4 total advance and aligned origin, and
    the glyphs' 28.4 baseline offsets."""

    glyphs: tuple
    advance: tuple[int, int]
    origin: tuple[int, int] = (0, 0)
    offsets: tuple = ()


def place_run(
    font: TransformedFont,
    indices,
    origin,
    alignment,
    *,
    advances=(),
    vertical_advances=(),
    baseline=None,
    side=None,
    extra=0,
    break_extra=0,
    breaks=(),
    max_pixels,
):
    """Place glyphs by native general-transform placement; ``origin`` is 28.4.

    ``baseline`` gives the unit baseline vector and the logical-to-28.4 scale
    along it; ``side`` the same across it, for paired (ETO_PDY) advances.
    ``extra`` and ``break_extra`` are 28.4 spacing along the baseline after
    every glyph and after each glyph whose position is in ``breaks``.
    """
    horizontal, vertical = alignment & 6, alignment & 24
    origin_x, origin_y = origin
    frame = font.frame()
    if vertical == 0:
        up = frame.ascent_vector
        origin_x, origin_y = origin_x - up[0], origin_y - up[1]
    elif vertical == 8:
        down = frame.descent_vector
        origin_x, origin_y = origin_x - down[0], origin_y - down[1]
    positions = [(0, 0)]
    if font.advance_matrix is not None:
        positions = _escapement_positions(font, indices, advances, baseline, extra, break_extra, breaks)
    elif advances:
        ux, uy, scale = baseline
        total = rise = 0
        for number, value in enumerate(advances):
            total += value
            along = _round_half_away(float32(float32(total) * float32(scale)))
            along += extra * (number + 1) + break_extra * sum(1 for b in breaks if b <= number)
            x = _round_half_away(float32(ux * float32(along)))
            y = _round_half_away(float32(uy * float32(along)))
            if vertical_advances:
                vx, vy, side_scale = side
                rise += vertical_advances[number]
                up = _round_half_away(float32(float32(rise) * float32(side_scale)))
                x += _round_half_away(float32(vx * float32(up)))
                y += _round_half_away(float32(vy * float32(up)))
            positions.append((x, y))
    else:
        sx = sy = 0
        base = font.frame().base
        unit = tuple(int(value * (1 << 32)) for value in base)
        for number, index in enumerate(indices):
            dx, dy = font.advance(index)
            sx, sy = sx + dx, sy + dy
            spacing = extra + (break_extra if number in breaks else 0)
            if spacing:
                sx, sy = sx + unit[0] * spacing, sy + unit[1] * spacing
            positions.append((sx >> 32, sy >> 32))
    total = positions.pop()
    if horizontal == 2:
        shift = total
    elif horizontal == 6:
        shift = tuple(int(value / 2) for value in total)
    else:
        shift = (0, 0)
    glyphs = []
    for index, (px, py) in zip(indices, positions, strict=True):
        glyph = font.glyph(index, max_pixels)
        x = (origin_x + px - shift[0] + 8) >> 4
        y = (origin_y + py - shift[1] + 8) >> 4
        glyphs.append((x + glyph.bearing[0], y + glyph.bearing[1], glyph))
    return TransformedRun(tuple(glyphs), total, (origin_x - shift[0], origin_y - shift[1]), tuple(positions))


def _gen_widths(alpha, beta, width, top, bottom, height):
    """A glyph's 28.4 extents back and forward along the escapement from its centre.

    The escapement leaves the centre at ``alpha`` along the baseline and
    ``beta`` along the ascender; it meets an ellipse through the half advance
    and the ink top or bottom widened by a sixteenth of the font's ascent.
    """
    if not width:
        return 0, 0
    if not beta:
        back = int(width / 2)
        return back, width - back
    if top == bottom:
        bottom = int(height / -4)
        top = int(height / 2) + bottom
    low, high = min(bottom, 0), max(top, 0)
    if beta < 0:
        low, high = -high, -low
    margin = int(height / 16)
    high += margin
    high = high or 1
    low -= margin
    low = low or -1
    if not alpha:
        return -low, high
    across = float32(float32(alpha) / float32(float32(width) * float32(0.5)))
    across = float32(across * across)

    def extent(limit):
        ratio = float32(float32(beta) / float32(limit))
        return _round_half_away(float32(1 / efloat_sqrt(float32(float32(ratio * ratio) + across))))

    return extent(low), extent(high)


def _escapement_positions(font, indices, advances, baseline, extra, break_extra, breaks):
    """28.4 glyph origins along an escapement that differs from the glyph orientation.

    Each glyph's centre (origin plus half its device advance) lies on the
    escapement at the running sum of extents from ``_gen_widths``, or, with
    explicit advances, at the scaled logical sum plus its back extent.
    """
    ux, uy, scale = baseline
    frame = font.frame()
    (bx, by), (sx, sy) = _unit(*_column(font, 0))[1], frame.side
    cross = bx * sy - by * sx
    alpha = float32((ux * sy - uy * sx) / cross)
    beta = float32((bx * uy - by * ux) / cross)
    positions, carry, logical = [], 0, 0
    for number, index in enumerate(indices):
        width, (dx, dy) = font.glyph_advance(index)
        top, bottom = font.ink_extent(index)
        back, forward = _gen_widths(alpha, beta, width, top, bottom, frame.ascent)
        if advances:
            centre = carry + back
        else:
            # The running sum is kept in whole logical units.
            centre = (
                _round_half_away(float32(float32(_round_half_away(float32(carry / scale))) * float32(scale))) + back
            )
        positions.append(
            (
                _round_half_away(float32(float32(centre) * ux)) - int(dx / 2),
                _round_half_away(float32(float32(centre) * uy)) - int(dy / 2),
            )
        )
        if advances:
            logical += advances[number]
            carry = _round_half_away(float32(float32(logical) * float32(scale)))
        else:
            carry = carry + back + forward + extra + (break_extra if number in breaks else 0)
    if not advances:
        carry = _round_half_away(float32(float32(_round_half_away(float32(carry / scale))) * float32(scale)))
    positions.append((_round_half_away(float32(carry * ux)), _round_half_away(float32(carry * uy))))
    return positions


def _q16(value) -> Fraction:
    return Fraction(_round_half_away(Fraction(value) * 65536), 65536)


def _device_rule(a, b, c, d, u, v, *, exact_x=False, world=None):
    """A notional point (u, v) as 26.6 device coordinates, as the scaler maps it.

    A rotating or shearing matrix is applied in two stages: each axis first
    scales by the larger component of its matrix column, held in 16.16 per
    notional unit, and rounds; the remaining matrix (the driver's 16.16
    matrix divided by those scales, rounded to 16.16) then maps the scaled
    point with each product rounded; ``world``, given for italic, is that
    matrix before the exact italic shear joins it. A scale-only matrix holds its x scale in
    16.16, except an unmirrored uniform one (``exact_x``), whose products
    round from the exact scale.
    """
    if b or c:
        sx = _q16(max(abs(Fraction(a)), abs(Fraction(c))))
        sy = _q16(max(abs(Fraction(b)), abs(Fraction(d))))
        x, y = _round_half_away(64 * sx * u), _round_half_away(64 * sy * v)
        ma, mb, mc, md = (_q16(m) for m in (a, b, c, d))
        if world is not None:
            ma, mb, mc, md = (_q16(m) for m in world)
            mb, md = mb + OBLIQUE * ma, md + OBLIQUE * mc
        qa, qb, qc, qd = (_round_half_away(m / scale * 65536) for m, scale in ((ma, sx), (mb, sy), (mc, sx), (md, sy)))
        return (
            ((x * qa + 0x8000) >> 16) + ((y * qb + 0x8000) >> 16),
            ((x * qc + 0x8000) >> 16) + ((y * qd + 0x8000) >> 16),
        )
    if exact_x:
        return _round_half_away(64 * a * u), _round_half_away(64 * d * v)
    sign = 1 if a >= 0 else -1
    return sign * _round_half_away(64 * _q16(abs(Fraction(a))) * u), _round_half_away(64 * d * v)


def _column(font, column):
    a, b, c, d = font._device_matrix()
    return (float32(a) * 16, float32(c) * 16) if column == 0 else (float32(b) * 16, float32(d) * 16)


def _round_product(value, factor) -> int:
    return _round_half_away(float32(float32(value) * factor))


def opaque_area(
    font: TransformedFont, run: TransformedRun, indices, *, explicit=False, drawn=False, recorded_scale=None
):
    """The 28.4 corners of the cell parallelogram an opaque run fills.

    Along the baseline the cell spans from the origin (or, with explicit
    advances, the earliest ink) to the run's length plus any ink protruding
    past its advance; across it, the cell ascent and descent. A recorded
    run without explicit advances passes ``recorded_scale``. A ``drawn``
    cell also reaches each glyph's ink end rounded up to a whole pixel, as
    the glyph bitmaps cover; a metafile's recorded bounds do not.
    """
    frame = font.frame()
    position = left = right = 0
    for index in indices:
        start, end = font.ink(index)
        left, right = min(left, position + start), max(right, position + end)
        position += _round_half_away(float32(font.design_advances.get(index, 0) * frame.base_length))

    def along(vector):
        x, y = vector
        length = float32(
            sqrt(
                float32(
                    float32(float32(x * 0.0625) * float32(x * 0.0625))
                    + float32(float32(y * 0.0625) * float32(y * 0.0625))
                )
            )
        )
        return _round_half_away(float32(length * 16))

    length = along(run.advance)
    if recorded_scale:
        # A recorded run without explicit advances spans its whole logical
        # length: the run's notional width through the matrix's x column,
        # each component rounded to 28.4, measured, and rounded to logical
        # units of ``recorded_scale`` (28.4 per logical unit).
        a, _, c, _ = font._device_matrix()
        units = sum(font.design_advances.get(index, 0) for index in indices)
        vector = tuple(_round_half_away(Fraction(units) * Fraction(float32(16 * value))) for value in (a, c))
        logical = _round_half_away(Fraction(along(vector)) / Fraction(recorded_scale))
        length = _round_half_away(float32(logical * recorded_scale))
    if drawn and run.offsets:
        length = max(
            length, *(along(o) + ((font.ink(i)[1] + 15) & ~15) for o, i in zip(run.offsets, indices, strict=True))
        )
    left, right = min(left, position) if explicit else 0, length + max(0, right - position)
    top, bottom = frame.ascent, -frame.descent
    bx, by = frame.base
    sx, sy = frame.side
    ox, oy = run.origin
    if not by and not sx or not bx and not sy:
        # An axis-aligned cell is a pixel rectangle, one pixel wider along x.
        cx, cy = (ox + 8) >> 4, (oy + 8) >> 4
        if not by:
            x0, x1 = (
                (cx + (left >> 4), cx + ((right + 15) >> 4))
                if bx >= 0
                else (cx - ((right + 15) >> 4), cx - (left >> 4))
            )
            y0, y1 = (
                (cy + (bottom >> 4), cy + ((top + 15) >> 4))
                if sy >= 0
                else (cy - ((top + 15) >> 4), cy - (bottom >> 4))
            )
            x1 += 1
        else:
            x0, x1 = (
                (cx + (bottom >> 4), cx + ((top + 15) >> 4))
                if sx >= 0
                else (cx - ((top + 15) >> 4), cx - (bottom >> 4))
            )
            y0, y1 = (
                (cy + (left >> 4), cy + ((right + 15) >> 4))
                if by >= 0
                else (cy - ((right + 15) >> 4), cy - (left >> 4))
            )
            y1 += 1
        return ((x0 * 16, y0 * 16), (x1 * 16, y0 * 16), (x1 * 16, y1 * 16), (x0 * 16, y1 * 16))
    ax, ay = _round_product(left, bx), _round_product(left, by)
    cx, cy = _round_product(right, bx), _round_product(right, by)
    ex, ey = _round_product(top, sx), _round_product(top, sy)
    gx, gy = _round_product(bottom, sx), _round_product(bottom, sy)
    return (
        (ox + ex + ax, oy + ey + ay),
        (ox + ex + cx, oy + ey + cy),
        (ox + gx + cx, oy + gy + cy),
        (ox + gx + ax, oy + gy + ay),
    )


def decoration_areas(font: TransformedFont, run: TransformedRun, metrics):
    """28.4 parallelograms for each (position, thickness) decoration, from the pixel origin along the run."""
    ox, oy = ((value + 8) & ~15 for value in run.origin)
    ax, ay = run.advance
    areas = []
    for position, thickness in metrics:
        px, py = font.offset(position)
        tx, ty = font.thickness(thickness)
        x, y = ox + px * 16, oy + py * 16
        tx, ty = tx * 16, ty * 16
        areas.append(((x, y), (x + ax, y + ay), (x + ax + tx, y + ay + ty), (x + tx, y + ty)))
    return tuple(areas)


def baseline_vector(matrix, world_baseline):
    """The unit device baseline and the logical-to-28.4 scale along it, in single precision."""
    a, _, c, _ = matrix
    length = float32(sqrt(float32(float32(a) * float32(a)) + float32(float32(c) * float32(c))))
    ux, uy = float32(float32(a) / length), float32(float32(c) / length)
    wx, wy = world_baseline
    scale = float32(float32(sqrt(float32(float32(wx * wx) + float32(wy * wy)))) * 16)
    return ux, uy, scale


def _raw_contours(outline):
    """Contours of notional (point, on-curve) pairs as the font stores them.

    CFF outlines' cubic arcs become eight on-curve lines each, so that every
    later stage sees TrueType's quadratic contours.
    """
    points, tags, ends = outline.points, outline.tags, outline.contours
    start = 0
    for end in ends:
        raw = [(points[i], tags[i] & 3) for i in range(start, end + 1)]
        start = end + 1
        if any(tag == 2 for _, tag in raw):
            raw = _cubic_lines(raw)
        if raw:
            yield [(point, tag & 1) for point, tag in raw]


def _cubic_lines(raw):
    """A contour of (point, tag) with each cubic arc (tag 2 controls) replaced by eight lines."""
    first = next((i for i, (_, tag) in enumerate(raw) if tag == 1), None)
    if first is None:
        return []
    raw = raw[first:] + raw[:first]
    contour = [raw[0]]
    i = 1
    while i <= len(raw):
        point, tag = raw[i % len(raw)]
        if tag == 2:
            p0, p1, p2, p3 = contour[-1][0], point, raw[(i + 1) % len(raw)][0], raw[(i + 2) % len(raw)][0]
            for step in range(1, 9):
                t = Fraction(step, 8)
                s = 1 - t
                contour.append(
                    (
                        tuple(
                            s**3 * p0[k] + 3 * s * s * t * p1[k] + 3 * s * t * t * p2[k] + t**3 * p3[k] for k in (0, 1)
                        ),
                        1,
                    )
                )
            i += 3
        else:
            contour.append((point, tag))
            i += 1
    contour.pop()  # the closing copy of the start point
    return contour


def _flatten(raw, half=lambda value: value / 2):
    """A contour of (point, on-curve) pairs with quadratic arcs approximated by eight lines each."""
    # Begin at an on-curve point, inserting implied midpoints between offs.
    expanded = []
    for i, (point, on) in enumerate(raw):
        previous, previous_on = raw[i - 1]
        if not on and not previous_on:
            expanded.append(((half(point[0] + previous[0]), half(point[1] + previous[1])), 1))
        expanded.append((point, on))
    first = next((i for i, (_, on) in enumerate(expanded) if on), None)
    if first is None:
        return None
    expanded = expanded[first:] + expanded[:first]
    contour = []
    for i, (point, on) in enumerate(expanded):
        if on:
            contour.append(point)
            continue
        p0, p2 = expanded[i - 1][0], expanded[(i + 1) % len(expanded)][0]
        for step in range(1, 8):
            t = Fraction(step, 8)
            contour.append(tuple((1 - t) ** 2 * p0[k] + 2 * (1 - t) * t * point[k] + t * t * p2[k] for k in (0, 1)))
    return contour


def _contours(outline):
    """Contours of notional points, with quadratic arcs approximated by eight lines each."""
    for raw in _raw_contours(outline):
        contour = _flatten(raw)
        if contour is not None:
            yield contour


def _on_segment(p, q, x, y):
    (x0, y0), (x1, y1) = p, q
    if (x1 - x0) * (y - y0) != (y1 - y0) * (x - x0):
        return False
    return min(x0, x1) <= x <= max(x0, x1) and min(y0, y1) <= y <= max(y0, y1)


def _crossings(segments, value, axis):
    """Where segments cross the line ``axis == value``, with their winding directions."""
    other = 1 - axis
    found = []
    for p, q in segments:
        if p[axis] == q[axis]:
            continue
        low, high = sorted((p[axis], q[axis]))
        if low <= value < high:
            position = p[other] + Fraction(value - p[axis]) * (q[other] - p[other]) / (q[axis] - p[axis])
            found.append((position, 1 if q[axis] > p[axis] else -1))
    return found


def _spans(crossings):
    out, winding, start = [], 0, None
    for position, direction in sorted(crossings):
        before = winding
        winding += direction
        if not before and winding:
            start = position
        elif before and not winding:
            out.append((start, position))
    return out


def scan_outline(contours, *, closed, dropout=True):
    """Pixels a TrueType outline of 26.6 device points covers, y down.

    A pixel is covered when its centre lies inside the outline by the nonzero
    rule. A centre exactly on the outline is covered when ``closed`` (the
    font's own orientation) and not when the outline is mirrored. Dropout
    control then fills, along every row and column centre line, each stretch
    of interior that holds no pixel centre (including vertices that only
    touch the line): the pixel to the left or below, or the other neighbour
    when that one lies outside the glyph bitmap. ``dropout`` false skips that
    step.
    """
    segments = [(p, q) for contour in contours for p, q in zip(contour, contour[1:] + contour[:1], strict=True)]
    if not segments:
        return set()
    xs = [p[0] for p, _ in segments]
    ys = [p[1] for p, _ in segments]
    columns = range(min(xs) // 64 - 1, max(xs) // 64 + 2)
    rows = range(min(ys) // 64 - 1, max(ys) // 64 + 2)
    covered = set()
    for row in rows:
        centre_y = 64 * row + 32
        crossings = _crossings(segments, centre_y, 1)
        for column in columns:
            centre_x = 64 * column + 32
            if any(_on_segment(p, q, centre_x, centre_y) for p, q in segments):
                if closed:
                    covered.add((column, row))
            elif sum(direction for position, direction in crossings if position < centre_x):
                covered.add((column, row))
    if not dropout:
        return covered
    # Dropout pixels stay inside the glyph bitmap, whose pixels have centres
    # within the outline's extent (rounded half up in the rasterizer's y-up
    # frame): a choice outside it takes the other neighbour instead.
    left, bottom = (min(xs) + 31) // 64, (max(ys) + 32) // 64 - 1
    for row in rows:
        for start, end in _dropout_spans(contours, segments, 64 * row + 32, 1):
            first = -((32 - start) // 64)  # the first pixel whose centre is at or after the start
            if first * 64 + 32 > end:
                covered.add((first - 1 if first - 1 >= left else first, row))  # the pixel to the left
    for column in columns:
        for start, end in _dropout_spans(contours, segments, 64 * column + 32, 0):
            first = -((32 - start) // 64)
            if first * 64 + 32 > end:
                covered.add((column, first if first <= bottom else first - 1))  # the pixel below
    return covered


def _dropout_spans(contours, segments, value, axis):
    """Interior stretches along a centre line, with vertices that only touch it as empty stretches."""
    found = _spans(_crossings(segments, value, axis))
    other = 1 - axis
    for contour in contours:
        for index, point in enumerate(contour):
            if point[axis] != value:
                continue
            before, after = contour[index - 1][axis], contour[(index + 1) % len(contour)][axis]
            if (before - value) * (after - value) > 0:
                found.append((point[other], point[other]))
    return found
