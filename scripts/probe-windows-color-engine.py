"""Print native HALFTONE colours under colourfulness, tint and illuminant adjustments.

A 32x32 32-bit source holds 1024 colours: the 256 greys, the 216-colour
6x6x6 cube, red, green and blue ramps of 128 levels each, and 168
pseudo-random colours. Each case selects a COLORADJUSTMENT, stretches the
source four times with StretchDIBits in HALFTONE mode onto a 128x128 DIB,
and prints the colour at each block's centre, in source order, as RRGGBB
hex, and the number of blocks whose 16 pixels are not all equal. No
reference images are written.

    case name applied=... mixed=... {values}
      RRGGBB ...
"""

import ctypes
import platform
from ctypes import wintypes

from windows_wmf_render import bind, check, module_versions, reference_surface

SOURCE, SCALE = 32, 4
SIZE = SOURCE * SCALE


class ColorAdjustment(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ushort) for name in ("size", "flags", "illuminant", "rg", "gg", "bg", "black", "white")]
    _fields_ += [(name, ctypes.c_short) for name in ("contrast", "brightness", "colorfulness", "tint")]


class BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("width", wintypes.LONG),
        ("height", wintypes.LONG),
        ("planes", wintypes.WORD),
        ("bit_count", wintypes.WORD),
        ("compression", wintypes.DWORD),
        ("size_image", wintypes.DWORD),
        ("xppm", wintypes.LONG),
        ("yppm", wintypes.LONG),
        ("used", wintypes.DWORD),
        ("important", wintypes.DWORD),
    ]


def colours():
    result = [(v, v, v) for v in range(256)]
    levels = (0, 51, 102, 153, 204, 255)
    result += [(r, g, b) for r in levels for g in levels for b in levels]
    for channel in range(3):
        for i in range(128):
            value = [0, 0, 0]
            value[channel] = 2 * i + 1
            result.append(tuple(value))
    seed = 12345
    while len(result) < SOURCE * SOURCE:
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        result.append(((seed >> 16) & 255, (seed >> 8) & 255, seed & 255))
    return result


NEUTRAL = dict(flags=0, illuminant=0, rg=10000, gg=10000, bg=10000, black=0, white=10000)
NEUTRAL |= dict(contrast=0, brightness=0, colorfulness=0, tint=0)


def cases():
    for value in (-100, -75, -50, -25, -10, -1, 1, 10, 25, 50, 75, 100):
        yield f"colorfulness{value}", NEUTRAL | dict(colorfulness=value)
    for value in (-100, -50, -10, -1, 1, 10, 50, 100):
        yield f"tint{value}", NEUTRAL | dict(tint=value)
    for value in range(1, 9):
        yield f"illuminant{value}", NEUTRAL | dict(illuminant=value)
    yield "colorfulness50-tint50", NEUTRAL | dict(colorfulness=50, tint=50)
    yield "colorfulness-50-tint-30", NEUTRAL | dict(colorfulness=-50, tint=-30)
    yield "illuminant1-colorfulness50", NEUTRAL | dict(illuminant=1, colorfulness=50)
    yield "illuminant8-tint30", NEUTRAL | dict(illuminant=8, tint=30)
    yield "contrast50-colorfulness50", NEUTRAL | dict(contrast=50, colorfulness=50)
    yield "brightness30-tint30", NEUTRAL | dict(brightness=30, tint=30)
    yield "gamma20000-colorfulness50", NEUTRAL | dict(rg=20000, gg=20000, bg=20000, colorfulness=50)
    yield "gamma-red-tint10", NEUTRAL | dict(rg=15000, tint=10)
    yield "reference-colorfulness30", NEUTRAL | dict(black=1000, white=9000, colorfulness=30)
    yield "negative-colorfulness30", NEUTRAL | dict(flags=1, colorfulness=30)
    yield "log-tint-20", NEUTRAL | dict(flags=2, tint=-20)
    yield "illuminant3-contrast-40", NEUTRAL | dict(illuminant=3, contrast=-40)
    yield "everything", NEUTRAL | dict(illuminant=2, rg=12000, contrast=20, brightness=-10, colorfulness=40, tint=-60)


def main():
    print(f"Windows colour engine probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    pixels = b"".join(bytes((b, g, r, 0)) for r, g, b in colours())
    header = BitmapInfoHeader(40, SOURCE, -SOURCE, 1, 32, 0, len(pixels), 0, 0, 0, 0)
    for name, values in cases():
        with reference_surface(SIZE, SIZE) as (gdi, dc, bits):
            ptr, integer = ctypes.c_void_p, ctypes.c_int
            bind(gdi, "SetColorAdjustment", wintypes.BOOL, ptr, ctypes.POINTER(ColorAdjustment))
            bind(gdi, "SetStretchBltMode", integer, ptr, integer)
            bind(gdi, "StretchDIBits", integer, ptr, *(integer,) * 8, ptr, ptr, wintypes.UINT, wintypes.DWORD)
            check(gdi.SetStretchBltMode(dc, 4), "SetStretchBltMode")
            applied = gdi.SetColorAdjustment(dc, ctypes.byref(ColorAdjustment(24, **values)))
            gdi.StretchDIBits(dc, 0, 0, SIZE, SIZE, 0, 0, SOURCE, SOURCE, pixels, ctypes.byref(header), 0, 0x00CC0020)
            data = ctypes.string_at(bits, SIZE * SIZE * 4)

        def pixel(x, y, data=data):
            return data[(y * SIZE + x) * 4 : (y * SIZE + x) * 4 + 3]

        centres, mixed = [], 0
        for index in range(SOURCE * SOURCE):
            left, top = (index % SOURCE) * SCALE, (index // SOURCE) * SCALE
            block = {pixel(left + i, top + j) for i in range(SCALE) for j in range(SCALE)}
            mixed += len(block) > 1
            b, g, r = pixel(left + SCALE // 2, top + SCALE // 2)
            centres.append(f"{r:02x}{g:02x}{b:02x}")
        print(f"case {name} applied={applied} mixed={mixed} {values}")
        print("  " + " ".join(centres))


if __name__ == "__main__":
    main()
