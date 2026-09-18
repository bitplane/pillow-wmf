"""Native paths for the screwdrv polygon and its flattened anisotropic pen."""

import ctypes
from ctypes import wintypes

from windows_wmf_render import bind, check, reference_surface


POLYGON = (
    (1602, 2641),
    (1631, 2648),
    (1671, 2656),
    (1702, 2658),
    (1732, 2656),
    (1767, 2649),
    (1792, 2645),
    (1808, 2661),
    (1823, 2677),
    (1831, 2694),
    (1831, 2760),
    (1787, 2777),
    (1745, 2784),
    (1657, 2784),
    (1610, 2777),
    (1569, 2758),
    (1569, 2693),
    (1576, 2677),
    (1588, 2661),
    (1602, 2641),
)


def main():
    profiles = [(6, 324, y) for y in (1920, 2038, 2048, 2050, 2112)]
    profiles += [(0, x, y) for x in (324, 128, 32, -128) for y in (8192, 4096, 2048, 1920)]
    for style, window_x, window_y in profiles:
        for stage in ("path", "wide", "pen", "line") if (style, window_x, window_y) == (6, 324, 2038) else ("pen",):
            with reference_surface(128, 128) as (gdi, dc, _bits):
                ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
                for name in ("BeginPath", "EndPath", "WidenPath"):
                    bind(gdi, name, boolean, ptr)
                bind(gdi, "Polygon", boolean, ptr, ctypes.POINTER(wintypes.POINT), integer)
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
                check(gdi.SetWindowExtEx(dc, window_x, window_y, None), "SetWindowExtEx")
                check(gdi.SetWindowOrgEx(dc, 1531, 1714, None), "SetWindowOrgEx")
                pen = check(gdi.CreatePen(style, 8, 0), "CreatePen")
                old_pen = check(gdi.SelectObject(dc, pen), "SelectObject")
                old_brush = check(gdi.SelectObject(dc, check(gdi.GetStockObject(5), "NULL_BRUSH")), "SelectObject")
                try:
                    check(gdi.BeginPath(dc), "BeginPath")
                    if stage in ("path", "wide"):
                        points = (wintypes.POINT * len(POLYGON))(*(wintypes.POINT(*p) for p in POLYGON))
                        check(gdi.Polygon(dc, points, len(points)), "Polygon")
                    elif stage == "line":
                        check(gdi.MoveToEx(dc, *POLYGON[6], None), "MoveToEx")
                        check(gdi.LineTo(dc, *POLYGON[7]), "LineTo")
                    else:
                        check(gdi.MoveToEx(dc, 1531, 1714, None), "MoveToEx")
                        check(gdi.LineTo(dc, 1531, 1714), "LineTo")
                    check(gdi.EndPath(dc), "EndPath")
                    if stage != "path":
                        check(gdi.WidenPath(dc), "WidenPath")
                    check(gdi.SetWindowOrgEx(dc, 0, 0, None), "SetWindowOrgEx")
                    check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                    count = gdi.GetPath(dc, None, None, 0)
                    if count < 0:
                        raise RuntimeError("GetPath failed")
                    points = (wintypes.POINT * count)()
                    kinds = (ctypes.c_ubyte * count)()
                    assert gdi.GetPath(dc, points, kinds, count) == count
                    print(
                        style,
                        window_x,
                        window_y,
                        stage,
                        [(p.x, p.y, k) for p, k in zip(points, kinds, strict=True)],
                        flush=True,
                    )
                finally:
                    gdi.SelectObject(dc, old_brush)
                    gdi.SelectObject(dc, old_pen)
                    gdi.DeleteObject(pen)


if __name__ == "__main__":
    main()
