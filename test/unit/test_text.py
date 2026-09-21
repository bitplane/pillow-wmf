"""Test font identity, GDI layout and DC effects separately from glyph pixels."""

from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest
from PIL import ImageFont

from pillow_wmf import FontCollection, FontFace, RasterContext, UnsupportedOperation
from pillow_wmf.text import Glyph, layout_text
from pillow_wmf.wmf.objects import Font

FONT_PATH = Path(__file__).resolve().parents[2] / "test/fonts/layout.ttf"
REQUEST = Font(height=-20, weight=400, quality=3, face_name=b"Pillow WMF Test".ljust(32, b"\0"))


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
    break_character = 32
    decorations = ()

    def shape(self, characters, max_pixels, *, raw=False):
        return tuple(self.glyph(character, max_pixels) for character in characters)

    ascent, descent = 9, 3

    def glyph(self, character, max_pixels):
        return Glyph((1, 1), (-1, -7), b"\xff", 5)


@pytest.mark.parametrize("horizontal,origin_x", [(0, 30), (2, 11), (6, 20)])
@pytest.mark.parametrize("vertical,baseline", [(0, 39), (8, 27), (24, 30)])
def test_alignment_and_explicit_advances_use_metrics_not_ink_bounds(horizontal, origin_x, vertical, baseline):
    result = layout_text(MetricFont(), b"A B", 30, 30, horizontal | vertical, (9, 3, 7), opaque=True, max_pixels=10)
    assert [(x, y) for x, y, _ in result.glyphs] == [(origin_x + n - 1, baseline - 7) for n in (0, 9, 12)]
    assert result.background == (
        (origin_x, baseline - 9),
        (origin_x + 19, baseline - 9),
        (origin_x + 19, baseline + 3),
        (origin_x, baseline + 3),
    )
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


@pytest.mark.parametrize("changes", [{"quality": 255}, {"charset": 2}])
def test_unimplemented_realization_fails_before_painting_or_committing(dc, changes):
    dc.select_object(dc.create_font(replace(REQUEST, **changes)))
    image, calls = dc.image.tobytes(), list(dc.calls)
    with pytest.raises(UnsupportedOperation):
        dc.ext_text_out(10, 20, b"A", options=2, rectangle=(0, 0, 50, 50))
    assert dc.image.tobytes() == image
    assert dc.calls == calls


@pytest.mark.parametrize("text", [b"\x80", b"\0", b"C"])
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


@pytest.mark.parametrize(
    "height,width,scale,metrics,advances",
    [
        (20, 0, (1, 1), (15, 5), (10, 5, 7)),
        (21, 0, (1, 1), (16, 5), (11, 5, 8)),
        (0, 0, (1, 1), (14, 5), (10, 5, 7)),
        (-20, 7, (1, 1), (18, 6), (9, 5, 7)),
        (-20, 12, (1, 1), (18, 6), (16, 8, 12)),
        (-20, 0, (2, 1), (18, 6), (12, 6, 9)),
        (-20, 0, (1, 2), (36, 12), (24, 12, 18)),
        (-20, 0, (Fraction(3, 2), Fraction(3, 2)), (27, 9), (18, 9, 13)),
        (-20, 7, (Fraction(3, 2), Fraction(2, 3)), (12, 4), (14, 7, 10)),
    ],
)
def test_realization_matches_native_metrics_and_device_advances(face, height, width, scale, metrics, advances):
    font = face.realize(replace(REQUEST, height=height, width=width), scale)
    assert (font.ascent, font.descent) == metrics
    assert tuple(font.glyph(c, 10000).advance for c in "A B") == advances


@pytest.mark.parametrize("alignment,position", [(25, (70, 30)), (27, (50, 30)), (31, None)])
def test_current_position_alignment_uses_run_width(alignment, position):
    result = layout_text(MetricFont(), b"AB", 60, 30, alignment, (), opaque=False, max_pixels=100)
    assert result.position == position


def test_explicit_signed_advances_override_justification_but_keep_character_extra():
    result = layout_text(
        MetricFont(),
        b"A B",
        20,
        30,
        25,
        (9, 0, -7),
        opaque=False,
        max_pixels=100,
        extra=2,
        justification=(1, 100),
        scale=Fraction(3, 2),
    )
    assert [x for x, _, _ in result.glyphs] == [19, 36, 39]
    assert result.position == (32, 30)


@pytest.mark.parametrize(
    "text,scale,justification,last_x", [(b"A B", 1, (2, 9), 13), (b"AB B", 1, (2, 9), 19), (b"AB", 2, (0, 0), 5)]
)
def test_device_advance_ties_round_even_before_logical_conversion(text, scale, justification, last_x):
    result = layout_text(
        MetricFont(), text, 0, 30, 24, (), opaque=False, max_pixels=100, scale=scale, justification=justification
    )
    assert result.glyphs[-1][0] == last_x


def test_default_quality_is_rgb_coverage_with_independent_cache(face):
    mono = face.realize(REQUEST, (1, 1)).glyph("A", 10000)
    rgb = face.realize(replace(REQUEST, quality=0), (1, 1)).glyph("A", 10000)
    assert mono.channels == 1
    assert rgb.channels == 3
    assert len(rgb.pixels) == rgb.size[0] * rgb.size[1] * 3
    assert any(value not in (0, 255) for value in rgb.pixels)


def test_rgb_text_keeps_dc_clip_and_ignores_rop2(face):
    dc = RasterContext(40, 40, fonts=FontCollection([face]))
    dc.select_object(dc.create_font(replace(REQUEST, quality=0)))
    dc.set_background_mode(1)
    dc.set_rop2(1)
    dc.set_text_color(0xFFFFFF)
    dc.text_out(5, 5, b"A")
    assert set(dc.image.get_flattened_data()) == {(255, 255, 255)}
    dc.set_text_color(0)
    dc.intersect_clip_rect(10, 10, 15, 20)
    dc.text_out(5, 5, b"A")
    changed = [(x, y) for y in range(40) for x in range(40) if dc.image.getpixel((x, y)) != (255, 255, 255)]
    assert changed
    assert all(10 <= x < 15 and 10 <= y < 20 for x, y in changed)
