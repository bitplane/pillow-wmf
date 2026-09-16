import pytest

from pillow_wmf.ellipse import arc_cubics
from pillow_wmf.gdi_math import sincos_degrees
from pillow_wmf.raster import RasterContext


@pytest.mark.parametrize("accurate,expected", ((False, (2777553, 15752235)), (True, (2778371, 15756924))))
def test_native_arc_endpoint_precision_modes(accurate, expected):
    # Run 35106971946, AngleArc at ten degrees with radius 1,000,000:
    # sweep 2.9999 uses accurate endpoints, while sweep 3 uses the table.
    assert tuple(round(value * 16000000) for value in sincos_degrees(10, accurate=accurate)) == expected


def test_native_short_arc_tangent_intersection_controls():
    # Original device controls captured in run 35104558437. Analytically
    # equivalent tan(sweep/4) handles are NOT equivalent with table arithmetic.
    assert arc_cubics(8, 8, 120, 120, (61, 65), (61, 66)) == (((174, 1297), (198, 1371), (233, 1442), (277, 1509)),)


def test_native_wrapping_arc_keeps_degenerate_terminal_piece():
    assert arc_cubics(8, 8, 120, 120, (67, 63), (67, 64)) == (
        ((1858, 735), (1738, 373), (1398, 128), (1016, 128)),
        ((1016, 128), (525, 128), (128, 526), (128, 1016)),
        ((128, 1016), (128, 1506), (525, 1904), (1016, 1904)),
        ((1016, 1904), (1507, 1904), (1904, 1506), (1904, 1016)),
        ((1904, 1016),) * 4,
    )


def test_native_nearly_equal_radials_produce_full_sweep_and_terminal_loop():
    assert arc_cubics(8, 8, 120, 120, (62, -16236), (62, -16235)) == (
        ((1016, 128), (526, 128), (128, 526), (128, 1016)),
        ((128, 1016), (128, 1506), (525, 1904), (1016, 1904)),
        ((1016, 1904), (1507, 1904), (1904, 1506), (1904, 1016)),
        ((1904, 1016), (1904, 526), (1507, 128), (1016, 128)),
        ((1016, 128), (1002, 128), (1002, 128), (1016, 128)),
    )


def test_arc_native_controls_distinguish_terminal_and_intermediate_quadrants():
    # Run 35099322489: GetPath reads the original device path, not a drawing
    # enlarged to 16x. The one-unit difference survives in wide raster output.
    assert arc_cubics(6, 70, 26, 92, (17, 81), (15, 82)) == (
        ((400, 1288), (400, 1195), (332, 1120), (248, 1120)),
        ((248, 1120), (164, 1120), (96, 1196), (96, 1288)),
        ((96, 1288), (96, 1330), (110, 1370), (136, 1401)),
    )


def test_arc_native_cardinal_boundary_piece_is_retained():
    assert arc_cubics(8, 8, 56, 56, (32, 31), (31, 32)) == (
        ((504, 128), (504, 128), (504, 128), (504, 128)),
        ((504, 128), (296, 128), (128, 296), (128, 504)),
    )


@pytest.mark.parametrize("style", (0, 1, 3, 5))
@pytest.mark.parametrize("change_start", (False, True))
@pytest.mark.parametrize("direction", ((1, -1), (-1, -1), (1, 0), (0, -1)))
def test_radial_distance_does_not_change_arc(style, change_start, direction):
    images = []
    for distance in (1, 10, 100):
        context = RasterContext(64, 64)
        context.select_object(context.create_pen(style, 1, 0))
        radial = tuple(32 + distance * component for component in direction)
        start, end = (radial, (8, 40)) if change_start else ((56, 40), radial)
        context.arc(8, 8, 56, 56, *start, *end)
        images.append(context.image.tobytes())
    assert images[0] == images[1] == images[2]
