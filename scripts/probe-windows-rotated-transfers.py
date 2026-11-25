"""Print the pixels native GDI writes for transfers and gradients under rotated transforms.

Each case sets a world transform in GM_ADVANCED on a fresh 64x64 32-bit DIB
filled with a light grey, performs one transfer, gradient or arc, and
prints every changed row as ``y x0 hex...`` (RRGGBB per pixel, ``-`` for
unchanged pixels between). No reference images are written.

    case transform name
"""

import ctypes
import math
import platform
import struct
from ctypes import wintypes

from windows_wmf_render import bind, check, module_versions, reference_surface

SIZE = 64
BACKGROUND = b"\xc0\xc0\xc0\x00"


class XForm(ctypes.Structure):
    _fields_ = [(name, ctypes.c_float) for name in ("m11", "m12", "m21", "m22", "dx", "dy")]


class TriVertex(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)] + [(c, ctypes.c_ushort) for c in "rgba"]


def transforms():
    angle = math.radians(25)
    yield "r25", (math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle), 30.0, 5.0)
    yield "shear", (1.0, 0.0, 0.4, 1.0, 10.0, 10.0)
    yield "general", (0.9, 0.35, -0.2, 1.1, 20.0, 8.0)


def bind_probe(gdi):
    ptr, integer, boolean, dword = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL, wintypes.DWORD
    bind(gdi, "SetGraphicsMode", integer, ptr, integer)
    bind(gdi, "SetWorldTransform", boolean, ptr, ctypes.POINTER(XForm))
    bind(gdi, "SetMapMode", integer, ptr, integer)
    bind(gdi, "GetStockObject", ptr, integer)
    bind(gdi, "SelectObject", ptr, ptr, ptr)
    bind(gdi, "DeleteObject", boolean, ptr)
    bind(gdi, "CreateHatchBrush", ptr, integer, dword)
    bind(gdi, "CreateSolidBrush", ptr, dword)
    bind(gdi, "CreateCompatibleDC", ptr, ptr)
    bind(gdi, "DeleteDC", boolean, ptr)
    bind(gdi, "CreateDIBSection", ptr, ptr, ptr, wintypes.UINT, ctypes.POINTER(ptr), ptr, dword)
    bind(gdi, "CreateBitmap", ptr, integer, integer, wintypes.UINT, wintypes.UINT, ptr)
    bind(gdi, "PatBlt", boolean, ptr, *(integer,) * 4, dword)
    bind(gdi, "BitBlt", boolean, ptr, *(integer,) * 4, ptr, integer, integer, dword)
    bind(gdi, "StretchBlt", boolean, ptr, *(integer,) * 4, ptr, *(integer,) * 4, dword)
    bind(gdi, "MaskBlt", boolean, ptr, *(integer,) * 4, ptr, integer, integer, ptr, integer, integer, dword)
    bind(gdi, "StretchDIBits", integer, ptr, *(integer,) * 8, ptr, ptr, wintypes.UINT, dword)
    bind(
        gdi,
        "SetDIBitsToDevice",
        integer,
        ptr,
        integer,
        integer,
        dword,
        dword,
        integer,
        integer,
        wintypes.UINT,
        wintypes.UINT,
        ptr,
        ptr,
        wintypes.UINT,
    )
    bind(gdi, "SetStretchBltMode", integer, ptr, integer)
    bind(gdi, "MoveToEx", boolean, ptr, integer, integer, ptr)
    bind(gdi, "AngleArc", boolean, ptr, integer, integer, dword, ctypes.c_float, ctypes.c_float)
    bind(gdi, "ArcTo", boolean, ptr, *(integer,) * 8)
    bind(gdi, "SetArcDirection", integer, ptr, integer)


def dib_info(width, height, depth=32):
    return struct.pack("<IiiHHIIiiII", 40, width, height, 1, depth, 0, 0, 0, 0, 0, 0)


def source_dc(gdi):
    dc = gdi.CreateCompatibleDC(None)
    info = ctypes.create_string_buffer(dib_info(8, -6), 64)
    bits = ctypes.c_void_p()
    bitmap = gdi.CreateDIBSection(dc, info, 0, ctypes.byref(bits), None, 0)
    pixels = b"".join(
        bytes(((x * 30) % 256, (y * 40) % 256, (x * 13 + y * 29) % 256, 0)) for y in range(6) for x in range(8)
    )
    ctypes.memmove(bits, pixels, len(pixels))
    gdi.SelectObject(dc, bitmap)
    return dc


PACKED = dib_info(4, 3, 24) + bytes((i * 23 + 5) % 256 for i in range(36))


def cases():
    def pat(rop, brush):
        def draw(gdi, dc):
            gdi.SelectObject(dc, brush(gdi))
            gdi.PatBlt(dc, 5, 5, 30, 20, rop)

        return draw

    yield "patblt-copy", pat(0x00F00021, lambda gdi: gdi.CreateSolidBrush(0x204080))
    yield "patblt-hatch", pat(0x00F00021, lambda gdi: gdi.CreateHatchBrush(5, 0x0000FF))
    yield "patblt-invert", pat(0x00550009, lambda gdi: gdi.GetStockObject(0))
    yield "patblt-patinvert", pat(0x005A0049, lambda gdi: gdi.CreateSolidBrush(0x00FF00))

    def blt(rop):
        def draw(gdi, dc):
            source = source_dc(gdi)
            gdi.BitBlt(dc, 5, 5, 8, 6, source, 0, 0, rop)
            gdi.DeleteDC(source)

        return draw

    yield "bitblt-copy", blt(0x00CC0020)
    yield "bitblt-srcinvert", blt(0x00660046)
    yield "bitblt-srcand", blt(0x008800C6)

    def stretch(rop, mode=3):
        def draw(gdi, dc):
            source = source_dc(gdi)
            gdi.SetStretchBltMode(dc, mode)
            gdi.StretchBlt(dc, 5, 5, 24, 15, source, 0, 0, 8, 6, rop)
            gdi.DeleteDC(source)

        return draw

    yield "stretchblt-copy", stretch(0x00CC0020)
    yield "stretchblt-srcpaint", stretch(0x00EE0086)
    yield "stretchblt-halftone", stretch(0x00CC0020, 4)

    def mask(gdi, dc):
        source = source_dc(gdi)
        mono = gdi.CreateBitmap(
            8, 6, 1, 1, ctypes.create_string_buffer(bytes((0xF0, 0, 0x0F, 0, 0xF0, 0, 0x0F, 0, 0xF0, 0, 0x0F, 0)), 12)
        )
        gdi.MaskBlt(dc, 5, 5, 8, 6, source, 0, 0, mono, 0, 0, 0xAACC0020)
        gdi.DeleteDC(source)

    yield "maskblt", mask

    def dib(rop):
        def draw(gdi, dc):
            gdi.StretchDIBits(dc, 5, 5, 20, 15, 0, 0, 4, 3, PACKED[40:], PACKED[:40], 0, rop)

        return draw

    yield "stretchdib-copy", dib(0x00CC0020)
    yield "stretchdib-srcinvert", dib(0x00660046)

    def setdib(gdi, dc):
        gdi.SetDIBitsToDevice(dc, 5, 5, 4, 3, 0, 0, 0, 3, PACKED[40:], PACKED[:40], 0)

    yield "setdibits", setdib

    def gradient(mode):
        def draw(gdi, dc):
            msimg = ctypes.WinDLL("msimg32", use_last_error=True)
            fill = bind(
                msimg,
                "GradientFill",
                wintypes.BOOL,
                ctypes.c_void_p,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.DWORD,
                wintypes.DWORD,
            )
            vertices = (TriVertex * 3)(
                TriVertex(4, 4, 0xF000, 0x1000, 0, 0),
                TriVertex(36, 24, 0x1000, 0xE000, 0xF000, 0),
                TriVertex(8, 30, 0, 0, 0xF000, 0),
            )
            if mode == 2:
                fill(dc, vertices, 3, (wintypes.DWORD * 3)(0, 1, 2), 1, 2)
            else:
                fill(dc, vertices, 2, (wintypes.DWORD * 2)(0, 1), 1, mode)

        return draw

    yield "gradient-h", gradient(0)
    yield "gradient-v", gradient(1)
    yield "gradient-triangle", gradient(2)

    def angle(gdi, dc):
        gdi.MoveToEx(dc, 2, 2, None)
        gdi.AngleArc(dc, 20, 20, 12, 30.0, 200.0)

    def arc_to(direction):
        def draw(gdi, dc):
            gdi.SetArcDirection(dc, direction)
            gdi.MoveToEx(dc, 2, 2, None)
            gdi.ArcTo(dc, 5, 5, 35, 25, 35, 15, 5, 5)

        return draw

    yield "anglearc", angle
    yield "arcto", arc_to(1)
    yield "arcto-clockwise", arc_to(2)


def run(transform, draw):
    with reference_surface(SIZE, SIZE) as (gdi, dc, bits):
        bind_probe(gdi)
        ctypes.memmove(bits, BACKGROUND * (SIZE * SIZE), SIZE * SIZE * 4)
        check(gdi.SetMapMode(dc, 1), "SetMapMode")
        check(gdi.SetGraphicsMode(dc, 2), "SetGraphicsMode")
        check(gdi.SetWorldTransform(dc, ctypes.byref(XForm(*transform))), "SetWorldTransform")
        draw(gdi, dc)
        data = ctypes.string_at(bits, SIZE * SIZE * 4)
    rows = []
    for y in range(SIZE):
        row = [data[(y * SIZE + x) * 4 : (y * SIZE + x) * 4 + 4] for x in range(SIZE)]
        changed = [x for x, pixel in enumerate(row) if pixel[:3] != BACKGROUND[:3]]
        if changed:
            pixels = row[changed[0] : changed[-1] + 1]
            text = " ".join("-" if p[:3] == BACKGROUND[:3] else f"{p[2]:02x}{p[1]:02x}{p[0]:02x}" for p in pixels)
            rows.append(f"  {y} {changed[0]} {text}")
    return rows


def main():
    print(f"Windows rotated transfer probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    for name, transform in transforms():
        for case, draw in cases():
            print(f"case {name} {case}")
            print("\n".join(run(transform, draw)))


if __name__ == "__main__":
    main()
