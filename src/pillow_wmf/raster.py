"""First WMF raster slice: solid pens/brushes and basic mapped geometry."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw

from .gdi import Call, Handle, UnsupportedOperation
from .trace import TraceContext


def rgb(colorref: int) -> tuple[int, int, int]:
    return colorref & 255, (colorref >> 8) & 255, (colorref >> 16) & 255


@dataclass(frozen=True)
class Pen:
    color: tuple[int, int, int]


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
        self._window_origin = (0, 0)
        self._viewport_origin = (0, 0)
        self._window_extent = (1, 1)
        self._viewport_extent = (1, 1)
        self._map_mode = 1

    def _point(self, x: int, y: int) -> tuple[int, int]:
        wx, wy = self._window_origin
        vx, vy = self._viewport_origin
        ww, wh = self._window_extent
        vw, vh = self._viewport_extent
        return vx + round((x - wx) * vw / ww), vy + round((y - wy) * vh / wh)

    def invoke(self, call: Call) -> Handle | int | None:
        call = self._prepare(call)
        name = call.name
        a = call.kwargs
        if name == "set_map_mode":
            if a["mode"] != 8:
                raise UnsupportedOperation(f"Map mode {a['mode']}")
        elif name in {"set_window_extent", "set_viewport_extent"}:
            if a["x"] == 0 or a["y"] == 0:
                raise UnsupportedOperation("Zero mapping extent")
        elif name == "create_pen":
            if a["style"] != 0 or a["width"] != 1:
                raise UnsupportedOperation("Only solid one-pixel pens are supported")
        elif name == "create_brush":
            if a["style"] != 0:
                raise UnsupportedOperation("Only solid brushes are supported")
        elif name == "select_object":
            if a["handle"].kind not in {"pen", "brush"}:
                raise UnsupportedOperation(f"Selecting {a['handle'].kind}")
        elif name not in {
            "set_window_origin",
            "set_viewport_origin",
            "move_to",
            "line_to",
            "rectangle",
            "ellipse",
            "delete_object",
        }:
            raise UnsupportedOperation(name)

        result = self._commit(call)
        if name == "set_map_mode":
            self._map_mode = a["mode"]
        elif name == "set_window_origin":
            self._window_origin = a["x"], a["y"]
        elif name == "set_viewport_origin":
            self._viewport_origin = a["x"], a["y"]
        elif name == "set_window_extent":
            self._window_extent = a["x"], a["y"]
        elif name == "set_viewport_extent":
            self._viewport_extent = a["x"], a["y"]
        elif name == "create_pen":
            self._objects[result] = Pen(rgb(a["color"]))
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
        elif name in {"rectangle", "ellipse"}:
            left, top = self._point(a["left"], a["top"])
            right, bottom = self._point(a["right"], a["bottom"])
            if right > left and bottom > top:
                if name == "rectangle":
                    self._rectangle(left, top, right, bottom)
                else:
                    ImageDraw.Draw(self.image).ellipse(
                        (left, top, right - 1, bottom - 1), fill=self._brush.color, outline=self._pen.color
                    )
        return result

    def _line(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        """One-pixel Bresenham stroke; GDI LineTo excludes the last point."""
        x, y = start
        end_x, end_y = end
        dx = abs(end_x - x)
        dy = abs(end_y - y)
        step_x = 1 if x < end_x else -1
        step_y = 1 if y < end_y else -1
        error = dx - dy
        pixels = self.image.load()
        while (x, y) != (end_x, end_y):
            if 0 <= x < self.image.width and 0 <= y < self.image.height:
                pixels[x, y] = self._pen.color
            doubled = 2 * error
            if doubled > -dy:
                error -= dy
                x += step_x
            if doubled < dx:
                error += dx
                y += step_y

    def _rectangle(self, left: int, top: int, right: int, bottom: int) -> None:
        pixels = self.image.load()
        for y in range(max(0, top), min(self.image.height, bottom)):
            for x in range(max(0, left), min(self.image.width, right)):
                color = self._pen.color if x in (left, right - 1) or y in (top, bottom - 1) else self._brush.color
                pixels[x, y] = color
