"""Native font mapping and byte decoding for charsets a face may not cover.

With every controlled face loaded privately, requests each face by name at
each LOGFONT charset (including values Windows does not define) and prints
what GDI realized and how ANSI text bytes map to that face's glyphs:

    map FACE charset=C selected=NAME realized=R codepage=P glyphs=G,G,...

``realized`` is GetTextCharsetInfo's charset and ``codepage`` the code page
TranslateCharsetInfo gives for it. ``glyphs`` are GetGlyphIndicesA's indices
for the bytes in BYTES (0xffff where the font lacks the character). Then
for a few cases the drawn run of those bytes:

    draw FACE charset=C
    row Y X0 MASK                 (# marks a changed pixel)
"""

import ctypes
import platform
from ctypes import wintypes
from pathlib import Path

from windows_wmf_render import bind, check, module_versions, private_fonts, reference_surface

ROOT = Path(__file__).resolve().parents[1] / "test/fonts"
FACES = {
    "Pillow WMF Test": "layout.ttf",
    "Pillow WMF Encoding": "encoding.ttf",
    "Pillow WMF Symbols": "symbols.ttf",
    "Pillow WMF DBCS": "dbcs.ttf",
    "Pillow WMF UTF8": "utf8.ttf",
}
CHARSETS = (
    0,
    1,
    2,
    3,
    77,
    100,
    128,
    129,
    130,
    134,
    136,
    161,
    162,
    163,
    177,
    178,
    186,
    200,
    204,
    222,
    238,
    253,
    254,
    255,
)
BYTES = bytes((0x20, 0x41, 0x42, 0x80, 0x9F, 0xA4, 0xC0, 0xC1, 0xE9, 0xF0, 0xFF))
DRAWN = (("Pillow WMF Test", 204), ("Pillow WMF Test", 2), ("Pillow WMF Symbols", 0), ("Pillow WMF Encoding", 238))
SIZE = 64


class LogFont(ctypes.Structure):
    _fields_ = [(name, wintypes.LONG) for name in ("height", "width", "escapement", "orientation", "weight")]
    _fields_ += [(name, ctypes.c_ubyte) for name in ("italic", "underline", "strikeout", "charset")]
    _fields_ += [(name, ctypes.c_ubyte) for name in ("out_precision", "clip_precision", "quality", "pitch")]
    _fields_ += [("face", ctypes.c_wchar * 32)]


class CharsetInfo(ctypes.Structure):
    _fields_ = [("charset", wintypes.UINT), ("codepage", wintypes.UINT), ("signature", wintypes.DWORD * 6)]


def main():
    print(f"Windows charset mapping probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    with private_fonts([ROOT / name for name in FACES.values()]), reference_surface(SIZE, SIZE) as (gdi, dc, bits):
        ptr, integer = ctypes.c_void_p, ctypes.c_int
        create_font = bind(gdi, "CreateFontIndirectW", ptr, ctypes.POINTER(LogFont))
        select = bind(gdi, "SelectObject", ptr, ptr, ptr)
        delete = bind(gdi, "DeleteObject", wintypes.BOOL, ptr)
        text_face = bind(gdi, "GetTextFaceW", integer, ptr, integer, ctypes.c_wchar_p)
        charset_info = bind(gdi, "GetTextCharsetInfo", integer, ptr, ptr, wintypes.DWORD)
        indices = bind(
            gdi,
            "GetGlyphIndicesA",
            wintypes.DWORD,
            ptr,
            ctypes.c_char_p,
            integer,
            ctypes.POINTER(wintypes.WORD),
            wintypes.DWORD,
        )
        text_out = bind(gdi, "TextOutA", wintypes.BOOL, ptr, integer, integer, ctypes.c_char_p, integer)
        flush = bind(gdi, "GdiFlush", wintypes.BOOL)
        translate = bind(
            gdi, "TranslateCharsetInfo", wintypes.BOOL, ctypes.c_void_p, ctypes.POINTER(CharsetInfo), wintypes.DWORD
        )
        pixels = ctypes.cast(bits, ctypes.POINTER(ctypes.c_uint32))
        bind(gdi, "SetBkMode", integer, ptr, integer)(dc, 1)
        bind(gdi, "SetTextAlign", wintypes.UINT, ptr, wintypes.UINT)(dc, 24)

        def realize(face, charset):
            font = check(
                create_font(ctypes.byref(LogFont(-20, 0, 0, 0, 400, 0, 0, 0, charset, 0, 0, 3, 0, face))), "font"
            )
            return font, select(dc, font)

        for face in FACES:
            for charset in CHARSETS:
                font, previous = realize(face, charset)
                name = ctypes.create_unicode_buffer(64)
                text_face(dc, 64, name)
                realized = charset_info(dc, None, 0)
                info = CharsetInfo()
                codepage = info.codepage if translate(ctypes.c_void_p(realized), ctypes.byref(info), 1) else -1
                glyphs = (wintypes.WORD * len(BYTES))()
                indices(dc, BYTES, len(BYTES), glyphs, 1)
                print(
                    f"map {face} charset={charset} selected={name.value} realized={realized} codepage={codepage} "
                    f"glyphs={','.join(str(g) for g in glyphs)}"
                )
                select(dc, previous)
                delete(font)
        for face, charset in DRAWN:
            font, previous = realize(face, charset)
            for offset in range(SIZE * SIZE):
                pixels[offset] = 0x00FFFFFF
            text_out(dc, 2, 40, b"AB\xc0\xe9", 4)
            flush()
            print(f"draw {face} charset={charset}")
            for y in range(SIZE):
                row = ["#" if pixels[y * SIZE + x] & 0xFFFFFF != 0xFFFFFF else "." for x in range(SIZE)]
                if "#" in row:
                    first = row.index("#")
                    print(f"row {y} {first} " + "".join(row[first : len(row) - row[::-1].index("#")]))
            select(dc, previous)
            delete(font)


if __name__ == "__main__":
    main()
