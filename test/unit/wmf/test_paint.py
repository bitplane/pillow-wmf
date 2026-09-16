"""Independent truth-table checks for the WMF binary raster modes."""

from pillow_wmf.paint import rop2


def test_rop2_modes_cover_all_boolean_functions() -> None:
    # Truth-table bits are ordered P,D = 00, 01, 10, 11 in MS-WMF.
    for mode in range(1, 17):
        for source in (0, 255):
            for destination in (0, 255):
                index = (bool(source) << 1) | bool(destination)
                expected = 255 if (mode - 1) & (1 << index) else 0
                assert rop2(mode, (source,) * 3, (destination,) * 3) == (expected,) * 3


def test_rop2_operates_independently_on_rgb_bits() -> None:
    source = (0x96, 0x5A, 0xC3)
    destination = (0x3C, 0xE1, 0x17)
    assert rop2(7, source, destination) == tuple(p ^ d for p, d in zip(source, destination, strict=True))
    assert rop2(13, source, destination) == source
    assert rop2(11, source, destination) == destination
