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


def records(data):
    position = 0
    while position < len(data):
        kind, size = struct.unpack_from("<II", data, position)
        yield kind, size, data[position + 8 : position + size]
        position += size


def main():
    print(f"Windows EMF recording probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    for name, frame, draw in scenarios():
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
