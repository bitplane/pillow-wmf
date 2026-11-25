"""Print the exact 28.4 outlines native GDI widens geometric pens into.

Each figure is recorded into a path in GM_ADVANCED under a fixture frame
fit, widened with an ExtCreatePen geometric pen, and read back under a 1/16
world transform so the returned integers are device sixteenths. Cases cover
end caps, joins, miter limits, closed figures and dash styles. No reference
images are written.

    case scale cap join limit style width figure drawn=... (type,x16,y16) ...
"""

import ctypes
import platform
import runpy
from ctypes import wintypes
from pathlib import Path

from windows_wmf_render import bind, check, module_versions, reference_surface

from pillow_wmf.emf import Header
from pillow_wmf.emf.transform import frame_fit

PS_GEOMETRIC, PS_USERSTYLE = 0x00010000, 7
CAPS = {"round": 0x0000, "square": 0x0100, "flat": 0x0200}
JOINS = {"round": 0x0000, "bevel": 0x1000, "miter": 0x2000}
STYLES = {"solid": 0, "dash": 1, "dot": 2, "dashdot": 3, "dashdotdot": 4}


class XForm(ctypes.Structure):
    _fields_ = [(name, ctypes.c_float) for name in ("m11", "m12", "m21", "m22", "dx", "dy")]


class LogBrush(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("color", wintypes.DWORD), ("hatch", ctypes.c_size_t)]


def scales():
    generator = runpy.run_path(str(Path(__file__).with_name("generate-emf-fixtures.py")))
    result = {}
    for name in ("unit", "up-2-5"):
        extent = generator["EXTENTS"][name]
        fit = frame_fit(Header.create((0, 0, -1, -1), generator["frame"](extent)), (0, 0, 128, 128))
        result[name] = (fit[0], fit[3], fit[4], fit[5], extent / 128)
    return result


FIGURES = {
    "vee": ((0, 0), (12, 22), (24, 0)),
    "flat-vee": ((0, 0), (10, 14), (20, 0)),
    "horizontal": ((0, 0), (40, 0)),
    "diagonal": ((0, 0), (24, 20)),
    "shallow": ((0, 0), (40, 8)),
    "reversal": ((0, 0), (16, 0), (4, 0)),
    "zigzag": ((0, 0), (8, 3), (16, 0), (17, 9)),
}


def bind_probe(gdi):
    ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
    bind(gdi, "SetGraphicsMode", integer, ptr, integer)
    bind(gdi, "SetWorldTransform", boolean, ptr, ctypes.POINTER(XForm))
    bind(gdi, "SetMapMode", integer, ptr, integer)
    bind(gdi, "SetMiterLimit", boolean, ptr, ctypes.c_float, ptr)
    bind(
        gdi,
        "ExtCreatePen",
        ptr,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(LogBrush),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    bind(gdi, "SelectObject", ptr, ptr, ptr)
    bind(gdi, "DeleteObject", boolean, ptr)
    bind(gdi, "BeginPath", boolean, ptr)
    bind(gdi, "EndPath", boolean, ptr)
    bind(gdi, "CloseFigure", boolean, ptr)
    bind(gdi, "WidenPath", boolean, ptr)
    bind(gdi, "MoveToEx", boolean, ptr, integer, integer, ptr)
    bind(gdi, "PolylineTo", boolean, ptr, ctypes.POINTER(wintypes.POINT), wintypes.DWORD)
    bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)


def read_path(gdi, dc):
    count = gdi.GetPath(dc, None, None, 0)
    if count <= 0:
        return "empty"
    points = (wintypes.POINT * count)()
    types = (ctypes.c_ubyte * count)()
    check(gdi.GetPath(dc, points, types, count) == count, "GetPath")
    return " ".join(f"({types[i]},{points[i].x},{points[i].y})" for i in range(count))


def widen(transform, style, width, figure, *, limit=10.0, closed=False, entries=()):
    m11, m22, dx, dy, unit = transform
    with reference_surface(16, 16) as (gdi, dc, _):
        bind_probe(gdi)
        check(gdi.SetMapMode(dc, 1), "SetMapMode")
        check(gdi.SetGraphicsMode(dc, 2), "SetGraphicsMode")
        check(gdi.SetWorldTransform(dc, ctypes.byref(XForm(m11, 0, 0, m22, dx, dy))), "SetWorldTransform")
        check(gdi.SetMiterLimit(dc, limit, None), "SetMiterLimit")
        brush = LogBrush(0, 0x0000FF, 0)
        array = (wintypes.DWORD * max(1, len(entries)))(*[round(e * unit) for e in entries])
        pen = gdi.ExtCreatePen(
            style, round(width * unit), ctypes.byref(brush), len(entries), array if entries else None
        )
        check(pen, "ExtCreatePen")
        previous = gdi.SelectObject(dc, pen)
        points = [(round((x + 6) * unit), round((y + 6) * unit)) for x, y in figure]
        rest = (wintypes.POINT * (len(points) - 1))(*[wintypes.POINT(*p) for p in points[1:]])
        check(gdi.BeginPath(dc), "BeginPath")
        gdi.MoveToEx(dc, *points[0], None)
        gdi.PolylineTo(dc, rest, len(points) - 1)
        if closed:
            gdi.CloseFigure(dc)
        check(gdi.EndPath(dc), "EndPath")
        drawn = gdi.WidenPath(dc)
        check(gdi.SetWorldTransform(dc, ctypes.byref(XForm(1 / 16, 0, 0, 1 / 16, 0, 0))), "SetWorldTransform")
        result = f"points={points} drawn={drawn} " + read_path(gdi, dc)
        gdi.SelectObject(dc, previous)
        gdi.DeleteObject(pen)
        return result


def main():
    print(f"Windows pen widening probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    fits = scales()
    print(f"Scales (m11, m22, dx, dy, unit): {fits}")
    # Single segments sweeping two octants show the cap and body vectors.
    directions = [(64, k) for k in range(65)] + [(k, 64) for k in range(63, -1, -1)]
    for width in (3, 5, 6, 9, 12):
        for cap in ("flat", "square"):
            style = PS_GEOMETRIC | CAPS[cap] | JOINS["bevel"]
            for dx, dy in directions:
                case = f"sweep {cap} bevel 10 solid {width} d{dx},{dy}"
                print(f"case {case} {widen(fits['unit'], style, width, ((0, 0), (dx, dy)))}")
    for scale, transform in fits.items():
        for width in (5, 4, 3, 6, 9):
            for cap, cap_bits in CAPS.items():
                for join, join_bits in JOINS.items():
                    style = PS_GEOMETRIC | cap_bits | join_bits
                    for figure in ("vee", "horizontal", "diagonal", "zigzag", "reversal"):
                        case = f"{scale} {cap} {join} 10 solid {width} {figure}"
                        print(f"case {case} {widen(transform, style, width, FIGURES[figure])}")
                    case = f"{scale} {cap} {join} 10 solid {width} closed-vee"
                    print(f"case {case} {widen(transform, style, width, FIGURES['vee'], closed=True)}")
        for limit in (1.0, 1.5, 2.0, 4.0):
            style = PS_GEOMETRIC | CAPS["flat"] | JOINS["miter"]
            for figure in ("flat-vee", "vee", "zigzag"):
                case = f"{scale} flat miter {limit} solid 4 {figure}"
                print(f"case {case} {widen(transform, style, 4, FIGURES[figure], limit=limit)}")
        for name, bits in STYLES.items():
            for cap in ("flat", "round", "square"):
                style = PS_GEOMETRIC | bits | CAPS[cap]
                for width in (3, 6) if scale != "unit" else (3, 1, 6):
                    for figure in ("horizontal", "shallow", "zigzag"):
                        case = f"{scale} {cap} round 10 {name} {width} {figure}"
                        print(f"case {case} {widen(transform, style, width, FIGURES[figure])}")
        style = PS_GEOMETRIC | PS_USERSTYLE | CAPS["flat"]
        for figure in ("horizontal", "zigzag"):
            case = f"{scale} flat round 10 user6323 3 {figure}"
            print(f"case {case} {widen(transform, style, 3, FIGURES[figure], entries=(6, 3, 2, 3))}")
            case = f"{scale} flat round 10 user513 3 {figure}"
            print(f"case {case} {widen(transform, style, 3, FIGURES[figure], entries=(5, 1, 3))}")


if __name__ == "__main__":
    main()
