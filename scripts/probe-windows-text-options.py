"""Measure WMF playback, not just direct ExtTextOut API behaviour."""

import argparse
import ctypes
from ctypes import wintypes
from pathlib import Path

from fontTools.ttLib import TTFont
from text_option_cases import FAMILY, FONT_PATH, SIZE, cases, placement_cases, rtl_cases
from windows_wmf_render import bind, check, private_fonts, reference_surface, render_wmf


def observe(source, tables):
    with reference_surface(*SIZE) as (gdi, dc, _):
        ptr = ctypes.c_void_p
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ptr, ptr, ptr, ctypes.c_int, ctypes.c_ssize_t)
        enum = bind(gdi, "EnumMetaFile", wintypes.BOOL, ptr, ptr, callback_type, ctypes.c_ssize_t)
        play = bind(gdi, "PlayMetaFileRecord", wintypes.BOOL, ptr, ptr, ptr, wintypes.UINT)
        create = bind(gdi, "SetMetaFileBitsEx", ptr, wintypes.UINT, ptr)
        delete = bind(gdi, "DeleteMetaFile", wintypes.BOOL, ptr)
        position = bind(gdi, "GetCurrentPositionEx", wintypes.BOOL, ptr, ctypes.POINTER(wintypes.POINT))
        face = bind(gdi, "GetTextFaceW", ctypes.c_int, ptr, ctypes.c_int, ctypes.c_wchar_p)
        font_data = bind(gdi, "GetFontData", wintypes.DWORD, ptr, wintypes.DWORD, wintypes.DWORD, ptr, wintypes.DWORD)
        errors = []

        @callback_type
        def callback(hdc, handles, record, count, _):
            try:
                function = ctypes.c_ushort.from_address(record + 4).value
                accepted = play(hdc, handles, record, count)
                if function == 0x012D:
                    selected = ctypes.create_unicode_buffer(64)
                    check(face(hdc, 64, selected), "GetTextFaceW")
                    if selected.value != FAMILY:
                        raise RuntimeError(f"Unexpected substitution: {selected.value!r}")
                    for tag, expected in tables.items():
                        buffer = ctypes.create_string_buffer(len(expected))
                        size = font_data(hdc, int.from_bytes(tag.encode(), "little"), 0, buffer, len(expected))
                        if size != len(expected) or buffer.raw != expected:
                            raise RuntimeError(f"Selected font differs: {tag}")
                point = wintypes.POINT()
                check(position(hdc, ctypes.byref(point)), "GetCurrentPositionEx")
                print(f"record={function:04x} accepted={int(accepted)} position=({point.x}, {point.y})", flush=True)
            except Exception as error:
                errors.append(error)
                return 0
            return 1

        metafile = check(create(len(source), ctypes.create_string_buffer(source)), "SetMetaFileBitsEx")
        try:
            accepted = enum(dc, metafile, callback, 0)
            if errors:
                raise errors[0]
            check(accepted, "EnumMetaFile")
        finally:
            delete(metafile)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--placement", action="store_true")
    parser.add_argument("--rtl", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with TTFont(FONT_PATH) as font:
        tables = {tag: font.getTableData(tag) for tag in ("head", "hmtx", "glyf", "cmap")}
    with private_fonts([FONT_PATH]):
        selected = rtl_cases if args.rtl else placement_cases if args.placement else cases
        for name, recorder in selected():
            print(f"[{name}]", flush=True)
            source = recorder.to_bytes()
            (args.output / f"{name}.wmf").write_bytes(source)
            observe(source, tables)
            try:
                image = render_wmf(source, *SIZE)
            except OSError as error:
                print(f"whole-file-rejected: {error}", flush=True)
            else:
                image.save(args.output / f"{name}.png")


if __name__ == "__main__":
    main()
