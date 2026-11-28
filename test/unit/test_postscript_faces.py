"""CFF-outline and variable faces draw through FreeType like TrueType faces."""

from io import BytesIO
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont, newTable

from pillow_wmf import FontCollection, FontFace, RasterContext
from pillow_wmf.wmf.objects import Font

FONTS = Path(__file__).resolve().parents[2] / "test/fonts"


def draw(face, text, *, height=-40, escapement=0, quality=3, weight=400, italic=0):
    dc = RasterContext(160, 120, fonts=FontCollection([face]))
    request = Font(
        height=height,
        escapement=escapement,
        weight=weight,
        italic=italic,
        quality=quality,
        face_name=face.family.encode(),
    )
    dc.select_object(dc.create_font(request))
    dc.text_out(60, 60, text)
    return dc.image.convert("L")


def ink(image):
    return {(x, y) for y in range(image.height) for x in range(image.width) if image.getpixel((x, y)) < 128}


def test_cff_face_metrics_follow_the_font():
    face = FontFace.from_path(FONTS / "cff.otf")
    assert face.family == "Pillow WMF CFF"
    assert face.hinted
    # A's black box: 50..550 along the baseline, 0..700 across it.
    a = face.cmap[ord("A")]
    assert face.ink_spans[a] == (50, 550) and face.ink_heights[a] == (0, 700)


@pytest.mark.parametrize(
    "style",
    [
        {},
        {"quality": 4},
        {"quality": 5},
        {"escapement": 300},
        {"escapement": 900, "weight": 700},
        {"italic": 1},
    ],
)
def test_cff_glyphs_match_the_same_truetype_shapes(style):
    # The CFF A and B repeat the layout font's outlines, so the masks agree but
    # for edge pixels where the two engines round differently.
    cff = ink(draw(FontFace.from_path(FONTS / "cff.otf"), b"AB", **style))
    truetype = ink(draw(FontFace.from_path(FONTS / "layout.ttf"), b"AB", **style))
    assert cff
    assert len(cff ^ truetype) <= 0.05 * len(cff | truetype)


def test_cubic_arcs_draw_under_rotation():
    face = FontFace.from_path(FONTS / "cff.otf")
    upright, rotated = ink(draw(face, b"C")), ink(draw(face, b"C", escapement=450))
    assert rotated and abs(len(rotated) - len(upright)) <= 0.05 * len(upright)


def test_variable_face_draws_its_default_instance():
    with TTFont(FONTS / "layout.ttf") as font:
        font["fvar"] = newTable("fvar")
        font["fvar"].axes, font["fvar"].instances = [], []
        stream = BytesIO()
        font.save(stream)
    variable, static = FontFace(stream.getvalue()), FontFace.from_path(FONTS / "layout.ttf")
    assert draw(variable, b"AB").tobytes() == draw(static, b"AB").tobytes()
