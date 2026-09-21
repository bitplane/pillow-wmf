"""Opt-in Macintosh decoding retains native NLS mappings and source spans."""

import hashlib
from pathlib import Path

import pytest

from pillow_wmf import Font, FontCollection, FontFace, SystemFontCollection
from pillow_wmf.dbcs import collapse_advances
from pillow_wmf.text import decode_codepage


@pytest.mark.parametrize(
    "codepage,fingerprint",
    [
        (10001, "37f8bb2c903c936afae7e32667a453a58fe6a4fb6104e5a13603eb4156c0e4bb"),
        (10002, "22b356d04ec31668eddeb38d69851d9321cc94ddcb02d2a6d10982db53cf311e"),
        (10003, "4a635e87396746eeb8ff429b903b3cc9c656ac7d34141c412c63a9b2a8518125"),
        (10008, "bd462d0a798117d959ee407bb5cd484d93f45b4de7f7e76a558728bf9e30c7fd"),
    ],
)
def test_native_mac_nls_fingerprint(codepage, fingerprint):
    # All singles/pairs plus malformed-boundary triples. No copied NLS blobs.
    samples = [bytes([b]) for b in range(256)]
    samples += [bytes([a, b]) for a in range(256) for b in range(256)]
    samples += [bytes([a, b, 0x41]) for a in range(0x80, 256) for b in (0, 0x20, 0x40, 0x7F, 0x80, 0xFF)]
    digest = hashlib.sha256()
    for sample in samples:
        decoded = decode_codepage(sample, codepage)
        assert sum(decoded.byte_lengths) == len(sample)
        assert len(decoded.byte_lengths) == len(decoded.text)
        digest.update(bytes([len(sample)]) + sample + bytes([len(decoded.text)]) + decoded.text.encode("utf-32le"))
    assert digest.hexdigest() == fingerprint


@pytest.mark.parametrize(
    "page,source,expected",
    [
        (10001, b"\x85\x40\xfd", "①©"),
        (10002, b"\x81\x40\xfd", "\ue000©"),
        (10003, b"\xb4\xd3\xc9", "닖\0"),
        (10008, b"\xa1\xac\xaa", "∥\0"),
    ],
)
def test_mac_vendor_assignments_and_explicit_environment(page, source, expected):
    face = FontFace.from_path(Path(__file__).parents[1] / "fonts/environment.ttf")
    request = Font(face_name=face.family.encode(), charset=77)
    controlled = FontCollection([face], mac_codepage=page)
    automatic = SystemFontCollection(paths=[], mac_codepage=page)
    decoded = controlled.decode_run(request, face, source)
    assert decoded.text == expected
    assert decoded.byte_lengths == (2, 1)
    assert automatic.decode_run(request, face, source) == decoded
    assert automatic._selection_request(request) == request
    # GDI's byte-array conversion gate only includes the four ANSI DBCS pages.
    assert collapse_advances((9, 5, 7), decoded.byte_lengths, byte_indexed=decoded.byte_indexed_advances) == (9, 5)


@pytest.mark.parametrize(
    "page,lead,replacement", [(10001, 0x81, "・"), (10002, 0x81, "?"), (10003, 0xA1, "?"), (10008, 0xA1, "?")]
)
def test_mac_malformed_pair_and_nul_boundary(page, lead, replacement):
    assert decode_codepage(bytes([lead]), page).text == replacement
    assert decode_codepage(bytes([lead, 0x20, 0x41]), page).text == replacement + "A"
    decoded = decode_codepage(bytes([lead, 0, 0x41]), page)
    assert decoded.text == replacement + "\0A"
    assert decoded.byte_lengths == (1, 1, 1)
