"""Print the outlines native GDI widens pens into under rotated transforms.

Each case sets a world transform in GM_ADVANCED, records a short line or
vee into a path with a CreatePen or geometric ExtCreatePen pen, widens it,
and reads the result back under a 1/16 world transform, so the returned
integers are device sixteenths. The pen polygon and its width are visible
in the outline. No reference images are written.

    case transform pen width figure drawn=... (type,x16,y16) ...
"""

import ctypes
import math
import platform
from ctypes import wintypes

from windows_wmf_render import bind, check, module_versions, reference_surface


class XForm(ctypes.Structure):
    _fields_ = [(name, ctypes.c_float) for name in ("m11", "m12", "m21", "m22", "dx", "dy")]


class LogBrush(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("color", wintypes.DWORD), ("hatch", ctypes.c_size_t)]


def transforms():
    for degrees in (0, 10, 25, 45, 90):
        for sx, sy in ((1.0, 1.0), (2.5092592239379883, 2.5098910331726074), (1.7, 1.2)):
            angle = math.radians(degrees)
            cos, sin = math.cos(angle), math.sin(angle)
            # Scale, then rotate: x' = sx*x*cos - sy*y*sin.
            yield f"r{degrees}-s{sx:.3f}x{sy:.3f}", (sx * cos, sx * sin, -sy * sin, sy * cos, 64.0, 64.0)
    yield "shear", (1.0, 0.0, 0.4, 1.0, 64.0, 64.0)


FIGURES = {"line": ((-12, -3), (14, 5)), "vee": ((-12, -8), (0, 10), (12, -8))}


def bind_probe(gdi):
    ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
    bind(gdi, "SetGraphicsMode", integer, ptr, integer)
    bind(gdi, "SetWorldTransform", boolean, ptr, ctypes.POINTER(XForm))
    bind(gdi, "SetMapMode", integer, ptr, integer)
    bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
    bind(
        gdi,
        "ExtCreatePen",
        ptr,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(LogBrush),
        wintypes.DWORD,
        ptr,
    )
    bind(gdi, "SelectObject", ptr, ptr, ptr)
    bind(gdi, "DeleteObject", boolean, ptr)
    bind(gdi, "BeginPath", boolean, ptr)
    bind(gdi, "EndPath", boolean, ptr)
    bind(gdi, "WidenPath", boolean, ptr)
    bind(gdi, "Polyline", boolean, ptr, ctypes.POINTER(wintypes.POINT), integer)
    bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)


def read_path(gdi, dc):
    count = gdi.GetPath(dc, None, None, 0)
    if count <= 0:
        return "empty"
    points = (wintypes.POINT * count)()
    types = (ctypes.c_ubyte * count)()
    check(gdi.GetPath(dc, points, types, count) == count, "GetPath")
    return " ".join(f"({types[i]},{points[i].x},{points[i].y})" for i in range(count))


def widen(transform, kind, width, figure):
    with reference_surface(16, 16) as (gdi, dc, _):
        bind_probe(gdi)
        check(gdi.SetMapMode(dc, 1), "SetMapMode")
        check(gdi.SetGraphicsMode(dc, 2), "SetGraphicsMode")
        check(gdi.SetWorldTransform(dc, ctypes.byref(XForm(*transform))), "SetWorldTransform")
        if kind == "create":
            pen = gdi.CreatePen(0, width, 0)
        else:
            brush = LogBrush(0, 0, 0)
            style = 0x00010000 | {"geo-round": 0, "geo-flat": 0x0200 | 0x1000}[kind]
            pen = gdi.ExtCreatePen(style, width, ctypes.byref(brush), 0, None)
        check(pen, "pen")
        previous = gdi.SelectObject(dc, pen)
        points = (wintypes.POINT * len(figure))(*[wintypes.POINT(*p) for p in figure])
        check(gdi.BeginPath(dc), "BeginPath")
        gdi.Polyline(dc, points, len(figure))
        check(gdi.EndPath(dc), "EndPath")
        drawn = gdi.WidenPath(dc)
        check(gdi.SetWorldTransform(dc, ctypes.byref(XForm(1 / 16, 0, 0, 1 / 16, 0, 0))), "SetWorldTransform")
        result = f"drawn={drawn} " + read_path(gdi, dc)
        gdi.SelectObject(dc, previous)
        gdi.DeleteObject(pen)
        return result


def main():
    print(f"Windows rotated pen probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    for name, transform in transforms():
        print(f"transform {name} {transform}")
        for kind in ("create", "geo-round", "geo-flat"):
            for width in (1, 2, 3, 4, 5, 7):
                for figure, points in FIGURES.items():
                    print(f"case {name} {kind} {width} {figure} {widen(transform, kind, width, points)}")


if __name__ == "__main__":
    main()
