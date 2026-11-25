"""Print the exact 28.4 path native GDI builds for box shapes in GM_ADVANCED.

Paths are stored in device fixed point. Each shape is recorded into a path
under the transform being studied; the world transform is then replaced by
a 1/16 scale before GetPath, so the returned logical integers are the
device coordinates in sixteenths of a pixel. GM_COMPATIBLE cases, where the
world transform cannot be set, are read under MM_ANISOTROPIC with the same
1/16 page scale instead. No reference images are written.

    case shape (type,x16,y16) ...
"""

import ctypes
import platform
import runpy
from ctypes import wintypes
from pathlib import Path

from windows_wmf_render import bind, check, module_versions, reference_surface

from pillow_wmf.emf import Header
from pillow_wmf.emf.transform import frame_fit
from pillow_wmf.numeric import float32


class XForm(ctypes.Structure):
    _fields_ = [(name, ctypes.c_float) for name in ("m11", "m12", "m21", "m22", "dx", "dy")]


def fixture_scales():
    """The frame fits of the EMF fixtures, plus an offset and a mirrored variant."""
    generator = runpy.run_path(str(Path(__file__).with_name("generate-emf-fixtures.py")))
    scales = {}
    for name, extent in generator["EXTENTS"].items():
        fit = frame_fit(Header.create((0, 0, -1, -1), generator["frame"](extent)), (0, 0, 128, 128))
        scales[name] = (fit[0], fit[3], fit[4], fit[5])
    up = scales["up"]
    scales["offset"] = (up[0], up[1], 0.3125, -0.4375)
    scales["flip"] = (-up[0], up[1], 128.0, 0.0)
    scales["flip-y"] = (up[0], -up[1], 0.0, 128.0)
    scales["flip-xy"] = (-up[0], -up[1], 128.0, 128.0)
    # MM_LOMETRIC played 1:1: 0.1 mm units with y up, as in emf-page-lometric.
    scales["lometric"] = (float32(1024 / 2710), float32(-768 / 2030), 0.0, 0.0)
    return scales


BOXES = (
    (6, 6, 30, 22),
    (36, 6, 60, 22),
    (11, 11, 53, 40),
    (3, 3, 16, 12),
    (5, 7, 6, 9),
    (8, 3, 9, 30),
    (10, 10, 41, 41),
)


def shapes(box):
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    yield "rectangle", ("Rectangle", *box)
    yield "ellipse", ("Ellipse", *box)
    yield "roundrect", ("RoundRect", *box, max(1, width // 3), max(1, height // 3))
    radials = (right, top, left, bottom)
    yield "arc", ("Arc", *box, *radials)
    yield "pie", ("Pie", *box, *radials)
    yield "chord", ("Chord", *box, right, top + height // 3, left, bottom)


def bind_probe(gdi):
    ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
    bind(gdi, "SetGraphicsMode", integer, ptr, integer)
    bind(gdi, "SetWorldTransform", boolean, ptr, ctypes.POINTER(XForm))
    bind(gdi, "ModifyWorldTransform", boolean, ptr, ctypes.POINTER(XForm), wintypes.DWORD)
    bind(gdi, "SetMapMode", integer, ptr, integer)
    bind(gdi, "SetWindowExtEx", boolean, ptr, integer, integer, ptr)
    bind(gdi, "SetViewportExtEx", boolean, ptr, integer, integer, ptr)
    bind(gdi, "BeginPath", boolean, ptr)
    bind(gdi, "EndPath", boolean, ptr)
    bind(gdi, "AbortPath", boolean, ptr)
    bind(gdi, "FlattenPath", boolean, ptr)
    bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)
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


def advanced_case(gdi, dc, transform, call, *, flatten=False):
    check(gdi.SetGraphicsMode(dc, 2), "SetGraphicsMode")
    check(
        gdi.SetWorldTransform(dc, ctypes.byref(XForm(transform[0], 0, 0, transform[1], transform[2], transform[3]))),
        "SetWorldTransform",
    )
    check(gdi.BeginPath(dc), "BeginPath")
    drawn = getattr(gdi, call[0])(dc, *call[1:])
    check(gdi.EndPath(dc), "EndPath")
    if flatten:
        check(gdi.FlattenPath(dc), "FlattenPath")
    check(gdi.SetWorldTransform(dc, ctypes.byref(XForm(1 / 16, 0, 0, 1 / 16, 0, 0))), "SetWorldTransform")
    return f"drawn={drawn} " + read_path(gdi, dc)


def compatible_case(gdi, dc, call):
    check(gdi.BeginPath(dc), "BeginPath")
    drawn = getattr(gdi, call[0])(dc, *call[1:])
    check(gdi.EndPath(dc), "EndPath")
    check(gdi.SetMapMode(dc, 8), "SetMapMode")
    check(gdi.SetWindowExtEx(dc, 16, 16, None), "SetWindowExtEx")
    check(gdi.SetViewportExtEx(dc, 1, 1, None), "SetViewportExtEx")
    return f"drawn={drawn} " + read_path(gdi, dc)


def main():
    print(f"Windows advanced path probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    scales = fixture_scales()
    print(f"Scales (m11, m22, dx, dy): {scales}")
    for box in BOXES:
        for shape, call in shapes(box):
            with reference_surface(16, 16) as (gdi, dc, _):
                bind_probe(gdi)
                # The reference DC starts MM_ANISOTROPIC at 1:1; reset to MM_TEXT.
                check(gdi.SetMapMode(dc, 1), "SetMapMode")
                print(f"compatible box={box} {shape} {compatible_case(gdi, dc, call)}")
            for name, transform in scales.items():
                with reference_surface(16, 16) as (gdi, dc, _):
                    bind_probe(gdi)
                    check(gdi.SetMapMode(dc, 1), "SetMapMode")
                    print(f"{name} box={box} {shape} {advanced_case(gdi, dc, transform, call)}")
                if shape in ("ellipse", "arc", "roundrect"):
                    # Flattened in the device, as drawing flattens curves.
                    with reference_surface(16, 16) as (gdi, dc, _):
                        bind_probe(gdi)
                        check(gdi.SetMapMode(dc, 1), "SetMapMode")
                        flat = advanced_case(gdi, dc, transform, call, flatten=True)
                        print(f"{name} box={box} flat-{shape} {flat}")


if __name__ == "__main__":
    main()
