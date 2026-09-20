from itertools import product

import pytest

from pillow_wmf import FormatError, RasterContext
from pillow_wmf.bitmap import RGBBitmap, encode_dib24, read_dib24
from pillow_wmf.blit import BlitAxis, StretchAxis
from pillow_wmf.raster import SourceTransfer, TransferAction
from pillow_wmf.wmf.objects import BitmapData


@pytest.mark.parametrize(
    "destination,extent,source,source_extent,expected",
    (
        (12, 7, 8, 7, BlitAxis(12, 8, 3)),
        (12, -7, 8, -7, BlitAxis(6, 2, 7)),
        (12, -7, 8, 7, BlitAxis(6, 10, 3, -1)),
        (12, -7, -3, 7, BlitAxis(9, 3, 4, -1)),
        (12, 7, 8, -7, BlitAxis(12, 8, 7, -1)),
        (12, 0, 0, 0, BlitAxis(12, 0, 0)),
    ),
)
def test_unscaled_axis(destination, extent, source, source_extent, expected):
    assert BlitAxis.unscaled(destination, extent, source, source_extent, 11) == expected


def test_axis_source_clipping_is_bounded_for_both_directions():
    for source, extent, mirror in product(range(-16, 17), range(-12, 13), (-1, 1)):
        axis = BlitAxis.unscaled(17, extent * mirror, source, extent, 11)
        assert 0 <= axis.length <= min(11, abs(extent))
        assert all(0 <= axis.source + i * axis.step < 11 for i in range(axis.length))


def test_ternary_axis_uses_half_open_edges_without_an_anchor_correction():
    assert BlitAxis.unscaled(12, -7, 8, -7, 11, anchor_pixel=False) == BlitAxis(5, 1, 7)


@pytest.mark.parametrize("top_down", (False, True))
def test_reflected_ternary_transfer_composes_black_outside_realized_source(top_down):
    context = RasterContext(4, 1, background=(10, 20, 30))
    context.set_window_extent(1, 1)
    context.set_viewport_extent(-1, 1)
    context.set_viewport_origin(3, 0)
    source = encode_dib24(RGBBitmap(1, 1, bytes((10, 20, 30))), top_down=top_down)
    context.dib_bit_blt(0, 0, 3, 1, 0, 0, 0x330008, source)  # NOTSRCCOPY
    assert list(context.image.get_flattened_data()) == [(10, 20, 30), (245, 235, 225), (255, 255, 255), (255, 255, 255)]


@pytest.mark.parametrize("top_down", (False, True))
def test_dib_blt_source_coordinates_are_top_left(top_down):
    source = RGBBitmap(2, 3, bytes(range(18)))
    context = RasterContext(8, 8)
    context.dib_bit_blt(2, 3, 2, 2, 0, 1, 0xCC0020, encode_dib24(source, top_down=top_down))
    assert context.image.getpixel((2, 3)) == (6, 7, 8)
    assert context.image.getpixel((3, 4)) == (15, 16, 17)
    assert context.image.getpixel((2, 5)) == (255, 255, 255)


def test_all_rop3_tables_ignore_dc_rop2_and_low_code_word():
    source = encode_dib24(RGBBitmap(1, 1, bytes((0x36, 0x79, 0xAB))))
    p, s, d = (0xA5, 0xC3, 0x17), (0x36, 0x79, 0xAB), (0x63, 0x9C, 0xE8)
    for table in range(256):
        context = RasterContext(1, 1, background=d)
        context.select_object(context.create_brush(0, 0x17C3A5, 0))
        context.set_rop2(7)
        context.dib_bit_blt(0, 0, 1, 1, 0, 0, table << 16 | 0xFFFF, source)
        expected = tuple(
            sum(
                ((table >> (((pc >> bit & 1) << 2) | ((sc >> bit & 1) << 1) | (dc >> bit & 1))) & 1) << bit
                for bit in range(8)
            )
            for pc, sc, dc in zip(p, s, d, strict=True)
        )
        assert context.image.getpixel((0, 0)) == expected


def test_null_brush_only_rejects_pattern_dependent_rops():
    context = RasterContext(2, 1)
    context.select_object(context.create_brush(1, 0, 0))
    source = encode_dib24(RGBBitmap(1, 1, bytes((12, 34, 56))))
    context.dib_bit_blt(0, 0, 1, 1, 0, 0, 0xCC0020, source)
    context.dib_bit_blt(1, 0, 1, 1, 0, 0, 0xFC0000, source)
    assert list(context.image.get_flattened_data()) == [(12, 34, 56), (255, 255, 255)]


def test_missing_dib_is_patblt_not_a_self_copy():
    context = RasterContext(3, 1)
    context.select_object(context.create_brush(0, 0x332211, 0))
    context.dib_bit_blt(0, 0, 1, 1, 99, 99, 0xF00021)
    context.dib_bit_blt(1, 0, 1, 1, 0, 0, 0xCC0020)
    assert list(context.image.get_flattened_data()) == [(17, 34, 51), (255, 255, 255), (255, 255, 255)]


@pytest.mark.parametrize(
    "changes,expected",
    (
        ({"source": None}, TransferAction.NOOP),
        ({"source": None, "rop": 0xF00021}, TransferAction.PATTERN),
        ({"rop": 0xF00021}, TransferAction.PATTERN),
        ({"width": 0}, TransferAction.NOOP),
        ({"src_x": 2}, TransferAction.NOOP),
    ),
)
def test_transfer_preparation_distinguishes_pattern_from_noop(changes, expected):
    context = RasterContext(3, 3)
    context.set_stretch_mode(4)
    args = {
        "x": 0,
        "y": 0,
        "width": 1,
        "height": 1,
        "src_x": 0,
        "src_y": 0,
        "src_width": 2,
        "src_height": 2,
        "rop": 0xCC0020,
        "source": encode_dib24(RGBBitmap(2, 2, bytes(12))),
    }
    assert context._prepare_transfer("dib_stretch_blt", args | changes) is expected


def test_replication_prepares_a_source_transfer_not_a_noop():
    context = RasterContext(3, 3)
    context.set_stretch_mode(4)
    args = {
        "x": 0,
        "y": 0,
        "width": 3,
        "height": 3,
        "src_x": 0,
        "src_y": 0,
        "src_width": 2,
        "src_height": 2,
        "rop": 0xCC0020,
        "source": encode_dib24(RGBBitmap(2, 2, bytes(12))),
    }
    transfer = context._prepare_transfer("dib_stretch_blt", args)
    assert isinstance(transfer, SourceTransfer)
    assert isinstance(transfer.bitmap, RGBBitmap)
    assert isinstance(transfer.horizontal, StretchAxis)


def test_source_noop_does_not_fall_through_to_pattern_renderer(monkeypatch):
    context = RasterContext(3, 3)

    def unexpected_pattern(*args, **kwargs):
        pytest.fail("Source no-op dispatched to PatBlt")

    monkeypatch.setattr(context, "_pat_blt", unexpected_pattern)
    context.dib_bit_blt(0, 0, 1, 1, 0, 0, 0xCC0020)
    assert context.calls[-1].name == "dib_bit_blt"


@pytest.mark.parametrize("top_down", (False, True))
def test_band_positions_buffer_without_skipping_bytes(top_down):
    source = encode_dib24(RGBBitmap(1, 4, bytes(range(12))), top_down=top_down)
    context = RasterContext(1, 4)
    context.set_dib_to_device(0, 0, 1, 4, 0, 0, 1, 1, 0, source)
    pixels = list(context.image.get_flattened_data())
    assert pixels == [(255, 255, 255), (255, 255, 255), (0, 1, 2) if top_down else (9, 10, 11), (255, 255, 255)]


def test_device_transfer_maps_origin_but_not_dimensions_or_source():
    context = RasterContext(16, 16)
    context.set_window_extent(1, 1)
    context.set_viewport_extent(-3, 2)
    context.set_viewport_origin(12, 1)
    context.set_rop2(7)
    source = encode_dib24(RGBBitmap(2, 1, bytes((1, 2, 3, 4, 5, 6))))
    context.set_dib_to_device(2, 3, 2, 1, 0, 0, 0, 1, 0, source)
    assert context.image.getpixel((6, 7)) == (1, 2, 3)
    assert context.image.getpixel((7, 7)) == (4, 5, 6)
    assert sum(p != (255, 255, 255) for p in context.image.get_flattened_data()) == 2


def test_band_decoder_checks_requested_buffer_and_header_budget():
    source = encode_dib24(RGBBitmap(1, 4, bytes(range(12))))
    band = BitmapData("dib", source.data[:44])
    layout = read_dib24(band)
    assert layout.decode(1).pixel(0, 0) == (9, 10, 11)
    with pytest.raises(FormatError, match="Truncated"):
        layout.decode(2)
    with pytest.raises(FormatError, match="limit"):
        read_dib24(band, max_pixels=3)
    for rows in (0, -1, 5):
        with pytest.raises(ValueError):
            layout.decode(rows)


@pytest.mark.parametrize("operation", ("dib_bit_blt", "set_dib_to_device"))
def test_invalid_transfer_does_not_commit_or_modify_image(operation):
    source = encode_dib24(RGBBitmap(1, 1, bytes((1, 2, 3))))
    source = BitmapData("dib", source.data[:39])
    context = RasterContext(2, 2)
    from pillow_wmf import UnsupportedOperation

    with pytest.raises(UnsupportedOperation, match="Truncated"):
        if operation == "dib_bit_blt":
            context.dib_bit_blt(0, 0, 1, 1, 0, 0, 0xCC0020, source)
        else:
            context.set_dib_to_device(0, 0, 1, 1, 0, 0, 0, 1, 0, source)
    assert context.calls == []
    assert set(context.image.get_flattened_data()) == {(255, 255, 255)}


def test_wmf_device_transfer_rejects_short_packed_image_even_with_complete_band():
    source = encode_dib24(RGBBitmap(1, 4, bytes(range(12))))
    context = RasterContext(1, 4)
    context.set_dib_to_device(0, 0, 1, 4, 0, 0, 1, 1, 0, BitmapData("dib", source.data[:44]))
    assert len(context.calls) == 1  # Failed native drawing still appears in the trace.
    assert set(context.image.get_flattened_data()) == {(255, 255, 255)}


def test_fully_unavailable_halftone_source_is_a_recorded_noop():
    context = RasterContext(8, 8)
    context.set_window_extent(2, 2)
    context.set_viewport_extent(1, 1)
    context.set_stretch_mode(4)
    before = list(context.calls)
    context.dib_bit_blt(0, 0, 3, 3, -4, -4, 0xCC0020, encode_dib24(RGBBitmap(3, 3, bytes(27))))
    assert context.calls[:-1] == before
    assert context.calls[-1].name == "dib_bit_blt"
    assert set(context.image.get_flattened_data()) == {(255, 255, 255)}


@pytest.mark.parametrize(
    "source,destination,expected",
    (
        (2, 5, (0, 0, 1, 1, 1)),
        (7, 5, (0, 2, 3, 4, 6)),
        (11, 2, (2, 8)),
        (9, 1, (4,)),
    ),
)
def test_stretch_centre_phase(source, destination, expected):
    axis = StretchAxis.create(0, destination, 0, source, source)
    assert tuple(next(iter(axis.samples(x, 3))) for x in range(destination)) == expected


def test_and_or_reduce_through_chosen_scan_not_an_area_box():
    axis = StretchAxis.create(0, 2, 0, 9, 9)
    assert tuple(axis.samples(0, 1)) == (0, 1, 2)
    assert tuple(axis.samples(1, 2)) == (3, 4, 5, 6)
    # Trailing scans 7 and 8 are not part of either destination sample.


def test_mirror_follows_source_clipping_without_restarting_dda():
    axis = StretchAxis.create(0, 13, 3, -7, 11)
    assert [tuple(axis.samples(x, 3)) for x in range(13)] == [
        (),
        (),
        (),
        (),
        (),
        (),
        (3,),
        (2,),
        (2,),
        (1,),
        (1,),
        (0,),
        (0,),
    ]


def test_reduction_clips_work_to_bitmap_and_requires_selected_scan():
    axis = StretchAxis.create(0, 1, -16000, 32001, 1)
    assert tuple(axis.samples(0, 1)) == (0,)
    axis = StretchAxis.create(0, 1, 0, 9, 4)
    assert tuple(axis.samples(0, 1)) == ()


def test_stretch_mode_is_saved_and_restored():
    context = RasterContext(3, 1)
    context.set_stretch_mode(3)
    context.save_dc()
    context.set_stretch_mode(1)
    source = encode_dib24(RGBBitmap(3, 1, bytes((1, 2, 4, 8, 16, 32, 64, 128, 255))))
    context.dib_stretch_blt(0, 0, 1, 1, 0, 0, 3, 1, 0xCC0020, source)
    context.restore_dc(-1)
    context.dib_stretch_blt(1, 0, 1, 1, 0, 0, 3, 1, 0xCC0020, source)
    context.set_stretch_mode(2)
    context.dib_stretch_blt(2, 0, 1, 1, 0, 0, 3, 1, 0xCC0020, source)
    assert list(context.image.get_flattened_data()) == [(0, 0, 0), (8, 16, 32), (9, 18, 36)]
