"""Explicit text environments and native unsupported-charset selection."""

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from pillow_wmf import Font, FontCollection, FontFace, RasterContext, SystemFontCollection, UnsupportedOperation
from pillow_wmf.text import decode_codepage

FONT = Path(__file__).parents[1] / "fonts/environment.ttf"


@pytest.mark.parametrize(
    "codepage,fingerprint",
    [
        (10000, "b0517f6aa35723cf394607b5c9525e39d9760ae6b789d9d2523238fc8d461c1d"),
        (10004, "ef819a2204475ff1b3a1e31f5603a7a81ad311b8533f6f9eea44577e7e832c00"),
        (10005, "af9b338490dec4c16e4fb1b37f234fae62409d54771afefba18f50f7619bdc6b"),
        (10006, "5f7dd855d0595dd25f28b8f48fdafd489812e841158ebd0c745c840f220895dd"),
        (10007, "4330e2f92d47700766670bdf22a0ebed720a65726db90f2e5f5dbce24145c269"),
        (10010, "4d5b1e0e7bc41edd2b2f2cec5b0acb30835060c98851067b1ef494c0cd2edf80"),
        (10017, "0ac70d4a8bd967beda973a03e6f252fc6d7bb7699bdc9a92ebbaff6c93cf83e9"),
        (10021, "550999aa1dcd82dd488471975e9decafeb18a67db0773eb67f5ef4d5e145b8f4"),
        (10029, "00c81d8dad40f000e76a88688551bdbfc7291734ac9030eb6f4404ee9bc53a3e"),
        (10079, "95bb921741f1a7392d687c97bbca657164d3cf7d1b0cb8d9a7a7b17aaaabc4ea"),
        (10081, "5b1f2694dfc57ba5ccfc939c3b4d1ba926c6032f55964a8e2dbcf2253160906d"),
        (10082, "a1b432efeab3ec5bc7db728a4a4fc5725e085151402f302114f0111779660d1c"),
        (437, "3b331692abddbdfa697e0e3b15e34d07859840f1d94e36eef8d34985405235ed"),
        (708, "34c47e3ffa2b8da9027771320206e5c8b0ee7eced65cdae859eabb44dfa05792"),
        (720, "16f804cb263e500f252e3a29fdbc735967b993e8136954decb9b111018ec38c0"),
        (737, "3e3659b37ad89ef942006b9f24d2915353b633644471f68dd9a2483601a2c57a"),
        (775, "ad319bbc5a65a51b59e4c899702d8c9c1952e3553e25bf94fdb5100ca3b35411"),
        (850, "c7e031eaeb91d36c24ce7fa0cc66090720165a0c1c47d96827869e59964b462d"),
        (852, "4e61b20363cdda6424d8072eaa434565fe551732c8a681cb91de445882755882"),
        (855, "b233c4d6adcf484d5512615b607a51ea4378bc2e08d0ab30c351b3a47e635b23"),
        (857, "f1e37c8660fc34b4371c452a24bb39e814017d29181e4f197989a10f98346bf9"),
        (858, "38c6bc13ac318df5e98a51e2c69a31fa62f539609fdcca69f4657402f94905f9"),
        (860, "186eacc467608ef0fbbc6b188d274e9ed2744297305241c64d445f7117eaee56"),
        (861, "79a4e4fefcb2e582e61379d12c2f5cf1b22b7a5b9bfe85bcaec3af1e6a5cdd38"),
        (862, "bf0d91e28a06ffa1dd8615882fe946d8f5f214f84391124f72c421e4c8868771"),
        (863, "2f579419c8aef72fd8dad7d3ec27271e8480121294d00b794dca01c35fe75010"),
        (864, "cc022a0cb2d4ef56d6888835df8ad481b74544649849be34658c9a9d5ef7fbc3"),
        (865, "f34788d50d32ef0c1447a57d0d415e56c9bfd9d2cf507b4c316d015792f43b39"),
        (866, "1a2194aa10d1f46e43961581daa31c085c90763414672d3eb614ed3c4f8fb180"),
        (869, "2d7691b5dd74f68d765b453a143e319e6fe47025947d32f5663cd39f1b5e9944"),
    ],
)
def test_complete_native_environment_tables(codepage, fingerprint):
    decoded = decode_codepage(bytes(range(256)), codepage)
    assert len(decoded.text) == 256
    assert decoded.byte_lengths == (1,) * 256
    assert hashlib.sha256(decoded.text.encode("utf-32le")).hexdigest() == fingerprint


def test_native_mac_and_oem_mapping_boundaries_remain_literal():
    assert decode_codepage(b"\xbd", 10000).text == "\u2126"  # OHM SIGN, not Greek omega.
    assert decode_codepage(b"\xa0\xfd", 10004).text == "\uf827\uf840"
    assert decode_codepage(b"\xa0\xff", 10005).text == "\uf7fc\uf826"
    assert decode_codepage(b"\x7f\x90\xdb\xdc\xff", 10021).text == "\0\0\ufeff\u200b\0"
    assert decode_codepage(b"\xd5\xe7\xf2", 857).text == "\uf8bb\uf8bc\uf8bd"
    assert decode_codepage(b"%\xa6\xa7\xff", 864).text == "%\uf8be\uf8bf\uf8c0"


def test_unknown_charset_classification_matches_native_ordinary_face_selection():
    known = {0, 1, 2, 128, 129, 130, 134, 136, 161, 162, 163, 177, 178, 186, 204, 222, 238, 254, 255}
    fonts = SystemFontCollection(paths=[])
    for charset in set(range(256)) - known:
        effective = fonts._selection_request(Font(face_name=b"Arial", charset=charset))
        assert effective.charset == 1
        assert effective.face_name == b""


def test_shared_oem_dbcs_page_preserves_its_advance_policy():
    fonts = SystemFontCollection(paths=[FONT], oem_codepage=932)
    request = Font(face_name=b"Pillow WMF Environment", charset=255)
    decoded = fonts.decode_run(request, fonts.resolve(request), b"A\x83\xa1")
    assert decoded.text == "AΓ"
    assert decoded.byte_lengths == (1, 2)


def test_oem_and_mac_are_explicit_and_do_not_change_face_name_encoding():
    face = FontFace.from_path(FONT)
    request = Font(face_name="É".encode("cp1252"), charset=255)
    fonts = FontCollection([face], aliases={"É": face.family}, oem_codepage=866, mac_codepage=10007)
    assert fonts.resolve(request) is face
    assert fonts.decode(request, face, b"\x80\xa0") == "Аа"
    assert fonts.decode(replace(request, charset=77), face, b"\x80\xe0") == "Аа"
    assert fonts.decode(replace(request, charset=1), face, b"\x80") == "€"
    assert FontCollection([face]).decode(request, face, b"\x80\x82") == "Çé"
    with pytest.raises(UnsupportedOperation, match="charset"):
        FontCollection([face]).decode(replace(request, charset=77), face, b"\x80")


@pytest.mark.parametrize("options,error", [({"oem_codepage": 65001}, "OEM"), ({"mac_codepage": 65001}, "Macintosh")])
def test_invalid_environments_fail_at_configuration(options, error):
    with pytest.raises(ValueError, match=error):
        FontCollection(**options)
    with pytest.raises(ValueError, match=error):
        SystemFontCollection(paths=[], **options)


def test_private_font_is_reproducible(load_script):
    assert load_script("environment_cases.py")["font_bytes"]() == FONT.read_bytes()


def test_oem_coverage_reads_the_second_os2_word():
    face = FontFace.from_path(FONT)
    assert face.codepages & (1 << 63)
    face.codepages = 1 << 63  # US OEM coverage without generic OEM bit 30.
    request = Font(face_name=face.family.encode(), charset=255)
    assert FontCollection([face]).decode(request, face, b"\x80") == "Ç"
    with pytest.raises(UnsupportedOperation, match="advertise"):
        FontCollection([face], oem_codepage=866).decode(request, face, b"\x80")


@pytest.mark.parametrize("charset", [3, 77, 160, 253])
def test_automatic_unknown_charset_uses_ansi_and_reports_the_choice(charset):
    fonts = SystemFontCollection(paths=[FONT])
    request = Font(face_name=b"Unavailable", charset=charset)
    face = fonts.resolve(request)
    assert fonts.decode(request, face, b"\x80\xe9") == "€é"
    assert fonts.substitutions[-1].reason == f"charset {charset} fallback to ANSI"
    assert fonts.substitutions[-1].requested == "Unavailable"
    count = len(fonts.substitutions)
    fonts.decode(request, face, b"A")
    assert len(fonts.substitutions) == count


@pytest.mark.parametrize("charset", [3, 77, 160, 253])
def test_unknown_charset_keeps_a_requested_symbol_family(charset):
    fonts = SystemFontCollection(paths=[])
    for family in ("Wingdings", "Symbol"):
        request = Font(face_name=family.encode(), charset=charset)
        face = fonts.resolve(request)
        assert fonts.decode(request, face, b"A") == fonts.decode(replace(request, charset=2), face, b"A")


def test_explicit_mac_override_does_not_use_native_ansi_fallback():
    fonts = SystemFontCollection(paths=[FONT], mac_codepage=10000)
    request = Font(face_name=b"Pillow WMF Environment", charset=77)
    face = fonts.resolve(request)
    assert fonts.decode(request, face, b"\x80\x82") == "ÄÇ"
    assert not fonts.substitutions


def test_direct_gdi_utf8_remains_distinct_from_wmf_charset_normalization():
    fonts = SystemFontCollection(paths=[FONT])
    for name in (b"Arial", b"Symbol", b"Wingdings"):
        request = Font(face_name=name, charset=254)
        with pytest.raises(UnsupportedOperation, match="UTF-8"):
            fonts.resolve(request)


def test_charset_extension_font_is_reproducible(load_script):
    assert load_script("utf8_cases.py")["font_bytes"]() == FONT.with_name("utf8.ttf").read_bytes()


def test_oem_text_current_position_and_restore():
    face = FontFace.from_path(FONT)
    dc = RasterContext(128, 128, fonts=FontCollection([face]))
    dc.select_object(dc.create_font(Font(face_name=face.family.encode(), charset=255, height=-20, quality=3)))
    dc.set_text_alignment(25)
    dc.move_to(8, 30)
    dc.save_dc()
    dc.ext_text_out(0, 0, b"\x80\x82AB", advances=(17, 19, 13, 11))
    assert dc._position == (68, 30)
    dc.restore_dc(-1)
    assert dc._position == (8, 30)
