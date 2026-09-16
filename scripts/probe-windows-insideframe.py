"""Native inside-frame geometry, including overlarge widths and mapping."""

import ctypes
from ctypes import wintypes
from itertools import product

from windows_wmf_render import bind, check, reference_surface


def main():
    with reference_surface(128, 128) as (gdi, dc, _bits):
        ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
        for name in ("BeginPath", "EndPath", "AbortPath"):
            bind(gdi, name, boolean, ptr)
        for name, count in (("Rectangle", 4), ("Ellipse", 4), ("RoundRect", 6), ("Arc", 8), ("Chord", 8), ("Pie", 8)):
            bind(gdi, name, boolean, ptr, *([integer] * count))
        bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
        bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)
        for width, scale in product((0, 1, 2, 3, 4, 7, 20, 40), ((1, 1), (2, 1))):
            pen = check(gdi.CreatePen(6, width, 0), "CreatePen")
            old = check(gdi.SelectObject(dc, pen), "SelectObject")
            try:
                for operation in ("Rectangle", "Ellipse", "RoundRect", "Arc", "Chord", "Pie"):
                    check(gdi.SetViewportExtEx(dc, 128 * scale[0], 128 * scale[1], None), "SetViewportExtEx")
                    args = (5, 6, 26, 43)
                    if operation == "RoundRect":
                        args += (13, 19)
                    elif operation in ("Arc", "Chord", "Pie"):
                        args += (35, 16, -5, 34)
                    check(gdi.BeginPath(dc), "BeginPath")
                    check(getattr(gdi, operation)(dc, *args), operation)
                    check(gdi.EndPath(dc), "EndPath")
                    check(gdi.SetViewportExtEx(dc, 128, 128, None), "SetViewportExtEx")
                    check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                    count = gdi.GetPath(dc, None, None, 0)
                    assert count >= 0
                    points = (wintypes.POINT * count)()
                    kinds = (ctypes.c_ubyte * count)()
                    assert gdi.GetPath(dc, points, kinds, count) == count
                    print(operation, width, scale, tuple((p.x, p.y, k) for p, k in zip(points, kinds, strict=True)))
                    check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")
                    check(gdi.AbortPath(dc), "AbortPath")
            finally:
                gdi.SelectObject(dc, old)
                gdi.DeleteObject(pen)


if __name__ == "__main__":
    main()
