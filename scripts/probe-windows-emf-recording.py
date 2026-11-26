"""Print complete native EMF recordings of GDI call sequences, header and EOF included.

Each scenario records into a fresh enhanced-metafile DC whose reference is
the 128x128 reference DIB DC, optionally with a picture frame, and prints
every record as type, size and payload hex. These answer how GDI chooses
record variants, bounds, object slots and header fields. No reference
images are written.

    [scenario] frame=... result=...
      type=... size=... payload=...
"""

import ctypes
import platform
import struct
from ctypes import wintypes
from pathlib import Path

from windows_wmf_render import bind, module_versions, private_fonts, reference_surface

gdi = ctypes.WinDLL("gdi32", use_last_error=True)
ptr, integer, boolean, dword = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL, wintypes.DWORD


def api(name, result, *args):
    return bind(gdi, name, result, *args)


create_emf = api("CreateEnhMetaFileW", ptr, ptr, ctypes.c_wchar_p, ctypes.POINTER(wintypes.RECT), ctypes.c_wchar_p)
close_emf = api("CloseEnhMetaFile", ptr, ptr)
get_bits = api("GetEnhMetaFileBits", wintypes.UINT, ptr, wintypes.UINT, ptr)
delete_emf = api("DeleteEnhMetaFile", boolean, ptr)
select = api("SelectObject", ptr, ptr, ptr)
delete = api("DeleteObject", boolean, ptr)
stock = api("GetStockObject", ptr, integer)
create_pen = api("CreatePen", ptr, integer, integer, dword)
solid_brush = api("CreateSolidBrush", ptr, dword)
hatch_brush = api("CreateHatchBrush", ptr, integer, dword)
rectangle = api("Rectangle", boolean, ptr, integer, integer, integer, integer)
ellipse = api("Ellipse", boolean, ptr, integer, integer, integer, integer)
round_rect = api("RoundRect", boolean, ptr, *(integer,) * 6)
arc = api("Arc", boolean, ptr, *(integer,) * 8)
pie = api("Pie", boolean, ptr, *(integer,) * 8)
move_to = api("MoveToEx", boolean, ptr, integer, integer, ptr)
line_to = api("LineTo", boolean, ptr, integer, integer)
polyline = api("Polyline", boolean, ptr, ctypes.POINTER(wintypes.POINT), integer)
polygon = api("Polygon", boolean, ptr, ctypes.POINTER(wintypes.POINT), integer)
poly_bezier = api("PolyBezier", boolean, ptr, ctypes.POINTER(wintypes.POINT), dword)
poly_polygon = api("PolyPolygon", boolean, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(integer), integer)
set_pixel = api("SetPixelV", boolean, ptr, integer, integer, dword)
set_map_mode = api("SetMapMode", integer, ptr, integer)
set_window_ext = api("SetWindowExtEx", boolean, ptr, integer, integer, ptr)
set_viewport_ext = api("SetViewportExtEx", boolean, ptr, integer, integer, ptr)
set_window_org = api("SetWindowOrgEx", boolean, ptr, integer, integer, ptr)
set_bk_mode = api("SetBkMode", integer, ptr, integer)
set_bk_color = api("SetBkColor", dword, ptr, dword)
set_text_color = api("SetTextColor", dword, ptr, dword)
set_rop2 = api("SetROP2", integer, ptr, integer)
save_dc = api("SaveDC", integer, ptr)
restore_dc = api("RestoreDC", boolean, ptr, integer)
begin_path = api("BeginPath", boolean, ptr)
end_path = api("EndPath", boolean, ptr)
stroke_path = api("StrokePath", boolean, ptr)
fill_path = api("FillPath", boolean, ptr)
intersect_clip = api("IntersectClipRect", integer, ptr, integer, integer, integer, integer)
create_rect_rgn = api("CreateRectRgn", ptr, integer, integer, integer, integer)
select_clip_rgn = api("SelectClipRgn", integer, ptr, ptr)
fill_rgn = api("FillRgn", boolean, ptr, ptr, ptr)
set_graphics_mode = api("SetGraphicsMode", integer, ptr, integer)


class XForm(ctypes.Structure):
    _fields_ = [(name, ctypes.c_float) for name in ("m11", "m12", "m21", "m22", "dx", "dy")]


class LogBrush(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("color", wintypes.DWORD), ("hatch", ctypes.c_size_t)]


class BitmapInfo(ctypes.Structure):
    _fields_ = [
        ("size", dword),
        ("width", wintypes.LONG),
        ("height", wintypes.LONG),
        ("planes", wintypes.WORD),
        ("bit_count", wintypes.WORD),
        ("compression", dword),
        ("size_image", dword),
        ("xppm", wintypes.LONG),
        ("yppm", wintypes.LONG),
        ("used", dword),
        ("important", dword),
    ]


set_world_transform = api("SetWorldTransform", boolean, ptr, ctypes.POINTER(XForm))
ext_create_pen = api("ExtCreatePen", ptr, dword, dword, ctypes.POINTER(LogBrush), dword, ptr)
pat_blt = api("PatBlt", boolean, ptr, *(integer,) * 4, dword)
stretch_dib = api("StretchDIBits", integer, ptr, *(integer,) * 8, ptr, ptr, wintypes.UINT, dword)
set_miter_limit = api("SetMiterLimit", boolean, ptr, ctypes.c_float, ptr)


def points(*values):
    return (wintypes.POINT * len(values))(*[wintypes.POINT(*value) for value in values]), len(values)


def scenarios():
    def empty(dc):
        return None

    yield "empty", None, empty
    yield "empty-frame", (0, 0, 3388, 3383), empty

    def one_rectangle(dc):
        return rectangle(dc, 10, 20, 50, 40)

    yield "rectangle", None, one_rectangle
    yield "rectangle-frame", (0, 0, 3388, 3383), one_rectangle

    def objects(dc):
        pen = create_pen(0, 5, 0x0000FF)
        brush = solid_brush(0x00FF00)
        unused = solid_brush(0x123456)  # Never selected.
        select(dc, pen)
        select(dc, brush)
        rectangle(dc, 10, 10, 40, 30)
        select(dc, stock(0))  # WHITE_BRUSH
        select(dc, stock(7))  # BLACK_PEN
        delete(pen)
        delete(unused)
        second = hatch_brush(2, 0xFF0000)
        select(dc, second)
        ellipse(dc, 50, 50, 90, 80)
        third = solid_brush(0x0000FF)
        select(dc, third)  # The second brush stays selected? No: replaced.
        delete(second)
        delete(third)
        return None

    yield "objects", None, objects

    def selected_delete(dc):
        brush = solid_brush(0x00FF00)
        select(dc, brush)
        delete(brush)  # Deleting the selected brush.
        rectangle(dc, 1, 1, 9, 9)
        return None

    yield "selected-delete", None, selected_delete

    def wide_pens(dc):
        for width in (0, 1, 2, 3, 6):
            pen = create_pen(0, width, 0)
            old = select(dc, pen)
            line_to(dc, 20 + width, 30)
            rectangle(dc, 40, 40, 60 + width, 70)
            select(dc, old)
            delete(pen)
        return None

    yield "wide-pens", None, wide_pens

    def shapes(dc):
        ellipse(dc, 5, 6, 30, 20)
        round_rect(dc, 5, 30, 40, 60, 10, 8)
        arc(dc, 50, 5, 90, 40, 90, 20, 50, 5)
        pie(dc, 50, 50, 90, 90, 90, 70, 70, 50)
        set_pixel(dc, 3, 4, 0x00FF00)
        return None

    yield "shapes", None, shapes

    def lines(dc):
        move_to(dc, 3, 4, None)
        line_to(dc, 30, 40)
        array, count = points((1, 2), (30, 5), (60, 40))
        polyline(dc, array, count)
        polygon(dc, array, count)
        array, count = points((1, 2), (40000, 5), (60, 40))
        polyline(dc, array, count)
        array, count = points((-5, 2), (30, -7), (60, 40))
        polyline(dc, array, count)
        array, count = points((1, 2), (10, 30), (30, 30), (40, 2))
        poly_bezier(dc, array, count)
        array, count = points((1, 1), (20, 1), (20, 20), (40, 40), (60, 40), (60, 60))
        counts = (integer * 2)(3, 3)
        poly_polygon(dc, array, counts, 2)
        return None

    yield "lines", None, lines

    def mapping(dc):
        set_map_mode(dc, 8)
        set_window_ext(dc, 100, 100, None)
        set_viewport_ext(dc, 50, 200, None)
        set_window_org(dc, 10, 10, None)
        rectangle(dc, 10, 10, 50, 30)
        return None

    yield "mapping", None, mapping

    def state(dc):
        set_bk_mode(dc, 1)
        set_bk_color(dc, 0x123456)
        set_text_color(dc, 0x654321)
        set_rop2(dc, 7)
        save_dc(dc)
        intersect_clip(dc, 5, 5, 50, 50)
        rectangle(dc, 0, 0, 60, 60)
        restore_dc(dc, -1)
        region = create_rect_rgn(10, 10, 30, 30)
        select_clip_rgn(dc, region)
        fill_rgn(dc, region, stock(4))
        delete(region)
        return None

    yield "state", None, state

    def paths(dc):
        begin_path(dc)
        move_to(dc, 5, 5, None)
        line_to(dc, 40, 10)
        line_to(dc, 20, 40)
        end_path(dc)
        stroke_path(dc)
        begin_path(dc)
        rectangle(dc, 50, 50, 80, 80)
        end_path(dc)
        fill_path(dc)
        return None

    yield "paths", None, paths

    # Bounds: one figure per metafile, so the header bounds belong to it.
    figures = {
        "rect": lambda dc: rectangle(dc, 20, 20, 40, 30),
        "ellipse": lambda dc: ellipse(dc, 20, 20, 40, 30),
        "line": lambda dc: (move_to(dc, 20, 20, None), line_to(dc, 40, 30)),
        "polyline": lambda dc: polyline(dc, *points((20, 20), (40, 30), (25, 35))),
        "polygon": lambda dc: polygon(dc, *points((20, 20), (40, 30), (25, 35))),
    }
    for figure, draw_figure in figures.items():
        for width in (0, 1, 2, 3, 4, 5, 8, 11):

            def draw(dc, width=width, draw_figure=draw_figure):
                pen = create_pen(0, width, 0)
                select(dc, pen)
                draw_figure(dc)
                return None

            yield f"bounds-{figure}-w{width}", None, draw
    for style in (1, 5, 6):

        def styled(dc, style=style):
            select(dc, create_pen(style, 6, 0))
            rectangle(dc, 20, 20, 40, 30)
            return None

        yield f"bounds-rect-style{style}", None, styled

    def geometric(dc):
        brush = LogBrush(0, 0, 0)
        select(dc, ext_create_pen(0x00010000 | 0x0200 | 0x2000, 6, ctypes.byref(brush), 0, None))
        polyline(dc, *points((20, 20), (40, 30), (25, 35)))
        return None

    yield "bounds-geometric-miter", None, geometric

    def miter(dc):
        set_miter_limit(dc, 2.0, None)
        select(dc, create_pen(0, 5, 0))
        rectangle(dc, 20, 20, 40, 30)
        return None

    yield "bounds-rect-miter2", None, miter

    def scaled(dc):
        set_map_mode(dc, 8)
        set_window_ext(dc, 10, 10, None)
        set_viewport_ext(dc, 25, 25, None)
        select(dc, create_pen(0, 2, 0))
        rectangle(dc, 4, 4, 20, 12)
        polyline(dc, *points((4, 4), (20, 12)))
        return None

    yield "bounds-scaled", None, scaled

    def advanced(dc):
        set_graphics_mode(dc, 2)
        set_world_transform(dc, ctypes.byref(XForm(1.5, 0, 0, 2.0, 3.0, 4.0)))
        rectangle(dc, 10, 10, 30, 20)
        ellipse(dc, 10, 10, 30, 20)
        set_graphics_mode(dc, 2)
        return None

    yield "advanced", None, advanced

    def transfers(dc):
        pat_blt(dc, 5, 6, 20, 10, 0x00F00021)
        info = BitmapInfo(40, 2, 2, 1, 24, 0, 0, 0, 0, 0, 0)
        bits = bytes(range(16))
        stretch_dib(dc, 30, 30, 8, 6, 0, 0, 2, 2, bits, ctypes.byref(info), 0, 0x00CC0020)
        return None

    yield "transfers", None, transfers


msimg = ctypes.WinDLL("msimg32", use_last_error=True)
modify_world_transform = api("ModifyWorldTransform", boolean, ptr, ctypes.POINTER(XForm), dword)
exclude_clip = api("ExcludeClipRect", integer, ptr, integer, integer, integer, integer)
create_brush_indirect = api("CreateBrushIndirect", ptr, ctypes.POINTER(LogBrush))
create_dc = api("CreateCompatibleDC", ptr, ptr)
delete_dc = api("DeleteDC", boolean, ptr)
create_dib_section = api("CreateDIBSection", ptr, ptr, ptr, wintypes.UINT, ctypes.POINTER(ptr), ptr, dword)
create_bitmap = api("CreateBitmap", ptr, integer, integer, wintypes.UINT, wintypes.UINT, ptr)
pattern_brush = api("CreatePatternBrush", ptr, ptr)
dib_pattern_brush = api("CreateDIBPatternBrushPt", ptr, ptr, wintypes.UINT)
bit_blt = api("BitBlt", boolean, ptr, *(integer,) * 4, ptr, integer, integer, dword)
stretch_blt = api("StretchBlt", boolean, ptr, *(integer,) * 4, ptr, *(integer,) * 4, dword)
mask_blt = api("MaskBlt", boolean, ptr, *(integer,) * 4, ptr, integer, integer, ptr, integer, integer, dword)
plg_blt = api("PlgBlt", boolean, ptr, ctypes.POINTER(wintypes.POINT), ptr, *(integer,) * 4, ptr, integer, integer)
alpha_blend = bind(msimg, "AlphaBlend", boolean, ptr, *(integer,) * 4, ptr, *(integer,) * 4, dword)
transparent_blt = bind(msimg, "TransparentBlt", boolean, ptr, *(integer,) * 4, ptr, *(integer,) * 4, wintypes.UINT)
set_dib_to_device = api(
    "SetDIBitsToDevice",
    integer,
    ptr,
    integer,
    integer,
    dword,
    dword,
    integer,
    integer,
    wintypes.UINT,
    wintypes.UINT,
    ptr,
    ptr,
    wintypes.UINT,
)
set_stretch_mode = api("SetStretchBltMode", integer, ptr, integer)
create_palette = api("CreatePalette", ptr, ptr)
select_palette = api("SelectPalette", ptr, ptr, ptr, boolean)
realize_palette = api("RealizePalette", wintypes.UINT, ptr)
set_palette_entries = api("SetPaletteEntries", wintypes.UINT, ptr, wintypes.UINT, wintypes.UINT, ptr)
resize_palette = api("ResizePalette", boolean, ptr, wintypes.UINT)
animate_palette = api("AnimatePalette", boolean, ptr, wintypes.UINT, wintypes.UINT, ptr)
set_arc_direction = api("SetArcDirection", integer, ptr, integer)
arc_to = api("ArcTo", boolean, ptr, *(integer,) * 8)
angle_arc = api("AngleArc", boolean, ptr, integer, integer, dword, ctypes.c_float, ctypes.c_float)
chord = api("Chord", boolean, ptr, *(integer,) * 8)
poly_draw = api("PolyDraw", boolean, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)
polyline_to = api("PolylineTo", boolean, ptr, ctypes.POINTER(wintypes.POINT), dword)
poly_bezier_to = api("PolyBezierTo", boolean, ptr, ctypes.POINTER(wintypes.POINT), dword)
poly_polyline = api("PolyPolyline", boolean, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(dword), dword)
scale_window_ext = api("ScaleWindowExtEx", boolean, ptr, integer, integer, integer, integer, ptr)
set_viewport_org = api("SetViewportOrgEx", boolean, ptr, integer, integer, ptr)
offset_window_org = api("OffsetWindowOrgEx", boolean, ptr, integer, integer, ptr)
set_brush_org = api("SetBrushOrgEx", boolean, ptr, integer, integer, ptr)
ext_flood_fill = api("ExtFloodFill", boolean, ptr, integer, integer, dword, wintypes.UINT)
set_layout = api("SetLayout", dword, ptr, dword)
set_poly_fill_mode = api("SetPolyFillMode", integer, ptr, integer)
flatten_path = api("FlattenPath", boolean, ptr)
widen_path = api("WidenPath", boolean, ptr)
select_clip_path = api("SelectClipPath", boolean, ptr, integer)
abort_path = api("AbortPath", boolean, ptr)
close_figure = api("CloseFigure", boolean, ptr)
frame_rgn = api("FrameRgn", boolean, ptr, ptr, ptr, integer, integer)
invert_rgn = api("InvertRgn", boolean, ptr, ptr)
paint_rgn = api("PaintRgn", boolean, ptr, ptr)
ext_select_clip_rgn = api("ExtSelectClipRgn", integer, ptr, ptr, integer)
offset_clip_rgn = api("OffsetClipRgn", integer, ptr, integer, integer)
set_meta_rgn = api("SetMetaRgn", integer, ptr)
gradient = bind(msimg, "GradientFill", boolean, ptr, ptr, dword, ptr, dword, dword)


def dib_info(width, height, depth, colors=()):
    header = struct.pack("<IiiHHIIiiII", 40, width, height, 1, depth, 0, 0, 0, 0, len(colors), 0)
    return header + b"".join(struct.pack("<I", color) for color in colors)


def source_dc(depth=32):
    """A memory DC holding a 4x3 DIB section with deterministic samples."""
    dc = create_dc(None)
    info = ctypes.create_string_buffer(dib_info(4, -3, depth, (0x000000, 0xFFFFFF) if depth == 1 else ()), 48)
    bits = ptr()
    bitmap = create_dib_section(dc, info, 0, ctypes.byref(bits), None, 0)
    stride = ((4 * depth + 31) // 32) * 4
    ctypes.memmove(bits, bytes((7 * i) % 256 for i in range(stride * 3)), stride * 3)
    select(dc, bitmap)
    return dc, bitmap


def more_scenarios():
    def advanced_once(dc):
        set_graphics_mode(dc, 2)
        set_world_transform(dc, ctypes.byref(XForm(1.5, 0, 0, 2.0, 3.0, 4.0)))
        rectangle(dc, 10, 10, 30, 20)

    yield "advanced-once", None, advanced_once

    def advanced_modes(dc):
        set_graphics_mode(dc, 2)
        set_graphics_mode(dc, 2)
        rectangle(dc, 10, 10, 30, 20)
        set_graphics_mode(dc, 1)
        rectangle(dc, 10, 10, 30, 20)

    yield "advanced-modes", None, advanced_modes

    def advanced_modify(dc):
        set_graphics_mode(dc, 2)
        modify_world_transform(dc, ctypes.byref(XForm(2, 0, 0, 2, 1, 1)), 2)
        modify_world_transform(dc, ctypes.byref(XForm(1, 0, 0.5, 1, 0, 0)), 3)
        rectangle(dc, 10, 10, 30, 20)
        modify_world_transform(dc, None, 1)
        set_world_transform(dc, ctypes.byref(XForm(1, 0, 0, 1, 0, 0)))
        set_graphics_mode(dc, 1)
        ellipse(dc, 40, 40, 60, 60)

    yield "advanced-modify", None, advanced_modify

    def null_brush(dc):
        select(dc, create_brush_indirect(ctypes.byref(LogBrush(1, 0, 0))))
        rectangle(dc, 10, 10, 30, 20)
        select(dc, stock(5))
        select(dc, stock(8))
        rectangle(dc, 40, 40, 60, 60)

    yield "null-brush", None, null_brush

    def clipped_bounds(dc):
        intersect_clip(dc, 10, 10, 40, 40)
        polyline(dc, *points((0, 0), (60, 30)))
        exclude_clip(dc, 10, 10, 40, 25)
        rectangle(dc, 0, 0, 60, 60)
        select_clip_rgn(dc, None)
        rectangle(dc, 70, 70, 80, 80)

    yield "clipped-bounds", None, clipped_bounds

    def regions(dc):
        region = create_rect_rgn(10, 10, 30, 30)
        frame_rgn(dc, region, stock(4), 2, 3)
        invert_rgn(dc, region)
        paint_rgn(dc, region)
        ext_select_clip_rgn(dc, region, 1)
        offset_clip_rgn(dc, 5, 6)
        set_meta_rgn(dc)
        rectangle(dc, 0, 0, 50, 50)
        delete(region)

    yield "regions", None, regions

    def palettes(dc):
        entries = struct.pack("<HH", 0x300, 4) + bytes((255, 0, 0, 0, 0, 255, 0, 0, 0, 0, 255, 0, 9, 9, 9, 1))
        buffer = ctypes.create_string_buffer(entries)
        palette = create_palette(buffer)
        select_palette(dc, palette, False)
        realize_palette(dc)
        update = ctypes.create_string_buffer(bytes((1, 2, 3, 0)))
        set_palette_entries(palette, 1, 1, update)
        resize_palette(palette, 6)
        animate_palette(palette, 3, 1, update)
        select_palette(dc, stock(15), False)
        delete(palette)

    yield "palettes", None, palettes

    def pattern_brushes(dc):
        mono = create_bitmap(8, 8, 1, 1, ctypes.create_string_buffer(bytes((0xAA, 0, 0x55, 0) * 4), 16))
        select(dc, pattern_brush(mono))
        rectangle(dc, 0, 0, 20, 20)
        source, bitmap = source_dc()
        select(dc, pattern_brush(bitmap))
        rectangle(dc, 30, 0, 50, 20)
        packed = ctypes.create_string_buffer(dib_info(2, 2, 24) + bytes(range(16)))
        select(dc, dib_pattern_brush(packed, 0))
        rectangle(dc, 60, 0, 80, 20)
        delete_dc(source)

    yield "pattern-brushes", None, pattern_brushes

    def dib_pattern_pen(dc):
        packed = ctypes.create_string_buffer(dib_info(2, 2, 24) + bytes(range(16)))
        brush = LogBrush(6, 0, ctypes.cast(packed, ctypes.c_void_p).value)
        select(dc, ext_create_pen(0x00010000, 4, ctypes.byref(brush), 0, None))
        line_to(dc, 30, 30)

    yield "dib-pattern-pen", None, dib_pattern_pen

    def transfers(dc):
        source, _ = source_dc()
        bit_blt(dc, 1, 2, 4, 3, source, 0, 0, 0x00CC0020)
        bit_blt(dc, 10, 2, 4, 3, source, 1, 1, 0x00660046)
        set_stretch_mode(dc, 4)
        stretch_blt(dc, 20, 2, 8, 6, source, 0, 0, 4, 3, 0x00CC0020)
        mono = create_bitmap(4, 3, 1, 1, ctypes.create_string_buffer(bytes((0xA0, 0, 0x50, 0, 0xA0, 0)), 6))
        mask_blt(dc, 30, 2, 4, 3, source, 0, 0, mono, 0, 0, 0xAACC0020)
        plg_blt(
            dc,
            (wintypes.POINT * 3)(wintypes.POINT(45, 1), wintypes.POINT(60, 6), wintypes.POINT(42, 12)),
            source,
            0,
            0,
            4,
            3,
            None,
            0,
            0,
        )
        alpha_blend(dc, 1, 20, 8, 6, source, 0, 0, 4, 3, 0x00800000)
        transparent_blt(dc, 20, 20, 8, 6, source, 0, 0, 4, 3, 0x00030201)
        info = ctypes.create_string_buffer(dib_info(2, 2, 24))
        set_dib_to_device(dc, 40, 20, 2, 2, 0, 0, 0, 2, bytes(range(16)), info, 0)
        delete_dc(source)

    yield "transfers-all", None, transfers

    def gradients(dc):
        class TriVertex(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)] + [(c, ctypes.c_ushort) for c in "rgba"]

        vertices = (TriVertex * 3)(
            TriVertex(1, 2, 0xFF00, 0, 0, 0), TriVertex(30, 20, 0, 0xFF00, 0, 0), TriVertex(5, 25, 0, 0, 0xFF00, 0)
        )
        gradient(dc, vertices, 2, (dword * 2)(0, 1), 1, 0)
        gradient(dc, vertices, 3, (dword * 3)(0, 1, 2), 1, 2)

    yield "gradients", None, gradients

    def curves(dc):
        set_arc_direction(dc, 2)
        move_to(dc, 5, 5, None)
        arc_to(dc, 10, 10, 40, 30, 40, 20, 10, 10)
        angle_arc(dc, 60, 60, 10, 30.0, 120.0)
        chord(dc, 70, 5, 100, 30, 100, 15, 70, 5)
        polyline_to(dc, *points((1, 90), (20, 100)))
        poly_bezier_to(dc, *points((30, 90), (40, 110), (50, 100)))
        array, count = points((5, 5), (20, 5), (20, 20), (60, 60), (70, 60))
        poly_polyline(dc, array, (dword * 2)(3, 2), 2)
        types = (ctypes.c_ubyte * 4)(6, 2, 2, 3)
        array, count = points((80, 80), (90, 80), (90, 90), (80, 90))
        poly_draw(dc, array, types, count)

    yield "curves", None, curves

    def state_more(dc):
        set_map_mode(dc, 8)
        set_window_ext(dc, 100, 100, None)
        set_viewport_ext(dc, 100, 100, None)
        scale_window_ext(dc, 2, 1, 3, 2, None)
        set_viewport_org(dc, 5, 6, None)
        offset_window_org(dc, 3, 4, None)
        set_brush_org(dc, 2, 3, None)
        set_poly_fill_mode(dc, 2)
        set_miter_limit(dc, 4.5, None)
        set_layout(dc, 0)
        ext_flood_fill(dc, 10, 10, 0, 1)
        rectangle(dc, 10, 10, 30, 30)

    yield "state-more", None, state_more

    def paths_more(dc):
        begin_path(dc)
        move_to(dc, 5, 5, None)
        line_to(dc, 40, 10)
        close_figure(dc)
        end_path(dc)
        flatten_path(dc)
        widen_path(dc)
        select_clip_path(dc, 5)
        begin_path(dc)
        line_to(dc, 1, 1)
        abort_path(dc)
        rectangle(dc, 0, 0, 60, 60)

    yield "paths-more", None, paths_more


class LogFontW(ctypes.Structure):
    _fields_ = [(name, wintypes.LONG) for name in ("height", "width", "escapement", "orientation", "weight")]
    _fields_ += [(name, ctypes.c_ubyte) for name in ("italic", "underline", "strikeout", "charset")]
    _fields_ += [(name, ctypes.c_ubyte) for name in ("out_precision", "clip_precision", "quality", "pitch_and_family")]
    _fields_ += [("face", ctypes.c_wchar * 32)]


create_font_indirect = api("CreateFontIndirectW", ptr, ctypes.POINTER(LogFontW))


def dib_section(depth, colors, *, height=-3, compression=0, masks=()):
    """A memory DC holding a 4-pixel-wide DIB section of ``depth``."""
    dc = create_dc(None)
    header = struct.pack("<IiiHHIIiiII", 40, 4, height, 1, depth, compression, 0, 0, 0, len(colors), 0)
    data = header + b"".join(struct.pack("<I", value) for value in (*masks, *colors))
    info = ctypes.create_string_buffer(data, len(data) + 1024)
    bits = ptr()
    bitmap = create_dib_section(dc, info, 0, ctypes.byref(bits), None, 0)
    stride = ((4 * depth + 31) // 32) * 4
    ctypes.memmove(bits, bytes((37 * i + 11) % 256 for i in range(stride * abs(height))), stride * abs(height))
    select(dc, bitmap)
    return dc


def gap_scenarios():
    def fonts(dc):
        for height, weight, italic, face, charset in (
            (-12, 400, 0, "Arial", 0),
            (20, 700, 1, "Courier New", 0),
            (-9, 0, 0, "", 1),
            (-30, 400, 0, "A Face Name Of Thirty-One Chars", 238),
        ):
            font = create_font_indirect(
                ctypes.byref(LogFontW(height, 0, 0, 0, weight, italic, 0, 0, charset, 0, 0, 0, 0, face))
            )
            select(dc, font)
            delete(font)
        select(dc, stock(13))
        select(dc, stock(17))

    yield "fonts", None, fonts

    def arc_positions(dc):
        for x, y, radius, start, sweep in (
            (60, 60, 10, 30.0, 120.0),
            (60, 60, 10, 0.0, 90.0),
            (60, 60, 10, 45.0, -60.0),
            (50, 50, 17, 200.0, 75.0),
            (50, 50, 17, 10.0, 350.0),
            (40, 40, 5, 123.0, 1.5),
            (40, 40, 9, 300.0, -200.0),
        ):
            move_to(dc, 0, 0, None)
            angle_arc(dc, x, y, radius, start, sweep)
            polyline_to(dc, *points((300, 300)))
        set_arc_direction(dc, 2)
        for box, radials in (
            ((10, 10, 40, 30), (40, 20, 10, 10)),
            ((10, 10, 41, 31), (40, 10, 10, 30)),
            ((5, 7, 60, 50), (0, 0, 60, 60)),
        ):
            move_to(dc, 0, 0, None)
            arc_to(dc, *box, *radials)
            polyline_to(dc, *points((300, 300)))
        set_arc_direction(dc, 1)
        move_to(dc, 0, 0, None)
        arc_to(dc, 10, 10, 40, 30, 40, 20, 10, 10)
        polyline_to(dc, *points((300, 300)))

    yield "arc-positions", None, arc_positions

    def colour_patterns(dc):
        for depth in (1, 4, 8, 16, 24, 32):
            stride = ((8 * depth + 15) // 16) * 2
            data = bytes((53 * i + 7) % 256 for i in range(stride * 8))
            bitmap = create_bitmap(8, 8, 1, depth, ctypes.create_string_buffer(data, len(data)))
            select(dc, pattern_brush(bitmap))
            rectangle(dc, 0, 0, 10, 10)
            select(dc, stock(0))

    yield "colour-patterns", None, colour_patterns

    def source_depths(dc):
        sources = (
            ("1", dib_section(1, (0x000000, 0xFFFFFF))),
            ("1-colours", dib_section(1, (0x123456, 0xABCDEF))),
            ("4", dib_section(4, tuple(0x111111 * i for i in range(16)))),
            ("4-short", dib_section(4, (0xFF0000, 0x00FF00, 0x0000FF))),
            ("8", dib_section(8, tuple(0x010203 * i for i in range(256)))),
            ("8-short", dib_section(8, tuple(0x0A0B0C * i for i in range(5)))),
            ("16", dib_section(16, ())),
            ("16-565", dib_section(16, (), compression=3, masks=(0xF800, 0x07E0, 0x001F))),
            ("24", dib_section(24, ())),
            ("24-bottom-up", dib_section(24, (), height=3)),
            ("32-bitfields", dib_section(32, (), compression=3, masks=(0xFF0000, 0xFF00, 0xFF))),
        )
        for index, (_, source) in enumerate(sources):
            bit_blt(dc, 5 * index, 2, 4, 3, source, 0, 0, 0x00CC0020)
            delete_dc(source)

    yield "source-depths", None, source_depths

    def excluded(dc):
        intersect_clip(dc, 10, 10, 50, 50)
        exclude_clip(dc, 0, 0, 30, 60)
        rectangle(dc, 0, 0, 60, 60)

    yield "excluded-left", None, excluded

    def excluded_middle(dc):
        intersect_clip(dc, 10, 10, 50, 50)
        exclude_clip(dc, 20, 20, 40, 40)
        rectangle(dc, 0, 0, 60, 60)

    yield "excluded-middle", None, excluded_middle

    for variant in ("plain", "close", "flatten", "widen", "widen5", "close-widen"):

        def clip_path(dc, variant=variant):
            if variant == "widen5":
                select(dc, create_pen(0, 5, 0))
            begin_path(dc)
            move_to(dc, 5, 5, None)
            line_to(dc, 40, 10)
            line_to(dc, 20, 40)
            if "close" in variant:
                close_figure(dc)
            end_path(dc)
            if variant == "flatten":
                flatten_path(dc)
            if "widen" in variant:
                widen_path(dc)
            select_clip_path(dc, 5)
            rectangle(dc, 0, 0, 60, 60)

        yield f"clip-path-{variant}", None, clip_path

    def angle_arc_turns(dc):
        # Sweeps of a full turn or more: the bounds and current position.
        for x, y, radius, start, sweep in (
            (60, 60, 10, 30.0, 360.0),
            (60, 60, 10, 90.0, 1080.0),
            (50, 50, 17, 45.0, 400.0),
            (50, 50, 17, 300.0, -540.0),
        ):
            move_to(dc, 0, 0, None)
            angle_arc(dc, x, y, radius, start, sweep)
            polyline_to(dc, *points((300, 300)))
        move_to(dc, 70, 70, None)
        angle_arc(dc, 70, 70, 20, 10.0, 725.0)

    yield "angle-arc-turns", None, angle_arc_turns

    def null_selections(dc):
        # Null object and palette selections, between drawing calls.
        rectangle(dc, 0, 0, 10, 10)
        select(dc, None)
        rectangle(dc, 20, 0, 30, 10)
        select_palette(dc, None, False)
        rectangle(dc, 40, 0, 50, 10)

    yield "null-selections", None, null_selections

    def clip_path_shapes(dc):
        # SelectClipPath of paths holding shapes and curves; each clipped
        # polyline's bounds give the clip region's box.
        shapes = (
            lambda: ellipse(dc, 5, 5, 40, 30),
            lambda: round_rect(dc, 6, 4, 41, 33, 12, 9),
            lambda: pie(dc, 5, 5, 41, 31, 40, 5, 5, 6),
            lambda: chord(dc, 3, 7, 44, 30, 2, 30, 44, 8),
            lambda: (move_to(dc, 2, 2, None), arc_to(dc, 10, 10, 50, 35, 50, 20, 10, 12), line_to(dc, 2, 2)),
            lambda: (move_to(dc, 30, 30, None), angle_arc(dc, 20, 20, 13, 30.0, 200.0)),
            lambda: (move_to(dc, 4, 4, None), poly_bezier_to(dc, *points((60, 0), (0, 60), (50, 50)))),
            lambda: (arc(dc, 5, 5, 45, 35, 45, 10, 5, 30), ellipse(dc, 30, 30, 45, 50)),
        )
        for shape in shapes:
            save_dc(dc)
            begin_path(dc)
            shape()
            end_path(dc)
            select_clip_path(dc, 5)
            polyline(dc, *points((0, 0), (90, 0), (90, 90), (0, 90), (0, 0)))
            restore_dc(dc, -1)
        set_graphics_mode(dc, 2)
        set_world_transform(dc, ctypes.byref(XForm(0.9, 0.4, -0.4, 0.9, 20, 0)))
        begin_path(dc)
        ellipse(dc, 5, 5, 40, 30)
        end_path(dc)
        select_clip_path(dc, 5)
        polyline(dc, *points((-50, -50), (90, -50), (90, 90), (-50, 90), (-50, -50)))

    yield "clip-path-shapes", None, clip_path_shapes

    def mask_blt_patterns(dc):
        # Source-less MaskBlt: the pattern through a mask, and without one.
        select(dc, hatch_brush(5, 0x0000FF))
        mono = create_bitmap(8, 6, 1, 1, ctypes.create_string_buffer(bytes((0xA5, 0, 0x5A, 0) * 3), 12))
        mask_blt(dc, 4, 4, 8, 6, None, 0, 0, mono, 0, 0, 0xAAF00021)
        mask_blt(dc, 20, 4, 8, 6, None, 0, 0, mono, 2, 1, 0x55F00021)
        mask_blt(dc, 36, 4, 8, 6, None, 0, 0, None, 0, 0, 0xAAF00021)
        delete(mono)

    yield "mask-blt-patterns", None, mask_blt_patterns

    def compressed_pattern_brushes(dc):
        # DIB pattern brushes from RLE8 and RLE4 DIBs.
        palette = b"".join(struct.pack("<I", value) for value in (0x0000FF, 0x00FF00, 0xFF0000, 0xFFFFFF))
        for compression, bits in (
            (1, bytes((4, 1, 4, 2, 0, 0, 8, 3, 0, 0, 2, 0, 0, 2, 2, 1, 0, 0, 0, 1))),
            (2, bytes((8, 0x12, 0, 0, 8, 0x30, 0, 0, 0, 3, 0x12, 0x30, 0, 0, 0, 1))),
        ):
            depth = 8 if compression == 1 else 4
            header = struct.pack("<IiiHHIIiiII", 40, 8, 4, 1, depth, compression, len(bits), 0, 0, 4, 0)
            packed = ctypes.create_string_buffer(header + palette + bits)
            select(dc, dib_pattern_brush(packed, 0))
            rectangle(dc, 0, 0, 20, 20)
            select(dc, stock(0))

    yield "compressed-pattern-brushes", None, compressed_pattern_brushes

    def clip_path_widened_shapes(dc):
        # SelectClipPath after widening shapes, arcs and extended-pen paths.
        select(dc, create_pen(0, 5, 0))
        shapes = (
            lambda: ellipse(dc, 5, 5, 40, 30),
            lambda: round_rect(dc, 6, 4, 41, 33, 12, 9),
            lambda: pie(dc, 5, 5, 41, 31, 40, 5, 5, 6),
            lambda: (move_to(dc, 2, 2, None), arc_to(dc, 10, 10, 50, 35, 50, 20, 10, 12), line_to(dc, 2, 2)),
            lambda: rectangle(dc, 8, 8, 40, 30),
        )
        for shape in shapes:
            save_dc(dc)
            begin_path(dc)
            shape()
            end_path(dc)
            widen_path(dc)
            select_clip_path(dc, 5)
            polyline(dc, *points((0, 0), (90, 0), (90, 90), (0, 90), (0, 0)))
            restore_dc(dc, -1)
        brush = LogBrush(0, 0, 0)
        for style in (0x00010000 | 0x0200 | 0x2000, 0x00010000 | 0x0100 | 0x1000):
            select(dc, ext_create_pen(style, 7, ctypes.byref(brush), 0, None))
            save_dc(dc)
            begin_path(dc)
            move_to(dc, 10, 10, None)
            line_to(dc, 40, 15)
            line_to(dc, 20, 35)
            end_path(dc)
            widen_path(dc)
            select_clip_path(dc, 5)
            polyline(dc, *points((0, 0), (90, 0), (90, 90), (0, 90), (0, 0)))
            restore_dc(dc, -1)

    yield "clip-path-widened-shapes", None, clip_path_widened_shapes

    def clip_path_inside_frame(dc):
        # SelectClipPath of paths built and widened with inside-frame pens,
        # and of unwidened paths built with inside-frame and mitred pens.
        frame = points((-60, -60), (120, -60), (120, 120), (-60, 120), (-60, -60))
        brush = LogBrush(0, 0, 0)
        pens = (
            lambda: create_pen(6, 7, 0),
            lambda: ext_create_pen(0x00010000 | 0x2000 | 6, 7, ctypes.byref(brush), 0, None),
        )
        shapes = (
            lambda: (move_to(dc, 10, 10, None), line_to(dc, 40, 15), line_to(dc, 20, 35)),
            lambda: (move_to(dc, 10, 10, None), line_to(dc, 40, 15), line_to(dc, 20, 35), close_figure(dc)),
            lambda: rectangle(dc, 8, 8, 40, 30),
            lambda: ellipse(dc, 5, 5, 40, 30),
            lambda: round_rect(dc, 6, 4, 41, 33, 12, 9),
            lambda: pie(dc, 5, 5, 41, 31, 40, 5, 5, 6),
            lambda: rectangle(dc, 8, 8, 13, 30),
            lambda: ellipse(dc, 8, 8, 13, 30),
            lambda: pie(dc, 8, 8, 13, 30, 13, 8, 8, 20),
            lambda: chord(dc, 3, 7, 44, 30, 2, 30, 44, 8),
            lambda: (move_to(dc, 2, 2, None), arc_to(dc, 10, 10, 50, 35, 50, 20, 10, 12), line_to(dc, 2, 2)),
            lambda: (arc(dc, 5, 5, 45, 35, 45, 10, 5, 30), close_figure(dc)),
        )

        def clipped(shape, widen=True):
            save_dc(dc)
            begin_path(dc)
            shape()
            end_path(dc)
            if widen:
                widen_path(dc)
            select_clip_path(dc, 5)
            polyline(dc, *frame)
            restore_dc(dc, -1)

        for pen in pens:
            select(dc, pen())
            for shape in shapes:
                clipped(shape)
            clipped(shapes[0], widen=False)
            clipped(shapes[2], widen=False)
            select(dc, stock(7))
        select(dc, ext_create_pen(0x00010000 | 0x2000, 7, ctypes.byref(brush), 0, None))
        clipped(shapes[0], widen=False)
        select(dc, stock(7))
        # Scaled, then rotated, inside-frame pens.
        select(dc, create_pen(6, 5, 0))
        save_dc(dc)
        set_map_mode(dc, 8)
        set_window_ext(dc, 10, 10, None)
        set_viewport_ext(dc, 15, 20, None)
        clipped(shapes[2])
        clipped(shapes[3])
        restore_dc(dc, -1)
        set_graphics_mode(dc, 2)
        set_world_transform(dc, ctypes.byref(XForm(0.9, 0.4, -0.4, 0.9, 20, 0)))
        clipped(shapes[2])
        clipped(shapes[3])
        clipped(shapes[0])

    yield "clip-path-inside-frame", None, clip_path_inside_frame

    def arc_to_inside_frame(dc):
        # ArcTo with an inside-frame pen: clip paths and current positions,
        # counterclockwise and clockwise, in a covered box, and in GM_ADVANCED.
        frame = points((-60, -60), (120, -60), (120, 120), (-60, 120), (-60, -60))
        select(dc, create_pen(6, 7, 0))
        boxes = ((10, 10, 50, 35, 50, 20, 10, 12), (10, 10, 15, 35, 15, 20, 10, 12))

        def run():
            for box in boxes:
                save_dc(dc)
                begin_path(dc)
                move_to(dc, 2, 2, None)
                arc_to(dc, *box)
                line_to(dc, 2, 2)
                end_path(dc)
                select_clip_path(dc, 5)
                polyline(dc, *frame)
                restore_dc(dc, -1)
                move_to(dc, 0, 0, None)
                arc_to(dc, *box)
                polyline_to(dc, *points((300, 300)))

        for direction in (1, 2):
            set_arc_direction(dc, direction)
            run()
        set_arc_direction(dc, 1)
        set_graphics_mode(dc, 2)
        run()
        set_world_transform(dc, ctypes.byref(XForm(0.9, 0.4, -0.4, 0.9, 20, 0)))
        run()

    yield "arc-to-inside-frame", None, arc_to_inside_frame

    def odd_arc_to(dc):
        # The clockwise ArcTo on an odd-sized box, then its current position.
        set_arc_direction(dc, 2)
        for box, radials in (((10, 10, 41, 31), (40, 10, 10, 30)), ((10, 10, 41, 31), (10, 30, 40, 10))):
            move_to(dc, 0, 0, None)
            arc_to(dc, *box, *radials)
            polyline_to(dc, *points((300, 300)))

    yield "odd-arc-to", None, odd_arc_to

    def path_readback(dc):
        # GetPath after building and widening the ArcTo figure, and the
        # current position after each odd ArcTo, written into GDI comments.
        api("GdiComment", boolean, ptr, wintypes.UINT, ctypes.c_char_p)
        api("GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)
        api("GetCurrentPositionEx", boolean, ptr, ctypes.POINTER(wintypes.POINT))

        def comment_path():
            count = gdi.GetPath(dc, None, None, 0)
            pts, kinds = (wintypes.POINT * max(count, 1))(), (ctypes.c_ubyte * max(count, 1))()
            gdi.GetPath(dc, pts, kinds, count)
            data = b"PATH" + b"".join(
                struct.pack("<iiB", p.x, p.y, k) for p, k in zip(pts[:count], kinds[:count], strict=True)
            )
            gdi.GdiComment(dc, len(data), data)

        select(dc, create_pen(0, 80, 0))  # Five device pixels once mapped.
        set_map_mode(dc, 8)  # Read the path back in sixteenths of a pixel.
        set_window_ext(dc, 16, 16, None)
        set_viewport_ext(dc, 1, 1, None)
        begin_path(dc)
        move_to(dc, 32, 32, None)
        arc_to(dc, 160, 160, 800, 560, 800, 320, 160, 192)
        line_to(dc, 32, 32)
        end_path(dc)
        comment_path()
        widen_path(dc)
        comment_path()
        abort_path(dc)
        set_arc_direction(dc, 2)
        for box, radials in (((10, 10, 41, 31), (40, 10, 10, 30)), ((10, 10, 41, 31), (10, 30, 40, 10))):
            begin_path(dc)
            move_to(dc, 0, 0, None)
            arc_to(dc, *(16 * value for value in (*box, *radials)))
            end_path(dc)
            comment_path()
            abort_path(dc)
        set_arc_direction(dc, 1)
        set_map_mode(dc, 1)
        set_arc_direction(dc, 2)
        for box, radials in (((10, 10, 41, 31), (40, 10, 10, 30)), ((10, 10, 41, 31), (10, 30, 40, 10))):
            move_to(dc, 0, 0, None)
            arc_to(dc, *box, *radials)
            point = wintypes.POINT()
            gdi.GetCurrentPositionEx(dc, ctypes.byref(point))
            data = b"CPOS" + struct.pack("<ii", point.x, point.y)
            gdi.GdiComment(dc, len(data), data)

    yield "path-readback", None, path_readback

    def inside_frame_readback(dc):
        # GetPath of curves built, then widened, with inside-frame and mitred
        # pens, in sixteenths of a pixel, written into GDI comments.
        api("GdiComment", boolean, ptr, wintypes.UINT, ctypes.c_char_p)
        api("GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)

        def comment_path():
            count = gdi.GetPath(dc, None, None, 0)
            pts, kinds = (wintypes.POINT * max(count, 1))(), (ctypes.c_ubyte * max(count, 1))()
            gdi.GetPath(dc, pts, kinds, count)
            data = b"PATH" + b"".join(
                struct.pack("<iiB", p.x, p.y, k) for p, k in zip(pts[:count], kinds[:count], strict=True)
            )
            gdi.GdiComment(dc, len(data), data)

        set_map_mode(dc, 8)
        set_window_ext(dc, 16, 16, None)
        set_viewport_ext(dc, 1, 1, None)
        brush = LogBrush(0, 0, 0)
        pens = (
            lambda: ext_create_pen(0x00010000 | 0x2000 | 6, 112, ctypes.byref(brush), 0, None),
            lambda: ext_create_pen(0x00010000 | 0x2000, 112, ctypes.byref(brush), 0, None),
            lambda: create_pen(6, 112, 0),
        )
        shapes = (
            lambda: ellipse(dc, 80, 80, 640, 480),
            lambda: pie(dc, 80, 80, 656, 496, 640, 80, 80, 96),
        )
        for pen in pens:
            select(dc, pen())
            for shape in shapes:
                begin_path(dc)
                shape()
                end_path(dc)
                comment_path()
                widen_path(dc)
                comment_path()
                abort_path(dc)
            select(dc, stock(7))

    yield "inside-frame-readback", None, inside_frame_readback

    def dashed_readback(dc):
        # GetPath of styled geometric pens widened along curves and lines, in
        # sixteenths of a pixel, written into GDI comments.
        api("GdiComment", boolean, ptr, wintypes.UINT, ctypes.c_char_p)
        api("GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)

        def comment_path():
            count = gdi.GetPath(dc, None, None, 0)
            pts, kinds = (wintypes.POINT * max(count, 1))(), (ctypes.c_ubyte * max(count, 1))()
            gdi.GetPath(dc, pts, kinds, count)
            data = b"PATH" + b"".join(
                struct.pack("<iiB", p.x, p.y, k) for p, k in zip(pts[:count], kinds[:count], strict=True)
            )
            gdi.GdiComment(dc, len(data), data)

        set_map_mode(dc, 8)
        set_window_ext(dc, 16, 16, None)
        set_viewport_ext(dc, 1, 1, None)
        brush = LogBrush(0, 0, 0)
        user = (wintypes.DWORD * 4)(14 * 16, 4 * 16, 6 * 16, 4 * 16)
        pens = (
            lambda: ext_create_pen(0x00010000 | 0x2000 | 0x0200 | 1, 64, ctypes.byref(brush), 0, None),
            lambda: ext_create_pen(0x00010000 | 0x2000 | 0x0200 | 7, 64, ctypes.byref(brush), 4, user),
        )
        shapes = (
            lambda: ellipse(dc, 64, 64, 480, 352),
            lambda: (move_to(dc, 32, 928, None), poly_bezier_to(dc, *points((128, 640), (384, 1120), (384, 768)))),
            lambda: (move_to(dc, 32, 32, None), line_to(dc, 400, 96), line_to(dc, 160, 320)),
        )
        for pen in pens:
            select(dc, pen())
            for shape in shapes:
                begin_path(dc)
                shape()
                end_path(dc)
                flatten_path(dc)
                comment_path()
                widen_path(dc)
                comment_path()
                abort_path(dc)
                # The same figure widened along its curves.
                begin_path(dc)
                shape()
                end_path(dc)
                comment_path()
                widen_path(dc)
                comment_path()
                abort_path(dc)
            select(dc, stock(7))

    yield "dashed-readback", None, dashed_readback


text_out_a = api("TextOutA", boolean, ptr, integer, integer, ctypes.c_char_p, integer)
ext_text_out_a = api(
    "ExtTextOutA", boolean, ptr, integer, integer, wintypes.UINT, ptr, ctypes.c_char_p, wintypes.UINT, ptr
)
ext_text_out_w = api("ExtTextOutW", boolean, ptr, integer, integer, wintypes.UINT, ptr, ptr, wintypes.UINT, ptr)
poly_text_out_w = api("PolyTextOutW", boolean, ptr, ptr, integer)
set_text_align = api("SetTextAlign", wintypes.UINT, ptr, wintypes.UINT)
set_text_extra = api("SetTextCharacterExtra", integer, ptr, integer)
set_text_justification = api("SetTextJustification", boolean, ptr, integer, integer)
TEXT_FACE = "Pillow WMF Test"
FONTS = sorted((Path(__file__).resolve().parents[1] / "test/fonts").glob("*.ttf"))


def wide(dc, x, y, text, options=0, rect=None, dx=None, glyphs=False):
    """ExtTextOutW of a string, or of glyph indices when ``glyphs``."""
    units = list(text) if glyphs else [ord(c) for c in text]
    buffer = (ctypes.c_ushort * max(1, len(units)))(*units)
    advances = (integer * len(dx))(*dx) if dx else None
    box = wintypes.RECT(*rect) if rect else None
    return ext_text_out_w(dc, x, y, options, ctypes.byref(box) if box else None, buffer, len(units), advances)


def text_font(dc, height=-12, face=TEXT_FACE, **fields):
    values = dict(escapement=0, orientation=0, weight=400, italic=0, underline=0, strikeout=0, charset=0)
    values.update(fields)
    font = create_font_indirect(
        ctypes.byref(
            LogFontW(
                height,
                0,
                values["escapement"],
                values["orientation"],
                values["weight"],
                values["italic"],
                values["underline"],
                values["strikeout"],
                values["charset"],
                0,
                0,
                3,
                0,
                face,
            )
        )
    )
    select(dc, font)
    return font


def text_scenarios():
    def text_calls(dc):
        text_font(dc)
        text_out_a(dc, 10, 20, b"AB A", 4)
        ext_text_out_a(dc, 10, 40, 0, None, b"BA", 2, None)
        wide(dc, 10, 60, "AB")
        wide(dc, 60, 60, "A B", dx=(7, 3, 9))
        wide(dc, 60, 80, (1, 2), glyphs=True, options=0x10)
        text_out_a(dc, 0, 0, b"", 0)

    yield "text-calls", None, text_calls

    def text_options(dc):
        text_font(dc)
        set_bk_mode(dc, 2)
        set_bk_color(dc, 0x00C0E0F0)
        wide(dc, 10, 20, "AB", options=2, rect=(8, 18, 40, 36))
        wide(dc, 10, 40, "BA", options=4, rect=(8, 38, 20, 50))
        wide(dc, 10, 60, "A", options=6, rect=(30, 58, 20, 70))
        set_bk_mode(dc, 1)
        wide(dc, 50, 20, "AB", options=0x2000, dx=(6, 2, 8, -3))
        wide(dc, 50, 40, "", options=2, rect=(50, 40, 60, 48))

    yield "text-options", None, text_options

    def text_alignment(dc):
        text_font(dc)
        for index, align in enumerate((6, 2, 8, 24, 0x0E)):
            set_text_align(dc, align)
            wide(dc, 64, 12 + 16 * index, "AB A")
        set_text_align(dc, 1)
        move_to(dc, 10, 100, None)
        wide(dc, 0, 0, "AB")
        wide(dc, 0, 0, "B")
        line_to(dc, 90, 120)
        set_text_align(dc, 0)
        set_text_extra(dc, 3)
        wide(dc, 10, 110, "AB")
        set_text_extra(dc, 0)
        set_text_justification(dc, 6, 1)
        wide(dc, 60, 110, "A A")

    yield "text-alignment", None, text_alignment

    def text_mapping(dc):
        set_map_mode(dc, 8)
        set_window_ext(dc, 200, 200, None)
        set_viewport_ext(dc, 128, 100, None)
        text_font(dc, -20)
        text_out_a(dc, 10, 20, b"AB A", 4)
        wide(dc, 10, 60, "BA", dx=(13, 9))
        wide(dc, 10, 100, "AB", options=2, rect=(8, 98, 60, 130))
        text_font(dc, 16, face="Pillow WMF Encoding")
        text_out_a(dc, 10, 140, b"A\xe9B", 3)

    yield "text-mapping", None, text_mapping

    def text_advanced(dc):
        set_graphics_mode(dc, 2)
        set_world_transform(dc, ctypes.byref(XForm(0.9, 0.4, -0.4, 0.9, 30.0, 10.0)))
        text_font(dc, -10)
        wide(dc, 0, 0, "AB A")
        set_bk_mode(dc, 2)
        wide(dc, 0, 20, "BA")
        set_world_transform(dc, ctypes.byref(XForm(1.5, 0.0, 0.0, 0.75, 0.0, 60.0)))
        wide(dc, 4, 4, "AB", dx=(9, 7))
        set_graphics_mode(dc, 1)
        set_world_transform(dc, ctypes.byref(XForm(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)))
        text_font(dc, -12, escapement=300, orientation=300, underline=1)
        wide(dc, 20, 110, "AB A")

    yield "text-advanced", None, text_advanced


def records(data):
    position = 0
    while position < len(data):
        kind, size = struct.unpack_from("<II", data, position)
        yield kind, size, data[position + 8 : position + size]
        position += size


def main():
    print(f"Windows EMF recording probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    for name, frame, draw in (*scenarios(), *more_scenarios(), *gap_scenarios(), *text_scenarios()):
        with private_fonts(FONTS), reference_surface(128, 128) as (_, reference, _bits):
            rect = wintypes.RECT(*frame) if frame else None
            dc = create_emf(reference, None, ctypes.byref(rect) if rect else None, None)
            result = draw(dc)
            metafile = close_emf(dc)
        size = get_bits(metafile, 0, None)
        buffer = ctypes.create_string_buffer(size)
        get_bits(metafile, size, buffer)
        delete_emf(metafile)
        print(f"\n[{name}] frame={frame} result={result!r}")
        for kind, length, payload in records(buffer.raw):
            print(f"  type={kind} size={length} payload={payload.hex()}")


if __name__ == "__main__":
    main()
