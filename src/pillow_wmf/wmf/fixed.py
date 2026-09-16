"""Fixed-field records. Field order follows MS-WMF, not the GDI argument order."""

from dataclasses import dataclass
from typing import ClassVar

from .constants import RecordType
from .records import FixedRecord, register


@register
@dataclass(frozen=True)
class Eof(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.EOF
    wire_layout: ClassVar[str] = ""
    fields: ClassVar[tuple[str, ...]] = ()
    operation: ClassVar[str | None] = None


@register
@dataclass(frozen=True)
class SaveDC(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SAVEDC
    wire_layout: ClassVar[str] = ""
    fields: ClassVar[tuple[str, ...]] = ()
    operation: ClassVar[str | None] = "save_dc"


@register
@dataclass(frozen=True)
class RealizePalette(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.REALIZEPALETTE
    wire_layout: ClassVar[str] = ""
    fields: ClassVar[tuple[str, ...]] = ()
    operation: ClassVar[str | None] = "realize_palette"


@register
@dataclass(frozen=True)
class SetRelAbs(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SETRELABS
    wire_layout: ClassVar[str] = ""
    fields: ClassVar[tuple[str, ...]] = ()
    operation: ClassVar[str | None] = None
    optional_reserved: ClassVar[bool] = True


@register
@dataclass(frozen=True)
class SetBkMode(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SETBKMODE
    wire_layout: ClassVar[str] = "H"
    fields: ClassVar[tuple[str, ...]] = ("mode",)
    operation: ClassVar[str | None] = "set_background_mode"
    optional_reserved: ClassVar[bool] = True
    mode: int


@register
@dataclass(frozen=True)
class SetMapMode(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SETMAPMODE
    wire_layout: ClassVar[str] = "H"
    fields: ClassVar[tuple[str, ...]] = ("mode",)
    operation: ClassVar[str | None] = "set_map_mode"
    mode: int


@register
@dataclass(frozen=True)
class SetROP2(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SETROP2
    wire_layout: ClassVar[str] = "H"
    fields: ClassVar[tuple[str, ...]] = ("mode",)
    operation: ClassVar[str | None] = "set_rop2"
    optional_reserved: ClassVar[bool] = True
    mode: int


@register
@dataclass(frozen=True)
class SetPolyFillMode(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SETPOLYFILLMODE
    wire_layout: ClassVar[str] = "H"
    fields: ClassVar[tuple[str, ...]] = ("mode",)
    operation: ClassVar[str | None] = "set_polygon_fill_mode"
    optional_reserved: ClassVar[bool] = True
    mode: int


@register
@dataclass(frozen=True)
class SetStretchBltMode(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SETSTRETCHBLTMODE
    wire_layout: ClassVar[str] = "H"
    fields: ClassVar[tuple[str, ...]] = ("mode",)
    operation: ClassVar[str | None] = "set_stretch_mode"
    optional_reserved: ClassVar[bool] = True
    mode: int


@register
@dataclass(frozen=True)
class SetTextCharExtra(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SETTEXTCHAREXTRA
    wire_layout: ClassVar[str] = "H"
    fields: ClassVar[tuple[str, ...]] = ("extra",)
    operation: ClassVar[str | None] = "set_text_character_extra"
    extra: int


@register
@dataclass(frozen=True)
class RestoreDC(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.RESTOREDC
    wire_layout: ClassVar[str] = "h"
    fields: ClassVar[tuple[str, ...]] = ("saved_dc",)
    operation: ClassVar[str | None] = "restore_dc"
    saved_dc: int


@register
@dataclass(frozen=True)
class ResizePalette(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.RESIZEPALETTE
    wire_layout: ClassVar[str] = "H"
    fields: ClassVar[tuple[str, ...]] = ("count",)
    operation: ClassVar[str | None] = "resize_palette"
    count: int


@register
@dataclass(frozen=True)
class DeleteObject(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.DELETEOBJECT
    wire_layout: ClassVar[str] = "H"
    fields: ClassVar[tuple[str, ...]] = ("object_index",)
    operation: ClassVar[str | None] = "delete_object"
    object_index: int


@register
@dataclass(frozen=True)
class SelectObject(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SELECTOBJECT
    wire_layout: ClassVar[str] = "H"
    fields: ClassVar[tuple[str, ...]] = ("object_index",)
    operation: ClassVar[str | None] = "select_object"
    object_index: int


@register
@dataclass(frozen=True)
class SelectPalette(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SELECTPALETTE
    wire_layout: ClassVar[str] = "H"
    fields: ClassVar[tuple[str, ...]] = ("palette",)
    operation: ClassVar[str | None] = "select_palette"
    palette: int


@register
@dataclass(frozen=True)
class SelectClipRegion(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SELECTCLIPREGION
    wire_layout: ClassVar[str] = "H"
    fields: ClassVar[tuple[str, ...]] = ("region",)
    operation: ClassVar[str | None] = "select_clip_region"
    region: int


@register
@dataclass(frozen=True)
class PaintRegion(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.PAINTREGION
    wire_layout: ClassVar[str] = "H"
    fields: ClassVar[tuple[str, ...]] = ("region",)
    operation: ClassVar[str | None] = "paint_region"
    region: int


@register
@dataclass(frozen=True)
class InvertRegion(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.INVERTREGION
    wire_layout: ClassVar[str] = "H"
    fields: ClassVar[tuple[str, ...]] = ("region",)
    operation: ClassVar[str | None] = "invert_region"
    region: int


@register
@dataclass(frozen=True)
class SetTextAlign(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SETTEXTALIGN
    wire_layout: ClassVar[str] = "H"
    fields: ClassVar[tuple[str, ...]] = ("alignment",)
    operation: ClassVar[str | None] = "set_text_alignment"
    optional_reserved: ClassVar[bool] = True
    alignment: int


@register
@dataclass(frozen=True)
class SetBkColor(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SETBKCOLOR
    wire_layout: ClassVar[str] = "I"
    fields: ClassVar[tuple[str, ...]] = ("color",)
    operation: ClassVar[str | None] = "set_background_color"
    color: int


@register
@dataclass(frozen=True)
class SetTextColor(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SETTEXTCOLOR
    wire_layout: ClassVar[str] = "I"
    fields: ClassVar[tuple[str, ...]] = ("color",)
    operation: ClassVar[str | None] = "set_text_color"
    color: int


@register
@dataclass(frozen=True)
class SetMapperFlags(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SETMAPPERFLAGS
    wire_layout: ClassVar[str] = "I"
    fields: ClassVar[tuple[str, ...]] = ("flags",)
    operation: ClassVar[str | None] = "set_mapper_flags"
    flags: int


@register
@dataclass(frozen=True)
class LineTo(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.LINETO
    wire_layout: ClassVar[str] = "hh"
    fields: ClassVar[tuple[str, ...]] = (
        "y",
        "x",
    )
    operation: ClassVar[str | None] = "line_to"
    y: int
    x: int


@register
@dataclass(frozen=True)
class MoveTo(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.MOVETO
    wire_layout: ClassVar[str] = "hh"
    fields: ClassVar[tuple[str, ...]] = (
        "y",
        "x",
    )
    operation: ClassVar[str | None] = "move_to"
    y: int
    x: int


@register
@dataclass(frozen=True)
class SetWindowOrg(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SETWINDOWORG
    wire_layout: ClassVar[str] = "hh"
    fields: ClassVar[tuple[str, ...]] = (
        "y",
        "x",
    )
    operation: ClassVar[str | None] = "set_window_origin"
    y: int
    x: int


@register
@dataclass(frozen=True)
class SetWindowExt(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SETWINDOWEXT
    wire_layout: ClassVar[str] = "hh"
    fields: ClassVar[tuple[str, ...]] = (
        "y",
        "x",
    )
    operation: ClassVar[str | None] = "set_window_extent"
    y: int
    x: int


@register
@dataclass(frozen=True)
class SetViewportOrg(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SETVIEWPORTORG
    wire_layout: ClassVar[str] = "hh"
    fields: ClassVar[tuple[str, ...]] = (
        "y",
        "x",
    )
    operation: ClassVar[str | None] = "set_viewport_origin"
    y: int
    x: int


@register
@dataclass(frozen=True)
class SetViewportExt(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SETVIEWPORTEXT
    wire_layout: ClassVar[str] = "hh"
    fields: ClassVar[tuple[str, ...]] = (
        "y",
        "x",
    )
    operation: ClassVar[str | None] = "set_viewport_extent"
    y: int
    x: int


@register
@dataclass(frozen=True)
class OffsetWindowOrg(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.OFFSETWINDOWORG
    wire_layout: ClassVar[str] = "hh"
    fields: ClassVar[tuple[str, ...]] = (
        "y",
        "x",
    )
    operation: ClassVar[str | None] = "offset_window_origin"
    y: int
    x: int


@register
@dataclass(frozen=True)
class OffsetViewportOrg(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.OFFSETVIEWPORTORG
    wire_layout: ClassVar[str] = "hh"
    fields: ClassVar[tuple[str, ...]] = (
        "y",
        "x",
    )
    operation: ClassVar[str | None] = "offset_viewport_origin"
    y: int
    x: int


@register
@dataclass(frozen=True)
class OffsetClipRgn(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.OFFSETCLIPRGN
    wire_layout: ClassVar[str] = "hh"
    fields: ClassVar[tuple[str, ...]] = (
        "y",
        "x",
    )
    operation: ClassVar[str | None] = "offset_clip_region"
    y: int
    x: int


@register
@dataclass(frozen=True)
class ScaleWindowExt(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SCALEWINDOWEXT
    wire_layout: ClassVar[str] = "hhhh"
    fields: ClassVar[tuple[str, ...]] = (
        "y_denominator",
        "y_numerator",
        "x_denominator",
        "x_numerator",
    )
    operation: ClassVar[str | None] = "scale_window_extent"
    y_denominator: int
    y_numerator: int
    x_denominator: int
    x_numerator: int


@register
@dataclass(frozen=True)
class ScaleViewportExt(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SCALEVIEWPORTEXT
    wire_layout: ClassVar[str] = "hhhh"
    fields: ClassVar[tuple[str, ...]] = (
        "y_denominator",
        "y_numerator",
        "x_denominator",
        "x_numerator",
    )
    operation: ClassVar[str | None] = "scale_viewport_extent"
    y_denominator: int
    y_numerator: int
    x_denominator: int
    x_numerator: int


@register
@dataclass(frozen=True)
class ExcludeClipRect(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.EXCLUDECLIPRECT
    wire_layout: ClassVar[str] = "hhhh"
    fields: ClassVar[tuple[str, ...]] = (
        "bottom",
        "right",
        "top",
        "left",
    )
    operation: ClassVar[str | None] = "exclude_clip_rect"
    bottom: int
    right: int
    top: int
    left: int


@register
@dataclass(frozen=True)
class IntersectClipRect(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.INTERSECTCLIPRECT
    wire_layout: ClassVar[str] = "hhhh"
    fields: ClassVar[tuple[str, ...]] = (
        "bottom",
        "right",
        "top",
        "left",
    )
    operation: ClassVar[str | None] = "intersect_clip_rect"
    bottom: int
    right: int
    top: int
    left: int


@register
@dataclass(frozen=True)
class Rectangle(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.RECTANGLE
    wire_layout: ClassVar[str] = "hhhh"
    fields: ClassVar[tuple[str, ...]] = (
        "bottom",
        "right",
        "top",
        "left",
    )
    operation: ClassVar[str | None] = "rectangle"
    bottom: int
    right: int
    top: int
    left: int


@register
@dataclass(frozen=True)
class Ellipse(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.ELLIPSE
    wire_layout: ClassVar[str] = "hhhh"
    fields: ClassVar[tuple[str, ...]] = (
        "bottom",
        "right",
        "top",
        "left",
    )
    operation: ClassVar[str | None] = "ellipse"
    bottom: int
    right: int
    top: int
    left: int


@register
@dataclass(frozen=True)
class Arc(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.ARC
    wire_layout: ClassVar[str] = "hhhhhhhh"
    fields: ClassVar[tuple[str, ...]] = (
        "end_y",
        "end_x",
        "start_y",
        "start_x",
        "bottom",
        "right",
        "top",
        "left",
    )
    operation: ClassVar[str | None] = "arc"
    end_y: int
    end_x: int
    start_y: int
    start_x: int
    bottom: int
    right: int
    top: int
    left: int


@register
@dataclass(frozen=True)
class Chord(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.CHORD
    wire_layout: ClassVar[str] = "hhhhhhhh"
    fields: ClassVar[tuple[str, ...]] = (
        "end_y",
        "end_x",
        "start_y",
        "start_x",
        "bottom",
        "right",
        "top",
        "left",
    )
    operation: ClassVar[str | None] = "chord"
    end_y: int
    end_x: int
    start_y: int
    start_x: int
    bottom: int
    right: int
    top: int
    left: int


@register
@dataclass(frozen=True)
class Pie(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.PIE
    wire_layout: ClassVar[str] = "hhhhhhhh"
    fields: ClassVar[tuple[str, ...]] = (
        "end_y",
        "end_x",
        "start_y",
        "start_x",
        "bottom",
        "right",
        "top",
        "left",
    )
    operation: ClassVar[str | None] = "pie"
    end_y: int
    end_x: int
    start_y: int
    start_x: int
    bottom: int
    right: int
    top: int
    left: int


@register
@dataclass(frozen=True)
class RoundRect(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.ROUNDRECT
    wire_layout: ClassVar[str] = "hhhhhh"
    fields: ClassVar[tuple[str, ...]] = (
        "ellipse_height",
        "ellipse_width",
        "bottom",
        "right",
        "top",
        "left",
    )
    operation: ClassVar[str | None] = "round_rect"
    ellipse_height: int
    ellipse_width: int
    bottom: int
    right: int
    top: int
    left: int


@register
@dataclass(frozen=True)
class SetPixel(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SETPIXEL
    wire_layout: ClassVar[str] = "Ihh"
    fields: ClassVar[tuple[str, ...]] = (
        "color",
        "y",
        "x",
    )
    operation: ClassVar[str | None] = "set_pixel"
    color: int
    y: int
    x: int


@register
@dataclass(frozen=True)
class FloodFill(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.FLOODFILL
    wire_layout: ClassVar[str] = "Ihh"
    fields: ClassVar[tuple[str, ...]] = (
        "color",
        "y",
        "x",
    )
    operation: ClassVar[str | None] = "flood_fill"
    color: int
    y: int
    x: int


@register
@dataclass(frozen=True)
class ExtFloodFill(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.EXTFLOODFILL
    wire_layout: ClassVar[str] = "HIhh"
    fields: ClassVar[tuple[str, ...]] = (
        "mode",
        "color",
        "y",
        "x",
    )
    operation: ClassVar[str | None] = "ext_flood_fill"
    mode: int
    color: int
    y: int
    x: int


@register
@dataclass(frozen=True)
class PatBlt(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.PATBLT
    wire_layout: ClassVar[str] = "Ihhhh"
    fields: ClassVar[tuple[str, ...]] = (
        "rop",
        "height",
        "width",
        "y",
        "x",
    )
    operation: ClassVar[str | None] = "pat_blt"
    rop: int
    height: int
    width: int
    y: int
    x: int


@register
@dataclass(frozen=True)
class FillRegion(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.FILLREGION
    wire_layout: ClassVar[str] = "HH"
    fields: ClassVar[tuple[str, ...]] = (
        "region",
        "brush",
    )
    operation: ClassVar[str | None] = "fill_region"
    region: int
    brush: int


@register
@dataclass(frozen=True)
class FrameRegion(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.FRAMEREGION
    wire_layout: ClassVar[str] = "HHhh"
    fields: ClassVar[tuple[str, ...]] = (
        "region",
        "brush",
        "height",
        "width",
    )
    operation: ClassVar[str | None] = "frame_region"
    region: int
    brush: int
    height: int
    width: int


@register
@dataclass(frozen=True)
class SetTextJustification(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SETTEXTJUSTIFICATION
    wire_layout: ClassVar[str] = "HH"
    fields: ClassVar[tuple[str, ...]] = (
        "break_count",
        "break_extra",
    )
    operation: ClassVar[str | None] = "set_text_justification"
    break_count: int
    break_extra: int


@register
@dataclass(frozen=True)
class SetLayout(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.SETLAYOUT
    wire_layout: ClassVar[str] = "HH"
    fields: ClassVar[tuple[str, ...]] = (
        "layout",
        "reserved",
    )
    operation: ClassVar[str | None] = "set_layout"
    layout: int
    reserved: int


@register
@dataclass(frozen=True)
class CreatePenIndirect(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.CREATEPENINDIRECT
    wire_layout: ClassVar[str] = "HhhI"
    fields: ClassVar[tuple[str, ...]] = (
        "style",
        "width",
        "unused_y",
        "color",
    )
    operation: ClassVar[str | None] = "create_pen"
    style: int
    width: int
    unused_y: int
    color: int


@register
@dataclass(frozen=True)
class CreateBrushIndirect(FixedRecord):
    kind: ClassVar[RecordType] = RecordType.CREATEBRUSHINDIRECT
    wire_layout: ClassVar[str] = "HIH"
    fields: ClassVar[tuple[str, ...]] = (
        "style",
        "color",
        "hatch",
    )
    operation: ClassVar[str | None] = "create_brush"
    style: int
    color: int
    hatch: int
