"""Local, read-only measurement of the production HALFTONE reducer.

Read inputs from the committed WMFs and compare the production bitmap sampler
against Windows PNGs. No duplicate renderer, fitting, tolerances or output writes.
Run with .venv/bin/python scripts/analyze-halftone.py.
"""

from pathlib import Path

from PIL import Image

from pillow_wmf import Metafile, TraceContext, play
from pillow_wmf.bitmap import decode_dib
from pillow_wmf.halftone import HalftoneReduction

ROOT = Path(__file__).resolve().parents[1] / "test" / "compatibility" / "wmf"


def examine(path):
    trace = TraceContext()
    play(Metafile.from_bytes(path.read_bytes()), trace, strict=True)
    differing = samples = transfers = largest = 0
    first = None
    with Image.open(path.with_suffix(".png")) as expected:
        for call in trace.calls:
            if call.name != "dib_stretch_blt":
                continue
            args = call.kwargs
            width, height = args["width"], args["height"]
            sw, sh = args["src_width"], args["src_height"]
            if not (0 < width <= sw and 0 < height <= sh):
                continue
            assert args["src_x"] == args["src_y"] == 0 and args["rop"] == 0xCC0020
            bitmap = decode_dib(args["source"])
            assert bitmap.height == sh
            output = HalftoneReduction(bitmap, 0, 0, sw, sh, width, height)
            transfers += 1
            for y in range(height):
                for x in range(width):
                    for channel, value in enumerate(output.pixel(x, y)):
                        native = expected.getpixel((args["x"] + x, args["y"] + y))[channel]
                        samples += 1
                        error = abs(value - native)
                        largest = max(largest, error)
                        differing += error != 0
                        if error and first is None:
                            first = (sw, sh, width, height, x, y, channel, value, native)
    print(
        f"{path.stem}: {transfers} reductions/equal-size transfers, {differing}/{samples} channels differ, max {largest}"
    )
    if first:
        print(f"  first (sw, sh, dw, dh, x, y, channel, actual, Windows): {first}")


def main():
    paths = sorted(ROOT.glob("halftone-kernel-*.wmf")) + sorted(ROOT.glob("halftone-basis-*.wmf"))
    paths += [ROOT / f"{name}.wmf" for name in ("halftone-two-dimensional", "dib-stretch-ratios-blt-0-4")]
    for path in paths:
        examine(path)


if __name__ == "__main__":
    main()
