"""Measure installed Wingdings metrics without distributing the font itself."""

import argparse
import os
from pathlib import Path
import runpy

from fontTools.ttLib import TTFont

from pillow_wmf import Recorder
from pillow_wmf.wmf.objects import Font
from windows_wmf_render import render_wmf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--visual", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    path = Path(os.environ["WINDIR"]) / "Fonts" / "wingding.ttf"
    with TTFont(path) as font:
        tables = {tag: font.getTableData(tag) for tag in ("head", "OS/2", "hhea", "hmtx", "glyf", "cmap")}
        for tag, fields in {
            "head": ("unitsPerEm", "xMin", "yMin", "xMax", "yMax"),
            "OS/2": ("xAvgCharWidth", "usWinAscent", "usWinDescent", "sTypoAscender", "sTypoDescender", "sCapHeight"),
            "hhea": ("ascent", "descent", "lineGap"),
        }.items():
            print(tag, {f: getattr(font[tag], f, None) for f in fields}, flush=True)
        cmap = next(t.cmap for t in font["cmap"].tables if t.platformID == 3 and t.platEncID == 0)
        for codepoint, name in sorted(cmap.items()):
            glyph = font["glyf"][name]
            print(
                "glyph",
                codepoint & 255,
                font["hmtx"][name][0],
                tuple(getattr(glyph, key, 0) for key in ("xMin", "yMin", "xMax", "yMax")),
                flush=True,
            )
    observe = runpy.run_path(str(Path(__file__).with_name("probe-windows-text.py")))["observe"]
    if args.visual:
        from wingdings_visual_cases import SIZE, SAMPLE, cases

        for name, recorder in cases():
            data = recorder.to_bytes()
            print(f"\n[{name}]", flush=True)
            observe(
                data,
                family="Wingdings",
                sample=SAMPLE,
                characters="".join(chr(0xF000 | byte) for byte in SAMPLE),
                size=SIZE,
                tables=tables,
            )
            (args.output / f"wingdings-visual-{name}.wmf").write_bytes(data)
            render_wmf(data, *SIZE).save(args.output / f"wingdings-visual-{name}.png")
        return
    for profile, height, width, angle in (
        ("natural", -48, 0, 0),
        ("cell", 48, 0, 0),
        ("wide", -48, 43, 0),
        ("angled", -48, 43, -27),
    ):
        recorder = Recorder()
        recorder.set_window_extent(320, 100)
        recorder.set_viewport_extent(320, 100)
        recorder.set_background_mode(1)
        recorder.set_text_alignment(24)
        recorder.select_object(
            recorder.create_font(
                Font(
                    height=height,
                    width=width,
                    escapement=angle,
                    weight=400,
                    charset=2,
                    quality=2,
                    face_name=b"Wingdings".ljust(32, b"\0"),
                )
            )
        )
        recorder.text_out(12, 65, b"AEFS")
        data = recorder.to_bytes()
        print(f"\n[{profile}]", flush=True)
        observe(
            data,
            family="Wingdings",
            sample=b"AEFS",
            characters="\uf041\uf045\uf046\uf053",
            size=(320, 100),
            tables=tables,
        )
        (args.output / f"wingdings-{profile}.wmf").write_bytes(data)
        render_wmf(data, 320, 100).save(args.output / f"wingdings-{profile}.png")


if __name__ == "__main__":
    main()
