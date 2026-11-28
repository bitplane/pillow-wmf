"""Native playback of EMF boundary cases observed in external corpora.

Each case of ``corpus_emf_cases.py`` is loaded with SetEnhMetaFileBits and
played into a fresh 64x64 reference surface fitted to its frame:

    case NAME loaded=L played=P
    row Y X0 RRGGBB,RRGGBB,...   (pixels from X0 to the last non-white one)

Then the handle ExtCreatePen returns for zero-width geometric pens, and native
EMF recordings, in the format of probe-windows-emf-recording.py, of drawing
with one:

    pen style=S width=W handle=H
    [NAME] frame=None result=R
      type=T size=S payload=HEX
"""

import ctypes
import platform
import struct
from ctypes import wintypes

from corpus_emf_cases import CASES, SIZE
from windows_wmf_render import bind, module_versions, reference_surface

PS_GEOMETRIC, PS_DASH, PS_ENDCAP_FLAT, PS_JOIN_MITER = 0x00010000, 1, 0x0200, 0x2000


class LogBrush(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("color", wintypes.DWORD), ("hatch", ctypes.c_size_t)]


def main():
    print(f"Windows corpus boundary probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    ptr = ctypes.c_void_p
    set_bits = bind(gdi, "SetEnhMetaFileBits", ptr, wintypes.UINT, ptr)
    delete_meta = bind(gdi, "DeleteEnhMetaFile", wintypes.BOOL, ptr)
    play = bind(gdi, "PlayEnhMetaFile", wintypes.BOOL, ptr, ptr, ctypes.POINTER(wintypes.RECT))
    for name, build in CASES.items():
        source = build()
        with reference_surface(SIZE, SIZE) as (gdi, dc, bits):
            buffer = ctypes.create_string_buffer(source)
            metafile = set_bits(len(source), buffer)
            played = None
            if metafile:
                played = bool(play(dc, metafile, ctypes.byref(wintypes.RECT(0, 0, SIZE, SIZE))))
                delete_meta(metafile)
            gdi.GdiFlush()
            pixels = ctypes.cast(bits, ctypes.POINTER(ctypes.c_uint32))
            print(f"case {name} loaded={bool(metafile)} played={played}")
            for y in range(SIZE):
                row = [pixels[y * SIZE + x] & 0xFFFFFF for x in range(SIZE)]
                inked = [x for x, value in enumerate(row) if value != 0xFFFFFF]
                if inked:
                    first, last = inked[0], inked[-1]
                    print(f"row {y} {first} " + ",".join(f"{value:06x}" for value in row[first : last + 1]))

    ext_create_pen = bind(gdi, "ExtCreatePen", ptr, wintypes.DWORD, wintypes.DWORD, ptr, wintypes.DWORD, ptr)
    delete_object = bind(gdi, "DeleteObject", wintypes.BOOL, ptr)
    select = bind(gdi, "SelectObject", ptr, ptr, ptr)
    move = bind(gdi, "MoveToEx", wintypes.BOOL, ptr, ctypes.c_int, ctypes.c_int, ptr)
    line = bind(gdi, "LineTo", wintypes.BOOL, ptr, ctypes.c_int, ctypes.c_int)
    brush = LogBrush(0, 0x000080, 0)
    styles = (PS_GEOMETRIC, PS_GEOMETRIC | PS_DASH, PS_GEOMETRIC | PS_ENDCAP_FLAT | PS_JOIN_MITER)
    for style in styles:
        for width in (0, 1):
            pen = ext_create_pen(style, width, ctypes.byref(brush), 0, None)
            print(f"pen style={style:#x} width={width} handle={bool(pen)}")
            if pen:
                delete_object(pen)

    create_emf = bind(gdi, "CreateEnhMetaFileW", ptr, ptr, ctypes.c_wchar_p, ptr, ctypes.c_wchar_p)
    close_emf = bind(gdi, "CloseEnhMetaFile", ptr, ptr)
    get_bits = bind(gdi, "GetEnhMetaFileBits", wintypes.UINT, ptr, wintypes.UINT, ptr)
    for style in styles:
        with reference_surface(128, 128) as (_, reference, _bits):
            dc = create_emf(reference, None, None, None)
            pen = ext_create_pen(style, 0, ctypes.byref(brush), 0, None)
            result = [bool(pen), bool(select(dc, pen)) if pen else None, move(dc, 4, 4, None), line(dc, 59, 20)]
            metafile = close_emf(dc)
            if pen:
                delete_object(pen)
        size = get_bits(metafile, 0, None)
        buffer = ctypes.create_string_buffer(size)
        get_bits(metafile, size, buffer)
        delete_meta(metafile)
        print(f"\n[zero-width-pen-{style:#x}] frame=None result={result!r}")
        position, data = 0, buffer.raw
        while position < len(data):
            kind, length = struct.unpack_from("<II", data, position)
            print(f"  type={kind} size={length} payload={data[position + 8 : position + length].hex()}")
            position += length


if __name__ == "__main__":
    main()
