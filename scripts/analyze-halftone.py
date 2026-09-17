"""Local, read-only check of the *unproven* HALFTONE reduction model.

This is an experiment, not a renderer or an alternate compatibility test.
Read inputs from the committed WMFs and compare rational area averaging plus
a Laplacian against the Windows PNGs. No fitting, tolerances or output writes.
Run with .venv/bin/python scripts/analyze-halftone.py.
"""

from fractions import Fraction
from pathlib import Path

from PIL import Image

from pillow_wmf import Metafile, TraceContext, play
from pillow_wmf.bitmap import decode_dib

ROOT = Path(__file__).resolve().parents[1] / "test" / "compatibility" / "wmf"


def area(values, length):
    """Exact overlap integrals of piecewise-constant source pixels."""
    size = len(values)
    return [
        sum(
            value * max(0, min((k + 1) * length, (j + 1) * size) - max(k * length, j * size))
            for k, value in enumerate(values)
        )
        / size
        for j in range(length)
    ]


def candidate(source, width, height):
    """Reduction hypothesis only: no enlargement, clipping, ROPs or mapping."""
    sh, sw = len(source), len(source[0])
    assert 0 < width <= sw and 0 < height <= sh
    rows = [area(row, width) for row in source]
    both = width < sw and height < sh
    if both:
        rows = [[Fraction((value + Fraction(1, 2)).__floor__()) for value in row] for row in rows]
    columns = [area([row[x] for row in rows], height) for x in range(width)]
    gain = Fraction(1, 8 if both else 4)
    result = []
    for y in range(height):
        row = []
        for x in range(width):
            center = columns[x][y]
            difference = 0
            if width < sw:
                difference += 2 * center - columns[max(0, x - 1)][y] - columns[min(width - 1, x + 1)][y]
            if height < sh:
                difference += 2 * center - columns[x][max(0, y - 1)] - columns[x][min(height - 1, y + 1)]
            row.append(max(0, min(255, (center + gain * difference).__floor__())))
        result.append(row)
    return result


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
            transfers += 1
            for channel in range(3):
                source = [[Fraction(bitmap.pixel(x, y)[channel]) for x in range(sw)] for y in range(sh)]
                output = candidate(source, width, height)
                for y, row in enumerate(output):
                    for x, value in enumerate(row):
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
        print(f"  first (sw, sh, dw, dh, x, y, channel, candidate, Windows): {first}")


def main():
    paths = sorted(ROOT.glob("halftone-kernel-*.wmf")) + sorted(ROOT.glob("halftone-basis-*.wmf"))
    paths += [ROOT / f"{name}.wmf" for name in ("halftone-two-dimensional", "dib-stretch-ratios-blt-0-4")]
    for path in paths:
        examine(path)


if __name__ == "__main__":
    main()
