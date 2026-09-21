"""Outline font-matching hints share the default smoothing policy."""

from dataclasses import replace
from pathlib import Path

import pytest

from pillow_wmf import FontCollection, FontFace, RasterContext, UnsupportedOperation
from pillow_wmf.wmf.objects import Font

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("height,width,angle", [(-11, 0, 0), (24, 0, 0), (-24, 15, -27)])
def test_outline_default_draft_and_proof_share_layout(face, height, width, angle):
    layouts = []
    for quality in (0, 1, 2):
        dc = RasterContext(80, 40, fonts=FontCollection([face]))
        request = Font(height=height, width=width, escapement=angle, quality=quality, face_name=face.family.encode())
        dc.select_object(dc.create_font(request))
        dc.set_text_alignment(25)
        dc.move_to(4, 24)
        layout, _ = dc._prepare_text(dict(x=0, y=0, text=b"AB", advances=(20, 20)))
        assert dc._text_state.font.quality == quality
        layouts.append(layout)
    assert layouts[0] == layouts[1] == layouts[2]


def test_outline_quality_retains_request_and_explicit_monochrome():
    face = FontFace.from_path(ROOT / "test/fonts/layout.ttf")
    request = Font(height=-24, quality=0)
    masks = []
    for quality in range(4):
        realized = face.realize(replace(request, quality=quality), (1, 1))
        assert realized.quality == quality
        glyph = realized.glyph("A", 10000)
        assert glyph.channels == (1 if quality == 3 else 3)
        masks.append(glyph)
    assert masks[0] == masks[1] == masks[2]


def test_outline_default_draft_and_proof_compose_identically(face):
    images = []
    for quality in (0, 1, 2):
        dc = RasterContext(24, 24, fonts=FontCollection([face]))
        dc.select_object(dc.create_font(Font(height=-16, quality=quality, face_name=face.family.encode())))
        dc.text_out(2, 2, b"A")
        images.append(dc.image.tobytes())
    assert images[0] == images[1] == images[2]


@pytest.mark.parametrize("quality", [7, 255])
def test_unsupported_smoothing_modes_are_not_treated_as_default(quality):
    face = FontFace.from_path(ROOT / "test/fonts/layout.ttf")
    with pytest.raises(UnsupportedOperation, match="quality"):
        face.at_size(24, quality=quality)


def test_explicit_grayscale_and_cleartype_masks():
    face = FontFace.from_path(ROOT / "test/fonts/layout.ttf")
    gray = face.at_size(24, quality=4).glyph("A", 10000)
    assert gray.channels == 1
    assert any(0 < coverage < 255 for coverage in gray.pixels)
    default = face.at_size(24, quality=0).glyph("A", 10000)
    assert face.at_size(24, quality=5).glyph("A", 10000) == default
    assert face.at_size(24, quality=6).glyph("A", 10000) == default


def test_grayscale_coverage_is_composited_not_thresholded():
    face = FontFace.from_path(ROOT / "test/fonts/layout.ttf")
    dc = RasterContext(80, 60, fonts=FontCollection([face]))
    dc.select_object(dc.create_font(Font(height=-24, quality=4, face_name=face.family.encode())))
    dc.set_background_mode(1)
    dc.text_out(10, 10, b"A")
    pixels = set(dc.image.get_flattened_data())
    assert any(0 < r < 255 and r == g == b for r, g, b in pixels)
