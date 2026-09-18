"""Native large paths expose arithmetic hidden by small bitmap fixtures."""

import pytest

from pillow_wmf.ellipse import arc_cubics


@pytest.mark.parametrize(
    "size,start,end,expected",
    [
        (
            131071,
            (10000, -1),
            (10000, -500),
            ((2097120, -218), (2097116, -35060), (2096244, -69912), (2094505, -104710)),
        ),
        (
            1000000,
            (10000, -1),
            (0, -10000),
            ((15999945, -1607), (15999105, -8837529), (8835935, -16000000), (-8, -16000000)),
        ),
        (
            1000000,
            (10000, -490),
            (10000, -1000),
            ((15980819, -782887), (15967589, -1052946), (15947505, -1322754), (15920605, -1591808)),
        ),
        (
            1000000,
            (10000, -1),
            (10000, -500),
            ((15999984, -1607), (15999956, -267435), (15993301, -533339), (15980030, -798831)),
        ),
        (
            1000000,
            (-10000, -490),
            (-10000, -1000),
            ((-15980836, -782886), (-15993608, -522155), (-16000000, -261039), (-16000000, -8)),
        ),
    ],
)
def test_native_large_arc_terminal_controls(size, start, end, expected):
    # Native GetPath capture. The surface remains 128²;
    # only the path coordinates are large. All values are exact device 28.4.
    assert arc_cubics(-size, -size, size, size, start, end)[0] == expected


def test_native_wrapping_arc_uses_exact_internal_axis_normals():
    # Close radial angles select Taylor endpoints, but their long
    # wrapping sweep still uses exact cardinal normals between quadrants.
    curves = arc_cubics(-1000000, -1000000, 1000000, 1000000, (-10000, -490), (-10000, -1000))
    assert [curves[0][0], *(p for curve in curves for p in curve[1:])] == [
        (-15980836, -782886),
        (-15993608, -522155),
        (-16000000, -261039),
        (-16000000, -8),
        (-16000000, 8836543),
        (-8836560, 15999984),
        (-8, 15999984),
        (8836544, 15999984),
        (15999984, 8836543),
        (15999984, -8),
        (15999984, -8836559),
        (8836544, -16000000),
        (-8, -16000000),
        (-8220039, -16000000),
        (-15102828, -9771060),
        (-15920621, -1591811),
    ]
