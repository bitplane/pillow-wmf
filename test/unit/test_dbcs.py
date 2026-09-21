"""CP932 byte boundaries, native NLS mappings, and ANSI spacing contracts."""

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from pillow_wmf import Font, FontCollection, FontFace, InvalidOperation, SystemFontCollection, UnsupportedOperation
from pillow_wmf.dbcs import collapse_advances, decode_cp932, decode_dbcs
from pillow_wmf.objects import EncodedText
from pillow_wmf.text import decode_codepage

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
        fonts.decode(replace(request, charset=160), face, b"A")


@pytest.mark.parametrize(
    "codepage,charset,character,encoded",
    [
        (936, 134, "一", b"\xd2\xbb"),
        (949, 129, "가", b"\xb0\xa1"),
        (950, 136, "一", b"\xa4\x40"),
        (1361, 130, "가", b"\x88\x61"),
    ],
)
def test_remaining_dbcs_charsets_preserve_bytes_and_environment(codepage, charset, character, encoded):
    source = b"A" + encoded + b"B"
    decoded = decode_codepage(source, codepage)
    assert decoded.text == "A" + character + "B"
    assert decoded.byte_lengths == (1, 2, 1)
    assert collapse_advances((9, 5, 7, 13), decoded.byte_lengths) == (9, 12, 13)
    assert collapse_advances((1, -3, 8, -6), decoded.byte_lengths) == (1, 5, -6)
    face = FontFace.from_path(FONT.with_name("layout.ttf"))
    request = Font(face_name=face.family.encode(), charset=charset)
    fonts = FontCollection([face], ansi_codepage=codepage)
    with pytest.raises(UnsupportedOperation, match="advertise"):
        fonts.decode(request, face, source)
    face.codepages |= 1 << {936: 18, 949: 19, 950: 20, 1361: 21}[codepage]
    assert fonts.decode(request, face, source) == decoded.text
    assert fonts.decode(replace(request, charset=1), face, source) == decoded.text
    automatic = SystemFontCollection(paths=[], ansi_codepage=codepage)
    assert automatic.decode_run(request, face, source) == decoded
    named = replace(request, charset=1, face_name=encoded)
    assert automatic._name(named) == character
    aliased = FontCollection([face], ansi_codepage=codepage, aliases={character: face.family})
    assert aliased.resolve(named) is face


def test_controlled_font_is_reproducible(load_script):
    assert load_script("dbcs_cases.py")["font_bytes"]() == FONT.read_bytes()
    assert load_script("dbcs_cases.py")["extended_font_bytes"]() == FONT.with_name("dbcs.ttf").read_bytes()


def test_cp932_ansi_environment_decodes_font_names_and_default_text():
    face = FontFace.from_path(FONT)
    japanese_name = "HG正楷書体-PRO"
    fonts = FontCollection([face], ansi_codepage=932, aliases={japanese_name: face.family})
    request = Font(face_name=japanese_name.encode("cp932"), charset=1)
    assert fonts.resolve(request) is face
    assert fonts.decode(request, face, b"\x83\xa1") == "\u0393"
    automatic = SystemFontCollection(paths=[FONT], ansi_codepage=932)
    assert automatic._name(request) == japanese_name


@pytest.mark.parametrize(
    "codepage,fingerprint",
    [
        (936, "3897155cbd83f158d099da3b6c56a6513999a4815c6b857021f8f0064a503680"),
        (949, "b611beb9322b50050954b771e249a0a7f58c9d82dfbf3f09870f054594779f2b"),
        (950, "afa017e43c012fccf13c801cdc09a1d20121646c086d61e6e1c573c11576ddb5"),
        (1361, "ab8817f46dd886f35bc3c683f0e76d6c74f49352e37591c9529c3e5c72ace96c"),
    ],
)
def test_remaining_complete_native_nls_conversion_fingerprints(codepage, fingerprint):
    # All singles, all pairs (including non-leads), then malformed boundaries
    # followed by ASCII. Expected fingerprints come from MultiByteToWideChar.
    samples = [bytes([b]) for b in range(256)]
    samples += [bytes([a, b]) for a in range(256) for b in range(256)]
    samples += [bytes([a, b, 0x41]) for a in range(0x80, 256) for b in (0, 0x20, 0x40, 0x7F, 0x80, 0xFF)]
    digest = hashlib.sha256()
    for source in samples:
        decoded = decode_dbcs(source, codepage)
        assert sum(decoded.byte_lengths) == len(source)
        assert len(decoded.byte_lengths) == len(decoded.text)
        digest.update(bytes([len(source)]) + source + bytes([len(decoded.text)]) + decoded.text.encode("utf-32le"))
    assert digest.hexdigest() == fingerprint


@pytest.mark.parametrize("codepage,lead", [(936, 0x81), (949, 0x81), (950, 0x81), (1361, 0x84)])
def test_dbcs_invalid_pairs_preserve_nul_and_following_ascii(codepage, lead):
    for suffix, text, lengths in ((b"", "?", (1,)), (b" A", "?A", (2, 1)), (b"\0A", "?\0A", (1, 1, 1))):
        decoded = decode_dbcs(bytes([lead]) + suffix, codepage)
        assert (decoded.text, decoded.byte_lengths) == (text, lengths)


@pytest.mark.parametrize(
    "codepage,source,expected",
    [
        (
            936,
            "80 ff aaa1 aafe aba1 a140 a17e a180 a2ab fea0",
            "\u20ac\uf8f5\ue000\ue05d\ue05e\ue4c6\ue504\ue505\ue766\ue864",
        ),
        (949, "80 ff c9a1 c9fe fea1 fefe", "\x80\uf8f7\ue000\ue05d\ue05e\ue0bb"),
        (950, "80 ff fa40 fa7e faa1 8140 c6a1 c8fe", "\x80\uf8f8\ue000\ue03e\ue03f\ueeb8\uf6b1\uf848"),
        (
            1361,
            "8441 8442 845d 8461 87a1 8841 d041 dad4 dafe d831 d8fe",
            "?\u11a8\u11c2\u1161\u1175\u1100\u1112\u115f\u11a1\ue000\ue0bb",
        ),
    ],
)
def test_windows_vendor_and_johab_component_mappings(codepage, source, expected):
    assert decode_dbcs(bytes.fromhex(source), codepage).text == expected


def test_johab_uses_character_indexed_advances_without_losing_byte_spans():
    decoded = decode_dbcs(b"A\x88\x61B", 1361)
    assert decoded.text == "A가B"
    assert decoded.byte_lengths == (1, 2, 1)
    assert not decoded.byte_indexed_advances
    assert collapse_advances((9, 5, 7, 13), decoded.byte_lengths, byte_indexed=False) == (9, 5, 7)
    assert collapse_advances((1, 2, 3, -6), decoded.byte_lengths, byte_indexed=False) == (1, 2, 3)
    with pytest.raises(InvalidOperation, match="byte count"):
        collapse_advances((9, 5, 7), decoded.byte_lengths, byte_indexed=False)


@pytest.mark.parametrize("codepage", [932, 936, 949, 950, 1361])
def test_empty_dbcs_runs_and_single_byte_api_rejection(codepage):
    from pillow_wmf.text import decode_single_byte

    decoded = decode_dbcs(b"", codepage)
    assert decoded.text == ""
    assert decoded.byte_lengths == ()
    with pytest.raises(UnsupportedOperation, match="code page"):
        decode_single_byte(b"A", codepage)


@pytest.mark.parametrize("first,second,last_offset", [(2, 10, 21), (10, 2, 26), (10, 10, 29), (-3, 20, 26)])
@pytest.mark.parametrize("pdy", [False, True])
def test_hangul_run_end_justification_preserves_logical_advance(first, second, last_offset, pdy):
    from pillow_wmf import RasterContext

    face = FontFace.from_path(FONT.with_name("dbcs.ttf"))
    dc = RasterContext(128, 128, fonts=FontCollection([face]))
    dc.select_object(dc.create_font(Font(face_name=face.family.encode(), charset=129, height=-16, quality=3)))
    dc.set_text_alignment(25)
    dc.move_to(16, 54)
    advances = (9, first, 0, second, 0, 7)
    if pdy:
        advances = tuple(v for dx in advances for v in (dx, 0))
    layout, _ = dc._prepare_text(
        dict(x=0, y=0, text=EncodedText("A가가B".encode("cp949")), advances=advances, options=0x2000 if pdy else 0)
    )
    origins = tuple(x - glyph.bearing[0] for x, _, glyph in layout.glyphs)
    last = 9 + first + second if pdy else last_offset
    assert origins == (16, 25, 25 + first, 16 + last)
    assert layout.position == (16 + 9 + first + second + 7, 54)
