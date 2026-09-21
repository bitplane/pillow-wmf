"""Observe whole-file success and continuation after invalid WMF operations."""

import argparse
import ctypes
from ctypes import wintypes
from pathlib import Path

from PIL import Image
from record_rejection_cases import cases, corpus_cases, header_cases, palette_cases
from windows_wmf_render import bind, check, reference_surface


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--corpus", action="store_true")
    parser.add_argument("--headers", action="store_true")
    parser.add_argument("--palettes", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    selected = (
        palette_cases()
        if args.palettes
        else header_cases()
        if args.headers
        else corpus_cases()
        if args.corpus
        else cases()
    )
    for name, metafile in selected:
        source = metafile.to_bytes()
        (args.output / f"{name}.wmf").write_bytes(source)
        with reference_surface(128, 128) as (gdi, dc, bits):
            ptr = ctypes.c_void_p
            create = bind(gdi, "SetMetaFileBitsEx", ptr, wintypes.UINT, ptr)
            delete = bind(gdi, "DeleteMetaFile", wintypes.BOOL, ptr)
            play = bind(gdi, "PlayMetaFile", wintypes.BOOL, ptr, ptr)
            flush = bind(gdi, "GdiFlush", wintypes.BOOL)
            handle = create(len(source), ctypes.create_string_buffer(source))
            if not handle:
                print(f"{name}: creation rejected, error={ctypes.get_last_error()}", flush=True)
                continue
            try:
                accepted = play(dc, handle)
                check(flush(), "GdiFlush")
                image = Image.frombytes("RGB", (128, 128), ctypes.string_at(bits, 128 * 128 * 4), "raw", "BGRX")
                image.save(args.output / f"{name}.png")
                ink = sum(pixel != (255, 255, 255) for pixel in image.get_flattened_data())
                mode = bind(gdi, "GetBkMode", ctypes.c_int, ptr)(dc)
                print(
                    f"{name}: accepted={accepted}, continuation={image.getpixel((120, 120))}, ink={ink}, background={mode}"
                )
            finally:
                delete(handle)


if __name__ == "__main__":
    main()
