"""Explicitly selected native verification of the DIB brush slice only."""

import runpy
from pathlib import Path

from windows_wmf_render import render_wmf

from pillow_wmf import Metafile, RasterContext, play


def verify():
    cases = runpy.run_path(str(Path(__file__).with_name("generate-wmf-fixtures.py")))["dib_brush_cases"]
    failures = 0
    for count, (name, recorder) in enumerate(cases(), 1):
        source = recorder.to_bytes()
        expected = render_wmf(source, 128, 128)
        context = RasterContext(128, 128)
        play(Metafile.from_bytes(source), context, strict=True)
        differing = sum(
            a != b for a, b in zip(expected.get_flattened_data(), context.image.get_flattened_data(), strict=True)
        )
        if differing:
            failures += 1
            print(f"FAIL {name}: {differing} pixels", flush=True)
    print(f"DIB brushes: {count} native cases, {failures} failures", flush=True)
    assert failures == 0


if __name__ == "__main__":
    verify()
