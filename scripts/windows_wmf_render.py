"""Minimal native WMF oracle: PlayMetaFile into a top-down 32-bit DIB."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from PIL import Image


class BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("width", wintypes.LONG),
        ("height", wintypes.LONG),
        ("planes", wintypes.WORD),
        ("bit_count", wintypes.WORD),
        ("compression", wintypes.DWORD),
        ("size_image", wintypes.DWORD),
        ("x_pixels_per_meter", wintypes.LONG),
        ("y_pixels_per_meter", wintypes.LONG),
        ("colors_used", wintypes.DWORD),
        ("colors_important", wintypes.DWORD),
    ]


class BitmapInfo(ctypes.Structure):
    _fields_ = [("header", BitmapInfoHeader), ("colors", wintypes.DWORD * 1)]


def render_wmf(source: bytes, width: int, height: int) -> Image.Image:
    """Render a standard (non-placeable) WMF at one logical unit per pixel."""
    if os.name != "nt":
        raise RuntimeError("Native WMF rendering requires Windows")
    if not source or width < 1 or height < 1:
        raise ValueError("Expected nonempty WMF bytes and positive dimensions")

    gdi = ctypes.WinDLL("gdi32", use_last_error=True)

    def api(name, result, *args):
        function = getattr(gdi, name)
        function.restype = result
        function.argtypes = args
        return function

    ptr = ctypes.c_void_p
    dword = wintypes.DWORD
    integer = ctypes.c_int
    set_bits = api("SetMetaFileBitsEx", ptr, dword, ptr)
    delete_meta = api("DeleteMetaFile", wintypes.BOOL, ptr)
    create_dc = api("CreateCompatibleDC", ptr, ptr)
    delete_dc = api("DeleteDC", wintypes.BOOL, ptr)
    create_dib = api("CreateDIBSection", ptr, ptr, wintypes.UINT, ctypes.POINTER(ptr), ptr, dword)
    select = api("SelectObject", ptr, ptr, ptr)
    delete_object = api("DeleteObject", wintypes.BOOL, ptr)
    set_map_mode = api("SetMapMode", integer, ptr, integer)
    set_window = api("SetWindowExtEx", wintypes.BOOL, ptr, integer, integer, ptr)
    set_viewport = api("SetViewportExtEx", wintypes.BOOL, ptr, integer, integer, ptr)
    play = api("PlayMetaFile", wintypes.BOOL, ptr, ptr)
    flush = api("GdiFlush", wintypes.BOOL)

    def check(handle, name):
        if not handle:
            raise OSError(ctypes.get_last_error(), f"{name} failed")
        return handle

    source_buffer = ctypes.create_string_buffer(source)
    metafile = check(set_bits(len(source), source_buffer), "SetMetaFileBitsEx")
    dc = None
    bitmap = None
    previous = None
    try:
        dc = check(create_dc(None), "CreateCompatibleDC")
        info = BitmapInfo()
        info.header = BitmapInfoHeader(40, width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0)
        bits = ptr()
        bitmap = check(create_dib(dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0), "CreateDIBSection")
        previous = check(select(dc, bitmap), "SelectObject")
        ctypes.memset(bits, 255, width * height * 4)
        check(set_map_mode(dc, 8), "SetMapMode")  # MM_ANISOTROPIC
        check(set_window(dc, width, height, None), "SetWindowExtEx")
        check(set_viewport(dc, width, height, None), "SetViewportExtEx")
        check(play(dc, metafile), "PlayMetaFile")
        check(flush(), "GdiFlush")
        pixels = ctypes.string_at(bits, width * height * 4)
        return Image.frombytes("RGB", (width, height), pixels, "raw", "BGRX")
    finally:
        if previous and dc:
            select(dc, previous)
        if bitmap:
            delete_object(bitmap)
        if dc:
            delete_dc(dc)
        delete_meta(metafile)
