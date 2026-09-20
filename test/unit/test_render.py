"""The public renderer uses the same strict playback as compatibility tests."""

from pathlib import Path

import pytest

from pillow_wmf import FontCollection, FontFace, FormatError, Limits, Recorder, UnsupportedOperation, render
from pillow_wmf.wmf.objects import Font


def test_render_returns_rgb_at_requested_size():
    source = Recorder()
    source.set_pixel(2, 3, 255)
    image = render(source.to_bytes(), (17, 23), background=(1, 2, 3))
    assert image.mode == "RGB"
    assert image.size == (17, 23)
    assert image.getpixel((2, 3)) == (255, 0, 0)
    assert image.getpixel((0, 0)) == (1, 2, 3)


def test_render_never_silently_returns_partial_output():
    source = Recorder()
    source.escape(0x7777, b"")
    with pytest.raises(UnsupportedOperation):
        render(source.to_bytes(), (10, 10))
    with pytest.raises(FormatError):
        render(source.to_bytes(), (10, 10), limits=Limits(max_bytes=1))


def test_configured_default_is_equivalent_to_explicit_font_selection():
    face = FontFace.from_path(Path(__file__).parents[1] / "fonts/layout.ttf")
    request = Font(height=-20, weight=400, quality=3, face_name=b"Pillow WMF Test".ljust(32, b"\0"))
    fonts = FontCollection([face], default_font=request)
    assert fonts.resolve(None) is face
    implicit = Recorder()
    implicit.text_out(5, 5, b"AB")
    explicit = Recorder()
    explicit.select_object(explicit.create_font(request))
    explicit.text_out(5, 5, b"AB")
    assert (
        render(implicit.to_bytes(), (60, 40), fonts=fonts).tobytes()
        == render(explicit.to_bytes(), (60, 40), fonts=fonts).tobytes()
    )
    with pytest.raises(UnsupportedOperation, match="Default font"):
        render(implicit.to_bytes(), (60, 40), fonts=FontCollection([face]))
    with pytest.raises(UnsupportedOperation, match="unavailable"):
        FontCollection(default_font=request)
