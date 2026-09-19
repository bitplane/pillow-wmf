"""WMF rasterization into a Pillow RGB image."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum, auto
from fractions import Fraction
from math import floor

from PIL import Image

from .bitmap import DEFAULT_MAX_BITMAP_PIXELS, DIBLayout, RGBBitmap, read_dib
from .bitmap16 import read_bitmap16
from .blit import BlitAxis, StretchAxis
from .clip import ClipRegion, RegionMask
from .ellipse import arc_figure, box_corners, ellipse_cubics, round_rect_figure
from .flood import flood_spans
from .gdi import Call, Handle, UnsupportedOperation
from .geometry import DevicePath, Polygon, contains
from .halftone import (
    HalftoneExpansion,
    HalftoneMode,
    HalftoneReduction,
    classify_content,
    fixup_candidate,
    halftone_bitmap,
)
from .halftone_fixup import fixup_bitmap
from .mapping import Mapping
from .paint import pattern_rop2, rop2, rop3
from .palette import DEFAULT_COLORS, LogicalPalette, PaletteIndex
from .stroke import (
    cosmetic_line,
    cosmetic_span,
    dash_is_foreground,
    frame_footprint,
    join_outline,
    realize_pen,
    widen_segment,
)
from .text import FontCollection, TextLayout, layout_text
from .trace import TraceContext
from .wmf.objects import Font


def rgb(colorref: int) -> tuple[int, int, int]:
    return colorref & 255, (colorref >> 8) & 255, (colorref >> 16) & 255


def logical_color(colorref):
    return PaletteIndex(colorref & 65535) if colorref >> 24 == 1 else rgb(colorref)


@dataclass(frozen=True)
class Pen:
    color: tuple[int, int, int] | PaletteIndex
    width: int = 1
    style: int = 0


@dataclass(frozen=True)
class Brush:
    color: tuple[int, int, int] | PaletteIndex
    style: int = 0
    hatch: int = 0
    pattern: RGBBitmap | DIBLayout | None = None
    monochrome: bool = False
    realizable: bool = True


class TransferAction(Enum):
    NOOP = auto()
    PATTERN = auto()


@dataclass(frozen=True)
class SourceTransfer:
    bitmap: RGBBitmap | HalftoneReduction | HalftoneExpansion
    horizontal: BlitAxis | StretchAxis
    vertical: BlitAxis | StretchAxis
    operation: int
    pad_bounds: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class TextState:
    """Logical text setup retained until glyph rendering is implemented."""

    alignment: int = 0
    character_extra: int = 0
    justification: tuple[int, int] = (0, 0)
    mapper_flags: int = 0
    font: Font | None = None  # None denotes the device's unresolved default font.


@dataclass(frozen=True)
class SavedDC:
    """Saved drawing state; selected objects retain their identity.

    Mapping is copied at save time. The image and handle allocation table are
    not part of a snapshot, and palette mutations remain visible after restore.
    """

    mapping: Mapping
    pen: Pen
    brush: Brush
    position: tuple[int, int]
    clip: ClipRegion
    polygon_fill_mode: int
    rop2: int
    background_mode: int
    background_color: tuple[int, int, int] | PaletteIndex
    text_color: tuple[int, int, int] | PaletteIndex
    stretch_mode: int
    palette: LogicalPalette
    text_state: TextState


# MFCOMMENT, POSTSCRIPT_IGNORE, BEGIN_PATH, CLIP_TO_PATH, END_PATH.
# These are metadata or printer-driver operations, not bitmap GDI paths.
# This RGB memory device has no PostScript channel. Unknown escapes remain
# unsupported rather than being silently treated as harmless comments.
BITMAP_NOOP_ESCAPES = frozenset({0x000F, 0x0026, 0x1000, 0x1001, 0x1002})


class RasterContext(TraceContext):
    """Draw the currently supported GDI calls into an RGB Pillow image.

    Unsupported modes and primitives raise rather than silently draw an
    approximate image. Playback with ``strict=True`` exposes that boundary.
    """

    def __init__(
        self,
        width: int,
        height: int,
        *,
        background=(255, 255, 255),
        max_bitmap_pixels: int = DEFAULT_MAX_BITMAP_PIXELS,
        fonts: FontCollection | None = None,
    ):
        super().__init__()
        if width <= 0 or height <= 0:
            raise ValueError("Image dimensions must be positive")
        if max_bitmap_pixels < 0:
            raise ValueError("Bitmap pixel limit must be nonnegative")
        self.max_bitmap_pixels = max_bitmap_pixels
        self.fonts = fonts if fonts is not None else FontCollection()
        self.image = Image.new("RGB", (width, height), background)
        self._objects: dict[Handle, Pen | Brush | Font | RegionMask | LogicalPalette | None] = {}
        self._palette = LogicalPalette.default()
        self._pen = Pen((0, 0, 0), width=0)
        self._brush = Brush((255, 255, 255))
        self._position = (0, 0)
        self._polygon_fill_mode = 1
        self._rop2 = 13
        self._stretch_mode = 1
        self._background_mode = 2
        self._background_color = (255, 255, 255)
        self._text_color = (0, 0, 0)
        self._text_state = TextState()
        self.mapping = Mapping(window_extent=(width, height), viewport_extent=(width, height), surface_width=width)
        self._clip = ClipRegion()
        self._saved: list[SavedDC] = []

    def _point(self, x: int, y: int) -> tuple[int, int]:
        return self.mapping.device_point(x, y)

    @staticmethod
    def _accepts_dib(layout):
        # The native reference surface is a 32-bit RGB DIB. PAL_INDICES avoids
        # colour translation and requires matching source/device pixel depths.
        return layout.header_size != 12 and (layout.color_usage != 2 or layout.depth == 32)

    def is_null_object(self, handle: Handle) -> bool:
        return handle.owner is self and handle in self._objects and self._objects[handle] is None

    def _clip_mask(self, region):
        if region is not None and self.mapping.rtl:
            return region.transformed(lambda x, y: (self.image.width - x, y))
        return region

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
        if name == "escape":
            if a["escape_function"] not in BITMAP_NOOP_ESCAPES:
                raise UnsupportedOperation(f"escape {a['escape_function']:#06x}")
        elif name in ("text_out", "ext_text_out"):
            try:
                text_layout, text_rectangle = self._prepare_text(a)
            except UnsupportedOperation as error:
                raise UnsupportedOperation(f"{name}: {error}") from error
        elif name in ("create_palette", "set_palette_entries", "animate_palette"):
            a["palette"].to_bytes()
            if name == "create_palette" and a["palette"].start != 0x300:
                raise ValueError("New palettes require version 0x0300")
        elif name == "resize_palette":
            if not 0 <= a["count"] <= 65535:
                raise ValueError("Palette size outside WORD range")
        elif name == "set_layout":
            if a["layout"] & ~9:
                raise UnsupportedOperation(f"Layout {a['layout']}")
        elif name == "set_map_mode":
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
            transfer = self._prepare_transfer(name, a)
        elif name in ("bit_blt", "stretch_blt"):
            transfer = self._prepare_legacy_transfer(name, a)
        elif name == "set_background_mode":
            if a["mode"] not in (1, 2):
                raise UnsupportedOperation(f"Background mode {a['mode']}")
        elif name == "ext_flood_fill":
            if a["mode"] not in (0, 1):
                raise UnsupportedOperation(f"Flood fill mode {a['mode']}")
        elif name == "create_pen":
            if a["width"] < 0:
                raise UnsupportedOperation("Negative pen width")
        elif name == "create_brush":
            if a["style"] not in (0, 1, 2) or (a["style"] == 2 and a["hatch"] not in range(6)):
                raise UnsupportedOperation("Only solid, null and six hatch brushes are supported")
        elif name == "create_pattern_brush":
            layout = read_bitmap16(a["bitmap"], native_pattern=True, max_pixels=self.max_bitmap_pixels)
            # A DDB keeps its device format. Only monochrome, the default
            # indexed device palette, and matching RGB32 realize on this DC.
            pattern = None
            if layout.complete and layout.depth in (1, 8, 32):
                colors = DEFAULT_COLORS[:10] + ((0, 0, 0),) * 236 + DEFAULT_COLORS[10:]
                pattern = layout.decode(colors=colors if layout.depth == 8 else None)
        elif name == "create_dib_pattern_brush":
            layout = read_dib(
                a["bitmap"],
                color_usage=0 if a["style"] == 3 else a["color_usage"],
                max_pixels=self.max_bitmap_pixels,
            )
            if layout.color_usage == 1 and layout.complete:
                # Packed brush storage DWORD-aligns the WORD palette table.
                # The allocation's tail is zero-filled, unlike the separate
                # header/bits pointers used by transfer records.
                padding = -layout.offset % 4
                layout = replace(layout, offset=layout.offset + padding, data=layout.data + bytes(padding))
            pattern = (
                None
                if not self._accepts_dib(layout)
                or layout.compression in (1, 2)
                or (layout.header_size > 40 and layout.compression == 3)
                else layout.decode(palette=self._palette.colors())
            )
            if pattern is not None and layout.color_usage == 1 and layout.depth <= 8:
                # Validate the packed samples now, but retain their palette
                # references. Pattern colours are realized against the drawing
                # DC, including subsequent palette edits and selections.
                pattern = layout
            if a["style"] == 3 and pattern is not None:
                # The legacy record path realizes a monochrome DDB in a
                # compatible memory DC. Its bitmap creation rejects top-down
                # dimensions; failed selection preserves the previous brush.
                pattern = None if layout.top_down else pattern.monochrome()
        elif name == "set_dib_to_device":
            transfer = self._prepare_device_transfer(a)
        elif name == "create_font":
            a["font"].to_bytes()
        elif name == "select_object":
            if a["handle"] is not None and a["handle"].kind not in {"pen", "brush", "region", "font"}:
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
            "select_palette",
            "realize_palette",
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
            "set_text_alignment",
            "set_text_character_extra",
            "set_text_justification",
            "set_mapper_flags",
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
        if name in ("text_out", "ext_text_out"):
            self._draw_text(text_layout, text_rectangle, a.get("options", 0))
        elif name == "create_palette":
            self._objects[result] = LogicalPalette(a["palette"].entries) if a["palette"].entries else None
        elif name == "select_palette":
            if a["handle"] is not None and self._objects[a["handle"]] is not None:
                self._palette = self._objects[a["handle"]]
        elif name in ("set_palette_entries", "animate_palette"):
            self._palette.update(a["palette"].start, a["palette"].entries, animate=name == "animate_palette")
        elif name == "resize_palette":
            self._palette.resize(a["count"])
        elif name == "set_map_mode":
            self.mapping.set_mode(a["mode"])
        elif name == "set_layout":
            self.mapping.set_layout(a["layout"])
        elif name == "set_polygon_fill_mode":
            self._polygon_fill_mode = a["mode"]
        elif name == "set_rop2":
            self._rop2 = a["mode"]
        elif name == "set_stretch_mode":
            self._stretch_mode = a["mode"]
        elif name == "set_background_mode":
            self._background_mode = a["mode"]
        elif name == "set_background_color":
            self._background_color = logical_color(a["color"])
        elif name == "set_text_color":
            self._text_color = logical_color(a["color"])
        elif name == "set_text_alignment":
            self._text_state = replace(self._text_state, alignment=a["alignment"])
        elif name == "set_text_character_extra":
            self._text_state = replace(self._text_state, character_extra=a["extra"])
        elif name == "set_text_justification":
            self._text_state = replace(self._text_state, justification=(a["break_count"], a["break_extra"]))
        elif name == "set_mapper_flags":
            self._text_state = replace(self._text_state, mapper_flags=a["flags"])
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
            # CreatePenIndirect uses CreatePen, not ExtCreatePen: unrecognized
            # styles become PS_SOLID, including styles with join/cap bits.
            # Normalize the realized object only; preserve the requested call.
            style = a["style"] if a["style"] in range(7) else 0
            self._objects[result] = Pen(logical_color(a["color"]), a["width"], style)
        elif name == "create_brush":
            self._objects[result] = Brush(logical_color(a["color"]), a["style"], a["hatch"])
        elif name == "create_font":
            self._objects[result] = a["font"]
        elif name == "create_pattern_brush":
            self._objects[result] = (
                Brush((0, 0, 0), style=3, pattern=pattern, monochrome=layout.depth == 1, realizable=pattern is not None)
                if layout.complete
                else None
            )
        elif name == "create_dib_pattern_brush":
            self._objects[result] = (
                Brush((0, 0, 0), style=3, pattern=pattern, monochrome=a["style"] == 3) if pattern is not None else None
            )
        elif name == "create_region":
            self._objects[result] = region_mask
        elif name == "select_clip_region":
            self._clip = ClipRegion(
                mask=self._clip_mask(self._objects[a["region"]]) if a["region"] is not None else None
            )
        elif name == "select_object":
            obj = self._objects[a["handle"]] if a["handle"] is not None else None
            if isinstance(obj, Pen):
                self._pen = obj
            elif isinstance(obj, Font):
                self._text_state = replace(self._text_state, font=obj)
            elif isinstance(obj, RegionMask):
                self._clip = ClipRegion(mask=self._clip_mask(obj))
            elif obj is None:
                pass  # Selecting a null object fails without changing state.
            else:
                self._brush = obj
        elif name == "delete_object":
            if not self.is_null_object(a["handle"]):
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
            # PolyPolygon validates the entire contour list before painting.
            # Dropping short contours would incorrectly draw the valid ones.
            if name == "poly_polygon" and any(len(points) < 2 for points in polygons):
                return result
            paths = tuple(self._mapped_path(points) for points in polygons)
            self._paint_polygons(tuple(DevicePath.polyline(path, closed=True) for path in paths))
        elif name == "set_pixel":
            self._pixel(*self._point(a["x"], a["y"]), logical_color(a["color"]))
        elif name == "pat_blt":
            self._pat_blt(a["x"], a["y"], a["width"], a["height"], a["rop"])
        elif name in ("bit_blt", "stretch_blt", "dib_bit_blt", "set_dib_to_device", "dib_stretch_blt", "stretch_dib"):
            if isinstance(transfer, SourceTransfer):
                self._source_blt(
                    transfer.bitmap,
                    transfer.horizontal,
                    transfer.vertical,
                    transfer.operation,
                    pad_bounds=transfer.pad_bounds,
                )
            elif transfer is TransferAction.PATTERN:
                self._pat_blt(a["x"], a["y"], a["width"], a["height"], a["rop"])
        elif name in ("flood_fill", "ext_flood_fill"):
            self._flood_fill(
                self._point(a["x"], a["y"]), self._palette.colorref(logical_color(a["color"])), a.get("mode", 0)
            )
        elif name == "save_dc":
            self._saved.append(
                SavedDC(
                    mapping=replace(self.mapping),
                    pen=self._pen,
                    brush=self._brush,
                    position=self._position,
                    clip=self._clip,
                    polygon_fill_mode=self._polygon_fill_mode,
                    rop2=self._rop2,
                    background_mode=self._background_mode,
                    background_color=self._background_color,
                    text_color=self._text_color,
                    stretch_mode=self._stretch_mode,
                    palette=self._palette,
                    text_state=self._text_state,
                )
            )
        elif name == "restore_dc":
            self.mapping = snapshot.mapping
            self._pen = snapshot.pen
            self._brush = snapshot.brush
            self._position = snapshot.position
            self._clip = snapshot.clip
            self._polygon_fill_mode = snapshot.polygon_fill_mode
            self._rop2 = snapshot.rop2
            self._background_mode = snapshot.background_mode
            self._background_color = snapshot.background_color
            self._text_color = snapshot.text_color
            self._stretch_mode = snapshot.stretch_mode
            self._palette = snapshot.palette
            self._text_state = snapshot.text_state
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
                            *self.mapping.linear_scale,
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
            pen = self._realized_pen()
            # Native EBOX decrements RTL logical X edges before transforming.
            # Rectangle's wide-pen path enters EBOX after its own decrement.
            shift = int(self.mapping.rtl) * (1 + (name == "rectangle" and not pen.cosmetic))
            left, top = self._point(a["left"] - shift, a["top"])
            right, bottom = self._point(a["right"] - shift, a["bottom"])
            left, right = sorted((left, right))
            top, bottom = sorted((top, bottom))
            if right > left and bottom > top:
                drawing_bounds = None
                covered = False
                if self._pen.style == 6 and not pen.cosmetic:
                    dx, dy = (
                        floor(self._pen.width * abs(Fraction(v, w)) * 16 + 0.5)
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
                        # Preserve the native signed half-width rounding.
                        # Odd spans retain their corner geometry downstream;
                        # they must not be replaced by a symmetric radius.
                        drawing_bounds = (
                            left * 16 + (dx + 1) // 2,
                            top * 16 + (dy + 1) // 2,
                            right * 16 - dx // 2,
                            bottom * 16 - (dy + 1) // 2,
                        )
                rectangle = name == "rectangle"
                if name == "rectangle":
                    bounds = drawing_bounds or (left * 16, top * 16, (right - 1) * 16, (bottom - 1) * 16)
                    path = DevicePath.polyline(box_corners(bounds), closed=True)
                elif name == "ellipse":
                    path = DevicePath(
                        ellipse_cubics(
                            left,
                            top,
                            right,
                            bottom,
                            null_pen=self._pen.style == 5,
                            drawing_bounds=drawing_bounds,
                            clockwise=self.mapping.rtl,
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
                        clockwise=self.mapping.rtl,
                    )
                else:
                    sx, sy = (1 if value >= 0 else -1 for value in self.mapping.linear_scale)
                    start = sx * a["start_x"], sy * a["start_y"]
                    end = sx * a["end_x"], sy * a["end_y"]
                    x0, x1 = sorted((sx * (a["left"] - shift), sx * (a["right"] - shift)))
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
                        clockwise=self.mapping.rtl,
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
        if isinstance(result, Handle) and self.is_null_object(result):
            # A failed creation is a typed null value, not an allocated GDI
            # object. Intern it so WMF slot reuse cannot leak backend handles.
            del self._live[result.serial]
            del self._objects[result]
            result = Handle(0, result.kind, self)
            self._objects[result] = None
        return result

    def _prepare_device_transfer(self, args) -> SourceTransfer | TransferAction:
        """Realize a scan band without stretching its device-pixel geometry."""
        layout = read_dib(args["source"], color_usage=args["color_usage"], max_pixels=self.max_bitmap_pixels)
        # WMF stores WORDs here but playback sign-extends coordinates and
        # extents. Scan indexes/counts remain unsigned.
        x, y, width, height, source_x, source_y = (
            (args[key] + 32768) % 65536 - 32768 for key in ("x", "y", "width", "height", "src_x", "src_y")
        )
        start, count = args["start_scan"], args["scan_count"]
        # WMF requires a complete packed DIB even when only cLines rows
        # are consumed. Short buffers are rejected regardless of SizeImage.
        if (
            not self._accepts_dib(layout)
            or not layout.complete
            or width <= 0
            or height <= 0
            or not count
            or start >= layout.height
        ):
            return TransferAction.NOOP
        if layout.compression in (1, 2):
            start, count = 0, layout.height
        if not layout.top_down:
            count = min(count, layout.height - start)
        x, y = self._point(x, y)
        if self.mapping.rtl:
            # Device scans keep their order; only the destination
            # rectangle is reflected about the anchor pixel.
            x -= width - 1
        horizontal = BlitAxis(x, source_x, width)
        vertical = BlitAxis(y, start + count - source_y - height, height)
        if layout.compression in (1, 2):
            bitmap = self._decode_device_rle(layout, horizontal, vertical)
        else:
            bitmap = layout.decode(min(count, layout.height), preserve_gaps=True, palette=self._palette.colors())
        return SourceTransfer(bitmap, horizontal, vertical, 0xCC0020)

    def _prepare_legacy_transfer(self, name, a) -> SourceTransfer | TransferAction:
        if a["source"] is not None:
            layout = read_bitmap16(a["source"], max_pixels=self.max_bitmap_pixels)
            # PlayMetaFileRecord exits after successful bitmap selection,
            # before testing the ROP. Other depths fail selection into the
            # RGB32 memory DC; only source-independent operations can execute
            # without a source bitmap. See gdi-bitmap16.md and native controls.
            if layout.complete and layout.depth not in (1, 32) and pattern_rop2(a["rop"]) is not None:
                return TransferAction.PATTERN
            return TransferAction.NOOP
        if pattern_rop2(a["rop"]) is not None:
            return TransferAction.PATTERN
        # Without embedded bits Windows uses the destination DC as source.
        # Snapshot before painting so overlapping transfers read original data.
        bitmap = RGBBitmap(self.image.width, self.image.height, self.image.tobytes())
        if name == "bit_blt":
            # Equal transforms order both half-open rectangles, then use the
            # destination size and source's low corner. Fractional rounding
            # can give the source a different size; that does not stretch it.
            x, y = self.mapping.edge_point(a["x"], a["y"])
            right, bottom = self.mapping.edge_point(a["x"] + a["width"], a["y"] + a["height"])
            sx, sy = self.mapping.edge_point(
                a["src_x"] + (a["width"] if right < x else 0),
                a["src_y"] + (a["height"] if bottom < y else 0),
            )
            left, top = min(x, right), min(y, bottom)
            return SourceTransfer(
                bitmap,
                BlitAxis(left, sx, abs(right - x)),
                BlitAxis(top, sy, abs(bottom - y)),
                a["rop"],
            )
        sx, sy = self._point(a["src_x"], a["src_y"])
        sw, sh = a.get("src_width", a["width"]), a.get("src_height", a["height"])
        right, bottom = self._point(a["src_x"] + sw, a["src_y"] + sh)
        a = dict(a, src_x=sx, src_width=right - sx, src_height=bottom - sy)
        return self._prepare_bitmap_transfer(a, bitmap, sy, depth=32, halftone=self._stretch_mode == 4, source_dc=True)

    def _prepare_transfer(self, name, a) -> SourceTransfer | TransferAction:
        if pattern_rop2(a["rop"]) is not None:
            return TransferAction.PATTERN
        if a["source"] is None:
            return TransferAction.NOOP
        layout = read_dib(a["source"], color_usage=a.get("color_usage", 0), max_pixels=self.max_bitmap_pixels)
        if not self._accepts_dib(layout):
            return TransferAction.NOOP
        copy = (a["rop"] >> 16) & 255 == 0xCC
        # DIB[STRETCH]BITBLT realizes a canonical black/white table as a
        # monochrome bitmap. Its bits use the destination DC's text/background
        # colours; STRETCHDIB keeps an explicit RGB table instead.
        monochrome = name != "stretch_dib" and layout.depth == 1 and layout.colors == ((0, 0, 0), (255, 255, 255))
        if monochrome:
            layout = replace(
                layout, colors=tuple(self._palette.colorref(c) for c in (self._text_color, self._background_color))
            )
        sy = a["src_y"]
        # STRETCHDIB exposes DIB-origin coordinates; DIB[STRETCH]BITBLT
        # adapts the source to top-left. The native ternary path also retains
        # the top-down storage distinction documented in gdi-dib-transfers.md.
        if (name == "stretch_dib") != (layout.top_down and not copy):
            sy = layout.height - sy - a.get("src_height", a["height"])
        # A positive, unstretched SRCCOPY from the DIB origin can be sent
        # straight to device scans. Other blits first realize a source bitmap.
        # The distinction is observable for RLE run phase and unwritten gaps.
        direct = (
            copy
            and self._stretch_mode != 4
            and self.mapping.translation_only
            and a["src_x"] == 0
            and a["src_y"] == 0
            and a["width"] == a.get("src_width", a["width"])
            and a["height"] == a.get("src_height", a["height"])
            and a["width"] > 0
            and a["height"] > 0
        )
        if layout.compression in (1, 2) and direct:
            x, y = self._point(a["x"], a["y"])
            horizontal = BlitAxis.unscaled(x, a["width"], 0, a["width"], layout.width)
            vertical = BlitAxis.unscaled(y, a["height"], sy, a["height"], layout.height)
            bitmap = self._decode_device_rle(layout, horizontal, vertical)
            return SourceTransfer(bitmap, horizontal, vertical, a["rop"])
        bitmap = layout.decode(
            replicate_channels=not (self._stretch_mode == 4 and copy),
            palette=self._palette.colors(),
            # Ternary RLE blits realize a cleared RGB bitmap, not a cleared
            # indexed bitmap: unwritten source pixels are black, not index 0.
            gap_color=None if copy else (0, 0, 0),
        )
        return self._prepare_bitmap_transfer(
            a,
            bitmap,
            sy,
            depth=layout.depth,
            halftone=self._stretch_mode == 4,
            monochrome_bitblt=monochrome and name == "dib_bit_blt",
        )

    def _decode_device_rle(self, layout, horizontal, vertical):
        """Clip compressed runs at the transfer boundary, before RGB realization."""
        left = max(0, horizontal.destination)
        top = max(0, vertical.destination)
        right = min(self.image.width, horizontal.destination + horizontal.length)
        bottom = min(self.image.height, vertical.destination + vertical.length)
        clip = RegionMask()
        if left < right and top < bottom:
            clip = self._clip.within((left, top, right, bottom)).offset(
                horizontal.source - horizontal.destination, vertical.source - vertical.destination
            )
        return layout.decode(preserve_gaps=True, palette=self._palette.colors(), clip_spans=clip.spans)

    def _prepare_bitmap_transfer(self, a, bitmap, sy, *, depth, halftone, monochrome_bitblt=False, source_dc=False):
        x, y = self._point(a["x"], a["y"])
        right, bottom = self._point(a["x"] + a["width"], a["y"] + a["height"])
        sw, sh = a.get("src_width", a["width"]), a.get("src_height", a["height"])
        dw, dh = right - x, bottom - y
        if self.mapping.rtl and dw > 0 and not source_dc:
            # A second X reflection restores forward scan order. Its anchor
            # is then the exclusive RTL edge rather than the mirrored pixel;
            # negative device extents get this conversion in Blit/StretchAxis.
            # A source using the same DC already shares the RTL transform.
            x += 1
        if not all((sw, sh, dw, dh)):
            return TransferAction.NOOP
        scaled = abs(dw) != abs(sw) or abs(dh) != abs(sh)
        mirrored = (dw < 0) != (sw < 0) or (dh < 0) != (sh < 0)
        copy = (a["rop"] >> 16) & 255 == 0xCC
        halftone = halftone and copy and not (monochrome_bitblt and not scaled)
        if halftone:
            hx = StretchAxis.create(x, dw, a["src_x"], sw, bitmap.width)
            hy = StretchAxis.create(y, dh, sy, sh, bitmap.height)
            left, top = max(0, hx.source), max(0, hy.source)
            right, bottom = min(bitmap.width, hx.source + abs(sw)), min(bitmap.height, hy.source + abs(sh))
            if left >= right or top >= bottom:
                return TransferAction.NOOP
            # Classify the original source once: filtering introduces colours
            # which must not change CheckBMPNeedFixup's dispatch decision.
            content = classify_content(bitmap, left, top, right - left, bottom - top, depth=depth)
            if content.fixup and fixup_candidate(abs(sw), abs(sh), abs(dw), abs(dh)):
                bitmap = fixup_bitmap(bitmap, left, top, right, bottom)
        if scaled and halftone:
            filtered = halftone_bitmap(
                bitmap, hx.source, hy.source, abs(sw), abs(sh), abs(dw), abs(dh), content=content
            )
            if filtered is HalftoneMode.NOOP:
                return TransferAction.NOOP
            if filtered is not HalftoneMode.REPLICATE:
                if not filtered.valid:
                    return TransferAction.NOOP
                return SourceTransfer(
                    filtered,
                    BlitAxis(hx.destination, abs(dw) - 1 if hx.mirrored else 0, abs(dw), -1 if hx.mirrored else 1),
                    BlitAxis(hy.destination, abs(dh) - 1 if hy.mirrored else 0, abs(dh), -1 if hy.mirrored else 1),
                    a["rop"],
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
        return SourceTransfer(bitmap, horizontal, vertical, a["rop"], pad_bounds)

    def _source_blt(self, bitmap, horizontal, vertical, operation, *, pad_bounds=None):
        coverage = getattr(bitmap, "coverage", None)
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
                    if 0 <= sx < bitmap.width
                    and 0 <= sy < bitmap.height
                    and (coverage is None or coverage[sy * bitmap.width + sx])
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
                pattern = self._brush_color_at(x, y, self._brush, opaque=True) if needs_pattern else (0, 0, 0)
                if pattern is not None:
                    self.image.putpixel((x, y), rop3(operation, pattern, source, self.image.getpixel((x, y))))

    def _pat_blt(self, x, y, width, height, rop):
        operation = pattern_rop2(rop)
        if operation is None:
            return  # Native PatBlt rejects operations requiring a source.
        left, top = self.mapping.edge_point(x, y)
        right, bottom = self.mapping.edge_point(x + width, y + height)
        # PatBlt orders mapped rectangle edges (unlike mirrored source blits).
        left, right = sorted((left, right))
        top, bottom = sorted((top, bottom))
        for py in range(max(0, top), min(self.image.height, bottom)):
            for px in range(max(0, left), min(self.image.width, right)):
                # Pattern-independent functions do not need a brush, including
                # a null brush or transparent hatch gaps.
                paint = (
                    (0, 0, 0) if operation in (1, 6, 11, 16) else self._brush_color_at(px, py, self._brush, opaque=True)
                )
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
                paint = self._brush_color_at(x, y, self._brush)
                if paint is not None:
                    self._pixel(x, y, paint)

    def _prepare_text(self, args):
        options = args.get("options", 0)
        if options & ~6:
            raise UnsupportedOperation("Text output options")
        rectangle = args.get("rectangle")
        if options and rectangle is None:
            raise ValueError("Text output options require a rectangle")
        sx, sy = self.mapping.linear_scale
        if self.mapping.rtl:
            raise UnsupportedOperation("Reflected text mapping")
        if rectangle is not None:
            rectangle = (*self._point(*rectangle[:2]), *self._point(*rectangle[2:]))
            left, top, right, bottom = rectangle
            rectangle = min(left, right), min(top, bottom), max(left, right), max(top, bottom)
        if not args["text"]:
            return TextLayout(), rectangle
        request = self._text_state.font
        face = self.fonts.resolve(request)
        if sx * sy < 0:
            request = replace(request, escapement=-request.escapement)
        if request.quality not in (0, 3):
            raise UnsupportedOperation("Unsupported font quality")
        if self._text_state.mapper_flags:
            raise UnsupportedOperation("Text mapper flags")
        origin = self._position if self._text_state.alignment & 1 else (args["x"], args["y"])
        origin = self._point(*origin)
        layout = layout_text(
            self.fonts.realize(request, face, (abs(sx), abs(sy))),
            args["text"],
            *origin,
            self._text_state.alignment,
            args.get("advances", ()),
            opaque=self._background_mode == 2,
            max_pixels=self.max_bitmap_pixels,
            scale=abs(sx),
            extra=self._text_state.character_extra,
            justification=self._text_state.justification,
            characters=self.fonts.decode(request, face, args["text"]),
            escapement=request.escapement,
        )
        if layout.position is not None:
            logical_origin = self._position
            device_position = []
            for axis, scale in enumerate((sx, sy)):
                coordinate = (
                    logical_origin[axis] - self.mapping.window_origin[axis]
                ) * scale + self.mapping.viewport_origin[axis]
                delta = layout.position[axis] - origin[axis]
                device_position.append(
                    ((coordinate + delta) // 1 - self.mapping.viewport_origin[axis]) / scale
                    + self.mapping.window_origin[axis]
                )
            layout = replace(
                layout,
                position=tuple(device_position),
            )
        return layout, rectangle

    def _draw_text(self, layout, rectangle, options):
        def paint_contour(contour, color):
            polygon = [(x * 16, y * 16) for x, y in contour]
            for x, y in self._contour_pixels((polygon,)):
                if not options & 4 or rectangle[0] <= x < rectangle[2] and rectangle[1] <= y < rectangle[3]:
                    self._pixel(x, y, color, operation=13)

        def fill(bounds):
            if bounds is not None:
                left, top, right, bottom = bounds
                for y in range(max(0, top), min(self.image.height, bottom)):
                    for x in range(max(0, left), min(self.image.width, right)):
                        self._pixel(x, y, self._background_color, operation=13)

        if options & 2:
            fill(rectangle)
        if layout.background is not None:
            paint_contour(layout.background, self._background_color)
        for left, top, glyph in layout.glyphs:
            width, height = glyph.size
            for y in range(max(0, top), min(self.image.height, top + height)):
                for x in range(max(0, left), min(self.image.width, left + width)):
                    if options & 4 and not (rectangle[0] <= x < rectangle[2] and rectangle[1] <= y < rectangle[3]):
                        continue
                    index = ((y - top) * width + x - left) * glyph.channels
                    if glyph.channels == 1:
                        if glyph.pixels[index]:
                            self._pixel(x, y, self._text_color, operation=13)
                    else:
                        coverage = glyph.pixels[index : index + 3]
                        foreground = self._palette.colorref(self._text_color)
                        background = self.image.getpixel((x, y))
                        color = tuple(
                            (f * a + b * (255 - a) + 127) // 255
                            for f, b, a in zip(foreground, background, coverage, strict=True)
                        )
                        if self._clip.contains(x, y):
                            self.image.putpixel((x, y), color)
        if layout.position is not None:
            self._position = layout.position

        for contour in layout.decorations:
            paint_contour(contour, self._text_color)

    def _pixel(self, x: int, y: int, color: tuple[int, int, int], *, operation: int | None = None) -> None:
        if 0 <= x < self.image.width and 0 <= y < self.image.height and self._clip.contains(x, y):
            color = self._palette.colorref(color)
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
        return realize_pen(self._pen.width, *self.mapping.linear_scale)

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
        brush = self._brush if brush is None else brush
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
        self, x: int, y: int, brush: Brush | None, *, opaque: bool = False
    ) -> tuple[int, int, int] | None:
        if brush is None:
            return None
        if brush.style == 0:
            return self._palette.colorref(brush.color)
        if brush.style == 1 or not brush.realizable:
            return None
        if brush.pattern is not None:
            px, py = x % brush.pattern.width, y % brush.pattern.height
            if isinstance(brush.pattern, DIBLayout):
                color = self._palette.color(brush.pattern.color(brush.pattern.index(px, py)))
            else:
                color = brush.pattern.pixel(px, py)
            if brush.monochrome:
                return self._palette.colorref(self._background_color if color == (255, 255, 255) else self._text_color)
            return color
        # The six GDI hatches tile in device space. These phase offsets are
        # shared by all shapes, mapping modes and brush selections.
        horizontal = y % 8 == 3
        vertical = x % 8 == 4
        forward = (x - y) % 8 == 0
        backward = (x + y) % 8 == 7
        mark = (horizontal, vertical, forward, backward, horizontal or vertical, forward or backward)[brush.hatch]
        if mark:
            return self._palette.colorref(brush.color)
        return self._palette.colorref(self._background_color) if opaque or self._background_mode == 2 else None
