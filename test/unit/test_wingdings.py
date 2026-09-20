"""Explicit legacy encoding conversion, separate from glyph appearance."""

from dataclasses import replace
from pathlib import Path

import pytest

from pillow_wmf import FontCollection, FontFace, Metafile, RasterContext, Recorder, UnsupportedOperation, play
from pillow_wmf.wmf.objects import Font
from pillow_wmf.wingdings import decode_wingdings

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
    assert face.family == "Noto Sans Symbols2"
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
