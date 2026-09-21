"""Render COLORREF high-byte flags through brushes, pens and SetPixel."""

import argparse
from pathlib import Path

from corpus_boundary_cases import color_cases
from windows_wmf_render import render_wmf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, recorder in color_cases():
        source = recorder.to_bytes()
        image = render_wmf(source, 128, 128)
        (args.output / f"{name}.wmf").write_bytes(source)
        image.save(args.output / f"{name}.png")
        for flag in range(256):
            x, y = flag % 16 * 8, flag // 16 * 8
            print(
                f"{flag:02x}: brush={image.getpixel((x + 1, y + 1))} "
                f"pen={image.getpixel((x + 1, y + 5))} pixel={image.getpixel((x + 6, y + 6))}"
            )


if __name__ == "__main__":
    main()
