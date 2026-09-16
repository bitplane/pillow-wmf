"""Render changed WMF fixtures with Windows GDI and write reference images."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from windows_wmf_render import render_wmf

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "test" / "compatibility" / "wmf"
ORACLE_VERSION = 1
SETTINGS = {"width": 128, "height": 128, "background": "white", "map_mode": "MM_ANISOTROPIC"}
RENDERER = Path(__file__).with_name("windows_wmf_render.py")


def expected_metadata(source: bytes) -> dict:
    return {
        "oracle": "Windows GDI PlayMetaFile",
        "oracle_version": ORACLE_VERSION,
        "renderer_sha256": hashlib.sha256(RENDERER.read_bytes()).hexdigest(),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "settings": SETTINGS,
    }


def main() -> int:
    if os.name != "nt":
        raise SystemExit("Native reference rendering requires Windows")
    fixtures = sorted(FIXTURES.glob("*.wmf"))
    if not fixtures:
        raise SystemExit("No WMF fixtures found")
    changed = 0
    for fixture in fixtures:
        png = fixture.with_suffix(".png")
        metadata_file = fixture.with_suffix(".json")
        source = fixture.read_bytes()
        metadata = expected_metadata(source)
        if png.is_file() and metadata_file.is_file():
            try:
                existing = json.loads(metadata_file.read_text(encoding="utf-8"))
                if (
                    all(existing.get(key) == value for key, value in metadata.items())
                    and existing.get("png_sha256") == hashlib.sha256(png.read_bytes()).hexdigest()
                ):
                    print(f"current: {fixture.name}")
                    continue
            except (OSError, ValueError):
                pass
        image = render_wmf(source, SETTINGS["width"], SETTINGS["height"])
        image.save(png, format="PNG")
        metadata["png_sha256"] = hashlib.sha256(png.read_bytes()).hexdigest()
        metadata_file.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"rendered: {fixture.name}")
        changed += 1
    print(f"Updated {changed} of {len(fixtures)} reference images")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
