"""Geometry measured from Windows GetPath after WidenPath in 28.4 units."""

import pytest

from pillow_wmf.geometry import DevicePath, StrokeSegment
from pillow_wmf.stroke import cosmetic_line, line_outline, realize_pen, widen_segment


def test_subdivided_cubic_retains_endpoint_tangents() -> None:
    # Native widened-path measurements distinguish both
    # endpoint tangents from their chords, not just a cardinal Arc endpoint.
    cubic = ((256, 256), (768, 768), (768, 256), (1024, 256))
    path = DevicePath((cubic,))
    assert path.segments[0].direction == (512, 512)
    assert path.segments[-1].direction == (256, 0)
    flattened = path.flattened()
    assert path.vertices == flattened.vertices
    assert path.segments[0].direction != flattened.segments[0].direction
    assert path.segments[-1].direction != flattened.segments[-1].direction


def test_single_chord_cubic_uses_its_chord_direction() -> None:
    path = DevicePath((((512, 512), (516, 512), (512, 516), (516, 516)),))
    assert path.segments == (StrokeSegment((512, 512), (516, 516), (4, 4)),)


def test_flattening_closed_path_does_not_add_a_zero_length_segment() -> None:
    path = DevicePath.polyline(((0, 0), (16, 0), (16, 16)), closed=True)
    assert path.flattened() == path


@pytest.mark.parametrize("fx", range(16))
@pytest.mark.parametrize("fy", range(16))
def test_cap_origin_quantization_matches_native_matrix(fx, fy) -> None:
    # Run 35098165992: all 256 phases, same line and same realized pen.
    start = (512 + fx, 512 + fy)
    segment = StrokeSegment.line(start, (start[0] + 128, start[1] + 32))
    outline = widen_segment(segment, realize_pen(3))
    relative_cap = [(x - start[0], y - start[1]) for x, y in outline[:5]]
    expected = [(8, -24), (-8, -24), (-24, -8), (-24, 8), (-8, 24)]
    if fx == fy == 0:
        expected = [(8, -24), (-7, -23), (-23, -7), (-23, 7), (-8, 24)]
    assert relative_cap == expected


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
