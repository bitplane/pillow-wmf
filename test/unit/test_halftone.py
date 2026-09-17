from itertools import product

import pytest

from pillow_wmf import RasterContext, UnsupportedOperation
from pillow_wmf.bitmap import RGBBitmap, encode_dib24
from pillow_wmf.blit import StretchAxis
from pillow_wmf.halftone import (
    ExpansionAxis,
    HalftoneExpansion,
    HalftoneMode,
    HalftoneReduction,
    RunExpansionAxis,
    area_weights,
    halftone_bitmap,
    replication_candidate,
    replication_content,
)
from pillow_wmf.halftone_power import tent_power
from pillow_wmf.halftone_scan import ExpansionWindow, ReductionScanReader


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


@pytest.mark.parametrize("size", ((4, 2), (2, 4), (0, 2)))
def test_reduction_view_requires_positive_non_enlarging_dimensions(size):
    with pytest.raises(UnsupportedOperation, match="HALFTONE"):
        HalftoneReduction(RGBBitmap(3, 3, bytes(27)), 0, 0, 3, 3, *size)


def test_source_clipping_retains_fractional_coverage_and_black_unavailable_cells():
    view = HalftoneReduction(RGBBitmap(11, 9, bytes((17, 128, 255)) * 99), -3, -2, 11, 9, 5, 3)
    assert (view.left, view.top, view.right, view.bottom) == (1, 0, 5, 3)
    assert view.pixel(0, 0) == (0, 0, 0)
    assert view.pixel(1, 0) == (17, 128, 255)


@pytest.mark.parametrize("x,y", ((1, 0), (0, 1), (-2, 0), (0, -2), (9, 9)))
@pytest.mark.parametrize("width,height", ((1, 1), (2, 2), (3, 3), (1, 3), (13, 13), (1_000_000_000, 1)))
def test_factory_rejects_unavailable_source_before_classification(x, y, width, height):
    class UnreadableBitmap:
        width = height = 1

        def pixel(self, x, y):
            pytest.fail("An unavailable source must not be sampled or classified")

    view = halftone_bitmap(UnreadableBitmap(), x, y, 2, 2, width, height)
    assert view is HalftoneMode.NOOP


def test_reduction_closing_cell_does_not_imply_physical_source_availability():
    bitmap = RGBBitmap(1, 1, bytes((31, 71, 113)))
    view = HalftoneReduction(bitmap, 0, 1, 1, 2, 1, 1)
    assert (view.left, view.top, view.right, view.bottom) == (0, 0, 1, 1)
    assert not view.valid
    assert view.pixel(0, 0) == (0, 0, 0)


def test_clipped_general_expansion_freezes_fetch_window_not_fractional_phase():
    full = ExpansionAxis(11, 13)
    clipped = ExpansionWindow(3)
    assert clipped.fetch(full.weights(2)) == ((2, 231), (1, 4843), (0, 3025), (None, 93))
    assert [w for _, w in clipped.fetch(full.weights(2))] == [w for _, w in full.weights(2)]
    assert clipped.fetch(full.weights(3)) != clipped.fetch(full.weights(2))


@pytest.mark.parametrize("rows", (1, 2, 3))
@pytest.mark.parametrize("fixup", (False, True))
def test_scan_reader_priming_and_replay_are_independent_of_access_order(rows, fixup):
    bitmap = RGBBitmap(1, rows, bytes((31, 71, 113)) * rows)
    reader = ReductionScanReader(bitmap, 0, -1, 4, 3, fixup=fixup)
    assert reader.current == (2 if rows > 1 else 1)
    assert reader.previous == (1 if rows > 1 else None)
    expected = None if fixup and rows == 1 else 1
    assert reader.row(1) == expected
    assert reader.row(3) == 3
    assert reader.row(1) == expected
    assert reader.pixel(0, reader.row(1)) == ((0, 0, 0) if expected is None else (31, 71, 113))


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


def test_large_constant_image_is_classified_for_replication():
    bitmap = RGBBitmap(49, 49, bytes(49 * 49 * 3))
    assert halftone_bitmap(bitmap, 0, 0, 49, 49, 50, 50) is HalftoneMode.REPLICATE


@pytest.mark.parametrize("colours,replicate", ((19, True), (20, False), (21, False)))
def test_sampled_classifier_has_a_strict_twenty_colour_boundary(colours, replicate):
    bitmap = RGBBitmap(129, 129, bytes(c for y in range(129) for x in range(129) for c in (x % colours, 71, 113)))
    assert replication_content(bitmap, 0, 0, 129, 129) == replicate


def test_replication_ties_and_reflection_are_output_addressed():
    forward = StretchAxis.create(0, 13, 0, 6, 6)
    reverse = StretchAxis.create(12, -13, 0, 6, 6)
    values = [tuple(forward.samples(i, 4)) for i in range(13)]
    assert values[6] == (2,)
    assert [tuple(reverse.samples(i, 4)) for i in range(13)] == values[::-1]


def test_halftone_clipped_reduction_retains_last_available_scan_in_run():
    axis = StretchAxis.create(0, 7, 7, 9, 9)
    assert [tuple(axis.samples(i, 4)) for i in range(3)] == [(7,), (8,), ()]


@pytest.mark.parametrize(
    "source,destination,expected",
    (
        (3, 2, (0, 23, 47)),
        (4, 3, (0, 17, 35)),
        (5, 2, (0, 71, 142)),
        (5, 3, (0, 28, 56)),
        (6, 4, (0, 23, 47)),
        (7, 4, (0, 71, 142)),
        (7, 5, (0, 20, 40)),
        (10000, 9999, (0, 71, 142)),  # Prefill quantizes to zero: no replay.
    ),
)
def test_area_override_preserves_fixup_reader_replay_state(source, destination, expected):
    bitmap = RGBBitmap(3, 7, bytes((0, 71, 142)) * 21)
    view = halftone_bitmap(bitmap, 0, 1 - source, 3, source, 3, destination)
    assert isinstance(view, HalftoneReduction)
    assert view.pixel(0, destination - 1) == expected


def test_vertical_closing_scan_emits_the_exact_boundary_cell():
    bitmap = RGBBitmap(1, 7, bytes((y * 53 + c * 71) % 256 for y in range(7) for c in range(3)))
    view = halftone_bitmap(bitmap, 0, 5, 1, 4, 1, 2)
    assert (view.top, view.bottom) == (0, 2)
    assert view.pixel(0, 0) == (28, 99, 170)
    assert view.pixel(0, 1) == (68, 139, 210)


def test_fast_run_stencils_partition_the_integer_replication_runs():
    for source in range(1, 17):
        for destination in range(source + 1, source * 5 + 1):
            axis = RunExpansionAxis(source, destination)
            for index in range(destination):
                weights = axis.weights(index)
                assert sum(w for _, w in weights) == 8192
                assert len(weights) == 3
                assert all(-1 <= scan <= source and w >= 0 for scan, w in weights)


def test_excessive_tap_allocation_is_rejected():
    with pytest.raises(UnsupportedOperation, match="tap limit"):
        ExpansionAxis(1, 1_000_000_000)
