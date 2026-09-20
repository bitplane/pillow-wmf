"""Generate exact native references for bounded DIB device acceptance."""

import argparse
from pathlib import Path

from dib_boundary_cases import SIZE, cases
from windows_wmf_render import render_wmf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, recorder in cases():
        source = recorder.to_bytes()
        (args.output / f"{name}.wmf").write_bytes(source)
        try:
            image = render_wmf(source, *SIZE)
        except OSError as error:
            print(f"{name}: rejected: {error}", flush=True)
        else:
            image.save(args.output / f"{name}.png")
            print(f"{name}: accepted; continuation={image.getpixel((120, 120))}", flush=True)


if __name__ == "__main__":
    main()
