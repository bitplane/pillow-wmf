import pytest

from pillow_wmf import Metafile, RasterContext, Recorder, play
from pillow_wmf.wmf.objects import Region, Scan


def test_clip_selection_is_device_space_and_survives_object_deletion():
    context = RasterContext(128, 128)
    context.set_viewport_extent(256, 256)
    handle = context.create_region(Region((8, 8, 32, 32), (Scan(8, 32, (8, 32)),)))
    context.select_clip_region(handle)
    context.delete_object(handle)
    context.set_viewport_extent(128, 128)
    context.set_pixel(8, 8, 0)
    context.set_pixel(32, 8, 0)
    assert context.image.getpixel((8, 8)) == (0, 0, 0)
    assert context.image.getpixel((32, 8)) == (255, 255, 255)


def test_empty_clip_and_no_clip_are_distinct():
    context = RasterContext(8, 8)
    handle = context.create_region(Region((0, 0, 0, 0), ()))
    context.select_clip_region(handle)
    context.set_pixel(1, 1, 0)
    assert context.image.getpixel((1, 1)) == (255, 255, 255)
    context.select_clip_region(None)
    context.set_pixel(1, 1, 0)
    assert context.image.getpixel((1, 1)) == (0, 0, 0)


def test_clip_reset_round_trip_without_objects():
    recorder = Recorder()
    recorder.select_clip_region(None)
    context = RasterContext(8, 8)
    context.exclude_clip_rect(0, 0, 8, 8)
    assert play(Metafile.from_bytes(recorder.to_bytes()), context, strict=True) == ()
    assert context._clip.contains(1, 1)


def test_recorder_does_not_silently_encode_slot_zero_as_clip_reset():
    recorder = Recorder()
    handle = recorder.create_region(Region((0, 0, 8, 8), (Scan(0, 8, (0, 8)),)))
    with pytest.raises(ValueError, match="slot zero"):
        recorder.select_clip_region(handle)
    recorder.select_object(handle)
