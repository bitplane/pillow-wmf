"""Targeted native paths for the four binary-review arithmetic findings."""

import ctypes
import os
import struct
import subprocess
from ctypes import wintypes
from pathlib import Path

from windows_wmf_render import bind, check, reference_surface


def bind_paths(gdi):
    ptr, integer = ctypes.c_void_p, ctypes.c_int
    for name in ("BeginPath", "EndPath", "WidenPath"):
        bind(gdi, name, wintypes.BOOL, ptr)
    for name in ("SetWindowOrgEx", "SetViewportOrgEx", "MoveToEx"):
        bind(gdi, name, wintypes.BOOL, ptr, integer, integer, ptr)
    bind(gdi, "LineTo", wintypes.BOOL, ptr, integer, integer)
    bind(gdi, "Ellipse", wintypes.BOOL, ptr, *([integer] * 4))
    bind(gdi, "RoundRect", wintypes.BOOL, ptr, *([integer] * 6))
    bind(gdi, "Arc", wintypes.BOOL, ptr, *([integer] * 8))
    bind(gdi, "SetLayout", wintypes.DWORD, ptr, wintypes.DWORD)
    bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
    bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)


def read_path(gdi, dc):
    gdi.SetLayout(dc, 0)
    check(gdi.SetWindowOrgEx(dc, 0, 0, None), "SetWindowOrgEx")
    check(gdi.SetViewportOrgEx(dc, 0, 0, None), "SetViewportOrgEx")
    check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
    check(gdi.SetViewportExtEx(dc, 128, 128, None), "SetViewportExtEx")
    count = gdi.GetPath(dc, None, None, 0)
    if count < 0:
        raise RuntimeError("GetPath failed")
    points, kinds = (wintypes.POINT * count)(), (ctypes.c_ubyte * count)()
    assert gdi.GetPath(dc, points, kinds, count) == count
    return [(p.x, p.y, kind) for p, kind in zip(points, kinds, strict=False)]


def main():
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-Item C:/Windows/System32/win32kbase.sys, C:/Windows/System32/win32kfull.sys | "
            "ForEach-Object { $_.Name; $_.VersionInfo.FileVersion }",
        ],
        check=True,
    )
    # Identify the exact public-symbol images, not just a nearby OS release.
    for name in ("win32kbase.sys", "win32kfull.sys"):
        data = (Path(os.environ["SYSTEMROOT"]) / "System32" / name).read_bytes()
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        timestamp = struct.unpack_from("<I", data, pe + 8)[0]
        image_size = struct.unpack_from("<I", data, pe + 24 + 56)[0]
        print("symbol-image", name, f"{timestamp:08X}{image_size:x}", flush=True)
    for layout in (0, 1):
        with reference_surface(128, 128) as (gdi, dc, _):
            bind_paths(gdi)
            gdi.SetWindowExtEx(dc, 6316, 128, None)
            gdi.SetViewportExtEx(dc, 511, 128, None)
            gdi.SetWindowOrgEx(dc, 21707, 0, None)
            gdi.SetViewportOrgEx(dc, 138, 0, None)
            gdi.SetLayout(dc, layout)
            check(gdi.BeginPath(dc), "BeginPath")
            gdi.MoveToEx(dc, 20006, 32, None)
            for x in (20007, 20008, 20500, 21000):
                check(gdi.LineTo(dc, x, 32), "LineTo")
            check(gdi.EndPath(dc), "EndPath")
            print("mapping", layout, read_path(gdi, dc), flush=True)

    for width in (511, 512, 513):
        for reflected in (False, True):
            with reference_surface(128, 128) as (gdi, dc, _):
                bind_paths(gdi)
                gdi.SetWindowExtEx(dc, 1, 1024, None)
                gdi.SetViewportExtEx(dc, -1 if reflected else 1, 1, None)
                pen = check(gdi.CreatePen(0, width, 0), "CreatePen")
                old = gdi.SelectObject(dc, pen)
                try:
                    check(gdi.BeginPath(dc), "BeginPath")
                    gdi.MoveToEx(dc, 0, 0, None)
                    check(gdi.LineTo(dc, 0, 0), "LineTo")
                    check(gdi.EndPath(dc), "EndPath")
                    check(gdi.WidenPath(dc), "WidenPath")
                    print("thin-pen", width, reflected, read_path(gdi, dc), flush=True)
                finally:
                    gdi.SelectObject(dc, old)
                    gdi.DeleteObject(pen)

    for extent in (88281, 88282, 88283):
        for operation in ("Ellipse", "RoundRect"):
            with reference_surface(128, 128) as (gdi, dc, _):
                bind_paths(gdi)
                check(gdi.BeginPath(dc), "BeginPath")
                args = (0, 0, extent, 100)
                if operation == "RoundRect":
                    args += (extent, 100)
                check(getattr(gdi, operation)(dc, *args), operation)
                check(gdi.EndPath(dc), "EndPath")
                print("control", operation, extent, read_path(gdi, dc), flush=True)

    for size in (128, 8192, 131071, 1000000):
        for start, end in (
            ((10000, -1), (0, -10000)),
            ((10000, -490), (10000, -1000)),
            ((10000, -523), (10000, -1048)),
            ((10000, -1), (10000, -500)),
            ((-10000, -490), (-10000, -1000)),
        ):
            with reference_surface(128, 128) as (gdi, dc, _):
                bind_paths(gdi)
                box = (-size, -size, size, size)
                check(gdi.BeginPath(dc), "BeginPath")
                check(gdi.Arc(dc, *box, *start, *end), "Arc")
                check(gdi.EndPath(dc), "EndPath")
                print("arc", size, start, end, read_path(gdi, dc), flush=True)

    with reference_surface(128, 128) as (gdi, dc, _):
        bind_paths(gdi)
        check(gdi.BeginPath(dc), "BeginPath")
        check(gdi.Arc(dc, 8, 16, 120, 112, 62, 16364, 62, 16365), "Arc")
        check(gdi.EndPath(dc), "EndPath")
        print("tiny-loop", read_path(gdi, dc), flush=True)


if __name__ == "__main__":
    main()
