"""Large native paths distinguish the fixed circle coefficient from sqrt(2)."""

import pytest

from pillow_wmf.ellipse import ellipse_cubics, round_rect_figure
from pillow_wmf.gdi_math import circle_control


@pytest.mark.parametrize("extent,control_x", [(88281, 1096286), (88282, 1096299), (88283, 1096311)])
@pytest.mark.parametrize("shape", ("ellipse", "roundrect"))
def test_native_large_circle_controls(extent, control_x, shape):
    # GetPath, Windows run 35329745361. Direct GDI coordinates deliberately
    # exceed WMF's signed 16-bit bounds; mapped WMFs use the same constructor.
    curves = (
        ellipse_cubics(0, 0, extent, 100)
        if shape == "ellipse"
        else round_rect_figure(0, 0, extent, 100, extent, 100).commands[::2]
    )
    assert curves[0] == (((extent - 1) * 16, 792), ((extent - 1) * 16, 355), (control_x, 0), ((extent - 1) * 8, 0))
    assert curves[1][1] == ((extent - 1) * 16 - control_x, 0)


@pytest.mark.parametrize("radius,up,down", [(0, 0, 0), (121173, 66923, 66922), (706248, 390051, 390050)])
def test_shared_coefficient_signed_rounding(radius, up, down):
    assert circle_control(radius, upward=True) == up
    assert circle_control(radius, upward=False) == down
    assert circle_control(-radius, upward=True) == -down
    assert circle_control(-radius, upward=False) == -up
