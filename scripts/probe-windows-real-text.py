"""Render a small real-font batch; upload observations, not golden replacements."""

import argparse
import importlib.util
from pathlib import Path

from fontTools.ttLib import TTFont
from real_text_cases import FONTS, SAMPLES, SIZE, cases, fetch_fonts
from test_font import FAMILY, FONT_PATH
from text_layout_cases import SIZE as LAYOUT_SIZE
from text_layout_cases import cases as layout_cases
from text_style_cases import SAMPLE as STYLE_SAMPLE
from text_style_cases import SIZE as STYLE_SIZE
from text_style_cases import cases as style_cases
from windows_wmf_render import private_fonts, render_wmf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--layout", action="store_true")
    parser.add_argument("--styles", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    paths = fetch_fonts(args.output / "fonts")
    if args.layout or args.styles:
        destination = args.output / "fonts" / FONT_PATH.name
        destination.write_bytes(FONT_PATH.read_bytes())
        paths.append(destination)
    spec = importlib.util.spec_from_file_location("text_probe", Path(__file__).with_name("probe-windows-text.py"))
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    tables = {}
    families = [family for _, family, _ in FONTS] + ([FAMILY] if args.layout or args.styles else [])
    for family, path in zip(families, paths, strict=True):
        with TTFont(path) as font:
            tables[family] = {tag: font.getTableData(tag) for tag in ("head", "hmtx", "glyf", "cmap")}
    with private_fonts(paths):
        inputs = style_cases() if args.styles else layout_cases() if args.layout else cases()
        for name, family, recorder in inputs:
            print(f"\n[{name}]", flush=True)
            source = recorder.to_bytes()
            size = STYLE_SIZE if args.styles else LAYOUT_SIZE if args.layout else SIZE
            sample = STYLE_SAMPLE if args.styles else b"A B A B" if args.layout else b" ".join(SAMPLES)
            probe.observe(source, family=family, size=size, sample=sample, tables=tables[family])
            (args.output / f"{name}.wmf").write_bytes(source)
            render_wmf(source, *size).save(args.output / f"{name}.png")


if __name__ == "__main__":
    main()
