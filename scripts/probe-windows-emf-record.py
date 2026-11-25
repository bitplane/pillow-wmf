"""Record GDI calls into enhanced metafiles natively and print their records.

Native recording is the reference for record layouts that the specification
leaves ambiguous. Each case records into a fresh metafile; its records are
printed as type, size and payload hex. No reference images are written.
"""

import ctypes
import platform
import struct
from ctypes import wintypes

from windows_wmf_render import bind, module_versions

gdi = ctypes.WinDLL("gdi32", use_last_error=True)
msimg = ctypes.WinDLL("msimg32", use_last_error=True)
ptr, integer, boolean, dword = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL, wintypes.DWORD


class TriVertex(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)] + [(c, ctypes.c_ushort) for c in ("r", "g", "b", "a")]


class ColorAdjustment(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ushort) for name in ("size", "flags", "illuminant", "rg", "gg", "bg", "black", "white")]
    _fields_ += [(name, ctypes.c_short) for name in ("contrast", "brightness", "colorfulness", "tint")]


class BitmapInfo(ctypes.Structure):
    _fields_ = [
        ("size", dword),
        ("width", wintypes.LONG),
        ("height", wintypes.LONG),
        ("planes", wintypes.WORD),
        ("bit_count", wintypes.WORD),
        ("compression", dword),
        ("size_image", dword),
        ("xppm", wintypes.LONG),
        ("yppm", wintypes.LONG),
        ("used", dword),
        ("important", dword),
        ("colors", dword * 2),
    ]


def api(module, name, result, *args):
    return bind(module, name, result, *args)


create_emf = api(gdi, "CreateEnhMetaFileW", ptr, ptr, ctypes.c_wchar_p, ptr, ctypes.c_wchar_p)
close_emf = api(gdi, "CloseEnhMetaFile", ptr, ptr)
get_bits = api(gdi, "GetEnhMetaFileBits", wintypes.UINT, ptr, wintypes.UINT, ptr)
delete_emf = api(gdi, "DeleteEnhMetaFile", boolean, ptr)
create_dc = api(gdi, "CreateCompatibleDC", ptr, ptr)
delete_dc = api(gdi, "DeleteDC", boolean, ptr)
create_dib = api(gdi, "CreateDIBSection", ptr, ptr, ptr, wintypes.UINT, ctypes.POINTER(ptr), ptr, dword)
select = api(gdi, "SelectObject", ptr, ptr, ptr)
delete_object = api(gdi, "DeleteObject", boolean, ptr)
create_rect_rgn = api(gdi, "CreateRectRgn", ptr, integer, integer, integer, integer)
create_brush = api(gdi, "CreateSolidBrush", ptr, dword)


def source_dc():
    """A memory DC holding a 4x3 32-bit DIB section, for transfers."""
    dc = create_dc(None)
    info = BitmapInfo(40, 4, -3, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ptr()
    bitmap = create_dib(dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
    ctypes.memmove(bits, bytes(range(48)), 48)
    select(dc, bitmap)
    return dc


def mono_bitmap():
    info = BitmapInfo(40, 4, 3, 1, 1, 0, 0, 0, 0, 2, 0)
    info.colors[1] = 0xFFFFFF
    bits = ptr()
    bitmap = create_dib(None, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
    ctypes.memmove(bits, bytes((0xA0, 0, 0, 0, 0x50, 0, 0, 0, 0xA0, 0, 0, 0)), 12)
    return bitmap


def cases():
    gradient = api(msimg, "GradientFill", boolean, ptr, ctypes.POINTER(TriVertex), dword, ptr, dword, dword)

    def gradient_fill(dc, mode):
        vertices = (TriVertex * 3)(
            TriVertex(1, 2, 0xFF00, 0, 0, 0), TriVertex(30, 20, 0, 0xFF00, 0, 0), TriVertex(5, 25, 0, 0, 0xFF00, 0)
        )
        if mode == 2:
            indexes = (dword * 3)(0, 1, 2)
            return gradient(dc, vertices, 3, indexes, 1, mode)
        indexes = (dword * 2)(0, 1)
        return gradient(dc, vertices, 2, indexes, 1, mode)

    yield "gradient-rect-h", lambda dc: gradient_fill(dc, 0)
    yield "gradient-rect-v", lambda dc: gradient_fill(dc, 1)
    yield "gradient-triangle", lambda dc: gradient_fill(dc, 2)
    miter = api(gdi, "SetMiterLimit", boolean, ptr, ctypes.c_float, ptr)
    yield "miter-limit-4", lambda dc: miter(dc, 4.0, None)
    yield "miter-limit-2-5", lambda dc: miter(dc, 2.5, None)
    adjust = api(gdi, "SetColorAdjustment", boolean, ptr, ctypes.POINTER(ColorAdjustment))
    yield (
        "color-adjustment",
        lambda dc: adjust(dc, ctypes.byref(ColorAdjustment(24, 0, 0, 10000, 10000, 10000, 0, 10000, 50, -50, 0, 0))),
    )
    icm = api(gdi, "SetICMMode", integer, ptr, integer)
    yield "icm-mode", lambda dc: icm(dc, 2)
    match = api(gdi, "ColorMatchToTarget", boolean, ptr, ptr, dword)

    def color_match(dc):
        target = create_dc(None)
        try:
            return (match(dc, target, 1), match(dc, target, 2), match(dc, target, 3))
        finally:
            delete_dc(target)

    yield "color-match", color_match
    text_out = api(
        gdi, "ExtTextOutW", boolean, ptr, integer, integer, wintypes.UINT, ptr, ctypes.c_wchar_p, wintypes.UINT, ptr
    )
    yield "ext-text-out-short", lambda dc: text_out(dc, 3, 4, 0, None, "Ab", 2, None)
    rect = wintypes.RECT(1, 2, 30, 20)
    yield "ext-text-out-opaque", lambda dc: text_out(dc, 3, 4, 2, ctypes.byref(rect), "Ab", 2, None)
    text_a = api(
        gdi, "ExtTextOutA", boolean, ptr, integer, integer, wintypes.UINT, ptr, ctypes.c_char_p, wintypes.UINT, ptr
    )
    yield "ext-text-out-a", lambda dc: text_a(dc, 3, 4, 0, None, b"Ab", 2, None)

    class PolyText(ctypes.Structure):
        _fields_ = [
            ("x", integer),
            ("y", integer),
            ("n", wintypes.UINT),
            ("text", ctypes.c_wchar_p),
            ("options", wintypes.UINT),
            ("rect", wintypes.RECT),
            ("dx", ptr),
        ]

    poly_text = api(gdi, "PolyTextOutW", boolean, ptr, ctypes.POINTER(PolyText), integer)
    texts = (PolyText * 2)(
        PolyText(1, 2, 2, "ab", 0, wintypes.RECT(), None), PolyText(5, 9, 1, "c", 2, wintypes.RECT(0, 0, 9, 9), None)
    )
    yield "poly-text-out", lambda dc: poly_text(dc, texts, 2)
    bit_blt_names = {
        "mask-blt": lambda dc, source: api(
            gdi, "MaskBlt", boolean, ptr, *(integer,) * 4, ptr, integer, integer, ptr, integer, integer, dword
        )(dc, 1, 2, 4, 3, source, 0, 0, mono_bitmap(), 0, 0, 0xAACC0020),
        "plg-blt": lambda dc, source: api(
            gdi, "PlgBlt", boolean, ptr, ptr, ptr, *(integer,) * 4, ptr, integer, integer
        )(
            dc,
            (wintypes.POINT * 3)(wintypes.POINT(5, 1), wintypes.POINT(20, 6), wintypes.POINT(2, 12)),
            source,
            0,
            0,
            4,
            3,
            None,
            0,
            0,
        ),
        "alpha-blend": lambda dc, source: api(
            msimg, "AlphaBlend", boolean, ptr, *(integer,) * 4, ptr, *(integer,) * 4, dword
        )(dc, 1, 2, 8, 6, source, 0, 0, 4, 3, 0x01FF0000),
        "transparent-blt": lambda dc, source: api(
            msimg, "TransparentBlt", boolean, ptr, *(integer,) * 4, ptr, *(integer,) * 4, wintypes.UINT
        )(dc, 1, 2, 8, 6, source, 0, 0, 4, 3, 0x00030201),
    }
    for name, call in bit_blt_names.items():

        def transfer(dc, call=call):
            source = source_dc()
            try:
                return call(dc, source)
            finally:
                delete_dc(source)

        yield name, transfer
    fill = api(gdi, "FillRgn", boolean, ptr, ptr, ptr)
    frame = api(gdi, "FrameRgn", boolean, ptr, ptr, ptr, integer, integer)
    invert = api(gdi, "InvertRgn", boolean, ptr, ptr)
    paint = api(gdi, "PaintRgn", boolean, ptr, ptr)
    yield "fill-rgn", lambda dc: fill(dc, create_rect_rgn(1, 2, 10, 8), create_brush(0xFF))
    yield "frame-rgn", lambda dc: frame(dc, create_rect_rgn(1, 2, 10, 8), create_brush(0xFF), 2, 3)
    yield "invert-rgn", lambda dc: invert(dc, create_rect_rgn(1, 2, 10, 8))
    yield "paint-rgn", lambda dc: paint(dc, create_rect_rgn(1, 2, 10, 8))
    escape = api(gdi, "Escape", integer, ptr, integer, integer, ctypes.c_char_p, ptr)
    ext_escape = api(gdi, "ExtEscape", integer, ptr, integer, integer, ctypes.c_char_p, integer, ptr)
    yield "escape", lambda dc: escape(dc, 0x1000, 4, b"abcd", None)
    yield "ext-escape", lambda dc: ext_escape(dc, 0x1000, 4, b"abcd", 0, None)
    angle = api(gdi, "AngleArc", boolean, ptr, integer, integer, dword, ctypes.c_float, ctypes.c_float)
    yield "angle-arc", lambda dc: angle(dc, 10, 12, 5, 30.0, 120.0)
    arc_direction = api(gdi, "SetArcDirection", integer, ptr, integer)
    yield "arc-direction", lambda dc: arc_direction(dc, 2)
    layout = api(gdi, "SetLayout", dword, ptr, dword)
    yield "layout", lambda dc: layout(dc, 1)


def records(data):
    position = 0
    while position < len(data):
        kind, size = struct.unpack_from("<II", data, position)
        yield kind, size, data[position + 8 : position + size]
        position += size


def main():
    print(f"Windows EMF recording probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    for name, record in cases():
        dc = create_emf(None, None, None, None)
        result = record(dc)
        metafile = close_emf(dc)
        size = get_bits(metafile, 0, None)
        buffer = ctypes.create_string_buffer(size)
        get_bits(metafile, size, buffer)
        delete_emf(metafile)
        print(f"\n[{name}] result={result!r}")
        for kind, length, payload in records(buffer.raw):
            if kind in (1, 14):
                continue  # Header and EOF.
            print(f"  type={kind} size={length} payload={payload.hex()}")


if __name__ == "__main__":
    main()
