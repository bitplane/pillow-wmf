"""Device metric tables control font cells independently of outline geometry."""

import runpy
from dataclasses import replace
from pathlib import Path

import pytest

from pillow_wmf import FontCollection, FontFace
from pillow_wmf.wmf.objects import Font


@pytest.fixture
def face():
    builder = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/test_font.py"))
    return FontFace(builder["device_font_bytes"]())


@pytest.mark.parametrize(
    "height,em,metrics", [(-16, 16, (15, 4)), (21, 17, (16, 5)), (22, 18, (16, 5)), (29, 24, (23, 6))]
)
def test_device_cells_choose_outline_size_and_line_metrics(face, height, em, metrics):
    raster = face.realize(Font(height=height, quality=3), (1, 1))
    assert raster.font.size.y_ppem == em
    assert (raster.ascent, raster.descent) == metrics


@pytest.mark.parametrize("height", [-19, 15, 30])
def test_missing_device_sizes_retain_linear_scaling(face, height):
    request = Font(height=height, quality=3)
    raster = face.realize(request, (1, 1))
    plain = FontFace((Path(__file__).resolve().parents[1] / "fonts/layout.ttf").read_bytes())
    expected = plain.realize(request, (1, 1))
    assert (raster.ascent, raster.descent) == (expected.ascent, expected.descent)
    assert raster.glyph("A", 1000) == expected.glyph("A", 1000)


def test_device_metrics_use_device_aspect_not_requested_glyph_width(face):
    request = Font(height=-24, quality=3)
    natural = face.realize(request, (1, 1))
    stretched = face.realize(replace(request, width=15), (1, 1))
    assert (natural.ascent, natural.descent) == (stretched.ascent, stretched.descent) == (23, 6)
    assert natural.glyph("A", 1000).advance != stretched.glyph("A", 1000).advance


@pytest.mark.parametrize("height,scale", [(-18, (1, 1)), (-9, (2, 2))])
def test_control_fallback_preserves_cell_then_links_at_replacement_em(face, height, scale):
    root = Path(__file__).resolve().parents[1] / "fonts"
    base = FontFace.from_path(root / "layout.ttf")
    link = FontFace.from_path(root / "encoding.ttf")
    fonts = FontCollection([base, face, link], fallbacks={base.family: (face.family, link.family)})
    run = fonts.realize(Font(height=height, quality=3), base, scale)
    assert run.primary.font.size.y_ppem == 18
    assert run.fallbacks[0].font.size.y_ppem == 18
    assert run.control_fallback.primary.font.size.y_ppem == 17
    assert run.control_fallback.fallbacks[0].font.size.y_ppem == 17
    assert (run.ascent, run.descent) == (16, 5)


def test_cell_fitting_scales_both_axes_and_linking_preserves_em_aspect(face):
    root = Path(__file__).resolve().parents[1] / "fonts"
    base = FontFace.from_path(root / "layout.ttf")
    link = FontFace.from_path(root / "encoding.ttf")
    fonts = FontCollection([base, face, link], fallbacks={base.family: (face.family, link.family)})
    request = Font(height=-18, width=10, quality=3)
    run = fonts.realize(request, base, (1, 1))
    raw = run.control_fallback.primary
    linear_em = 21 * face.units_per_em / (face.ascent + face.descent)
    expected_width = 10 * face.units_per_em / face.average_width * 17 / linear_em
    assert raw.em_width == pytest.approx(expected_width)
    assert run.control_fallback.fallbacks[0].em_width == raw.em_width
