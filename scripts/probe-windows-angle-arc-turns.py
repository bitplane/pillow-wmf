"""Print native AngleArc paths for sweeps of a full turn or more.

Each case moves to (5, 5), records one AngleArc into a path in GM_ADVANCED
under the identity transform, and reads the path back under a 1/16 world
transform, so the integers are device sixteenths. Sweeps just below a turn
give the partial-arc reference for the same start angle. No reference
images are written.

    case radius start sweep drawn=... (type,x16,y16) ...
"""

import ctypes
import platform
from ctypes import wintypes

from windows_wmf_render import bind, check, module_versions, reference_surface

CASES = [
    (20, 0.0, 359.0),
    (20, 0.0, 360.0),
    (20, 30.0, 360.0),
    (20, 30.0, -360.0),
    (20, 45.0, 400.0),
    (20, 45.0, -400.0),
    (20, 10.0, 720.0),
    (20, 10.0, 725.0),
    (20, 90.0, 1080.0),
    (7, 30.0, 360.0),
    (7, 200.0, 450.0),
    (33, 300.0, -540.0),
]


class XForm(ctypes.Structure):
    _fields_ = [(name, ctypes.c_float) for name in ("m11", "m12", "m21", "m22", "dx", "dy")]


def bind_probe(gdi):
    ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
    bind(gdi, "SetGraphicsMode", integer, ptr, integer)
    bind(gdi, "SetWorldTransform", boolean, ptr, ctypes.POINTER(XForm))
    bind(gdi, "SetMapMode", integer, ptr, integer)
    bind(gdi, "BeginPath", boolean, ptr)
    bind(gdi, "EndPath", boolean, ptr)
    bind(gdi, "MoveToEx", boolean, ptr, integer, integer, ptr)
    bind(gdi, "AngleArc", boolean, ptr, integer, integer, wintypes.DWORD, ctypes.c_float, ctypes.c_float)
    bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)


def angle_arc(radius, start, sweep):
    with reference_surface(16, 16) as (gdi, dc, _):
        bind_probe(gdi)
        check(gdi.SetMapMode(dc, 1), "SetMapMode")
        check(gdi.SetGraphicsMode(dc, 2), "SetGraphicsMode")
        check(gdi.BeginPath(dc), "BeginPath")
        check(gdi.MoveToEx(dc, 5, 5, None), "MoveToEx")
        drawn = gdi.AngleArc(dc, 40, 40, radius, start, sweep)
        check(gdi.EndPath(dc), "EndPath")
        check(gdi.SetWorldTransform(dc, ctypes.byref(XForm(1 / 16, 0, 0, 1 / 16, 0, 0))), "SetWorldTransform")
        count = gdi.GetPath(dc, None, None, 0)
        text = "empty"
        if count > 0:
            path = (wintypes.POINT * count)()
            types = (ctypes.c_ubyte * count)()
            check(gdi.GetPath(dc, path, types, count) == count, "GetPath")
            text = " ".join(f"({types[i]},{path[i].x},{path[i].y})" for i in range(count))
        return f"drawn={drawn} {text}"


def main():
    print(f"Windows angle arc turn probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    for radius, start, sweep in CASES:
        print(f"case {radius} {start} {sweep} {angle_arc(radius, start, sweep)}")


if __name__ == "__main__":
    main()
