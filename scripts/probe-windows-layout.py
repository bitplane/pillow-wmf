"""Targeted layout state observations; no pytest or reference regeneration."""

import ctypes
import runpy
from ctypes import wintypes
from pathlib import Path

from windows_wmf_render import bind, check, reference_surface


def main():
    helpers = runpy.run_path(str(Path(__file__).with_name("probe-windows-mapping.py")))
    for order in ("before", "after", "restore"):
        print(f"\n[WMF layout-mapping-{order}]", flush=True)
        source = (
            Path(__file__).resolve().parents[1] / "test/compatibility/wmf" / f"layout-mapping-{order}.wmf"
        ).read_bytes()
        with reference_surface(128, 128) as (gdi, dc, _):
            helpers["bind_probe"](gdi)
            ptr = ctypes.c_void_p
            set_bits = bind(gdi, "SetMetaFileBitsEx", ptr, wintypes.UINT, ptr)
            delete = bind(gdi, "DeleteMetaFile", wintypes.BOOL, ptr)
            play = bind(gdi, "PlayMetaFileRecord", wintypes.BOOL, ptr, ptr, ptr, ctypes.c_uint)
            callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ptr, ptr, ptr, ctypes.c_int, ctypes.c_ssize_t)
            enum = bind(gdi, "EnumMetaFile", wintypes.BOOL, ptr, ptr, callback_type, ctypes.c_ssize_t)
            errors = []

            @callback_type
            def callback(hdc, handles, record, count, _):
                try:
                    function = ctypes.c_ushort.from_address(record + 4).value
                    result = play(hdc, handles, record, count)
                    if function in (0x0103, 0x020B, 0x020C, 0x020D, 0x020E, 0x0149, 0x001E, 0x0127):
                        print(f"record={function:04x} result={result}")
                        helpers["snapshot"](gdi, hdc)
                    return 1
                except Exception as error:
                    errors.append(error)
                    return 0

            buffer = ctypes.create_string_buffer(source)
            metafile = check(set_bits(len(source), buffer), "SetMetaFileBitsEx")
            try:
                check(enum(dc, metafile, callback, 0), "EnumMetaFile")
                if errors:
                    raise errors[0]
            finally:
                delete(metafile)


if __name__ == "__main__":
    main()
