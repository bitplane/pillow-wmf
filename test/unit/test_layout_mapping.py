"""Native-observed RTL state and coordinate-space contracts."""

import pytest

from pillow_wmf import RasterContext, UnsupportedOperation
from pillow_wmf.ellipse import arc_cubics, ellipse_cubics
from pillow_wmf.mapping import Mapping


@pytest.mark.parametrize(
    "wx,vx,extent,origin",
    ((0, 0, 96, 126), (3, 0, 96, 130.5), (0, 7, 96, 119), (3, 7, 96, 123.5), (3, 7, -96, 114.5), (3, 7, 64, 123)),
)
def test_native_transform_coefficients(wx, vx, extent, origin):
    mapping = Mapping(
        window_origin=(wx, -2), viewport_origin=(vx, 4), window_extent=(64, 128), viewport_extent=(extent, 128)
    )
    mapping.set_layout(1)
    numerator, denominator, translation = next(mapping._axes())
    assert numerator / denominator == -extent / 64
    assert translation == origin


def test_native_lp_to_dp_samples_at_fractional_scale():
    mapping = Mapping(window_origin=(3, -2), viewport_origin=(7, 4), window_extent=(64, 128), viewport_extent=(96, 128))
    mapping.set_layout(1)
    assert [mapping.point(x, x) for x in (-15, -3, -1, 0, 1, 3, 15, 127)] == [
        (146, -9),
        (128, 3),
        (125, 5),
        (124, 6),
        (122, 7),
        (119, 9),
        (101, 21),
        (-67, 133),
    ]


def test_layout_mode_transitions_retain_anisotropic_mode_until_explicit_reset():
    mapping = Mapping()
    mapping.set_mode(1)
    mapping.set_layout(1)
    assert mapping.mode == 8
    mapping.set_extent(window=True, x=64, y=128)
    assert mapping.window_extent == (64, 128)
    mapping.set_mode(1)
    assert mapping.mode == 8
    assert mapping.window_extent == mapping.viewport_extent == (1, 1)
    mapping.set_layout(0)
    assert mapping.mode == 8
    mapping.set_mode(1)
    assert mapping.mode == 1


@pytest.mark.parametrize("width", (17, 128, 203))
def test_surface_width_not_viewport_extent_defines_identity_reflection(width):
    dc = RasterContext(width, 12)
    dc.set_layout(1)
    dc.set_pixel(0, 0, 0)
    assert dc.image.getpixel((width - 1, 0)) == (0, 0, 0)
    assert dc.image.getpixel((0, 0)) == (255, 255, 255)


def test_layout_is_saved_with_mapping_not_baked_into_extents():
    dc = RasterContext(20, 12)
    dc.set_layout(9)
    dc.save_dc()
    dc.set_layout(0)
    dc.set_map_mode(1)
    dc.restore_dc(-1)
    assert dc.mapping.layout == 9
    assert dc.mapping.mode == 8
    assert dc.mapping.viewport_extent == (20, 12)


def test_unimplemented_layout_bits_fail_without_mutating_state():
    dc = RasterContext(20, 12)
    with pytest.raises(UnsupportedOperation, match="Layout"):
        dc.set_layout(2)
    assert dc.mapping.layout == 0


def test_points_clip_edges_and_displacements_have_distinct_contracts():
    mapping = Mapping()
    mapping.set_layout(1)
    assert mapping.device_point(8, 5) == (119, 5)
    assert mapping.clip_point(8, 5) == (120, 5)
    assert mapping.clip_displacement(3, 2) == (-3, 2)
    assert mapping.vector(3, 2) == (-3, 2)


def test_clockwise_ellipse_matches_native_fixed_controls_not_reversed_ccw():
    curves = ellipse_cubics(76, 28, 117, 45, clockwise=True)
    assert curves[0] == ((1856, 576), (1856, 647), (1713, 704), (1536, 704))
    assert curves[1] == ((1536, 704), (1359, 704), (1216, 647), (1216, 576))
    ccw = ellipse_cubics(76, 28, 117, 45)
    assert curves != tuple(tuple(reversed(curve)) for curve in reversed(ccw))


def test_clockwise_arc_matches_native_28_4_controls():
    assert arc_cubics(76, 76, 117, 93, (-40, 70), (-3, 101), radial_bounds=(-33, 76, -6, 93), clockwise=True) == (
        ((1323, 1248), (1382, 1228), (1458, 1216), (1536, 1216)),
        ((1536, 1216), (1713, 1216), (1856, 1273), (1856, 1344)),
        ((1856, 1344), (1856, 1388), (1800, 1429), (1706, 1452)),
    )
