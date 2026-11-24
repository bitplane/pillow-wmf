"""Row-run polygon coverage is exactly the per-pixel ``contains`` predicate."""

import random
import tracemalloc

import pytest

from pillow_wmf import RasterContext
from pillow_wmf.geometry import contains, coverage_spans


def _pixels(polygons, bounds, fill_mode):
    pixels = []
    for y, start, end in coverage_spans(polygons, *bounds, fill_mode=fill_mode):
        pixels.extend((x, y) for x in range(start, end))
    return pixels


def _reference(polygons, bounds, fill_mode):
    left, top, right, bottom = bounds
    return [
        (x, y) for y in range(top, bottom) for x in range(left, right) if contains(polygons, x, y, fill_mode=fill_mode)
    ]


@pytest.mark.parametrize("seed", range(40))
def test_spans_match_per_pixel_predicate(seed):
    generator = random.Random(seed)
    size = generator.choice((16, 24))
    polygons = tuple(
        [(generator.randint(-64, size * 16 + 64), generator.randint(-64, size * 16 + 64)) for _ in range(count)]
        for count in (generator.randint(1, 9) for _ in range(generator.randint(1, 3)))
    )
    bounds = (generator.randint(-2, 6), generator.randint(-2, 6), size, size)
    for fill_mode in (1, 2):
        assert _pixels(polygons, bounds, fill_mode) == _reference(polygons, bounds, fill_mode)


@pytest.mark.parametrize(
    "polygon",
    [
        # Vertices and edges exactly on sample rows and columns.
        [(0, 0), (64, 0), (64, 64), (0, 64)],
        [(16, 0), (48, 32), (16, 64), (-16, 32)],
        # Collinear, repeated and horizontal edges.
        [(0, 0), (32, 0), (32, 0), (64, 0), (64, 48), (32, 48), (0, 48)],
        # Self-intersecting figure whose fill modes differ.
        [(0, 0), (96, 0), (96, 96), (32, 96), (32, 32), (64, 32), (64, 64), (0, 64)],
        # Degenerate figures.
        [(8, 8)],
        [(0, 0), (80, 80)],
        [],
    ],
)
def test_spans_match_boundary_cases(polygon):
    bounds = (0, 0, 8, 8)
    for fill_mode in (1, 2):
        assert _pixels((polygon,), bounds, fill_mode) == _reference((polygon,), bounds, fill_mode)


def test_spans_are_ordered_merged_and_bounded():
    # Two overlapping same-direction squares: nonzero winding merges them.
    polygons = ([(0, 0), (64, 0), (64, 64), (0, 64)], [(48, 0), (160, 0), (160, 64), (48, 64)])
    assert list(coverage_spans(polygons, 2, 0, 8, 12, fill_mode=2)) == [(y, 2, 8) for y in range(4)]
    # Alternate mode leaves the overlap as a hole between two runs.
    assert list(coverage_spans(polygons, 0, 0, 12, 1)) == [(0, 0, 3), (0, 4, 10)]
    assert list(coverage_spans(polygons, 8, 0, 8, 12)) == []


def test_large_fill_does_not_materialize_pixel_sets():
    # Fill coverage is held as row runs, not one Python tuple per pixel.
    context = RasterContext(512, 512, trace_calls=False)
    tracemalloc.start()
    try:
        context.rectangle(0, 0, 512, 512)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert context.image.getpixel((256, 256)) == (255, 255, 255)
    assert context.image.getpixel((0, 0)) == (0, 0, 0)
    assert peak < 4 * 1024 * 1024
