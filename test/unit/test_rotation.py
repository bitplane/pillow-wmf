"""Rotated and sheared world transforms. Expected 28.4 paths were read back from native GetPath."""

import math

import pytest

from pillow_wmf.numeric import float32
from pillow_wmf.raster import RasterContext

# The rotation fixture's world at 1:1: 25 degrees about (40, -10).
COS, SIN = (float32(value) for value in (math.cos(math.radians(25)), math.sin(math.radians(25))))
FIXTURE = (COS, SIN, -SIN, COS, 40.0, -10.0)


def recorded(call, *args, world=FIXTURE):
    context = RasterContext(128, 128, trace_calls=False)
    context.set_graphics_mode(2)
    context.set_world_transform(*world)
    context.begin_path()
    getattr(context, call)(*args)
    context.end_path()
    ((commands, _),) = context._state.path
    points = [commands[0][0]]
    for command in commands:
        points.extend(command[1:])
    return points


def test_points_map_through_float32_product_sums():
    # Native maps (-20, 16) and (113, -10) of a polyline to these sixteenths.
    assert recorded("polyline", ((-20, 16), (113, -10)))[:2] == [(242, -63), (2346, 459)]


def test_rectangles_map_three_corners_and_reflect_the_fourth():
    scale = (2.2741613388061523, 1.0607258081436157, -1.060458779335022, 2.274733781814575)
    world = (*scale, 40.14814758300781, -10.03956413269043)
    # The fixture's 2.5x world: the mapped bottom-right would be (1244, 829).
    assert recorded("rectangle", 4, 4, 24, 16, world=world)[:4] == [(1447, 392), (720, 52), (516, 489), (1243, 829)]


@pytest.mark.parametrize(
    ("call", "args", "expected"),
    [
        (
            "ellipse",
            (10, 50, 60, 80),
            [(1071, 1189), (1127, 1069), (1010, 896), (809, 802), (609, 708), (402, 731), (345, 850)],
        ),
        (
            "round_rect",
            (64, 50, 100, 80, 10, 10),
            [(1718, 1313), (1737, 1274), (1720, 1226), (1679, 1207), (1303, 1032), (1262, 1013), (1215, 1031)],
        ),
        (
            "pie",
            (64, 10, 100, 46, 100, 28, 64, 10),
            [(1901, 923), (1968, 779), (1906, 607), (1762, 540), (1693, 508), (1614, 504), (1542, 530)],
        ),
    ],
)
def test_curved_shapes_are_built_on_the_mapped_corners(call, args, expected):
    assert recorded(call, *args)[: len(expected)] == expected


def test_oblique_pens_narrow_by_their_rounded_width_vectors():
    context = RasterContext(8, 8, trace_calls=False)
    context.set_graphics_mode(2)
    angle = math.radians(25)
    sx, sy = 2.5092592239379883, 2.5098910331726074
    context.set_world_transform(
        sx * math.cos(angle), sx * math.sin(angle), -sy * math.sin(angle), sy * math.cos(angle), 0, 0
    )
    # A one-unit pen is 2.509 pixels wide unrotated; at 25 degrees each
    # device axis rounds the width vector to (36, 17) sixteenths and
    # truncates its length to 39, two pixels.
    assert context.mapping.rotated_pen_scale(1) == (pytest.approx(39 / 16), pytest.approx(39 / 16))


def test_axis_aligned_operations_are_refused_under_rotation():
    from pillow_wmf.gdi import UnsupportedOperation
    from pillow_wmf.objects import RegionGeometry

    context = RasterContext(8, 8, trace_calls=False)
    context.set_graphics_mode(2)
    context.set_world_transform(*FIXTURE)
    with pytest.raises(UnsupportedOperation):
        context.frame_region(context.create_region(RegionGeometry(((0, 0, 4, 4),))), context.get_stock_object(4), 1, 1)


def gradient_dib(width=16, height=12):
    """The fixtures' bottom-up 24-bit source: each pixel's colour names its position."""
    import struct

    from pillow_wmf.objects import BitmapData

    stride = (width * 3 + 3) & ~3
    header = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, stride * height, 0, 0, 0, 0)
    rows = b""
    for y in range(height - 1, -1, -1):
        row = b"".join(bytes(((x + y) * 5 + 40, y * 10, x * 8)) for x in range(width))
        rows += row + bytes(stride - len(row))
    return BitmapData("dib", header + rows)


def test_plg_blt_ties_follow_source_columns_and_device_rows():
    context = RasterContext(128, 128, background=(255, 255, 255), trace_calls=False)
    context.plg_blt(((30, 8), (110, 40), (10, 70)), 0, 0, 16, 12, gradient_dib())
    image = context.image.convert("RGB")

    def source(x, y):
        red, green, _ = image.getpixel((x, y))
        return (red // 8, green // 10) if (red, green) != (255, 255) else None

    # Native: the upper-left corner and top edge are outside, the lower-left
    # corner is inside, and an exact source row boundary belongs to the row
    # above in device space; exact columns belong to the column they start.
    assert [source(30, 8), source(35, 10), source(10, 70), source(20, 39), source(35, 10 + 1)] == [
        None,
        None,
        (0, 11),
        (0, 5),
        (1, 0),
    ]


def test_rotated_rectangle_frames_share_a_perpendicular_per_box_axis():
    world = (
        2.2741613388061523,
        1.0607258081436157,
        -1.060458779335022,
        2.274733781814575,
        40.14814758300781,
        -10.03956413269043,
    )

    def row(draw):
        context = RasterContext(128, 128, background=(255, 255, 255), trace_calls=False)
        context.set_graphics_mode(2)
        context.set_world_transform(*world)
        context.select_object(context.create_pen(0, 1, 0))
        context.select_object(context.get_stock_object(5))  # NULL_BRUSH
        draw(context)
        image = context.image.convert("RGB")
        return [x for x in range(30, 50) if image.getpixel((x, 8)) != (255, 255, 255)]

    # Native: a polyline keeps the pen's support vertex on the steep edge, two
    # pixels wide, while Rectangle's mitred frame places it on the narrower
    # pen perpendicular shared by both logical vertical edges.
    assert row(lambda c: c.polyline(((4, 4), (24, 4), (24, 16), (4, 16), (4, 4)))) == [42, 43]
    assert row(lambda c: c.rectangle(4, 4, 24, 16)) == [43]
