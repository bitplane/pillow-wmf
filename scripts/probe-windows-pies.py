"""Capture native Pie paths, including centre placement and closure order."""

import ctypes
from ctypes import wintypes

from windows_wmf_render import bind, check, reference_surface


def main():
    with reference_surface(128, 128) as (gdi, dc, _bits):
        ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
        for name in ("BeginPath", "EndPath", "AbortPath"):
            bind(gdi, name, boolean, ptr)
        bind(gdi, "Pie", boolean, ptr, *([integer] * 8))
        bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
        bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)
        for style, width in ((0, 1), (0, 7), (1, 1), (5, 1)):
            pen = check(gdi.CreatePen(style, width, 0), "CreatePen")
            old = check(gdi.SelectObject(dc, pen), "SelectObject")
            try:
                for args in (
                    (8, 16, 120, 112, 120, 64, 120, 64),
                    (8, 16, 120, 112, 120, 64, 176, 64),
                    (5, 6, 28, 27, 36, 16, 36, -4),
                    (8, 16, 120, 112, 117, 43, 31, 107),
                    (25, 3, 78, 64, 90, 30, 30, 80),
                    (60, 8, 63, 120, 100, 30, 20, 80),
                ):
                    check(gdi.BeginPath(dc), "BeginPath")
                    check(gdi.Pie(dc, *args), "Pie")
                    check(gdi.EndPath(dc), "EndPath")
                    check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                    count = gdi.GetPath(dc, None, None, 0)
                    assert count > 0
                    points = (wintypes.POINT * count)()
                    kinds = (ctypes.c_ubyte * count)()
                    assert gdi.GetPath(dc, points, kinds, count) == count
                    print("Pie", style, width, args, tuple((p.x, p.y, k) for p, k in zip(points, kinds, strict=True)))
                    check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")
                    check(gdi.AbortPath(dc), "AbortPath")
            finally:
                gdi.SelectObject(dc, old)
                gdi.DeleteObject(pen)


if __name__ == "__main__":
    main()
