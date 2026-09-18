"""Verify byte-to-glyph mappings using identical fonts and native ANSI APIs."""

import argparse
import ctypes
import importlib.util
from pathlib import Path

from fontTools.ttLib import TTFont
from real_text_cases import fetch_fonts
from text_encoding_cases import ENCODING_FAMILY, FONT_ROOT, SIZE, SYMBOL_FAMILY, cases
from windows_wmf_render import bind, check, private_fonts, render_wmf

from pillow_wmf import Recorder
from pillow_wmf.wmf.objects import Font


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--missing-only", action="store_true")
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
    sample_bytes = bytes(range(256))
    for codepage in (1252, 1251):
        decoded = ctypes.create_unicode_buffer(256)
        check(convert(codepage, 0, sample_bytes, 256, decoded, 256), "MultiByteToWideChar")
        print(f"codepage={codepage} unicode={[ord(c) for c in decoded]}", flush=True)
    paths = fetch_fonts(args.output / "fonts")
    for filename in ("encoding.ttf", "symbols.ttf"):
        path = args.output / "fonts" / filename
        path.write_bytes((FONT_ROOT / filename).read_bytes())
        paths.append(path)
    spec = importlib.util.spec_from_file_location("text_probe", Path(__file__).with_name("probe-windows-text.py"))
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    tables = {}
    for family, path in zip(("Noto Sans", "Noto Serif", ENCODING_FAMILY, SYMBOL_FAMILY), paths, strict=True):
        with TTFont(path) as font:
            tables[family] = {tag: font.getTableData(tag) for tag in ("head", "hmtx", "glyf", "cmap")}
    with private_fonts(paths):
        for name, family, sample, encoding, recorder in cases(missing_only=args.missing_only):
            print(f"\n[{name}]", flush=True)
            if encoding == "symbol":
                characters = "".join(chr(0xF000 | byte) for byte in sample)
            else:
                characters = "".join(bytes([byte]).decode(encoding, errors="surrogateescape") for byte in sample)
                characters = "".join(chr(ord(c) - 0xDC00) if 0xDC80 <= ord(c) <= 0xDCFF else c for c in characters)
            source = recorder.to_bytes()
            probe.observe(source, family=family, size=SIZE, sample=sample, tables=tables[family], characters=characters)
            (args.output / f"{name}.wmf").write_bytes(source)
            render_wmf(source, *SIZE).save(args.output / f"{name}.png")
    if args.missing_only:
        return
    # Native installed fonts are queried, never uploaded or silently replaced.
    for family in ("Symbol", "Wingdings"):
        for charset in (1, 2):
            print(f"\n[native-{family}-{charset}]", flush=True)
            recorder = Recorder()
            recorder.select_object(
                recorder.create_font(
                    Font(height=-24, weight=400, quality=3, charset=charset, face_name=family.encode().ljust(32, b"\0"))
                )
            )
            sample = b"AB \x80\xe9\xff"
            probe.observe(
                recorder.to_bytes(), family=family, sample=sample, characters="".join(chr(0xF000 | b) for b in sample)
            )


if __name__ == "__main__":
    main()
