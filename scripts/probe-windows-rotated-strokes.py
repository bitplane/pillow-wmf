"""Print the pixels native GDI draws for wide pens under rotated transforms.

Each case draws one figure with a solid CreatePen pen in GM_ADVANCED on a
fresh 128x128 32-bit DIB and prints the rows it changed as ``y x0 mask``,
where the mask has ``#`` for each changed pixel from ``x0``. Figures are
open lines in sixteen directions and a closed rectangle. No reference
images are written.

    case transform width figure points=...
"""

import ctypes
import math
import platform
from ctypes import wintypes

from windows_wmf_render import bind, check, module_versions, reference_surface

SIZE = 128


class XForm(ctypes.Structure):
    _fields_ = [(name, ctypes.c_float) for name in ("m11", "m12", "m21", "m22", "dx", "dy")]


def transforms():
    # The rotation fixture's composed 2.5x world, as float32 values.
    yield (
        "fixture-2-5",
        (
            2.2741613388061523,
            1.0607258081436157,
            -1.060458779335022,
            2.274733781814575,
            40.14814758300781,
            -10.03956413269043,
        ),
    )
    angle = math.radians(25)
    yield "r25", (math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle), 64.0, 30.0)


def figures(name):
    if name == "fixture-2-5":
        yield "rectangle", ((4, 4), (24, 4), (24, 16), (4, 16), (4, 4))
        centre, radius = (14, 14), 10
    else:
        yield "rectangle", ((10, 10), (60, 10), (60, 40), (10, 40), (10, 10))
        centre, radius = (20, 60), 18
    for index in range(16):
        angle = math.radians(index * 22.5 + 3)
        end = (round(centre[0] + radius * math.cos(angle)), round(centre[1] + radius * math.sin(angle)))
        yield f"line{index}", (centre, end)


def bind_probe(gdi):
    ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
    bind(gdi, "SetGraphicsMode", integer, ptr, integer)
    bind(gdi, "SetWorldTransform", boolean, ptr, ctypes.POINTER(XForm))
    bind(gdi, "SetMapMode", integer, ptr, integer)
    bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
    bind(gdi, "SelectObject", ptr, ptr, ptr)
    bind(gdi, "DeleteObject", boolean, ptr)
    bind(gdi, "Polyline", boolean, ptr, ctypes.POINTER(wintypes.POINT), integer)


def draw(transform, width, points):
    with reference_surface(SIZE, SIZE) as (gdi, dc, bits):
        bind_probe(gdi)
        check(gdi.SetMapMode(dc, 1), "SetMapMode")
        check(gdi.SetGraphicsMode(dc, 2), "SetGraphicsMode")
        check(gdi.SetWorldTransform(dc, ctypes.byref(XForm(*transform))), "SetWorldTransform")
        pen = check(gdi.CreatePen(0, width, 0), "CreatePen")
        previous = gdi.SelectObject(dc, pen)
        array = (wintypes.POINT * len(points))(*[wintypes.POINT(*p) for p in points])
        check(gdi.Polyline(dc, array, len(points)), "Polyline")
        gdi.SelectObject(dc, previous)
        gdi.DeleteObject(pen)
        data = ctypes.string_at(bits, SIZE * SIZE * 4)
    rows = []
    for y in range(SIZE):
        row = data[y * SIZE * 4 : (y + 1) * SIZE * 4]
        changed = [x for x in range(SIZE) if row[4 * x : 4 * x + 4] != b"\xff\xff\xff\xff"]
        if changed:
            mask = "".join("#" if x in changed else "." for x in range(changed[0], changed[-1] + 1))
            rows.append(f"  {y} {changed[0]} {mask}")
    return rows


def main():
    print(f"Windows rotated stroke probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    for name, transform in transforms():
        for width in (1, 2, 3):
            for figure, points in figures(name):
                print(f"case {name} {width} {figure} points={points}")
                print("\n".join(draw(transform, width, points)))


if __name__ == "__main__":
    main()
