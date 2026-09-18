"""Render a small real-font batch; upload observations, not golden replacements."""

import argparse
import importlib.util
from pathlib import Path

from fontTools.ttLib import TTFont
from real_text_cases import FONTS, SAMPLES, SIZE, cases, fetch_fonts
from windows_wmf_render import private_fonts, render_wmf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    paths = fetch_fonts(args.output / "fonts")
    spec = importlib.util.spec_from_file_location("text_probe", Path(__file__).with_name("probe-windows-text.py"))
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    tables = {}
    for (_, family, _), path in zip(FONTS, paths, strict=True):
        with TTFont(path) as font:
            tables[family] = {tag: font.getTableData(tag) for tag in ("head", "hmtx", "glyf", "cmap")}
    with private_fonts(paths):
        for name, family, recorder in cases():
            print(f"\n[{name}]", flush=True)
            source = recorder.to_bytes()
            probe.observe(source, family=family, size=SIZE, sample=b" ".join(SAMPLES), tables=tables[family])
            (args.output / f"{name}.wmf").write_bytes(source)
            render_wmf(source, *SIZE).save(args.output / f"{name}.png")


if __name__ == "__main__":
    main()
