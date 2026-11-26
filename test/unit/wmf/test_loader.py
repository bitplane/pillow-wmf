"""The WMF loader identifies, places and plays a file for any front-end."""

import pytest

from pillow_wmf import FormatError, PlaceableHeader, RasterContext, Recorder, UnsupportedOperation
from pillow_wmf.objects import FontRequest
from pillow_wmf.plugin import LOADERS
from pillow_wmf.text import FontCollection
from pillow_wmf.wmf import loader


def _drawing():
    recorder = Recorder()
    recorder.set_pixel(2, 3, 255)
    return recorder.to_bytes()


def test_plugin_registers_the_wmf_loader():
    assert loader in LOADERS


@pytest.mark.parametrize("placeable", [False, True])
def test_accepts_plain_and_placeable_headers(placeable):
    data = (PlaceableHeader(0, 0, 32, 16, 1440).to_bytes() if placeable else b"") + _drawing()
    assert loader.accepts(data[:16])
    assert not loader.accepts(b"\x01\x00\x00\x00 EMF")


def test_placement_comes_from_usable_placeable_bounds():
    drawing = _drawing()
    assert loader.placement(drawing[: loader.HEADER_BYTES]) is None
    placed = PlaceableHeader(-4, 2, 28, 18, 1440).to_bytes() + drawing
    assert loader.placement(placed[: loader.HEADER_BYTES]) == loader.Placement((-4, 2, 28, 18), 1440)
    reversed_bounds = PlaceableHeader(8, 0, 8, 16, 1440).to_bytes() + drawing
    zero_density = placed[:14] + bytes(2) + placed[16:]
    for unusable in (reversed_bounds, zero_density):
        assert loader.placement(unusable[: loader.HEADER_BYTES]) is None


def test_placement_rejects_an_invalid_header():
    with pytest.raises(FormatError):
        loader.placement(b"\x01\x00\x09\x00" + bytes(14))
    with pytest.raises(FormatError):
        loader.placement(_drawing()[:10])


def test_play_into_maps_the_placement_onto_the_context():
    data = PlaceableHeader(0, 0, 8, 8, 1440).to_bytes() + _drawing()
    context = RasterContext(16, 16)
    loader.play_into(context, data, loader.placement(data[: loader.HEADER_BYTES]))
    assert context.image.getpixel((4, 6)) == (255, 0, 0)
    unplaced = RasterContext(16, 16)
    loader.play_into(unplaced, data, None)
    assert unplaced.image.getpixel((2, 3)) == (255, 0, 0)


def test_play_into_is_strict():
    recorder = Recorder()
    recorder.select_object(recorder.create_font(FontRequest(height=-12, face_name="Unavailable Face")))
    recorder.text_out(0, 0, b"x")
    with pytest.raises(UnsupportedOperation):
        loader.play_into(RasterContext(4, 4, fonts=FontCollection([])), recorder.to_bytes(), None)
