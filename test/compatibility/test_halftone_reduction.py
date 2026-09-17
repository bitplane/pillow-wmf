"""Individual transfers supplement, never replace, the full atlas comparisons."""

from pathlib import Path

import pytest
from PIL import Image

from pillow_wmf import Metafile, RasterContext, TraceContext, play

ROOT = Path(__file__).parent / "wmf"


def reductions():
    paths = sorted(ROOT.glob("halftone-*.wmf")) + sorted(ROOT.glob("dib-stretch-ratios-*-4.wmf"))
    for path in paths:
        trace = TraceContext()
        play(Metafile.from_bytes(path.read_bytes()), trace, strict=True)
        for index, call in enumerate(trace.calls):
            if call.name not in ("dib_stretch_blt", "stretch_dib"):
                continue
            a = call.kwargs
            # This supplementary test isolates SRCCOPY. The full atlas test
            # retains brushes/destination state for ternary ROP comparisons.
            if a["rop"] != 0xCC0020:
                continue
            if 0 < a["width"] <= a["src_width"] and 0 < a["height"] <= a["src_height"]:
                yield pytest.param(path, call, id=f"{path.stem}-{index}")


@pytest.mark.parametrize("path,call", tuple(reductions()))
def test_native_halftone_reduction(path, call):
    a = call.kwargs
    context = RasterContext(a["width"], a["height"])
    context.set_stretch_mode(4)
    getattr(context, call.name)(**(a | {"x": 0, "y": 0}))
    with Image.open(path.with_suffix(".png")) as atlas:
        expected = atlas.crop((a["x"], a["y"], a["x"] + a["width"], a["y"] + a["height"]))
        assert context.image.tobytes() == expected.convert("RGB").tobytes()
