"""Render WMF fixtures missing a Windows reference image."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from reference_cases import image_size, reference_cases

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "test" / "compatibility" / "wmf"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=FIXTURES)
    parser.add_argument("--size", type=image_size, help="Create a WIDTHxHEIGHT reference directory")
    parser.add_argument("--check", action="store_true", help="Linux-safe missing-reference preflight")
    args = parser.parse_args(argv)
    cases = list(reference_cases(args.root, args.size))
    if not cases:
        parser.error("No WMF fixtures found")
    missing = [(source, png, size) for source, png, size in cases if not png.is_file()]
    if args.check:
        print(f"{len(missing)} missing Windows reference images")
        if output := os.environ.get("GITHUB_OUTPUT"):
            with open(output, "a", encoding="utf-8") as stream:
                stream.write(f"missing={str(bool(missing)).lower()}\n")
        return 0
    if os.name != "nt":
        raise SystemExit("Native reference rendering requires Windows")
    from windows_wmf_render import render_wmf

    for fixture, png, size in missing:
        image = render_wmf(fixture.read_bytes(), *size)
        png.parent.mkdir(parents=True, exist_ok=True)
        image.save(png, format="PNG")
        print(f"rendered: {png}")
    print(f"Updated {len(missing)} of {len(cases)} reference images")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
