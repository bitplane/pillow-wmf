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
    with pytest.raises(ValueError, match="Invalid default font"):
        FontCollection(default_font=request)


@pytest.mark.parametrize("strict", [False, True])
def test_extreme_mapping_cannot_expand_unbounded_curves(strict):
    from pillow_wmf import Metafile, RasterContext, play
    from pillow_wmf.binary import ResourceLimitError

    source = Recorder()
    source.set_window_extent(1, 1)
    source.set_viewport_extent(32767, 32767)
    source.scale_viewport_extent(32767, 1, 32767, 1)
    source.scale_viewport_extent(32767, 1, 32767, 1)
    source.ellipse(0, 0, 10, 10)
    data = source.to_bytes()
    context = RasterContext(16, 16, max_bitmap_pixels=256)
    with pytest.raises(ResourceLimitError, match="Curve point limit"):
        play(Metafile.from_bytes(data), context, strict=strict)
    with pytest.raises(RuntimeError, match="unusable"):
        context.set_pixel(0, 0, 0)
    with pytest.raises(ResourceLimitError, match="Curve point limit"):
        render(data, (16, 16), max_bitmap_pixels=256)


def test_render_honors_increased_saved_state_limit():
    source = Recorder(max_saved_states=1025)
    for _ in range(1025):
        source.save_dc()
    source.set_viewport_origin(1, 1)
    source.restore_dc(1)
    source.set_pixel(0, 0, 255)
    image = render(source.to_bytes(), (2, 2), limits=Limits(max_saved_states=1025))
    assert image.getpixel((0, 0)) == (255, 0, 0)
    assert image.getpixel((1, 1)) == (255, 255, 255)


@pytest.mark.parametrize("limit", [0, 1, 1024])
def test_render_rejects_save_beyond_configured_limit(limit):
    from pillow_wmf import PlaybackError

    source = Recorder(max_saved_states=limit + 1)
    for _ in range(limit + 1):
        source.save_dc()
    with pytest.raises(PlaybackError, match="saved-state limit"):
        render(source.to_bytes(), (1, 1), limits=Limits(max_saved_states=limit))


def test_raster_object_limit_rejection_allows_cleanup_and_reuse():
    from pillow_wmf import RasterContext

    context = RasterContext(4, 4, max_objects=1)
    pen = context.create_pen(0, 1, 0)
    with pytest.raises(ValueError, match="Object limit"):
        context.create_brush(0, 255, 0)
    context.delete_object(pen)
    context.select_object(context.create_brush(0, 255, 0))
    context.pat_blt(0, 0, 4, 4, 0xF00021)
    assert context.image.getpixel((1, 1)) == (255, 0, 0)
