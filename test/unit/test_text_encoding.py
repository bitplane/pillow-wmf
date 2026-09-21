import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from pillow_wmf import FontCollection, FontFace, RasterContext, SystemFontCollection, UnsupportedOperation
from pillow_wmf.text import FontRun, decode_single_byte, layout_text
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


def test_ansi_request_does_not_force_an_arbitrary_symbol_face():
    face = FontFace.from_path(FONTS / "symbols.ttf")
    fonts = FontCollection([face])
    request = replace(REQUEST, face_name=face.family.encode(), charset=0)
    with pytest.raises(UnsupportedOperation, match="symbol font charset"):
        fonts.decode(request, face, b"AB")


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
def test_unsupported_charset_face_combinations_are_atomic(face, charset):
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


@pytest.mark.parametrize(
    "charset,codepage,bit,text",
    [
        (177, 1255, 5, "שלום"),
        (178, 1256, 6, "العربية"),
        (163, 1258, 8, "a\u0301 ơưđ"),
        (222, 874, 16, "ภาษาไทย"),
        (238, 1250, 1, "Příliš žluťoučký kůň Łódź"),
        (161, 1253, 3, "Καλημέρα κόσμε"),
        (162, 1254, 4, "İstanbul ıİ şŞ ğĞ"),
        (186, 1257, 7, "Ąžuolas Ėė Įį Ųų Ūū"),
    ],
)
def test_charsets_and_explicit_ansi_environment(charset, codepage, bit, text):
    face = FontFace.from_path(FONTS / "encoding.ttf")
    data = text.encode(f"cp{codepage}")
    assert decode_single_byte(data, codepage) == text
    request = replace(REQUEST, charset=charset)
    fonts = FontCollection([face], ansi_codepage=codepage)
    with pytest.raises(UnsupportedOperation, match="advertise"):
        fonts.decode(request, face, data)
    face.codepages |= 1 << bit
    assert fonts.decode(request, face, data) == text
    assert fonts.decode(replace(request, charset=1), face, data) == text
    assert len(fonts.decode(request, face, bytes(range(256)))) == 256
    # ANSI_CHARSET is Windows-1252, not the caller's DEFAULT_CHARSET environment.
    assert fonts.decode(replace(request, charset=0), face, b"\xe9") == "é"
    automatic = SystemFontCollection(paths=[], ansi_codepage=codepage)
    decoded = automatic.decode_run(request, face, data)
    assert decoded.text == text
    assert decoded.byte_lengths == (1,) * len(data)


@pytest.mark.parametrize(
    "codepage,fingerprint",
    [
        (1255, "20a34a57a2c718c285c88f6df762f8c734d5699662de0771e6c9b708bf16e6b9"),
        (1256, "3e8c71d2d46c2b8e003788e0aeeff4a85ad8b4f051cea8c65ac7f628b9d2b556"),
        (1258, "d8f8e7cdd9e3cda7eabe83e52edf96f0645df0c38aca6edc70355ab0563dbae9"),
        (874, "8e89d9194054b6e2a38a5103e6ef0e08f4bca8e85490ba0b8401d2a4db931c57"),
    ],
)
def test_remaining_single_byte_tables_match_native_nls(codepage, fingerprint):
    # MultiByteToWideChar(codepage, 0) for each individual byte, in order.
    decoded = decode_single_byte(bytes(range(256)), codepage)
    assert len(decoded) == 256
    assert hashlib.sha256(decoded.encode("utf-32le")).hexdigest() == fingerprint


def test_hebrew_and_thai_vendor_mappings_are_preserved():
    assert decode_single_byte(b"\xca\xd9\xdf\xfb\xfc\xff", 1255) == "\u05ba\uf88d\uf893\uf894\uf895\uf896"
    assert decode_single_byte(b"\xdb\xde\xfc\xff", 874) == "\uf8c1\uf8c4\uf8c5\uf8c8"


def test_vietnamese_combining_bytes_are_not_normalized():
    assert decode_single_byte(b"a\xec", 1258) == "a\u0301"


def test_european_byte_tables_match_native_windows_nls():
    tables = Path(__file__).with_name("windows_sbcs.txt").read_text().splitlines()
    for line in tables:
        codepage, *codepoints = line.split()
        expected = tuple(int(value, 16) for value in codepoints)
        assert len(expected) == 256
        assert tuple(map(ord, decode_single_byte(bytes(range(256)), int(codepage)))) == expected


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


@pytest.fixture
def control_fonts(face):
    """Distinguish shaping fallback, linked glyphs and default glyphs."""
    primary = face.realize(REQUEST, (1, 1))
    fallback = replace(primary, cmap={32: 1}, missing_glyph="notdef", _glyphs={})
    null_face = replace(primary, cmap={0: 1}, _glyphs={})
    control_face = replace(primary, cmap={1: 3, 0x81: 2, 0x8D: 2}, _glyphs={})
    return FontRun(primary, (fallback, null_face, control_face))


@pytest.mark.parametrize(
    "text,indices",
    [
        ("A\x81B", (2, 0, 3)),  # Shaped C1 is blank, not the linked font's visible glyph.
        ("A\0B", (2, 1, 3)),
        ("A\x81\0B", (2, 2, 1, 3)),
        ("A\0\x81B", (2, 1, 0, 3)),
        ("A\x81\0\x81\x8dB", (2, 2, 1, 0, 0, 3)),
        ("A\x81\x01B\x01\x81A", (2, 2, 3, 3, 3, 0, 2)),
    ],
)
def test_control_run_linking_depends_on_remaining_run_not_adjacent_bytes(control_fonts, text, indices):
    glyphs = control_fonts.shape(text, 10000)
    assert tuple(glyph.index for glyph in glyphs) == indices
    if text == "A\x81B":
        assert (glyphs[1].pixels, glyphs[1].advance) == (b"", 0)
    else:
        for character, glyph in zip(text, glyphs, strict=True):
            if character == "\0":
                assert not any(glyph.pixels)
                assert glyph.advance > 0
            elif character in "\x81\x8d":
                assert glyph.pixels


@pytest.mark.parametrize("separator", "\t\n\r\x1c\x1d\x1e\x1f")
def test_separators_keep_control_fallback_in_its_own_run(control_fonts, separator):
    glyphs = control_fonts.shape("A\x81" + separator + "\0B", 10000)
    assert [(glyph.pixels, glyph.advance) for glyph in glyphs[1:3]] == [(b"", 0), (b"", 0)]
    assert glyphs[3].index == 1


def test_controls_covered_by_primary_do_not_trigger_raw_fallback(control_fonts):
    primary = replace(control_fonts.primary, cmap={0: 1, 0x81: 2}, _glyphs={})
    run = replace(control_fonts, primary=primary)
    null, undefined = run.shape("\0\x81", 10000)
    assert null.index == 1
    assert (undefined.pixels, undefined.advance) == (b"", 0)


def test_raw_control_fallback_does_not_implicitly_enable_notdef(control_fonts):
    strict = replace(control_fonts.fallbacks[0], missing_glyph="error")
    run = replace(control_fonts, fallbacks=(strict, *control_fonts.fallbacks[1:]))
    with pytest.raises(UnsupportedOperation, match="U\\+0081"):
        run.shape("\0\x81", 10000)


def test_explicit_spacing_keeps_one_advance_per_control_byte(control_fonts):
    result = layout_text(
        control_fonts, b"A\x81\0\x81B", 12, 40, 25, (21, 22, 23, 24, 25), opaque=False, max_pixels=10000
    )
    assert result.position == (127, 40)
    assert tuple(x - glyph.bearing[0] for x, _, glyph in result.glyphs) == (12, 33, 55, 78, 102)


def test_linking_skips_zero_advance_candidates_and_retries_default_character(control_fonts):
    primary, fallback, null_face, control_face = control_fonts.primary, *control_fonts.fallbacks
    zero_advance = replace(control_face, design_advances={**control_face.design_advances, 2: 0}, _glyphs={})
    replacement = replace(primary, cmap={0x30FB: 3}, _glyphs={})
    run = FontRun(primary, (fallback, zero_advance, null_face, replacement))
    undefined, null, trailing = run.shape("\x81\0\x81", 10000)
    assert undefined is replacement.glyph("\u30fb", 10000)
    assert null is null_face.glyph("\0", 10000)
    assert trailing is fallback.glyph("\x81", 10000)
    assert zero_advance.glyph("\x81", 10000).advance == 0


def test_primary_zero_advance_glyph_is_not_replaced(control_fonts):
    primary = replace(
        control_fonts.primary,
        design_advances={**control_fonts.primary.design_advances, 2: 0},
        _glyphs={},
    )
    run = replace(control_fonts, primary=primary)
    assert run.shape("A", 10000)[0] is primary.glyph("A", 10000)
    assert run.shape("A", 10000)[0].advance == 0


def test_raw_replacement_tries_base_face_before_links(control_fonts):
    fallback = replace(control_fonts.fallbacks[0], cmap={0x30FB: 3}, _glyphs={})
    run = FontRun(control_fonts.primary, (fallback,))
    assert run.shape("\x81\0", 10000) == (fallback.glyph("\u30fb", 10000),) * 2


def test_del_default_glyph_does_not_force_neighbouring_controls_to_raw_output(control_fonts):
    delete, first, second = control_fonts.shape("\x7f\x81\x8d", 10000)
    assert delete is control_fonts.fallbacks[0].glyph("\x7f", 10000)
    assert [(g.pixels, g.advance) for g in (first, second)] == [(b"", 0), (b"", 0)]


def test_paired_advances_do_not_blank_control_glyphs(control_fonts):
    characters = "\x81\x8d"
    assert all(g.size == (0, 0) for g in control_fonts.shape(characters, 10000))
    raw = control_fonts.shape(characters, 10000, raw=True)
    assert raw == tuple(control_fonts._linked_glyph(c, 10000) for c in characters)
    assert any(g.size != (0, 0) for g in raw)
    layout = layout_text(
        control_fonts, b"\x81\x8d", 0, 30, 24, (9, 11), vertical_advances=(2, 3), opaque=False, max_pixels=10000
    )
    assert tuple(glyph for _, _, glyph in layout.glyphs) == raw
