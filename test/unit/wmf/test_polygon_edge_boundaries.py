"""Native scan-edge boundaries expressed independently of traversal storage."""

import pytest

from pillow_wmf.geometry import contains


@pytest.mark.parametrize(
    "start,end,left_edges",
    [
        ((-17, -9), (65, 57), (0, 1, 3, 4)),
        ((63, -7), (-37, 42), (4, 2, -1)),
    ],
)
@pytest.mark.parametrize("reverse", (False, True))
@pytest.mark.parametrize("fill_mode", (1, 2))
def test_fractional_edges_use_ceiling_intersections(start, end, left_edges, reverse, fill_mode):
    # Each row's left boundary was checked against native edge initialization
    # and stepping. Upper endpoints are included; lower endpoints are not.
    polygon = [start, end, (128, end[1]), (128, start[1])]
    if reverse:
        polygon.reverse()
    expected = {(x, y) for y, left in enumerate(left_edges) for x in range(left, 8)}
    actual = {(x, y) for y in range(-2, 6) for x in range(-4, 10) if contains((polygon,), x, y, fill_mode=fill_mode)}
    assert actual == expected
