"""Outline font-matching hints share the default smoothing policy."""

import runpy
from dataclasses import replace
from pathlib import Path

import pytest

from pillow_wmf import FontCollection, FontFace, Metafile, RasterContext, UnsupportedOperation, play
from pillow_wmf.wmf.objects import Font

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("profile", ["small", "cell", "scaled-angle"])
def test_outline_default_draft_and_proof_share_pixels_and_layout(profile):
    cases = runpy.run_path(str(ROOT / "scripts/text_quality_cases.py"))["cases"]
    face = FontFace.from_path(ROOT / "test/fonts/layout.ttf")
    images = []
    for name, family, recorder in cases():
        if family != face.family or not name.endswith(tuple(f"{profile}-{q}" for q in (0, 1, 2))):
            continue
        source = recorder.to_bytes()
        metafile = Metafile.from_bytes(source)
        assert metafile.to_bytes() == source
        dc = RasterContext(320, 100, fonts=FontCollection([face]))
        play(metafile, dc, strict=True)
        quality = int(name[-1])
        assert dc._text_state.font.quality == quality
        images.append((dc.image.tobytes(), dc._position))
    assert len(images) == 3
    assert images[0] == images[1] == images[2]


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
