"""Print the pixels native GDI writes for blends and device transfers under rotated transforms.

Each case sets a world transform in GM_ADVANCED on a fresh 64x64 32-bit DIB
filled with a position-coded background (``background(x, y)``), performs
one AlphaBlend, TransparentBlt or same-DC transfer, and prints every
changed row as ``y x0 hex...`` (RRGGBB per pixel, ``-`` for unchanged
pixels between). The ``identity`` transform gives unrotated references.
No reference images are written.

    case transform name
"""

import ctypes
import math
import platform
import struct
from ctypes import wintypes

from windows_wmf_render import bind, check, module_versions, reference_surface

SIZE = 64


def background(x, y):
    """The initial pixel at (x, y), as BGRA bytes."""
    return bytes((0x80, y * 4, x * 4, 0))


BACKGROUND = b"".join(background(x, y) for y in range(SIZE) for x in range(SIZE))


class XForm(ctypes.Structure):
    _fields_ = [(name, ctypes.c_float) for name in ("m11", "m12", "m21", "m22", "dx", "dy")]


def transforms():
    yield "identity", (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
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


def cases():
    msimg = ctypes.WinDLL("msimg32", use_last_error=True)
    ptr, integer = ctypes.c_void_p, ctypes.c_int
    alpha_blend = bind(msimg, "AlphaBlend", wintypes.BOOL, ptr, *(integer,) * 4, ptr, *(integer,) * 4, wintypes.DWORD)
    transparent = bind(
        msimg, "TransparentBlt", wintypes.BOOL, ptr, *(integer,) * 4, ptr, *(integer,) * 4, wintypes.UINT
    )

    def blend(width, height, constant, per_pixel):
        def draw(gdi, dc):
            source = source_dc(gdi, per_pixel)
            function = constant << 16 | (1 << 24 if per_pixel else 0)
            alpha_blend(dc, 5, 5, width, height, source, 0, 0, 8, 6, function)
            gdi.DeleteDC(source)

        return draw

    yield "alpha-const", blend(8, 6, 128, False)
    yield "alpha-const-stretch", blend(24, 15, 200, False)
    yield "alpha-pixel", blend(8, 6, 255, True)
    yield "alpha-pixel-stretch", blend(24, 15, 255, True)
    yield "alpha-pixel-half", blend(8, 6, 128, True)
    yield "alpha-pixel-half-stretch", blend(24, 15, 77, True)

    def key(width, height):
        def draw(gdi, dc):
            source = source_dc(gdi)
            # Source pixel (2, 1): bytes (60, 40, 55) as BGR.
            transparent(dc, 5, 5, width, height, source, 0, 0, 8, 6, 0x3C2837)
            gdi.DeleteDC(source)

        return draw

    yield "transparent", key(8, 6)
    yield "transparent-stretch", key(24, 15)

    def same_dc(call):
        def draw(gdi, dc):
            call(gdi, dc)

        return draw

    yield "bitblt-self", same_dc(lambda gdi, dc: gdi.BitBlt(dc, 5, 5, 12, 8, dc, 20, 25, 0x00CC0020))
    yield "bitblt-self-xor", same_dc(lambda gdi, dc: gdi.BitBlt(dc, 5, 5, 12, 8, dc, 20, 25, 0x00660046))
    yield "stretchblt-self", same_dc(lambda gdi, dc: gdi.StretchBlt(dc, 5, 5, 24, 15, dc, 20, 25, 8, 6, 0x00CC0020))

    def no_source(rop):
        def draw(gdi, dc):
            gdi.SelectObject(dc, gdi.CreateSolidBrush(0x204080))
            gdi.BitBlt(dc, 5, 5, 30, 20, None, 0, 0, rop)

        return draw

    yield "bitblt-patcopy", no_source(0x00F00021)
    yield "bitblt-dstinvert", no_source(0x00550009)


def run(transform, draw):
    with reference_surface(SIZE, SIZE) as (gdi, dc, bits):
        bind_probe(gdi)
        ctypes.memmove(bits, BACKGROUND, len(BACKGROUND))
        check(gdi.SetMapMode(dc, 1), "SetMapMode")
        check(gdi.SetGraphicsMode(dc, 2), "SetGraphicsMode")
        check(gdi.SetWorldTransform(dc, ctypes.byref(XForm(*transform))), "SetWorldTransform")
        draw(gdi, dc)
        data = ctypes.string_at(bits, SIZE * SIZE * 4)
    rows = []
    for y in range(SIZE):
        row = [data[(y * SIZE + x) * 4 : (y * SIZE + x) * 4 + 4] for x in range(SIZE)]
        changed = [x for x, pixel in enumerate(row) if pixel[:3] != background(x, y)[:3]]
        if changed:
            span = range(changed[0], changed[-1] + 1)
            text = " ".join(
                "-" if row[x][:3] == background(x, y)[:3] else f"{row[x][2]:02x}{row[x][1]:02x}{row[x][0]:02x}"
                for x in span
            )
            rows.append(f"  {y} {changed[0]} {text}")
    return rows


def main():
    print(f"Windows rotated blend probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    for name, transform in transforms():
        for case, draw in cases():
            print(f"case {name} {case}")
            print("\n".join(run(transform, draw)))


if __name__ == "__main__":
    main()
