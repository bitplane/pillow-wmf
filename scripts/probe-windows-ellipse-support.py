"""Native ellipse paths and cubic flattening across the 32/64-bit boundary."""

import ctypes
from ctypes import wintypes

from windows_wmf_render import bind, check, reference_surface


def probe_cubic_range():
    # Controls are expressed directly in 28.4 units. Native BEZIER32 accepts
    # a bounding-box span below 16384 on both axes; larger spans use BEZIER64.
    for span in (16368, 16384, 16400, 65536):
        control = ((0, 0), (span, 731), (span // 3, 1199), (span - 37, 1777))
        for swap in (False, True):
            points_in = tuple((y, x) if swap else (x, y) for x, y in control)
            with reference_surface(128, 128) as (gdi, dc, _bits):
                ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
                for name in ("BeginPath", "EndPath", "FlattenPath"):
                    bind(gdi, name, boolean, ptr)
                bind(gdi, "PolyBezier", boolean, ptr, ctypes.POINTER(wintypes.POINT), wintypes.DWORD)
                bind(
                    gdi,
                    "GetPath",
                    integer,
                    ptr,
                    ctypes.POINTER(wintypes.POINT),
                    ctypes.POINTER(ctypes.c_ubyte),
                    integer,
                )
                check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                check(gdi.BeginPath(dc), "BeginPath")
                check(
                    gdi.PolyBezier(dc, (wintypes.POINT * 4)(*(wintypes.POINT(*p) for p in points_in)), 4), "PolyBezier"
                )
                check(gdi.EndPath(dc), "EndPath")
                stored = (wintypes.POINT * 4)()
                stored_kinds = (ctypes.c_ubyte * 4)()
                assert gdi.GetPath(dc, stored, stored_kinds, 4) == 4
                points_in = tuple((p.x, p.y) for p in stored)
                check(gdi.FlattenPath(dc), "FlattenPath")
                count = gdi.GetPath(dc, None, None, 0)
                if count < 0:
                    raise RuntimeError("GetPath failed")
                points = (wintypes.POINT * count)()
                kinds = (ctypes.c_ubyte * count)()
                assert gdi.GetPath(dc, points, kinds, count) == count
                print("cubic-range", span, swap, points_in, [(p.x, p.y) for p in points], flush=True)


def main():
    probe_cubic_range()
    profiles = (
        ("switch", (128, 128), 96, (-1008, -854), (2021, 2092), (-905, -726, 921, 1111)),
        ("nopark", (128, 128), 79, (-1003, -931), (1987, 2078), (-961, -889, 940, 1107)),
        ("nopark-odd", (257, 193), 79, (-1003, -931), (1987, 2078), (-961, -889, 940, 1107)),
    )
    for label, surface, width, origin, window, box in profiles:
        for stage in ("curves", "flat", "wide", "pen"):
            with reference_surface(*surface) as (gdi, dc, _bits):
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
                    check(gdi.SetWindowExtEx(dc, surface[0] * 16, surface[1] * 16, None), "SetWindowExtEx")
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
