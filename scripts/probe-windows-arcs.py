"""Inspect Windows GDI's native Arc path and direct raster output."""

import ctypes
from ctypes import wintypes

from windows_wmf_render import bind, check, reference_surface


def path_points(gdi, dc):
    count = gdi.GetPath(dc, None, None, 0)
    points = (wintypes.POINT * count)()
    kinds = (ctypes.c_ubyte * count)()
    check(gdi.GetPath(dc, points, kinds, count) == count, "GetPath")
    return tuple((point.x, point.y, kind) for point, kind in zip(points, kinds, strict=True))


def fixed_path_points(gdi, dc):
    """Magnify the inverse mapping only after constructing the device path."""
    check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
    try:
        return path_points(gdi, dc)
    finally:
        check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")


def main():
    with reference_surface(128, 128) as (gdi, dc, bits):
        ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
        for name in ("BeginPath", "EndPath", "FlattenPath", "AbortPath", "StrokePath", "WidenPath", "GdiFlush"):
            bind(gdi, name, boolean, ptr) if name != "GdiFlush" else bind(gdi, name, boolean)
        bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)
        bind(gdi, "Arc", boolean, ptr, *(integer for _ in range(8)))
        bind(gdi, "SetViewportExtEx", boolean, ptr, integer, integer, ctypes.POINTER(wintypes.SIZE))
        bind(gdi, "SetWindowExtEx", boolean, ptr, integer, integer, ctypes.POINTER(wintypes.SIZE))
        cases = (
            (8, 8, 47, 47, 47, 27, 27, 8),
            (68, 8, 107, 47, 87, 8, 68, 27),
            (8, 68, 47, 107, 8, 87, 27, 106),
            (68, 68, 107, 107, 87, 106, 106, 87),
            (8, 8, 59, 43, 54, 13, 12, 38),
        )
        for case in cases:
            check(gdi.BeginPath(dc), "BeginPath")
            check(gdi.Arc(dc, *case), "Arc")
            check(gdi.EndPath(dc), "EndPath")
            print("arc-raw", case, path_points(gdi, dc))
            print("arc-fixed-controls", case, fixed_path_points(gdi, dc))
            check(gdi.FlattenPath(dc), "FlattenPath")
            print("arc-flat", case, path_points(gdi, dc))
            print("arc-fixed-flat", case, fixed_path_points(gdi, dc))
            check(gdi.AbortPath(dc), "AbortPath")
            check(gdi.SetViewportExtEx(dc, 2048, 2048, None), "SetViewportExtEx")
            check(gdi.BeginPath(dc), "BeginPath")
            check(gdi.Arc(dc, *case), "Arc")
            check(gdi.EndPath(dc), "EndPath")
            print("arc-raw-16x", case, path_points(gdi, dc))
            check(gdi.AbortPath(dc), "AbortPath")
            check(gdi.SetViewportExtEx(dc, 128, 128, None), "SetViewportExtEx")
            ctypes.memset(bits, 255, 128 * 128 * 4)
            check(gdi.Arc(dc, *case), "Arc")
            check(gdi.GdiFlush(), "GdiFlush")
            direct = ctypes.string_at(bits, 128 * 128 * 4)
            ctypes.memset(bits, 255, 128 * 128 * 4)
            check(gdi.BeginPath(dc), "BeginPath")
            check(gdi.Arc(dc, *case), "Arc")
            check(gdi.EndPath(dc), "EndPath")
            check(gdi.StrokePath(dc), "StrokePath")
            check(gdi.GdiFlush(), "GdiFlush")
            path = ctypes.string_at(bits, 128 * 128 * 4)
            difference = sum(direct[i : i + 3] != path[i : i + 3] for i in range(0, len(direct), 4))
            print("arc-direct-path-difference", case, difference)
            ctypes.memset(bits, 255, 128 * 128 * 4)
            check(gdi.BeginPath(dc), "BeginPath")
            check(gdi.Arc(dc, *case), "Arc")
            check(gdi.EndPath(dc), "EndPath")
            check(gdi.FlattenPath(dc), "FlattenPath")
            check(gdi.StrokePath(dc), "StrokePath")
            check(gdi.GdiFlush(), "GdiFlush")
            flattened = ctypes.string_at(bits, 128 * 128 * 4)
            difference = sum(direct[i : i + 3] != flattened[i : i + 3] for i in range(0, len(direct), 4))
            print("arc-direct-flattened-difference", case, difference)
        bind(gdi, "SetViewportOrgEx", boolean, ptr, integer, integer, ctypes.POINTER(wintypes.POINT))
        for label, extent, origin in (
            ("reflect-x", (-128, 128), (64, 8)),
            ("reflect-y", (128, -128), (8, 64)),
            ("reflect-both", (-128, -128), (64, 64)),
        ):
            check(gdi.SetViewportExtEx(dc, *extent, None), "SetViewportExtEx")
            check(gdi.SetViewportOrgEx(dc, *origin, None), "SetViewportOrgEx")
            check(gdi.BeginPath(dc), "BeginPath")
            check(gdi.Arc(dc, 8, 8, 56, 56, 56, 32, 32, 8), "Arc")
            check(gdi.EndPath(dc), "EndPath")
            check(gdi.SetViewportExtEx(dc, 128, 128, None), "SetViewportExtEx")
            check(gdi.SetViewportOrgEx(dc, 0, 0, None), "SetViewportOrgEx")
            print("arc-reflected-raw", label, path_points(gdi, dc))
            check(gdi.FlattenPath(dc), "FlattenPath")
            print("arc-reflected-flat", label, path_points(gdi, dc))
            check(gdi.AbortPath(dc), "AbortPath")
        check(gdi.SetViewportExtEx(dc, 128, 128, None), "SetViewportExtEx")
        check(gdi.SetViewportOrgEx(dc, 0, 0, None), "SetViewportOrgEx")
        bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
        bind(gdi, "SelectObject", ptr, ptr, ptr)
        bind(gdi, "DeleteObject", boolean, ptr)
        pen = check(gdi.CreatePen(0, 3, 0), "CreatePen")
        previous = check(gdi.SelectObject(dc, pen), "SelectObject")
        try:
            check(gdi.BeginPath(dc), "BeginPath")
            check(gdi.Arc(dc, 68, 8, 116, 56, 136, 32, 68, 8), "Arc")
            check(gdi.EndPath(dc), "EndPath")
            print("arc-wide-raw", path_points(gdi, dc))
            print("arc-wide-fixed-controls", fixed_path_points(gdi, dc))
            check(gdi.FlattenPath(dc), "FlattenPath")
            print("arc-wide-fixed-flat", fixed_path_points(gdi, dc))
            check(gdi.WidenPath(dc), "WidenPath")
            print("arc-wide-widened", path_points(gdi, dc))
            check(gdi.AbortPath(dc), "AbortPath")
        finally:
            gdi.SelectObject(dc, previous)
            gdi.DeleteObject(pen)


if __name__ == "__main__":
    main()
