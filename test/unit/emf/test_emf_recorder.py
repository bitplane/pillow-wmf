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
from pillow_wmf.objects import BitmapData, RegionGeometry
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


SCENARIOS = list(scenarios())


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
