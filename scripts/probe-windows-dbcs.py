"""Native CP932 conversion and controlled-font WMF spacing, no pytest."""

import argparse
import ctypes
import json
import runpy
from pathlib import Path

from dbcs_cases import (
    EXTENDED_CODEPAGES,
    EXTENDED_FAMILY,
    FAMILY,
    cases,
    extended_cases,
    extended_font_bytes,
    font_bytes,
    spacing_cases,
)
from windows_wmf_render import bind, check, private_fonts, render_wmf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extended", action="store_true", help="Probe GBK, Korean, Big5 and Johab instead of CP932")
    parser.add_argument("--spacing", action="store_true", help="Only probe short Hangul advances; no NLS scan")
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
    codepages = () if args.spacing else EXTENDED_CODEPAGES if args.extended else (932,)
    for codepage in codepages:
        samples = [bytes([b]) for b in range(256)]
        leads = range(256) if args.extended else (*range(0x81, 0xA0), *range(0xE0, 0xFD))
        samples += [bytes([a, b]) for a in leads for b in range(256)]
        samples += [bytes([a, b, 0x41]) for a in range(0x80, 256) for b in (0, 0x20, 0x40, 0x7F, 0x80, 0xFF)]
        decoded = {}
        for sample in samples:
            result = ctypes.create_unicode_buffer(4)
            count = convert(codepage, 0, sample, len(sample), result, 4)
            check(count, "MultiByteToWideChar")
            decoded[sample.hex()] = result[:count]
        (args.output / f"cp{codepage}.json").write_text(json.dumps(decoded, ensure_ascii=True), encoding="ascii")
    path = args.output / ("dbcs.ttf" if args.extended else "cp932.ttf")
    path.write_bytes(extended_font_bytes() if args.extended else font_bytes())
    observe = runpy.run_path(str(Path(__file__).with_name("probe-windows-text.py")))["observe"]
    with private_fonts([path]):
        selected_cases = spacing_cases() if args.spacing else extended_cases() if args.extended else cases()
        for name, recorder in selected_cases:
            print(f"\n[{name}]", flush=True)
            source = recorder.to_bytes()
            observe(source, family=EXTENDED_FAMILY if args.extended else FAMILY, sample=b"AB", characters="AB")
            (args.output / f"{name}.wmf").write_bytes(source)
            render_wmf(source, 128, 128).save(args.output / f"{name}.png")


if __name__ == "__main__":
    main()
