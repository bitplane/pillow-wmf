#!/usr/bin/env python3
"""Put native and local renderings of the text sample sheets side by side.

    python scripts/text-samples-side-by-side.py NATIVE_DIR OUTPUT_DIR

NATIVE_DIR is the ``text-samples`` probe artifact. Each sheet's recorded EMF
is rendered with ``SystemFontCollection`` at the native image's size, and
OUTPUT_DIR receives ``NAME.png`` (Windows left, pillow-wmf right) and
``NAME-zoom.png`` (the top-left corner of both, enlarged three times).
"""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

from pillow_wmf import SystemFontCollection, render

GAP, LABEL = 12, 18
ZOOM, CROP = 3, (0, 0, 240, 160)


def pair(left, right, scale=1):
    left, right = (image.resize((image.width * scale, image.height * scale), Image.NEAREST) for image in (left, right))
    width, height = left.width + GAP + right.width, LABEL + max(left.height, right.height)
    result = Image.new("RGB", (width, height), (128, 128, 128))
    result.paste(left, (0, LABEL))
    result.paste(right, (left.width + GAP, LABEL))
    draw = ImageDraw.Draw(result)
    draw.text((4, 3), "Windows GDI", fill=(255, 255, 255))
    draw.text((left.width + GAP + 4, 3), "pillow-wmf", fill=(255, 255, 255))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("native", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)
    fonts = SystemFontCollection()
    for source in sorted(arguments.native.glob("*.emf")):
        native = Image.open(source.with_suffix(".png")).convert("RGB")
        local = render(source.read_bytes(), native.size, fonts=fonts)
        pair(native, local).save(arguments.output / f"{source.stem}.png")
        pair(native.crop(CROP), local.crop(CROP), ZOOM).save(arguments.output / f"{source.stem}-zoom.png")
        print(arguments.output / f"{source.stem}.png")
    for substitution in fonts.substitutions:
        print(f"substitution: {substitution.requested} -> {substitution.selected} ({substitution.reason})")


if __name__ == "__main__":
    main()
