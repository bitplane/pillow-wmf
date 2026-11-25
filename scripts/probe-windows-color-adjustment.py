"""Print the colours native HALFTONE stretching produces under colour adjustments.

A 16x16 32-bit source holds 256 distinct colours: pixel i is
(i, 255 - i, i * 7 mod 256) in red, green and blue. Each case selects a
COLORADJUSTMENT, stretches the source four times with StretchDIBits in
HALFTONE mode onto the 64x64 reference DIB, and prints the colour at the
centre of each source pixel's block, in source order, as RRGGBB hex. No
reference images are written.

    case name flags illuminant gamma(r,g,b) black white contrast brightness colorfulness tint
"""

import ctypes
import platform
from ctypes import wintypes

from windows_wmf_render import bind, check, module_versions, reference_surface

SIZE, SOURCE, SCALE = 64, 16, 4


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


NEUTRAL = dict(flags=0, illuminant=0, rg=10000, gg=10000, bg=10000, black=0, white=10000)
NEUTRAL |= dict(contrast=0, brightness=0, colorfulness=0, tint=0)


def cases():
    yield "neutral", NEUTRAL
    yield "fixture", NEUTRAL | dict(contrast=50, brightness=-50)
    for value in (-100, -50, -20, 20, 50, 100):
        yield f"contrast{value}", NEUTRAL | dict(contrast=value)
    for value in (-100, -50, -20, 20, 50, 100):
        yield f"brightness{value}", NEUTRAL | dict(brightness=value)
    for contrast, brightness in ((50, 50), (-50, -50), (-50, 50), (100, -100), (20, -80)):
        yield f"contrast{contrast}-brightness{brightness}", NEUTRAL | dict(contrast=contrast, brightness=brightness)
    for value in (-100, -50, 50, 100):
        yield f"colorfulness{value}", NEUTRAL | dict(colorfulness=value)
    for value in (-100, -30, 30, 100):
        yield f"tint{value}", NEUTRAL | dict(tint=value)
    for value in (2500, 5000, 20000, 65000):
        yield f"gamma{value}", NEUTRAL | dict(rg=value, gg=value, bg=value)
    yield "gamma-red", NEUTRAL | dict(rg=20000)
    for black, white in ((1000, 10000), (0, 9000), (2000, 8000), (4000, 6000)):
        yield f"reference{black}-{white}", NEUTRAL | dict(black=black, white=white)
    for value in range(1, 9):
        yield f"illuminant{value}", NEUTRAL | dict(illuminant=value)
    for flags in (1, 2, 3):
        yield f"flags{flags}", NEUTRAL | dict(flags=flags)
    yield "flags1-contrast50", NEUTRAL | dict(flags=1, contrast=50)


def main():
    print(f"Windows colour adjustment probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    pixels = b"".join(bytes(((i * 7) % 256, 255 - i, i, 0)) for i in range(SOURCE * SOURCE))
    header = BitmapInfoHeader(40, SOURCE, -SOURCE, 1, 32, 0, len(pixels), 0, 0, 0, 0)
    for name, values in cases():
        with reference_surface(SIZE, SIZE) as (gdi, dc, bits):
            ptr, integer = ctypes.c_void_p, ctypes.c_int
            bind(gdi, "SetColorAdjustment", wintypes.BOOL, ptr, ctypes.POINTER(ColorAdjustment))
            bind(gdi, "SetStretchBltMode", integer, ptr, integer)
            bind(gdi, "StretchDIBits", integer, ptr, *(integer,) * 8, ptr, ptr, wintypes.UINT, wintypes.DWORD)
            check(gdi.SetStretchBltMode(dc, 4), "SetStretchBltMode")
            adjustment = ColorAdjustment(24, **values)
            applied = gdi.SetColorAdjustment(dc, ctypes.byref(adjustment))
            gdi.StretchDIBits(dc, 0, 0, SIZE, SIZE, 0, 0, SOURCE, SOURCE, pixels, ctypes.byref(header), 0, 0x00CC0020)
            data = ctypes.string_at(bits, SIZE * SIZE * 4)
        centres = []
        for index in range(SOURCE * SOURCE):
            x, y = (index % SOURCE) * SCALE + SCALE // 2, (index // SOURCE) * SCALE + SCALE // 2
            b, g, r = data[(y * SIZE + x) * 4 : (y * SIZE + x) * 4 + 3]
            centres.append(f"{r:02x}{g:02x}{b:02x}")
        print(f"case {name} applied={applied} {values}")
        print("  " + " ".join(centres))


if __name__ == "__main__":
    main()
