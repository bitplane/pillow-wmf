"""First WMF raster slice: solid pens/brushes and basic mapped geometry."""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction

from PIL import Image

from .clip import ClipRegion
from .ellipse import ellipse_path
from .gdi import Call, Handle, UnsupportedOperation
from .geometry import Polygon, contains
from .mapping import Mapping
from .stroke import cosmetic_line, join_outline, realize_pen, widen_segment
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
        self._polygon_fill_mode = 1
        self.mapping = Mapping(window_extent=(width, height), viewport_extent=(width, height))
        self._clip = ClipRegion()
        self._saved: list[tuple[Mapping, Pen, Brush, tuple[int, int], ClipRegion, int]] = []

    def _point(self, x: int, y: int) -> tuple[int, int]:
        return self.mapping.point(x, y)

    def _mapped_path(self, points) -> Polygon:
        path = []
        for logical_x, logical_y in points:
            x, y = self._point(logical_x, logical_y)
            path.append((x * 16, y * 16))
        return path

    def invoke(self, call: Call) -> Handle | int | None:
        call = self._prepare(call)
        name = call.name
        a = call.kwargs
        if name == "set_map_mode":
            if a["mode"] not in range(1, 9):
                raise UnsupportedOperation(f"Map mode {a['mode']}")
        elif name == "set_polygon_fill_mode":
            if a["mode"] not in (1, 2):
                raise UnsupportedOperation(f"Polygon fill mode {a['mode']}")
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
            "polygon",
            "poly_polygon",
            "set_polygon_fill_mode",
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
        elif name == "set_polygon_fill_mode":
            self._polygon_fill_mode = a["mode"]
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
        elif name in {"polygon", "poly_polygon"}:
            polygons = (a["points"],) if name == "polygon" else a["polygons"]
            paths = tuple(self._mapped_path(points) for points in polygons)
            self._paint_polygons(paths)
        elif name == "set_pixel":
            self._pixel(*self._point(a["x"], a["y"]), rgb(a["color"]))
        elif name == "save_dc":
            self._saved.append(
                (
                    replace(self.mapping),
                    self._pen,
                    self._brush,
                    self._position,
                    self._clip,
                    self._polygon_fill_mode,
                )
            )
        elif name == "restore_dc":
            self.mapping, self._pen, self._brush, self._position, self._clip, self._polygon_fill_mode = snapshot
            del self._saved[target - 1 :]
        elif name in ("intersect_clip_rect", "exclude_clip_rect"):
            left, top = self._point(a["left"], a["top"])
            right, bottom = self._point(a["right"], a["bottom"])
            rectangle = (min(left, right), min(top, bottom), max(left, right), max(top, bottom))
            if name == "intersect_clip_rect":
                self._clip = self._clip.intersect(rectangle)
            else:
                self._clip = self._clip.exclude(rectangle)
        elif name == "offset_clip_region":
            dx, dy = self.mapping.vector(a["x"], a["y"])
            self._clip = self._clip.offset(dx, dy)
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
        if 0 <= x < self.image.width and 0 <= y < self.image.height and self._clip.contains(x, y):
            self.image.putpixel((x, y), color)

    def _line(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        self._stroke_path([(start[0] * 16, start[1] * 16), (end[0] * 16, end[1] * 16)])

    def _stroke_path(self, path, *, closed=False, miter=False) -> None:
        if self._pen.style == 5:
            return
        pen = realize_pen(
            self._pen.width,
            Fraction(self.mapping.viewport_extent[0], self.mapping.window_extent[0]),
            Fraction(self.mapping.viewport_extent[1], self.mapping.window_extent[1]),
        )
        for start, end in zip(path, path[1:] + (path[:1] if closed else [])):
            if pen.cosmetic:
                for x, y in cosmetic_line(start, end, self.image.width, self.image.height):
                    self._pixel(x, y, self._pen.color)
            else:
                self._fill_path(widen_segment(start, end, pen), self._pen.color)
        if not pen.cosmetic:
            triples = zip(path[-1:] + path[:-1], path, path[1:] + path[:1]) if closed else zip(path, path[1:], path[2:])
            for before, vertex, after in triples:
                self._fill_path(join_outline(before, vertex, after, pen, miter=miter), self._pen.color)

    def _fill_path(self, polygon, color, *, fill_mode=1) -> None:
        self._fill_contours((polygon,), color, fill_mode=fill_mode)

    def _fill_contours(self, contours: tuple[Polygon, ...], color, *, fill_mode=1) -> None:
        if not contours:
            return
        left = max(0, min(p[0] for contour in contours for p in contour) // 16)
        top = max(0, min(p[1] for contour in contours for p in contour) // 16)
        right = min(self.image.width, max(p[0] for contour in contours for p in contour) // 16 + 1)
        bottom = min(self.image.height, max(p[1] for contour in contours for p in contour) // 16 + 1)
        for y in range(top, bottom):
            for x in range(left, right):
                if contains(contours, x, y, fill_mode=fill_mode):
                    self._pixel(x, y, color)

    def _paint_polygons(self, paths: tuple[Polygon, ...]) -> None:
        contours = tuple(path for path in paths if len(path) >= 2)
        self._fill_contours(contours, self._brush.color, fill_mode=self._polygon_fill_mode)
        for path in contours:
            self._stroke_path(path, closed=True)

    def _rectangle(self, left: int, top: int, right: int, bottom: int) -> None:
        path = [
            (left * 16, top * 16),
            ((right - 1) * 16, top * 16),
            ((right - 1) * 16, (bottom - 1) * 16),
            (left * 16, (bottom - 1) * 16),
        ]
        self._fill_path(path, self._brush.color)
        self._stroke_path(path, closed=True, miter=True)

    def _ellipse(self, left: int, top: int, right: int, bottom: int) -> None:
        path = ellipse_path(left, top, right, bottom)
        self._fill_path(path, self._brush.color)
        self._stroke_path(path, closed=True)
