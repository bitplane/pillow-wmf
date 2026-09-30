"""GDI rasterization into a Pillow RGB image."""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
from math import floor

from PIL import Image

from .binary import FormatError, ResourceLimitError
from .bitmap import DEFAULT_MAX_BITMAP_PIXELS, DIBLayout, RGBBitmap, read_dib
from .bitmap16 import Bitmap16Layout, read_bitmap16
from .clip import ClipRegion, RegionMask
from .constants import (
    ALTERNATE,
    BLACKONWHITE,
    BS_HATCHED,
    BS_NULL,
    BS_PATTERN,
    BS_SOLID,
    COLORONCOLOR,
    ETO_CLIPPED,
    ETO_GLYPH_INDEX,
    ETO_NUMERICSLATIN,
    ETO_NUMERICSLOCAL,
    ETO_OPAQUE,
    ETO_PDY,
    ETO_RTLREADING,
    FLOODFILLBORDER,
    FLOODFILLSURFACE,
    HALFTONE,
    MM_ANISOTROPIC,
    MM_TEXT,
    PS_INSIDEFRAME,
    PS_NULL,
    PS_SOLID,
    R2_BLACK,
    R2_NOP,
    R2_NOT,
    R2_WHITE,
    TA_UPDATECP,
    TRANSPARENT,
    WHITEONBLACK,
    WINDING,
)
from .ellipse import arc_figure, box_corners, ellipse_cubics, round_rect_figure
from .gdi import Call, Handle, InvalidOperation, UnsupportedOperation
from .geometry import DevicePath, Polygon
from .mapping import Mapping
from .objects import FontRequest, GlyphIndices
from .palette import DEFAULT_COLORS, LogicalPalette, PaletteIndex
from .raster_paint import RasterPainter
from .raster_state import Brush as Brush
from .raster_state import DrawingState
from .raster_state import Pen as Pen
from .raster_state import SavedDC as SavedDC
from .raster_state import TextState as TextState
from .stroke import frame_footprint
from .text import FontCollection
from .text_layout import TextLayout, layout_text
from .trace import TraceContext
from .transfer import SourceTransfer as SourceTransfer
from .transfer import TransferAction as TransferAction
from .transfer import TransferPreparation, accepts_dib


def rgb(colorref: int) -> tuple[int, int, int]:
    return colorref & 255, (colorref >> 8) & 255, (colorref >> 16) & 255


def logical_color(colorref):
    # PALETTEINDEX is a flag, not an exclusive high-byte value. Other high
    # bits do not cancel it, including sign-extended colours in legacy files.
    return PaletteIndex(colorref & 65535) if colorref & 0x01000000 else rgb(colorref)


@dataclass(frozen=True)
class PreparedEffect:
    """Decoded inputs shared by validation and application, never DC state."""

    text_layout: TextLayout | None = None
    text_rectangle: tuple[int, int, int, int] | None = None
    transfer: SourceTransfer | TransferAction | None = None
    pattern: RGBBitmap | DIBLayout | None = None
    region_mask: RegionMask | None = None
    layout: Bitmap16Layout | DIBLayout | None = None


# MS-WMF's defined escape records are printer operations or embedded metadata.
# They do not affect the native RGB memory device. Keep the verified set
# explicit: other escape numbers, including callbacks and XPS, are unsupported.
BITMAP_NOOP_ESCAPES = frozenset(
    {
        0x0001,  # NEWFRAME
        0x0002,  # ABORTDOC
        0x0003,  # NEXTBAND
        0x0004,  # SETCOLORTABLE
        0x0005,  # GETCOLORTABLE
        0x0008,  # QUERYESCSUPPORT
        0x000A,  # STARTDOC
        0x000B,  # ENDDOC
        0x000C,  # GETPHYSPAGESIZE
        0x000D,  # GETPRINTINGOFFSET
        0x000E,  # GETSCALINGFACTOR
        0x000F,  # META_ESCAPE_ENHANCED_METAFILE
        0x0011,  # SETCOPYCOUNT
        0x0013,  # PASSTHROUGH
        0x0015,  # SETLINECAP
        0x0016,  # SETLINEJOIN
        0x0017,  # SETMITERLIMIT
        0x0019,  # DRAWPATTERNRECT
        0x0021,  # EPSPRINTING
        0x0025,  # POSTSCRIPT_DATA
        0x0026,  # POSTSCRIPT_IGNORE
        0x002A,  # GETDEVICEUNITS
        0x0100,  # GETEXTENDEDTEXTMETRICS
        0x0102,  # GETPAIRKERNTABLE
        0x0200,  # EXTTEXTOUT (escape, not META_EXTTEXTOUT)
        0x0201,  # GETFACENAME
        0x0202,  # DOWNLOADFACE
        0x0801,  # METAFILE_DRIVER
        0x0C01,  # QUERYDIBSUPPORT
        0x1000,  # BEGIN_PATH
        0x1001,  # CLIP_TO_PATH
        0x1002,  # END_PATH
        0x100E,  # OPENCHANNEL
        0x100F,  # DOWNLOADHEADER
        0x1010,  # CLOSECHANNEL
        0x1013,  # POSTSCRIPT_PASSTHROUGH
        0x1014,  # ENCAPSULATED_POSTSCRIPT
        0x1015,  # POSTSCRIPT_IDENTIFY
        0x1016,  # POSTSCRIPT_INJECTION
        0x1017,  # CHECKJPEGFORMAT
        0x1018,  # CHECKPNGFORMAT
        0x1019,  # GET_PS_FEATURESETTING
        0x11D8,  # SPCLPASSTHROUGH2
    }
)


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
        self._objects: dict[Handle, Pen | Brush | FontRequest | RegionMask | LogicalPalette | None] = {}
        self._state = DrawingState(
            Mapping(window_extent=(width, height), viewport_extent=(width, height), surface_width=width)
        )
        self._saved: list[DrawingState] = []

    @property
    def mapping(self):
        return self._state.mapping

    @mapping.setter
    def mapping(self, value):
        self._state.mapping = value

    def _point(self, x: int, y: int) -> tuple[int, int]:
        return self.mapping.device_point(x, y)

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

    def _prepare_effect(self, call):
        """Validate and decode inputs before recording or changing DC state."""
        name = call.name
        a = call.kwargs
        text_layout = text_rectangle = transfer = pattern = region_mask = layout = None
        if name == "escape":
            if a["escape_function"] not in BITMAP_NOOP_ESCAPES:
                raise UnsupportedOperation(f"escape {a['escape_function']:#06x}")
        elif name in ("text_out", "ext_text_out"):
            try:
                text_layout, text_rectangle = self._prepare_text(a)
            except UnsupportedOperation as error:
                raise UnsupportedOperation(f"{name}: {error}") from error
        elif name == "resize_palette":
            if not 0 <= a["count"] <= 65535:
                raise ValueError("Palette size outside WORD range")
        elif name == "set_layout":
            if a["layout"] & ~9:
                raise UnsupportedOperation(f"Layout {a['layout']}")
        elif name == "set_map_mode":
            if a["mode"] not in range(MM_TEXT, MM_ANISOTROPIC + 1):
                raise UnsupportedOperation(f"Map mode {a['mode']}")
        elif name == "set_polygon_fill_mode":
            if a["mode"] not in (ALTERNATE, WINDING):
                raise UnsupportedOperation(f"Polygon fill mode {a['mode']}")
        elif name == "set_rop2":
            if a["mode"] not in range(R2_BLACK, R2_WHITE + 1):
                raise UnsupportedOperation(f"ROP2 mode {a['mode']}")
        elif name == "set_stretch_mode":
            if a["mode"] not in (BLACKONWHITE, WHITEONBLACK, COLORONCOLOR, HALFTONE):
                raise UnsupportedOperation(f"Stretch mode {a['mode']}")
        elif name in ("dib_bit_blt", "dib_stretch_blt", "stretch_dib"):
            transfer = self._prepare_transfer(name, a)
        elif name in ("bit_blt", "stretch_blt"):
            transfer = self._prepare_legacy_transfer(name, a)
        elif name == "ext_flood_fill":
            if a["mode"] not in (FLOODFILLBORDER, FLOODFILLSURFACE):
                raise UnsupportedOperation(f"Flood fill mode {a['mode']}")
        elif name == "create_brush":
            if a["style"] not in (BS_SOLID, BS_NULL, BS_HATCHED) or (
                a["style"] == BS_HATCHED and a["hatch"] not in range(6)
            ):
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
                if not accepts_dib(layout)
                or layout.compression in (1, 2)
                or (layout.header_size > 40 and layout.compression == 3)
                else layout.decode(palette=self._state.palette.colors())
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
        elif name == "select_object":
            if a["handle"] is not None and a["handle"].kind not in {"pen", "brush", "region", "font"}:
                raise UnsupportedOperation(f"Selecting {a['handle'].kind}")
        elif name == "create_region":
            region_mask = RegionMask.from_rectangles(a["region"].rectangles) if a["region"] is not None else None
        return PreparedEffect(text_layout, text_rectangle, transfer, pattern, region_mask, layout)

    def prepare(self, call: Call):
        token = super().prepare(call)
        call = token.call
        handler = getattr(self, f"_apply_{call.name}", None)
        if handler is None:
            raise UnsupportedOperation(call.name)
        try:
            prepared = self._prepare_effect(call)
        except ResourceLimitError:
            raise
        except FormatError as error:
            raise UnsupportedOperation(f"{call.name}: malformed input: {error}") from error
        null_object = False
        if call.name == "create_region":
            null_object = prepared.region_mask is None
        elif call.name == "create_palette":
            palette = call.kwargs["palette"]
            null_object = palette is None or not palette.entries
        elif call.name == "create_pattern_brush":
            null_object = not prepared.layout.complete
        elif call.name == "create_dib_pattern_brush":
            null_object = prepared.pattern is None
        return replace(token, payload=(handler, prepared), null_object=null_object)

    def _execute(self, token):
        call = token.call
        handler, prepared = token.payload
        result = self._result(call)
        # Input rejection belongs in prepare; execution failures are fatal.
        handler(call, prepared, result)
        self._commit(call)
        if isinstance(result, Handle) and self.is_null_object(result):
            # Intern failed creations so file-slot reuse cannot leak handles.
            del self._live[result.serial]
            del self._objects[result]
            result = Handle(0, result.kind, self)
            self._objects[result] = None
        return result

    def _apply_escape(self, call, prepared, result):
        pass  # Accepted printer metadata has no effect on a bitmap DC.

    _apply_realize_palette = _apply_escape

    def _apply_text_out(self, call, prepared, result):
        a = call.kwargs
        self._draw_text(prepared.text_layout, prepared.text_rectangle, a.get("options", 0))

    _apply_ext_text_out = _apply_text_out

    def _apply_create_palette(self, call, prepared, result):
        a = call.kwargs
        palette = a["palette"]
        self._objects[result] = LogicalPalette(palette.entries) if palette is not None and palette.entries else None

    def _apply_select_palette(self, call, prepared, result):
        a = call.kwargs
        if a["handle"] is not None and self._objects[a["handle"]] is not None:
            self._state.palette = self._objects[a["handle"]]

    def _apply_set_palette_entries(self, call, prepared, result):
        name = call.name
        a = call.kwargs
        self._state.palette.update(a["palette"].start, a["palette"].entries, animate=name == "animate_palette")

    _apply_animate_palette = _apply_set_palette_entries

    def _apply_resize_palette(self, call, prepared, result):
        a = call.kwargs
        self._state.palette.resize(a["count"])

    def _apply_set_map_mode(self, call, prepared, result):
        a = call.kwargs
        self.mapping.set_mode(a["mode"])

    def _apply_set_layout(self, call, prepared, result):
        a = call.kwargs
        self.mapping.set_layout(a["layout"])

    def _apply_set_polygon_fill_mode(self, call, prepared, result):
        a = call.kwargs
        self._state.polygon_fill_mode = a["mode"]

    def _apply_set_rop2(self, call, prepared, result):
        a = call.kwargs
        self._state.rop2 = a["mode"]

    def _apply_set_stretch_mode(self, call, prepared, result):
        a = call.kwargs
        self._state.stretch_mode = a["mode"]

    def _apply_set_background_mode(self, call, prepared, result):
        a = call.kwargs
        self._state.background_mode = a["mode"]

    def _apply_set_background_color(self, call, prepared, result):
        a = call.kwargs
        self._state.background_color = logical_color(a["color"])

    def _apply_set_text_color(self, call, prepared, result):
        a = call.kwargs
        self._state.text_color = logical_color(a["color"])

    def _apply_set_text_alignment(self, call, prepared, result):
        a = call.kwargs
        self._state.text_state = replace(self._state.text_state, alignment=a["alignment"])

    def _apply_set_text_character_extra(self, call, prepared, result):
        a = call.kwargs
        self._state.text_state = replace(self._state.text_state, character_extra=a["extra"])

    def _apply_set_text_justification(self, call, prepared, result):
        a = call.kwargs
        self._state.text_state = replace(self._state.text_state, justification=(a["break_count"], a["break_extra"]))

    def _apply_set_mapper_flags(self, call, prepared, result):
        a = call.kwargs
        self._state.text_state = replace(self._state.text_state, mapper_flags=a["flags"])

    def _apply_set_window_origin(self, call, prepared, result):
        a = call.kwargs
        self.mapping.window_origin = a["x"], a["y"]

    def _apply_set_viewport_origin(self, call, prepared, result):
        a = call.kwargs
        self.mapping.viewport_origin = a["x"], a["y"]

    def _apply_set_window_extent(self, call, prepared, result):
        a = call.kwargs
        self.mapping.set_extent(window=True, x=a["x"], y=a["y"])

    def _apply_set_viewport_extent(self, call, prepared, result):
        a = call.kwargs
        self.mapping.set_extent(window=False, x=a["x"], y=a["y"])

    def _apply_offset_window_origin(self, call, prepared, result):
        a = call.kwargs
        x, y = self.mapping.window_origin
        self.mapping.window_origin = x + a["x"], y + a["y"]

    def _apply_offset_viewport_origin(self, call, prepared, result):
        a = call.kwargs
        x, y = self.mapping.viewport_origin
        self.mapping.viewport_origin = x + a["x"], y + a["y"]

    def _apply_scale_window_extent(self, call, prepared, result):
        name = call.name
        a = call.kwargs
        self.mapping.scale_extent(
            window=name == "scale_window_extent",
            xn=a["x_numerator"],
            xd=a["x_denominator"],
            yn=a["y_numerator"],
            yd=a["y_denominator"],
        )

    _apply_scale_viewport_extent = _apply_scale_window_extent

    def _apply_create_pen(self, call, prepared, result):
        a = call.kwargs
        # CreatePenIndirect uses CreatePen, not ExtCreatePen: unrecognized
        # styles become PS_SOLID, including styles with join/cap bits.
        # Normalize the realized object only; preserve the requested call.
        style = a["style"] if a["style"] in range(PS_SOLID, PS_INSIDEFRAME + 1) else PS_SOLID
        self._objects[result] = Pen(logical_color(a["color"]), abs(a["width"]), style)

    def _apply_create_brush(self, call, prepared, result):
        a = call.kwargs
        self._objects[result] = Brush(logical_color(a["color"]), a["style"], a["hatch"])

    def _apply_create_font(self, call, prepared, result):
        a = call.kwargs
        self._objects[result] = a["font"]

    def _apply_create_pattern_brush(self, call, prepared, result):
        self._objects[result] = (
            Brush(
                (0, 0, 0),
                style=BS_PATTERN,
                pattern=prepared.pattern,
                monochrome=prepared.layout.depth == 1,
                realizable=prepared.pattern is not None,
            )
            if prepared.layout.complete
            else None
        )

    def _apply_create_dib_pattern_brush(self, call, prepared, result):
        a = call.kwargs
        self._objects[result] = (
            Brush((0, 0, 0), style=BS_PATTERN, pattern=prepared.pattern, monochrome=a["style"] == BS_PATTERN)
            if prepared.pattern is not None
            else None
        )

    def _apply_create_region(self, call, prepared, result):
        self._objects[result] = prepared.region_mask

    def _apply_select_clip_region(self, call, prepared, result):
        a = call.kwargs
        self._state.clip = ClipRegion(
            mask=self._clip_mask(self._objects[a["region"]]) if a["region"] is not None else None
        )

    def _apply_select_object(self, call, prepared, result):
        a = call.kwargs
        obj = self._objects[a["handle"]] if a["handle"] is not None else None
        if isinstance(obj, Pen):
            self._state.pen = obj
        elif isinstance(obj, FontRequest):
            self._state.text_state = replace(self._state.text_state, font=obj)
        elif isinstance(obj, RegionMask):
            self._state.clip = ClipRegion(mask=self._clip_mask(obj))
        elif obj is None:
            pass  # Selecting a null object fails without changing state.
        else:
            self._state.brush = obj

    def _apply_delete_object(self, call, prepared, result):
        a = call.kwargs
        if not self.is_null_object(a["handle"]):
            del self._objects[a["handle"]]

    def _apply_move_to(self, call, prepared, result):
        a = call.kwargs
        self._state.position = a["x"], a["y"]

    def _apply_line_to(self, call, prepared, result):
        a = call.kwargs
        self._line(self._point(*self._state.position), self._point(a["x"], a["y"]))
        self._state.position = a["x"], a["y"]

    def _apply_polyline(self, call, prepared, result):
        a = call.kwargs
        self._stroke_path(DevicePath.polyline(self._mapped_path(a["points"])))

    def _apply_polygon(self, call, prepared, result):
        name = call.name
        a = call.kwargs
        polygons = (a["points"],) if name == "polygon" else a["polygons"]
        # Polygon and PolyPolygon reject contours with fewer than two points.
        # PolyPolygon validates the entire contour list before painting.
        # Dropping short contours would incorrectly draw the valid ones.
        if any(len(points) < 2 for points in polygons):
            return
        paths = tuple(self._mapped_path(points) for points in polygons)
        self._paint_polygons(tuple(DevicePath.polyline(path, closed=True) for path in paths))

    _apply_poly_polygon = _apply_polygon

    def _apply_set_pixel(self, call, prepared, result):
        a = call.kwargs
        self._pixel(*self._point(a["x"], a["y"]), logical_color(a["color"]))

    def _apply_pat_blt(self, call, prepared, result):
        a = call.kwargs
        self._pat_blt(a["x"], a["y"], a["width"], a["height"], a["rop"])

    def _apply_bit_blt(self, call, prepared, result):
        a = call.kwargs
        if isinstance(prepared.transfer, SourceTransfer):
            self._source_blt(
                prepared.transfer.bitmap,
                prepared.transfer.horizontal,
                prepared.transfer.vertical,
                prepared.transfer.operation,
                pad_bounds=prepared.transfer.pad_bounds,
            )
        elif prepared.transfer is TransferAction.PATTERN:
            self._pat_blt(a["x"], a["y"], a["width"], a["height"], a["rop"])

    _apply_stretch_blt = _apply_bit_blt
    _apply_dib_bit_blt = _apply_bit_blt
    _apply_set_dib_to_device = _apply_bit_blt
    _apply_dib_stretch_blt = _apply_bit_blt
    _apply_stretch_dib = _apply_bit_blt

    def _apply_flood_fill(self, call, prepared, result):
        a = call.kwargs
        self._flood_fill(
            self._point(a["x"], a["y"]), self._state.palette.colorref(logical_color(a["color"])), a.get("mode", 0)
        )

    _apply_ext_flood_fill = _apply_flood_fill

    def _apply_save_dc(self, call, prepared, result):
        self._saved.append(self._state.snapshot())

    def _apply_restore_dc(self, call, prepared, result):
        level = call.kwargs["saved_dc"]
        target = level if level > 0 else len(self._saved) + level + 1
        self._state = self._saved[target - 1]
        del self._saved[target - 1 :]

    def _apply_intersect_clip_rect(self, call, prepared, result):
        name = call.name
        a = call.kwargs
        left, top = self.mapping.clip_point(a["left"], a["top"])
        right, bottom = self.mapping.clip_point(a["right"], a["bottom"])
        rectangle = (min(left, right), min(top, bottom), max(left, right), max(top, bottom))
        if name == "intersect_clip_rect":
            self._state.clip = self._state.clip.intersect(rectangle)
        else:
            self._state.clip = self._state.clip.exclude(rectangle)

    _apply_exclude_clip_rect = _apply_intersect_clip_rect

    def _apply_offset_clip_region(self, call, prepared, result):
        a = call.kwargs
        dx, dy = self.mapping.clip_displacement(a["x"], a["y"])
        self._state.clip = self._state.clip.offset(dx, dy)

    def _apply_fill_region(self, call, prepared, result):
        name = call.name
        a = call.kwargs
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
            brush = self._objects[a["brush"]] if "brush" in a else self._state.brush
            for left, top, right, bottom in region.rectangles():
                for y in range(max(0, top), min(self.image.height, bottom)):
                    for x in range(max(0, left), min(self.image.width, right)):
                        color = (0, 0, 0) if name == "invert_region" else self._brush_color_at(x, y, brush)
                        if color is not None:
                            self._pixel(x, y, color, operation=R2_NOT if name == "invert_region" else None)

    _apply_paint_region = _apply_fill_region
    _apply_invert_region = _apply_fill_region
    _apply_frame_region = _apply_fill_region

    def _apply_rectangle(self, call, prepared, result):
        name = call.name
        a = call.kwargs
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
            if self._state.pen.style == PS_INSIDEFRAME and not pen.cosmetic:
                dx, dy = (
                    floor(self._state.pen.width * abs(Fraction(v, w)) * 16 + 0.5)
                    for v, w in zip(self.mapping.viewport_extent, self.mapping.window_extent, strict=False)
                )
                # Equality retains a degenerate centreline and widens it
                # normally. Only a negative interior triggers GDI's
                # pen-colour fill (or rejection for arc-family calls).
                covered = self._state.pen.width > min(abs(a["right"] - a["left"]), abs(a["bottom"] - a["top"]))
                if covered:
                    if name in {"arc", "chord", "pie"}:
                        return
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
                        null_pen=self._state.pen.style == PS_NULL,
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
                    null_pen=self._state.pen.style == PS_NULL,
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
                    null_pen=self._state.pen.style == PS_NULL,
                    drawing_bounds=drawing_bounds,
                    radial_bounds=(x0, y0, x1, y1),
                    clockwise=self.mapping.rtl,
                )
            if covered:
                for x, y in self._contour_pixels((path.vertices,)):
                    self._pixel(x, y, self._state.pen.color)
            elif name == "arc":
                self._stroke_path(path)
            else:
                brush = self._state.brush
                # Rectangle's block-fill realization simplifies ROPs
                # independent of the pattern before applying hatch
                # transparency. Region/path fills retain the hatch mask.
                if rectangle and brush.style == BS_HATCHED and self._state.rop2 in (R2_BLACK, R2_NOT, R2_NOP, R2_WHITE):
                    brush = replace(brush, style=0)
                self._paint_polygons((path,), miter=rectangle, reserve_outline=rectangle, brush=brush)

    _apply_ellipse = _apply_rectangle
    _apply_arc = _apply_rectangle
    _apply_chord = _apply_rectangle
    _apply_pie = _apply_rectangle
    _apply_round_rect = _apply_rectangle

    def _transfer_preparation(self):
        return TransferPreparation(
            image=self.image,
            mapping=self.mapping,
            palette=self._state.palette,
            clip=self._state.clip,
            stretch_mode=self._state.stretch_mode,
            text_color=self._state.text_color,
            background_color=self._state.background_color,
            max_bitmap_pixels=self.max_bitmap_pixels,
        )

    def _prepare_device_transfer(self, args):
        return self._transfer_preparation().prepare_device(args)

    def _prepare_legacy_transfer(self, name, args):
        return self._transfer_preparation().prepare_legacy(name, args)

    def _prepare_transfer(self, name, args):
        return self._transfer_preparation().prepare_dib(name, args)

    def _painter(self):
        return RasterPainter(self.image, self._state)

    def _source_blt(self, bitmap, horizontal, vertical, operation, *, pad_bounds=None):
        self._painter().source_blt(bitmap, horizontal, vertical, operation, pad_bounds=pad_bounds)

    def _pat_blt(self, x, y, width, height, rop):
        self._painter().pat_blt(x, y, width, height, rop)

    def _flood_fill(self, seed, color, mode):
        self._painter().flood_fill(seed, color, mode)

    def _prepare_text(self, args):
        options = args.get("options", 0)
        # Reading order and numeral substitution do not alter our supported
        # left-to-right code pages. Arabic/Hebrew remain explicit boundaries.
        if options & ~(
            ETO_OPAQUE
            | ETO_CLIPPED
            | ETO_RTLREADING
            | ETO_NUMERICSLOCAL
            | ETO_NUMERICSLATIN
            | ETO_GLYPH_INDEX
            | ETO_PDY
        ):
            raise UnsupportedOperation("Text output options")
        rectangle = args.get("rectangle")
        if options & (ETO_OPAQUE | ETO_CLIPPED) and rectangle is None:
            raise InvalidOperation("Text output options require a rectangle")
        sx, sy = self.mapping.linear_scale
        if rectangle is not None:
            rectangle = (*self._point(*rectangle[:2]), *self._point(*rectangle[2:]))
            left, top, right, bottom = rectangle
            rectangle = min(left, right), min(top, bottom), max(left, right), max(top, bottom)
            if self.mapping.rtl:
                rectangle = rectangle[0] + 1, rectangle[1], rectangle[2] + 1, rectangle[3]
        if not args["text"]:
            return TextLayout(), rectangle
        request = self._state.text_state.font or self.fonts.default_font
        face = self.fonts.resolve(request)
        if sx * sy < 0:
            request = replace(request, escapement=-request.escapement)
        # Mapper flags constrain physical-font selection, not drawing with an
        # already explicitly supplied TrueType face. Retain them in DC state.
        origin = self._state.position if self._state.text_state.alignment & TA_UPDATECP else (args["x"], args["y"])
        precise_origin = tuple(Fraction(value, 16) for value in self.mapping.fixed_point(*origin))
        origin = self._point(*origin)
        alignment = self._state.text_state.alignment
        # RTL layout swaps reference edges, not glyph masks or byte order.
        if self.mapping.rtl and alignment & 6 != 6:
            alignment ^= 2
        text = args["text"]
        glyph_indices = text.indices if isinstance(text, GlyphIndices) else None
        data = text.data if glyph_indices is None else b""
        advances = args.get("advances", ())
        vertical_advances = ()
        if options & ETO_PDY and not advances:
            # Paired displacement output requires explicit advances.
            return TextLayout(), None
        if options & ETO_PDY and advances:
            vertical_advances = advances[1::2]
            advances = advances[::2]
        decoded = self.fonts.decode_run(request, face, data) if glyph_indices is None else None
        characters = decoded.text if decoded is not None else None
        layout = layout_text(
            self.fonts.layout_font(request, face, (abs(sx), abs(sy)), characters=characters),
            data,
            *origin,
            alignment,
            advances,
            opaque=self._state.background_mode != TRANSPARENT,
            max_pixels=self.max_bitmap_pixels,
            scale=abs(sx),
            extra=self._state.text_state.character_extra,
            justification=self._state.text_state.justification,
            characters=characters,
            byte_lengths=decoded.byte_lengths if decoded is not None else (),
            byte_indexed_advances=decoded.byte_indexed_advances if decoded is not None else True,
            escapement=request.escapement,
            glyph_indices=glyph_indices,
            vertical_advances=vertical_advances,
            vertical_scale=abs(sy),
            mirrored_layout=self.mapping.rtl,
            precise_origin=precise_origin,
        )
        if layout.position is not None:
            logical_origin = self._state.position
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
        painter = self._painter()
        painter.text(layout, rectangle, options)
        if layout.position is not None:
            self._state.position = layout.position
        painter.decorations(layout, rectangle, options)

    def _pixel(self, x, y, color, *, operation=None):
        self._painter().pixel(x, y, color, operation=operation)

    def _line(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        self._stroke_path(DevicePath.polyline([(start[0] * 16, start[1] * 16), (end[0] * 16, end[1] * 16)]))

    def _stroke_path(self, path, *, miter=False):
        self._painter().stroke_path(path, miter=miter)

    def _realized_pen(self):
        return self._painter().realized_pen()

    def _stroke_fragments(self, paths, *, miter=False):
        return self._painter().stroke_fragments(paths, miter=miter)

    def _contour_pixels(self, contours, *, fill_mode=ALTERNATE):
        return self._painter().contour_pixels(contours, fill_mode=fill_mode)

    def _paint_polygons(self, paths, *, miter=False, reserve_outline=False, brush=None):
        self._painter().paint_polygons(paths, miter=miter, reserve_outline=reserve_outline, brush=brush)

    def _brush_color_at(self, x, y, brush, *, opaque=False):
        return self._painter().brush_color_at(x, y, brush, opaque=opaque)
