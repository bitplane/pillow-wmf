"""Observe OEM/Mac NLS mappings and unknown-charset font selection."""

import argparse
import ctypes
import json
import runpy
from pathlib import Path

from environment_cases import FAMILY, MAC_PAGES, OEM_PAGES, cases, font_bytes
from windows_wmf_render import bind, check, private_fonts, reference_surface, render_wmf


class CPInfo(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint), ("default", ctypes.c_ubyte * 2), ("leads", ctypes.c_ubyte * 12)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    convert = bind(
        kernel,
        "MultiByteToWideChar",
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.c_ulong,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_wchar_p,
        ctypes.c_int,
    )
    info = bind(kernel, "GetCPInfo", ctypes.c_int, ctypes.c_uint, ctypes.POINTER(CPInfo))
    for codepage in (*OEM_PAGES, *MAC_PAGES):
        cpinfo = CPInfo()
        if not info(codepage, ctypes.byref(cpinfo)):
            print(f"codepage={codepage} unavailable", flush=True)
            continue
        print(f"codepage={codepage} max_size={cpinfo.size}", flush=True)
        if cpinfo.size != 1:
            continue
        table = []
        for byte in range(256):
            result = ctypes.create_unicode_buffer(8)
            count = convert(codepage, 0, bytes([byte]), 1, result, 8)
            check(count, "MultiByteToWideChar")
            table.append(result[:count])
        (args.output / f"cp{codepage}.json").write_text(json.dumps(table, ensure_ascii=True), encoding="ascii")
    path = args.output / "environment.ttf"
    path.write_bytes(font_bytes())
    with private_fonts([path]):
        with reference_surface(128, 128) as (gdi, dc, _):
            ptr = ctypes.c_void_p
            create = bind(gdi, "CreateFontW", ptr, *([ctypes.c_int] * 5), *([ctypes.c_uint] * 8), ctypes.c_wchar_p)
            select = bind(gdi, "SelectObject", ptr, ptr, ptr)
            delete = bind(gdi, "DeleteObject", ctypes.c_int, ptr)
            face = bind(gdi, "GetTextFaceW", ctypes.c_int, ptr, ctypes.c_int, ctypes.c_wchar_p)
            charset_info = bind(gdi, "GetTextCharsetInfo", ctypes.c_int, ptr, ptr, ctypes.c_uint)
            selections = []
            for family, hint in (
                (FAMILY, 0),
                ("Arial", 0),
                ("Symbol", 0),
                ("Wingdings", 0),
                ("Unavailable", 0),
                ("Unavailable", 16),
                ("Unavailable", 49),
            ):
                for charset in (0, 1, 2, 3, 77, 160, 254, 255):
                    font = check(create(-20, 0, 0, 0, 400, 0, 0, 0, charset, 0, 0, 3, hint, family), "CreateFontW")
                    old = check(select(dc, font), "SelectObject")
                    try:
                        name = ctypes.create_unicode_buffer(64)
                        check(face(dc, len(name), name), "GetTextFaceW")
                        selections.append(
                            dict(
                                family=family,
                                hint=hint,
                                requested=charset,
                                selected=name.value,
                                charset=charset_info(dc, None, 0),
                            )
                        )
                    finally:
                        select(dc, old)
                        delete(font)
            (args.output / "selections.json").write_text(json.dumps(selections, indent=2), encoding="ascii")
        observe = runpy.run_path(str(Path(__file__).with_name("probe-windows-text.py")))["observe"]
        for name, recorder in cases():
            source = recorder.to_bytes()
            observe(source, family=None, sample=b"AB")
            (args.output / f"{name}.wmf").write_bytes(source)
            render_wmf(source, 128, 128).save(args.output / f"{name}.png")


if __name__ == "__main__":
    main()
