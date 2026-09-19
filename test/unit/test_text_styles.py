"""Native-controlled glyph geometry, state and explicit style selection."""

from dataclasses import replace
from pathlib import Path
import runpy

import pytest

from pillow_wmf import FontCollection, FontFace, RasterContext, UnsupportedOperation
from pillow_wmf.wmf.objects import Font

REQUEST = Font(height=-24, weight=400, quality=3, face_name=b"Pillow WMF Test")


@pytest.fixture
def face():
    return FontFace.from_path(Path(__file__).resolve().parents[1] / "fonts/layout.ttf")


@pytest.mark.parametrize("bold,italic", [(True, False), (False, True), (True, True)])
def test_synthetic_glyph_matches_native_controlled_rows(face, bold, italic):
    request = replace(REQUEST, weight=700 if bold else 400, italic=int(italic))
    with pytest.raises(UnsupportedOperation, match="unavailable"):
        FontCollection([face]).resolve(request)
    fonts = FontCollection([face], synthesize_styles=True)
    glyph = fonts.realize(request, fonts.resolve(request), (1, 1)).glyph("A", 10000)
    # Windows monochrome scanlines for the original L-shaped test glyph.
    lefts = (7, 6, 6, 6, 5, 5, 5, 4, 4, 4, 3, 3, 3, 2, 2, 2, 1) if italic else (1,) * 17
    expected = {
        (x, y)
        for y, left in zip(range(-17, 0), lefts, strict=True)
        for x in range(left, left + (5 if y < -5 else 12) + bold)
    }
    actual = {
        (x + glyph.bearing[0], y + glyph.bearing[1])
        for y in range(glyph.size[1])
        for x in range(glyph.size[0])
        if glyph.pixels[y * glyph.size[0] + x]
    }
    assert actual == expected
    assert glyph.advance == 14 + bold


def test_style_and_rotation_caches_do_not_mutate_regular_glyphs(face):
    regular = face.realize(REQUEST, (1, 1))
    before = regular.glyph("A", 10000)
    for change in ({"italic": 1}, {"weight": 700}, {"escapement": 900}):
        other = face.realize(replace(REQUEST, **change), (1, 1))
        assert other is not regular
        assert other.glyph("A", 10000) != before
        with pytest.raises(ValueError, match="pixel limit"):
            other.glyph("A", 1)
    assert regular.glyph("A", 10000) == before


def test_compatible_orientation_alone_does_not_rotate_text(face):
    images = []
    for orientation in (0, 900):
        dc = RasterContext(100, 100, fonts=FontCollection([face]))
        dc.select_object(dc.create_font(replace(REQUEST, orientation=orientation)))
        dc.text_out(10, 30, b"AB")
        images.append(dc.image.tobytes())
    assert images[0] == images[1]


@pytest.mark.parametrize("scale,expected", [((-1, 1), (-71, 0)), ((1, -1), (71, 0)), ((-1, -1), (-71, 0))])
def test_reflection_keeps_glyphs_upright_and_updates_logical_position(face, scale, expected):
    dc = RasterContext(200, 100, fonts=FontCollection([face]))
    dc.set_window_extent(200, 100)
    dc.set_viewport_extent(200 * scale[0], 100 * scale[1])
    dc.set_viewport_origin(50, 50)
    dc.set_background_mode(1)
    dc.set_text_alignment(25)
    dc.select_object(dc.create_font(REQUEST))
    dc.move_to(0, 0)
    dc.text_out(0, 0, b"A B A B")
    assert dc._position == expected
    assert dc.image.getpixel((51, 34)) == (0, 0, 0)
    assert dc.image.getpixel((49, 34)) == (255, 255, 255)


@pytest.mark.parametrize("angle,expected", [(900, (0, -71)), (300, (62, -36)), (-300, (62, 36))])
def test_rotated_current_position_matches_native_controlled_run(face, angle, expected):
    dc = RasterContext(200, 200, fonts=FontCollection([face]))
    dc.set_window_extent(200, 200)
    dc.set_viewport_extent(200, 200)
    dc.set_viewport_origin(50, 100)
    dc.set_background_mode(1)
    dc.set_text_alignment(25)
    dc.select_object(dc.create_font(replace(REQUEST, escapement=angle)))
    dc.move_to(0, 0)
    dc.text_out(0, 0, b"A B A B")
    assert dc._position == expected


@pytest.mark.parametrize("decoration", ["underline", "strikeout"])
def test_zero_font_decoration_metrics_still_produce_one_pixel_rule(face, decoration):
    fonts = FontCollection([face])
    dc = RasterContext(120, 70, fonts=fonts)
    dc.set_window_extent(120, 70)
    dc.set_viewport_extent(120, 70)
    dc.set_background_mode(1)
    dc.set_text_alignment(25)
    dc.select_object(dc.create_font(replace(REQUEST, **{decoration: 1})))
    dc.move_to(10, 40)
    dc.text_out(0, 0, b"A B A B")
    assert dc._position == (81, 40)
    assert all(dc.image.getpixel((x, 40)) == (0, 0, 0) for x in range(10, 81))
    assert dc.image.getpixel((81, 40)) == (255, 255, 255)


@pytest.mark.parametrize("decoration", ["underline", "strikeout"])
def test_zero_thickness_rotated_decoration_does_not_add_ink(face, decoration):
    images = []
    for enabled in (False, True):
        dc = RasterContext(160, 128, fonts=FontCollection([face]))
        dc.set_window_extent(160, 128)
        dc.set_viewport_extent(160, 128)
        dc.set_background_mode(1)
        dc.set_text_alignment(24)
        request = replace(REQUEST, escapement=300, **{decoration: int(enabled)})
        dc.select_object(dc.create_font(request))
        dc.text_out(30, 80, b"A B A B")
        images.append(dc.image.tobytes())
    assert images[0] == images[1]


@pytest.mark.parametrize("thickness", [0, 1, 50])
@pytest.mark.parametrize("angle,reflection", [(0, 1), (300, 1), (900, 1), (0, -1)])
def test_native_decoration_thickness_depends_on_rule_direction(thickness, angle, reflection):
    cases = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/text_decoration_cases.py"))
    face = FontFace(cases["font_bytes"](thickness))
    images = []
    for enabled in (False, True):
        dc = RasterContext(160, 128, fonts=FontCollection([face]))
        dc.set_window_extent(160, 128)
        dc.set_viewport_extent(160 * reflection, 128)
        dc.set_viewport_origin(80, 80)
        dc.set_background_mode(1)
        dc.set_text_alignment(24)
        request = replace(
            REQUEST,
            face_name=face.family.encode(),
            escapement=angle,
            underline=int(enabled),
            strikeout=int(enabled),
        )
        dc.select_object(dc.create_font(request))
        dc.text_out(0, 0, b"A B")
        images.append(dc.image.tobytes())
    assert (images[0] != images[1]) == (angle % 900 == 0 or thickness == 50)
