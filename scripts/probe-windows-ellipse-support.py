"""Native centreline, flattening and widening for two corpus ellipse strokes."""

import ctypes
from ctypes import wintypes

from windows_wmf_render import bind, check, reference_surface


def main():
    profiles = (
        ("switch", 96, (-1008, -854), (2021, 2092), (-905, -726, 921, 1111)),
        ("nopark", 79, (-1003, -931), (1987, 2078), (-961, -889, 940, 1107)),
    )
    for label, width, origin, window, box in profiles:
        for stage in ("curves", "flat", "wide", "pen"):
            with reference_surface(128, 128) as (gdi, dc, _bits):
                ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
                for name in ("BeginPath", "EndPath", "FlattenPath", "WidenPath"):
                    bind(gdi, name, boolean, ptr)
                bind(gdi, "Ellipse", boolean, ptr, integer, integer, integer, integer)
                bind(gdi, "SetWindowOrgEx", boolean, ptr, integer, integer, ptr)
                bind(gdi, "MoveToEx", boolean, ptr, integer, integer, ptr)
                bind(gdi, "LineTo", boolean, ptr, integer, integer)
                bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
                bind(gdi, "GetStockObject", ptr, integer)
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
                old_pen = check(gdi.SelectObject(dc, pen), "SelectObject")
                old_brush = check(gdi.SelectObject(dc, check(gdi.GetStockObject(5), "NULL_BRUSH")), "SelectObject")
                try:
                    check(gdi.BeginPath(dc), "BeginPath")
                    if stage == "pen":
                        check(gdi.MoveToEx(dc, *origin, None), "MoveToEx")
                        check(gdi.LineTo(dc, *origin), "LineTo")
                    else:
                        check(gdi.Ellipse(dc, *box), "Ellipse")
                    check(gdi.EndPath(dc), "EndPath")
                    if stage == "flat":
                        check(gdi.FlattenPath(dc), "FlattenPath")
                    elif stage in ("wide", "pen"):
                        check(gdi.WidenPath(dc), "WidenPath")
                    check(gdi.SetWindowOrgEx(dc, 0, 0, None), "SetWindowOrgEx")
                    check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                    count = gdi.GetPath(dc, None, None, 0)
                    if count < 0:
                        raise RuntimeError("GetPath failed")
                    points = (wintypes.POINT * count)()
                    kinds = (ctypes.c_ubyte * count)()
                    assert gdi.GetPath(dc, points, kinds, count) == count
                    print(label, stage, [(p.x, p.y, k) for p, k in zip(points, kinds, strict=True)], flush=True)
                finally:
                    gdi.SelectObject(dc, old_brush)
                    gdi.SelectObject(dc, old_pen)
                    gdi.DeleteObject(pen)


if __name__ == "__main__":
    main()
