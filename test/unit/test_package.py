def test_package_imports() -> None:
    import pillow_wmf

    assert pillow_wmf.__name__ == "pillow_wmf"


def test_bundled_symbols_font_and_license():
    import hashlib
    from importlib.resources import files

    from pillow_wmf import FontCollection, FontFace, UnsupportedOperation
    from pillow_wmf.wmf.objects import Font
    import pytest

    face = FontFace.bundled_symbols()
    assert face.family == "Noto Sans Symbols2"
    assert not face.symbol
    assert hashlib.sha256(face.data).hexdigest() == "630846d528dbe4c4981370a4d0a9475a1fd1491a129bb411f8e157cdb5de13c6"
    assert {0x270C, 0x261C, 0x261E, 0x1F322} <= face.cmap.keys()
    license_text = files("pillow_wmf").joinpath("fonts", "OFL.txt").read_text()
    assert "Copyright 2018 The Noto Project Authors" in license_text
    assert "SIL OPEN FONT LICENSE Version 1.1" in license_text
    with pytest.raises(UnsupportedOperation, match="Font face unavailable"):
        FontCollection([face]).resolve(Font(face_name=b"Wingdings", charset=2))
    font = face.at_size(24)
    assert any(font.glyph(chr(0x1F322), 10000).pixels)
