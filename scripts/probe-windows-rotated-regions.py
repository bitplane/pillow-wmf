"""Print the pixels native GDI clips and paints for regions under rotated transforms.

Each case sets a world transform in GM_ADVANCED on a fresh 64x64 32-bit DIB.
Clip cases build the clip under the transform, restore the identity
transform and fill the whole surface, so the changed pixels are the clip
region itself. Region cases paint a region under the transform. Rows are
printed as ``y x0 mask`` with ``#`` for each changed pixel from ``x0``. No
reference images are written.

    case transform name
"""

import ctypes
import math
import platform
from ctypes import wintypes

from windows_wmf_render import bind, check, module_versions, reference_surface

SIZE = 64


class XForm(ctypes.Structure):
    _fields_ = [(name, ctypes.c_float) for name in ("m11", "m12", "m21", "m22", "dx", "dy")]


def transforms():
    angle = math.radians(25)
    yield "r25", (math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle), 30.0, 5.0)
    angle = math.radians(-40)
    yield "r-40", (math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle), 10.0, 30.0)
    yield "shear", (1.0, 0.0, 0.4, 1.0, 10.0, 10.0)
    yield "general", (0.9, 0.35, -0.2, 1.1, 20.0, 8.0)
    yield "scaled-r30", (1.5 * 0.8660254, 1.5 * 0.5, -1.2 * 0.5, 1.2 * 0.8660254, 30.0, 2.0)


def bind_probe(gdi):
    ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
    bind(gdi, "SetGraphicsMode", integer, ptr, integer)
    bind(gdi, "SetWorldTransform", boolean, ptr, ctypes.POINTER(XForm))
    bind(gdi, "SetMapMode", integer, ptr, integer)
    bind(gdi, "IntersectClipRect", integer, ptr, integer, integer, integer, integer)
    bind(gdi, "ExcludeClipRect", integer, ptr, integer, integer, integer, integer)
    bind(gdi, "OffsetClipRgn", integer, ptr, integer, integer)
    bind(gdi, "SelectClipRgn", integer, ptr, ptr)
    bind(gdi, "CreateRectRgn", ptr, integer, integer, integer, integer)
    bind(gdi, "CombineRgn", integer, ptr, ptr, ptr, integer)
    bind(gdi, "DeleteObject", boolean, ptr)
    bind(gdi, "GetStockObject", ptr, integer)
    bind(gdi, "SelectObject", ptr, ptr, ptr)
    bind(gdi, "PatBlt", boolean, ptr, integer, integer, integer, integer, wintypes.DWORD)
    bind(gdi, "FillRgn", boolean, ptr, ptr, ptr)
    bind(gdi, "PaintRgn", boolean, ptr, ptr)
    bind(gdi, "InvertRgn", boolean, ptr, ptr)
    bind(gdi, "FrameRgn", boolean, ptr, ptr, ptr, integer, integer)


IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def compound(gdi):
    first = gdi.CreateRectRgn(5, 5, 25, 20)
    second = gdi.CreateRectRgn(15, 15, 40, 35)
    gdi.CombineRgn(first, first, second, 2)  # RGN_OR
    gdi.DeleteObject(second)
    return first


def cases():
    def intersect(gdi, dc):
        gdi.IntersectClipRect(dc, 5, 5, 35, 25)

    def exclude(gdi, dc):
        gdi.ExcludeClipRect(dc, 5, 5, 35, 25)

    def intersect_twice(gdi, dc):
        gdi.IntersectClipRect(dc, 5, 5, 35, 25)
        gdi.IntersectClipRect(dc, 15, 0, 50, 20)

    def intersect_offset(gdi, dc):
        gdi.IntersectClipRect(dc, 5, 5, 35, 25)
        gdi.OffsetClipRgn(dc, 6, 3)

    def select_region(gdi, dc):
        region = gdi.CreateRectRgn(5, 5, 35, 25)
        gdi.SelectClipRgn(dc, region)
        gdi.DeleteObject(region)

    def thin(gdi, dc):
        gdi.IntersectClipRect(dc, 10, 10, 11, 40)

    yield "clip-intersect", intersect, True
    yield "clip-exclude", exclude, True
    yield "clip-intersect-twice", intersect_twice, True
    yield "clip-intersect-offset", intersect_offset, True
    yield "clip-select-region", select_region, True
    yield "clip-thin", thin, True

    def fill(gdi, dc):
        region = gdi.CreateRectRgn(5, 5, 35, 25)
        gdi.FillRgn(dc, region, gdi.GetStockObject(4))
        gdi.DeleteObject(region)

    def fill_compound(gdi, dc):
        region = compound(gdi)
        gdi.FillRgn(dc, region, gdi.GetStockObject(4))
        gdi.DeleteObject(region)

    def paint(gdi, dc):
        gdi.SelectObject(dc, gdi.GetStockObject(2))  # GRAY_BRUSH
        region = gdi.CreateRectRgn(5, 5, 35, 25)
        gdi.PaintRgn(dc, region)
        gdi.DeleteObject(region)

    def invert(gdi, dc):
        region = compound(gdi)
        gdi.InvertRgn(dc, region)
        gdi.DeleteObject(region)

    def frame(gdi, dc):
        region = compound(gdi)
        gdi.FrameRgn(dc, region, gdi.GetStockObject(4), 2, 3)
        gdi.DeleteObject(region)

    yield "fill-rect", fill, False
    yield "fill-compound", fill_compound, False
    yield "paint-rect", paint, False
    yield "invert-compound", invert, False
    yield "frame-compound", frame, False


def run(transform, draw, clip):
    with reference_surface(SIZE, SIZE) as (gdi, dc, bits):
        bind_probe(gdi)
        check(gdi.SetMapMode(dc, 1), "SetMapMode")
        check(gdi.SetGraphicsMode(dc, 2), "SetGraphicsMode")
        check(gdi.SetWorldTransform(dc, ctypes.byref(XForm(*transform))), "SetWorldTransform")
        draw(gdi, dc)
        if clip:
            check(gdi.SetWorldTransform(dc, ctypes.byref(XForm(*IDENTITY))), "SetWorldTransform")
            gdi.SelectObject(dc, gdi.GetStockObject(4))  # BLACK_BRUSH
            gdi.PatBlt(dc, 0, 0, SIZE, SIZE, 0x00F00021)
        data = ctypes.string_at(bits, SIZE * SIZE * 4)
    rows = []
    for y in range(SIZE):
        row = data[y * SIZE * 4 : (y + 1) * SIZE * 4]
        values = [row[4 * x : 4 * x + 3] for x in range(SIZE)]
        changed = [x for x in range(SIZE) if values[x] != b"\xff\xff\xff"]
        if changed:
            marks = {b"\x00\x00\x00": "#", b"\x80\x80\x80": "g"}
            mask = "".join(
                marks.get(values[x], "?") if x in changed else "." for x in range(changed[0], changed[-1] + 1)
            )
            rows.append(f"  {y} {changed[0]} {mask}")
    return rows


def main():
    print(f"Windows rotated region probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    for name, transform in transforms():
        for case, draw, clip in cases():
            print(f"case {name} {case}")
            print("\n".join(run(transform, draw, clip)))


if __name__ == "__main__":
    main()
