"""Print native WidenPath outlines of figures stroked with styled cosmetic pens.

Each case records a figure into a path in GM_ADVANCED under a world
transform, selects a CreatePen pen or a cosmetic ExtCreatePen pen, widens
the path and reads it back under a 1/16 world transform, so the integers
are device sixteenths. Styled CreatePen pens wider than one pixel and the
solid pen are references for the same figure. No reference images are
written.

    case transform pen style width figure widened=... (type,x16,y16) ...
"""

import ctypes
import platform
from ctypes import wintypes

from windows_wmf_render import bind, check, module_versions, reference_surface

STYLES = {"solid": 0, "dash": 1, "dot": 2, "dashdot": 3, "dashdotdot": 4, "user": 7, "alternate": 8}
USER_STYLE = (3, 2, 1, 2)
TRANSFORMS = {
    "identity": (1, 0, 0, 1, 0, 0),
    "scale2": (2, 0, 0, 2, 0, 0),
    "r25": (0.9063, 0.4226, -0.4226, 0.9063, 8, 0),
}
FIGURES = {
    "line": ((2, 3), (44, 12)),
    "vee": ((2, 2), (14, 20), (26, 2)),
    "closed": ((2, 2), (30, 4), (12, 22)),
}
CASES = [
    *(
        ("identity", "create", style, width, "line")
        for style in ("solid", "dash", "dot", "dashdot", "dashdotdot")
        for width in (0, 1)
    ),
    ("identity", "create", "dash", 2, "line"),
    ("identity", "create", "dash", 1, "vee"),
    ("identity", "create", "dot", 1, "closed"),
    ("scale2", "create", "dash", 1, "line"),
    ("scale2", "create", "dot", 0, "vee"),
    ("r25", "create", "dash", 1, "line"),
    *(("identity", "cosmetic", style, 1, "line") for style in ("solid", "dash", "alternate", "user")),
    ("identity", "cosmetic", "alternate", 1, "vee"),
    ("scale2", "cosmetic", "user", 1, "line"),
]


class XForm(ctypes.Structure):
    _fields_ = [(name, ctypes.c_float) for name in ("m11", "m12", "m21", "m22", "dx", "dy")]


class LogBrush(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("color", wintypes.DWORD), ("hatch", ctypes.c_size_t)]


def bind_probe(gdi):
    ptr, integer, boolean, dword = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL, wintypes.DWORD
    bind(gdi, "SetGraphicsMode", integer, ptr, integer)
    bind(gdi, "SetWorldTransform", boolean, ptr, ctypes.POINTER(XForm))
    bind(gdi, "SetMapMode", integer, ptr, integer)
    bind(gdi, "CreatePen", ptr, integer, integer, dword)
    bind(gdi, "ExtCreatePen", ptr, dword, dword, ctypes.POINTER(LogBrush), dword, ctypes.POINTER(dword))
    bind(gdi, "SelectObject", ptr, ptr, ptr)
    bind(gdi, "DeleteObject", boolean, ptr)
    bind(gdi, "BeginPath", boolean, ptr)
    bind(gdi, "EndPath", boolean, ptr)
    bind(gdi, "CloseFigure", boolean, ptr)
    bind(gdi, "WidenPath", boolean, ptr)
    bind(gdi, "MoveToEx", boolean, ptr, integer, integer, ptr)
    bind(gdi, "PolylineTo", boolean, ptr, ctypes.POINTER(wintypes.POINT), dword)
    bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)


def read_path(gdi, dc):
    count = gdi.GetPath(dc, None, None, 0)
    if count <= 0:
        return "empty"
    points = (wintypes.POINT * count)()
    types = (ctypes.c_ubyte * count)()
    check(gdi.GetPath(dc, points, types, count) == count, "GetPath")
    return " ".join(f"({types[i]},{points[i].x},{points[i].y})" for i in range(count))


def make_pen(gdi, kind, style, width):
    if kind == "create":
        return gdi.CreatePen(STYLES[style], width, 0x0000FF)
    brush = LogBrush(0, 0x0000FF, 0)
    entries = USER_STYLE if style == "user" else ()
    array = (wintypes.DWORD * max(1, len(entries)))(*entries)
    return gdi.ExtCreatePen(STYLES[style], width, ctypes.byref(brush), len(entries), array if entries else None)


def widen(transform, kind, style, width, figure):
    with reference_surface(16, 16) as (gdi, dc, _):
        bind_probe(gdi)
        check(gdi.SetMapMode(dc, 1), "SetMapMode")
        check(gdi.SetGraphicsMode(dc, 2), "SetGraphicsMode")
        check(gdi.SetWorldTransform(dc, ctypes.byref(XForm(*TRANSFORMS[transform]))), "SetWorldTransform")
        pen = make_pen(gdi, kind, style, width)
        check(pen, "pen")
        previous = gdi.SelectObject(dc, pen)
        points = FIGURES[figure]
        rest = (wintypes.POINT * (len(points) - 1))(*[wintypes.POINT(*p) for p in points[1:]])
        check(gdi.BeginPath(dc), "BeginPath")
        gdi.MoveToEx(dc, *points[0], None)
        gdi.PolylineTo(dc, rest, len(points) - 1)
        if figure == "closed":
            gdi.CloseFigure(dc)
        check(gdi.EndPath(dc), "EndPath")
        widened = gdi.WidenPath(dc)
        check(gdi.SetWorldTransform(dc, ctypes.byref(XForm(1 / 16, 0, 0, 1 / 16, 0, 0))), "SetWorldTransform")
        result = f"widened={widened} " + read_path(gdi, dc)
        gdi.SelectObject(dc, previous)
        gdi.DeleteObject(pen)
        return result


def main():
    print(f"Windows cosmetic widen probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    for transform, kind, style, width, figure in CASES:
        print(f"case {transform} {kind} {style} {width} {figure} {widen(transform, kind, style, width, figure)}")


if __name__ == "__main__":
    main()
