"""Geometry measured from Windows GetPath after WidenPath in 28.4 units."""

import pytest

from pillow_wmf.stroke import line_outline


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
