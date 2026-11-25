"""Write native HALFTONE stretches through the colour engine at many scales.

Each case stretches a source with StretchDIBits in HALFTONE mode under
colourfulness 40 and tint -30, onto a white top-down 32-bit DIB, and writes
the destination as raw RGB bytes to ``color-engine-phase/NAME.rgb``. Cases
cover filtered and replicated enlargements at integer and fractional
ratios, enlargements beyond five times, reductions, and source rectangles
away from the bitmap origin, so the dither phase of each path can be fitted
offline. Sources: ``hues`` (many colours, filtered) and ``gradient`` (16x12,
replicated). No reference images are written.

    case NAME source=WxH rect=(x,y,w,h) dest=WxH result=...
"""

import ctypes
import platform
from ctypes import wintypes
from pathlib import Path

from windows_wmf_render import bind, module_versions, reference_surface

OUTPUT = Path("color-engine-phase")


class ColorAdjustment(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ushort) for name in ("size", "flags", "illuminant", "rg", "gg", "bg", "black", "white")]
    _fields_ += [(name, ctypes.c_short) for name in ("contrast", "brightness", "colorfulness", "tint")]


def hues(x, y):
    return (x * 37 + y * 11) % 256, (x * 13 + y * 41) % 256, (x * 23 + y * 29 + 90) % 256


def gradient(x, y):
    return (x * 8) % 256, (y * 10) % 256, ((x + y) * 5 + 40) % 256


SOURCES = {
    "hues50": (50, 50, hues),
    "hues60": (60, 60, hues),
    "hues100": (100, 100, hues),
    "gradient": (16, 12, gradient),
}

CASES = [
    # (name, source, (src_x, src_y, src_w, src_h), (dest_w, dest_h))
    *((f"filter-{d}", "hues50", (0, 0, 50, 50), (d, d)) for d in (51, 55, 60, 64, 75, 80, 99, 100, 101, 110, 125)),
    ("filter-120x64", "hues50", (0, 0, 50, 50), (120, 64)),
    ("filter-64x120", "hues50", (0, 0, 50, 50), (64, 120)),
    ("filter-100x51", "hues50", (0, 0, 50, 50), (100, 51)),
    ("general-400", "hues60", (0, 0, 60, 60), (400, 400)),
    ("general-310x200", "hues60", (0, 0, 60, 60), (310, 200)),
    *(
        (f"replicate-{w}x{h}", "gradient", (0, 0, 16, 12), (w, h))
        for w, h in ((64, 48), (120, 108), (40, 30), (33, 25), (100, 100), (17, 13), (48, 60))
    ),
    *((f"reduce-{d}", "hues100", (0, 0, 100, 100), (d, d)) for d in (50, 64, 80, 99)),
    ("reduce-70x40", "hues100", (0, 0, 100, 100), (70, 40)),
    ("offset-filter", "hues60", (5, 4, 40, 40), (100, 100)),
    ("offset-filter-int", "hues60", (5, 4, 40, 40), (80, 80)),
    ("offset-replicate", "gradient", (3, 2, 10, 8), (64, 64)),
    ("offset-replicate-int", "gradient", (3, 2, 10, 8), (40, 32)),
]


def main():
    print(f"Windows colour engine phase probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    OUTPUT.mkdir(exist_ok=True)
    for name, source, (src_x, src_y, src_w, src_h), (width, height) in CASES:
        sw, sh, colour = SOURCES[source]
        pixels = b"".join(bytes((b, g, r, 0)) for y in range(sh) for x in range(sw) for r, g, b in [colour(x, y)])
        header = (wintypes.DWORD * 10)(40, sw, (-sh) & 0xFFFFFFFF, 1 | 32 << 16, 0, len(pixels), 0, 0, 0, 0)
        with reference_surface(width, height) as (gdi, dc, bits):
            ptr, integer = ctypes.c_void_p, ctypes.c_int
            bind(gdi, "SetColorAdjustment", wintypes.BOOL, ptr, ctypes.POINTER(ColorAdjustment))
            bind(gdi, "SetStretchBltMode", integer, ptr, integer)
            bind(gdi, "StretchDIBits", integer, ptr, *(integer,) * 8, ptr, ptr, wintypes.UINT, wintypes.DWORD)
            gdi.SetStretchBltMode(dc, 4)
            values = dict(flags=0, illuminant=0, rg=10000, gg=10000, bg=10000, black=0, white=10000)
            gdi.SetColorAdjustment(dc, ctypes.byref(ColorAdjustment(24, **values, colorfulness=40, tint=-30)))
            result = gdi.StretchDIBits(
                dc, 0, 0, width, height, src_x, src_y, src_w, src_h, pixels, ctypes.byref(header), 0, 0x00CC0020
            )
            data = ctypes.string_at(bits, width * height * 4)
        rgb = bytes(v for i in range(0, len(data), 4) for v in (data[i + 2], data[i + 1], data[i]))
        (OUTPUT / f"{name}.rgb").write_bytes(rgb)
        print(f"case {name} source={sw}x{sh} rect={(src_x, src_y, src_w, src_h)} dest={width}x{height} result={result}")


if __name__ == "__main__":
    main()
