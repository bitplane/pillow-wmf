"""Render WMF fixtures missing a Windows reference image."""

from __future__ import annotations

import os
from pathlib import Path

from windows_wmf_render import render_wmf

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "test" / "compatibility" / "wmf"
WIDTH = HEIGHT = 128


def main() -> int:
    if os.name != "nt":
        raise SystemExit("Native reference rendering requires Windows")
    fixtures = sorted(FIXTURES.glob("*.wmf"))
    if not fixtures:
        raise SystemExit("No WMF fixtures found")
    changed = 0
    for fixture in fixtures:
        png = fixture.with_suffix(".png")
        if png.is_file():
            print(f"current: {fixture.name}")
            continue
        image = render_wmf(fixture.read_bytes(), WIDTH, HEIGHT)
        image.save(png, format="PNG")
        print(f"rendered: {fixture.name}")
        changed += 1
    print(f"Updated {changed} of {len(fixtures)} reference images")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
