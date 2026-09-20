"""Font-selection hints and LTR flags do not change an explicit TrueType face."""

from pathlib import Path

import pytest

from pillow_wmf import FontCollection, FontFace, RasterContext
from pillow_wmf.wmf.objects import Font


def draw(*, mapper=0, options=0, alignment=0):
    face = FontFace.from_path(Path(__file__).parents[1] / "fonts/layout.ttf")
    dc = RasterContext(192, 128, fonts=FontCollection([face]))
    dc.select_object(dc.create_font(Font(height=-24, quality=3, face_name=face.family.encode())))
    dc.set_background_mode(1)
    dc.set_mapper_flags(mapper)
    dc.set_text_alignment(25 | alignment)
    dc.move_to(20, 40)
    dc.ext_text_out(999, 999, b"ABA", options=options, advances=(19, 23, 17))
    return dc.image.tobytes(), dc._position


@pytest.mark.parametrize(
    "changes",
    [
        {"mapper": 1},
        {"mapper": 2},
        {"mapper": 3},
        {"options": 0x80},
        {"options": 0x400},
        {"options": 0x800},
        {"alignment": 0x100},
    ],
)
def test_native_ltr_and_explicit_face_equivalences(changes):
    assert draw(**changes) == draw()
    assert draw(**changes)[1] == (79, 40)
