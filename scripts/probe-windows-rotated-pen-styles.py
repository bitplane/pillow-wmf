"""Print native WidenPath outlines for geometric pen caps, joins and styles under rotation.

Each case records a vee or a closed triangle into a path under a world
transform in GM_ADVANCED with one geometric ExtCreatePen pen, widens it and
reads the path back under a 1/16 world transform, so the integers are device
sixteenths. No reference images are written.

    case transform cap join style width figure drawn=... (type,x16,y16) ...
"""

import ctypes
import math
import platform
from ctypes import wintypes

from windows_wmf_render import bind, check, module_versions, reference_surface

CAPS = {"round": 0x0000, "square": 0x0100, "flat": 0x0200}
JOINS = {"round": 0x0000, "bevel": 0x1000, "miter": 0x2000}
STYLES = {"solid": 0, "dash": 1, "dot": 2, "user": 7}
USER = (3, 2, 1, 2)
FIGURES = {"vee": ((4, 4), (16, 24), (28, 6)), "triangle": ((4, 4), (28, 8), (12, 24))}
PENS = [
    (cap, join, "solid") for cap in CAPS for join in JOINS if (cap, join) not in {("round", "round"), ("flat", "bevel")}
]
PENS += [("flat", "bevel", "dash"), ("round", "round", "dot"), ("square", "miter", "user")]


class XForm(ctypes.Structure):
    _fields_ = [(name, ctypes.c_float) for name in ("m11", "m12", "m21", "m22", "dx", "dy")]


class LogBrush(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("color", wintypes.DWORD), ("hatch", ctypes.c_size_t)]


def transforms():
    yield "identity", (1.0, 0.0, 0.0, 1.0, 16.0, 16.0)
    angle = math.radians(25)
    yield "r25", (math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle), 30.0, 5.0)
    yield "shear", (1.0, 0.0, 0.4, 1.0, 10.0, 10.0)
    yield "general", (0.9, 0.35, -0.2, 1.1, 20.0, 8.0)


def bind_probe(gdi):
    ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
    bind(gdi, "SetGraphicsMode", integer, ptr, integer)
    bind(gdi, "SetWorldTransform", boolean, ptr, ctypes.POINTER(XForm))
    bind(gdi, "SetMapMode", integer, ptr, integer)
    bind(gdi, "ExtCreatePen", ptr, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(LogBrush), wintypes.DWORD, ptr)
    bind(gdi, "SelectObject", ptr, ptr, ptr)
    bind(gdi, "DeleteObject", boolean, ptr)
    bind(gdi, "BeginPath", boolean, ptr)
    bind(gdi, "EndPath", boolean, ptr)
    bind(gdi, "WidenPath", boolean, ptr)
    bind(gdi, "Polyline", boolean, ptr, ctypes.POINTER(wintypes.POINT), integer)
    bind(gdi, "Polygon", boolean, ptr, ctypes.POINTER(wintypes.POINT), integer)
    bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)


def widen(transform, cap, join, style, width, figure):
    with reference_surface(16, 16) as (gdi, dc, _):
        bind_probe(gdi)
        check(gdi.SetMapMode(dc, 1), "SetMapMode")
        check(gdi.SetGraphicsMode(dc, 2), "SetGraphicsMode")
        check(gdi.SetWorldTransform(dc, ctypes.byref(XForm(*transform))), "SetWorldTransform")
        bits = 0x00010000 | CAPS[cap] | JOINS[join] | STYLES[style]
        entries = (wintypes.DWORD * len(USER))(*USER) if style == "user" else None
        pen = gdi.ExtCreatePen(bits, width, ctypes.byref(LogBrush(0, 0, 0)), len(USER) if entries else 0, entries)
        check(pen, "pen")
        previous = gdi.SelectObject(dc, pen)
        vertices = FIGURES[figure]
        array = (wintypes.POINT * len(vertices))(*[wintypes.POINT(*p) for p in vertices])
        check(gdi.BeginPath(dc), "BeginPath")
        (gdi.Polygon if figure == "triangle" else gdi.Polyline)(dc, array, len(vertices))
        check(gdi.EndPath(dc), "EndPath")
        drawn = gdi.WidenPath(dc)
        check(gdi.SetWorldTransform(dc, ctypes.byref(XForm(1 / 16, 0, 0, 1 / 16, 0, 0))), "SetWorldTransform")
        count = gdi.GetPath(dc, None, None, 0)
        text = "empty"
        if count > 0:
            path = (wintypes.POINT * count)()
            types = (ctypes.c_ubyte * count)()
            check(gdi.GetPath(dc, path, types, count) == count, "GetPath")
            text = " ".join(f"({types[i]},{path[i].x},{path[i].y})" for i in range(count))
        gdi.SelectObject(dc, previous)
        gdi.DeleteObject(pen)
        return f"drawn={drawn} {text}"


def main():
    print(f"Windows rotated pen style probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    for name, transform in transforms():
        for cap, join, style in PENS:
            for width in (4, 7):
                for figure in FIGURES:
                    result = widen(transform, cap, join, style, width, figure)
                    print(f"case {name} {cap} {join} {style} {width} {figure} {result}")


if __name__ == "__main__":
    main()
