from dataclasses import replace
from pathlib import Path

import pytest

from pillow_wmf import FontCollection, FontFace, RasterContext, UnsupportedOperation
from pillow_wmf.text import decode_single_byte, layout_text
from pillow_wmf.wmf.objects import Font

FONTS = Path(__file__).resolve().parents[2] / "test/fonts"
REQUEST = Font(height=-24, weight=400, quality=3, face_name=b"Pillow WMF Encoding")


@pytest.fixture(scope="module")
def face():
    return FontFace.from_path(FONTS / "encoding.ttf")


@pytest.mark.parametrize(
    "charset,characters,indices", [(0, "\u00e9\u20ac\u00c6", (2, 3, 3)), (204, "\u0439\u0402\u0416", (3, 2, 2))]
)
def test_identical_bytes_select_different_codepage_glyphs(face, charset, characters, indices):
    fonts = FontCollection([face])
    request = replace(REQUEST, charset=charset)
    assert fonts.decode(request, face, b"\xe9\x80\xc6") == characters
    raster = face.realize(request, (1, 1))
    assert tuple(raster.glyph(c, 10000).index for c in characters) == indices


def test_default_charset_and_face_names_use_explicit_ansi_environment(face):
    fonts = FontCollection([face], ansi_codepage=1251, aliases={"\u0424\u043e\u043d\u0442": face.family})
    request = replace(REQUEST, face_name="\u0424\u043e\u043d\u0442".encode("cp1251"), charset=1)
    assert fonts.resolve(request) is face
    assert fonts.decode(request, face, b"\xe9") == "\u0439"
    assert fonts.decode(replace(request, charset=0), face, b"\xe9") == "\u00e9"
    with pytest.raises(UnsupportedOperation, match="unavailable"):
        FontCollection([face]).resolve(request)


@pytest.mark.parametrize("codepage,undefined", [(1252, b"\x81\x8d\x8f\x90\x9d"), (1251, b"\x98")])
def test_undefined_bytes_are_not_replaced_or_dropped(codepage, undefined):
    assert tuple(map(ord, decode_single_byte(undefined, codepage))) == tuple(undefined)
    assert len(decode_single_byte(bytes(range(256)), codepage)) == 256


@pytest.mark.parametrize("charset", [1, 2])
def test_symbol_mapping_uses_font_cmap_not_a_unicode_icon_table(charset):
    face = FontFace.from_path(FONTS / "symbols.ttf")
    fonts = FontCollection([face])
    request = replace(REQUEST, face_name=face.family.encode(), charset=charset)
    characters = fonts.decode(request, face, b"AB \x80\xe9\xff")
    assert tuple(map(ord, characters)) == (0xF041, 0xF042, 0xF020, 0xF080, 0xF0E9, 0xF0FF)
    raster = face.realize(request, (1, 1))
    assert tuple(raster.glyph(c, 10000).index for c in characters) == (2, 3, 1, 2, 3, 2)


def test_missing_glyph_policy_is_explicit_and_cache_isolation_is_preserved(face):
    strict = face.realize(REQUEST, (1, 1))
    permissive = face.realize(REQUEST, (1, 1), missing_glyph="notdef")
    assert permissive.glyph("C", 10000).index == 0
    assert permissive.glyph("C", 10000).advance == 12
    with pytest.raises(UnsupportedOperation, match="Missing glyph"):
        strict.glyph("C", 10000)
    fonts = FontCollection([face], missing_glyph="notdef")
    assert fonts.decode(REQUEST, face, b"A\0B\t") == "A\0B\t"


def test_single_byte_explicit_advances_remain_byte_indexed(face):
    fonts = FontCollection([face])
    data = b"\xe9\x80\xc6"
    characters = fonts.decode(REQUEST, face, data)
    raster = face.realize(REQUEST, (1, 1))
    layout = layout_text(raster, data, 12, 40, 25, (21, 22, 23), opaque=False, max_pixels=10000, characters=characters)
    assert layout.position == (78, 40)
    assert tuple(x - glyph.bearing[0] for x, _, glyph in layout.glyphs) == (12, 33, 55)


@pytest.mark.parametrize("charset", [2, 128, 255])
def test_unimplemented_charsets_are_atomic(face, charset):
    dc = RasterContext(100, 100, fonts=FontCollection([face]))
    dc.select_object(dc.create_font(replace(REQUEST, charset=charset)))
    before = dc.image.tobytes(), list(dc.calls)
    with pytest.raises(UnsupportedOperation, match="charset"):
        dc.ext_text_out(10, 40, b"A", options=2, rectangle=(0, 0, 50, 50))
    assert (dc.image.tobytes(), dc.calls) == before


def test_missing_face_is_not_replaced_without_a_caller_alias(face):
    request = replace(REQUEST, face_name=b"Unavailable Commercial Font")
    with pytest.raises(UnsupportedOperation, match="unavailable"):
        FontCollection([face]).resolve(request)
    assert FontCollection([face], aliases={"Unavailable Commercial Font": face.family}).resolve(request) is face


def test_invalid_environment_or_policy_is_rejected():
    with pytest.raises(ValueError, match="ANSI"):
        FontCollection(ansi_codepage=65001)
    with pytest.raises(ValueError, match="Missing-glyph"):
        FontCollection(missing_glyph="ignore")


def test_fallback_fills_only_missing_glyphs_and_preserves_base_metrics(face):
    base = FontFace.from_path(FONTS / "layout.ttf")
    request = replace(REQUEST, face_name=base.family.encode())
    fonts = FontCollection([base, face], fallbacks={base.family: (face.family,)})
    run = fonts.realize(request, base, (1, 1))
    assert run.glyph("A", 10000) is run.primary.glyph("A", 10000)
    assert run.glyph("\xe9", 10000) is face.realize(request, (1, 1)).glyph("\xe9", 10000)
    assert (run.ascent, run.descent, run.break_character) == (22, 7, 32)
    with pytest.raises(UnsupportedOperation, match="Missing glyph"):
        FontCollection([base, face]).realize(request, base, (1, 1)).glyph("\xe9", 10000)
    with pytest.raises(ValueError, match="pixel limit"):
        run.glyph("\xe9", 1)


def test_missing_fallback_face_fails_without_painting(face):
    fonts = FontCollection([face], fallbacks={face.family: ("Unavailable",)})
    dc = RasterContext(100, 100, fonts=fonts)
    dc.select_object(dc.create_font(REQUEST))
    before = dc.image.tobytes(), list(dc.calls)
    with pytest.raises(UnsupportedOperation, match="Fallback font unavailable"):
        dc.ext_text_out(10, 40, b"ACB", options=2, rectangle=(0, 0, 50, 50))
    assert (dc.image.tobytes(), dc.calls) == before


@pytest.mark.parametrize("control", [b"\t", b"\n", b"\r"])
@pytest.mark.parametrize("advances,expected", [((), (37, 40)), ((21, 22, 23), (78, 40))])
def test_line_controls_are_blank_without_discarding_explicit_byte_advances(face, control, advances, expected):
    fonts = FontCollection([face])
    run = fonts.realize(REQUEST, face, (1, 1))
    result = layout_text(run, b"A" + control + b"B", 12, 40, 25, advances, opaque=False, max_pixels=10000)
    assert result.glyphs[1][2].pixels == b""
    assert result.position == expected
