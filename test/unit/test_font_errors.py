"""Extreme LOGFONT/mapping combinations fail the record, not the player."""

from io import BytesIO

import freetype as ft
import pytest
from PIL import Image

from pillow_wmf import Font, FontCollection, Metafile, RasterContext, Recorder, UnsupportedOperation, play


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
