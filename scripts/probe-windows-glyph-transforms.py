"""Native glyph realization and placement of the controlled layout font under world transforms.

For each case the DC is put in GM_ADVANCED with a world transform and the
controlled font selected, unantialiased. The probe prints, per character,
GetGlyphOutlineW's metrics and monochrome bitmap, then the pixels ExtTextOutW
paints for that character alone and for the run "AB A", at a fixed origin
with baseline alignment:

    case NAME height=H transform=(m11, m12, m21, m22) escapement=E
    glyph CH box=W,H origin=X,Y cell=CX,CY
    bits ROW MASK              (# marks a set bit)
    text LABEL [align=A]       (baseline alignment unless given)
    row Y X0 MASK              (one per changed row)
"""

import ctypes
import platform
import struct
from ctypes import wintypes

from test_font import FAMILY, FONT_PATH
from windows_wmf_render import bind, check, module_versions, private_fonts, reference_surface

SIZE = 96
ORIGIN = (40, 48)
TRANSFORMS = {
    "identity": (1.0, 0.0, 0.0, 1.0),
    "mirror-x": (-1.0, 0.0, 0.0, 1.0),
    "mirror-y": (1.0, 0.0, 0.0, -1.0),
    "scale": (1.5, 0.0, 0.0, 0.75),
    "rotate": (0.9, 0.4, -0.4, 0.9),
    "shear": (1.0, 0.0, 0.45, 1.0),
}


class XForm(ctypes.Structure):
    _fields_ = [(name, ctypes.c_float) for name in ("m11", "m12", "m21", "m22", "dx", "dy")]


class GlyphMetrics(ctypes.Structure):
    _fields_ = [
        ("width", wintypes.UINT),
        ("height", wintypes.UINT),
        ("origin", wintypes.POINT),
        ("cell_x", ctypes.c_short),
        ("cell_y", ctypes.c_short),
    ]


class Fixed(ctypes.Structure):
    _fields_ = [("fract", wintypes.WORD), ("value", ctypes.c_short)]


class Mat2(ctypes.Structure):
    _fields_ = [("m11", Fixed), ("m12", Fixed), ("m21", Fixed), ("m22", Fixed)]


class LogFont(ctypes.Structure):
    _fields_ = [
        ("height", wintypes.LONG),
        ("width", wintypes.LONG),
        ("escapement", wintypes.LONG),
        ("orientation", wintypes.LONG),
        ("weight", wintypes.LONG),
        ("italic", wintypes.BYTE),
        ("underline", wintypes.BYTE),
        ("strikeout", wintypes.BYTE),
        ("charset", wintypes.BYTE),
        ("out_precision", wintypes.BYTE),
        ("clip_precision", wintypes.BYTE),
        ("quality", wintypes.BYTE),
        ("pitch_family", wintypes.BYTE),
        ("face", ctypes.c_wchar * 32),
    ]


def print_native(data):
    """TTPOLYGONHEADER contours of 16.16 device points (y up), one line each."""
    position = 0
    while position < len(data):
        size, _kind = struct.unpack_from("<II", data, position)
        points = [struct.unpack_from("<ii", data, position + 8)]
        cursor = position + 16
        while cursor < position + size:
            kind, count = struct.unpack_from("<HH", data, cursor)
            points += [struct.unpack_from("<ii", data, cursor + 4 + 8 * i) for i in range(count)]
            cursor += 4 + 8 * count
        print("native " + " ".join(f"{x},{y}" for x, y in points))
        position += size


def cases():
    for height in (-10, -25):
        for name, matrix in TRANSFORMS.items():
            yield name, height, matrix, 0
    yield "escapement", -10, TRANSFORMS["identity"], 300
    yield "escapement-scale", -10, TRANSFORMS["scale"], 300


def main():
    print(f"Windows glyph transform probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    with private_fonts([FONT_PATH]), reference_surface(SIZE, SIZE) as (gdi, dc, bits):
        ptr = ctypes.c_void_p
        set_mode = bind(gdi, "SetGraphicsMode", ctypes.c_int, ptr, ctypes.c_int)
        set_world = bind(gdi, "SetWorldTransform", wintypes.BOOL, ptr, ctypes.POINTER(XForm))
        create_font = bind(gdi, "CreateFontIndirectW", ptr, ctypes.POINTER(LogFont))
        select = bind(gdi, "SelectObject", ptr, ptr, ptr)
        delete = bind(gdi, "DeleteObject", wintypes.BOOL, ptr)
        outline = bind(
            gdi, "GetGlyphOutlineW", wintypes.DWORD, ptr, wintypes.UINT, wintypes.UINT, ptr, wintypes.DWORD, ptr, ptr
        )
        text_out = bind(
            gdi,
            "ExtTextOutW",
            wintypes.BOOL,
            ptr,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
            ptr,
            ctypes.c_wchar_p,
            wintypes.UINT,
            ptr,
        )
        set_align = bind(gdi, "SetTextAlign", wintypes.UINT, ptr, wintypes.UINT)
        set_bk = bind(gdi, "SetBkMode", ctypes.c_int, ptr, ctypes.c_int)
        pixels = ctypes.cast(bits, ctypes.POINTER(ctypes.c_uint32))
        identity = Mat2(Fixed(0, 1), Fixed(0, 0), Fixed(0, 0), Fixed(0, 1))
        check(set_mode(dc, 2), "SetGraphicsMode")
        set_bk(dc, 1)
        set_align(dc, 24)  # TA_BASELINE
        for name, height, matrix, escapement in cases():
            print(f"case {name} height={height} transform={matrix} escapement={escapement}")
            check(set_world(dc, ctypes.byref(XForm(*matrix, 0.0, 0.0))), "SetWorldTransform")
            logfont = LogFont(height, 0, escapement, escapement, 400, 0, 0, 0, 0, 0, 0, 3, 0, FAMILY)
            font = check(create_font(ctypes.byref(logfont)), "CreateFontIndirectW")
            previous = select(dc, font)
            for character in "AB ":
                metrics = GlyphMetrics()
                size = outline(dc, ord(character), 1, ctypes.byref(metrics), 0, None, ctypes.byref(identity))
                buffer = ctypes.create_string_buffer(max(1, size))
                if size not in (0, 0xFFFFFFFF):
                    outline(dc, ord(character), 1, ctypes.byref(metrics), size, buffer, ctypes.byref(identity))
                print(
                    f"glyph {character!r} box={metrics.width},{metrics.height} "
                    f"origin={metrics.origin.x},{metrics.origin.y} cell={metrics.cell_x},{metrics.cell_y}"
                )
                native = outline(dc, ord(character), 2, ctypes.byref(metrics), 0, None, ctypes.byref(identity))
                if native not in (0, 0xFFFFFFFF):
                    data = ctypes.create_string_buffer(native)
                    outline(dc, ord(character), 2, ctypes.byref(metrics), native, data, ctypes.byref(identity))
                    print_native(data.raw)
                if size not in (0, 0xFFFFFFFF) and metrics.width:
                    stride = (metrics.width + 31) // 32 * 4
                    for row in range(metrics.height):
                        line = buffer.raw[row * stride : row * stride + stride]
                        mask = "".join(
                            "#" if line[column // 8] >> (7 - column % 8) & 1 else "." for column in range(metrics.width)
                        )
                        print(f"bits {row} {mask}")
            # The world origin maps to the device origin; draw at its inverse.
            runs = [("A", 24), ("B", 24), ("AB A", 24), ("AB A", 0), ("AB A", 8), ("AB A", 30), ("AB A", 26)]
            for label, alignment in runs:
                ctypes.memset(bits, 0xFF, SIZE * SIZE * 4)
                set_align(dc, alignment)
                set_world(dc, ctypes.byref(XForm(*matrix, float(ORIGIN[0]), float(ORIGIN[1]))))
                text_out(dc, 0, 0, 0, None, label, len(label), None)
                set_world(dc, ctypes.byref(XForm(*matrix, 0.0, 0.0)))
                print(f"text {label!r}" + (f" align={alignment}" if alignment != 24 else ""))
                for y in range(SIZE):
                    row = [pixels[y * SIZE + x] & 0xFFFFFF != 0xFFFFFF for x in range(SIZE)]
                    if any(row):
                        first = row.index(True)
                        last = SIZE - 1 - row[::-1].index(True)
                        print(f"row {y} {first} " + "".join("#" if value else "." for value in row[first : last + 1]))
            select(dc, previous)
            delete(font)


if __name__ == "__main__":
    main()
