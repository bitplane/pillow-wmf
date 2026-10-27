"""Generated geometry is bounded across curves, strokes and saved DCs."""

import pytest

from pillow_wmf import RasterContext, Recorder, render
from pillow_wmf.binary import ResourceLimitError
from pillow_wmf.geometry import GeometryBudget, StrokeSegment
from pillow_wmf.stroke import join_outline, realize_pen, widen_segment


def test_render_budget_accumulates_across_records():
    source = Recorder()
    source.ellipse(0, 0, 8, 8)
    render(source.to_bytes(), (8, 8), max_geometry_points=500)
    for _ in range(100):
        source.ellipse(0, 0, 8, 8)
    with pytest.raises(ResourceLimitError, match="Generated geometry point limit"):
        render(source.to_bytes(), (8, 8), max_geometry_points=500)


def test_saved_dc_cannot_restore_spent_geometry_budget():
    context = RasterContext(8, 8, max_geometry_points=500)
    with pytest.raises(ResourceLimitError, match="Generated geometry point limit"):
        for _ in range(100):
            context.save_dc()
            context.ellipse(0, 0, 8, 8)
            context.restore_dc(-1)
    # Failure must reset the dynamically scoped budget, including for other DCs.
    fresh = RasterContext(8, 8, max_geometry_points=500)
    fresh.ellipse(0, 0, 8, 8)
    assert fresh.image.getpixel((4, 0)) == (0, 0, 0)


@pytest.mark.parametrize("join", [False, True])
def test_wide_pen_caps_and_reversal_joins_spend_budget(join):
    pen = realize_pen(40)
    forward = StrokeSegment.line((0, 0), (160, 0))
    reverse = StrokeSegment.line((160, 0), (0, 0))

    def outline():
        return join_outline(forward, reverse, pen) if join else widen_segment(forward, pen)

    assert outline()
    budget = GeometryBudget(200)
    with budget.activate(), pytest.raises(ResourceLimitError, match="Generated geometry point limit"):
        for _ in range(100):
            outline()
    assert outline()  # Standalone helpers must not inherit an exhausted budget.


def test_straight_cosmetic_drawing_does_not_spend_expansion_budget():
    source = Recorder()
    source.rectangle(1, 1, 12, 12)
    source.polygon(((2, 2), (6, 2), (4, 6)))
    source.poly_polygon((((3, 3), (7, 3), (5, 7)), ((8, 8), (11, 8), (10, 11))))
    source.polyline(((0, 0), (15, 15), (0, 15)))
    data = source.to_bytes()
    assert render(data, (16, 16), max_geometry_points=0).tobytes() == render(data, (16, 16)).tobytes()


def test_pillow_reports_curve_exhaustion_as_oserror():
    from io import BytesIO

    from PIL import Image

    source = Recorder()
    source.set_window_extent(1, 1)
    source.set_viewport_extent(32767, 32767)
    source.scale_viewport_extent(32767, 1, 32767, 1)
    source.scale_viewport_extent(32767, 1, 32767, 1)
    source.ellipse(0, 0, 10, 10)
    with (
        Image.open(BytesIO(source.to_bytes())) as image,
        pytest.raises(OSError, match="Curve point limit") as caught,
    ):
        image.load(size=(16, 16))
    assert isinstance(caught.value.__cause__, ResourceLimitError)


@pytest.mark.parametrize("width", [2, 3, 4, 5, 6])
def test_fixed_table_pen_drawing_does_not_spend_expansion_budget(width):
    source = Recorder()
    source.select_object(source.create_pen(0, width, 0))
    source.rectangle(1, 1, 12, 12)
    source.polygon(((2, 2), (6, 2), (4, 6)))
    source.polyline(((0, 0), (15, 15), (0, 0)))
    data = source.to_bytes()
    assert render(data, (16, 16), max_geometry_points=0).tobytes() == render(data, (16, 16)).tobytes()


def test_dynamic_pen_body_without_caps_has_bounded_size():
    pen = realize_pen(40)
    segment = StrokeSegment.line((0, 0), (160, 0))
    with GeometryBudget(0).activate():
        assert len(widen_segment(segment, pen, cap_start=False, cap_end=False)) == 4


def test_wide_rectangle_reuses_geometry_within_operation_only():
    def draw(budget):
        context = RasterContext(64, 64, max_geometry_points=budget)
        context.select_object(context.create_pen(0, 12, 0))
        context.rectangle(10, 10, 50, 50)
        return context

    # One realization fits; repeating it within the same drawing call did not.
    limited = draw(25)
    assert limited.image.tobytes() == draw(1000).image.tobytes()
    limited.select_object(limited.create_pen(0, 1, 255))
    limited.set_viewport_origin(1, 1)
    limited.move_to(0, 0)
    limited.line_to(4, 0)
    assert limited.image.getpixel((2, 1)) == (255, 0, 0)
    with pytest.raises(ResourceLimitError):
        draw(0)
