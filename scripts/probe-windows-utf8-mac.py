"""Observe UTF-8 and double-byte Macintosh NLS conversion and UTF-8 WMF spacing."""

import argparse
import ctypes
import itertools
import json
import runpy
from pathlib import Path

from utf8_cases import FAMILY, cases, font_bytes
from windows_wmf_render import bind, check, private_fonts, render_wmf


class CPInfo(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint), ("default", ctypes.c_ubyte * 2), ("leads", ctypes.c_ubyte * 12)]


def samples(codepage):
    yield from (bytes([b]) for b in range(256))
    yield from (bytes(pair) for pair in itertools.product(range(256), repeat=2))
    if codepage == 65001:
        # Continuation boundaries, overlong encodings, surrogates, truncated
        # sequences and the ends of Unicode's scalar range.
        boundaries = (0, 0x41, 0x7F, 0x80, 0x8F, 0x90, 0x9F, 0xA0, 0xBF, 0xC0, 0xFF)
        for first in range(0xE0, 0xF5):
            for tail in itertools.product(boundaries, repeat=2 if first < 0xF0 else 3):
                yield bytes((first, *tail))
        for character in (0x80, 0x7FF, 0x800, 0xD7FF, 0xE000, 0xFFFF, 0x10000, 0x10FFFF):
            encoded = chr(character).encode()
            for length in range(1, len(encoded) + 1):
                yield encoded[:length]
    else:
        for first in range(0x80, 256):
            for second in (0, 0x20, 0x40, 0x7F, 0x80, 0xFF):
                yield bytes((first, second, 0x41))


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
    for codepage in (65001, 10001, 10002, 10003, 10008):
        cpinfo = CPInfo()
        check(info(codepage, ctypes.byref(cpinfo)), "GetCPInfo")
        print(
            f"codepage={codepage} size={cpinfo.size} default={list(cpinfo.default)} leads={list(cpinfo.leads)}",
            flush=True,
        )
        decoded = {}
        for sample in samples(codepage):
            result = ctypes.create_unicode_buffer(16)
            count = convert(codepage, 0, sample, len(sample), result, 16)
            check(count, "MultiByteToWideChar")
            decoded[sample.hex()] = result[:count]
        (args.output / f"cp{codepage}.json").write_text(json.dumps(decoded, ensure_ascii=True), encoding="ascii")
    font = args.output / "utf8.ttf"
    font.write_bytes(font_bytes())
    observe = runpy.run_path(str(Path(__file__).with_name("probe-windows-text.py")))["observe"]
    with private_fonts([font]):
        for name, recorder in cases():
            print(f"\n[{name}]", flush=True)
            source = recorder.to_bytes()
            observe(source, family=FAMILY, sample=b"AB", characters="AB")
            (args.output / f"{name}.wmf").write_bytes(source)
            render_wmf(source, 128, 128).save(args.output / f"{name}.png")


if __name__ == "__main__":
    main()
