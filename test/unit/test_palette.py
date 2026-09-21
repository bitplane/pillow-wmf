from struct import pack

import pytest

from pillow_wmf import FormatError, RasterContext, Recorder, UnsupportedOperation
from pillow_wmf.bitmap import decode_dib, encode_dib, read_dib
from pillow_wmf.palette import LogicalPalette, PaletteIndex
from pillow_wmf.wmf.objects import BitmapData, Palette

COLORS = ((17, 31, 53), (71, 97, 131), (149, 173, 199))


def test_paletteindex_flag_is_independent_of_other_high_bits():
    from pillow_wmf.raster import logical_color

    for flags in range(256):
        expected = PaletteIndex(0x3412) if flags & 1 else (18, 52, 86)
        assert logical_color(flags << 24 | 0x563412) == expected


@pytest.mark.parametrize("depth,pixels", ((1, b"\x40\0\0\0"), (4, b"\x01\x00\0\0"), (8, b"\0\1\0\0")))
def test_palette_writer_matches_independent_word_table_bytes(depth, pixels):
    source = encode_dib(3, 1, (0, 1, 0), depth=depth, color_usage=1, colors=(2, 1))
    assert source.data == pack("<IiiHHIIiiII", 40, 3, 1, 1, depth, 0, 4, 0, 0, 2, 0) + pack("<HH", 2, 1) + pixels
    layout = read_dib(source, color_usage=1)
    assert layout.colors == (2, 1)
    assert layout.decode(palette=COLORS).pixels == bytes(COLORS[2] + COLORS[1] + COLORS[2])
    with pytest.raises(UnsupportedOperation, match="requires"):
        layout.decode()


@pytest.mark.parametrize("header", (12, 40, 108, 124))
@pytest.mark.parametrize("depth", (1, 4, 8))
def test_palette_header_layout_and_word_wrap(header, depth):
    source = encode_dib(3, 2, (0, 1, 0, 1, 0, 1), depth=depth, color_usage=1, colors=(4, 65535), header_size=header)
    assert decode_dib(source, color_usage=1, palette=COLORS).pixels == bytes(COLORS[1] + COLORS[0]) * 3


@pytest.mark.parametrize("depth", (4, 8))
def test_rle_palette_resolution_uses_same_table(depth):
    source = encode_dib(3, 1, (0, 1, 0), depth=depth, color_usage=1, colors=(2, 1), rle=True)
    assert decode_dib(source, color_usage=1, palette=COLORS).pixels == bytes(COLORS[2] + COLORS[1] + COLORS[2])


def test_direct_palette_indices_have_no_table():
    source = encode_dib(3, 1, (0, 2, 1), depth=8, color_usage=2)
    assert len(source.data) == 44
    assert read_dib(source, color_usage=2).offset == 40
    assert decode_dib(source, color_usage=2, palette=COLORS).pixels == bytes(COLORS[0] + COLORS[2] + COLORS[1])


def test_odd_word_table_is_not_rounded_to_dword_boundary():
    source = encode_dib(3, 1, (2, 1, 0), depth=4, color_usage=1, colors=(0, 1, 2))
    assert read_dib(source, color_usage=1).offset == 46
    assert decode_dib(source, color_usage=1, palette=COLORS).pixels == bytes(COLORS[2] + COLORS[1] + COLORS[0])
    with pytest.raises(FormatError, match="table"):
        read_dib(BitmapData("dib", source.data[:45]), color_usage=1)


def test_palette_mutation_is_object_state_not_saved_dc_state():
    dc = RasterContext(8, 8)
    a = dc.create_palette(Palette(entries=tuple((*c, 0) for c in COLORS)))
    b = dc.create_palette(Palette(entries=((3, 5, 7, 0),)))
    dc.select_palette(a)
    original = dc._palette
    dc.save_dc()
    dc.set_palette_entries(Palette(1, ((13, 19, 29, 0),)))
    dc.select_palette(b)
    dc.restore_dc(-1)
    assert dc._palette is original
    assert dc._palette.color(1) == (13, 19, 29)


def test_animation_checks_old_flags_and_replaces_new_flags():
    palette = LogicalPalette(((1, 2, 3, 0), (4, 5, 6, 1)))
    palette.update(0, ((17, 31, 53, 0),) * 2, animate=True)
    assert palette.entries == ((1, 2, 3, 0), (17, 31, 53, 0))
    palette.update(0, ((71, 97, 131, 1),) * 2, animate=True)
    assert palette.entries == ((1, 2, 3, 0), (17, 31, 53, 0))


def test_resize_truncates_and_grows_with_zero_entries():
    palette = LogicalPalette(((1, 2, 3, 1), (4, 5, 6, 4)))
    palette.resize(1)
    palette.resize(3)
    assert palette.entries == ((1, 2, 3, 1), (0, 0, 0, 0), (0, 0, 0, 0))
    palette.update(2, ((7, 8, 9, 0), (10, 11, 12, 0)))
    assert palette.entries[-1] == (7, 8, 9, 0)


def test_stock_palette_is_not_mutated():
    palette = LogicalPalette.default()
    original = palette.entries
    palette.update(0, ((31, 71, 131, 0),))
    palette.resize(2)
    assert palette.entries == original


def test_unallocated_palette_selection_is_noop_but_not_recordable():
    dc = RasterContext(8, 8)
    palette = dc._palette
    dc.select_palette(None)
    assert dc._palette is palette
    with pytest.raises(ValueError, match="portable"):
        Recorder().select_palette(None)


@pytest.mark.parametrize("usage", (1, 2))
def test_invalid_palette_writer_values(usage):
    with pytest.raises(ValueError):
        encode_dib(1, 1, (0,), depth=4, colors=(65536,), color_usage=usage)


def test_palette_brush_resolves_current_palette_when_drawing():
    dc = RasterContext(4, 2)
    dc.select_palette(dc.create_palette(Palette(entries=tuple((*c, 0) for c in COLORS))))
    dib = encode_dib(2, 1, (0, 1), depth=1, color_usage=1, colors=(2, 0))
    dc.select_object(dc.create_dib_pattern_brush(5, 1, dib))
    dc.pat_blt(0, 0, 4, 1, 0xF00021)
    dc.set_palette_entries(Palette(2, ((7, 11, 13, 0),)))
    dc.pat_blt(0, 1, 4, 1, 0xF00021)
    assert dc.image.getpixel((0, 0)) == COLORS[2]
    assert dc.image.getpixel((0, 1)) == (7, 11, 13)
    assert dc.image.getpixel((1, 1)) == COLORS[0]


def test_colorref_bounds_differ_from_dib_table_wraparound():
    palette = LogicalPalette(tuple((*c, 0) for c in COLORS))
    assert palette.color(4) == COLORS[1]
    assert palette.colorref(PaletteIndex(4)) == COLORS[0]
    assert palette.colorref((13, 19, 29)) == (13, 19, 29)


def test_pen_and_brush_palette_references_are_not_frozen_at_creation():
    dc = RasterContext(8, 4)
    dc.select_palette(dc.create_palette(Palette(entries=tuple((*c, 0) for c in COLORS))))
    dc.select_object(dc.create_brush(0, 0x01000001, 0))
    dc.select_object(dc.create_pen(0, 1, 0x01000002))
    dc.pat_blt(0, 0, 4, 1, 0xF00021)
    dc.set_palette_entries(Palette(1, ((7, 11, 13, 0), (19, 23, 29, 0))))
    dc.pat_blt(0, 1, 4, 1, 0xF00021)
    dc.move_to(0, 2)
    dc.line_to(4, 2)
    assert dc.image.getpixel((0, 0)) == COLORS[1]
    assert dc.image.getpixel((0, 1)) == (7, 11, 13)
    assert dc.image.getpixel((0, 2)) == (19, 23, 29)


@pytest.mark.parametrize("depth", (8, 16, 24, 32))
def test_direct_index_playback_requires_reference_device_depth(depth):
    dc = RasterContext(1, 1, background=(3, 5, 7))
    source = encode_dib(1, 1, (0x735119 if depth == 32 else 0,), depth=depth, color_usage=2 if depth == 8 else 0)
    dc.set_dib_to_device(0, 0, 1, 1, 0, 0, 0, 1, 2, source)
    assert dc.image.getpixel((0, 0)) == ((115, 81, 25) if depth == 32 else (3, 5, 7))


@pytest.mark.parametrize("top_down", (False, True))
def test_packed_brush_aligns_table_without_changing_transfer_layout(top_down):
    dc = RasterContext(3, 2)
    dc.select_palette(dc.create_palette(Palette(entries=tuple((*c, 0) for c in COLORS))))
    source = encode_dib(3, 1, (0, 1, 2), depth=8, color_usage=1, colors=(0, 1, 2), top_down=top_down)
    # Add the packed brush's DWORD alignment; the transfer codec does not
    # automatically consume these bytes when decoding an ordinary WORD table.
    packed = BitmapData("dib", source.data[:46] + b"\x02\x02" + source.data[46:])
    dc.select_object(dc.create_dib_pattern_brush(5, 1, packed))
    dc.pat_blt(0, 0, 3, 1, 0xF00021)
    assert list(dc.image.crop((0, 0, 3, 1)).get_flattened_data()) == list(COLORS)
    assert decode_dib(packed, color_usage=1, palette=COLORS).pixels == bytes(COLORS[2] + COLORS[2] + COLORS[0])


def test_malformed_palette_call_is_atomic():
    dc = RasterContext(1, 1)
    with pytest.raises(ValueError):
        dc.create_palette(Palette(entries=((256, 0, 0, 0),)))
    assert dc.calls == []
    assert dc._objects == {}
