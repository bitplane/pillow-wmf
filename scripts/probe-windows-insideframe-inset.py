"""Measure coin-scale inside-frame bounds and pen contours in device sixteenths."""

import ctypes
from ctypes import wintypes

from windows_wmf_render import bind, check, reference_surface


def main():
    profiles = (
        ("penny", 48, (-1114, -917), (2232, 2218), (-1058, -877, 1092, 1279)),
        ("quarter", 48, (-1104, -917), (2213, 2223), (-1070, -871, 1080, 1279)),
        ("nickel", 48, (-1099, -917), (2203, 2218), (-1065, -873, 1079, 1277)),
        ("dime", 80, (-1147, -955), (2299, 2299), (-1104, -889, 1106, 1299)),
    )
    for label, width, origin, window, box in profiles:
        for operation in ("Ellipse", "Rectangle", "pen"):
            with reference_surface(128, 128) as (gdi, dc, _bits):
                ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
                for name in ("BeginPath", "EndPath", "WidenPath"):
                    bind(gdi, name, boolean, ptr)
                for name in ("Ellipse", "Rectangle"):
                    bind(gdi, name, boolean, ptr, integer, integer, integer, integer)
                bind(gdi, "MoveToEx", boolean, ptr, integer, integer, ptr)
                bind(gdi, "LineTo", boolean, ptr, integer, integer)
                bind(gdi, "SetWindowOrgEx", boolean, ptr, integer, integer, ptr)
                bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
                bind(
                    gdi,
                    "GetPath",
                    integer,
                    ptr,
                    ctypes.POINTER(wintypes.POINT),
                    ctypes.POINTER(ctypes.c_ubyte),
                    integer,
                )
                check(gdi.SetWindowExtEx(dc, *window, None), "SetWindowExtEx")
                check(gdi.SetWindowOrgEx(dc, *origin, None), "SetWindowOrgEx")
                pen = check(gdi.CreatePen(6, width, 0), "CreatePen")
                old = check(gdi.SelectObject(dc, pen), "SelectObject")
                try:
                    check(gdi.BeginPath(dc), "BeginPath")
                    if operation == "pen":
                        check(gdi.MoveToEx(dc, *origin, None), "MoveToEx")
                        check(gdi.LineTo(dc, *origin), "LineTo")
                    else:
                        check(getattr(gdi, operation)(dc, *box), operation)
                    check(gdi.EndPath(dc), "EndPath")
                    if operation == "pen":
                        check(gdi.WidenPath(dc), "WidenPath")
                    check(gdi.SetWindowOrgEx(dc, 0, 0, None), "SetWindowOrgEx")
                    check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                    count = gdi.GetPath(dc, None, None, 0)
                    if count < 0:
                        raise RuntimeError("GetPath failed")
                    points = (wintypes.POINT * count)()
                    kinds = (ctypes.c_ubyte * count)()
                    assert gdi.GetPath(dc, points, kinds, count) == count
                    print(label, operation, [(p.x, p.y, k) for p, k in zip(points, kinds, strict=True)], flush=True)
                finally:
                    gdi.SelectObject(dc, old)
                    gdi.DeleteObject(pen)


if __name__ == "__main__":
    main()
