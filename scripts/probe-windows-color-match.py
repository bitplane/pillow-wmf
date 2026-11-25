"""Print how native EMF playback treats ColorMatchToTargetW records.

Each case is a metafile with a rectangle before and after one
EMR_COLORMATCHTOTARGETW variant. It is played twice onto the 64x64
reference DIB: with PlayEnhMetaFile, printing its result and which
rectangles were drawn, and with EnumEnhMetaFile, printing each record's
PlayEnhMetaFileRecord result. No reference images are written.

    case name play=... first=... second=... records=[(type, result), ...]
"""

import ctypes
import platform
from ctypes import wintypes

from windows_wmf_render import bind, check, module_versions, reference_surface

from pillow_wmf.emf import Metafile, fixed, system

SIZE = 64
FRAME = (0, 0, 1694, 1692)


def cases():
    profile = "sRGB Color Space Profile.icm\0".encode("utf-16-le")
    for action in (0, 1, 2, 3, 4):
        yield f"action{action}", system.ColorMatchToTargetW(action, 0, b"", b"")
    for flags in (1, 2, 3):
        yield f"flags{flags}", system.ColorMatchToTargetW(1, flags, b"", b"")
    yield "name", system.ColorMatchToTargetW(1, 0, profile, b"")
    yield "name-action2", system.ColorMatchToTargetW(2, 0, profile, b"")
    yield "name-action3", system.ColorMatchToTargetW(3, 0, profile, b"")
    yield "data", system.ColorMatchToTargetW(1, 1, b"", bytes(128))
    yield "name-data", system.ColorMatchToTargetW(1, 1, profile, bytes(128))
    yield "odd-name", system.ColorMatchToTargetW(1, 0, b"x", b"")


def bind_probe(gdi):
    ptr = ctypes.c_void_p
    bind(gdi, "SetEnhMetaFileBits", ptr, wintypes.UINT, ptr)
    bind(gdi, "DeleteEnhMetaFile", wintypes.BOOL, ptr)
    bind(gdi, "PlayEnhMetaFile", wintypes.BOOL, ptr, ptr, ctypes.POINTER(wintypes.RECT))
    bind(gdi, "PlayEnhMetaFileRecord", wintypes.BOOL, ptr, ptr, ptr, wintypes.UINT)


def drawn(bits):
    data = ctypes.string_at(bits, SIZE * SIZE * 4)

    def at(x, y):
        return data[(y * SIZE + x) * 4 : (y * SIZE + x) * 4 + 4] != b"\xff\xff\xff\xff"

    return at(10, 10), at(40, 40)


def main():
    print(f"Windows ColorMatchToTargetW probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    bind_probe(gdi)
    callback_type = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, wintypes.LPARAM
    )
    enum = bind(
        gdi,
        "EnumEnhMetaFile",
        wintypes.BOOL,
        ctypes.c_void_p,
        ctypes.c_void_p,
        callback_type,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.RECT),
    )
    for name, record in cases():
        records = [fixed.Rectangle(5, 5, 20, 20), record, fixed.Rectangle(35, 35, 50, 50)]
        data = Metafile.build(records, frame=FRAME).to_bytes()
        buffer = ctypes.create_string_buffer(data)
        metafile = check(gdi.SetEnhMetaFileBits(len(data), buffer), "SetEnhMetaFileBits")
        try:
            rect = wintypes.RECT(0, 0, SIZE, SIZE)
            with reference_surface(SIZE, SIZE) as (_, dc, bits):
                played = gdi.PlayEnhMetaFile(dc, metafile, ctypes.byref(rect))
                first, second = drawn(bits)
            results = []

            def visit(hdc, table, entry, handles, _, results=results):
                kind = ctypes.cast(entry, ctypes.POINTER(wintypes.DWORD))[0]
                results.append((kind, gdi.PlayEnhMetaFileRecord(hdc, table, entry, handles)))
                return 1

            with reference_surface(SIZE, SIZE) as (_, dc, _bits):
                callback = callback_type(visit)
                enumerated = enum(dc, metafile, callback, None, ctypes.byref(rect))
        finally:
            gdi.DeleteEnhMetaFile(metafile)
        print(f"case {name} play={played} first={first} second={second} enum={enumerated} records={results}")


if __name__ == "__main__":
    main()
