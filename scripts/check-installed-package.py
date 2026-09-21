#!/usr/bin/env python3
"""Smoke-test the installed distribution, without repository test resources."""

from importlib.resources import files
from io import BytesIO

from PIL import Image

from pillow_wmf import FontCollection, FontFace, Recorder
from pillow_wmf.wmf.objects import Font


def main():
    source = Recorder()
    source.set_pixel(2, 3, 255)
    with Image.open(BytesIO(source.to_bytes())) as image:
        image.load(size=(17, 23))
        assert image.size == (17, 23)
        assert image.getpixel((2, 3)) == (255, 0, 0)

    # Exercise both packaged fonts, not a developer's installed font inventory.
    fonts = FontCollection(wingdings_fallback=True, symbol_fallback=True)
    for family in (b"Wingdings", b"Symbol"):
        source = Recorder()
        source.select_object(source.create_font(Font(height=-24, face_name=family.ljust(32, b"\0"), charset=2)))
        source.text_out(2, 2, b"ABC")
        with Image.open(BytesIO(source.to_bytes())) as image:
            image.load(fonts=fonts)
            assert image.getextrema() != ((255, 255),) * 3
    assert len(FontFace.bundled_wingdings().data) < 60_000
    resources = files("pillow_wmf").joinpath("fonts")
    for name in ("OFL.txt", "symbol/COPYING.LIB", "symbol/symbol.sfd", "symbol/genttf.ff"):
        assert resources.joinpath(name).read_bytes()
    print("Installed package: Pillow loading, bundled fonts and licence/source resources passed")


if __name__ == "__main__":
    main()
