"""Native CP932 conversion and controlled-font WMF spacing, no pytest."""

import argparse
import ctypes
import json
import runpy
from pathlib import Path

from dbcs_cases import FAMILY, cases, font_bytes
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
    samples = [bytes([b]) for b in range(256)]
    samples += [bytes([a, b]) for a in (*range(0x81, 0xA0), *range(0xE0, 0xFD)) for b in range(256)]
    decoded = {}
    for sample in samples:
        result = ctypes.create_unicode_buffer(4)
        count = convert(932, 0, sample, len(sample), result, 4)
        check(count, "MultiByteToWideChar")
        decoded[sample.hex()] = result[:count]
    (args.output / "cp932.json").write_text(json.dumps(decoded, ensure_ascii=True), encoding="ascii")
    path = args.output / "cp932.ttf"
    path.write_bytes(font_bytes())
    observe = runpy.run_path(str(Path(__file__).with_name("probe-windows-text.py")))["observe"]
    with private_fonts([path]):
        for name, recorder in cases():
            print(f"\n[{name}]", flush=True)
            source = recorder.to_bytes()
            observe(source, family=FAMILY, sample=b"A\x83\xa1B", characters="A\u0393B")
            (args.output / f"{name}.wmf").write_bytes(source)
            render_wmf(source, 128, 128).save(args.output / f"{name}.png")


if __name__ == "__main__":
    main()
