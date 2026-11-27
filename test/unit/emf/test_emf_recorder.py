"""EMF recording. Expected bytes are native recordings of the same calls.

``native_recordings.json`` holds complete files Windows wrote for each
scenario through CreateEnhMetaFile on the reference DC.
"""

import json
import struct
from pathlib import Path

import pytest

from pillow_wmf.emf import Metafile, Recorder, play
from pillow_wmf.font import FontFace
from pillow_wmf.gdi import UnsupportedOperation
from pillow_wmf.objects import BitmapData, FontRequest, GlyphIndices, PaletteEntries, PaletteUpdate, RegionGeometry
from pillow_wmf.raster import RasterContext
from pillow_wmf.text import FontCollection
from pillow_wmf.wmf import Metafile as WmfMetafile
from pillow_wmf.wmf.player import play as play_wmf

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

    def angle_arc_turns(r):
        # Sweeps of a full turn or more: the bounds and current position.
        for args in (
            (60, 60, 10, 30.0, 360.0),
            (60, 60, 10, 90.0, 1080.0),
            (50, 50, 17, 45.0, 400.0),
            (50, 50, 17, 300.0, -540.0),
        ):
            r.move_to(0, 0)
            r.angle_arc(*args)
            r.polyline_to(((300, 300),))
        r.move_to(70, 70)
        r.angle_arc(70, 70, 20, 10.0, 725.0)

    yield "angle-arc-turns", None, angle_arc_turns

    def null_selections(r):
        # Null object and palette selections fail without a record.
        r.rectangle(0, 0, 10, 10)
        r.select_object(None)
        r.rectangle(20, 0, 30, 10)
        r.select_palette(None)
        r.rectangle(40, 0, 50, 10)

    yield "null-selections", None, null_selections

    def clip_path_shapes(r):
        # SelectClipPath of paths holding shapes and curves; each clipped
        # polyline's bounds give the clip region's box.
        shapes = (
            lambda: r.ellipse(5, 5, 40, 30),
            lambda: r.round_rect(6, 4, 41, 33, 12, 9),
            lambda: r.pie(5, 5, 41, 31, 40, 5, 5, 6),
            lambda: r.chord(3, 7, 44, 30, 2, 30, 44, 8),
            lambda: (r.move_to(2, 2), r.arc_to(10, 10, 50, 35, 50, 20, 10, 12), r.line_to(2, 2)),
            lambda: (r.move_to(30, 30), r.angle_arc(20, 20, 13, 30.0, 200.0)),
            lambda: (r.move_to(4, 4), r.poly_bezier_to(((60, 0), (0, 60), (50, 50)))),
            lambda: (r.arc(5, 5, 45, 35, 45, 10, 5, 30), r.ellipse(30, 30, 45, 50)),
        )
        for shape in shapes:
            r.save_dc()
            r.begin_path()
            shape()
            r.end_path()
            r.select_clip_path(5)
            r.polyline(((0, 0), (90, 0), (90, 90), (0, 90), (0, 0)))
            r.restore_dc(-1)
        r.set_graphics_mode(2)
        r.set_world_transform(0.9, 0.4, -0.4, 0.9, 20, 0)
        r.begin_path()
        r.ellipse(5, 5, 40, 30)
        r.end_path()
        r.select_clip_path(5)
        r.polyline(((-50, -50), (90, -50), (90, 90), (-50, 90), (-50, -50)))

    yield "clip-path-shapes", None, clip_path_shapes

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

    def mask_blt_patterns(r):
        # Source-less MaskBlt records nothing, with or without a mask.
        r.select_object(r.create_brush(2, 0x0000FF, 5))
        mono = dib(8, 6, 1, bytes((0xA5, 0, 0, 0, 0x5A, 0, 0, 0) * 3), colors=(0, 0xFFFFFF))
        r.mask_blt(4, 4, 8, 6, 0, 0, 0xAAF00021, None, mono, 0, 0, 2)
        r.mask_blt(20, 4, 8, 6, 0, 0, 0x55F00021, None, mono, 2, 1, 2)
        r.mask_blt(36, 4, 8, 6, 0, 0, 0xAAF00021, None, None, 0, 0, 2)

    yield "mask-blt-patterns", None, mask_blt_patterns

    def compressed_pattern_brushes(r):
        # DIB pattern brushes from RLE DIBs fail to be created.
        palette = b"".join(struct.pack("<I", value) for value in (0x0000FF, 0x00FF00, 0xFF0000, 0xFFFFFF))
        for compression, bits in (
            (1, bytes((4, 1, 4, 2, 0, 0, 8, 3, 0, 0, 2, 0, 0, 2, 2, 1, 0, 0, 0, 1))),
            (2, bytes((8, 0x12, 0, 0, 8, 0x30, 0, 0, 0, 3, 0x12, 0x30, 0, 0, 0, 1))),
        ):
            depth = 8 if compression == 1 else 4
            header = struct.pack("<IiiHHIIiiII", 40, 8, 4, 1, depth, compression, len(bits), 0, 0, 4, 0)
            r.select_object(r.create_dib_pattern_brush(5, 0, BitmapData("dib", header + palette + bits)))
            r.rectangle(0, 0, 20, 20)
            r.select_object(r.get_stock_object(0))

    yield "compressed-pattern-brushes", None, compressed_pattern_brushes

    def clip_path_widened_shapes(r):
        # SelectClipPath after widening shapes, arcs and extended-pen paths.
        r.select_object(r.create_pen(0, 5, 0))
        shapes = (
            lambda: r.ellipse(5, 5, 40, 30),
            lambda: r.round_rect(6, 4, 41, 33, 12, 9),
            lambda: r.pie(5, 5, 41, 31, 40, 5, 5, 6),
            lambda: (r.move_to(2, 2), r.arc_to(10, 10, 50, 35, 50, 20, 10, 12), r.line_to(2, 2)),
            lambda: r.rectangle(8, 8, 40, 30),
        )
        frame = ((0, 0), (90, 0), (90, 90), (0, 90), (0, 0))
        for shape in shapes:
            r.save_dc()
            r.begin_path()
            shape()
            r.end_path()
            r.widen_path()
            r.select_clip_path(5)
            r.polyline(frame)
            r.restore_dc(-1)
        for style in (0x00010000 | 0x0200 | 0x2000, 0x00010000 | 0x0100 | 0x1000):
            r.select_object(r.ext_create_pen(style=style, width=7, color=0))
            r.save_dc()
            r.begin_path()
            r.move_to(10, 10)
            r.line_to(40, 15)
            r.line_to(20, 35)
            r.end_path()
            r.widen_path()
            r.select_clip_path(5)
            r.polyline(frame)
            r.restore_dc(-1)

    yield "clip-path-widened-shapes", None, clip_path_widened_shapes

    def clip_path_inside_frame(r):
        # SelectClipPath of paths built and widened with inside-frame pens,
        # and of unwidened paths built with inside-frame and mitred pens.
        frame = ((-60, -60), (120, -60), (120, 120), (-60, 120), (-60, -60))
        pens = (
            lambda: r.create_pen(6, 7, 0),
            lambda: r.ext_create_pen(style=0x00010000 | 0x2000 | 6, width=7, color=0),
        )
        shapes = (
            lambda: (r.move_to(10, 10), r.line_to(40, 15), r.line_to(20, 35)),
            lambda: (r.move_to(10, 10), r.line_to(40, 15), r.line_to(20, 35), r.close_figure()),
            lambda: r.rectangle(8, 8, 40, 30),
            lambda: r.ellipse(5, 5, 40, 30),
            lambda: r.round_rect(6, 4, 41, 33, 12, 9),
            lambda: r.pie(5, 5, 41, 31, 40, 5, 5, 6),
            lambda: r.rectangle(8, 8, 13, 30),
            lambda: r.ellipse(8, 8, 13, 30),
            lambda: r.pie(8, 8, 13, 30, 13, 8, 8, 20),
            lambda: r.chord(3, 7, 44, 30, 2, 30, 44, 8),
            lambda: (r.move_to(2, 2), r.arc_to(10, 10, 50, 35, 50, 20, 10, 12), r.line_to(2, 2)),
            lambda: (r.arc(5, 5, 45, 35, 45, 10, 5, 30), r.close_figure()),
        )

        def clipped(shape, widen=True):
            r.save_dc()
            r.begin_path()
            shape()
            r.end_path()
            if widen:
                r.widen_path()
            r.select_clip_path(5)
            r.polyline(frame)
            r.restore_dc(-1)

        for pen in pens:
            r.select_object(pen())
            for shape in shapes:
                clipped(shape)
            clipped(shapes[0], widen=False)
            clipped(shapes[2], widen=False)
            r.select_object(r.get_stock_object(7))
        r.select_object(r.ext_create_pen(style=0x00010000 | 0x2000, width=7, color=0))
        clipped(shapes[0], widen=False)
        r.select_object(r.get_stock_object(7))
        # Scaled, then rotated, inside-frame pens.
        r.select_object(r.create_pen(6, 5, 0))
        r.save_dc()
        r.set_map_mode(8)
        r.set_window_extent(10, 10)
        r.set_viewport_extent(15, 20)
        clipped(shapes[2])
        clipped(shapes[3])
        r.restore_dc(-1)
        r.set_graphics_mode(2)
        r.set_world_transform(0.9, 0.4, -0.4, 0.9, 20, 0)
        clipped(shapes[2])
        clipped(shapes[3])
        clipped(shapes[0])

    yield "clip-path-inside-frame", None, clip_path_inside_frame

    def arc_to_inside_frame(r):
        # ArcTo with an inside-frame pen: clip paths and current positions,
        # counterclockwise and clockwise, in a covered box, and in GM_ADVANCED.
        frame = ((-60, -60), (120, -60), (120, 120), (-60, 120), (-60, -60))
        r.select_object(r.create_pen(6, 7, 0))
        boxes = ((10, 10, 50, 35, 50, 20, 10, 12), (10, 10, 15, 35, 15, 20, 10, 12))

        def run():
            for box in boxes:
                r.save_dc()
                r.begin_path()
                r.move_to(2, 2)
                r.arc_to(*box)
                r.line_to(2, 2)
                r.end_path()
                r.select_clip_path(5)
                r.polyline(frame)
                r.restore_dc(-1)
                r.move_to(0, 0)
                r.arc_to(*box)
                r.polyline_to(((300, 300),))

        for direction in (1, 2):
            r.set_arc_direction(direction)
            run()
        r.set_arc_direction(1)
        r.set_graphics_mode(2)
        run()
        r.set_world_transform(0.9, 0.4, -0.4, 0.9, 20, 0)
        run()

    yield "arc-to-inside-frame", None, arc_to_inside_frame

    def odd_arc_to(r):
        # The clockwise ArcTo on an odd-sized box, then its current position.
        r.set_arc_direction(2)
        for box, radials in (((10, 10, 41, 31), (40, 10, 10, 30)), ((10, 10, 41, 31), (10, 30, 40, 10))):
            r.move_to(0, 0)
            r.arc_to(*box, *radials)
            r.polyline_to(((300, 300),))

    yield "odd-arc-to", None, odd_arc_to


TEXT_FACE = "Pillow WMF Test"
FONTS = FontCollection(FontFace.from_path(path) for path in sorted((Path(__file__).parents[2] / "fonts").glob("*.ttf")))


def text_font(r, height=-12, face=TEXT_FACE, **fields):
    font = r.create_font(FontRequest(height=height, weight=400, quality=3, face_name=face, **fields))
    r.select_object(font)
    return font


def text_scenarios():
    def text_calls(r):
        text_font(r)
        r.text_out(10, 20, b"AB A")
        r.ext_text_out(10, 40, b"BA")
        r.ext_text_out(10, 60, "AB")
        r.ext_text_out(60, 60, "A B", advances=(7, 3, 9))
        r.ext_text_out(60, 80, GlyphIndices((2, 3)), advances=(8, 6))
        r.text_out(0, 0, b"")

    yield "text-calls", None, text_calls

    def text_options(r):
        text_font(r)
        r.set_background_mode(2)
        r.set_background_color(0x00C0E0F0)
        r.ext_text_out(10, 20, "AB", 2, (8, 18, 40, 36))
        r.ext_text_out(10, 40, "BA", 4, (8, 38, 20, 50))
        r.ext_text_out(10, 60, "A", 6, (30, 58, 20, 70))
        r.set_background_mode(1)
        r.ext_text_out(50, 20, "AB", 0x2000, advances=(6, 2, 8, -3))
        r.ext_text_out(50, 40, "", 2, (50, 40, 60, 48))

    yield "text-options", None, text_options

    def text_alignment(r):
        text_font(r)
        for index, align in enumerate((6, 2, 8, 24, 0x0E)):
            r.set_text_alignment(align)
            r.ext_text_out(64, 12 + 16 * index, "AB A")
        r.set_text_alignment(1)
        r.move_to(10, 100)
        r.ext_text_out(0, 0, "AB")
        r.ext_text_out(0, 0, "B")
        r.line_to(90, 120)
        r.set_text_alignment(0)
        r.set_text_character_extra(3)
        r.ext_text_out(10, 110, "AB")
        r.set_text_character_extra(0)
        r.set_text_justification(1, 6)
        r.ext_text_out(60, 110, "A A")

    yield "text-alignment", None, text_alignment

    def text_mapping(r):
        r.set_map_mode(8)
        r.set_window_extent(200, 200)
        r.set_viewport_extent(128, 100)
        text_font(r, -20)
        r.text_out(10, 20, b"AB A")
        r.ext_text_out(10, 60, "BA", advances=(13, 9))
        r.ext_text_out(10, 100, "AB", 2, (8, 98, 60, 130))
        text_font(r, 16, face="Pillow WMF Encoding")
        r.text_out(10, 140, b"A\xe9B")

    yield "text-mapping", None, text_mapping

    def text_advanced(r):
        r.set_graphics_mode(2)
        r.set_world_transform(0.9, 0.4, -0.4, 0.9, 30.0, 10.0)
        text_font(r, -10)
        r.ext_text_out(0, 0, "AB A")
        r.set_background_mode(2)
        r.ext_text_out(0, 20, "BA")
        r.set_world_transform(1.5, 0.0, 0.0, 0.75, 0.0, 60.0)
        r.ext_text_out(4, 4, "AB", advances=(9, 7))
        r.set_graphics_mode(1)
        r.set_world_transform(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        text_font(r, -12, escapement=300, orientation=300, underline=1)
        r.ext_text_out(20, 110, "AB A")

    yield "text-advanced", None, text_advanced

    def text_bounds(r):
        r.set_graphics_mode(2)
        text_font(r, -10)
        for row, matrix in enumerate(((0.9, 0.4, -0.4, 0.9), (1.0, 0.0, 0.45, 1.0))):
            r.set_world_transform(*matrix, 10.0, 10.0 + 60.0 * row)
            for mode in (1, 2):
                r.set_background_mode(mode)
                for column, text in enumerate(("BA", "AB", "B", "A B")):
                    r.ext_text_out(28 * column, 24 * (mode - 1), text)

    yield "text-bounds", None, text_bounds


# A WMF of legacy-bitmap BitBlt and StretchBlt records, with and without a
# source, which the probe plays into its recording DC with PlayMetaFile.
LEGACY_BLITS = bytes.fromhex(
    "0100090000035400000000001800000000001600000022092000cc000000000002000200040004000000020002000600011803020106"
    "05040908070c0b0a18000000230b2000cc0002000200000000000400060004000a0000000200020006000118030201060504090807"
    "0c0b0a0c00000022092100f00000000000000003000300040014000e000000230b49005a00020002000000000000000500050004001e"
    "00030000000000"
)

# Legacy-bitmap BitBlt from Bitmap16 sources of each depth: 1, 4, 8, 16, 24, 32.
LEGACY_DEPTHS = bytes.fromhex(
    "010009000003c300000000002e00000000001300000022092000cc00000000000300050028000400000005000300020001015000"
    "a80050001600000022092000cc00000000000300050028001400000005000300040001040b61c0001c72d0002d83e00019000000"
    "22092000cc0000000000030005002800240000000500030006000108003b76b1ec00417cb7f22d0082bdf8336e001f0000002209"
    "2000cc000000000003000500280034000000050003000a00011000003b197632b14bec6441297c42b75bf2742d8e8252bd6bf884"
    "339e6eb72800000022092000cc00000000000300050028004400000005000300100001180000003b1908763210b14b18ec642000"
    "4129007c4208b75b10f274182d8e2000825200bd6b08f88410339e186eb720002e00000022092000cc0000000000030005002800"
    "540000000500030014000120000000003b19080076321000b14b1800ec642000412900087c420808b75b1008f27418082d8e2008"
    "82520010bd6b0810f8841010339e18106eb72010030000000000"
)


def completion_scenarios():
    def advanced(r):
        r.set_graphics_mode(2)
        r.set_world_transform(1.5, 0, 0, 2.0, 3.0, 4.0)
        r.rectangle(10, 10, 30, 20)
        r.ellipse(10, 10, 30, 20)
        r.set_graphics_mode(2)

    yield "advanced", None, advanced

    def advanced_modify(r):
        r.set_graphics_mode(2)
        r.modify_world_transform(2, 0, 0, 2, 1, 1, 2)
        r.modify_world_transform(1, 0, 0.5, 1, 0, 0, 3)
        r.rectangle(10, 10, 30, 20)
        r.modify_world_transform(1, 0, 0, 1, 0, 0, 1)
        r.set_world_transform(1, 0, 0, 1, 0, 0)
        r.set_graphics_mode(1)
        r.ellipse(40, 40, 60, 60)

    yield "advanced-modify", None, advanced_modify

    def curves(r):
        r.set_arc_direction(2)
        r.move_to(5, 5)
        r.arc_to(10, 10, 40, 30, 40, 20, 10, 10)
        r.angle_arc(60, 60, 10, 30.0, 120.0)
        r.chord(70, 5, 100, 30, 100, 15, 70, 5)
        r.polyline_to(((1, 90), (20, 100)))
        r.poly_bezier_to(((30, 90), (40, 110), (50, 100)))
        r.poly_polyline((((5, 5), (20, 5), (20, 20)), ((60, 60), (70, 60))))
        r.poly_draw(((80, 80), (90, 80), (90, 90), (80, 90)), bytes((6, 2, 2, 3)))

    yield "curves", None, curves

    def paths_more(r):
        r.begin_path()
        r.move_to(5, 5)
        r.line_to(40, 10)
        r.close_figure()
        r.end_path()
        r.flatten_path()
        r.widen_path()
        r.select_clip_path(5)
        r.begin_path()
        r.line_to(1, 1)
        r.abort_path()
        r.rectangle(0, 0, 60, 60)

    yield "paths-more", None, paths_more

    def arc_positions(r):
        for x, y, radius, start, sweep in (
            (60, 60, 10, 30.0, 120.0),
            (60, 60, 10, 0.0, 90.0),
            (60, 60, 10, 45.0, -60.0),
            (50, 50, 17, 200.0, 75.0),
            (50, 50, 17, 10.0, 350.0),
            (40, 40, 5, 123.0, 1.5),
            (40, 40, 9, 300.0, -200.0),
        ):
            r.move_to(0, 0)
            r.angle_arc(x, y, radius, start, sweep)
            r.polyline_to(((300, 300),))
        r.set_arc_direction(2)
        for box, radials in (
            ((10, 10, 40, 30), (40, 20, 10, 10)),
            ((10, 10, 41, 31), (40, 10, 10, 30)),
            ((5, 7, 60, 50), (0, 0, 60, 60)),
        ):
            r.move_to(0, 0)
            r.arc_to(*box, *radials)
            r.polyline_to(((300, 300),))
        r.set_arc_direction(1)
        r.move_to(0, 0)
        r.arc_to(10, 10, 40, 30, 40, 20, 10, 10)
        r.polyline_to(((300, 300),))

    yield "arc-positions", None, arc_positions

    def completion(r):
        r.offset_viewport_origin(3, 4)
        r.set_map_mode(8)
        r.set_window_extent(100, 100)
        r.set_viewport_extent(100, 100)
        r.scale_viewport_extent(2, 3, 4, 5)
        r.set_map_mode(1)
        r.set_color_adjustment(1, 2, 12000, 11000, 9000, 100, 9000, 10, -20, 30, -40)
        r.set_mapper_flags(1)
        r.escape(15, b"note\0")  # MFCOMMENT
        r.escape(8)  # QUERYESCSUPPORT
        r.begin_path()
        r.rectangle(10, 10, 40, 30)
        r.end_path()
        r.stroke_and_fill_path()
        play_wmf(WmfMetafile.from_bytes(LEGACY_BLITS), r, strict=True)
        # PlayMetaFile ends by restoring the DC's selections and clip.
        r.select_object(r.get_stock_object(7))  # BLACK_PEN
        r.select_object(r.get_stock_object(0))  # WHITE_BRUSH
        r.select_palette(r.get_stock_object(15))  # DEFAULT_PALETTE
        r.select_clip_region(None)

    yield "completion", None, completion

    def legacy_depths(r):
        play_wmf(WmfMetafile.from_bytes(LEGACY_DEPTHS), r, strict=True)
        r.select_object(r.get_stock_object(7))
        r.select_object(r.get_stock_object(0))
        r.select_palette(r.get_stock_object(15))
        r.select_clip_region(None)

    yield "legacy-depths", None, legacy_depths

    def transformed_shapes(m11, m12, m21, m22):
        def draw(r):
            r.set_graphics_mode(2)
            r.set_world_transform(m11, m12, m21, m22, 20.0, 10.0)
            r.rectangle(10, 10, 30, 20)
            r.ellipse(40, 10, 60, 24)
            r.round_rect(10, 30, 30, 44, 6, 4)
            r.arc(40, 30, 60, 44, 60, 37, 40, 30)
            r.chord(10, 50, 30, 64, 30, 57, 10, 50)
            r.pie(40, 50, 60, 64, 60, 57, 40, 50)
            r.polygon(((10, 70), (25, 72), (18, 80)))
            r.polyline(((40, 70), (55, 75), (48, 82)))
            r.move_to(5, 85)
            r.line_to(30, 90)

        return draw

    yield "sheared-shapes", None, transformed_shapes(1.0, 0.0, 0.45, 1.0)
    yield "rotated-shapes", None, transformed_shapes(0.9, 0.4, -0.4, 0.9)

    def compatible_after_world(r):
        r.set_graphics_mode(2)
        r.set_world_transform(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        r.set_graphics_mode(1)
        r.rectangle(10, 10, 30, 20)
        r.ellipse(40, 10, 60, 30)
        r.set_graphics_mode(2)
        r.modify_world_transform(1, 0, 0, 1, 0, 0, 1)
        r.set_graphics_mode(1)
        r.rectangle(10, 40, 30, 50)
        r.ellipse(40, 40, 60, 60)

    yield "compatible-after-world", None, compatible_after_world

    def flood_and_comment(r):
        r.flood_fill(10, 10, 0x00FF00)
        r.gdi_comment(b"note\0")

    yield "flood-and-comment", None, flood_and_comment

    shapes = {
        "rectangle": lambda r: r.rectangle(10, 10, 31, 23),
        "ellipse": lambda r: r.ellipse(10, 10, 31, 23),
        "round-rect": lambda r: r.round_rect(10, 10, 31, 23, 6, 4),
        "arc": lambda r: r.arc(10, 10, 31, 23, 31, 16, 10, 10),
        "chord": lambda r: r.chord(10, 10, 31, 23, 31, 23, 10, 10),
        "pie": lambda r: r.pie(10, 10, 31, 23, 31, 23, 10, 10),
    }
    for shape, draw_shape in shapes.items():
        for world in (False, True):

            def draw(r, draw_shape=draw_shape, world=world):
                if world:
                    r.set_graphics_mode(2)
                    r.set_world_transform(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
                    r.set_graphics_mode(1)
                draw_shape(r)

            yield f"compatible-{shape}{'-after-world' if world else ''}", None, draw

    resets = {
        "set": lambda r: r.set_world_transform(1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
        "modify": lambda r: r.modify_world_transform(1, 0, 0, 1, 0, 0, 1),
        "modify-set": lambda r: (
            r.modify_world_transform(1, 0, 0, 1, 0, 0, 1),
            r.set_world_transform(1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
        ),
    }
    for shape in ("rectangle", "ellipse"):
        for reset_name, reset in resets.items():

            def draw(r, shape=shapes[shape], reset=reset):
                r.set_graphics_mode(2)
                r.set_world_transform(1.0, 0.0, 0.45, 1.0, 0.0, 0.0)
                reset(r)
                r.set_graphics_mode(1)
                shape(r)

            yield f"compatible-{shape}-after-shear-{reset_name}", None, draw


def degenerate_scenarios():
    """Curved shapes with empty logical boxes: all at once per mode, and each alone rotated."""
    boxes = {"w0": (20, 10, 20, 40), "h0": (10, 20, 40, 20), "both0": (20, 20, 20, 20), "w1": (20, 10, 21, 40)}
    modes = {"compatible": None, "identity": (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), "scaled": (1.5, 0.0, 0.0, 0.5, 0.0, 10.0)}

    def shape(r, call, box):
        if call == "round_rect":
            r.round_rect(*box, 8, 8)
        elif call == "ellipse":
            r.ellipse(*box)
        elif call == "angle_arc":
            r.angle_arc(box[0], box[1], 0, 30.0, 120.0)
        else:
            getattr(r, call)(*box, 50, 5, 5, 50)

    def degenerate(transform):
        def draw(r):
            if transform is not None:
                r.set_graphics_mode(2)
                r.set_world_transform(*transform)
            for box in boxes.values():
                for call in ("arc", "chord", "pie", "arc_to", "round_rect", "ellipse", "angle_arc"):
                    shape(r, call, box)

        return draw

    for mode, transform in modes.items():
        yield f"degenerate-shapes-{mode}", None, degenerate(transform)

    def rotated(call, box):
        def draw(r):
            r.set_graphics_mode(2)
            r.set_world_transform(0.866, 0.5, -0.5, 0.866, 20.0, 0.0)
            shape(r, call, box)

        return draw

    for box_name, box in boxes.items():
        for call in ("arc", "chord", "pie", "round_rect", "ellipse", "angle_arc"):
            yield f"degenerate-rotated-{box_name}-{call}", None, rotated(call, box)


SCENARIOS = [
    *scenarios(),
    *more_scenarios(),
    *gap_scenarios(),
    *text_scenarios(),
    *completion_scenarios(),
    *degenerate_scenarios(),
]


@pytest.mark.parametrize(("name", "frame", "draw"), SCENARIOS, ids=[name for name, _, _ in SCENARIOS])
def test_recordings_match_native_bytes(name, frame, draw):
    recorder = Recorder(fonts=FONTS)
    draw(recorder)
    assert recorder.to_bytes(frame=frame).hex() == defined_bytes(bytes.fromhex(NATIVE[name])).hex()


def defined_bytes(data: bytes) -> bytes:
    """Zero what GDI leaves uninitialized: the padding after an odd-length text string."""
    data = bytearray(data)
    position = 0
    while position < len(data):
        kind, size = struct.unpack_from("<II", data, position)
        if kind == 84:  # EMR_EXTTEXTOUTW
            chars, offset = struct.unpack_from("<II", data, position + 44)
            if chars % 2:
                start = position + offset + 2 * chars
                data[start : start + 2] = bytes(2)
        position += size
    return bytes(data)


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


def test_font_limited_text_is_refused_before_anything_is_written():
    # Without the face, the recording DC cannot measure the text it records.
    recorder = Recorder(fonts=FontCollection([]))
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
