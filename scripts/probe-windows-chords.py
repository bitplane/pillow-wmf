"""Measure Chord path construction independently of the local rasterizer."""

import ctypes
from ctypes import wintypes

from windows_wmf_render import bind, check, reference_surface


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


if __name__ == "__main__":
    main()
