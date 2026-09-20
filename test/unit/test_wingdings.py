"""Explicit legacy encoding conversion, separate from glyph appearance."""

from dataclasses import replace
from pathlib import Path
from fractions import Fraction
from importlib.resources import files
from io import BytesIO

import pytest
from fontTools.ttLib import TTFont

from pillow_wmf import FontCollection, FontFace, Metafile, RasterContext, Recorder, UnsupportedOperation, play
from pillow_wmf.wmf.objects import Font
from pillow_wmf.wingdings import FALLBACK_FAMILY, decode_wingdings

REQUEST = Font(height=-24, weight=400, quality=3, charset=2, face_name=b"Wingdings".ljust(32, b"\0"))


def test_mapping_character_identities_and_byte_boundaries():
    assert decode_wingdings(b" AEFSC\xfc") == " \u270c\u261c\u261e\U0001f322\U0001f44d\u2713"
    assert decode_wingdings(b"\x80\x8b\xfe") == "\U0001f10b\U0001f10c\U0001f5f9"
    assert decode_wingdings(b"") == ""
    for byte in range(256):
        if byte < 32 or byte in (127, 255):
            with pytest.raises(UnsupportedOperation, match=f"0x{byte:02X}"):
                decode_wingdings(bytes([byte]))
        else:
            assert len(decode_wingdings(bytes([byte]))) == 1


def test_fallback_is_opt_in_and_retains_physical_identity():
    with pytest.raises(UnsupportedOperation, match="unavailable"):
        FontCollection().resolve(REQUEST)
    fonts = FontCollection(wingdings_fallback=True)
    face = fonts.resolve(REQUEST)
    assert face.family == FALLBACK_FAMILY
    assert fonts.resolve(replace(REQUEST, face_name=b"WINGDINGS")) is face
    assert fonts.decode(REQUEST, face, b"A") == "\u270c"
    with pytest.raises(UnsupportedOperation, match="charset"):
        fonts.decode(replace(REQUEST, charset=0), face, b"A")
    for family in (b"Wingdings 2", b"Wingdings 3", b"Webdings"):
        with pytest.raises(UnsupportedOperation, match="unavailable"):
            fonts.resolve(replace(REQUEST, face_name=family))
    with pytest.raises(UnsupportedOperation, match="unavailable"):
        fonts.resolve(replace(REQUEST, weight=700))


def test_supplied_symbol_face_wins_without_recoding():
    # Original controlled geometry, renamed in memory to test selection only.
    face = FontFace.from_path(Path(__file__).resolve().parents[1] / "fonts/layout.ttf")
    face.family = "Wingdings"
    face.symbol = True
    fonts = FontCollection([face], wingdings_fallback=True)
    assert fonts.resolve(REQUEST) is face
    assert fonts.decode(REQUEST, face, b"AE") == "\uf041\uf045"


def test_missing_unicode_glyph_is_not_silently_replaced():
    fonts = FontCollection(wingdings_fallback=True)
    face = fonts.resolve(REQUEST)
    characters = fonts.decode(REQUEST, face, b"J")
    assert characters == "\u263a"
    with pytest.raises(UnsupportedOperation, match="Missing glyph"):
        fonts.realize(REQUEST, face, (1, 1)).shape(characters, 10000)


def test_wmf_playback_preserves_byte_advances_for_supplementary_symbols():
    recorder = Recorder()
    recorder.select_object(recorder.create_font(REQUEST))
    recorder.set_background_mode(1)
    recorder.set_text_alignment(25)
    recorder.move_to(10, 40)
    recorder.ext_text_out(0, 0, b"SAF", advances=(31, 19, 27))
    source = recorder.to_bytes()
    metafile = Metafile.from_bytes(source)
    assert metafile.to_bytes() == source
    dc = RasterContext(128, 80, fonts=FontCollection(wingdings_fallback=True))
    play(metafile, dc, strict=True)
    assert dc._position == (87, 40)
    assert any(pixel != (255, 255, 255) for pixel in dc.image.get_flattened_data())


def test_fallback_preserves_source_design_metrics_for_every_available_symbol():
    face = FontCollection(wingdings_fallback=True).resolve(REQUEST)
    assert (face.units_per_em, face.average_width, face.ascent, face.descent) == (2048, 1822, 1841, 432)
    with TTFont(BytesIO(face.data)) as font:
        cmap = font.getBestCmap()
        lines = files("pillow_wmf").joinpath("fonts", "wingdings-metrics.txt").read_text().splitlines()
        checked = set()
        for line in lines:
            if line.startswith("#"):
                continue
            byte, *values = line.split()
            character = ord(decode_wingdings(bytes([int(byte, 16)])))
            if character not in cmap:
                continue
            advance, left, bottom, right, top = map(int, values)
            name = cmap[character]
            assert font["hmtx"][name] == (advance, left)
            glyph = font["glyf"][name]
            assert tuple(getattr(glyph, key, 0) for key in ("xMin", "yMin", "xMax", "yMax")) == (
                left,
                bottom,
                right,
                top,
            )
            checked.add(character)
        assert checked == set(cmap)
        assert "Open Font License" in font["name"].getDebugName(13)


@pytest.mark.parametrize("size", [(128, 128), (257, 193)])
def test_fallback_victory_hand_uses_design_metrics_not_canvas_fitting(size):
    fonts = FontCollection(wingdings_fallback=True)
    request = replace(REQUEST, height=-490, width=436)
    scale = Fraction(size[0], 247), Fraction(size[1], 390)
    face = fonts.resolve(request)
    font = fonts.realize(request, face, scale)
    glyph = font.glyph("\u270c", 100000)
    # Measured original advance/bounds, independently of Noto or the WMF image.
    xscale = 436 * scale[0] / 1822
    yscale = round(490 * scale[1]) / 2048
    assert abs(glyph.size[0] - (1032 - 173) * xscale) < 3
    assert abs(glyph.size[1] - (1604 + 25) * yscale) < 3
    assert abs(glyph.bearing[0] - 173 * xscale) < 2
    assert abs(glyph.bearing[1] + 1604 * yscale) < 2
    assert abs(glyph.advance - 1203 * xscale) < 1
    # Loading the Unicode face directly never applies Wingdings metrics.
    original = FontFace.bundled_symbols()
    assert (original.units_per_em, original.average_width) == (1000, 830)
