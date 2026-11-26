"""Bounds of EMR_EXTTEXTOUTW records for rotated text, as a Windows metafile DC records them.

``recorded_text_bounds.json`` holds records the ``glyph-transforms`` probe
captured: runs of the controlled font drawn at (40, 40) with TA_TOP, in
GM_ADVANCED, through an escapement or a rotating world transform, with and
without explicit advances, transparent and opaque, some with the world origin
moved by sixteenths of a pixel.
"""

import json
import struct
from pathlib import Path

import pytest

from pillow_wmf import FontCollection, FontFace
from pillow_wmf.emf import Recorder
from pillow_wmf.objects import FontRequest, UnicodeText

ROOT = Path(__file__).parents[2]
GROUPS = json.loads(Path(__file__).with_name("recorded_text_bounds.json").read_text())
FONTS = FontCollection([FontFace.from_path(ROOT / "fonts/layout.ttf")])


@pytest.mark.parametrize(
    "group", GROUPS, ids=[f"{g['height']}-{g['escapement']}-{g['world'][0]}-{g['world'][4]}" for g in GROUPS]
)
def test_recorded_bounds_match_native(group):
    recorder = Recorder(fonts=FONTS)
    recorder.set_graphics_mode(2)
    recorder.set_world_transform(*group["world"])
    font = FontRequest(
        height=group["height"],
        escapement=group["escapement"],
        orientation=group["escapement"],
        weight=400,
        quality=3,
        face_name="Pillow WMF Test",
    )
    recorder.select_object(recorder.create_font(font))
    for text, mode, advances, _ in group["calls"]:
        recorder.set_background_mode(mode)
        recorder.set_text_alignment(0)
        recorder.ext_text_out(40, 40, UnicodeText(text), advances=tuple(advances or ()))
    data, position, bounds = recorder.to_bytes(), 0, []
    while position < len(data):
        kind, size = struct.unpack_from("<II", data, position)
        if kind == 84:  # EMR_EXTTEXTOUTW
            bounds.append(list(struct.unpack_from("<4i", data, position + 8)))
        position += size
    assert bounds == [native for *_, native in group["calls"]]
