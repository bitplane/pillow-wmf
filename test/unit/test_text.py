"""Test font identity, GDI layout and DC effects separately from glyph pixels."""

from dataclasses import replace
from pathlib import Path

import pytest
from PIL import ImageFont

from pillow_wmf import FontCollection, FontFace, RasterContext, UnsupportedOperation
from pillow_wmf.text import Glyph, layout_text
from pillow_wmf.wmf.objects import Font

FONT_PATH = Path(__file__).resolve().parents[2] / "test/fonts/layout.ttf"
REQUEST = Font(height=-20, weight=400, quality=3, face_name=b"Pillow WMF Test".ljust(32, b"\0"))


@pytest.fixture(scope="module")
def face():
    return FontFace.from_path(FONT_PATH)


@pytest.fixture
def dc(face):
    context = RasterContext(80, 60, fonts=FontCollection([face]))
    context.select_object(context.create_font(REQUEST))
    return context


def test_resolution_is_explicit_and_case_insensitive(face):
    fonts = FontCollection([face])
    assert fonts.resolve(replace(REQUEST, face_name=b"pillow wmf TEST", weight=0)) is face
    with pytest.raises(UnsupportedOperation, match="unavailable"):
        fonts.resolve(replace(REQUEST, face_name=b"Arial"))
    with pytest.raises(UnsupportedOperation, match="unavailable"):
        fonts.resolve(replace(REQUEST, weight=700))
    with pytest.raises(UnsupportedOperation, match="Default font"):
        fonts.resolve(None)
    with pytest.raises(ValueError, match="Ambiguous"):
        FontCollection([face, FontFace.from_path(FONT_PATH)])


def test_windows_metrics_are_not_freetype_line_metrics(face):
    font = face.at_size(20)
    assert (font.ascent, font.descent) == (18, 6)
    assert ImageFont.truetype(FONT_PATH, 20).getmetrics() == (16, 4)
    assert [font.glyph(c, 1000).advance for c in "A B"] == [12, 6, 9]
    assert [font.glyph(c, 1000).index for c in "A B"] == [2, 1, 3]


class MetricFont:
    ascent, descent = 9, 3

    def glyph(self, character, max_pixels):
        return Glyph((1, 1), (-1, -7), b"\xff", 5)


@pytest.mark.parametrize("horizontal,origin_x", [(0, 30), (2, 11), (6, 20)])
@pytest.mark.parametrize("vertical,baseline", [(0, 39), (8, 27), (24, 30)])
def test_alignment_and_explicit_advances_use_metrics_not_ink_bounds(horizontal, origin_x, vertical, baseline):
    result = layout_text(MetricFont(), b"A B", 30, 30, horizontal | vertical, (9, 3, 7), opaque=True, max_pixels=10)
    assert [(x, y) for x, y, _ in result.glyphs] == [(origin_x + n - 1, baseline - 7) for n in (0, 9, 12)]
    assert result.background == (origin_x, baseline - 9, origin_x + 19, baseline + 3)
    assert result.position is None


def test_current_position_is_logical_and_saved_independently_of_glyph_cache(dc):
    dc.set_viewport_origin(4, 7)
    dc.set_text_alignment(25)
    dc.move_to(8, 25)
    dc.save_dc()
    dc.ext_text_out(999, 999, b"AB", advances=(17, 9))
    assert dc._position == (34, 25)
    dc.restore_dc(-1)
    assert dc._position == (8, 25)


@pytest.mark.parametrize(
    "changes", [{"quality": 0}, {"charset": 2}, {"height": 20}, {"width": 10}, {"escapement": 900}]
)
def test_unimplemented_realization_fails_before_painting_or_committing(dc, changes):
    dc.select_object(dc.create_font(replace(REQUEST, **changes)))
    image, calls = dc.image.tobytes(), list(dc.calls)
    with pytest.raises(UnsupportedOperation):
        dc.ext_text_out(10, 20, b"A", options=2, rectangle=(0, 0, 50, 50))
    assert dc.image.tobytes() == image
    assert dc.calls == calls


@pytest.mark.parametrize("text", [b"\x80", b"\0", b"\t", b"C"])
def test_unsupported_encoding_and_missing_glyph_do_not_silently_replace(dc, text):
    before = dc.image.tobytes(), list(dc.calls)
    with pytest.raises(UnsupportedOperation):
        dc.text_out(10, 20, text)
    assert (dc.image.tobytes(), dc.calls) == before


@pytest.mark.parametrize("cached", [False, True])
def test_glyph_budget_applies_before_rendering_and_to_cached_masks(cached):
    face = FontFace.from_path(FONT_PATH)
    if cached:
        face.at_size(20).glyph("A", 1000)
    dc = RasterContext(80, 60, fonts=FontCollection([face]), max_bitmap_pixels=1)
    dc.select_object(dc.create_font(REQUEST))
    before = list(dc.calls)
    with pytest.raises(ValueError, match="Glyph pixel limit"):
        dc.text_out(0, 20, b"A")
    assert dc.calls == before


def test_empty_opaque_call_needs_no_font_and_respects_dc_clip():
    dc = RasterContext(8, 8)
    dc.set_rop2(1)  # Text backgrounds are copies, not ROP2 foreground marks.
    dc.set_background_color(0x00FF00)
    dc.intersect_clip_rect(2, 2, 6, 6)
    dc.ext_text_out(0, 0, b"", options=2, rectangle=(0, 0, 4, 4))
    assert dc.image.getpixel((2, 2)) == (0, 255, 0)
    assert dc.image.getpixel((1, 2)) == (255, 255, 255)
    assert dc.image.getpixel((4, 2)) == (255, 255, 255)


def test_bad_advance_array_is_atomic(dc):
    before = list(dc.calls)
    with pytest.raises(ValueError, match="advance count"):
        dc.ext_text_out(10, 20, b"AB", advances=(10,))
    assert dc.calls == before
