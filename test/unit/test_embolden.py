"""The TrueType rasterizer's synthetic emboldening of outline points."""

from pillow_wmf.embolden import _intersect, _normalize, embolden

# A clockwise square (y up) and a clockwise triangle with a slanted right side.
SQUARE = [(0, 0, 1), (0, 256, 1), (256, 256, 1), (256, 0, 1)]
TRIANGLE = [(0, 0, 1), (64, 256, 1), (192, 0, 1)]


def test_one_pixel_grid_fitted_strength_moves_downward_edges_right():
    assert embolden([SQUARE], 1, grid_fitted=True) == [[(0, 0, 1), (0, 256, 1), (320, 256, 1), (320, 0, 1)]]
    # The apex joins an upward and a downward edge: it moves along the upward
    # edge's line, at most the strength.
    [[left, apex, right]] = embolden([TRIANGLE], 1, grid_fitted=True)
    assert (left, right) == ((0, 0, 1), (256, 0, 1))
    assert apex[1] == 256 and 64 <= apex[0] <= 128


def test_unfitted_strength_splits_and_short_contours_stay():
    assert embolden([SQUARE], 1, grid_fitted=False)[0][2][:2] == (320, 256)
    assert embolden([SQUARE], 1, grid_fitted=False)[0][0][:2] == (32, 0)
    line = [(0, 0, 1), (64, 64, 1)]
    assert embolden([line], 1, grid_fitted=True) == [line]


def test_wider_strengths_offset_both_edges_along_normals():
    [[*points]] = embolden([SQUARE], 2, grid_fitted=True)
    assert [point[:2] for point in points] == [(0, 0), (0, 256), (384, 256), (384, 0)]


def test_fixed_point_helpers():
    assert _normalize(3, 4) == (9830, 13107)  # 0.6 and 0.8 in 2.14
    assert _normalize(0, 0) == (0x4000, 0)
    assert _intersect((0, 0), (64, 0), (32, -32), (32, 32)) == (32, 0)
