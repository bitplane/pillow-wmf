"""Geometry measured from Windows GetPath after WidenPath in 28.4 units."""

import pytest

from pillow_wmf.stroke import cosmetic_line, line_outline


@pytest.mark.parametrize(
    ("start", "end", "width", "scale", "expected"),
    [
        (
            (16, 8),
            (96, 8),
            1,
            (2, 1),
            [(256, 120), (241, 128), (256, 136), (1536, 136), (1551, 128), (1536, 120)],
        ),
        (
            (16, 8),
            (96, 8),
            3,
            (2, 1),
            [
                (256, 104),
                (223, 112),
                (209, 128),
                (223, 144),
                (256, 152),
                (1536, 152),
                (1569, 144),
                (1583, 128),
                (1569, 112),
                (1536, 104),
            ],
        ),
        (
            (16, 16),
            (80, 40),
            3,
            (2, 1),
            [
                (288, 240),
                (256, 233),
                (223, 240),
                (209, 256),
                (224, 272),
                (1248, 656),
                (1280, 663),
                (1313, 656),
                (1327, 640),
                (1312, 624),
            ],
        ),
        (
            (8, 32),
            (40, 80),
            3,
            (1, 2),
            [
                (144, 480),
                (128, 465),
                (112, 479),
                (105, 512),
                (112, 544),
                (624, 1312),
                (640, 1327),
                (656, 1313),
                (663, 1280),
                (656, 1248),
            ],
        ),
    ],
)
def test_widened_line_matches_windows_fixed_path(start, end, width, scale, expected) -> None:
    assert line_outline(start, end, width, *scale) == expected


@pytest.mark.parametrize(
    "start,end,expected",
    [
        ((736, 424), (710, 308), {(45, 20), (45, 21), (45, 22), (45, 23), (45, 24), (46, 25), (46, 26)}),
        ((432, 128), (424, 128), {(27, 8)}),
        ((427, 472), (395, 499), {(26, 30), (25, 31)}),
        ((395, 499), (384, 528), {(24, 32)}),
    ],
)
def test_fractional_segments_match_native_windows(start, end, expected) -> None:
    # Run 35096891899: fractional paths verified with GetPath before StrokePath.
    # The shared vertex (395, 499) is outside the diamond: the incoming segment
    # owns (25, 31), contrary to the former blanket "following segment" rule.
    assert set(cosmetic_line(start, end, 128, 128)) == expected


def test_cosmetic_line_clips_enumeration_without_changing_the_line() -> None:
    assert list(cosmetic_line((-(10**12), 64), (10**12, 64), 8, 8)) == [(x, 4) for x in range(8)]


@pytest.mark.parametrize("reverse", [False, True])
def test_cosmetic_half_ties_keep_the_same_interior_pixel(reverse: bool) -> None:
    start, end = (0, 0), (32, 16)
    if reverse:
        start, end = end, start
    pixels = set(cosmetic_line(start, end, 8, 8))
    assert (1, 0) in pixels
    assert (1, 1) not in pixels
    assert (end[0] // 16, end[1] // 16) not in pixels
