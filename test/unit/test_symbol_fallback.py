"""Legacy Symbol mapping stays in the face, not an approximate Unicode alias."""

import hashlib
from dataclasses import replace
from importlib.resources import files
from io import BytesIO

import pytest
from fontTools.ttLib import TTFont

from pillow_wmf import Font, FontCollection, FontFace, Recorder, SystemFontCollection, UnsupportedOperation, render


@pytest.fixture(scope="module")
def symbol():
    return FontFace.bundled_symbol()


def test_upstream_font_source_and_licence_are_packaged(symbol):
    root = files("pillow_wmf").joinpath("fonts", "symbol")
    assert hashlib.sha256(symbol.data).hexdigest() == "d79da0fbd9a9f3cf806059bb1f2c9d7ce43dd9e3e4c7d4dcc5d9f2759b81196f"
    assert "SplineFontDB:" in root.joinpath("symbol.sfd").read_text()
    assert "Generate" in root.joinpath("genttf.ff").read_text()
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in root.joinpath("COPYING.LIB").read_text()
    assert symbol.family == "Symbol" and symbol.symbol


def test_repertoire_matches_native_defined_slots_not_postscript_extensions(symbol):
    expected = {*range(32, 127), *range(161, 240), *range(241, 255)}
    assert {c - 0xF000 for c in symbol.cmap} == expected
    assert len(symbol.cmap) == 188
    font = symbol.realize(Font(height=-24), (1, 1), missing_glyph="notdef")
    for byte in (0, 127, 128, 160, 240, 255):
        assert font.glyph(chr(0xF000 | byte), 10000).index == 0


@pytest.mark.parametrize("charset", (0, 1, 2, 204, 255))
def test_symbol_byte_positions_identify_greek_and_equation_pieces(symbol, charset):
    fonts = FontCollection([symbol])
    request = Font(face_name=b"Symbol", charset=charset)
    characters = fonts.decode(request, symbol, b"AaWw\xe6\xe7\xe8\xf2")
    with TTFont(BytesIO(symbol.data)) as table:
        names = [table.getGlyphName(symbol.cmap[ord(c)]) for c in characters]
    assert names == ["Alpha", "alpha", "Omega", "omega", "parenlefttp", "parenleftex", "parenleftbt", "integral"]
    assert len(fonts.decode(request, symbol, bytes(range(256)))) == 256


def test_fallback_is_opt_in_for_explicit_collection_and_automatic_for_system():
    request = Font(face_name=b"Symbol", charset=2)
    with pytest.raises(UnsupportedOperation, match="unavailable"):
        FontCollection().resolve(request)
    assert FontCollection(symbol_fallback=True).resolve(request).symbol
    fonts = SystemFontCollection(paths=[])
    for weight, italic in ((400, 0), (700, 0), (400, 1)):
        face = fonts.resolve(replace(request, weight=weight, italic=italic))
        assert face.symbol
    assert fonts.substitutions[0].reason == "bundled symbol font"


def test_supplied_face_precedes_bundled_fallback(symbol):
    assert FontCollection([symbol], symbol_fallback=True).resolve(Font(face_name=b"Symbol")) is symbol


def test_bundled_font_cannot_claim_native_glyph_number_compatibility():
    fonts = SystemFontCollection(paths=[])
    request = Font(face_name=b"Symbol", charset=2)
    face = fonts.resolve(request)
    with pytest.raises(UnsupportedOperation, match="Glyph-index"):
        fonts.layout_font(request, face, (1, 1))


def test_explicit_collection_does_not_alias_other_specialist_fonts():
    fonts = FontCollection(symbol_fallback=True)
    for name in (b"MT Symbol", b"MT Extra", b"ZapfDingbats"):
        with pytest.raises(UnsupportedOperation):
            fonts.resolve(Font(face_name=name, charset=2))


@pytest.mark.parametrize("name", (b"????????", b"Missing Symbol Family", b"", b"MT Extra"))
@pytest.mark.parametrize("pitch,family", ((0, "Pillow WMF Wingdings Fallback"), (18, "Symbol")))
def test_missing_symbol_family_uses_family_hint_and_reports_substitution(name, pitch, family):
    fonts = SystemFontCollection(paths=[])
    request = Font(face_name=name, charset=2, pitch_and_family=pitch)
    face = fonts.resolve(request)
    assert face.family == family
    text = fonts.decode(request, face, b"\xc5")
    assert text == ("\uf0c5" if pitch == 18 else "\u2bb2")
    assert fonts.substitutions[-1].requested == name.decode()
    assert fonts.substitutions[-1].reason == "symbol charset fallback"
    with pytest.raises(UnsupportedOperation, match="Glyph-index"):
        fonts.layout_font(request, face, (1, 1))


def test_missing_roman_symbol_renders_like_an_explicit_symbol_request():
    images = []
    for name in (b"????????", b"Symbol"):
        recorder = Recorder()
        recorder.set_background_mode(1)
        recorder.select_object(
            recorder.create_font(
                Font(
                    face_name=name.ljust(32, b"\0"),
                    charset=2,
                    pitch_and_family=18,
                    height=-48,
                )
            )
        )
        recorder.text_out(8, 8, b"\xc5")
        images.append(render(recorder.to_bytes(), (80, 80), fonts=SystemFontCollection(paths=[])))
    assert images[0].tobytes() == images[1].tobytes()
    assert len(set(images[0].get_flattened_data())) > 1
