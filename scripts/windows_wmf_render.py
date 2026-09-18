"""Minimal native WMF oracle: PlayMetaFile into a top-down 32-bit DIB."""

from __future__ import annotations

import ctypes
import os
from contextlib import contextmanager
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


def bind(gdi, name, result, *args):
    function = getattr(gdi, name)
    function.restype = result
    function.argtypes = args
    return function


def check(handle, name):
    if not handle:
        raise OSError(ctypes.get_last_error(), f"{name} failed")
    return handle


@contextmanager
def private_fonts(paths):
    """Make supplied oracle fonts available only to this process."""
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    add = bind(gdi, "AddFontResourceExW", ctypes.c_int, ctypes.c_wchar_p, wintypes.DWORD, ctypes.c_void_p)
    remove = bind(gdi, "RemoveFontResourceExW", wintypes.BOOL, ctypes.c_wchar_p, wintypes.DWORD, ctypes.c_void_p)
    loaded = []
    try:
        for path in paths:
            path = str(path.resolve())
            check(add(path, 0x10, None), "AddFontResourceExW")  # FR_PRIVATE
            loaded.append(path)
        yield
    finally:
        for path in reversed(loaded):
            check(remove(path, 0x10, None), "RemoveFontResourceExW")


@contextmanager
def reference_surface(width: int, height: int):
    """The shared native DC/DIB and initial mapping for images and probes."""
    if os.name != "nt":
        raise RuntimeError("Native WMF rendering requires Windows")
    if width < 1 or height < 1:
        raise ValueError("Expected positive dimensions")

    gdi = ctypes.WinDLL("gdi32", use_last_error=True)

    def api(name, result, *args):
        return bind(gdi, name, result, *args)

    ptr = ctypes.c_void_p
    dword = wintypes.DWORD
    integer = ctypes.c_int
    create_dc = api("CreateCompatibleDC", ptr, ptr)
    delete_dc = api("DeleteDC", wintypes.BOOL, ptr)
    create_dib = api("CreateDIBSection", ptr, ptr, ptr, wintypes.UINT, ctypes.POINTER(ptr), ptr, dword)
    select = api("SelectObject", ptr, ptr, ptr)
    delete_object = api("DeleteObject", wintypes.BOOL, ptr)
    set_map_mode = api("SetMapMode", integer, ptr, integer)
    set_window = api("SetWindowExtEx", wintypes.BOOL, ptr, integer, integer, ptr)
    set_viewport = api("SetViewportExtEx", wintypes.BOOL, ptr, integer, integer, ptr)
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
        yield gdi, dc, bits
    finally:
        if previous and dc:
            select(dc, previous)
        if bitmap:
            delete_object(bitmap)
        if dc:
            delete_dc(dc)


def render_wmf(source: bytes, width: int, height: int) -> Image.Image:
    """Render WMF bytes; records may change the initial 1:1 mapping.

    The optional 22-byte placeable wrapper is not passed to SetMetaFileBitsEx.
    As in local playback, its suggested bounds do not override the DC profile.
    """
    if source.startswith(bytes.fromhex("d7cdc69a")):
        if len(source) < 22:
            raise ValueError("Truncated placeable WMF header")
        source = source[22:]
    if not source:
        raise ValueError("Expected nonempty WMF bytes")
    with reference_surface(width, height) as (gdi, dc, bits):
        ptr = ctypes.c_void_p
        set_bits = bind(gdi, "SetMetaFileBitsEx", ptr, wintypes.UINT, ptr)
        delete_meta = bind(gdi, "DeleteMetaFile", wintypes.BOOL, ptr)
        play = bind(gdi, "PlayMetaFile", wintypes.BOOL, ptr, ptr)
        flush = bind(gdi, "GdiFlush", wintypes.BOOL)
        source_buffer = ctypes.create_string_buffer(source)
        metafile = check(set_bits(len(source), source_buffer), "SetMetaFileBitsEx")
        try:
            check(play(dc, metafile), "PlayMetaFile")
            check(flush(), "GdiFlush")
            pixels = ctypes.string_at(bits, width * height * 4)
            return Image.frombytes("RGB", (width, height), pixels, "raw", "BGRX")
        finally:
            delete_meta(metafile)
