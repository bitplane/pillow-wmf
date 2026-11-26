"""Pixel painting against a surface and explicitly supplied drawing state."""

from dataclasses import dataclass, replace
from fractions import Fraction
from functools import cached_property
from math import floor

from .bitmap import DIBLayout
from .constants import (
    ALTERNATE,
    BLACKONWHITE,
    BS_NULL,
    BS_SOLID,
    COLORONCOLOR,
    ETO_CLIPPED,
    ETO_OPAQUE,
    HALFTONE,
    OPAQUE,
    PS_NULL,
    PS_USERSTYLE,
    R2_COPYPEN,
    WINDING,
)
from .flood import flood_spans
from .geometry import DevicePath, Polygon, coverage_spans
from .gradient import triangle_spans
from .paint import pattern_rop2, rop2, rop3
from .raster_state import Brush, DrawingState
from .stroke import (
    cosmetic_line,
    cosmetic_span,
    dash_is_foreground,
    join_outline,
    realize_pen,
    realize_transformed_pen,
    widen_segment,
)
from .surface import Surface
from .widen import CAP_FLAT, CAP_ROUND, JOIN_MITER, JOIN_ROUND, PenShape, perpendicular
from .widen import outline as widen_outline
from .widener import dashes, widen, widen_dashes
from .widener import segments as widener_segments


def _nudged_index(numerator, det, step):
    """Floor of ``numerator / det`` at x + epsilon, where ``step`` is the
    numerator's change per device pixel along x: an exact boundary falls to
    the lower index only when the coordinate decreases along device x."""
    value = Fraction(numerator, det)
    return floor(value) - (value.denominator == 1 and (step > 0) != (det > 0) and step != 0)


@dataclass
class RasterPainter:
    """Paint one operation against stable pen/mapping state; never retain across calls."""

    surface: Surface
    state: DrawingState

    def __post_init__(self):
        self._pixels = self.surface.pixels()
        self._width, self._height = self.surface.width, self.surface.height

    def source_blt(
        self, bitmap, horizontal, vertical, operation, *, pad_bounds=None, transparent=None, mask=None, mode=None
    ):
        """Apply a realized source. ``transparent`` skips source pixels of that colour.

        ``mask`` is ``(sample, background)``: where ``sample(sx, sy)`` is false
        the ``background`` ROP3 applies instead of ``operation``.
        """
        coverage = getattr(bitmap, "coverage", None)
        table = (operation >> 16) & 255
        # EngStretchBltROP downgrades HALFTONE for ternary operations. Keep
        # this per-transfer; the saved DC stretch mode must remain unchanged.
        if mode is None:
            mode = COLORONCOLOR if self.state.stretch_mode == HALFTONE and table != 0xCC else self.state.stretch_mode
        tables = (table, (mask[1] >> 16) & 255) if mask is not None else (table,)
        needs_pattern = any((t & 15) != (t >> 4) for t in tables)
        reduce = (lambda a, b: a & b) if self.state.stretch_mode == BLACKONWHITE else (lambda a, b: a | b)
        left, top, right, bottom = pad_bounds or (
            horizontal.destination,
            vertical.destination,
            horizontal.destination + horizontal.length,
            vertical.destination + vertical.length,
        )
        source_left, source_right = horizontal.destination, horizontal.destination + horizontal.length
        source_top, source_bottom = vertical.destination, vertical.destination + vertical.length
        width, height = bitmap.width, bitmap.height
        clip, pixels = self.state.clip, self._pixels
        # Sample selection depends on one axis only; resolve each column once.
        columns = range(max(0, left), min(self._width, right))
        # Mask positions extrapolate past the source bitmap; sources are padded.
        mask_horizontal = replace(horizontal, limit=1 << 30) if hasattr(horizontal, "limit") else horizontal
        mask_vertical = replace(vertical, limit=1 << 30) if hasattr(vertical, "limit") else vertical
        raw_columns = [tuple(mask_horizontal.samples(x, mode)) for x in columns]
        column_samples = [tuple(sx for sx in horizontal.samples(x, mode) if 0 <= sx < width) for x in columns]
        for y in range(max(0, top), min(self._height, bottom)):
            raw_rows = tuple(mask_vertical.samples(y, mode))
            row_samples = tuple(sy for sy in vertical.samples(y, mode) if 0 <= sy < height)
            in_rows = source_top <= y < source_bottom
            for x, xs, raw_xs in zip(columns, column_samples, raw_columns, strict=True):
                if not clip.contains(x, y):
                    continue
                samples = (
                    bitmap.pixel(sx, sy)
                    for sy in row_samples
                    for sx in xs
                    if coverage is None or coverage[sy * width + sx]
                )
                op, op_table = operation, table
                # The mask covers the transfer rectangle; outside it, its bits are 0.
                if mask is not None and not (raw_rows and raw_xs and mask[0](raw_xs[0], raw_rows[0])):
                    op = mask[1]
                    op_table = (op >> 16) & 255
                source = next(samples, None)
                if source is not None:
                    for sample in samples:
                        source = tuple(reduce(a, b) for a, b in zip(source, sample, strict=True))
                in_source = source is not None and in_rows and source_left <= x < source_right
                if not in_source and pad_bounds is None:
                    continue
                source = source if in_source else (0, 0, 0)
                if transparent is not None and tuple(channel & 255 for channel in source) == transparent:
                    continue
                if op_table == 0xCC:
                    # SRCCOPY's truth table selects the source in every channel.
                    pixels[x, y] = tuple(channel & 255 for channel in source)
                    continue
                if op_table == 0xAA:
                    continue  # The destination is unchanged.
                pattern = self.brush_color_at(x, y, self.state.brush, opaque=True) if needs_pattern else (0, 0, 0)
                if pattern is not None:
                    pixels[x, y] = rop3(op, pattern, source, pixels[x, y])

    def alpha_blt(self, bitmap, alpha, horizontal, vertical, constant, blend):
        """Composite a stretched source; ``alpha`` is per-pixel or None for ``constant`` only.

        ``blend(source, destination, source_alpha, constant)`` combines one channel.
        """
        width, height = bitmap.width, bitmap.height
        pixels, clip = self._pixels, self.state.clip
        left, right = horizontal.destination, horizontal.destination + horizontal.length
        top, bottom = vertical.destination, vertical.destination + vertical.length
        columns = range(max(0, left), min(self._width, right))
        column_samples = [
            next((sx for sx in horizontal.samples(x, COLORONCOLOR) if 0 <= sx < width), None) for x in columns
        ]
        for y in range(max(0, top), min(self._height, bottom)):
            sy = next((sy for sy in vertical.samples(y, COLORONCOLOR) if 0 <= sy < height), None)
            if sy is None:
                continue
            for x, sx in zip(columns, column_samples, strict=True):
                if sx is None or not clip.contains(x, y):
                    continue
                source = bitmap.pixel(sx, sy)
                source_alpha = alpha[sy * width + sx] if alpha is not None else None
                destination = pixels[x, y]
                pixels[x, y] = tuple(
                    blend(s, d, source_alpha, constant) for s, d in zip(source, destination, strict=True)
                )

    def pat_blt(self, x, y, width, height, rop):
        operation = pattern_rop2(rop)
        if operation is None:
            return  # Native PatBlt rejects operations requiring a source.
        left, top = self.state.mapping.edge_point(x, y)
        right, bottom = self.state.mapping.edge_point(x + width, y + height)
        # PatBlt orders mapped rectangle edges (unlike mirrored source blits).
        left, right = sorted((left, right))
        top, bottom = sorted((top, bottom))
        # Pattern-independent functions do not need a brush, including a null
        # brush or transparent hatch gaps. A solid brush is one colour.
        constant = (0, 0, 0) if operation in (1, 6, 11, 16) else self._solid_color(self.state.brush)
        for py in range(max(0, top), min(self._height, bottom)):
            if constant:
                self.span(py, left, right, constant, operation=operation)
                continue
            for px in range(max(0, left), min(self._width, right)):
                paint = self.brush_color_at(px, py, self.state.brush, opaque=True)
                if paint is not None:
                    self.pixel(px, py, paint, operation=operation)

    def flood_fill(self, seed, color, mode):
        if self.state.brush.style == BS_NULL:
            return
        pixels = self._pixels

        def eligible(x, y):
            return self.state.clip.contains(x, y) and ((pixels[x, y] == color) == (mode == 1))

        # Finish discovery before applying the brush/ROP: neither transparent
        # gaps nor a result equal to the source may affect connectivity.
        spans = flood_spans(self._width, self._height, seed, eligible)
        solid = self._solid_color(self.state.brush)
        for y, left, right in spans:
            if solid:
                self.span(y, left, right, solid)
                continue
            for x in range(left, right):
                paint = self.brush_color_at(x, y, self.state.brush)
                if paint is not None:
                    self.pixel(x, y, paint)

    def text_contour(self, contour, color, rectangle, options):
        polygon = [(int(x * 16), int(y * 16)) for x, y in contour]
        for x, y in self.contour_pixels((polygon,)):
            if not options & ETO_CLIPPED or rectangle[0] <= x < rectangle[2] and rectangle[1] <= y < rectangle[3]:
                self.pixel(x, y, color, operation=13)

    def text(self, layout, rectangle, options):
        def fill(bounds):
            if bounds is not None:
                left, top, right, bottom = bounds
                for y in range(max(0, top), min(self._height, bottom)):
                    self.span(y, left, right, self.state.background_color, operation=R2_COPYPEN)

        if options & ETO_OPAQUE:
            fill(rectangle)
        if layout.background is not None:
            self.text_contour(layout.background, self.state.background_color, rectangle, options)
        for left, top, glyph in layout.glyphs:
            width, height = glyph.size
            for y in range(max(0, top), min(self._height, top + height)):
                for x in range(max(0, left), min(self._width, left + width)):
                    if options & ETO_CLIPPED and not (
                        rectangle[0] <= x < rectangle[2] and rectangle[1] <= y < rectangle[3]
                    ):
                        continue
                    index = ((y - top) * width + x - left) * glyph.channels
                    if glyph.channels == 1 and glyph.pixels[index] in (0, 255):
                        if glyph.pixels[index]:
                            self.pixel(x, y, self.state.text_color, operation=13)
                    else:
                        coverage = (
                            (glyph.pixels[index],) * 3 if glyph.channels == 1 else glyph.pixels[index : index + 3]
                        )
                        foreground = self.state.palette.colorref(self.state.text_color)
                        background = self._pixels[x, y]
                        color = tuple(
                            (f * a + b * (255 - a) + 127) // 255
                            for f, b, a in zip(foreground, background, coverage, strict=True)
                        )
                        if self.state.clip.contains(x, y):
                            self._pixels[x, y] = color

    def decorations(self, layout, rectangle, options):
        for contour in layout.decorations:
            self.text_contour(contour, self.state.text_color, rectangle, options)

    def pixel(self, x: int, y: int, color: tuple[int, int, int], *, operation: int | None = None) -> None:
        if 0 <= x < self._width and 0 <= y < self._height and self.state.clip.contains(x, y):
            color = self.state.palette.colorref(color)
            operation = self.state.rop2 if operation is None else operation
            if operation == R2_COPYPEN:
                self._pixels[x, y] = color
                return
            destination = self._pixels[x, y]
            self._pixels[x, y] = rop2(operation, color, destination)

    def span(self, y: int, start: int, end: int, color: tuple[int, int, int], *, operation: int | None = None) -> None:
        """Paint the row run ``[start, end)`` in one colour, as ``pixel`` would each pixel."""
        if not 0 <= y < self._height:
            return
        start, end = max(0, start), min(self._width, end)
        operation = self.state.rop2 if operation is None else operation
        if operation != R2_COPYPEN:
            for x in range(start, end):
                self.pixel(x, y, color, operation=operation)
            return
        color = self.state.palette.colorref(color)
        for left, right in self.state.clip.spans(y, start, end):
            self.surface.fill_span(y, left, right, color)

    def fill_box(self, left: int, top: int, right: int, bottom: int, brush: Brush | None) -> None:
        """Brush a half-open device rectangle with the current ROP2."""
        solid = self._solid_color(brush)
        for y in range(max(0, top), min(self._height, bottom)):
            if solid:
                self.span(y, left, right, solid)
                continue
            for x in range(max(0, left), min(self._width, right)):
                color = self.brush_color_at(x, y, brush)
                if color is not None:
                    self.pixel(x, y, color)

    def stroke_path(self, path: DevicePath, *, miter=False) -> None:
        if self.realized_pen.cosmetic:
            # Opaque style gaps are painted beneath foreground marks, even
            # when the figure retraces itself. Keep multiplicity in each pass.
            passes = (
                (False, True)
                if (self.state.pen.style in range(1, 5) or self.state.pen.pattern)
                and self.state.background_mode == OPAQUE
                else (True,)
            )
            for foreground in passes:
                for (x, y), mark in self._cosmetic_fragments((path,)):
                    if mark == foreground:
                        self.pixel(x, y, self.state.pen.color if foreground else self.state.background_color)
            return
        # Geometric pens have no style gaps; their footprint is one set.
        for x, y in self._stroke_pixels((path,), miter=miter):
            self.pen_pixel(x, y)

    def plg_blt(self, source, corners, rectangle, sample=None) -> None:
        """Copy a source rectangle onto a 28.4 parallelogram.

        ``corners`` are the destination of the source's upper-left,
        upper-right and lower-left corners. Each pixel inverts the mapping
        at its integer point nudged right along device x, so a source
        column or row on an exact boundary is the one just to the right of
        the point. ``sample`` decides per source pixel whether a mask lets
        it through.
        """
        (x0, y0), (x1, y1), (x2, y2) = corners
        ax, ay, bx, by = x1 - x0, y1 - y0, x2 - x0, y2 - y0
        det = ax * by - ay * bx
        if not det:
            return
        left, top, width, height = rectangle
        xs, ys = (x0, x1, x2, x1 + x2 - x0), (y0, y1, y2, y1 + y2 - y0)
        for y in range(max(0, min(ys) // 16), min(self._height, max(ys) // 16 + 1)):
            for x in range(max(0, min(xs) // 16), min(self._width, max(xs) // 16 + 1)):
                dx, dy = 16 * x - x0, 16 * y - y0
                u = _nudged_index((dx * by - dy * bx) * width, det, by)
                v = _nudged_index((ax * dy - ay * dx) * height, det, -ay)
                if not (0 <= u < width and 0 <= v < height):
                    continue
                u, v = left + u, top + v
                if sample is None or sample(u, v):
                    self.pixel(x, y, source.pixel(u, v), operation=R2_COPYPEN)

    def _parallelogram_spans(self, corners):
        (x0, y0), (x1, y1), (x2, y2) = corners
        polygon = ((x0, y0), (x1, y1), (x1 + x2 - x0, y1 + y2 - y0), (x2, y2))
        return self.contour_spans((polygon,))

    def transform_blt(self, source, corners, rectangle, rop, *, mask=None, background_rop=None, blend=None) -> None:
        """A transfer under a rotating or shearing transform.

        It covers the polygon fill of its 28.4 destination parallelogram,
        and each pixel takes the source sample at the floor of its inverted
        integer point, nudged right along device x to break ties; samples
        clamp into the source rectangle. ``mask`` chooses ``rop`` or ``background_rop`` per
        source pixel, as MaskBlt does.
        """
        (x0, y0), (x1, y1), (x2, y2) = corners
        ax, ay, bx, by = x1 - x0, y1 - y0, x2 - x0, y2 - y0
        det = ax * by - ay * bx
        if not det:
            return
        left, top, width, height = rectangle
        brush = self.state.brush

        def index(numerator, step):
            return _nudged_index(numerator, det, step)

        for y, start, end in self._parallelogram_spans(corners):
            for x in range(start, end):
                if not self.state.clip.contains(x, y):
                    continue
                dx, dy = 16 * x - x0, 16 * y - y0
                u = index((dx * by - dy * bx) * width, by)
                v = index((ax * dy - ay * dx) * height, -ay)
                u, v = min(width - 1, max(0, u)), min(height - 1, max(0, v))
                sample = source.pixel(left + u, top + v)
                if blend is not None:
                    paint = blend(sample, self._pixels[x, y], left + u, top + v)
                    if paint is not None:
                        self._pixels[x, y] = paint
                    continue
                operation = rop if mask is None or mask(left + u, top + v) else background_rop
                if (operation >> 16) & 255 == 0xCC:
                    self._pixels[x, y] = sample
                    continue
                pattern = self.brush_color_at(x, y, brush, opaque=True) or (0, 0, 0)
                self._pixels[x, y] = rop3(operation, pattern, sample, self._pixels[x, y])

    def transform_pat_blt(self, corners, rop) -> None:
        """PatBlt under a rotating transform: the brush fills the parallelogram."""
        operation = pattern_rop2(rop)
        if operation is None:
            return
        constant = (0, 0, 0) if operation in (1, 6, 11, 16) else None
        for y, start, end in self._parallelogram_spans(corners):
            for x in range(start, end):
                paint = constant or self.brush_color_at(x, y, self.state.brush, opaque=True)
                if paint is not None:
                    self.pixel(x, y, paint, operation=operation)

    def gradient_rectangle(self, corners, *, vertical: bool) -> None:
        """Shade a device rectangle between two corner colours along one axis.

        Each 16-bit channel advances by a floored 16.16 step per pixel from
        the leading edge, and the top 8 bits are kept.
        """
        first, second = corners
        axis = 1 if vertical else 0
        if first[axis] > second[axis]:
            first, second = second, first
        left, right = sorted((first[0], second[0]))
        top, bottom = sorted((first[1], second[1]))
        start, length = first[axis], second[axis] - first[axis]
        if not length or left == right or top == bottom:
            return
        # A 16.16 per-pixel step, floored, accumulated from the leading colour.
        steps = tuple(((second[2 + c] - first[2 + c]) << 16) // length for c in range(3))
        for position in range(top, bottom) if vertical else range(left, right):
            offset = position - start
            color = tuple(((first[2 + c] << 16) + offset * steps[c]) >> 24 for c in range(3))
            if vertical:
                self.span(position, left, right, color, operation=R2_COPYPEN)
            else:
                for y in range(top, bottom):
                    self.pixel(position, y, color, operation=R2_COPYPEN)

    def gradient_triangle(self, corners) -> None:
        """Shade a device triangle as native GradientFill does (see ``gradient.py``)."""
        for y, left, right, colour in triangle_spans(corners, 0, self._height):
            for x in range(max(left, 0), min(right, self._width)):
                self.pixel(x, y, colour(x), operation=R2_COPYPEN)

    def pen_pixel(self, x: int, y: int) -> None:
        """Paint one pixel of a geometric pen footprint, through its brush if any."""
        brush = self.state.pen.brush
        if brush is None:
            self.pixel(x, y, self.state.pen.color)
            return
        color = self.brush_color_at(x, y, brush)
        if color is not None:
            self.pixel(x, y, color)

    @cached_property
    def realized_pen(self):
        mapping = self.state.mapping
        if mapping.rotated:
            pen = realize_transformed_pen(self.state.pen.width, mapping, geometric=self.state.pen.geometric)
        else:
            pen = realize_pen(self.state.pen.width, *mapping.linear_scale)
        # Geometric pens are widened even below the cosmetic hairline width.
        return replace(pen, cosmetic=False) if self.state.pen.geometric else pen

    @cached_property
    def pen_shape(self) -> PenShape | None:
        """Outline construction for geometric caps and joins other than round."""
        pen = self.state.pen
        if not pen.geometric or (pen.cap == CAP_ROUND and pen.join == JOIN_ROUND):
            return None
        sx, sy = self.state.mapping.linear_scale
        return PenShape(
            self.realized_pen,
            (8 * pen.width * sx, 8 * pen.width * sy),
            (float(sx), float(sy)),
            pen.cap,
            pen.join,
            self.state.miter_limit,
            tuple(float(value) for value in self.state.mapping.world[:4]) if self.state.mapping.rotated else None,
            pen.width,
        )

    def _cosmetic_fragments(self, paths):
        if self.state.pen.style == PS_NULL:
            return
        for path in paths:
            # A figure starts at phase zero on its first emitted GIQ pixel,
            # not at the floor of its fractional geometric starting point.
            # Advance through unclipped spans so clipping never resets style.
            position = 0
            segments = zip(path.vertices, path.vertices[1:], strict=False)
            for start, end in segments:
                span = cosmetic_span(start, end)
                major = 1 if abs(end[1] - start[1]) > abs(end[0] - start[0]) else 0
                if not span:
                    continue
                for pixel in cosmetic_line(start, end, self._width, self._height):
                    phase = position + span.step * (pixel[major] - span.start)
                    if self._cosmetic_mark(phase):
                        yield pixel, True
                    elif self.state.background_mode == OPAQUE:
                        yield pixel, False
                position += len(span)

    def _cosmetic_mark(self, phase: int) -> bool:
        pen = self.state.pen
        if pen.pattern:
            phase %= sum(pen.pattern)
            for index, length in enumerate(pen.pattern):
                if phase < length:
                    return index % 2 == 0
                phase -= length
            return False
        return pen.style in (0, 6) or dash_is_foreground(pen.style, phase)

    def stroke_fragments(self, paths: tuple[DevicePath, ...], *, miter=False):
        if self.state.pen.style == PS_NULL:
            return set(), set()
        if not self.realized_pen.cosmetic:
            return self._stroke_pixels(paths, miter=miter), set()
        foreground, gaps = set(), set()
        for pixel, mark in self._cosmetic_fragments(paths):
            (foreground if mark else gaps).add(pixel)
        return foreground, gaps - foreground

    def _stroke_pixels(self, paths: tuple[DevicePath, ...], *, miter=False) -> set[tuple[int, int]]:
        if self.state.pen.style == PS_NULL:
            return set()
        pixels: set[tuple[int, int]] = set()
        if not self.realized_pen.cosmetic and not miter:
            # Wide pens fill the widened outlines by winding.
            return set(self.contour_pixels(tuple(self.widened_outlines(paths)), fill_mode=WINDING))
        for path in paths:
            for segments, closed, _ in self._pen_figures(path):
                pixels.update(self._figure_pixels(segments, closed, miter=miter))
        return pixels

    def _pen_figures(self, path: DevicePath):
        """The figures a pen strokes: each dash of a patterned geometric pen, or the path."""
        pen = self.state.pen
        if pen.geometric and pen.pattern:
            for segments, closed, seam, _ in self._dashes(path.segments, path.closed):
                yield segments, closed, seam
        else:
            yield path.segments, path.closed, 0

    def _dashes(self, segments, closed):
        """A patterned geometric pen's dashes of one figure; see ``widener.dashes``."""
        pen = self.state.pen
        pattern = list(pen.pattern)
        if pen.cap != CAP_FLAT and pen.style != PS_USERSTYLE:
            # Predefined styles pull capped dash ends back; user styles do not.
            for index in range(0, len(pattern) - 1, 2):
                dash = max(0, pattern[index] - pen.width)
                pattern[index], pattern[index + 1] = dash, pattern[index + 1] + pattern[index] - dash
        return dashes(self.widen_shape, segments, pattern, closed=closed)

    @cached_property
    def widen_shape(self) -> PenShape:
        """The pen as the native widener sees it: round caps and joins unless extended."""
        if self.pen_shape is not None:
            return self.pen_shape
        sx, sy = self.state.mapping.linear_scale
        return PenShape(
            self.realized_pen,
            (8 * self.state.pen.width * sx, 8 * self.state.pen.width * sy),
            (float(sx), float(sy)),
            CAP_ROUND,
            JOIN_ROUND,
            self.state.miter_limit,
            tuple(float(value) for value in self.state.mapping.world[:4]) if self.state.mapping.rotated else None,
            self.state.pen.width,
        )

    def widened_outlines(self, paths: tuple[DevicePath, ...]) -> list[Polygon]:
        """WidenPath's closed outlines, as the native widener builds them."""
        pen = self.state.pen
        if pen.geometric and pen.pattern:
            dashes = [dash for path in paths for dash in self._dashes(widener_segments(path), path.closed)]
            return [points for points, _ in widen_dashes(self.widen_shape, dashes)]
        return [points for points, _ in widen(self.widen_shape, paths)]

    def _figure_pixels(self, segments, closed, *, miter=False):
        if miter and self.state.mapping.rotated and not self.realized_pen.cosmetic:
            # Mitred frames under rotation place their bodies on the pen
            # perpendicular, as geometric pens with non-round joins do.
            scale = tuple(float(value) for value in self.state.mapping.rotated_pen_scale(self.state.pen.width))
            width = self.state.pen.width
            shape = PenShape(
                self.realized_pen,
                (8 * width * scale[0], 8 * width * scale[1]),
                scale,
                CAP_ROUND,
                JOIN_MITER,
                self.state.miter_limit,
                tuple(float(value) for value in self.state.mapping.world[:4]),
                width,
            )
            perps = None
            if closed and len(segments) == 4:
                # A box frame takes one perpendicular per box axis, from the
                # left-top corner, for both of its parallel edges.
                top, left, bottom, right = segments
                # The two edges leaving that corner give the vectors.
                horizontal = perpendicular(shape.pen, top.direction)
                vertical = perpendicular(shape.pen, left.direction)
                perps = [horizontal, vertical, (-horizontal[0], -horizontal[1]), (-vertical[0], -vertical[1])]
            outline = widen_outline(shape, segments, closed, perps=perps)
            return set(self.contour_pixels(tuple(outline), fill_mode=WINDING))
        if self.pen_shape is not None:
            # Each figure is widened into closed outlines filled by winding.
            outlines = tuple(widen_outline(self.pen_shape, segments, closed))
            return set(self.contour_pixels(outlines, fill_mode=WINDING))
        pen = self.realized_pen
        pixels: set[tuple[int, int]] = set()
        # A wholly collapsed figure still has a pen footprint. There is
        # no nonzero tangent with which to form a closed-path join.
        collapsed = len(segments) == 1 and segments[0].start == segments[0].end
        for index, segment in enumerate(segments):
            start, end = segment.start, segment.end
            if pen.cosmetic:
                pixels.update(cosmetic_line(start, end, self._width, self._height))
            else:
                outline = widen_segment(
                    segment,
                    pen,
                    cap_start=collapsed or not closed and index == 0,
                    cap_end=collapsed or not closed and index == len(segments) - 1,
                    miter=miter and not collapsed,
                )
                pixels.update(self.contour_pixels((outline,)))
        if not pen.cosmetic:
            pairs = zip(segments, segments[1:] + (segments[:1] if closed else ()), strict=False)
            for first, second in pairs:
                join = join_outline(first, second, pen, miter=miter)
                if join:
                    pixels.update(self.contour_pixels((join,)))
        return pixels

    def contour_spans(self, contours: tuple[Polygon, ...], *, fill_mode=ALTERNATE):
        """Yield ``(y, start, end)`` covered runs, clipped to the image."""
        if not contours:
            return
        left = max(0, min(p[0] for contour in contours for p in contour) // 16)
        top = max(0, min(p[1] for contour in contours for p in contour) // 16)
        right = min(self._width, max(p[0] for contour in contours for p in contour) // 16 + 1)
        bottom = min(self._height, max(p[1] for contour in contours for p in contour) // 16 + 1)
        yield from coverage_spans(contours, left, top, right, bottom, fill_mode=fill_mode)

    def contour_pixels(self, contours: tuple[Polygon, ...], *, fill_mode=ALTERNATE):
        for y, start, end in self.contour_spans(contours, fill_mode=fill_mode):
            for x in range(start, end):
                yield x, y

    def paint_polygons(self, paths: tuple[DevicePath, ...], *, miter=False, reserve_outline=False, brush=None) -> None:
        brush = self.state.brush if brush is None else brush
        paths = tuple(path for path in paths if path.segments)
        contours = tuple(path.vertices for path in paths)
        # Native copy-mode combined fill/stroke consumes the flattened contour.
        # Other ROP2 modes and stroke-only paths retain cubic tangents.
        if brush.style != BS_NULL and self.state.rop2 == R2_COPYPEN:
            paths = tuple(path.flattened() for path in paths)
        # Fill coverage stays as row runs; only stroke coverage is a pixel set.
        fill_spans = (
            ()
            if brush.style == BS_NULL
            else tuple(self.contour_spans(contours, fill_mode=self.state.polygon_fill_mode))
        )
        pen = self.realized_pen
        # Cosmetic strokes are emitted below with pixel multiplicity intact;
        # their deduplicated coverage sets would not be used.
        outline = set() if pen.cosmetic else self._stroke_pixels(paths, miter=miter)
        # Only cosmetic styles need a separate solid outline for fill reservation.
        stroke_pixels = (
            self._stroke_pixels(paths, miter=miter) if fill_spans and reserve_outline and pen.cosmetic else outline
        )
        if pen.cosmetic and not reserve_outline:
            # Cosmetic paths fill first, then emit the outline (including
            # repeated pixels). Wide combined paths exclude stroke coverage.
            stroke_pixels = set()
        solid = self._solid_color(brush)
        for y, start, end in fill_spans:
            if solid:
                # A constant colour paints the runs between reserved stroke pixels.
                run = start
                for x in range(start, end) if stroke_pixels else ():
                    if (x, y) in stroke_pixels:
                        self.span(y, run, x, solid)
                        run = x + 1
                self.span(y, run, end, solid)
                continue
            for x in range(start, end):
                if (x, y) not in stroke_pixels:
                    color = self.brush_color_at(x, y, brush)
                    if color is not None:
                        self.pixel(x, y, color)
        if pen.cosmetic:
            for path in paths:
                self.stroke_path(path)
            return
        for x, y in outline:
            self.pen_pixel(x, y)

    def _solid_color(self, brush: Brush | None) -> tuple[int, int, int] | None:
        """The constant colour of a solid brush; otherwise None."""
        if brush is not None and brush.style == BS_SOLID:
            return self.state.palette.colorref(brush.color)
        return None

    def brush_color_at(
        self, x: int, y: int, brush: Brush | None, *, opaque: bool = False
    ) -> tuple[int, int, int] | None:
        if brush is None:
            return None
        if brush.style == BS_SOLID:
            return self.state.palette.colorref(brush.color)
        if brush.style == BS_NULL or not brush.realizable:
            return None
        # Patterns and hatches tile from the device brush origin.
        x, y = x - self.state.brush_origin[0], y - self.state.brush_origin[1]
        if brush.pattern is not None:
            px, py = x % brush.pattern.width, y % brush.pattern.height
            if isinstance(brush.pattern, DIBLayout):
                color = self.state.palette.color(brush.pattern.color(brush.pattern.index(px, py)))
            else:
                color = brush.pattern.pixel(px, py)
            if brush.monochrome:
                return self.state.palette.colorref(
                    self.state.background_color if color == (255, 255, 255) else self.state.text_color
                )
            return color
        # The six GDI hatches tile in device space. These phase offsets are
        # shared by all shapes, mapping modes and brush selections.
        horizontal = y % 8 == 3
        vertical = x % 8 == 4
        forward = (x - y) % 8 == 0
        backward = (x + y) % 8 == 7
        mark = (horizontal, vertical, forward, backward, horizontal or vertical, forward or backward)[brush.hatch]
        if mark:
            return self.state.palette.colorref(brush.color)
        return (
            self.state.palette.colorref(self.state.background_color)
            if opaque or self.state.background_mode == OPAQUE
            else None
        )
