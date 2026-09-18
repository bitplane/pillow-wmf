"""Small native contour probe for the fdo39256-2 support boundary."""

import ctypes
from ctypes import wintypes

from windows_wmf_render import bind, check, reference_surface


def main():
    for width, window, viewport in (
        (176, (8118, 8035), (128, 128)),
        (6, (412, 1915), (128, 128)),
        (6, (412, 1536), (128, 128)),
        (6, (412, 1280), (128, 128)),
        (1, (128, 128), (192, 96)),
        (48, (2232, 2218), (128, 128)),
        (48, (2213, 2223), (128, 128)),
        (16, (936, 2655), (128, 128)),
        (6, (412, 1535), (128, 128)),
    ):
        for endpoint in ((0, 0), (698, -1695), (0, 1000), (1000, 0)):
            with reference_surface(128, 128) as (gdi, dc, _bits):
                ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
                for name in ("BeginPath", "EndPath", "WidenPath"):
                    bind(gdi, name, boolean, ptr)
                bind(gdi, "FillPath", boolean, ptr)
                bind(gdi, "CreateSolidBrush", ptr, wintypes.DWORD)
                bind(gdi, "GdiFlush", boolean)
                bind(
                    gdi,
                    "GetPath",
                    integer,
                    ptr,
                    ctypes.POINTER(wintypes.POINT),
                    ctypes.POINTER(ctypes.c_ubyte),
                    integer,
                )
                bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
                bind(gdi, "SelectObject", ptr, ptr, ptr)
                bind(gdi, "DeleteObject", boolean, ptr)
                bind(gdi, "MoveToEx", boolean, ptr, integer, integer, ctypes.POINTER(wintypes.POINT))
                bind(gdi, "LineTo", boolean, ptr, integer, integer)
                bind(gdi, "SetWindowExtEx", boolean, ptr, integer, integer, ctypes.POINTER(wintypes.SIZE))
                bind(gdi, "SetViewportExtEx", boolean, ptr, integer, integer, ctypes.POINTER(wintypes.SIZE))
                bind(gdi, "SetViewportOrgEx", boolean, ptr, integer, integer, ctypes.POINTER(wintypes.POINT))
                bind(gdi, "SetMapMode", integer, ptr, integer)
                check(gdi.SetWindowExtEx(dc, *window, None), "SetWindowExtEx")
                check(gdi.SetViewportExtEx(dc, *viewport, None), "SetViewportExtEx")
                check(gdi.SetViewportOrgEx(dc, 64, 64, None), "SetViewportOrgEx")
                pen = check(gdi.CreatePen(0, width, 0), "CreatePen")
                old = gdi.SelectObject(dc, pen)
                brush = check(gdi.CreateSolidBrush(0), "CreateSolidBrush")
                old_brush = gdi.SelectObject(dc, brush)
                check(gdi.MoveToEx(dc, 0, 0, None), "MoveToEx")
                check(gdi.LineTo(dc, *endpoint), "LineTo")
                gdi.GdiFlush()
                direct = ctypes.string_at(_bits, 128 * 128 * 4)
                ctypes.memset(_bits, 255, 128 * 128 * 4)
                check(gdi.BeginPath(dc), "BeginPath")
                check(gdi.MoveToEx(dc, 0, 0, None), "MoveToEx")
                check(gdi.LineTo(dc, *endpoint), "LineTo")
                check(gdi.EndPath(dc), "EndPath")
                check(gdi.WidenPath(dc), "WidenPath")
                for coordinates in ("logical", "fixed", "device"):
                    if coordinates == "fixed":
                        check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                        check(gdi.SetViewportExtEx(dc, 128, 128, None), "SetViewportExtEx")
                        check(gdi.SetViewportOrgEx(dc, 0, 0, None), "SetViewportOrgEx")
                    if coordinates == "device":
                        check(gdi.SetMapMode(dc, 1), "SetMapMode")
                        check(gdi.SetViewportOrgEx(dc, 0, 0, None), "SetViewportOrgEx")
                    count = gdi.GetPath(dc, None, None, 0)
                    if count < 0:
                        raise RuntimeError("GetPath failed")
                    points = (wintypes.POINT * count)()
                    kinds = (ctypes.c_ubyte * count)()
                    assert gdi.GetPath(dc, points, kinds, count) == count
                    print(
                        width, window, endpoint, coordinates, [(p.x, p.y, k) for p, k in zip(points, kinds)], flush=True
                    )
                check(gdi.FillPath(dc), "FillPath")
                gdi.GdiFlush()
                widened = ctypes.string_at(_bits, 128 * 128 * 4)
                differences = sum(direct[i : i + 3] != widened[i : i + 3] for i in range(0, len(direct), 4))
                print(width, window, endpoint, "direct-vs-widened", differences, flush=True)
                gdi.SelectObject(dc, old)
                gdi.SelectObject(dc, old_brush)
                gdi.DeleteObject(pen)
                gdi.DeleteObject(brush)


if __name__ == "__main__":
    main()
