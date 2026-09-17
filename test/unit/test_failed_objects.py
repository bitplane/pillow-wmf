"""Failed native creations are null results, not live allocated objects."""

import pytest

from pillow_wmf import RasterContext, Recorder, play
from pillow_wmf.bitmap16 import encode_bitmap16
from pillow_wmf.wmf.objects import Palette, Region, Scan


@pytest.mark.parametrize("kind", ("region", "brush", "palette"))
def test_repeated_failed_creations_do_not_consume_object_budget(kind):
    dc = RasterContext(8, 8)
    dc.max_objects = 1
    results = []
    for _ in range(20):
        if kind == "region":
            handle = dc.create_region(Region((0, 0, 0, 0), ()))
        elif kind == "palette":
            handle = dc.create_palette(Palette(entries=()))
        else:
            handle = dc.create_pattern_brush(encode_bitmap16(1, 1, (1,), pattern=True))
        assert dc.is_null_object(handle)
        results.append(handle)
    assert len(dc._live) == 0
    assert len(dc._objects) == 1
    valid = dc.create_brush(0, 255, 0)
    assert not dc.is_null_object(valid)
    with pytest.raises(ValueError, match="Object limit"):
        dc.create_brush(0, 0, 0)
    dc.delete_object(results[0])
    assert dc.is_null_object(results[-1])
    assert valid.serial in dc._live


def test_playback_reuses_failed_slots_without_leaking_backend_objects():
    recorder = Recorder()
    for _ in range(20):
        recorder.create_region(Region((0, 0, 0, 0), ()))
    dc = RasterContext(8, 8)
    dc.max_objects = 1
    assert play(recorder.metafile(), dc, strict=True) == ()
    assert not dc._live
    assert len(dc._objects) == 1


def test_null_handles_still_reject_wrong_owner_and_kind():
    dc = RasterContext(8, 8)
    other = RasterContext(8, 8)
    null = dc.create_region(Region((0, 0, 0, 0), ()))
    with pytest.raises(ValueError, match="Invalid"):
        other.select_object(null)
    with pytest.raises(ValueError, match="Wrong object type"):
        dc.select_palette(null)


@pytest.mark.parametrize("operation", ("fill_region", "frame_region"))
@pytest.mark.parametrize("mode", (1, 7, 13))
def test_failed_explicit_brush_never_falls_back_to_selected_brush(operation, mode):
    dc = RasterContext(8, 8)
    dc.select_object(dc.create_brush(0, 255, 0))
    region = dc.create_region(Region((0, 0, 8, 8), (Scan(0, 8, (0, 8)),)))
    failed = dc.create_pattern_brush(encode_bitmap16(1, 1, (1,), pattern=True))
    dc.set_rop2(mode)
    original = dc.image.tobytes()
    getattr(dc, operation)(region, failed, *((2, 2) if operation == "frame_region" else ()))
    assert dc.image.tobytes() == original
    assert dc._brush.color == (255, 0, 0)
    dc.set_rop2(13)
    dc.paint_region(region)
    assert dc.image.getpixel((0, 0)) == (255, 0, 0)
