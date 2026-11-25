"""Print native 28.4 paths and world matrices under rotated and sheared transforms.

Each transform is built as EMF playback builds it: the fixture frame fit is
set first and the record's transform is left-multiplied onto it. The
resulting world matrix is printed as float32 bit patterns, then each shape
is recorded into a path and read back under a 1/16 world transform, so the
returned integers are device sixteenths. No reference images are written.

    world name m11 m12 m21 m22 dx dy   (hex float32)
    case name shape drawn=... (type,x16,y16) ...
"""

import ctypes
import math
import platform
import runpy
import struct
from ctypes import wintypes
from pathlib import Path

from windows_wmf_render import bind, check, module_versions, reference_surface

from pillow_wmf.emf import Header
from pillow_wmf.emf.transform import frame_fit

MWT_LEFTMULTIPLY = 2


class XForm(ctypes.Structure):
    _fields_ = [(name, ctypes.c_float) for name in ("m11", "m12", "m21", "m22", "dx", "dy")]


def fits():
    generator = runpy.run_path(str(Path(__file__).with_name("generate-emf-fixtures.py")))
    result = {}
    for name in ("unit", "up-2-5"):
        extent = generator["EXTENTS"][name]
        fit = frame_fit(Header.create((0, 0, -1, -1), generator["frame"](extent)), (0, 0, 128, 128))
        result[name] = (fit, extent / 128)
    return result


def rotation(degrees, dx=0.0, dy=0.0):
    angle = math.radians(degrees)
    cos, sin = math.cos(angle), math.sin(angle)
    return (cos, sin, -sin, cos, dx, dy)


def transforms():
    """(name, fit name, [record transforms applied in order, each left-multiplied])."""
    for fit in ("unit", "up-2-5"):
        extent = 51 if fit == "up-2-5" else 128
        # The rotation fixture: 25 degrees about an offset origin, then a shear.
        fixture = rotation(25, round(40 * extent / 128), round(-10 * extent / 128))
        yield f"fixture-{fit}", fit, [fixture]
        yield f"fixture-shear-{fit}", fit, [fixture, (1.0, 0.0, 0.4, 1.0, 0.0, 0.0)]
    for degrees in (10, 30, 45, 60, 90, 120, 180, 200, 270, 330, -15):
        yield f"rotate-{degrees}", "unit", [rotation(degrees, 64.0, 64.0)]
    yield "shear-x", "unit", [(1.0, 0.0, 0.4, 1.0, 10.0, 5.0)]
    yield "shear-y", "unit", [(1.0, 0.3, 0.0, 1.0, 5.0, 10.0)]
    yield "general", "unit", [(0.9, 0.35, -0.2, 1.1, 30.25, 20.5)]


def shapes(scale):
    def u(value):
        return round(value * scale)

    def box(left, top, right, bottom):
        return u(left), u(top), u(right), u(bottom)

    # The rotation fixture's shapes, in its logical units.
    yield "rectangle", ("Rectangle", *box(10, 10, 60, 40))
    yield "ellipse", ("Ellipse", *box(10, 50, 60, 80))
    yield "pie", ("Pie", *box(64, 10, 100, 46), *box(100, 28, 64, 10))
    yield "roundrect", ("RoundRect", *box(64, 50, 100, 80), 10, 10)
    yield "line", ("Polyline", ((u(0), u(90)), (u(90), u(90))))
    # Point mapping: many vertices exercise the float evaluation order.
    yield "points", ("Polyline", tuple((u(x), u((x * 37) % 97 - 20)) for x in range(-20, 120, 7)))
    yield "small-ellipse", ("Ellipse", *box(3, 4, 14, 11))
    yield "arc", ("Arc", *box(20, 20, 50, 44), *box(50, 20, 20, 44))
    yield "chord", ("Chord", *box(20, 20, 50, 44), *box(50, 30, 20, 44))


def bind_probe(gdi):
    ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
    bind(gdi, "SetGraphicsMode", integer, ptr, integer)
    bind(gdi, "SetWorldTransform", boolean, ptr, ctypes.POINTER(XForm))
    bind(gdi, "ModifyWorldTransform", boolean, ptr, ctypes.POINTER(XForm), wintypes.DWORD)
    bind(gdi, "GetWorldTransform", boolean, ptr, ctypes.POINTER(XForm))
    bind(gdi, "SetMapMode", integer, ptr, integer)
    bind(gdi, "BeginPath", boolean, ptr)
    bind(gdi, "EndPath", boolean, ptr)
    bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)
    bind(gdi, "Polyline", boolean, ptr, ctypes.POINTER(wintypes.POINT), integer)
    for name in ("Rectangle", "Ellipse"):
        bind(gdi, name, boolean, ptr, integer, integer, integer, integer)
    bind(gdi, "RoundRect", boolean, ptr, *(integer,) * 6)
    for name in ("Arc", "Pie", "Chord"):
        bind(gdi, name, boolean, ptr, *(integer,) * 8)


def read_path(gdi, dc):
    count = gdi.GetPath(dc, None, None, 0)
    if count <= 0:
        return "empty"
    points = (wintypes.POINT * count)()
    types = (ctypes.c_ubyte * count)()
    check(gdi.GetPath(dc, points, types, count) == count, "GetPath")
    return " ".join(f"({types[i]},{points[i].x},{points[i].y})" for i in range(count))


def hex_floats(xform):
    values = (xform.m11, xform.m12, xform.m21, xform.m22, xform.dx, xform.dy)
    return " ".join(struct.pack("<f", value).hex() for value in values)


def setup(gdi, dc, fit, records):
    check(gdi.SetMapMode(dc, 1), "SetMapMode")
    check(gdi.SetGraphicsMode(dc, 2), "SetGraphicsMode")
    check(gdi.SetWorldTransform(dc, ctypes.byref(XForm(*fit))), "SetWorldTransform")
    for record in records:
        check(gdi.ModifyWorldTransform(dc, ctypes.byref(XForm(*record)), MWT_LEFTMULTIPLY), "ModifyWorldTransform")


def main():
    print(f"Windows rotated path probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    available = fits()
    for name, fit_name, records in transforms():
        fit, scale = available[fit_name]
        with reference_surface(16, 16) as (gdi, dc, _):
            bind_probe(gdi)
            setup(gdi, dc, fit, records)
            world = XForm()
            check(gdi.GetWorldTransform(dc, ctypes.byref(world)), "GetWorldTransform")
            print(f"world {name} fit={fit} records={records} {hex_floats(world)}")
        for shape, call in shapes(scale):
            with reference_surface(16, 16) as (gdi, dc, _):
                bind_probe(gdi)
                setup(gdi, dc, fit, records)
                check(gdi.BeginPath(dc), "BeginPath")
                if call[0] == "Polyline":
                    points = (wintypes.POINT * len(call[1]))(*[wintypes.POINT(*p) for p in call[1]])
                    drawn = gdi.Polyline(dc, points, len(call[1]))
                else:
                    drawn = getattr(gdi, call[0])(dc, *call[1:])
                check(gdi.EndPath(dc), "EndPath")
                check(gdi.SetWorldTransform(dc, ctypes.byref(XForm(1 / 16, 0, 0, 1 / 16, 0, 0))), "SetWorldTransform")
                print(f"case {name} {shape} call={call} drawn={drawn} {read_path(gdi, dc)}")


if __name__ == "__main__":
    main()
