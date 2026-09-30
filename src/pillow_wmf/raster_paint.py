"""Pixel painting against an image and explicitly supplied drawing state."""

from dataclasses import dataclass

from PIL import Image

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
)
from .flood import flood_spans
from .geometry import DevicePath, Polygon, contains
from .paint import pattern_rop2, rop2, rop3
from .raster_state import Brush, DrawingState
from .stroke import cosmetic_line, cosmetic_span, dash_is_foreground, join_outline, realize_pen, widen_segment


@dataclass
class RasterPainter:
    """Execute pixel effects; handle bookkeeping and state changes stay in the DC."""

    image: Image.Image
    state: DrawingState

    def source_blt(self, bitmap, horizontal, vertical, operation, *, pad_bounds=None):
        coverage = getattr(bitmap, "coverage", None)
        table = (operation >> 16) & 255
        # EngStretchBltROP downgrades HALFTONE for ternary operations. Keep
        # this per-transfer; the saved DC stretch mode must remain unchanged.
        mode = COLORONCOLOR if self.state.stretch_mode == HALFTONE and table != 0xCC else self.state.stretch_mode
        needs_pattern = (table & 15) != (table >> 4)
        left, top, right, bottom = pad_bounds or (
            horizontal.destination,
            vertical.destination,
            horizontal.destination + horizontal.length,
            vertical.destination + vertical.length,
        )
        for y in range(max(0, top), min(self.image.height, bottom)):
            for x in range(max(0, left), min(self.image.width, right)):
                if not self.state.clip.contains(x, y):
                    continue
                samples = (
                    bitmap.pixel(sx, sy)
                    for sy in vertical.samples(y, mode)
                    for sx in horizontal.samples(x, mode)
                    if 0 <= sx < bitmap.width
                    and 0 <= sy < bitmap.height
                    and (coverage is None or coverage[sy * bitmap.width + sx])
                )
                source = next(samples, None)
                if source is not None:
                    for sample in samples:
                        source = tuple(
                            a & b if self.state.stretch_mode == BLACKONWHITE else a | b
                            for a, b in zip(source, sample, strict=True)
                        )
                in_source = (
                    source is not None
                    and horizontal.destination <= x < horizontal.destination + horizontal.length
                    and vertical.destination <= y < vertical.destination + vertical.length
                )
                if not in_source and pad_bounds is None:
                    continue
                source = source if in_source else (0, 0, 0)
                pattern = self.brush_color_at(x, y, self.state.brush, opaque=True) if needs_pattern else (0, 0, 0)
                if pattern is not None:
                    self.image.putpixel((x, y), rop3(operation, pattern, source, self.image.getpixel((x, y))))

    def pat_blt(self, x, y, width, height, rop):
        operation = pattern_rop2(rop)
        if operation is None:
            return  # Native PatBlt rejects operations requiring a source.
        left, top = self.state.mapping.edge_point(x, y)
        right, bottom = self.state.mapping.edge_point(x + width, y + height)
        # PatBlt orders mapped rectangle edges (unlike mirrored source blits).
        left, right = sorted((left, right))
        top, bottom = sorted((top, bottom))
        for py in range(max(0, top), min(self.image.height, bottom)):
            for px in range(max(0, left), min(self.image.width, right)):
                # Pattern-independent functions do not need a brush, including
                # a null brush or transparent hatch gaps.
                paint = (
                    (0, 0, 0)
                    if operation in (1, 6, 11, 16)
                    else self.brush_color_at(px, py, self.state.brush, opaque=True)
                )
                if paint is not None:
                    self.pixel(px, py, paint, operation=operation)

    def flood_fill(self, seed, color, mode):
        if self.state.brush.style == BS_NULL:
            return
        pixels = self.image.load()

        def eligible(x, y):
            return self.state.clip.contains(x, y) and ((pixels[x, y] == color) == (mode == 1))

        # Finish discovery before applying the brush/ROP: neither transparent
        # gaps nor a result equal to the source may affect connectivity.
        spans = flood_spans(self.image.width, self.image.height, seed, eligible)
        for y, left, right in spans:
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
                for y in range(max(0, top), min(self.image.height, bottom)):
                    for x in range(max(0, left), min(self.image.width, right)):
                        self.pixel(x, y, self.state.background_color, operation=13)

        if options & ETO_OPAQUE:
            fill(rectangle)
        if layout.background is not None:
            self.text_contour(layout.background, self.state.background_color, rectangle, options)
        for left, top, glyph in layout.glyphs:
            width, height = glyph.size
            for y in range(max(0, top), min(self.image.height, top + height)):
                for x in range(max(0, left), min(self.image.width, left + width)):
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
                        background = self.image.getpixel((x, y))
                        color = tuple(
                            (f * a + b * (255 - a) + 127) // 255
                            for f, b, a in zip(foreground, background, coverage, strict=True)
                        )
                        if self.state.clip.contains(x, y):
                            self.image.putpixel((x, y), color)

    def decorations(self, layout, rectangle, options):
        for contour in layout.decorations:
            self.text_contour(contour, self.state.text_color, rectangle, options)

    def pixel(self, x: int, y: int, color: tuple[int, int, int], *, operation: int | None = None) -> None:
        if 0 <= x < self.image.width and 0 <= y < self.image.height and self.state.clip.contains(x, y):
            color = self.state.palette.colorref(color)
            destination = self.image.getpixel((x, y))
            self.image.putpixel((x, y), rop2(self.state.rop2 if operation is None else operation, color, destination))

    def stroke_path(self, path: DevicePath, *, miter=False) -> None:
        if self.realized_pen().cosmetic:
            # Opaque style gaps are painted beneath foreground marks, even
            # when the figure retraces itself. Keep multiplicity in each pass.
            passes = (
                (False, True)
                if self.state.pen.style in range(1, 5) and self.state.background_mode != TRANSPARENT
                else (True,)
            )
            for foreground in passes:
                for (x, y), mark in self._cosmetic_fragments((path,)):
                    if mark == foreground:
                        self.pixel(x, y, self.state.pen.color if foreground else self.state.background_color)
            return
        foreground, gaps = self.stroke_fragments((path,), miter=miter)
        for x, y in gaps:
            self.pixel(x, y, self.state.background_color)
        for x, y in foreground:
            self.pixel(x, y, self.state.pen.color)

    def realized_pen(self):
        return realize_pen(self.state.pen.width, *self.state.mapping.linear_scale)

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
                for pixel in cosmetic_line(start, end, self.image.width, self.image.height):
                    phase = position + span.step * (pixel[major] - span.start)
                    if self.state.pen.style in (0, 6) or dash_is_foreground(self.state.pen.style, phase):
                        yield pixel, True
                    elif self.state.background_mode != TRANSPARENT:
                        yield pixel, False
                position += len(span)

    def stroke_fragments(self, paths: tuple[DevicePath, ...], *, miter=False):
        if self.state.pen.style == PS_NULL:
            return set(), set()
        if not self.realized_pen().cosmetic:
            return self._stroke_pixels(paths, miter=miter), set()
        foreground, gaps = set(), set()
        for pixel, mark in self._cosmetic_fragments(paths):
            (foreground if mark else gaps).add(pixel)
        return foreground, gaps - foreground

    def _stroke_pixels(self, paths: tuple[DevicePath, ...], *, miter=False) -> set[tuple[int, int]]:
        if self.state.pen.style == PS_NULL:
            return set()
        pen = self.realized_pen()
        pixels: set[tuple[int, int]] = set()
        for path in paths:
            # A wholly collapsed figure still has a pen footprint. There is
            # no nonzero tangent with which to form a closed-path join.
            collapsed = len(path.segments) == 1 and path.segments[0].start == path.segments[0].end
            for index, segment in enumerate(path.segments):
                start, end = segment.start, segment.end
                if pen.cosmetic:
                    pixels.update(cosmetic_line(start, end, self.image.width, self.image.height))
                else:
                    outline = widen_segment(
                        segment,
                        pen,
                        cap_start=collapsed or not path.closed and index == 0,
                        cap_end=collapsed or not path.closed and index == len(path.segments) - 1,
                        miter=miter and not collapsed,
                    )
                    pixels.update(self.contour_pixels((outline,)))
            if not pen.cosmetic:
                segments = path.segments
                pairs = zip(segments, segments[1:] + (segments[:1] if path.closed else ()), strict=False)
                for first, second in pairs:
                    join = join_outline(first, second, pen, miter=miter)
                    if join:
                        pixels.update(self.contour_pixels((join,)))
        return pixels

    def contour_pixels(self, contours: tuple[Polygon, ...], *, fill_mode=ALTERNATE):
        if not contours:
            return
        left = max(0, min(p[0] for contour in contours for p in contour) // 16)
        top = max(0, min(p[1] for contour in contours for p in contour) // 16)
        right = min(self.image.width, max(p[0] for contour in contours for p in contour) // 16 + 1)
        bottom = min(self.image.height, max(p[1] for contour in contours for p in contour) // 16 + 1)
        for y in range(top, bottom):
            for x in range(left, right):
                if contains(contours, x, y, fill_mode=fill_mode):
                    yield x, y

    def paint_polygons(self, paths: tuple[DevicePath, ...], *, miter=False, reserve_outline=False, brush=None) -> None:
        brush = self.state.brush if brush is None else brush
        paths = tuple(path for path in paths if path.segments)
        contours = tuple(path.vertices for path in paths)
        # Native copy-mode combined fill/stroke consumes the flattened contour.
        # Other ROP2 modes and stroke-only paths retain cubic tangents.
        if self.state.brush.style != BS_NULL and self.state.rop2 == R2_COPYPEN:
            paths = tuple(path.flattened() for path in paths)
        fill_pixels = set(self.contour_pixels(contours, fill_mode=self.state.polygon_fill_mode))
        foreground, gaps = self.stroke_fragments(paths, miter=miter)
        stroke_pixels = self._stroke_pixels(paths, miter=miter) if reserve_outline else foreground | gaps
        pen = self.realized_pen()
        if pen.cosmetic and not reserve_outline:
            # Cosmetic paths fill first, then emit the outline (including
            # repeated pixels). Wide combined paths exclude stroke coverage.
            stroke_pixels = set()
        for x, y in fill_pixels - stroke_pixels:
            color = self.brush_color_at(x, y, brush)
            if color is not None:
                self.pixel(x, y, color)
        if pen.cosmetic:
            for path in paths:
                self.stroke_path(path)
            return
        for x, y in gaps:
            self.pixel(x, y, self.state.background_color)
        for x, y in foreground:
            self.pixel(x, y, self.state.pen.color)

    def brush_color_at(
        self, x: int, y: int, brush: Brush | None, *, opaque: bool = False
    ) -> tuple[int, int, int] | None:
        if brush is None:
            return None
        if brush.style == BS_SOLID:
            return self.state.palette.colorref(brush.color)
        if brush.style == BS_NULL or not brush.realizable:
            return None
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
