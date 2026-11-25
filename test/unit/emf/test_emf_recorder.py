"""EMF recording. Expected bytes are native recordings of the same calls.

``native_recordings.json`` holds complete files Windows wrote for each
scenario through CreateEnhMetaFile on the reference DC.
"""

import json
import struct
from pathlib import Path

import pytest

from pillow_wmf.emf import Metafile, Recorder, play
from pillow_wmf.gdi import UnsupportedOperation
from pillow_wmf.objects import BitmapData, FontRequest, PaletteEntries, PaletteUpdate, RegionGeometry
from pillow_wmf.raster import RasterContext

NATIVE = json.loads((Path(__file__).with_name("native_recordings.json")).read_text())


def scenarios():
    """(name, frame, drawing) for each native recording."""

    def empty(r):
        pass

    yield "empty", None, empty
    yield "empty-frame", (0, 0, 3388, 3383), empty
    yield "rectangle", None, lambda r: r.rectangle(10, 20, 50, 40)
    yield "rectangle-frame", (0, 0, 3388, 3383), lambda r: r.rectangle(10, 20, 50, 40)

    def objects(r):
        pen = r.create_pen(0, 5, 0x0000FF)
        brush = r.create_brush(0, 0x00FF00, 0)
        unused = r.create_brush(0, 0x123456, 0)
        r.select_object(pen)
        r.select_object(brush)
        r.rectangle(10, 10, 40, 30)
        r.select_object(r.get_stock_object(0))
        r.select_object(r.get_stock_object(7))
        r.delete_object(pen)
        r.delete_object(unused)
        second = r.create_brush(2, 0xFF0000, 2)
        r.select_object(second)
        r.ellipse(50, 50, 90, 80)
        third = r.create_brush(0, 0x0000FF, 0)
        r.select_object(third)
        r.delete_object(second)
        r.delete_object(third)

    yield "objects", None, objects

    def selected_delete(r):
        b = r.create_brush(0, 0x00FF00, 0)
        r.select_object(b)
        r.delete_object(b)
        r.rectangle(1, 1, 9, 9)

    yield "selected-delete", None, selected_delete

    def wide(r):
        black = r.get_stock_object(7)
        for w in (0, 1, 2, 3, 6):
            p = r.create_pen(0, w, 0)
            r.select_object(p)
            r.line_to(20 + w, 30)
            r.rectangle(40, 40, 60 + w, 70)
            r.select_object(black)
            r.delete_object(p)

    yield "wide-pens", None, wide

    def shapes(r):
        r.ellipse(5, 6, 30, 20)
        r.round_rect(5, 30, 40, 60, 10, 8)
        r.arc(50, 5, 90, 40, 90, 20, 50, 5)
        r.pie(50, 50, 90, 90, 90, 70, 70, 50)
        r.set_pixel(3, 4, 0x00FF00)

    yield "shapes", None, shapes

    def lines(r):
        r.move_to(3, 4)
        r.line_to(30, 40)
        pts = ((1, 2), (30, 5), (60, 40))
        r.polyline(pts)
        r.polygon(pts)
        r.polyline(((1, 2), (40000, 5), (60, 40)))
        r.polyline(((-5, 2), (30, -7), (60, 40)))
        r.poly_bezier(((1, 2), (10, 30), (30, 30), (40, 2)))
        r.poly_polygon((((1, 1), (20, 1), (20, 20)), ((40, 40), (60, 40), (60, 60))))

    yield "lines", None, lines

    def mapping(r):
        r.set_map_mode(8)
        r.set_window_extent(100, 100)
        r.set_viewport_extent(50, 200)
        r.set_window_origin(10, 10)
        r.rectangle(10, 10, 50, 30)

    yield "mapping", None, mapping

    def state(r):
        r.set_background_mode(1)
        r.set_background_color(0x123456)
        r.set_text_color(0x654321)
        r.set_rop2(7)
        r.save_dc()
        r.intersect_clip_rect(5, 5, 50, 50)
        r.rectangle(0, 0, 60, 60)
        r.restore_dc(-1)
        g = r.create_region(RegionGeometry(((10, 10, 30, 30),)))
        r.select_clip_region(g)
        r.fill_region(g, r.get_stock_object(4))
        r.delete_object(g)

    yield "state", None, state

    def paths(r):
        r.begin_path()
        r.move_to(5, 5)
        r.line_to(40, 10)
        r.line_to(20, 40)
        r.end_path()
        r.stroke_path()
        r.begin_path()
        r.rectangle(50, 50, 80, 80)
        r.end_path()
        r.fill_path()

    yield "paths", None, paths
    figures = {
        "rect": lambda r: r.rectangle(20, 20, 40, 30),
        "ellipse": lambda r: r.ellipse(20, 20, 40, 30),
        "line": lambda r: (r.move_to(20, 20), r.line_to(40, 30)),
        "polyline": lambda r: r.polyline(((20, 20), (40, 30), (25, 35))),
        "polygon": lambda r: r.polygon(((20, 20), (40, 30), (25, 35))),
    }
    for f, draw in figures.items():
        for w in (0, 1, 2, 3, 4, 5, 8, 11):

            def go(r, w=w, draw=draw):
                r.select_object(r.create_pen(0, w, 0))
                draw(r)

            yield f"bounds-{f}-w{w}", None, go
    for st in (1, 5, 6):

        def styled(r, st=st):
            r.select_object(r.create_pen(st, 6, 0))
            r.rectangle(20, 20, 40, 30)

        yield f"bounds-rect-style{st}", None, styled

    def geometric(r):
        r.select_object(r.ext_create_pen(style=0x00010000 | 0x0200 | 0x2000, width=6, color=0))
        r.polyline(((20, 20), (40, 30), (25, 35)))

    yield "bounds-geometric-miter", None, geometric

    def miter(r):
        r.set_miter_limit(2.0)
        r.select_object(r.create_pen(0, 5, 0))
        r.rectangle(20, 20, 40, 30)

    yield "bounds-rect-miter2", None, miter

    def scaled(r):
        r.set_map_mode(8)
        r.set_window_extent(10, 10)
        r.set_viewport_extent(25, 25)
        r.select_object(r.create_pen(0, 2, 0))
        r.rectangle(4, 4, 20, 12)
        r.polyline(((4, 4), (20, 12)))

    yield "bounds-scaled", None, scaled

    def transfers(r):
        r.pat_blt(5, 6, 20, 10, 0x00F00021)
        info = struct.pack("<IiiHHIIiiII", 40, 2, 2, 1, 24, 0, 0, 0, 0, 0, 0)
        r.stretch_dib(30, 30, 8, 6, 0, 0, 2, 2, 0x00CC0020, 0, BitmapData("dib", info + bytes(range(16))))

    yield "transfers", None, transfers


def dib(width, height, depth, bits, colors=(), clr_used=None):
    header = struct.pack(
        "<IiiHHIIiiII", 40, width, height, 1, depth, 0, 0, 0, 0, len(colors) if clr_used is None else clr_used, 0
    )
    return BitmapData("dib", header + b"".join(struct.pack("<I", c) for c in colors) + bits)


SOURCE = dib(4, -3, 32, bytes((7 * i) % 256 for i in range(48)))
MASK = dib(4, -3, 1, bytes((0xA0, 0, 0, 0, 0x50, 0, 0, 0, 0xA0, 0, 0, 0)))
PACKED = dib(2, 2, 24, bytes(range(16)))


def more_scenarios():
    """Palettes, clipping, transfers, gradients and state, as native recorded them."""

    def advanced_once(r):
        r.set_graphics_mode(2)
        r.set_world_transform(1.5, 0, 0, 2.0, 3.0, 4.0)
        r.rectangle(10, 10, 30, 20)

    yield "advanced-once", None, advanced_once

    def advanced_modes(r):
        r.set_graphics_mode(2)
        r.set_graphics_mode(2)
        r.rectangle(10, 10, 30, 20)
        r.set_graphics_mode(1)
        r.rectangle(10, 10, 30, 20)

    yield "advanced-modes", None, advanced_modes

    def null_brush(r):
        r.select_object(r.create_brush(1, 0, 0))
        r.rectangle(10, 10, 30, 20)
        r.select_object(r.get_stock_object(5))
        r.select_object(r.get_stock_object(8))
        r.rectangle(40, 40, 60, 60)

    yield "null-brush", None, null_brush

    def clipped(r):
        r.intersect_clip_rect(10, 10, 40, 40)
        r.polyline(((0, 0), (60, 30)))
        r.exclude_clip_rect(10, 10, 40, 25)
        r.rectangle(0, 0, 60, 60)
        r.select_clip_region(None)
        r.rectangle(70, 70, 80, 80)

    yield "clipped-bounds", None, clipped

    def regions(r):
        g = r.create_region(RegionGeometry(((10, 10, 30, 30),)))
        b = r.get_stock_object(4)
        r.frame_region(g, b, 2, 3)
        r.invert_region(g)
        r.paint_region(g)
        r.ext_select_clip_region(g, 1)
        r.offset_clip_region(5, 6)
        r.set_meta_region()
        r.rectangle(0, 0, 50, 50)
        r.delete_object(g)

    yield "regions", None, regions

    def palettes(r):
        p = r.create_palette(PaletteEntries(((255, 0, 0, 0), (0, 255, 0, 0), (0, 0, 255, 0), (9, 9, 9, 1))))
        r.select_palette(p)
        r.realize_palette()
        r.set_palette_entries(PaletteUpdate(1, ((1, 2, 3, 0),)))
        r.resize_palette(6)
        r.animate_palette(PaletteUpdate(3, ((1, 2, 3, 0),)))
        r.select_palette(r.get_stock_object(15))
        r.delete_object(p)

    yield "palettes", None, palettes

    def transfers(r):
        r.dib_bit_blt(1, 2, 4, 3, 0, 0, 0x00CC0020, SOURCE)
        r.dib_bit_blt(10, 2, 4, 3, 1, 1, 0x00660046, SOURCE)
        r.set_stretch_mode(4)
        r.dib_stretch_blt(20, 2, 8, 6, 0, 0, 4, 3, 0x00CC0020, SOURCE)
        r.mask_blt(30, 2, 4, 3, 0, 0, 0xAACC0020, SOURCE, MASK, 0, 0, 2)
        r.plg_blt(((45, 1), (60, 6), (42, 12)), 0, 0, 4, 3, SOURCE)
        r.alpha_blend(1, 20, 8, 6, 0, 0, 4, 3, 0x00800000, SOURCE)
        r.transparent_blt(20, 20, 8, 6, 0, 0, 4, 3, 0x00030201, SOURCE)
        r.set_dib_to_device(40, 20, 2, 2, 0, 0, 0, 2, 0, PACKED)

    yield "transfers-all", None, transfers

    def gradients(r):
        v = ((1, 2, 0xFF00, 0, 0, 0), (30, 20, 0, 0xFF00, 0, 0), (5, 25, 0, 0, 0xFF00, 0))
        r.gradient_fill(0, v[:2], ((0, 1),))
        r.gradient_fill(2, v, ((0, 1, 2),))

    yield "gradients", None, gradients

    def state_more(r):
        r.set_map_mode(8)
        r.set_window_extent(100, 100)
        r.set_viewport_extent(100, 100)
        r.scale_window_extent(2, 1, 3, 2)
        r.set_viewport_origin(5, 6)
        r.offset_window_origin(3, 4)
        r.set_brush_origin(2, 3)
        r.set_polygon_fill_mode(2)
        r.set_miter_limit(4.5)
        r.set_layout(0)
        r.ext_flood_fill(10, 10, 0, 1)
        r.rectangle(10, 10, 30, 30)

    yield "state-more", None, state_more


def bitmap16(depth, width=8, height=8):
    stride = ((width * depth + 15) // 16) * 2
    data = bytes((53 * i + 7) % 256 for i in range(stride * height))
    return BitmapData("bitmap16", struct.pack("<hhhhBB", 0, width, height, stride, 1, depth) + data)


def section(depth, colors=(), *, height=-3, compression=0, masks=()):
    """The DIB a native probe's 4-pixel-wide DIB section held."""
    header = struct.pack("<IiiHHIIiiII", 40, 4, height, 1, depth, compression, 0, 0, 0, len(colors), 0)
    stride = ((4 * depth + 31) // 32) * 4
    bits = bytes((37 * i + 11) % 256 for i in range(stride * abs(height)))
    return BitmapData("dib", header + b"".join(struct.pack("<I", v) for v in (*masks, *colors)) + bits)


def gap_scenarios():
    """Fonts, pattern brushes, source depths, excluded clips and clip paths."""

    def fonts(r):
        for height, weight, italic, face, charset in (
            (-12, 400, 0, "Arial", 0),
            (20, 700, 1, "Courier New", 0),
            (-9, 0, 0, "", 1),
            (-30, 400, 0, "A Face Name Of Thirty-One Chars", 238),
        ):
            font = r.create_font(FontRequest(height, 0, 0, 0, weight, italic, 0, 0, charset, 0, 0, 0, 0, face))
            r.select_object(font)
            r.delete_object(font)
        r.select_object(r.get_stock_object(13))
        r.select_object(r.get_stock_object(17))

    yield "fonts", None, fonts

    def colour_patterns(r):
        white = r.get_stock_object(0)
        for depth in (1, 4, 8, 16, 24, 32):
            if depth in (1, 32):  # Native CreateBitmap fails for the others.
                r.select_object(r.create_pattern_brush(bitmap16(depth)))
            r.rectangle(0, 0, 10, 10)
            r.select_object(white)

    yield "colour-patterns", None, colour_patterns

    def source_depths(r):
        sources = (
            section(1, (0x000000, 0xFFFFFF)),
            section(1, (0x123456, 0xABCDEF)),
            section(4, tuple(0x111111 * i for i in range(16))),
            section(4, (0xFF0000, 0x00FF00, 0x0000FF)),
            section(8, tuple(0x010203 * i for i in range(256))),
            section(8, tuple(0x0A0B0C * i for i in range(5))),
            section(16),
            section(16, compression=3, masks=(0xF800, 0x07E0, 0x001F)),
            section(24),
            section(24, height=3),
            section(32, compression=3, masks=(0xFF0000, 0xFF00, 0xFF)),
        )
        for index, source in enumerate(sources):
            r.dib_bit_blt(5 * index, 2, 4, 3, 0, 0, 0x00CC0020, source)

    yield "source-depths", None, source_depths

    def excluded(left, top, right, bottom):
        def draw(r):
            r.intersect_clip_rect(10, 10, 50, 50)
            r.exclude_clip_rect(left, top, right, bottom)
            r.rectangle(0, 0, 60, 60)

        return draw

    yield "excluded-left", None, excluded(0, 0, 30, 60)
    yield "excluded-middle", None, excluded(20, 20, 40, 40)

    for variant in ("plain", "close", "flatten", "widen", "widen5", "close-widen"):

        def clip_path(r, variant=variant):
            if variant == "widen5":
                r.select_object(r.create_pen(0, 5, 0))
            r.begin_path()
            r.move_to(5, 5)
            r.line_to(40, 10)
            r.line_to(20, 40)
            if "close" in variant:
                r.close_figure()
            r.end_path()
            if variant == "flatten":
                r.flatten_path()
            if "widen" in variant:
                r.widen_path()
            r.select_clip_path(5)
            r.rectangle(0, 0, 60, 60)

        yield f"clip-path-{variant}", None, clip_path

    def pattern_brushes(r):
        mono = BitmapData("bitmap16", struct.pack("<hhhhBB", 0, 8, 8, 2, 1, 1) + bytes((0xAA, 0, 0x55, 0) * 4))
        r.select_object(r.create_pattern_brush(mono))
        r.rectangle(0, 0, 20, 20)
        colour = BitmapData(
            "bitmap16", struct.pack("<hhhhBB", 0, 4, 3, 16, 1, 32) + bytes((7 * i) % 256 for i in range(48))
        )
        r.select_object(r.create_pattern_brush(colour))
        r.rectangle(30, 0, 50, 20)
        r.select_object(r.create_dib_pattern_brush(5, 0, PACKED))
        r.rectangle(60, 0, 80, 20)

    yield "pattern-brushes", None, pattern_brushes

    def dib_pattern_pen(r):
        r.select_object(r.ext_create_pen(style=0x00010000, width=4, color=0, brush_style=6, bitmap=PACKED))
        r.line_to(30, 30)

    yield "dib-pattern-pen", None, dib_pattern_pen


SCENARIOS = [*scenarios(), *more_scenarios(), *gap_scenarios()]


@pytest.mark.parametrize(("name", "frame", "draw"), SCENARIOS, ids=[name for name, _, _ in SCENARIOS])
def test_recordings_match_native_bytes(name, frame, draw):
    recorder = Recorder()
    draw(recorder)
    assert recorder.to_bytes(frame=frame).hex() == NATIVE[name]


def test_every_native_recording_has_a_scenario():
    assert {name for name, _, _ in SCENARIOS} == set(NATIVE)


def test_recordings_play_back():
    recorder = Recorder()
    brush = recorder.create_brush(0, 0x0000FF, 0)
    recorder.select_object(brush)
    recorder.rectangle(2, 2, 10, 8)
    # A frame covering the 128-pixel canvas plays the picture 1:1.
    metafile = Metafile.from_bytes(recorder.to_bytes(frame=(0, 0, 3388, 3383)))
    context = RasterContext(128, 128, background=(255, 255, 255), trace_calls=False)
    play(metafile, context, rect=(0, 0, 128, 128))
    image = context.image.convert("RGB")
    # The recorded inclusive box plays back to the compatible-mode extent.
    assert [image.getpixel(point) for point in ((5, 5), (9, 7), (10, 8))] == [
        (255, 0, 0),
        (0, 0, 0),
        (255, 255, 255),
    ]


def test_unrecorded_calls_are_refused_before_anything_is_written():
    recorder = Recorder()
    with pytest.raises(UnsupportedOperation):
        recorder.text_out(0, 0, b"x")
    assert recorder.records == []


@pytest.mark.parametrize(
    ("call", "args", "expected"),
    [
        # Native current positions after AngleArc: the exact end, floored.
        ("angle_arc", (60, 60, 10, 30.0, 120.0), (51, 55)),
        ("angle_arc", (60, 60, 10, 0.0, 90.0), (60, 50)),
        ("angle_arc", (60, 60, 10, 45.0, -60.0), (69, 62)),
        ("angle_arc", (50, 50, 17, 200.0, 75.0), (51, 66)),
        ("angle_arc", (50, 50, 17, 10.0, 350.0), (67, 50)),
        ("angle_arc", (40, 40, 5, 123.0, 1.5), (37, 35)),
        ("angle_arc", (40, 40, 9, 300.0, -200.0), (38, 31)),
        # ArcTo ends on the recorded inclusive box's ellipse, floored.
        ("arc_to", (10, 10, 40, 30, 40, 20, 10, 10), (14, 12)),
        ("arc_to", (5, 7, 60, 50, 0, 0, 60, 60), (47, 45)),
    ],
)
def test_arcs_leave_the_native_current_position(call, args, expected):
    recorder = Recorder()
    recorder.move_to(0, 0)
    getattr(recorder, call)(*args)
    recorder.polyline_to(((300, 300),))
    # The following PolylineTo's bounds start at the current position.
    assert recorder.records[-1].bounds[:2] == expected


def test_native_dib_pattern_pens_play_despite_their_header_marker():
    # Native recording writes 0x20000000 in place of the pen bitmap's header size.
    metafile = Metafile.from_bytes(bytes.fromhex(NATIVE["dib-pattern-pen"]))
    context = RasterContext(64, 64, background=(255, 255, 255), trace_calls=False)
    assert play(metafile, context, rect=(0, 0, 64, 64)) == ()
