"""CP932 byte boundaries, native NLS mappings, and ANSI spacing contracts."""

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from pillow_wmf import Font, FontCollection, FontFace, InvalidOperation, SystemFontCollection, UnsupportedOperation
from pillow_wmf.dbcs import collapse_advances, decode_cp932

FONT = Path(__file__).parents[1] / "fonts/cp932.ttf"


def test_mixed_single_and_double_byte_text_retains_source_spans():
    decoded = decode_cp932(b"A\x83\xa1B\x82\xa0\xb1\x88\xea")
    assert decoded.text == "A\u0393B\u3042\uff71\u4e00"
    assert decoded.byte_lengths == (1, 2, 1, 2, 1, 2)


@pytest.mark.parametrize(
    "source,text,lengths",
    (
        (b"\x81", "\u30fb", (1,)),
        (b"\x81 A", "\u30fbA", (2, 1)),
        (b"\x81\x00A", "\u30fb\x00A", (1, 1, 1)),
        (b"\x81\xad", "\u30fb", (2,)),
        (b"\x80\xa0\xfd\xfe\xff", "\x80\uf8f0\uf8f1\uf8f2\uf8f3", (1, 1, 1, 1, 1)),
        (b"", "", ()),
    ),
)
def test_native_malformed_and_vendor_mappings(source, text, lengths):
    decoded = decode_cp932(source)
    assert (decoded.text, decoded.byte_lengths) == (text, lengths)


def test_complete_native_nls_conversion_fingerprint():
    # All singles and all lead/trail pairs from MultiByteToWideChar(932, 0).
    # Keep one digest rather than a large duplicate codec table in the repo.
    samples = [bytes([b]) for b in range(256)]
    samples += [bytes([a, b]) for a in (*range(0x81, 0xA0), *range(0xE0, 0xFD)) for b in range(256)]
    digest = hashlib.sha256()
    for sample in samples:
        decoded = decode_cp932(sample)
        assert sum(decoded.byte_lengths) == len(sample)
        assert len(decoded.byte_lengths) == len(decoded.text)
        digest.update(bytes([len(sample)]) + sample + bytes([len(decoded.text)]) + decoded.text.encode("utf-32le"))
    assert digest.hexdigest() == "4f092bc26ab171cd242c9b8b720f16b08c145736fe7cfe00a247df1a59bcbe37"


def test_ansi_advances_sum_by_character_for_both_axes():
    spans = decode_cp932(b"A\x83\xa1B").byte_lengths
    assert collapse_advances((9, 5, 7, 13), spans) == (9, 12, 13)
    assert collapse_advances((9, 12, 0, 13), spans) == (9, 12, 13)
    assert collapse_advances((1, -3, 8, -6), spans) == (1, 5, -6)
    assert collapse_advances((), spans) == ()
    with pytest.raises(InvalidOperation, match="byte count"):
        collapse_advances((9, 12, 13), spans)


def test_explicit_font_selection_checks_cp932_coverage_and_preserves_decode_api():
    face = FontFace.from_path(FONT)
    request = Font(face_name=face.family.encode(), charset=128)
    fonts = FontCollection([face])
    assert fonts.decode(request, face, b"\x83\xa1") == "\u0393"
    assert fonts.decode_run(request, face, b"\x83\xa1").byte_lengths == (2,)
    latin = FontFace.from_path(FONT.with_name("layout.ttf"))
    with pytest.raises(UnsupportedOperation, match="advertise"):
        fonts.decode(request, latin, b"\x83\xa1")
    automatic = SystemFontCollection(paths=[])
    assert automatic.decode(request, latin, b"\x83\xa1") == "\u0393"
    with pytest.raises(UnsupportedOperation, match="charset"):
        fonts.decode(replace(request, charset=129), face, b"A")


def test_controlled_font_is_reproducible(load_script):
    assert load_script("dbcs_cases.py")["font_bytes"]() == FONT.read_bytes()


def test_cp932_ansi_environment_decodes_font_names_and_default_text():
    face = FontFace.from_path(FONT)
    japanese_name = "HG正楷書体-PRO"
    fonts = FontCollection([face], ansi_codepage=932, aliases={japanese_name: face.family})
    request = Font(face_name=japanese_name.encode("cp932"), charset=1)
    assert fonts.resolve(request) is face
    assert fonts.decode(request, face, b"\x83\xa1") == "\u0393"
    automatic = SystemFontCollection(paths=[FONT], ansi_codepage=932)
    assert automatic._name(request) == japanese_name
