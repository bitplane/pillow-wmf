"""Read-only comparison of production enlargement against committed PNGs.

The experimental floating-point model has been removed. This exercises the
ordinary renderer, including its filter selection and fixed-decimal weights.
Run with .venv/bin/python scripts/analyze-halftone-expansion.py.
"""

from pathlib import Path

from PIL import Image

from pillow_wmf import Metafile, RasterContext, TraceContext, play

ROOT = Path(__file__).resolve().parents[1] / "test" / "compatibility" / "wmf"


def examine(path):
    trace = TraceContext()
    play(Metafile.from_bytes(path.read_bytes()), trace, strict=True)
    differences = samples = transfers = 0
    with Image.open(path.with_suffix(".png")) as expected:
        for call in trace.calls:
            if call.name not in ("dib_stretch_blt", "stretch_dib"):
                continue
            a = call.kwargs
            width, height = a["width"], a["height"]
            if width <= a["src_width"] and height <= a["src_height"]:
                continue
            context = RasterContext(width, height)
            context.set_stretch_mode(4)
            getattr(context, call.name)(**(a | {"x": 0, "y": 0}))
            transfers += 1
            for y in range(height):
                for x in range(width):
                    color = context.image.getpixel((x, y))
                    native = expected.getpixel((a["x"] + x, a["y"] + y))
                    differences += sum(v != n for v, n in zip(color, native, strict=True))
                    samples += 3
    print(f"{path.stem}: {transfers} enlargement/mixed transfers, {differences}/{samples} channels differ")


if __name__ == "__main__":
    paths = sorted(ROOT.glob("halftone-*.wmf")) + sorted(ROOT.glob("dib-stretch-ratios-*-4.wmf"))
    for path in paths:
        examine(path)
