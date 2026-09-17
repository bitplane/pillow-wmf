from itertools import product

import pytest

from pillow_wmf.paint import pattern_rop2, rop2, rop3


@pytest.mark.parametrize("table", range(256))
def test_all_rop3_truth_table_entries(table):
    for p, s, d in product((0, 255), repeat=3):
        index = ((p & 1) << 2) | ((s & 1) << 1) | (d & 1)
        expected = 255 if table & (1 << index) else 0
        assert rop3(table << 16, (p,) * 3, (s,) * 3, (d,) * 3) == (expected,) * 3


def test_mixed_colour_bits_and_ignored_code_word():
    p, s, d = (0x35, 0xA7, 0x19), (0x89, 0x23, 0xBE), (0x76, 0x58, 0xC1)
    for table in range(256):
        expected = tuple(
            sum(
                ((table >> ((((a >> bit) & 1) << 2) | (((b >> bit) & 1) << 1) | ((c >> bit) & 1))) & 1) << bit
                for bit in range(8)
            )
            for a, b, c in zip(p, s, d, strict=True)
        )
        assert rop3((table << 16) | 0x8000FFFF, p, s, d) == expected


def test_exactly_sixteen_source_independent_tables_reduce_to_rop2():
    modes = []
    for table in range(256):
        mode = pattern_rop2(table << 16)
        independent = all(((table >> i) & 1) == ((table >> (i ^ 2)) & 1) for i in range(8))
        assert (mode is not None) == independent
        if mode is not None:
            modes.append(mode)
            for source in ((0, 0, 0), (255, 71, 129)):
                assert rop3(table << 16, (19, 87, 211), source, (231, 56, 91)) == rop2(
                    mode, (19, 87, 211), (231, 56, 91)
                )
    assert sorted(modes) == list(range(1, 17))
