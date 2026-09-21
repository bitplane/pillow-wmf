"""Pillow loading contracts, independent of installed fonts and native runners."""

import subprocess
import sys
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, UnidentifiedImageError, WmfImagePlugin

from pillow_wmf import FontCollection, FontFace, Metafile, PlaceableHeader, Recorder, UnsupportedOperation, render
from pillow_wmf.plugin import WmfImageFile
from pillow_wmf.wmf.objects import Font


def test_plain_wmf_and_explicit_canvas():
    recorder = Recorder()
    recorder.set_pixel(2, 3, 255)
    data = recorder.to_bytes()
    stream = BytesIO(data)
    with Image.open(stream, formats=["WMF"]) as image:
        assert isinstance(image, WmfImageFile)
        assert image.size == (128, 128)
        image.load(size=(17, 23))
        assert image.tobytes() == render(data, (17, 23)).tobytes()
        assert image.load() is not None
        assert image.copy().size == (17, 23)
        with pytest.raises(ValueError, match="already loaded"):
            image.load(size=(20, 20))
    assert not stream.closed


def test_placeable_mapping_and_dpi():
    recorder = Recorder()
    recorder.set_pixel(100, 200, 255)
    metafile = Metafile.from_bytes(recorder.to_bytes())
    data = Metafile.build(metafile.records, placeable=PlaceableHeader(100, 200, 1540, 3080)).to_bytes()
    with Image.open(BytesIO(data)) as image:
        assert image.size == (72, 144)
        image.load(dpi=144)
        assert image.size == (144, 288)
        assert image.getpixel((0, 0)) == (255, 0, 0)


def test_path_is_closed_after_loading(tmp_path):
    path = tmp_path / "drawing.wmf"
    path.write_bytes(Recorder().to_bytes())
    image = Image.open(path)
    stream = image.fp
    image.load()
    assert stream.closed
    assert image.fp is None
    image.close()


def test_font_default_and_explicit_override(monkeypatch):
    from pillow_wmf import plugin

    font_path = Path(__file__).parents[1] / "fonts/layout.ttf"
    request = Font(height=-20, face_name=b"Pillow WMF Test", quality=3)
    fonts = FontCollection([FontFace.from_path(font_path)], default_font=request)

    class InstalledFonts(plugin.SystemFontCollection):
        def __init__(self):
            super().__init__(paths=[font_path], default_font=request)

    monkeypatch.setattr(plugin, "SystemFontCollection", InstalledFonts)
    recorder = Recorder()
    recorder.text_out(1, 2, b"AB")
    with Image.open(BytesIO(recorder.to_bytes())) as image:
        image.load(fonts=fonts)
        assert image.tobytes() == render(recorder.to_bytes(), (128, 128), fonts=fonts).tobytes()
    with Image.open(BytesIO(recorder.to_bytes())) as image:
        image.load()
        assert image.tobytes() == render(recorder.to_bytes(), (128, 128), fonts=InstalledFonts()).tobytes()
        assert "wmf_font_substitutions" in image.info


@pytest.mark.parametrize("options", [{"size": (0, 10)}, {"size": (1.5, 2)}, {"dpi": 72}, {"size": (10, 10), "dpi": 72}])
def test_invalid_options(options):
    with Image.open(BytesIO(Recorder().to_bytes())) as image, pytest.raises(ValueError):
        image.load(**options)


def test_unsupported_drawing_is_not_silently_omitted():
    recorder = Recorder()
    recorder.escape(0x7777, b"")
    with Image.open(BytesIO(recorder.to_bytes())) as image, pytest.raises(OSError) as caught:
        image.load()
    assert isinstance(caught.value.__cause__, UnsupportedOperation)
    with pytest.raises(UnsupportedOperation):
        render(recorder.to_bytes(), (128, 128))


def test_corrupt_signature_becomes_unidentified_image():
    data = b"\x01\x00\x09\x00" + bytes(14)
    with pytest.raises(UnidentifiedImageError):
        Image.open(BytesIO(data), formats=["WMF"])


def test_plugin_preserves_programming_errors(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("unexpected defect")

    monkeypatch.setattr("pillow_wmf.plugin.play", broken)
    with Image.open(BytesIO(Recorder().to_bytes())) as image, pytest.raises(RuntimeError, match="unexpected defect"):
        image.load()


def test_pillow_lazy_initialization_cannot_replace_registration():
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from PIL import Image; import pillow_wmf; "
            "Image.init(); from io import BytesIO; "
            "from pillow_wmf.plugin import WmfImageFile; "
            "assert isinstance(Image.open(BytesIO(pillow_wmf.Recorder().to_bytes())), WmfImageFile)",
        ],
        check=True,
    )


def test_emf_is_delegated(monkeypatch):
    from pillow_wmf.plugin import _factory

    sentinel = object()
    monkeypatch.setattr(WmfImagePlugin, "WmfStubImageFile", lambda fp, filename: sentinel)
    assert _factory(BytesIO(b"\x01\x00\x00\x00" + bytes(40)), "test.emf") is sentinel


def test_output_size_obeys_pillow_bomb_limit(monkeypatch):
    with Image.open(BytesIO(Recorder().to_bytes())) as image:
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
        with pytest.raises(Image.DecompressionBombError):
            image.load(size=(100, 100))
