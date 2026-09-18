"""Measure controlled-font WMF playback; no tests or reference replacement."""

import argparse
import ctypes
import struct
from ctypes import wintypes
from pathlib import Path

from test_font import FAMILY, FONT_PATH
from text_probe_cases import cases
from windows_wmf_render import bind, check, reference_surface, render_wmf


class TextMetrics(ctypes.Structure):
    _fields_ = (
        [
            (name, wintypes.LONG)
            for name in (
                "height",
                "ascent",
                "descent",
                "internal_leading",
                "external_leading",
                "average_width",
                "maximum_width",
                "weight",
                "overhang",
                "aspect_x",
                "aspect_y",
            )
        ]
        + [(name, ctypes.c_ushort) for name in ("first", "last", "default", "break_char")]
        + [(name, ctypes.c_ubyte) for name in ("italic", "underline", "strikeout", "pitch_family", "charset")]
    )


class GlyphMetrics(ctypes.Structure):
    _fields_ = [
        ("width", wintypes.UINT),
        ("height", wintypes.UINT),
        ("origin", wintypes.POINT),
        ("advance_x", ctypes.c_short),
        ("advance_y", ctypes.c_short),
    ]


def observe(source, *, family=FAMILY, size=(128, 128), sample=b"A B", tables=None):
    with reference_surface(*size) as (gdi, dc, _):
        ptr = ctypes.c_void_p
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ptr, ptr, ptr, ctypes.c_int, ctypes.c_ssize_t)
        enum = bind(gdi, "EnumMetaFile", wintypes.BOOL, ptr, ptr, callback_type, ctypes.c_ssize_t)
        play = bind(gdi, "PlayMetaFileRecord", wintypes.BOOL, ptr, ptr, ptr, ctypes.c_uint)
        set_bits = bind(gdi, "SetMetaFileBitsEx", ptr, wintypes.UINT, ptr)
        delete = bind(gdi, "DeleteMetaFile", wintypes.BOOL, ptr)
        metrics = bind(gdi, "GetTextMetricsW", wintypes.BOOL, ptr, ctypes.POINTER(TextMetrics))
        face = bind(gdi, "GetTextFaceW", ctypes.c_int, ptr, ctypes.c_int, ctypes.c_wchar_p)
        position = bind(gdi, "GetCurrentPositionEx", wintypes.BOOL, ptr, ctypes.POINTER(wintypes.POINT))
        extent = bind(
            gdi,
            "GetTextExtentPoint32A",
            wintypes.BOOL,
            ptr,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.POINTER(wintypes.SIZE),
        )
        errors = []
        font_data = bind(gdi, "GetFontData", wintypes.DWORD, ptr, wintypes.DWORD, wintypes.DWORD, ptr, wintypes.DWORD)
        glyph_indices = bind(
            gdi, "GetGlyphIndicesW", wintypes.DWORD, ptr, ctypes.c_wchar_p, ctypes.c_int, ptr, wintypes.DWORD
        )
        char_width = bind(gdi, "GetCharWidth32W", wintypes.BOOL, ptr, wintypes.UINT, wintypes.UINT, ptr)
        glyph_metrics = bind(
            gdi, "GetGlyphOutlineW", wintypes.DWORD, ptr, wintypes.UINT, wintypes.UINT, ptr, wintypes.DWORD, ptr, ptr
        )
        extent_ex = bind(
            gdi,
            "GetTextExtentExPointW",
            wintypes.BOOL,
            ptr,
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.c_int,
            ptr,
            ptr,
            ptr,
        )

        @callback_type
        def callback(hdc, handles, record, count, _):
            try:
                function = ctypes.c_ushort.from_address(record + 4).value
                check(play(hdc, handles, record, count), "PlayMetaFileRecord")
                if function in (0x012D, 0x0521, 0x0A32):  # SelectObject, TextOut, ExtTextOut
                    selected = ctypes.create_unicode_buffer(64)
                    check(face(hdc, len(selected), selected), "GetTextFaceW")
                    if selected.value != family:
                        raise RuntimeError(f"Unexpected font substitution: {selected.value!r}")
                    if function == 0x012D:
                        for tag, expected in (tables or {}).items():
                            buffer = ctypes.create_string_buffer(len(expected))
                            length = font_data(hdc, int.from_bytes(tag.encode(), "little"), 0, buffer, len(expected))
                            if length != len(expected) or buffer.raw != expected:
                                raise RuntimeError(f"Selected font table differs: {tag}")
                        characters = sample.decode("ascii")
                        indices = (ctypes.c_ushort * len(characters))()
                        if glyph_indices(hdc, characters, len(characters), indices, 1) == 0xFFFFFFFF:
                            raise OSError("GetGlyphIndicesW failed")
                        widths = []
                        for character in characters:
                            width = ctypes.c_int()
                            check(
                                char_width(hdc, ord(character), ord(character), ctypes.byref(width)), "GetCharWidth32W"
                            )
                            widths.append(width.value)
                        print(f"characters={characters!r} glyphs={list(indices)} advances={widths}", flush=True)
                        identity = ctypes.create_string_buffer(struct.pack("<HhHhHhHh", 0, 1, 0, 0, 0, 0, 0, 1))
                        cells = []
                        for character in characters:
                            glyph = GlyphMetrics()
                            if (
                                glyph_metrics(hdc, ord(character), 0, ctypes.byref(glyph), 0, None, identity)
                                == 0xFFFFFFFF
                            ):
                                raise OSError("GetGlyphOutlineW failed")
                            cells.append(glyph.advance_x)
                        prefixes = (ctypes.c_int * len(characters))()
                        extent_size = wintypes.SIZE()
                        check(
                            extent_ex(
                                hdc, characters, len(characters), 0x7FFFFFFF, None, prefixes, ctypes.byref(extent_size)
                            ),
                            "GetTextExtentExPointW",
                        )
                        print(f"device_advances={cells} logical_prefixes={list(prefixes)}", flush=True)
                    value, point, size = TextMetrics(), wintypes.POINT(), wintypes.SIZE()
                    check(metrics(hdc, ctypes.byref(value)), "GetTextMetricsW")
                    check(position(hdc, ctypes.byref(point)), "GetCurrentPositionEx")
                    check(extent(hdc, sample, len(sample), ctypes.byref(size)), "GetTextExtentPoint32A")
                    print(
                        f"record={function:04x} face={selected.value!r} "
                        f"metrics={{ {', '.join(f'{name}={getattr(value, name)}' for name, _ in value._fields_)} }} "
                        f"extent={(size.cx, size.cy)} position={(point.x, point.y)}",
                        flush=True,
                    )
                return 1
            except Exception as error:  # noqa: BLE001 -- cannot raise across a ctypes callback
                errors.append(error)
                return 0

        buffer = ctypes.create_string_buffer(source)
        metafile = check(set_bits(len(source), buffer), "SetMetaFileBitsEx")
        try:
            result = enum(dc, metafile, callback, 0)
            if errors:
                raise errors[0]
            check(result, "EnumMetaFile")
        finally:
            delete(metafile)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    add = bind(gdi, "AddFontResourceExW", ctypes.c_int, ctypes.c_wchar_p, wintypes.DWORD, ctypes.c_void_p)
    remove = bind(gdi, "RemoveFontResourceExW", wintypes.BOOL, ctypes.c_wchar_p, wintypes.DWORD, ctypes.c_void_p)
    check(add(str(FONT_PATH), 0x10, None), "AddFontResourceExW")  # FR_PRIVATE
    try:
        for name, recorder in cases():
            print(f"\n[{name}]", flush=True)
            source = recorder.to_bytes()
            observe(source)
            (args.output / f"{name}.wmf").write_bytes(source)
            render_wmf(source, 128, 128).save(args.output / f"{name}.png")
    finally:
        check(remove(str(FONT_PATH), 0x10, None), "RemoveFontResourceExW")


if __name__ == "__main__":
    main()
