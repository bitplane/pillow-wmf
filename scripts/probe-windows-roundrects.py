"""Capture native RoundRect controls before reconstructing corner geometry."""

import ctypes
from ctypes import wintypes
from itertools import product

from windows_wmf_render import bind, check, reference_surface


def main():
    with reference_surface(128, 128) as (gdi, dc, _bits):
        ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
        for name in ("BeginPath", "EndPath", "AbortPath"):
            bind(gdi, name, boolean, ptr)
        bind(gdi, "RoundRect", boolean, ptr, *([integer] * 6))
        bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
        bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)
        for style, width in ((0, 1), (0, 7), (5, 1)):
            pen = check(gdi.CreatePen(style, width, 0), "CreatePen")
            old = check(gdi.SelectObject(dc, pen), "SelectObject")
            try:
                for box, size in product(
                    ((8, 16, 120, 112), (5, 6, 26, 28)),
                    ((17, 29), (0, 0), (0, 12), (1, 1), (2, 2), (3, 5), (21, 22), (200, 200), (-17, 29)),
                ):
                    check(gdi.BeginPath(dc), "BeginPath")
                    check(gdi.RoundRect(dc, *box, *size), "RoundRect")
                    check(gdi.EndPath(dc), "EndPath")
                    check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                    count = gdi.GetPath(dc, None, None, 0)
                    assert count >= 0
                    points = (wintypes.POINT * count)()
                    kinds = (ctypes.c_ubyte * count)()
                    assert gdi.GetPath(dc, points, kinds, count) == count
                    print(
                        "RoundRect",
                        style,
                        width,
                        box,
                        size,
                        tuple((p.x, p.y, k) for p, k in zip(points, kinds, strict=True)),
                    )
                    check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")
                    check(gdi.AbortPath(dc), "AbortPath")
            finally:
                gdi.SelectObject(dc, old)
                gdi.DeleteObject(pen)


if __name__ == "__main__":
    main()
