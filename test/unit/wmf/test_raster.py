import pytest

from pillow_wmf import Metafile, RasterContext, Recorder, UnsupportedOperation, play
from pillow_wmf.ellipse import ellipse_path
from pillow_wmf.stroke import cosmetic_line, dash_is_foreground


def test_raster_realizes_negative_pen_width_as_its_magnitude() -> None:
    context = RasterContext(8, 8)
    handle = context.create_pen(style=0, width=-1, color=0)
    assert context._objects[handle].width == 1
    assert context.calls[-1].kwargs["width"] == -1
    assert context.image.getpixel((0, 0)) == (255, 255, 255)


@pytest.mark.parametrize("style", [7, 8, 0x0100, 0x0200, 0x1000, 0x2000, 0x1100, 0x2200, 0x1001, 0x1005, 0xFFFF])
@pytest.mark.parametrize("width", [0, 1, 5])
def test_create_pen_indirect_falls_back_to_solid_without_changing_wire_style(style, width):
    images = []
    for requested in (0, style):
        recorder = Recorder()
        pen = recorder.create_pen(requested, width, 0x000000FF)
        recorder.select_object(pen)
        recorder.polyline(((2, 2), (13, 2), (8, 13)))
        source = recorder.to_bytes()
        parsed = Metafile.from_bytes(source)
        assert parsed.records[0].style == requested
        assert parsed.to_bytes() == source
        context = RasterContext(16, 16)
        assert play(parsed, context, strict=True) == ()
        assert context._pen.style == 0
        assert context.calls[0].kwargs["style"] == requested
        images.append(context.image.tobytes())
    assert images[0] == images[1]


@pytest.mark.parametrize(
    ("style", "pattern"),
    (
        (1, (18, 6)),
        (2, (3, 3)),
        (3, (9, 6, 3, 6)),
        (4, (9, 3, 3, 3, 3, 3)),
    ),
)
def test_cosmetic_pen_pattern_cycle(style: int, pattern: tuple[int, ...]) -> None:
    expected = tuple(on for index, length in enumerate(pattern) for on in (index % 2 == 0,) * length)
    actual = tuple(dash_is_foreground(style, position) for position in range(2 * len(expected)))
    assert actual == expected * 2


def test_styled_pen_gaps_use_background_mode_and_color() -> None:
    context = RasterContext(16, 8, background=(9, 9, 9))
    context.select_object(context.create_pen(2, 1, 0x000000FF))
    context.set_background_mode(1)
    context.move_to(0, 2)
    context.line_to(12, 2)
    context.set_background_mode(2)
    context.set_background_color(0x0000FF00)
    context.move_to(0, 4)
    context.line_to(12, 4)
    assert [context.image.getpixel((x, 2)) for x in range(6)] == [(255, 0, 0)] * 3 + [(9, 9, 9)] * 3
    assert [context.image.getpixel((x, 4)) for x in range(6)] == [(255, 0, 0)] * 3 + [(0, 255, 0)] * 3


def test_diamond_touches_are_resolved_by_segment_coverage() -> None:
    for bounds, index, expected in (
        ((66, 16, 121, 69), 3, 2),  # Exit then re-enter: two style steps.
        ((64, 12, 102, 61), 8, 0),  # Grazing an excluded edge: no step.
        ((12, 12, 40, 43), 2, 1),  # Crossing: one step.
        ((8, 8, 57, 43), 3, 1),  # Ordinary shared vertex: one step.
    ):
        path = ellipse_path(*bounds)
        pixel = tuple((coordinate + 8) // 16 for coordinate in path[index])
        first = set(cosmetic_line(path[index - 1], path[index], 128, 128))
        second = set(cosmetic_line(path[index], path[index + 1], 128, 128))
        assert int(pixel in first) + int(pixel in second) == expected


def test_fully_offscreen_segment_still_advances_connected_dash_phase() -> None:
    context = RasterContext(32, 8)
    context.set_background_mode(1)
    context.select_object(context.create_pen(1, 1, 0x000000FF))
    context.polyline(((-80, 3), (-32, 3), (24, 3)))
    assert context.image.getpixel((0, 3)) == (255, 0, 0)  # Phase 80 of 24.
    assert context.image.getpixel((10, 3)) == (255, 255, 255)  # Phase 90 is a gap.


def test_raster_requires_positive_image_size() -> None:
    with pytest.raises(ValueError, match="positive"):
        RasterContext(0, 8)


def test_zero_length_wide_line_draws_the_native_pen_footprint() -> None:
    context = RasterContext(16, 16)
    context.select_object(context.create_pen(0, 3, 0))
    context.move_to(8, 8)
    context.line_to(8, 8)
    pixels = {(x, y) for y in range(16) for x in range(16) if context.image.getpixel((x, y)) == (0, 0, 0)}
    assert pixels == {(8, 8), (7, 8), (9, 8), (8, 7), (8, 9)}


def test_save_restore_keeps_device_clip_without_copying_or_trimming_it() -> None:
    context = RasterContext(16, 16)
    context.intersect_clip_rect(32, 32, 40, 40)
    context.save_dc()
    context.offset_clip_region(-32, -32)
    context.set_pixel(4, 4, 0)
    context.restore_dc(-1)
    context.set_pixel(5, 5, 0)
    assert context.image.getpixel((4, 4)) == (0, 0, 0)
    assert context.image.getpixel((5, 5)) == (255, 255, 255)


def test_polygon_fill_mode_is_saved_and_restored() -> None:
    context = RasterContext(20, 8)
    context.select_object(context.create_pen(5, 0, 0))
    context.select_object(context.create_brush(0, 0, 0))
    contour = ((1, 1), (7, 1), (7, 7), (1, 7))
    context.set_polygon_fill_mode(2)
    context.save_dc()
    context.set_polygon_fill_mode(1)
    context.polygon(contour + contour)
    context.restore_dc(-1)
    shifted = tuple((x + 10, y) for x, y in contour)
    context.polygon(shifted + shifted)
    assert context.image.getpixel((3, 3)) == (255, 255, 255)
    assert context.image.getpixel((13, 3)) == (0, 0, 0)


def test_invalid_polygon_fill_mode_does_not_change_context() -> None:
    context = RasterContext(8, 8)
    with pytest.raises(UnsupportedOperation, match="Polygon fill mode"):
        context.set_polygon_fill_mode(3)
    assert context.calls == []


@pytest.mark.parametrize(("pen_style", "pen_width"), [(0, 1), (0, 5), (1, 1), (5, 0)])
@pytest.mark.parametrize("fill_mode", [1, 2])
def test_recorded_empty_polygon_leaves_pixels_and_subsequent_drawing_unchanged(pen_style, pen_width, fill_mode):
    images = []
    for insert_empty in (False, True):
        recorder = Recorder()
        recorder.select_object(recorder.create_pen(pen_style, pen_width, 0x000000FF))
        recorder.select_object(recorder.create_brush(0, 0x0000FF00, 0))
        recorder.set_polygon_fill_mode(fill_mode)
        recorder.move_to(2, 3)
        if insert_empty:
            recorder.polygon(())
        recorder.line_to(13, 3)
        recorder.polygon(((2, 7), (13, 7), (8, 13)))
        if insert_empty:
            recorder.polygon(())
        context = RasterContext(16, 16, background=(20, 30, 40))
        assert play(Metafile.from_bytes(recorder.to_bytes()), context, strict=True) == ()
        images.append(context.image.tobytes())
    assert images[0] == images[1]


@pytest.mark.parametrize("short", ((), ((4, 4),)))
@pytest.mark.parametrize("position", (0, 1, 2))
@pytest.mark.parametrize("fill_mode", (1, 2))
@pytest.mark.parametrize("width", (0, 7))
def test_polypolygon_rejects_all_contours_if_any_has_fewer_than_two_points(short, position, fill_mode, width):
    dc = RasterContext(32, 32)
    dc.select_object(dc.create_pen(0, width, 0))
    dc.select_object(dc.create_brush(0, 0x335577, 0))
    dc.set_polygon_fill_mode(fill_mode)
    dc.move_to(3, 29)
    before = dc.image.tobytes()
    valid = ((8, 8), (24, 8), (24, 24), (8, 24))
    polygons = [valid, valid]
    polygons.insert(position, short)
    dc.poly_polygon(tuple(polygons))
    assert dc.image.tobytes() == before
    dc.line_to(29, 29)
    assert dc.image.getpixel((16, 29)) == (0, 0, 0)


def test_nonstandard_background_mode_is_retained() -> None:
    context = RasterContext(8, 8)
    context.set_background_mode(3)
    assert context._background_mode == 3
    assert context.calls[-1].kwargs["mode"] == 3


def test_invalid_hatch_does_not_create_an_object() -> None:
    context = RasterContext(8, 8)
    with pytest.raises(UnsupportedOperation, match="hatch brushes"):
        context.create_brush(2, 0, 6)
    assert context.calls == []


def test_hatch_background_mode_and_color_are_saved_and_restored() -> None:
    context = RasterContext(24, 8, background=(9, 9, 9))
    context.select_object(context.create_pen(5, 0, 0))
    context.select_object(context.create_brush(2, 0x000000FF, 0))
    context.set_background_mode(1)
    context.save_dc()
    context.set_background_mode(2)
    context.set_background_color(0x0000FF00)
    context.rectangle(0, 0, 8, 8)
    context.restore_dc(-1)
    context.rectangle(8, 0, 16, 8)
    assert context.image.getpixel((1, 1)) == (0, 255, 0)
    assert context.image.getpixel((9, 1)) == (9, 9, 9)
    assert context.image.getpixel((1, 3)) == (255, 0, 0)
    assert context.image.getpixel((9, 3)) == (255, 0, 0)


def test_null_brush_leaves_fill_untouched_even_when_background_is_opaque() -> None:
    context = RasterContext(8, 8, background=(9, 9, 9))
    context.select_object(context.create_pen(5, 0, 0))
    context.select_object(context.create_brush(1, 0x000000FF, 0))
    context.set_background_mode(2)
    context.set_background_color(0x0000FF00)
    context.rectangle(0, 0, 8, 8)
    assert context.image.getpixel((3, 3)) == (9, 9, 9)


def test_polyline_does_not_change_current_position() -> None:
    context = RasterContext(10, 6)
    context.move_to(1, 1)
    context.polyline(((3, 3), (4, 3)))
    context.line_to(8, 1)
    assert context.image.getpixel((2, 1)) == (0, 0, 0)
    assert context.image.getpixel((5, 3)) == (255, 255, 255)
