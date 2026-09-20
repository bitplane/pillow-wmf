def test_package_imports() -> None:
    import pillow_wmf

    assert pillow_wmf.__name__ == "pillow_wmf"


def test_bundled_wingdings_font_and_license():
    from importlib.resources import files

    import pytest

    from pillow_wmf import FontCollection, FontFace, UnsupportedOperation
    from pillow_wmf.wmf.objects import Font

    face = FontFace.bundled_wingdings()
    assert face.family == "Pillow WMF Wingdings Fallback"
    assert not face.symbol
    assert len(face.data) < 60_000
    assert {0x270C, 0x261C, 0x261E, 0x1F322} <= face.cmap.keys()
    license_text = files("pillow_wmf").joinpath("fonts", "OFL.txt").read_text()
    assert "Copyright 2018 The Noto Project Authors" in license_text
    assert "SIL OPEN FONT LICENSE Version 1.1" in license_text
    with pytest.raises(UnsupportedOperation, match="Font face unavailable"):
        FontCollection([face]).resolve(Font(face_name=b"Wingdings", charset=2))
    font = face.at_size(24)
    assert any(font.glyph(chr(0x1F322), 10000).pixels)


def test_font_build_matches_packaged_bytes(load_script):
    from pathlib import Path

    from pillow_wmf import FontFace

    root = Path(__file__).resolve().parents[2]
    build = load_script("build-font.py")["build_font"]
    source = (root / "src/fonts/NotoSansSymbols2-Regular.ttf").read_bytes()
    metrics = (root / "src/fonts/wingdings-metrics.txt").read_text()
    assert build(source, metrics) == FontFace.bundled_wingdings().data
