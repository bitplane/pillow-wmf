#!/usr/bin/env python3
"""Smoke-test the installed distribution, without repository test resources."""

from importlib.metadata import distribution
from importlib.resources import files
from io import BytesIO

from PIL import Image

from pillow_wmf import FontCollection, FontFace, Recorder
from pillow_wmf.wmf.objects import Font


def main():
    package = distribution("pillow_wmf")
    assert package.metadata["License-Expression"] == (
        "LicenseRef-WTFPL-With-Warranty AND LGPL-2.1-or-later AND OFL-1.1"
    )
    notices = package.metadata.get_all("License-File")
    assert notices and "LICENSE.md" in notices
    assert "src/pillow_wmf/fonts/OFL.txt" in notices
    assert "src/pillow_wmf/fonts/symbol/COPYING.LIB" in notices
    for notice in notices:
        path = next(p for p in package.files if str(p).endswith(f".dist-info/licenses/{notice}"))
        assert package.locate_file(path).read_bytes()

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
