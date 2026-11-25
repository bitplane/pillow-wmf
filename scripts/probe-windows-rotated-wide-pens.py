"""Print native strokes and widened closed figures for pens under rotated transforms.

Stroke cases draw one figure with a black pen and the null brush on a fresh
white 64x64 32-bit DIB under a world transform in GM_ADVANCED, and print
each changed row as ``y x0 mask`` with ``#`` for each changed pixel from
``x0``. Widen cases record a closed triangle in a path, widen it and read
the path back under a 1/16 world transform, so the integers are device
sixteenths. No reference images are written.

    case transform pen width figure
    widen transform pen width drawn=... (type,x16,y16) ...
"""

import ctypes
import math
import platform
from ctypes import wintypes

from windows_wmf_render import bind, check, module_versions, reference_surface

SIZE = 64
PENS = {"create": None, "geo-round": 0x00010000, "geo-flat": 0x00010000 | 0x0200 | 0x1000}
VEE = ((4, 4), (16, 24), (28, 6))
TRIANGLE = ((4, 4), (28, 8), (12, 24))


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
    bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
    bind(gdi, "ExtCreatePen", ptr, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(LogBrush), wintypes.DWORD, ptr)
    bind(gdi, "GetStockObject", ptr, integer)
    bind(gdi, "SelectObject", ptr, ptr, ptr)
    bind(gdi, "DeleteObject", boolean, ptr)
    bind(gdi, "BeginPath", boolean, ptr)
    bind(gdi, "EndPath", boolean, ptr)
    bind(gdi, "WidenPath", boolean, ptr)
    bind(gdi, "Polyline", boolean, ptr, ctypes.POINTER(wintypes.POINT), integer)
    bind(gdi, "Polygon", boolean, ptr, ctypes.POINTER(wintypes.POINT), integer)
    bind(gdi, "Rectangle", boolean, ptr, integer, integer, integer, integer)
    bind(gdi, "Ellipse", boolean, ptr, integer, integer, integer, integer)
    bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)


def points(figure):
    return (wintypes.POINT * len(figure))(*[wintypes.POINT(*p) for p in figure]), len(figure)


def make_pen(gdi, kind, width):
    if PENS[kind] is None:
        return gdi.CreatePen(0, width, 0)
    return gdi.ExtCreatePen(PENS[kind], width, ctypes.byref(LogBrush(0, 0, 0)), 0, None)


FIGURES = {
    "vee": lambda gdi, dc: gdi.Polyline(dc, *points(VEE)),
    "triangle": lambda gdi, dc: gdi.Polygon(dc, *points(TRIANGLE)),
    "rectangle": lambda gdi, dc: gdi.Rectangle(dc, 4, 4, 28, 20),
    "ellipse": lambda gdi, dc: gdi.Ellipse(dc, 4, 4, 28, 20),
}
STROKES = (
    ("create", 1, "vee"),
    ("create", 3, "vee"),
    ("create", 7, "vee"),
    ("create", 5, "triangle"),
    ("create", 5, "rectangle"),
    ("create", 5, "ellipse"),
    ("geo-round", 5, "vee"),
    ("geo-round", 4, "triangle"),
    ("geo-flat", 4, "vee"),
    ("geo-flat", 4, "triangle"),
)
WIDENS = (("create", 5), ("geo-round", 4), ("geo-flat", 4))


def prepare(gdi, dc, transform):
    bind_probe(gdi)
    check(gdi.SetMapMode(dc, 1), "SetMapMode")
    check(gdi.SetGraphicsMode(dc, 2), "SetGraphicsMode")
    check(gdi.SetWorldTransform(dc, ctypes.byref(XForm(*transform))), "SetWorldTransform")


def stroke(transform, kind, width, figure):
    with reference_surface(SIZE, SIZE) as (gdi, dc, bits):
        prepare(gdi, dc, transform)
        pen = make_pen(gdi, kind, width)
        check(pen, "pen")
        gdi.SelectObject(dc, pen)
        gdi.SelectObject(dc, gdi.GetStockObject(5))  # NULL_BRUSH
        FIGURES[figure](gdi, dc)
        gdi.SelectObject(dc, gdi.GetStockObject(7))  # BLACK_PEN
        gdi.DeleteObject(pen)
        data = ctypes.string_at(bits, SIZE * SIZE * 4)
    rows = []
    for y in range(SIZE):
        row = data[y * SIZE * 4 : (y + 1) * SIZE * 4]
        changed = [x for x in range(SIZE) if row[4 * x : 4 * x + 3] != b"\xff\xff\xff"]
        if changed:
            mask = "".join("#" if x in changed else "." for x in range(changed[0], changed[-1] + 1))
            rows.append(f"  {y} {changed[0]} {mask}")
    return rows


def widen(transform, kind, width):
    with reference_surface(16, 16) as (gdi, dc, _):
        prepare(gdi, dc, transform)
        pen = make_pen(gdi, kind, width)
        check(pen, "pen")
        previous = gdi.SelectObject(dc, pen)
        check(gdi.BeginPath(dc), "BeginPath")
        gdi.Polygon(dc, *points(TRIANGLE))
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
    print(f"Windows rotated wide pen probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    for name, transform in transforms():
        for kind, width, figure in STROKES:
            print(f"case {name} {kind} {width} {figure}")
            print("\n".join(stroke(transform, kind, width, figure)))
        for kind, width in WIDENS:
            print(f"widen {name} {kind} {width} {widen(transform, kind, width)}")


if __name__ == "__main__":
    main()
