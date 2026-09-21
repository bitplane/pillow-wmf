"""Explicit WMF/GDI bindings. File handle indexes never cross into a backend."""

from dataclasses import dataclass

from . import bitmaps, fixed, variable
from .records import Record


@dataclass(frozen=True)
class Binding:
    record: type[Record]
    parameters: tuple[str, ...]
    references: tuple[tuple[str, str], ...] = ()
    signed_words: tuple[str, ...] = ()


BINDINGS = {
    "save_dc": Binding(fixed.SaveDC, (), ()),
    "realize_palette": Binding(fixed.RealizePalette, (), ()),
    "set_background_mode": Binding(fixed.SetBkMode, ("mode",), ()),
    "set_map_mode": Binding(fixed.SetMapMode, ("mode",), ()),
    "set_rop2": Binding(fixed.SetROP2, ("mode",), ()),
    "set_polygon_fill_mode": Binding(fixed.SetPolyFillMode, ("mode",), ()),
    "set_stretch_mode": Binding(fixed.SetStretchBltMode, ("mode",), ()),
    "set_text_character_extra": Binding(fixed.SetTextCharExtra, ("extra",), signed_words=("extra",)),
    "restore_dc": Binding(fixed.RestoreDC, ("saved_dc",), ()),
    "resize_palette": Binding(fixed.ResizePalette, ("count",), ()),
    "delete_object": Binding(fixed.DeleteObject, ("handle",), (("handle", "object_index"),)),
    "select_object": Binding(fixed.SelectObject, ("handle",), (("handle", "object_index"),)),
    "select_palette": Binding(fixed.SelectPalette, ("handle",), (("handle", "palette"),)),
    "select_clip_region": Binding(fixed.SelectClipRegion, ("region",), (("region", "region"),)),
    "paint_region": Binding(fixed.PaintRegion, ("region",), (("region", "region"),)),
    "invert_region": Binding(fixed.InvertRegion, ("region",), (("region", "region"),)),
    "set_text_alignment": Binding(fixed.SetTextAlign, ("alignment",), ()),
    "set_background_color": Binding(fixed.SetBkColor, ("color",), ()),
    "set_text_color": Binding(fixed.SetTextColor, ("color",), ()),
    "set_mapper_flags": Binding(fixed.SetMapperFlags, ("flags",), ()),
    "line_to": Binding(
        fixed.LineTo,
        (
            "x",
            "y",
        ),
        (),
    ),
    "move_to": Binding(
        fixed.MoveTo,
        (
            "x",
            "y",
        ),
        (),
    ),
    "set_window_origin": Binding(
        fixed.SetWindowOrg,
        (
            "x",
            "y",
        ),
        (),
    ),
    "set_window_extent": Binding(
        fixed.SetWindowExt,
        (
            "x",
            "y",
        ),
        (),
    ),
    "set_viewport_origin": Binding(
        fixed.SetViewportOrg,
        (
            "x",
            "y",
        ),
        (),
    ),
    "set_viewport_extent": Binding(
        fixed.SetViewportExt,
        (
            "x",
            "y",
        ),
        (),
    ),
    "offset_window_origin": Binding(
        fixed.OffsetWindowOrg,
        (
            "x",
            "y",
        ),
        (),
    ),
    "offset_viewport_origin": Binding(
        fixed.OffsetViewportOrg,
        (
            "x",
            "y",
        ),
        (),
    ),
    "offset_clip_region": Binding(
        fixed.OffsetClipRgn,
        (
            "x",
            "y",
        ),
        (),
    ),
    "scale_window_extent": Binding(
        fixed.ScaleWindowExt,
        (
            "y_denominator",
            "y_numerator",
            "x_denominator",
            "x_numerator",
        ),
        (),
    ),
    "scale_viewport_extent": Binding(
        fixed.ScaleViewportExt,
        (
            "y_denominator",
            "y_numerator",
            "x_denominator",
            "x_numerator",
        ),
        (),
    ),
    "exclude_clip_rect": Binding(
        fixed.ExcludeClipRect,
        (
            "left",
            "top",
            "right",
            "bottom",
        ),
        (),
    ),
    "intersect_clip_rect": Binding(
        fixed.IntersectClipRect,
        (
            "left",
            "top",
            "right",
            "bottom",
        ),
        (),
    ),
    "rectangle": Binding(
        fixed.Rectangle,
        (
            "left",
            "top",
            "right",
            "bottom",
        ),
        (),
    ),
    "ellipse": Binding(
        fixed.Ellipse,
        (
            "left",
            "top",
            "right",
            "bottom",
        ),
        (),
    ),
    "arc": Binding(
        fixed.Arc,
        (
            "left",
            "top",
            "right",
            "bottom",
            "end_y",
            "end_x",
            "start_y",
            "start_x",
        ),
        (),
    ),
    "chord": Binding(
        fixed.Chord,
        (
            "left",
            "top",
            "right",
            "bottom",
            "end_y",
            "end_x",
            "start_y",
            "start_x",
        ),
        (),
    ),
    "pie": Binding(
        fixed.Pie,
        (
            "left",
            "top",
            "right",
            "bottom",
            "end_y",
            "end_x",
            "start_y",
            "start_x",
        ),
        (),
    ),
    "round_rect": Binding(
        fixed.RoundRect,
        (
            "left",
            "top",
            "right",
            "bottom",
            "ellipse_height",
            "ellipse_width",
        ),
        (),
    ),
    "set_pixel": Binding(
        fixed.SetPixel,
        (
            "x",
            "y",
            "color",
        ),
        (),
    ),
    "flood_fill": Binding(
        fixed.FloodFill,
        (
            "x",
            "y",
            "color",
        ),
        (),
    ),
    "ext_flood_fill": Binding(
        fixed.ExtFloodFill,
        (
            "x",
            "y",
            "mode",
            "color",
        ),
        (),
    ),
    "pat_blt": Binding(
        fixed.PatBlt,
        (
            "x",
            "y",
            "rop",
            "height",
            "width",
        ),
        (),
    ),
    "fill_region": Binding(
        fixed.FillRegion,
        (
            "region",
            "brush",
        ),
        (
            ("region", "region"),
            ("brush", "brush"),
        ),
    ),
    "frame_region": Binding(
        fixed.FrameRegion,
        (
            "region",
            "brush",
            "height",
            "width",
        ),
        (
            ("region", "region"),
            ("brush", "brush"),
        ),
    ),
    "set_text_justification": Binding(
        fixed.SetTextJustification,
        (
            "break_count",
            "break_extra",
        ),
        (),
        signed_words=("break_extra",),
    ),
    "set_layout": Binding(fixed.SetLayout, ("layout",), ()),
    "create_pen": Binding(
        fixed.CreatePenIndirect,
        (
            "style",
            "width",
            "color",
        ),
        (),
    ),
    "create_brush": Binding(
        fixed.CreateBrushIndirect,
        (
            "style",
            "color",
            "hatch",
        ),
        (),
    ),
    "polyline": Binding(variable.Polyline, ("points",), ()),
    "polygon": Binding(variable.Polygon, ("points",), ()),
    "poly_polygon": Binding(variable.PolyPolygon, ("polygons",), ()),
    "text_out": Binding(
        variable.TextOut,
        (
            "x",
            "y",
            "text",
        ),
        (),
    ),
    "ext_text_out": Binding(
        variable.ExtTextOut,
        (
            "x",
            "y",
            "text",
            "options",
            "rectangle",
            "advances",
        ),
        (),
    ),
    "create_font": Binding(variable.CreateFontIndirect, ("font",), ()),
    "create_palette": Binding(variable.CreatePalette, ("palette",), ()),
    "animate_palette": Binding(variable.AnimatePalette, ("palette",), ()),
    "set_palette_entries": Binding(variable.SetPalEntries, ("palette",), ()),
    "create_region": Binding(variable.CreateRegion, ("region",), ()),
    "create_pattern_brush": Binding(variable.CreatePatternBrush, ("bitmap",), ()),
    "create_dib_pattern_brush": Binding(
        variable.DibCreatePatternBrush,
        (
            "style",
            "color_usage",
            "bitmap",
        ),
        (),
    ),
    "escape": Binding(
        variable.Escape,
        (
            "escape_function",
            "data",
        ),
        (),
    ),
    "bit_blt": Binding(
        bitmaps.BitBlt,
        (
            "x",
            "y",
            "width",
            "height",
            "src_x",
            "src_y",
            "rop",
            "source",
        ),
        (),
    ),
    "dib_bit_blt": Binding(
        bitmaps.DibBitBlt,
        (
            "x",
            "y",
            "width",
            "height",
            "src_x",
            "src_y",
            "rop",
            "source",
        ),
        (),
    ),
    "stretch_blt": Binding(
        bitmaps.StretchBlt,
        (
            "x",
            "y",
            "width",
            "height",
            "src_x",
            "src_y",
            "src_width",
            "src_height",
            "rop",
            "source",
        ),
        (),
    ),
    "dib_stretch_blt": Binding(
        bitmaps.DibStretchBlt,
        (
            "x",
            "y",
            "width",
            "height",
            "src_x",
            "src_y",
            "src_width",
            "src_height",
            "rop",
            "source",
        ),
        (),
    ),
    "set_dib_to_device": Binding(
        bitmaps.SetDibToDev,
        (
            "x",
            "y",
            "width",
            "height",
            "src_x",
            "src_y",
            "start_scan",
            "scan_count",
            "color_usage",
            "source",
        ),
        (),
        signed_words=("x", "y", "width", "height", "src_x", "src_y"),
    ),
    "stretch_dib": Binding(
        bitmaps.StretchDib,
        (
            "x",
            "y",
            "width",
            "height",
            "src_x",
            "src_y",
            "src_width",
            "src_height",
            "rop",
            "color_usage",
            "source",
        ),
        (),
    ),
}
BY_KIND = {binding.record.kind: (name, binding) for name, binding in BINDINGS.items()}
