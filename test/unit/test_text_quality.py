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


@pytest.mark.parametrize("quality", [4, 5, 6, 255])
def test_unsupported_smoothing_modes_are_not_treated_as_default(quality):
    face = FontFace.from_path(ROOT / "test/fonts/layout.ttf")
    with pytest.raises(UnsupportedOperation, match="quality"):
        face.at_size(24, quality=quality)
