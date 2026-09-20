"""Measure native decoration thickness; original fonts only, no test suite."""

import argparse
import runpy
from pathlib import Path

from fontTools.ttLib import TTFont
from text_decoration_cases import SIZE, THICKNESSES, cases, family_name, font_bytes
from windows_wmf_render import private_fonts, render_wmf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    directory = args.output / "fonts"
    directory.mkdir(parents=True, exist_ok=True)
    paths, tables = [], {}
    for thickness in THICKNESSES:
        path = directory / f"decoration-{thickness}.ttf"
        path.write_bytes(font_bytes(thickness))
        paths.append(path)
        with TTFont(path) as font:
            tables[family_name(thickness)] = {
                tag: font.getTableData(tag) for tag in ("head", "glyf", "hmtx", "cmap", "OS/2", "post")
            }
    observe = runpy.run_path(str(Path(__file__).with_name("probe-windows-text.py")))["observe"]
    with private_fonts(paths):
        for name, family, recorder in cases():
            print(f"\n[{name}]", flush=True)
            source = recorder.to_bytes()
            observe(source, family=family, size=SIZE, sample=b"A B", tables=tables[family])
            (args.output / f"{name}.wmf").write_bytes(source)
            render_wmf(source, *SIZE).save(args.output / f"{name}.png")


if __name__ == "__main__":
    main()
