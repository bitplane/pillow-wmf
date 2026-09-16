"""First WMF raster slice: solid pens/brushes and basic mapped geometry."""

from __future__ import annotations

from dataclasses import dataclass, replace

from PIL import Image, ImageDraw

from .ellipse import contains, ellipse_path, widen_pixel_path
from .gdi import Call, Handle, UnsupportedOperation
from .mapping import Mapping
from .stroke import line_outline
from .trace import TraceContext


def rgb(colorref: int) -> tuple[int, int, int]:
    return colorref & 255, (colorref >> 8) & 255, (colorref >> 16) & 255


@dataclass(frozen=True)
class Pen:
    color: tuple[int, int, int]
    width: int = 1
    style: int = 0


@dataclass(frozen=True)
class Brush:
    color: tuple[int, int, int]


class RasterContext(TraceContext):
    """Draw the currently supported GDI calls into an RGB Pillow image.

    Unsupported modes and primitives raise rather than silently draw an
    approximate image. Playback with ``strict=True`` exposes that boundary.
    """

    def __init__(self, width: int, height: int, *, background=(255, 255, 255)):
        super().__init__()
        if width <= 0 or height <= 0:
            raise ValueError("Image dimensions must be positive")
        self.image = Image.new("RGB", (width, height), background)
        self._objects: dict[Handle, Pen | Brush] = {}
        self._pen = Pen((0, 0, 0))
        self._brush = Brush((255, 255, 255))
        self._position = (0, 0)
        self.mapping = Mapping(window_extent=(width, height), viewport_extent=(width, height))
        self._clip: set[tuple[int, int]] | None = None
        self._saved: list[tuple[Mapping, Pen, Brush, tuple[int, int], set[tuple[int, int]] | None]] = []

    def _point(self, x: int, y: int) -> tuple[int, int]:
        return self.mapping.point(x, y)

    def invoke(self, call: Call) -> Handle | int | None:
        call = self._prepare(call)
        name = call.name
        a = call.kwargs
        if name == "set_map_mode":
            if a["mode"] not in range(1, 9):
                raise UnsupportedOperation(f"Map mode {a['mode']}")
        elif name == "create_pen":
            if a["style"] not in (0, 5) or a["width"] < 0:
                raise UnsupportedOperation("Only solid and null pens are supported")
        elif name == "create_brush":
            if a["style"] != 0:
                raise UnsupportedOperation("Only solid brushes are supported")
        elif name == "select_object":
            if a["handle"].kind not in {"pen", "brush"}:
                raise UnsupportedOperation(f"Selecting {a['handle'].kind}")
        elif name not in {
            "set_window_origin",
            "set_viewport_origin",
            "set_window_extent",
            "set_viewport_extent",
            "offset_window_origin",
            "offset_viewport_origin",
            "scale_window_extent",
            "scale_viewport_extent",
            "move_to",
            "line_to",
            "rectangle",
            "ellipse",
            "set_pixel",
            "save_dc",
            "restore_dc",
            "intersect_clip_rect",
            "exclude_clip_rect",
            "offset_clip_region",
            "delete_object",
        }:
            raise UnsupportedOperation(name)

        if name == "restore_dc":
            level = a["saved_dc"]
            target = level if level > 0 else len(self._saved) + level + 1
            snapshot = self._saved[target - 1]
        result = self._commit(call)
        if name == "set_map_mode":
            self.mapping.set_mode(a["mode"])
        elif name == "set_window_origin":
            self.mapping.window_origin = a["x"], a["y"]
        elif name == "set_viewport_origin":
            self.mapping.viewport_origin = a["x"], a["y"]
        elif name == "set_window_extent":
            self.mapping.set_extent(window=True, x=a["x"], y=a["y"])
        elif name == "set_viewport_extent":
            self.mapping.set_extent(window=False, x=a["x"], y=a["y"])
        elif name == "offset_window_origin":
            x, y = self.mapping.window_origin
            self.mapping.window_origin = x + a["x"], y + a["y"]
        elif name == "offset_viewport_origin":
            x, y = self.mapping.viewport_origin
            self.mapping.viewport_origin = x + a["x"], y + a["y"]
        elif name in ("scale_window_extent", "scale_viewport_extent"):
            self.mapping.scale_extent(
                window=name == "scale_window_extent",
                xn=a["x_numerator"],
                xd=a["x_denominator"],
                yn=a["y_numerator"],
                yd=a["y_denominator"],
            )
        elif name == "create_pen":
            self._objects[result] = Pen(rgb(a["color"]), a["width"], a["style"])
        elif name == "create_brush":
            self._objects[result] = Brush(rgb(a["color"]))
        elif name == "select_object":
            obj = self._objects[a["handle"]]
            if isinstance(obj, Pen):
                self._pen = obj
            else:
                self._brush = obj
        elif name == "delete_object":
            del self._objects[a["handle"]]
        elif name == "move_to":
            self._position = a["x"], a["y"]
        elif name == "line_to":
            self._line(self._point(*self._position), self._point(a["x"], a["y"]))
            self._position = a["x"], a["y"]
        elif name == "set_pixel":
            self._pixel(*self._point(a["x"], a["y"]), rgb(a["color"]))
        elif name == "save_dc":
            self._saved.append(
                (
                    replace(self.mapping),
                    self._pen,
                    self._brush,
                    self._position,
                    None if self._clip is None else self._clip.copy(),
                )
            )
        elif name == "restore_dc":
            self.mapping, self._pen, self._brush, self._position, self._clip = snapshot
            del self._saved[target - 1 :]
        elif name in ("intersect_clip_rect", "exclude_clip_rect"):
            left, top = self._point(a["left"], a["top"])
            right, bottom = self._point(a["right"], a["bottom"])
            region = {
                (x, y)
                for y in range(max(0, min(top, bottom)), min(self.image.height, max(top, bottom)))
                for x in range(max(0, min(left, right)), min(self.image.width, max(left, right)))
            }
            current = (
                self._clip
                if self._clip is not None
                else {(x, y) for y in range(self.image.height) for x in range(self.image.width)}
            )
            self._clip = current & region if name == "intersect_clip_rect" else current - region
        elif name == "offset_clip_region":
            if self._clip is not None:
                dx, dy = self.mapping.vector(a["x"], a["y"])
                self._clip = {(x + dx, y + dy) for x, y in self._clip}
        elif name in {"rectangle", "ellipse"}:
            left, top = self._point(a["left"], a["top"])
            right, bottom = self._point(a["right"], a["bottom"])
            left, right = sorted((left, right))
            top, bottom = sorted((top, bottom))
            if right > left and bottom > top:
                if name == "rectangle":
                    self._rectangle(left, top, right, bottom)
                else:
                    self._ellipse(left, top, right, bottom)
        return result

    def _pixel(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < self.image.width and 0 <= y < self.image.height and (self._clip is None or (x, y) in self._clip):
            self.image.putpixel((x, y), color)

    def _line(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        """One-pixel Bresenham stroke; GDI LineTo excludes the last point."""
        x, y = start
        end_x, end_y = end
        dx = abs(end_x - x)
        dy = abs(end_y - y)
        step_x = 1 if x < end_x else -1
        step_y = 1 if y < end_y else -1
        error = dx - dy
        if self._pen.style == 5:
            return
        scale_x = self.mapping.viewport_extent[0] / self.mapping.window_extent[0]
        scale_y = self.mapping.viewport_extent[1] / self.mapping.window_extent[1]
        if self._pen.width and (
            (self._pen.width == 1 and abs(scale_x) != 1)
            or (self._pen.width > 1 and (abs(scale_x) != 1 or abs(scale_y) != 1))
        ):
            outline = line_outline(start, end, self._pen.width, scale_x, scale_y)
            if outline:
                left = max(0, min(p[0] for p in outline) // 16)
                top = max(0, min(p[1] for p in outline) // 16)
                right = min(self.image.width, max(p[0] for p in outline) // 16 + 2)
                bottom = min(self.image.height, max(p[1] for p in outline) // 16 + 2)
                for py in range(top, bottom):
                    for px in range(left, right):
                        if contains((outline,), px, py):
                            self._pixel(px, py, self._pen.color)
                return
        pen_width = max(1, abs(self.mapping.vector(self._pen.width, 0)[0])) if self._pen.width else 1
        pen_height = max(1, abs(self.mapping.vector(0, self._pen.width)[1])) if self._pen.width else 1
        if pen_width == 1 and self._pen.width == 1:
            pen_height = 1
        kernel = Image.new("1", (pen_width, pen_height))
        if pen_width == pen_height == 1:
            kernel.putpixel((0, 0), 1)
        else:
            ImageDraw.Draw(kernel).ellipse((0, 0, pen_width - 1, pen_height - 1), fill=1)
        while (x, y) != (end_x, end_y):
            self._stroke_pixel(x, y, kernel)
            doubled = 2 * error
            if doubled > -dy or (doubled == -dy and step_x < 0):
                error -= dy
                x += step_x
            if doubled < dx or (doubled == dx and step_y < 0):
                error += dx
                y += step_y
        if pen_width > 1 or pen_height > 1:
            self._stroke_pixel(end_x, end_y, kernel)
        # Anisotropic geometric pens need their own device-space widening
        # rule; the circular logical-space body only matches unit mapping.
        if (
            self._pen.width > 1
            and abs(self.mapping.viewport_extent[0]) == abs(self.mapping.window_extent[0])
            and abs(self.mapping.viewport_extent[1]) == abs(self.mapping.window_extent[1])
        ):
            self._fill_stroke_body(start, end)

    def _fill_stroke_body(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        """Cover the continuous body between the discrete pen endcaps."""
        scale_x = self.mapping.viewport_extent[0] / self.mapping.window_extent[0]
        scale_y = self.mapping.viewport_extent[1] / self.mapping.window_extent[1]
        dx = (end[0] - start[0]) / scale_x
        dy = (end[1] - start[1]) / scale_y
        length_squared = dx * dx + dy * dy
        if not length_squared:
            return
        radius = self._pen.width / 2
        x_margin = abs(scale_x) * radius + 1
        y_margin = abs(scale_y) * radius + 1
        for y in range(
            max(0, int(min(start[1], end[1]) - y_margin)),
            min(self.image.height, int(max(start[1], end[1]) + y_margin + 1)),
        ):
            for x in range(
                max(0, int(min(start[0], end[0]) - x_margin)),
                min(self.image.width, int(max(start[0], end[0]) + x_margin + 1)),
            ):
                logical_x = (x - start[0]) / scale_x
                logical_y = (y - start[1]) / scale_y
                projection = (logical_x * dx + logical_y * dy) / length_squared
                if (
                    0 <= projection <= 1
                    and (logical_x - projection * dx) ** 2 + (logical_y - projection * dy) ** 2 <= radius**2
                ):
                    self._pixel(x, y, self._pen.color)

    def _stroke_pixel(self, x: int, y: int, kernel: Image.Image) -> None:
        left, top = kernel.width // 2, kernel.height // 2
        for ky in range(kernel.height):
            for kx in range(kernel.width):
                if kernel.getpixel((kx, ky)):
                    self._pixel(x + kx - left, y + ky - top, self._pen.color)

    def _rectangle(self, left: int, top: int, right: int, bottom: int) -> None:
        # A null pen removes the outline, but GDI still reserves its final
        # right/bottom boundary when it fills a rectangle.
        if self._pen.style == 5:
            right -= 1
            bottom -= 1
        for y in range(max(0, top), min(self.image.height, bottom)):
            for x in range(max(0, left), min(self.image.width, right)):
                if self._pen.style != 5 and (x in (left, right - 1) or y in (top, bottom - 1)):
                    self._pixel(x, y, self._pen.color)
                else:
                    self._pixel(x, y, self._brush.color)

    def _ellipse(self, left: int, top: int, right: int, bottom: int) -> None:
        if right - left < 2 or bottom - top < 2 or self._pen.width > 1:
            ImageDraw.Draw(self.image).ellipse(
                (left, top, right - 1, bottom - 1),
                fill=self._brush.color,
                outline=None if self._pen.style == 5 else self._pen.color,
            )
            return

        path = ellipse_path(left, top, right, bottom)
        stroke = widen_pixel_path(path) if self._pen.style != 5 else None
        for y in range(max(0, top - 1), min(self.image.height, bottom + 1)):
            for x in range(max(0, left - 1), min(self.image.width, right + 1)):
                if stroke is not None and contains(stroke, x, y):
                    self._pixel(x, y, self._pen.color)
                elif contains((path,), x, y):
                    self._pixel(x, y, self._brush.color)
        if right - left == 2 and self._pen.style != 5:
            # At this width the two arcs form a cusp.  Its one-pixel cap is
            # owned by the left pixel at both vertical extrema.
            self._pixel(left, top, self._pen.color)
            self._pixel(left, bottom - 1, self._pen.color)
