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

from windows_wmf_render import bind, module_versions, reference_surface

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


def records(data):
    position = 0
    while position < len(data):
        kind, size = struct.unpack_from("<II", data, position)
        yield kind, size, data[position + 8 : position + size]
        position += size


def main():
    print(f"Windows EMF recording probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    for name, frame, draw in (*scenarios(), *more_scenarios()):
        with reference_surface(128, 128) as (_, reference, _bits):
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
