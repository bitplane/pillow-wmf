"""Native ExtTextOutW runs of the controlled font under GM_ADVANCED world transforms.

``transformed_runs.json`` holds the pixels the ``glyph-transforms`` probe read
back for each run: text drawn at the device point (40, 48) with the given
world transform, font height, escapement (and orientation, when it differs)
and alignment.
"""

import json
from pathlib import Path

import pytest

from pillow_wmf import FontCollection, FontFace, RasterContext
from pillow_wmf.objects import FontRequest

ROOT = Path(__file__).parents[1]
RUNS = json.loads((Path(__file__).with_name("transformed_runs.json")).read_text())
FONTS = FontCollection([FontFace.from_path(ROOT / "fonts/layout.ttf")])


@pytest.mark.parametrize("run", RUNS, ids=[f"{r['case']}{r['height']}-{r['text']}-{r['align']}" for r in RUNS])
def test_runs_match_native_pixels(run):
    dc = RasterContext(96, 96, fonts=FONTS, trace_calls=False)
    dc.set_graphics_mode(2)
    dc.set_background_mode(1)
    dc.set_text_alignment(run["align"])
    dc.set_world_transform(*run["transform"], 40.0, 48.0)
    escapement = run["escapement"]
    font = FontRequest(
        height=run["height"],
        escapement=escapement,
        orientation=run.get("orientation", escapement),
        weight=400,
        quality=3,
        face_name="Pillow WMF Test",
    )
    dc.select_object(dc.create_font(font))
    dc.ext_text_out(0, 0, run["text"])
    native = {(x0 + i, y) for y, x0, mask in run["rows"] for i, c in enumerate(mask) if c == "#"}
    image = dc.image
    ours = {(x, y) for y in range(96) for x in range(96) if image.getpixel((x, y)) != (255, 255, 255)}
    assert ours == native
