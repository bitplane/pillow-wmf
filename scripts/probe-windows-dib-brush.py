"""Inspect the native realization of the two DIB pattern-brush styles."""

import ctypes
from ctypes import wintypes

from windows_wmf_render import bind, check, reference_surface

from pillow_wmf import Recorder
from pillow_wmf.bitmap import RGBBitmap, encode_dib24


class LogBrush(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("color", wintypes.DWORD), ("hatch", ctypes.c_size_t)]


class Bitmap(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.LONG),
        ("width", wintypes.LONG),
        ("height", wintypes.LONG),
        ("stride", wintypes.LONG),
        ("planes", wintypes.WORD),
        ("depth", wintypes.WORD),
        ("bits", ctypes.c_void_p),
    ]


def inspect():
    for style in (3, 5):
        for color in ((0, 0, 0), (255, 255, 255), (128, 128, 128), (255, 0, 0)):
            for top_down in (False, True):
                r = Recorder()
                r.select_object(
                    r.create_dib_pattern_brush(
                        style, 0, encode_dib24(RGBBitmap(3, 2, bytes(color) * 6), top_down=top_down)
                    )
                )
                r.pat_blt(0, 0, 16, 16, 0xF00021)
                with reference_surface(16, 16) as (gdi, dc, bits):
                    ptr = ctypes.c_void_p
                    set_bits = bind(gdi, "SetMetaFileBitsEx", ptr, wintypes.UINT, ptr)
                    delete = bind(gdi, "DeleteMetaFile", wintypes.BOOL, ptr)
                    play = bind(gdi, "PlayMetaFile", wintypes.BOOL, ptr, ptr)
                    current = bind(gdi, "GetCurrentObject", ptr, ptr, wintypes.UINT)
                    get_object = bind(gdi, "GetObjectW", ctypes.c_int, ptr, ctypes.c_int, ptr)
                    flush = bind(gdi, "GdiFlush", wintypes.BOOL)
                    source = r.to_bytes()
                    meta = check(set_bits(len(source), ctypes.create_string_buffer(source)), "SetMetaFileBitsEx")
                    try:
                        check(play(dc, meta), "PlayMetaFile")
                        check(flush(), "GdiFlush")
                        brush = LogBrush()
                        got_brush = get_object(current(dc, 2), ctypes.sizeof(brush), ctypes.byref(brush))
                        bitmap = Bitmap()
                        got_bitmap = get_object(brush.hatch, ctypes.sizeof(bitmap), ctypes.byref(bitmap))
                        pixels = ctypes.string_at(bits, 16 * 16 * 4)
                        colors = sorted({tuple(pixels[i : i + 3]) for i in range(0, len(pixels), 4)})
                        print(
                            style,
                            color,
                            top_down,
                            "brush",
                            got_brush,
                            brush.style,
                            brush.color,
                            "bitmap",
                            got_bitmap,
                            bitmap.width,
                            bitmap.height,
                            bitmap.stride,
                            bitmap.planes,
                            bitmap.depth,
                            "BGR colors",
                            colors,
                            flush=True,
                        )
                    finally:
                        delete(meta)


if __name__ == "__main__":
    inspect()
