"""Print native HALFTONE colours under colourfulness, tint and illuminant adjustments.

The ``colours`` source is 32x32 and holds 1024 colours: the 256 greys, the
216-colour 6x6x6 cube, red, green and blue ramps of 128 levels each, and
168 pseudo-random colours. The ``greys`` source is 64x64; pixel (x, y) is
the grey x // 4 + 16 * (y // 4), so each grey appears at all sixteen
positions of a 4x4 cell. Each ``grey-octets`` source is 64x64; pixel (x, y) is the grey
base + x // 8 + 8 * (y // 8), at every position of an 8x8 cell. Each
``grey-sixteens`` source is 128x128; pixel (x, y) is the grey
base + x // 16 + 8 * (y // 16), at every position of a 16x16 cell. Each
``grey-tiles`` source is 512x512 with 16 greys, base + x // 128 +
4 * (y // 128), few enough to be replicated; only their red channel is
printed. The ``grey-cells`` source is 256x256; pixel
(x, y) is the grey x // 16 + 16 * (y // 16), at every position of a 16x16
cell. Each case selects a COLORADJUSTMENT, stretches its
source four times (or the factor after ``-x`` in the case name) with StretchDIBits in HALFTONE mode, and prints the
colour at each block's centre, in source order, as RRGGBB hex, and the
number of blocks whose 16 pixels are not all equal. No reference images
are written.

    case name applied=... mixed=... {values}
      RRGGBB ...
"""

import ctypes
import platform
from ctypes import wintypes

from windows_wmf_render import bind, check, module_versions, reference_surface

SCALE = 4


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
    while len(result) < 32 * 32:
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        result.append(((seed >> 16) & 255, (seed >> 8) & 255, seed & 255))
    return result


NEUTRAL = dict(flags=0, illuminant=0, rg=10000, gg=10000, bg=10000, black=0, white=10000)
NEUTRAL |= dict(contrast=0, brightness=0, colorfulness=0, tint=0)


def greys():
    return [(v, v, v) for y in range(64) for x in range(64) for v in [x // 4 + 16 * (y // 4)]]


def grey_cells():
    return [(v, v, v) for y in range(256) for x in range(256) for v in [x // 16 + 16 * (y // 16)]]


def grey_octets(base):
    return lambda: [(v, v, v) for y in range(64) for x in range(64) for v in [base + x // 8 + 8 * (y // 8)]]


def grey_sixteens(base):
    return lambda: [(v, v, v) for y in range(128) for x in range(128) for v in [base + x // 16 + 8 * (y // 16)]]


def grey_tiles(base):
    return lambda: [(v, v, v) for y in range(512) for x in range(512) for v in [base + x // 128 + 4 * (y // 128)]]


SOURCES = {"colours": (32, colours), "greys": (64, greys), "grey-cells": (256, grey_cells)}
SOURCES |= {f"grey-tiles{base}": (512, grey_tiles(base)) for base in range(0, 256, 16)}
SOURCES |= {f"grey-sixteens{base}": (128, grey_sixteens(base)) for base in (0, 64, 128, 192)}
SOURCES |= {f"grey-octets{base}": (64, grey_octets(base)) for base in (0, 64, 128, 192)}


def cases():
    yield from (("colours", name, values) for name, values in colour_cases())
    for name, values in (
        ("colorfulness1", NEUTRAL | dict(colorfulness=1)),
        ("tint1", NEUTRAL | dict(tint=1)),
        ("illuminant1", NEUTRAL | dict(illuminant=1)),
        ("colorfulness-100", NEUTRAL | dict(colorfulness=-100)),
    ):
        yield "greys", f"greys-{name}", values
    yield "grey-cells", "grey-cells-colorfulness1", NEUTRAL | dict(colorfulness=1)
    for base in range(0, 256, 16):
        yield f"grey-tiles{base}", f"grey-tiles{base}-colorfulness1-x2", NEUTRAL | dict(colorfulness=1)
    for base in (0, 64, 128, 192):
        yield f"grey-sixteens{base}", f"grey-sixteens{base}-colorfulness1", NEUTRAL | dict(colorfulness=1)
    for base in (0, 64, 128, 192):
        yield f"grey-octets{base}", f"grey-octets{base}-colorfulness1", NEUTRAL | dict(colorfulness=1)
    # The same sources at other stretch factors: name-xSCALE.
    for source, scale in (("greys", 2), ("greys", 8), ("greys", 16), ("grey-cells", 2), ("colours", 8)):
        yield source, f"{source}-colorfulness1-x{scale}", NEUTRAL | dict(colorfulness=1)


def colour_cases():
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
    for source_name, name, values in cases():
        side, make = SOURCES[source_name]
        scale = int(name.rsplit("-x", 1)[1]) if "-x" in name else SCALE
        size = side * scale
        pixels = b"".join(bytes((b, g, r, 0)) for r, g, b in make())
        header = BitmapInfoHeader(40, side, -side, 1, 32, 0, len(pixels), 0, 0, 0, 0)
        with reference_surface(size, size) as (gdi, dc, bits):
            ptr, integer = ctypes.c_void_p, ctypes.c_int
            bind(gdi, "SetColorAdjustment", wintypes.BOOL, ptr, ctypes.POINTER(ColorAdjustment))
            bind(gdi, "SetStretchBltMode", integer, ptr, integer)
            bind(gdi, "StretchDIBits", integer, ptr, *(integer,) * 8, ptr, ptr, wintypes.UINT, wintypes.DWORD)
            check(gdi.SetStretchBltMode(dc, 4), "SetStretchBltMode")
            applied = gdi.SetColorAdjustment(dc, ctypes.byref(ColorAdjustment(24, **values)))
            gdi.StretchDIBits(dc, 0, 0, size, size, 0, 0, side, side, pixels, ctypes.byref(header), 0, 0x00CC0020)
            data = ctypes.string_at(bits, size * size * 4)

        def pixel(x, y, data=data, size=size):
            return data[(y * size + x) * 4 : (y * size + x) * 4 + 3]

        centres, mixed = [], 0
        for index in range(side * side):
            left, top = (index % side) * scale, (index // side) * scale
            block = {pixel(left + i, top + j) for i in range(scale) for j in range(scale)}
            mixed += len(block) > 1
            b, g, r = pixel(left + scale // 2, top + scale // 2)
            centres.append(f"{r:02x}{g:02x}{b:02x}")
        print(f"case {name} applied={applied} mixed={mixed} {values}")
        if source_name.startswith("grey-tiles"):
            # Greys only: the red channel, two hex digits per pixel.
            print("  red " + "".join(centre[:2] for centre in centres))
            continue
        print("  " + " ".join(centres))
        if mixed:
            # 64x64 destination pixels from the middle, row by row.
            middle = size // 2
            for y in range(middle, min(middle + 64, size)):
                row = (pixel(x, y) for x in range(middle, min(middle + 64, size)))
                print("  row " + " ".join(f"{r:02x}{g:02x}{b:02x}" for b, g, r in row))


if __name__ == "__main__":
    main()
