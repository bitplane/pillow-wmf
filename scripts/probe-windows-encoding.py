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
    parser.add_argument("--sizing-only", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location("text_probe", Path(__file__).with_name("probe-windows-text.py"))
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    if args.sizing_only:
        inspect_fallback_sizing(args.output, probe)
        return
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
            probe.observe(
                source,
                family=family,
                size=SIZE,
                sample=sample,
                tables=tables[family],
                characters=characters,
                shaping=args.missing_only,
            )
            (args.output / f"{name}.wmf").write_bytes(source)
            render_wmf(source, *SIZE).save(args.output / f"{name}.png")
            if args.missing_only:
                inspect_native_text(source)
    if args.missing_only:
        import os
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\FontLink\SystemLink"
        ) as key:
            print("system_links=", winreg.QueryValueEx(key, "Microsoft Sans Serif")[0], flush=True)
        for path in sorted((Path(os.environ["WINDIR"]) / "Fonts").glob("*.tt[fc]")):
            try:
                with TTFont(path, fontNumber=0, lazy=True) as font:
                    cmap = font.getBestCmap() or {}
                    if 0 in cmap or 0x81 in cmap:

                        def glyph_metrics(codepoint):
                            name = cmap.get(codepoint, ".notdef")
                            glyph = font["glyf"][name]
                            return (font.getGlyphID(name), font["hmtx"][name], glyph.numberOfContours)

                        print(
                            f"control_face={font['name'].getBestFamilyName()!r} "
                            f"em={font['head'].unitsPerEm} "
                            f"tables={font.keys()} "
                            f"coverage={[(c, cmap.get(c), glyph_metrics(c)) for c in (0, 1, 0x81)]}",
                            flush=True,
                        )
            except Exception as error:
                print(f"font inspection skipped: {path.name}: {error}", flush=True)
        recorder = Recorder()
        recorder.select_object(
            recorder.create_font(
                Font(height=-24, weight=400, quality=3, face_name=b"Microsoft Sans Serif".ljust(32, b"\0"))
            )
        )
        sample = b"C\0\x01\x08\t\n\x0b\x0c\r\x1f\x7f\x81\x8d"
        print("[fallback-face]", flush=True)
        probe.observe(
            recorder.to_bytes(),
            family="Microsoft Sans Serif",
            sample=sample,
            characters="".join(map(chr, sample)),
            shaping=True,
        )
        for family in ("MS UI Gothic", "PMingLiU", "Gulim"):
            recorder = Recorder()
            recorder.select_object(
                recorder.create_font(
                    Font(height=-24, weight=400, quality=3, face_name=family.encode().ljust(32, b"\0"))
                )
            )
            print(f"[linked-face-{family}]", flush=True)
            probe.observe(recorder.to_bytes(), family=family, sample=b"\0\x01\x81", characters="\0\x01\x81")
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


def inspect_fallback_sizing(output, probe):
    """Separate shaping fallback realization from direct and linked font sizes."""
    path = FONT_ROOT / "encoding.ttf"
    with TTFont(path) as font:
        tables = {tag: font.getTableData(tag) for tag in ("head", "hmtx", "glyf", "cmap")}
    with private_fonts([path]):
        for height, width in ((-12, 0), (-24, 0), (-31, 0), (29, 0), (-24, 11)):
            for family in (ENCODING_FAMILY, "Microsoft Sans Serif", "PMingLiU"):
                recorder = Recorder()
                recorder.set_window_extent(*SIZE)
                recorder.set_viewport_extent(*SIZE)
                recorder.select_object(
                    recorder.create_font(
                        Font(
                            height=height,
                            width=width,
                            weight=400,
                            quality=3,
                            face_name=family.encode().ljust(32, b"\0"),
                        )
                    )
                )
                recorder.set_background_mode(1)
                recorder.set_text_alignment(25)
                recorder.move_to(12, 80)
                sample = b"A\x81\0\x01B"
                recorder.text_out(0, 0, sample)
                recorder.line_to(600, 80)
                name = f"{family.replace(' ', '-')}-{height}-{width}"
                print(f"\n[{name}]", flush=True)
                source = recorder.to_bytes()
                probe.observe(
                    source,
                    family=family,
                    size=SIZE,
                    sample=sample,
                    characters="".join(map(chr, sample)),
                    tables=tables if family == ENCODING_FAMILY else None,
                )
                inspect_native_text(source)
                (output / f"{name}.wmf").write_bytes(source)
                render_wmf(source, *SIZE).save(output / f"{name}.png")


def inspect_native_text(source):
    """Capture GDI's downstream font/text records to identify fallback faces."""
    from windows_wmf_render import reference_surface

    with reference_surface(*SIZE) as (gdi, dc, _):
        ptr = ctypes.c_void_p
        create = bind(gdi, "CreateEnhMetaFileW", ptr, ptr, ptr, ptr, ptr)
        close = bind(gdi, "CloseEnhMetaFile", ptr, ptr)
        bits = bind(gdi, "SetMetaFileBitsEx", ptr, ctypes.c_uint, ptr)
        play = bind(gdi, "PlayMetaFile", ctypes.c_int, ptr, ptr)
        delete = bind(gdi, "DeleteMetaFile", ctypes.c_int, ptr)
        delete_enh = bind(gdi, "DeleteEnhMetaFile", ctypes.c_int, ptr)
        get_bits = bind(gdi, "GetEnhMetaFileBits", ctypes.c_uint, ptr, ctypes.c_uint, ptr)
        recording = check(create(dc, None, None, None), "CreateEnhMetaFileW")
        metafile = check(bits(len(source), source), "SetMetaFileBitsEx")
        try:
            check(play(recording, metafile), "PlayMetaFile")
        finally:
            delete(metafile)
            enhanced = check(close(recording), "CloseEnhMetaFile")
        try:
            size = get_bits(enhanced, 0, None)
            data = ctypes.create_string_buffer(size)
            check(get_bits(enhanced, size, data), "GetEnhMetaFileBits")
            import struct

            offset = 0
            while offset < size:
                kind, length = struct.unpack_from("<II", data.raw, offset)
                record = data.raw[offset : offset + length]
                if kind == 82:
                    family = record[40:104].decode("utf-16-le").split(chr(0))[0]
                    height, width = struct.unpack_from("<ii", record, 12)
                    print(f"native font={family!r} height={height} width={width}", flush=True)
                elif kind == 84:
                    count, string_at, flags = struct.unpack_from("<III", record, 44)
                    values = struct.unpack_from(f"<{count}H", record, string_at)
                    print(f"native text flags={flags:#x} values={values}", flush=True)
                offset += length
        finally:
            delete_enh(enhanced)


if __name__ == "__main__":
    main()
