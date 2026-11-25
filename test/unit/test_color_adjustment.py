"""COLORADJUSTMENT in HALFTONE stretching. Expected levels were read back natively."""

import pytest

from pillow_wmf.color_adjustment import ColorAdjustment


@pytest.mark.parametrize(
    ("adjustment", "levels"),
    [
        # The fixture's contrast 50 with brightness -50, including near-ties.
        (ColorAdjustment(contrast=50, brightness=-50), {24: 3, 32: 20, 117: 198, 136: 238, 145: 255}),
        (ColorAdjustment(contrast=-50), {20: 10, 60: 29, 255: 121}),
        (ColorAdjustment(contrast=100, brightness=-100), {35: 59, 72: 223, 79: 255}),
        (ColorAdjustment(brightness=20), {0: 19, 255: 255}),
        (ColorAdjustment(gamma=(20000, 20000, 20000)), {128: 64, 224: 197}),
        (ColorAdjustment(black=1000, white=9000 + 1000), {32: 7}),
        (ColorAdjustment(flags=2), {32: 77, 128: 185}),
        (ColorAdjustment(flags=3), {32: 178, 128: 70}),
        (ColorAdjustment(flags=1, contrast=50), {32: 188, 128: 0}),
    ],
)
def test_levels_match_native_halftone_output(adjustment, levels):
    table = adjustment.tables[0]
    assert {value: table[value] for value in levels} == levels


def test_channels_take_their_own_gamma():
    red, green, blue = ColorAdjustment(gamma=(20000, 10000, 10000)).tables
    assert (red[128], green[128], blue[128]) == (64, 128, 128)


def test_channel_mixing_adjustments_are_refused():
    from pillow_wmf.gdi import UnsupportedOperation
    from pillow_wmf.raster import RasterContext

    with pytest.raises(UnsupportedOperation):
        RasterContext(4, 4).set_color_adjustment(colorfulness=50)
