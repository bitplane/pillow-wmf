from fractions import Fraction
from itertools import product
from math import ceil, floor
from random import Random

import pytest

from pillow_wmf import RasterContext
from pillow_wmf.clip import RegionMask
from pillow_wmf.mapping import Mapping
from pillow_wmf.stroke import frame_footprint
from pillow_wmf.wmf.objects import Region, Scan


def test_band_difference_matches_set_subtraction():
    random = Random(943)
    for _ in range(30):
        first, second = (
            RegionMask.from_rectangles(tuple(random.randrange(-8, 9) for _ in range(4)) for _ in range(5))
            for _ in range(2)
        )
        difference = first.difference(second)
        for x, y in product(range(-10, 11), repeat=2):
            assert difference.contains(x, y) == (first.contains(x, y) and not second.contains(x, y))


@pytest.mark.parametrize("width,height", ((1, 1), (2, 3), (8, 9), (Fraction(3, 2), Fraction(5, 2))))
def test_frame_is_complement_dilation_not_individual_rectangle_outlines(width, height):
    region = RegionMask.from_rectangles(((0, 0, 12, 4), (0, 4, 4, 12), (8, 4, 12, 12), (0, 12, 12, 16)))
    frame = region.frame(width, height)
    for x, y in product(range(-2, 19), repeat=2):
        interior = all(
            region.contains(x + dx, y + dy)
            for dx in range(-ceil(width), floor(width) + 1)
            for dy in range(-ceil(height), floor(height) + 1)
        )
        assert frame.contains(x, y) == (region.contains(x, y) and not interior)


@pytest.mark.parametrize("width,height", ((0, 0), (0, 2), (3, 0)))
def test_zero_frame_dimension_paints_nothing(width, height):
    assert not RegionMask.from_rectangles(((0, 0, 20, 20),)).frame(width, height).bands


@pytest.mark.parametrize("operation", ("fill_region", "frame_region", "paint_region", "invert_region"))
def test_region_paint_preserves_brush_and_clip(operation):
    context = RasterContext(32, 32)
    selected = context.create_brush(0, 0x000000FF, 0)
    explicit = context.create_brush(0, 0x0000FF00, 0)
    context.select_object(selected)
    region = context.create_region(Region((0, 0, 20, 20), (Scan(0, 20, (0, 20)),)))
    context.exclude_clip_rect(0, 0, 2, 32)
    clip = context._clip
    if operation in ("fill_region", "frame_region"):
        getattr(context, operation)(region, explicit, *((3, 4) if operation == "frame_region" else ()))
    else:
        getattr(context, operation)(region)
    assert context._brush.color == (255, 0, 0)
    assert context._clip == clip
    assert context.image.getpixel((1, 1)) == (255, 255, 255)
    assert (
        context.image.getpixel((2, 1))
        == {
            "fill_region": (0, 255, 0),
            "frame_region": (0, 255, 0),
            "paint_region": (255, 0, 0),
            "invert_region": (0, 0, 0),
        }[operation]
    )


@pytest.mark.parametrize("mode", range(1, 17))
def test_invert_region_ignores_brush_and_rop_without_changing_them(mode):
    context = RasterContext(8, 8)
    context.image.paste((17, 63, 129), (0, 0, 8, 8))
    context.select_object(context.create_brush(1, 0, 0))
    context.set_rop2(mode)
    region = context.create_region(Region((1, 1, 7, 7), (Scan(1, 7, (1, 7)),)))
    context.invert_region(region)
    assert context.image.getpixel((2, 2)) == (238, 192, 126)
    assert context.image.getpixel((0, 0)) == (17, 63, 129)
    assert context._rop2 == mode
    assert context._brush.style == 1


def test_frame_storage_depends_on_region_edges_not_surface_area():
    frame = RegionMask.from_rectangles(((-1000000, -1000000, 1000000, 1000000),)).frame(3, 7)
    assert len(frame.bands) == 3
    assert frame.contains(-1000000, 0)
    assert not frame.contains(0, 0)


@pytest.mark.parametrize(
    "width,height,sx,sy,expected",
    (
        (1, 1, 0.75, 1, (0.5, 1)),
        (3, 1, 0.75, 1, (2, 1)),
        (5, 1, 0.75, 1, (4, 1)),
        (5, 1, -0.75, 1, (3.5, 1)),
        (17, 1, 43 / 128, 1, (6, 1)),
        (5, 7, 43 / 128, 77 / 128, (1.5, 4.5)),
        (5, 9, -0.75, 1.125, (3.5, 10)),
        (5, 9, 0.75, 1.125, (4, 10)),
    ),
)
def test_native_frame_footprint_quantization(width, height, sx, sy, expected):
    assert frame_footprint(width, height, sx, sy) == expected
    assert frame_footprint(-width, -height, sx, sy) == expected


def test_collapsed_geometric_frame_terminates():
    assert frame_footprint(1, 2, 1 / 32767, 1 / 32767) == (0, 0)


def test_clip_rectangle_edges_round_through_fixed_point():
    mapping = Mapping(window_origin=(1, -3), viewport_origin=(7, 9), viewport_extent=(43, 77))
    assert mapping.point(17, 51) == (12, 41)
    assert mapping.clip_point(17, 51) == (12, 42)


def test_collapsed_gap_retains_seam_without_extending_its_ends():
    region = RegionMask.from_rectangles(((0, 0, 4, 10), (5, 0, 12, 10), (0, 10, 12, 14)))

    def point(x, y):
        return x // 2, y

    frame = region.frame(1, 2, point=point)
    assert frame.contains(2, 5)
    assert not frame.contains(2, 10)
    assert not region.transformed(point).frame(1, 2).contains(2, 5)


def test_mirrored_small_frame_uses_realized_contour_orientation():
    assert frame_footprint(1, 1, -0.5, 0.5) == (0.5, 0.5)


@pytest.mark.parametrize("mode,color", ((1, (0, 0, 0)), (6, (238, 192, 126)), (16, (255, 255, 255))))
@pytest.mark.parametrize("operation", ("rectangle", "paint_region"))
def test_constant_rop_block_fill_and_masked_region_fill(mode, color, operation):
    context = RasterContext(8, 8)
    context.image.paste((17, 63, 129), (0, 0, 8, 8))
    context.select_object(context.create_pen(5, 0, 0))
    context.select_object(context.create_brush(2, 0x00123456, 4))
    context.set_background_mode(1)
    context.set_rop2(mode)
    if operation == "rectangle":
        context.rectangle(0, 0, 8, 8)
    else:
        context.paint_region(context.create_region(Region((0, 0, 8, 8), (Scan(0, 8, (0, 8)),))))
    for x, y in product(range(1, 7), repeat=2):
        covered = operation == "rectangle" or x % 8 == 4 or y % 8 == 3
        assert context.image.getpixel((x, y)) == (color if covered else (17, 63, 129))
