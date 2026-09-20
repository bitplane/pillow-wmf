"""Original geometry for fractional ellipse and collapsed-pen integration tests."""

from pillow_wmf import Recorder
from pillow_wmf.constants import BS_NULL, BS_SOLID, MM_ANISOTROPIC, PS_INSIDEFRAME


def mapped(window):
    recorder = Recorder()
    recorder.set_map_mode(MM_ANISOTROPIC)
    recorder.set_window_extent(*window)
    recorder.set_viewport_extent(128, 128)
    recorder.select_object(recorder.create_brush(BS_NULL, 0, 0))
    return recorder


def cases():
    # Near-circular pen quantization and geometric inside-frame insets have
    # different rounding rules. Exercise both with offset, overlapping rims.
    for name, window, width in (
        ("x-wide", (2232, 2218), 48),
        ("y-wide", (2213, 2223), 48),
        ("y-wider", (2203, 2218), 48),
        ("uniform", (2299, 2299), 80),
    ):
        recorder = mapped(window)
        recorder.select_object(recorder.create_pen(PS_INSIDEFRAME, width, 0x174A91))
        recorder.select_object(recorder.create_brush(BS_SOLID, 0xDDEECC, 0))
        recorder.ellipse(173, 251, 1887, 1643)
        recorder.select_object(recorder.create_brush(BS_NULL, 0, 0))
        recorder.select_object(recorder.create_pen(PS_INSIDEFRAME, width, 0xA14219))
        recorder.ellipse(419, 613, 2063, 2081)
        yield f"ellipse-fractional-rims-{name}", recorder

    for name, window, width in (
        ("wide", (2021, 2092), 96),
        ("narrow", (1987, 2078), 79),
    ):
        recorder = mapped(window)
        recorder.select_object(recorder.create_pen(PS_INSIDEFRAME, width, 0x174A91))
        recorder.ellipse(157, 193, 1823, 1867)
        recorder.ellipse(467, 677, 1451, 1339)
        yield f"ellipse-anisotropic-unfilled-{name}", recorder

    recorder = mapped((412, 1915))
    for row, width in enumerate((6, 8)):
        recorder.set_viewport_origin(0, row * 64)
        recorder.select_object(recorder.create_pen(PS_INSIDEFRAME, width, 0x174A91))
        recorder.polyline(((43, 139), (167, 631), (347, 173)))
        recorder.select_object(recorder.create_brush(BS_SOLID, 0xDDEECC, 0))
        recorder.polygon(((61, 683), (203, 419), (331, 757)))
        recorder.select_object(recorder.create_brush(BS_NULL, 0, 0))
    yield "pen-subpixel-minor-axis-paths", recorder

    recorder = mapped((324, 2038))
    recorder.select_object(recorder.create_pen(PS_INSIDEFRAME, 8, 0x174A91))
    recorder.polygon(((37, 251), (283, 317), (251, 593), (53, 527)))
    recorder.select_object(recorder.create_brush(BS_SOLID, 0xDDEECC, 0))
    recorder.polygon(((41, 947), (269, 881), (293, 1193), (67, 1259)))
    recorder.polyline(((43, 1703), (173, 1661), (281, 1719)))
    yield "pen-collapsed-shallow-polygons", recorder
