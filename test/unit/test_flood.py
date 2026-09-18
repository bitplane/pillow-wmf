from collections import deque
from random import Random

import pytest

from pillow_wmf import RasterContext
from pillow_wmf.flood import flood_spans
from pillow_wmf.gdi import UnsupportedOperation


def test_scanlines_match_independent_four_neighbour_search():
    random = Random(721)
    for _ in range(100):
        eligible = {(x, y) for y in range(19) for x in range(23) if random.random() < 0.7}
        seed = random.randrange(-1, 24), random.randrange(-1, 20)
        expected = set()
        pending = deque([seed])
        while pending:
            x, y = pending.popleft()
            if (x, y) not in eligible or (x, y) in expected:
                continue
            expected.add((x, y))
            pending.extend(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))
        spans = flood_spans(23, 19, seed, lambda x, y, eligible=eligible: (x, y) in eligible)
        actual = [(x, y) for y, left, right in spans for x in range(left, right)]
        assert len(actual) == len(set(actual))
        assert set(actual) == expected


def test_tall_fill_does_not_recurse():
    assert len(flood_spans(1, 10000, (0, 0), lambda x, y: True)) == 10000


@pytest.mark.parametrize("mode", (0, 1))
def test_fill_preserves_current_position_and_selected_state(mode):
    context = RasterContext(8, 8)
    context.move_to(3, 4)
    context.select_object(context.create_brush(0, 0xFFFFFF, 0))
    context.ext_flood_fill(0, 0, 0 if mode == 0 else 0xFFFFFF, mode)
    assert context._position == (3, 4)
    assert context._rop2 == 13
    assert context._brush.color == (255, 255, 255)


def test_unknown_mode_remains_explicitly_unsupported():
    with pytest.raises(UnsupportedOperation):
        RasterContext(8, 8).ext_flood_fill(0, 0, 0, 2)
