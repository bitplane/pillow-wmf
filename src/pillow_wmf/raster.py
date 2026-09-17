"""WMF rasterization into a Pillow RGB image."""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
from math import ceil
from struct import unpack_from

from PIL import Image

from .bitmap import DEFAULT_MAX_BITMAP_PIXELS, RGBBitmap, decode_dib, read_dib24
from .blit import BlitAxis, StretchAxis
from .clip import ClipRegion, RegionMask
from .ellipse import arc_figure, ellipse_cubics, round_rect_figure
from .flood import flood_spans
from .gdi import Call, Handle, UnsupportedOperation
from .geometry import DevicePath, Polygon, contains
from .halftone import halftone_bitmap
from .mapping import Mapping
from .paint import pattern_rop2, rop2, rop3
from .stroke import (
    cosmetic_line,
    cosmetic_span,
    dash_is_foreground,
    frame_footprint,
    join_outline,
    realize_pen,
    widen_segment,
)
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
    style: int = 0
    hatch: int = 0
    pattern: RGBBitmap | None = None
    monochrome: bool = False


class RasterContext(TraceContext):
    """Draw the currently supported GDI calls into an RGB Pillow image.

    Unsupported modes and primitives raise rather than silently draw an
    approximate image. Playback with ``strict=True`` exposes that boundary.
    """

    def __init__(
        self, width: int, height: int, *, background=(255, 255, 255), max_bitmap_pixels: int = DEFAULT_MAX_BITMAP_PIXELS
    ):
        super().__init__()
        if width <= 0 or height <= 0:
            raise ValueError("Image dimensions must be positive")
        if max_bitmap_pixels < 0:
            raise ValueError("Bitmap pixel limit must be nonnegative")
        self.max_bitmap_pixels = max_bitmap_pixels
        self.image = Image.new("RGB", (width, height), background)
        self._objects: dict[Handle, Pen | Brush | RegionMask | None] = {}
        self._pen = Pen((0, 0, 0), width=0)
        self._brush = Brush((255, 255, 255))
        self._position = (0, 0)
        self._polygon_fill_mode = 1
        self._rop2 = 13
        self._stretch_mode = 1
        self._background_mode = 2
        self._background_color = (255, 255, 255)
        self._text_color = (0, 0, 0)
        self.mapping = Mapping(window_extent=(width, height), viewport_extent=(width, height))
        self._clip = ClipRegion()
        self._saved: list[
            tuple[
                Mapping,
                Pen,
                Brush,
                tuple[int, int],
                ClipRegion,
                int,
                int,
                int,
                tuple[int, int, int],
                tuple[int, int, int],
                int,
            ]
        ] = []

    def _point(self, x: int, y: int) -> tuple[int, int]:
        return self.mapping.device_point(x, y)

    def is_null_object(self, handle: Handle) -> bool:
        return handle.owner is self and handle in self._objects and self._objects[handle] is None

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
        elif name == "set_rop2":
            if a["mode"] not in range(1, 17):
                raise UnsupportedOperation(f"ROP2 mode {a['mode']}")
        elif name == "set_stretch_mode":
            if a["mode"] not in (1, 2, 3, 4):
                raise UnsupportedOperation(f"Stretch mode {a['mode']}")
        elif name in ("dib_bit_blt", "dib_stretch_blt", "stretch_dib"):
            bitmap, horizontal, vertical, pad_bounds = self._prepare_transfer(name, a)
        elif name == "set_background_mode":
            if a["mode"] not in (1, 2):
                raise UnsupportedOperation(f"Background mode {a['mode']}")
        elif name == "ext_flood_fill":
            if a["mode"] not in (0, 1):
                raise UnsupportedOperation(f"Flood fill mode {a['mode']}")
        elif name == "create_pen":
            if a["style"] not in range(7) or a["width"] < 0:
                raise UnsupportedOperation("Only solid, dashed, dotted, null and inside-frame pens are supported")
        elif name == "create_brush":
            if a["style"] not in (0, 1, 2) or (a["style"] == 2 and a["hatch"] not in range(6)):
                raise UnsupportedOperation("Only solid, null and six hatch brushes are supported")
        elif name == "create_dib_pattern_brush":
            pattern = decode_dib(
                a["bitmap"],
                color_usage=0 if a["style"] == 3 else a["color_usage"],
                max_pixels=self.max_bitmap_pixels,
            )
            if a["style"] == 3:
                # The legacy record path realizes a monochrome DDB in a
                # compatible memory DC. Its bitmap creation rejects top-down
                # dimensions; failed selection preserves the previous brush.
                pattern = None if unpack_from("<i", a["bitmap"].data, 8)[0] < 0 else pattern.monochrome()
        elif name == "set_dib_to_device":
            layout = read_dib24(a["source"], color_usage=a["color_usage"], max_pixels=self.max_bitmap_pixels)
            bitmap = None
            # WMF stores WORDs here but playback sign-extends coordinates and
            # extents. Scan indexes/counts remain unsigned.
            x, y, width, height, sx, sy = (
                (a[k] + 32768) % 65536 - 32768 for k in ("x", "y", "width", "height", "src_x", "src_y")
            )
            start, count = a["start_scan"], a["scan_count"]
            # WMF requires a complete packed DIB even when only cLines rows
            # are consumed. Short buffers are rejected regardless of SizeImage.
            if layout.complete and width > 0 and height > 0 and count and start < layout.height:
                if not layout.top_down:
                    count = min(count, layout.height - start)
                bitmap = layout.decode(min(count, layout.height))
                x, y = self._point(x, y)
                horizontal = BlitAxis(x, sx, width)
                vertical = BlitAxis(y, start + count - sy - height, height)
        elif name == "select_object":
            if a["handle"] is not None and a["handle"].kind not in {"pen", "brush", "region"}:
                raise UnsupportedOperation(f"Selecting {a['handle'].kind}")
        elif name == "create_region":

            def signed(value):
                return (value + 32768) % 65536 - 32768

            # Zero-scan WMF creation fails, leaving a null object in its slot.
            # A nonzero scan count with zero area is a valid empty region.
            region_mask = (
                RegionMask.from_rectangles(
                    (signed(left), signed(scan.top), signed(right), signed(scan.bottom))
                    for scan in a["region"].scans
                    for left, right in zip(scan.endpoints[::2], scan.endpoints[1::2], strict=True)
                )
                if a["region"].scans
                else None
            )
        elif name not in {
            "pat_blt",
            "flood_fill",
            "fill_region",
            "paint_region",
            "invert_region",
            "frame_region",
            "select_clip_region",
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
            "polyline",
            "polygon",
            "poly_polygon",
            "set_polygon_fill_mode",
            "set_rop2",
            "set_background_color",
            "set_text_color",
            "rectangle",
            "ellipse",
            "arc",
            "chord",
            "pie",
            "round_rect",
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
        elif name == "set_rop2":
            self._rop2 = a["mode"]
        elif name == "set_stretch_mode":
            self._stretch_mode = a["mode"]
        elif name == "set_background_mode":
            self._background_mode = a["mode"]
        elif name == "set_background_color":
            self._background_color = rgb(a["color"])
        elif name == "set_text_color":
            self._text_color = rgb(a["color"])
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
            self._objects[result] = Brush(rgb(a["color"]), a["style"], a["hatch"])
        elif name == "create_dib_pattern_brush":
            self._objects[result] = (
                Brush((0, 0, 0), style=3, pattern=pattern, monochrome=a["style"] == 3) if pattern is not None else None
            )
        elif name == "create_region":
            self._objects[result] = region_mask
        elif name == "select_clip_region":
            self._clip = ClipRegion(mask=self._objects[a["region"]] if a["region"] is not None else None)
        elif name == "select_object":
            obj = self._objects[a["handle"]] if a["handle"] is not None else None
            if isinstance(obj, Pen):
                self._pen = obj
            elif isinstance(obj, RegionMask):
                self._clip = ClipRegion(mask=obj)
            elif obj is None:
                pass  # Selecting a null object fails without changing state.
            else:
                self._brush = obj
        elif name == "delete_object":
            del self._objects[a["handle"]]
        elif name == "move_to":
            self._position = a["x"], a["y"]
        elif name == "line_to":
            self._line(self._point(*self._position), self._point(a["x"], a["y"]))
            self._position = a["x"], a["y"]
        elif name == "polyline":
            self._stroke_path(DevicePath.polyline(self._mapped_path(a["points"])))
        elif name in {"polygon", "poly_polygon"}:
            polygons = (a["points"],) if name == "polygon" else a["polygons"]
            paths = tuple(self._mapped_path(points) for points in polygons)
            self._paint_polygons(tuple(DevicePath.polyline(path, closed=True) for path in paths))
        elif name == "set_pixel":
            self._pixel(*self._point(a["x"], a["y"]), rgb(a["color"]))
        elif name == "pat_blt":
            self._pat_blt(a["x"], a["y"], a["width"], a["height"], a["rop"])
        elif name in ("dib_bit_blt", "set_dib_to_device", "dib_stretch_blt", "stretch_dib"):
            if bitmap is not None:
                self._source_blt(
                    bitmap,
                    horizontal,
                    vertical,
                    a.get("rop", 0xCC0020),
                    pad_bounds=pad_bounds if name != "set_dib_to_device" else None,
                )
            elif name != "set_dib_to_device":
                self._pat_blt(a["x"], a["y"], a["width"], a["height"], a["rop"])
        elif name in ("flood_fill", "ext_flood_fill"):
            self._flood_fill(self._point(a["x"], a["y"]), rgb(a["color"]), a.get("mode", 0))
        elif name == "save_dc":
            self._saved.append(
                (
                    replace(self.mapping),
                    self._pen,
                    self._brush,
                    self._position,
                    self._clip,
                    self._polygon_fill_mode,
                    self._rop2,
                    self._background_mode,
                    self._background_color,
                    self._text_color,
                    self._stretch_mode,
                )
            )
        elif name == "restore_dc":
            (
                self.mapping,
                self._pen,
                self._brush,
                self._position,
                self._clip,
                self._polygon_fill_mode,
                self._rop2,
                self._background_mode,
                self._background_color,
                self._text_color,
                self._stretch_mode,
            ) = snapshot
            del self._saved[target - 1 :]
        elif name in ("intersect_clip_rect", "exclude_clip_rect"):
            left, top = self.mapping.clip_point(a["left"], a["top"])
            right, bottom = self.mapping.clip_point(a["right"], a["bottom"])
            rectangle = (min(left, right), min(top, bottom), max(left, right), max(top, bottom))
            if name == "intersect_clip_rect":
                self._clip = self._clip.intersect(rectangle)
            else:
                self._clip = self._clip.exclude(rectangle)
        elif name == "offset_clip_region":
            dx, dy = self.mapping.clip_displacement(a["x"], a["y"])
            self._clip = self._clip.offset(dx, dy)
        elif name in {"fill_region", "paint_region", "invert_region", "frame_region"}:
            region = self._objects[a["region"]]
            if region is not None:
                if name == "frame_region":
                    region = region.frame(
                        *frame_footprint(
                            a["width"],
                            a["height"],
                            *(
                                v / w
                                for v, w in zip(self.mapping.viewport_extent, self.mapping.window_extent, strict=True)
                            ),
                        ),
                        point=self._point,
                    )
                else:
                    region = region.transformed(self._point)
                brush = self._objects[a["brush"]] if "brush" in a else self._brush
                for left, top, right, bottom in region.rectangles():
                    for y in range(max(0, top), min(self.image.height, bottom)):
                        for x in range(max(0, left), min(self.image.width, right)):
                            color = (0, 0, 0) if name == "invert_region" else self._brush_color_at(x, y, brush)
                            if color is not None:
                                self._pixel(x, y, color, operation=6 if name == "invert_region" else None)
        elif name in {"rectangle", "ellipse", "arc", "chord", "pie", "round_rect"}:
            left, top = self._point(a["left"], a["top"])
            right, bottom = self._point(a["right"], a["bottom"])
            left, right = sorted((left, right))
            top, bottom = sorted((top, bottom))
            if right > left and bottom > top:
                drawing_bounds = None
                covered = False
                pen = self._realized_pen()
                if self._pen.style == 6 and not pen.cosmetic:
                    dx, dy = (
                        ceil(self._pen.width * abs(Fraction(v, w)) * 8)
                        for v, w in zip(self.mapping.viewport_extent, self.mapping.window_extent)
                    )
                    # Equality retains a degenerate centreline and widens it
                    # normally. Only a negative interior triggers GDI's
                    # pen-colour fill (or rejection for arc-family calls).
                    covered = self._pen.width > min(abs(a["right"] - a["left"]), abs(a["bottom"] - a["top"]))
                    if covered:
                        if name in {"arc", "chord", "pie"}:
                            return result
                        drawing_bounds = left * 16, top * 16, right * 16, bottom * 16
                    else:
                        drawing_bounds = left * 16 + dx, top * 16 + dy, right * 16 - dx, bottom * 16 - dy
                rectangle = name == "rectangle"
                if name == "rectangle":
                    path = DevicePath.rectangle(
                        *(drawing_bounds or (left * 16, top * 16, (right - 1) * 16, (bottom - 1) * 16))
                    )
                elif name == "ellipse":
                    path = DevicePath(
                        ellipse_cubics(
                            left, top, right, bottom, null_pen=self._pen.style == 5, drawing_bounds=drawing_bounds
                        ),
                        closed=True,
                    )
                elif name == "round_rect":
                    # Corner proportions are established before integer device
                    # mapping, just like arc radial directions.
                    width = Fraction(abs(a["ellipse_width"]) * (right - left), abs(a["right"] - a["left"]))
                    height = Fraction(abs(a["ellipse_height"]) * (bottom - top), abs(a["bottom"] - a["top"]))
                    rectangle = not width or not height
                    path = round_rect_figure(
                        left,
                        top,
                        right,
                        bottom,
                        width,
                        height,
                        null_pen=self._pen.style == 5,
                        drawing_bounds=drawing_bounds,
                    )
                else:
                    sx, sy = (
                        1 if v * w >= 0 else -1
                        for v, w in zip(self.mapping.viewport_extent, self.mapping.window_extent)
                    )
                    start = sx * a["start_x"], sy * a["start_y"]
                    end = sx * a["end_x"], sy * a["end_y"]
                    x0, x1 = sorted((sx * a["left"], sx * a["right"]))
                    y0, y1 = sorted((sy * a["top"], sy * a["bottom"]))
                    path = arc_figure(
                        left,
                        top,
                        right,
                        bottom,
                        start,
                        end,
                        closure="open" if name == "arc" else name,
                        null_pen=self._pen.style == 5,
                        drawing_bounds=drawing_bounds,
                        radial_bounds=(x0, y0, x1, y1),
                    )
                if covered:
                    for x, y in self._contour_pixels((path.vertices,)):
                        self._pixel(x, y, self._pen.color)
                elif name == "arc":
                    self._stroke_path(path)
                else:
                    brush = self._brush
                    # Rectangle's block-fill realization simplifies ROPs
                    # independent of the pattern before applying hatch
                    # transparency. Region/path fills retain the hatch mask.
                    if rectangle and brush.style == 2 and self._rop2 in (1, 6, 11, 16):
                        brush = replace(brush, style=0)
                    self._paint_polygons((path,), miter=rectangle, reserve_outline=rectangle, brush=brush)
        return result

    def _prepare_transfer(self, name, a):
        if a["source"] is None or pattern_rop2(a["rop"]) is not None:
            return None, None, None, None
        layout = read_dib24(a["source"], color_usage=a.get("color_usage", 0), max_pixels=self.max_bitmap_pixels)
        x, y = self._point(a["x"], a["y"])
        right, bottom = self._point(a["x"] + a["width"], a["y"] + a["height"])
        sw, sh = a.get("src_width", a["width"]), a.get("src_height", a["height"])
        dw, dh = right - x, bottom - y
        if not all((sw, sh, dw, dh)):
            return None, None, None, None
        scaled = abs(dw) != abs(sw) or abs(dh) != abs(sh)
        bitmap = layout.decode()
        mirrored = (dw < 0) != (sw < 0) or (dh < 0) != (sh < 0)
        copy = (a["rop"] >> 16) & 255 == 0xCC
        sy = a["src_y"]
        # STRETCHDIB exposes DIB-origin coordinates; DIB[STRETCH]BITBLT
        # adapts the source to top-left. The native ternary path also retains
        # the top-down storage distinction documented in gdi-dib-transfers.md.
        if (name == "stretch_dib") != (layout.top_down and not copy):
            sy = layout.height - sy - sh
        if scaled and self._stretch_mode == 4 and copy:
            hx = StretchAxis.create(x, dw, a["src_x"], sw, bitmap.width)
            hy = StretchAxis.create(y, dh, sy, sh, bitmap.height)
            if (
                hx.source >= bitmap.width
                or hx.source + abs(sw) <= 0
                or hy.source >= bitmap.height
                or hy.source + abs(sh) <= 0
            ):
                return None, None, None, None
            filtered = halftone_bitmap(bitmap, hx.source, hy.source, abs(sw), abs(sh), abs(dw), abs(dh))
            if filtered is not None:
                if not filtered.valid:
                    return None, None, None, None
                return (
                    filtered,
                    BlitAxis(hx.destination, abs(dw) - 1 if hx.mirrored else 0, abs(dw), -1 if hx.mirrored else 1),
                    BlitAxis(hy.destination, abs(dh) - 1 if hy.mirrored else 0, abs(dh), -1 if hy.mirrored else 1),
                    None,
                )
        if scaled:
            horizontal = StretchAxis.create(x, dw, a["src_x"], sw, bitmap.width)
            vertical = StretchAxis.create(y, dh, sy, sh, bitmap.height)
        else:
            horizontal = BlitAxis.unscaled(x, dw, a["src_x"], sw, bitmap.width, anchor_pixel=copy or mirrored)
            vertical = BlitAxis.unscaled(y, dh, sy, sh, bitmap.height, anchor_pixel=copy or mirrored)
        pad_bounds = None
        if (scaled or mirrored) and (not copy or (scaled and self._stretch_mode == 4)):
            left, top = x + min(0, dw + 1), y + min(0, dh + 1)
            pad_bounds = (left, top, left + abs(dw), top + abs(dh))
        return bitmap, horizontal, vertical, pad_bounds

    def _source_blt(self, bitmap, horizontal, vertical, operation, *, pad_bounds=None):
        table = (operation >> 16) & 255
        # EngStretchBltROP downgrades HALFTONE for ternary operations. Keep
        # this per-transfer; the saved DC stretch mode must remain unchanged.
        mode = 3 if self._stretch_mode == 4 and table != 0xCC else self._stretch_mode
        needs_pattern = (table & 15) != (table >> 4)
        left, top, right, bottom = pad_bounds or (
            horizontal.destination,
            vertical.destination,
            horizontal.destination + horizontal.length,
            vertical.destination + vertical.length,
        )
        for y in range(max(0, top), min(self.image.height, bottom)):
            for x in range(max(0, left), min(self.image.width, right)):
                if not self._clip.contains(x, y):
                    continue
                samples = (
                    bitmap.pixel(sx, sy)
                    for sy in vertical.samples(y, mode)
                    for sx in horizontal.samples(x, mode)
                    if 0 <= sx < bitmap.width and 0 <= sy < bitmap.height
                )
                source = next(samples, None)
                if source is not None:
                    for sample in samples:
                        source = tuple(
                            a & b if self._stretch_mode == 1 else a | b for a, b in zip(source, sample, strict=True)
                        )
                in_source = (
                    source is not None
                    and horizontal.destination <= x < horizontal.destination + horizontal.length
                    and vertical.destination <= y < vertical.destination + vertical.length
                )
                if not in_source and pad_bounds is None:
                    continue
                source = source if in_source else (0, 0, 0)
                pattern = self._brush_color_at(x, y, opaque=True) if needs_pattern else (0, 0, 0)
                if pattern is not None:
                    self.image.putpixel((x, y), rop3(operation, pattern, source, self.image.getpixel((x, y))))

    def _pat_blt(self, x, y, width, height, rop):
        operation = pattern_rop2(rop)
        if operation is None:
            return  # Native PatBlt rejects operations requiring a source.
        left, top = self._point(x, y)
        right, bottom = self._point(x + width, y + height)
        # PatBlt orders mapped rectangle edges (unlike mirrored source blits).
        left, right = sorted((left, right))
        top, bottom = sorted((top, bottom))
        for py in range(max(0, top), min(self.image.height, bottom)):
            for px in range(max(0, left), min(self.image.width, right)):
                # Pattern-independent functions do not need a brush, including
                # a null brush or transparent hatch gaps.
                paint = (0, 0, 0) if operation in (1, 6, 11, 16) else self._brush_color_at(px, py, opaque=True)
                if paint is not None:
                    self._pixel(px, py, paint, operation=operation)

    def _flood_fill(self, seed, color, mode):
        if self._brush.style == 1:
            return
        pixels = self.image.load()

        def eligible(x, y):
            return self._clip.contains(x, y) and ((pixels[x, y] == color) == (mode == 1))

        # Finish discovery before applying the brush/ROP: neither transparent
        # gaps nor a result equal to the source may affect connectivity.
        spans = flood_spans(self.image.width, self.image.height, seed, eligible)
        for y, left, right in spans:
            for x in range(left, right):
                paint = self._brush_color_at(x, y)
                if paint is not None:
                    self._pixel(x, y, paint)

    def _pixel(self, x: int, y: int, color: tuple[int, int, int], *, operation: int | None = None) -> None:
        if 0 <= x < self.image.width and 0 <= y < self.image.height and self._clip.contains(x, y):
            destination = self.image.getpixel((x, y))
            self.image.putpixel((x, y), rop2(self._rop2 if operation is None else operation, color, destination))

    def _line(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        self._stroke_path(DevicePath.polyline([(start[0] * 16, start[1] * 16), (end[0] * 16, end[1] * 16)]))

    def _stroke_path(self, path: DevicePath, *, miter=False) -> None:
        if self._realized_pen().cosmetic:
            # Opaque style gaps are painted beneath foreground marks, even
            # when the figure retraces itself. Keep multiplicity in each pass.
            passes = (False, True) if self._pen.style in range(1, 5) and self._background_mode == 2 else (True,)
            for foreground in passes:
                for (x, y), mark in self._cosmetic_fragments((path,)):
                    if mark == foreground:
                        self._pixel(x, y, self._pen.color if foreground else self._background_color)
            return
        foreground, gaps = self._stroke_fragments((path,), miter=miter)
        for x, y in gaps:
            self._pixel(x, y, self._background_color)
        for x, y in foreground:
            self._pixel(x, y, self._pen.color)

    def _realized_pen(self):
        return realize_pen(
            self._pen.width,
            Fraction(self.mapping.viewport_extent[0], self.mapping.window_extent[0]),
            Fraction(self.mapping.viewport_extent[1], self.mapping.window_extent[1]),
        )

    def _cosmetic_fragments(self, paths):
        if self._pen.style == 5:
            return
        for path in paths:
            # A figure starts at phase zero on its first emitted GIQ pixel,
            # not at the floor of its fractional geometric starting point.
            # Advance through unclipped spans so clipping never resets style.
            position = 0
            segments = zip(path.vertices, path.vertices[1:])
            for start, end in segments:
                span = cosmetic_span(start, end)
                major = 1 if abs(end[1] - start[1]) > abs(end[0] - start[0]) else 0
                if not span:
                    continue
                for pixel in cosmetic_line(start, end, self.image.width, self.image.height):
                    phase = position + span.step * (pixel[major] - span.start)
                    if self._pen.style in (0, 6) or dash_is_foreground(self._pen.style, phase):
                        yield pixel, True
                    elif self._background_mode == 2:
                        yield pixel, False
                position += len(span)

    def _stroke_fragments(self, paths: tuple[DevicePath, ...], *, miter=False):
        if self._pen.style == 5:
            return set(), set()
        if not self._realized_pen().cosmetic:
            return self._stroke_pixels(paths, miter=miter), set()
        foreground, gaps = set(), set()
        for pixel, mark in self._cosmetic_fragments(paths):
            (foreground if mark else gaps).add(pixel)
        return foreground, gaps - foreground

    def _stroke_pixels(self, paths: tuple[DevicePath, ...], *, miter=False) -> set[tuple[int, int]]:
        if self._pen.style == 5:
            return set()
        pen = self._realized_pen()
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
                    pixels.update(self._contour_pixels((outline,)))
            if not pen.cosmetic:
                segments = path.segments
                pairs = zip(segments, segments[1:] + (segments[:1] if path.closed else ()))
                for first, second in pairs:
                    join = join_outline(first, second, pen, miter=miter)
                    if join:
                        pixels.update(self._contour_pixels((join,)))
        return pixels

    def _contour_pixels(self, contours: tuple[Polygon, ...], *, fill_mode=1):
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

    def _paint_polygons(self, paths: tuple[DevicePath, ...], *, miter=False, reserve_outline=False, brush=None) -> None:
        paths = tuple(path for path in paths if path.segments)
        contours = tuple(path.vertices for path in paths)
        # Native copy-mode combined fill/stroke consumes the flattened contour.
        # Other ROP2 modes and stroke-only paths retain cubic tangents.
        if self._brush.style != 1 and self._rop2 == 13:
            paths = tuple(path.flattened() for path in paths)
        fill_pixels = set(self._contour_pixels(contours, fill_mode=self._polygon_fill_mode))
        foreground, gaps = self._stroke_fragments(paths, miter=miter)
        stroke_pixels = self._stroke_pixels(paths, miter=miter) if reserve_outline else foreground | gaps
        pen = self._realized_pen()
        if pen.cosmetic and not reserve_outline:
            # Cosmetic paths fill first, then emit the outline (including
            # repeated pixels). Wide combined paths exclude stroke coverage.
            stroke_pixels = set()
        for x, y in fill_pixels - stroke_pixels:
            color = self._brush_color_at(x, y, brush)
            if color is not None:
                self._pixel(x, y, color)
        if pen.cosmetic:
            for path in paths:
                self._stroke_path(path)
            return
        for x, y in gaps:
            self._pixel(x, y, self._background_color)
        for x, y in foreground:
            self._pixel(x, y, self._pen.color)

    def _brush_color_at(
        self, x: int, y: int, brush: Brush | None = None, *, opaque: bool = False
    ) -> tuple[int, int, int] | None:
        brush = self._brush if brush is None else brush
        if brush.style == 0:
            return brush.color
        if brush.style == 1:
            return None
        if brush.pattern is not None:
            color = brush.pattern.pixel(x % brush.pattern.width, y % brush.pattern.height)
            if brush.monochrome:
                return self._background_color if color == (255, 255, 255) else self._text_color
            return color
        # The six GDI hatches tile in device space. These phase offsets are
        # shared by all shapes, mapping modes and brush selections.
        horizontal = y % 8 == 3
        vertical = x % 8 == 4
        forward = (x - y) % 8 == 0
        backward = (x + y) % 8 == 7
        mark = (horizontal, vertical, forward, backward, horizontal or vertical, forward or backward)[brush.hatch]
        if mark:
            return brush.color
        return self._background_color if opaque or self._background_mode == 2 else None
