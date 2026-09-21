"""Native single-byte NLS conversion and isolated controlled glyph placement."""

import argparse
import ctypes
import json
import runpy
from pathlib import Path

from codepage_cases import SINGLE_BYTE, font_bytes, single_byte_case
from windows_wmf_render import bind, check, private_fonts, render_wmf


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
    paths = []
    for codepage, (_, bit, sample) in SINGLE_BYTE.items():
        table = {}
        for data in [bytes([b]) for b in range(256)] + [b"a\xec", b"\xe0\xe1", b"\xa1\xd1"]:
            result = ctypes.create_unicode_buffer(8)
            count = convert(codepage, 0, data, len(data), result, 8)
            check(count, "MultiByteToWideChar")
            table[data.hex()] = result[:count]
        (args.output / f"cp{codepage}.json").write_text(json.dumps(table, ensure_ascii=True), encoding="ascii")
        path = args.output / f"cp{codepage}.ttf"
        path.write_bytes(font_bytes(codepage, bit, sample))
        paths.append(path)
    observe = runpy.run_path(str(Path(__file__).with_name("probe-windows-text.py")))["observe"]
    with private_fonts(paths):
        source = single_byte_case().to_bytes()
        observe(source, family=None, sample=b"AB")
        (args.output / "codepages-single-byte.wmf").write_bytes(source)
        render_wmf(source, 128, 128).save(args.output / "codepages-single-byte.png")


if __name__ == "__main__":
    main()
