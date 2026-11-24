"""The surface owns device pixels; clipping and raster operations stay with the painter."""

import random

import pytest

from pillow_wmf import RasterContext
from pillow_wmf.clip import ClipRegion, RegionMask
from pillow_wmf.constants import R2_COPYPEN, R2_NOT
from pillow_wmf.mapping import Mapping
from pillow_wmf.raster_paint import RasterPainter
from pillow_wmf.raster_state import DrawingState
from pillow_wmf.surface import Surface

R2_XORPEN = 7


def _clips():
    generator = random.Random(7)

    def rectangle():
        x0, x1 = sorted(generator.randint(-4, 20) for _ in range(2))
        y0, y1 = sorted(generator.randint(-4, 12) for _ in range(2))
        return x0, y0, x1, y1

    yield ClipRegion()
    yield ClipRegion(RegionMask())
    for _ in range(40):
        clip = (
            ClipRegion(RegionMask.from_rectangles(rectangle() for _ in range(3)))
            if generator.random() < 0.5
            else ClipRegion()
        )
        for _ in range(generator.randint(0, 4)):
            clip = clip.exclude(rectangle()) if generator.random() < 0.6 else clip.intersect(rectangle())
        yield clip


def test_surface_rejects_empty_canvas():
    with pytest.raises(ValueError, match="dimensions must be positive"):
        Surface(0, 4)


def test_context_image_is_the_surface_canvas():
    context = RasterContext(6, 3, background=(1, 2, 3))
    assert context.image is context.surface.image
    assert (context.surface.width, context.surface.height) == (6, 3)


def test_fill_span_is_half_open_and_snapshot_is_detached():
    surface = Surface(5, 2, background=(0, 0, 0))
    surface.fill_span(1, 1, 4, (9, 8, 7))
    snapshot = surface.snapshot()
    surface.fill_span(1, 0, 5, (1, 1, 1))
    assert [snapshot.pixel(x, 1) for x in range(5)] == [(0, 0, 0), (9, 8, 7), (9, 8, 7), (9, 8, 7), (0, 0, 0)]
    assert [snapshot.pixel(x, 0) for x in range(5)] == [(0, 0, 0)] * 5


def test_clip_spans_cover_exactly_the_contained_pixels():
    for clip in _clips():
        for y in range(-2, 10):
            for start, end in ((-3, 18), (2, 9), (5, 5), (9, 2)):
                covered = [x for left, right in clip.spans(y, start, end) for x in range(left, right)]
                assert covered == [x for x in range(start, end) if clip.contains(x, y)]


@pytest.mark.parametrize("operation", [R2_COPYPEN, R2_NOT, R2_XORPEN, None])
def test_painter_span_matches_per_pixel_painting(operation):
    for clip in _clips():
        painters = []
        for _ in range(2):
            state = DrawingState(Mapping(), clip=clip, rop2=R2_XORPEN)
            painters.append(RasterPainter(Surface(16, 8, background=(40, 80, 120)), state))
        by_span, by_pixel = painters
        for y in range(-1, 9):
            by_span.span(y, -3, 19, (200, 10, 60), operation=operation)
            for x in range(-3, 19):
                by_pixel.pixel(x, y, (200, 10, 60), operation=operation)
        assert by_span.surface.image.tobytes() == by_pixel.surface.image.tobytes()


def test_two_painters_share_one_surface():
    surface = Surface(4, 1, background=(0, 0, 0))
    first = RasterPainter(surface, DrawingState(Mapping()))
    second = RasterPainter(surface, DrawingState(Mapping(), clip=ClipRegion().exclude((0, 0, 2, 1))))
    first.span(0, 0, 4, (5, 5, 5))
    second.span(0, 0, 4, (9, 9, 9))
    assert list(surface.image.get_flattened_data()) == [(5, 5, 5), (5, 5, 5), (9, 9, 9), (9, 9, 9)]
