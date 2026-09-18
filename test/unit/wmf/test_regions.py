import pytest

from pillow_wmf import Metafile, RasterContext, Recorder, play
from pillow_wmf.clip import ClipRegion, RegionMask
from pillow_wmf.wmf import fixed, variable
from pillow_wmf.wmf.objects import Region, Scan


def test_band_union_and_half_open_edges():
    rectangles = ((-10, -4, 8, 8), (0, 0, 12, 12), (12, 0, 20, 12), (3, 3, 3, 7))
    mask = RegionMask.from_rectangles(rectangles)
    assert mask.bands == ((-4, 0, (-10, 8)), (0, 8, (-10, 20)), (8, 12, (0, 20)))
    for x in range(-12, 23):
        for y in range(-6, 15):
            assert mask.contains(x, y) == any(
                left <= x < right and top <= y < bottom for left, top, right, bottom in rectangles
            )


def test_region_clip_preserves_off_surface_data_and_constraints():
    clip = ClipRegion(mask=RegionMask.from_rectangles(((-100, -100, -20, -20),)))
    clip = clip.exclude((-90, -90, -80, -80)).intersect((-95, -95, -40, -40))
    moved = clip.offset(100, 100)
    assert moved.contains(5, 5)
    assert not moved.contains(10, 10)
    assert not moved.contains(60, 60)
    assert clip.contains(-95, -95)


def test_finite_clip_spans_match_membership_without_changing_application_clip():
    clip = ClipRegion(mask=RegionMask.from_rectangles(((-4, -3, 8, 7), (10, 1, 14, 9))))
    clip = clip.intersect((-2, -1, 12, 8)).exclude((3, 2, 5, 6))
    bounded = clip.within((0, 0, 11, 8))
    for y in range(-5, 12):
        spans = tuple(bounded.spans(y))
        for x in range(-5, 16):
            expected = 0 <= x < 11 and 0 <= y < 8 and clip.contains(x, y)
            assert any(left <= x < right for left, right in spans) == expected
    assert clip.contains(-1, -1)


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
    handle = context.create_region(Region((0, 0, 0, 0), (Scan(0, 0, (0, 0)),)))
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


def test_zero_scan_wmf_region_is_a_null_object_not_an_empty_region():
    context = RasterContext(8, 8)
    context.exclude_clip_rect(0, 0, 8, 8)
    handle = context.create_region(Region((0, 0, 0, 0), ()))
    context.select_object(handle)
    assert not context._clip.contains(1, 1)
    context.select_clip_region(handle)
    assert context._clip.contains(1, 1)


def test_failed_region_creation_does_not_occupy_native_file_slot():
    file = Metafile.build(
        [
            fixed.CreatePenIndirect(5, 1, 0, 0),
            fixed.SelectObject(0),
            variable.CreateRegion(Region((0, 0, 0, 0), ())),
            fixed.CreateBrushIndirect(0, 0x00CC8844, 0),
            fixed.SelectObject(1),
            fixed.Rectangle(1, 1, 7, 7),
        ]
    )
    context = RasterContext(8, 8)
    assert play(file, context, strict=True) == ()
    assert context.image.getpixel((3, 3)) == (68, 136, 204)


@pytest.mark.parametrize(
    "delta,expected", (((7, -9), (11, -5)), ((-7, 9), (-11, 5)), ((1, 1), (2, 1)), ((-1, -1), (-2, -1)))
)
def test_clip_offset_half_ties_are_symmetric(delta, expected):
    context = RasterContext(128, 128)
    context.set_viewport_extent(192, 64)
    assert context.mapping.clip_displacement(*delta) == expected
