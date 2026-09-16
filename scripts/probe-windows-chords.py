"""Measure Chord path construction independently of the local rasterizer."""

import ctypes
from ctypes import wintypes

from windows_wmf_render import bind, check, reference_surface

from pillow_wmf import RasterContext
from pillow_wmf.geometry import DevicePath


def verify_dash_phase(gdi, dc, bits):
    """Independent fractional polylines distinguish open and closed starts."""
    ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
    bind(gdi, "MoveToEx", boolean, ptr, integer, integer, ptr)
    bind(gdi, "LineTo", boolean, ptr, integer, integer)
    bind(gdi, "CloseFigure", boolean, ptr)
    bind(gdi, "StrokePath", boolean, ptr)
    bind(gdi, "GdiFlush", boolean)
    bind(gdi, "SetGraphicsMode", integer, ptr, integer)
    check(gdi.SetGraphicsMode(dc, 2), "SetGraphicsMode")
    pen = check(gdi.CreatePen(1, 1, 0), "CreatePen")
    old = check(gdi.SelectObject(dc, pen), "SelectObject")
    failures = tested = 0
    try:
        for fx, fy in ((0, 0), (1, 7), (7, 1), (8, 8), (9, 15), (15, 9)):
            for reverse in (False, True):
                for closed in (False, True):
                    points = ((512 + fx, 512 + fy), (1001, 287), (1389, 1271))
                    if reverse:
                        points = points[::-1]
                    check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                    check(gdi.BeginPath(dc), "BeginPath")
                    check(gdi.MoveToEx(dc, *points[0], None), "MoveToEx")
                    for point in points[1:]:
                        check(gdi.LineTo(dc, *point), "LineTo")
                    if closed:
                        check(gdi.CloseFigure(dc), "CloseFigure")
                    check(gdi.EndPath(dc), "EndPath")
                    check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")
                    ctypes.memset(bits, 255, 128 * 128 * 4)
                    check(gdi.StrokePath(dc), "StrokePath")
                    check(gdi.GdiFlush(), "GdiFlush")
                    native = ctypes.string_at(bits, 128 * 128 * 4)[::4]
                    context = RasterContext(128, 128)
                    context.select_object(context.create_pen(1, 1, 0))
                    context._stroke_path(DevicePath.polyline(points, closed=closed))
                    actual = context.image.convert("L").tobytes()
                    differing = sum(a != b for a, b in zip(actual, native, strict=True))
                    tested += 1
                    if differing:
                        failures += 1
                        print("dash-phase-FAIL", points, closed, differing)
        print("dash-phase-matrix", tested, failures)
        assert not failures
    finally:
        gdi.SelectObject(dc, old)
        gdi.DeleteObject(pen)
        check(gdi.SetGraphicsMode(dc, 1), "SetGraphicsMode")


def main():
    with reference_surface(128, 128) as (gdi, dc, bits):
        ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
        for name in ("BeginPath", "EndPath", "AbortPath", "FlattenPath"):
            bind(gdi, name, boolean, ptr)
        for name in ("Chord", "Arc"):
            bind(gdi, name, boolean, ptr, *([integer] * 8))
        bind(gdi, "Ellipse", boolean, ptr, *([integer] * 4))
        bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)
        bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
        bind(gdi, "GetObjectW", integer, ptr, integer, ptr)
        bind(gdi, "GetCurrentObject", ptr, ptr, wintypes.UINT)
        stock = (ctypes.c_int * 4)()
        check(gdi.GetObjectW(gdi.GetCurrentObject(dc, 1), ctypes.sizeof(stock), stock), "GetObjectW")
        print("default-pen", tuple(stock))
        for style, width in ((0, 1), (1, 1), (5, 0), (5, 1), (5, 7)):
            pen = check(gdi.CreatePen(style, width, 0), "CreatePen")
            old = check(gdi.SelectObject(dc, pen), "SelectObject")
            try:
                for args in (
                    (8, 16, 120, 112, 120, 64, 120, 64),
                    (8, 16, 120, 112, 120, 64, 176, 64),
                    (5, 6, 28, 27, 36, 16, 36, -4),
                    (8, 16, 120, 112, 117, 43, 31, 107),
                    (25, 3, 78, 64, 90, 30, 30, 80),
                ):
                    for operation in ("Arc", "Chord", "Ellipse"):
                        check(gdi.BeginPath(dc), "BeginPath")
                        check(getattr(gdi, operation)(dc, *(args[:4] if operation == "Ellipse" else args)), operation)
                        check(gdi.EndPath(dc), "EndPath")
                        check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                        count = gdi.GetPath(dc, None, None, 0)
                        assert count > 0
                        points = (wintypes.POINT * count)()
                        kinds = (ctypes.c_ubyte * count)()
                        assert gdi.GetPath(dc, points, kinds, count) == count
                        print(
                            operation,
                            style,
                            width,
                            args,
                            tuple((p.x, p.y, k) for p, k in zip(points, kinds, strict=True)),
                        )
                        check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")
                        check(gdi.AbortPath(dc), "AbortPath")
            finally:
                gdi.SelectObject(dc, old)
                gdi.DeleteObject(pen)
        verify_dash_phase(gdi, dc, bits)


if __name__ == "__main__":
    main()
