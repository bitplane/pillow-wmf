from itertools import product

import pytest

from pillow_wmf import RasterContext, UnsupportedOperation
from pillow_wmf.bitmap import RGBBitmap, encode_dib24
from pillow_wmf.blit import StretchAxis
from pillow_wmf.halftone import (
    ExpansionAxis,
    HalftoneExpansion,
    HalftoneReduction,
    area_weights,
    halftone_bitmap,
    replication_candidate,
)
from pillow_wmf.halftone_power import tent_power


def test_weights_carry_remainders_between_source_contributions():
    assert list(area_weights(9, 5, 0)) == [(0, 4551), (1, 3641)]
    assert list(area_weights(9, 5, 1)) == [(1, 910), (2, 4551), (3, 2731)]


def test_weights_partition_every_destination_cell_exactly():
    for source in range(1, 33):
        for destination in range(1, source + 1):
            for index in range(destination):
                weights = list(area_weights(source, destination, index))
                assert sum(weight for _, weight in weights) == 8192
                assert all(0 <= scan < source and weight >= 0 for scan, weight in weights)


def test_fractional_accumulators_survive_until_sharpening():
    bitmap = RGBBitmap(3, 1, bytes((0, 0, 0, 255, 255, 255, 0, 0, 0)))
    view = HalftoneReduction(bitmap, 0, 0, 3, 1, 2, 1)
    assert view.pixel(0, 0) == (85, 85, 85)
    assert view.pixel(1, 0) == (84, 84, 84)


@pytest.mark.parametrize("width,height", tuple(product((1, 2, 3), repeat=2)))
def test_constants_survive_all_reduction_directions(width, height):
    bitmap = RGBBitmap(3, 3, bytes((17, 128, 255)) * 9)
    view = HalftoneReduction(bitmap, 0, 0, 3, 3, width, height)
    assert all(view.pixel(x, y) == (17, 128, 255) for y in range(height) for x in range(width))


@pytest.mark.parametrize("rectangle,size", (((-1, 0, 3, 3), (2, 2)), ((0, 0, 4, 3), (2, 2)), ((0, 0, 3, 3), (4, 2))))
def test_uncharacterized_geometry_is_explicitly_rejected(rectangle, size):
    with pytest.raises(UnsupportedOperation, match="HALFTONE"):
        HalftoneReduction(RGBBitmap(3, 3, bytes(27)), *rectangle, *size)


def test_destination_clipping_retains_filter_phase_and_neighbours():
    source = encode_dib24(RGBBitmap(9, 9, bytes((i * 37) % 256 for i in range(243))))
    whole = RasterContext(5, 5)
    clipped = RasterContext(3, 3)
    for context, origin in ((whole, 0), (clipped, -1)):
        context.set_stretch_mode(4)
        context.dib_stretch_blt(origin, origin, 5, 5, 0, 0, 9, 9, 0xCC0020, source)
    assert clipped.image.tobytes() == whole.image.crop((1, 1, 4, 4)).tobytes()


def test_lazy_view_does_not_allocate_an_intermediate_surface():
    bitmap = RGBBitmap(1, 3000, bytes((23, 45, 67)) * 3000)
    view = HalftoneReduction(bitmap, 0, 0, 1, 3000, 1, 2999)
    for y in range(view.height):
        assert view.pixel(0, y) == (23, 45, 67)
    assert view.area.cache_info().currsize <= 2048
    assert view.horizontal.cache_info().currsize <= 2048


@pytest.mark.parametrize(
    "value,expected",
    (
        (0, 0),
        (1, 1),
        (20, 1),
        (123456, 51904),
        (250000, 140785),
        (499999, 375213),
        (500000, 500000),
        (500001, 612548),
        (750000, 815934),
        (999999, 1000000),
        (1000000, 1000000),
    ),
)
def test_native_fixed_decimal_tent_power(value, expected):
    # Independently checked against the native RaisePower helper. In
    # particular, neither side of 1/2 is continuous with the exact-half branch.
    assert tent_power(value) == expected


@pytest.mark.parametrize(
    "sw,sh,width,height,replicate",
    ((3, 2, 17, 1, True), (9, 2, 17, 1, False), (9, 2, 61, 1, True), (3, 3, 17, 1, False), (7, 9, 5, 13, True)),
)
def test_native_replication_dispatch(sw, sh, width, height, replicate):
    assert replication_candidate(sw, sh, width, height) == replicate


def test_halftone_replication_reduces_by_inverse_run_end_not_centre():
    axis = StretchAxis.create(0, 5, 0, 7, 7)
    assert [tuple(axis.samples(i, 4)) for i in range(5)] == [(0,), (2,), (3,), (5,), (6,)]
    for source in range(2, 25):
        for destination in range(1, source):
            axis = StretchAxis.create(0, destination, 0, source, source)
            inverse = [(2 * i + 1) * destination // (2 * source) for i in range(source)]
            assert [next(iter(axis.samples(i, 4))) for i in range(destination)] == [
                max(k for k, value in enumerate(inverse) if value == i) for i in range(destination)
            ]


def test_expansion_weights_are_normalized_and_have_bounded_support():
    for source, destination in ((2, 3), (3, 17), (9, 13), (9, 17), (2, 113)):
        axis = ExpansionAxis(source, destination)
        for index in range(destination):
            weights = axis.weights(index)
            assert sum(w for _, w in weights) == 8192
            assert len(weights) <= 4
            assert all(0 <= i < source and w >= 0 for i, w in weights)


def test_source_sharpening_saturates_before_expansion():
    bitmap = RGBBitmap(3, 1, bytes((64, 64, 64, 192, 192, 192, 64, 64, 64)))
    view = HalftoneExpansion(bitmap, 17, 1)
    assert [view.sharp(i, 0) for i in range(3)] == [(32, 32, 32), (255, 255, 255), (32, 32, 32)]


def test_unresolved_large_image_classifier_is_not_assumed_to_replicate():
    bitmap = RGBBitmap(49, 49, bytes(49 * 49 * 3))
    with pytest.raises(UnsupportedOperation, match="classification"):
        halftone_bitmap(bitmap, 0, 0, 49, 49, 50, 50)


def test_excessive_tap_allocation_is_rejected():
    with pytest.raises(UnsupportedOperation, match="tap limit"):
        ExpansionAxis(1, 1_000_000_000)
