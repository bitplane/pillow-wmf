"""Read-only, exact whole-metafile comparison shared by tests and diagnostics."""

import argparse
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from pillow_wmf import Metafile, RasterContext, play


@dataclass(frozen=True)
class Comparison:
    pixels: int
    differing_pixels: int
    differing_channels: int
    largest_error: int
    first: tuple | None


def compare_reference(source_path, png_path=None):
    source_path = Path(source_path)
    png_path = Path(png_path) if png_path is not None else source_path.with_suffix(".png")
    with Image.open(png_path) as reference:
        expected = reference.convert("RGB")
    context = RasterContext(expected.width, expected.height)
    issues = play(Metafile.from_bytes(source_path.read_bytes()), context, strict=True)
    if issues:
        raise RuntimeError(f"Incomplete playback of {source_path.name}: {issues}")
    differing_pixels = differing_channels = largest = 0
    first = None
    for index, (actual, native) in enumerate(
        zip(context.image.get_flattened_data(), expected.get_flattened_data(), strict=True)
    ):
        if actual == native:
            continue
        differing_pixels += 1
        errors = tuple(abs(a - n) for a, n in zip(actual, native, strict=True))
        differing_channels += sum(error != 0 for error in errors)
        largest = max(largest, *errors)
        if first is None:
            first = (index % expected.width, index // expected.width, actual, native)
    return Comparison(expected.width * expected.height, differing_pixels, differing_channels, largest, first)


def run_comparisons(paths):
    failed = False
    for item in paths:
        path, png = item if isinstance(item, tuple) else (item, item.with_suffix(".png"))
        try:
            result = compare_reference(path, png)
        except (OSError, ValueError, RuntimeError) as error:
            print(f"{png}: {type(error).__name__}: {error}")
            failed = True
            continue
        print(
            f"{png}: {result.differing_pixels}/{result.pixels} pixels differ, "
            f"{result.differing_channels} channels, max error {result.largest_error}"
        )
        if result.first is not None:
            print(f"  first (x, y, actual, Windows): {result.first}")
        failed |= result.differing_pixels != 0
    return int(failed)


def main(argv=None):
    from reference_cases import discover_pairs

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+", type=Path, help="One or more corpus directories")
    args = parser.parse_args(argv)
    pairs = []
    for root in args.roots:
        found = discover_pairs(root)
        if not found:
            parser.error(f"No WMFs found in {root}")
        pairs.extend(found)
    return run_comparisons(pairs)


if __name__ == "__main__":
    raise SystemExit(main())
