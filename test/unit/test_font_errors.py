"""Extreme LOGFONT/mapping combinations fail the record, not the player."""

from io import BytesIO
from pathlib import Path

import freetype as ft
import pytest
from fontTools.ttLib import TTFont
from PIL import Image

from pillow_wmf import (
    Font,
    FontCollection,
    FontFace,
    Metafile,
    RasterContext,
    Recorder,
    SystemFontCollection,
    UnsupportedOperation,
    play,
)

LAYOUT = Path(__file__).resolve().parents[1] / "fonts/layout.ttf"


def _layout_font_with(changes):
    with TTFont(LAYOUT) as font:
        for table, attribute, value in changes:
            setattr(font[table], attribute, value)
        stream = BytesIO()
        font.save(stream)
    return stream.getvalue()


@pytest.mark.parametrize(
    "changes",
    [
        # Neither the Windows metrics nor their hhea fallback describe a cell.
        (("OS/2", "usWinAscent", 0), ("OS/2", "usWinDescent", 0), ("hhea", "ascent", 0), ("hhea", "descent", 0)),
        (("OS/2", "usWinAscent", 0), ("OS/2", "usWinDescent", 0), ("hhea", "ascent", 800), ("hhea", "descent", 800)),
        (("head", "unitsPerEm", 0),),
    ],
)
def test_face_without_usable_vertical_metrics_is_rejected(changes, tmp_path):
    data = _layout_font_with(changes)
    with pytest.raises(UnsupportedOperation, match="vertical metrics"):
        FontFace(data)
    # Host discovery skips such a face instead of failing the job.
    path = tmp_path / "broken.ttf"
    path.write_bytes(data)
    fonts = SystemFontCollection(paths=[path])
    request = Font(height=-16, face_name=b"Pillow WMF Test")
    with pytest.raises(UnsupportedOperation, match="No usable installed font"):
        fonts.resolve(request)


@pytest.mark.parametrize("height,scale", [(-200, 30000), (-32767, 64)])
def test_unrealizable_font_size_in_both_playback_modes(face, height, scale):
    fonts = FontCollection([face])
    recorder = Recorder()
    recorder.set_window_extent(1, 1)
    recorder.set_viewport_extent(1, scale)
    recorder.select_object(recorder.create_font(Font(height=height, face_name=face.family.encode().ljust(32, b"\0"))))
    recorder.text_out(0, 0, b"A")
    recorder.set_pixel(0, 0, 255)
    data = recorder.to_bytes()
    metafile = Metafile.from_bytes(data)

    context = RasterContext(16, 16, fonts=fonts)
    omissions = play(metafile, context, strict=False)
    assert len(omissions) == 1
    assert "Cannot realize font" in omissions[0].reason
    assert context.image.getpixel((0, 0)) == (255, 0, 0)
    with pytest.raises(UnsupportedOperation, match="Cannot realize font"):
        play(metafile, RasterContext(16, 16, fonts=fonts), strict=True)
    with Image.open(BytesIO(data)) as image, pytest.raises(OSError, match="Cannot realize font"):
        image.load(size=(16, 16), fonts=fonts)
    assert not face._sizes
    assert face.at_size(16) is not None


def test_freetype_error_retains_cause(face):
    with pytest.raises(UnsupportedOperation) as caught:
        face.at_size(6_000_000)
    assert isinstance(caught.value.__cause__, ft.FT_Exception)
