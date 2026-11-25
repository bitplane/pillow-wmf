"""Pixel painting against a surface and explicitly supplied drawing state."""

from dataclasses import dataclass, replace
from fractions import Fraction
from functools import cached_property
from math import ceil, floor

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
    PS_NULL,
    R2_COPYPEN,
    TRANSPARENT,
    WINDING,
)
from .flood import flood_spans
from .geometry import DevicePath, Polygon, coverage_spans
from .paint import pattern_rop2, rop2, rop3
from .raster_state import Brush, DrawingState
from .stroke import cosmetic_line, cosmetic_span, dash_is_foreground, join_outline, realize_pen, widen_segment
from .surface import Surface
from .widen import CAP_FLAT, CAP_ROUND, JOIN_ROUND, PenShape, dash_figures
from .widen import outline as widen_outline


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
                and self.state.background_mode != TRANSPARENT
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
        """Shade a device triangle by the plane through its corner colours.

        Rows run from the top vertex to the row before the bottom one; each
        covers the columns from the ceiling of the left edge to before the
        ceiling of the right edge. Each 16-bit channel of the exact plane
        value is rounded to the nearest unit before its top 8 bits are kept.
        """
        (ax, ay), (bx, by), (cx, cy) = (corner[:2] for corner in corners)
        det = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if not det:
            return
        edges = [(corners[i], corners[(i + 1) % 3]) for i in range(3)]
        top, bottom = min(ay, by, cy), max(ay, by, cy)
        for y in range(max(top, 0), min(bottom, self._height)):
            crossings = [
                Fraction(p[0]) + Fraction((q[0] - p[0]) * (y - p[1]), q[1] - p[1])
                for p, q in edges
                if min(p[1], q[1]) <= y <= max(p[1], q[1]) and p[1] != q[1]
            ]
            left, right = ceil(min(crossings)), ceil(max(crossings))
            for x in range(max(left, 0), min(right, self._width)):
                # Barycentric weights of the second and third corners, over det.
                second = (x - ax) * (cy - ay) - (y - ay) * (cx - ax)
                third = (bx - ax) * (y - ay) - (by - ay) * (x - ax)
                first = det - second - third
                color = tuple(
                    floor(
                        Fraction(
                            corners[0][2 + i] * first + corners[1][2 + i] * second + corners[2][2 + i] * third, det
                        )
                        + Fraction(1, 2)
                    )
                    >> 8
                    for i in range(3)
                )
                self.pixel(x, y, color, operation=R2_COPYPEN)

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
        pen = realize_pen(self.state.pen.width, *self.state.mapping.linear_scale)
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
                    elif self.state.background_mode != TRANSPARENT:
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
        for path in paths:
            for segments, closed in self._pen_figures(path):
                pixels.update(self._figure_pixels(segments, closed, miter=miter))
        return pixels

    def _pen_figures(self, path: DevicePath):
        """The figures a pen strokes: each dash of a patterned geometric pen, or the path."""
        pen = self.state.pen
        if pen.geometric and pen.pattern:
            # Each dash is an open figure with the pen's caps and joins.
            scale = self.state.mapping.linear_scale
            shorten = pen.width if pen.cap != CAP_FLAT else 0
            for dash in dash_figures(path.segments, pen.pattern, scale, shorten=shorten):
                yield dash, False
        else:
            yield path.segments, path.closed

    def widened_outlines(self, paths: tuple[DevicePath, ...]) -> list[Polygon] | None:
        """WidenPath's closed outlines, or None for pens without outline construction."""
        if self.pen_shape is None:
            return None
        outlines: list[Polygon] = []
        for path in paths:
            for segments, closed in self._pen_figures(path.flattened()):
                outlines.extend(widen_outline(self.pen_shape, segments, closed))
        return outlines

    def _figure_pixels(self, segments, closed, *, miter=False):
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
            if opaque or self.state.background_mode != TRANSPARENT
            else None
        )
