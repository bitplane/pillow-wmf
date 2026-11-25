import random
import struct
from dataclasses import replace

import pytest

from pillow_wmf import Call, Handle, PlaybackError, TraceContext, UnsupportedOperation
from pillow_wmf.emf import FormatError, Limits, LogFont, Metafile, UnknownRecord, bitmaps, fixed, text, variable
from pillow_wmf.emf.player import play
from pillow_wmf.numeric import float32
from pillow_wmf.objects import (
    BitmapData,
    EncodedText,
    FontRequest,
    GlyphIndices,
    PaletteEntries,
    PaletteUpdate,
    RegionGeometry,
)

DIB = bytes.fromhex("28000000 01000000 01000000 0100 1800 00000000 04000000 00000000 00000000 00000000 00000000")
PIXEL = bytes.fromhex("0000ff00")
WHITE_BRUSH = 0x80000000
NULL_PEN = 0x80000008
SYSTEM_FONT = 0x8000000D


# A frame of 128 reference pixels; fitted to 128 pixels it is exactly 1:1.
UNIT_FRAME = (0, 0, 3388, 3383)
IDENTITY = dict(m11=1.0, m12=0.0, m21=0.0, m22=1.0, dx=0.0, dy=0.0)
PREAMBLE = [Call.make("set_graphics_mode", mode=2), Call.make("set_world_transform", **IDENTITY)]


def run(records, **options):
    """Play at 1:1 and return the calls after the playback preamble."""
    trace = TraceContext()
    omissions = play(Metafile.build(records, frame=UNIT_FRAME), trace, rect=(0, 0, 128, 128), **options)
    assert trace.calls[:2] == PREAMBLE
    return trace.calls[2:], omissions


def test_state_and_drawing_records_translate_to_gdi_calls():
    calls, omissions = run(
        [
            fixed.SetBkMode(1),
            fixed.SetBkColor(0x00112233),
            fixed.SetTextColor(0x00445566),
            fixed.SetTextAlign(24),
            fixed.SetPolyFillMode(2),
            fixed.SetROP2(7),
            fixed.SetStretchBltMode(3),
            fixed.SetMapperFlags(1),
            fixed.SetLayout(0),
            fixed.SetTextJustification(10, 2),
            fixed.IntersectClipRect(0, 0, 50, 60),
            fixed.ExcludeClipRect(1, 2, 3, 4),
            fixed.OffsetClipRgn(5, 6),
            fixed.MoveToEx(1, 2),
            fixed.LineTo(70_000, -70_000),
            fixed.Rectangle(1, 2, 3, 4),
            fixed.Ellipse(1, 2, 3, 4),
            fixed.RoundRect(1, 2, 3, 4, 5, 6),
            fixed.Arc(1, 2, 3, 4, 5, 6, 7, 8),
            fixed.Chord(1, 2, 3, 4, 5, 6, 7, 8),
            fixed.Pie(1, 2, 3, 4, 5, 6, 7, 8),
            fixed.SetPixelV(1, 2, 0xFF),
            fixed.ExtFloodFill(1, 2, 0, 1),
            fixed.RealizePalette(),
            variable.Polygon((0, 0, 9, 9), ((0, 0), (9, 0), (9, 9))),
            variable.Polygon16((0, 0, 9, 9), ((0, 0), (9, 9))),
            variable.Polyline((0, 0, 9, 9), ((0, 0), (9, 9))),
            variable.Polyline16((0, 0, 9, 9), ((0, 0), (9, 9))),
            variable.PolyPolygon((0, 0, 9, 9), (((0, 0), (9, 0), (9, 9)), ((1, 1),))),
            variable.PolyPolygon16((0, 0, 9, 9), (((0, 0), (9, 0), (9, 9)),)),
        ],
        strict=True,
    )
    assert omissions == ()
    rect = {"left": 1, "top": 2, "right": 3, "bottom": 4}
    box = rect | {"start_x": 5, "start_y": 6, "end_x": 7, "end_y": 8}
    assert calls == [
        Call.make("set_background_mode", mode=1),
        Call.make("set_background_color", color=0x00112233),
        Call.make("set_text_color", color=0x00445566),
        Call.make("set_text_alignment", alignment=24),
        Call.make("set_polygon_fill_mode", mode=2),
        Call.make("set_rop2", mode=7),
        Call.make("set_stretch_mode", mode=3),
        Call.make("set_mapper_flags", flags=1),
        Call.make("set_layout", layout=0),
        Call.make("set_text_justification", break_count=2, break_extra=10),
        Call.make("intersect_clip_rect", left=0, top=0, right=50, bottom=60),
        Call.make("exclude_clip_rect", **rect),
        Call.make("offset_clip_region", x=5, y=6),
        Call.make("move_to", x=1, y=2),
        Call.make("line_to", x=70_000, y=-70_000),
        Call.make("rectangle", **rect),
        Call.make("ellipse", **rect),
        Call.make("round_rect", **rect, ellipse_width=5, ellipse_height=6),
        Call.make("arc", **box),
        Call.make("chord", **box),
        Call.make("pie", **box),
        Call.make("set_pixel", x=1, y=2, color=0xFF),
        Call.make("ext_flood_fill", x=1, y=2, color=0, mode=1),
        Call.make("realize_palette"),
        Call.make("polygon", points=((0, 0), (9, 0), (9, 9))),
        Call.make("polygon", points=((0, 0), (9, 9))),
        Call.make("polyline", points=((0, 0), (9, 9))),
        Call.make("polyline", points=((0, 0), (9, 9))),
        Call.make("poly_polygon", polygons=(((0, 0), (9, 0), (9, 9)), ((1, 1),))),
        Call.make("poly_polygon", polygons=(((0, 0), (9, 0), (9, 9)),)),
    ]


def test_objects_use_explicit_slots():
    calls, omissions = run(
        [
            fixed.CreatePen(3, 0, 2, 0, 0xFF),
            fixed.CreateBrushIndirect(1, 2, 0x00FF00, 4),
            variable.CreatePalette(2, ((1, 2, 3, 0),)),
            variable.ExtCreateFontIndirectW(
                4, LogFont(height=-12, face_name="Arial".encode("utf-16-le").ljust(64, b"\0"))
            ),
            fixed.SelectObject(3),
            fixed.SelectObject(1),
            fixed.SelectObject(4),
            fixed.SelectPalette(2),
            fixed.DeleteObject(3),
            fixed.SelectObject(3),  # Deleted: the native lookup fails without a call.
            fixed.DeleteObject(3),
            fixed.SelectObject(0),  # Slot 0 is the metafile itself.
            fixed.SelectObject(99),
            fixed.CreatePen(0, 0, 1, 0, 0),  # Slot 0 cannot hold an object.
        ],
        strict=True,
    )
    assert omissions == ()
    assert [call.name for call in calls] == [
        "create_pen",
        "create_brush",
        "create_palette",
        "create_font",
        "select_object",
        "select_object",
        "select_object",
        "select_palette",
        "delete_object",
    ]
    assert calls[0] == Call.make("create_pen", style=0, width=2, color=0xFF)
    assert calls[1] == Call.make("create_brush", style=2, color=0x00FF00, hatch=4)
    assert calls[2] == Call.make("create_palette", palette=PaletteEntries(((1, 2, 3, 0),)))
    assert calls[3] == Call.make("create_font", font=FontRequest(height=-12, face_name="Arial"))
    selected = [call.kwargs["handle"].serial for call in calls[4:9]]
    assert selected == [1, 2, 4, 3, 1]


def test_creation_replaces_an_occupied_slot():
    calls, _ = run([fixed.CreatePen(1, 0, 1, 0, 0), fixed.CreatePen(1, 0, 2, 0, 0), fixed.SelectObject(1)])
    assert calls[-1].kwargs["handle"].serial == 2


def test_stock_objects_are_fetched_once():
    calls, omissions = run(
        [
            fixed.SelectObject(WHITE_BRUSH),
            fixed.SelectObject(NULL_PEN),
            fixed.SelectObject(WHITE_BRUSH),
            fixed.DeleteObject(WHITE_BRUSH),  # Stock objects are never deleted.
            fixed.SelectObject(SYSTEM_FONT),
        ]
    )
    brush, pen, font = Handle(1, "brush", None), Handle(2, "pen", None), Handle(3, "font", None)
    assert calls == [
        Call.make("get_stock_object", index=0),
        Call.make("select_object", handle=brush),
        Call.make("get_stock_object", index=8),
        Call.make("select_object", handle=pen),
        Call.make("select_object", handle=brush),
        Call.make("get_stock_object", index=13),
        Call.make("select_object", handle=font),
    ]
    assert omissions == ()


def test_palette_edits_name_their_palette():
    calls, omissions = run(
        [
            variable.CreatePalette(1, ((1, 2, 3, 0),)),
            variable.CreatePalette(2, ((4, 5, 6, 0),)),
            fixed.SelectPalette(1),
            variable.SetPaletteEntries(1, 0, ((7, 8, 9, 0),)),
            fixed.ResizePalette(2, 4),
            fixed.CreateBrushIndirect(3, 0, 0, 0),
            fixed.ResizePalette(3, 4),  # Not a palette: fails natively.
        ],
        strict=True,
    )
    first, second = Handle(1, "palette", None), Handle(2, "palette", None)
    assert [(call.name, call.kwargs) for call in calls[2:]] == [
        ("select_palette", {"handle": first}),
        ("set_palette_entries", {"palette": PaletteUpdate(0, ((7, 8, 9, 0),))}),
        ("select_palette", {"handle": second}),
        ("resize_palette", {"count": 4}),
        ("select_palette", {"handle": first}),
        ("create_brush", {"style": 0, "color": 0, "hatch": 0}),
    ]
    assert omissions == ()


def test_unsupported_creations_are_reported_once_selected():
    _, omissions = run(
        [
            bitmaps.ExtCreatePen(1, 0, 0, 0, 0, 0x10000, 1, 0, 0, 0),  # Geometric width 1.
            fixed.SelectObject(1),
        ]
    )
    assert [(o.record_index, o.reason) for o in omissions] == [
        (0, "Extended pen type is not yet supported"),
        (1, "Object creation was unsupported"),
    ]


@pytest.mark.parametrize(
    ("pen", "call"),
    [
        (
            bitmaps.ExtCreatePen(1, 0, 0, 0, 0, 0x00000002, 1, 0, 0xFF, 0),
            Call.make("create_pen", style=2, width=1, color=0xFF),
        ),
        (
            bitmaps.ExtCreatePen(1, 0, 0, 0, 0, 0x00011200, 5, 0, 0xFF, 0),
            Call.make("create_pen", style=0x1200, width=5, color=0xFF),
        ),
        (bitmaps.ExtCreatePen(1, 0, 0, 0, 0, 0x00010001, 5, 0, 0, 0), None),  # Geometric dashes.
        (bitmaps.ExtCreatePen(1, 0, 0, 0, 0, 0x00000007, 1, 0, 0, 0, (1, 2)), None),  # User style.
        (bitmaps.ExtCreatePen(1, 0, 0, 0, 0, 0x00010000, 5, 2, 0, 1), None),  # Hatched brush.
    ],
)
def test_extended_pens_that_create_pen_can_express(pen, call):
    calls, omissions = run([pen])
    assert calls == ([call] if call else [])
    assert bool(omissions) == (call is None)


def test_relative_save_levels():
    calls, omissions = run(
        [fixed.SaveDC(), fixed.SaveDC(), fixed.RestoreDC(-2), fixed.RestoreDC(-1), fixed.SaveDC(), fixed.RestoreDC(1)]
    )
    assert [(call.name, call.kwargs) for call in calls] == [
        ("save_dc", {}),
        ("save_dc", {}),
        ("restore_dc", {"saved_dc": -2}),
        ("save_dc", {}),
    ]
    assert omissions == ()  # Native playback ignores the absolute level.


def transform(**values):
    return Call.make("set_world_transform", **IDENTITY | values)


def test_mapping_records_become_world_transforms():
    calls, omissions = run(
        [
            fixed.SetMapMode(8),  # The extents are still 1:1, so nothing changes yet.
            fixed.SetWindowExtEx(256, 64),
            fixed.SetViewportOrgEx(3, 4),
            fixed.SetViewportExtEx(128, 128),
            fixed.SetWindowOrgEx(-2, 2),
            fixed.SetWindowOrgEx(-2, 2),  # The same matrix is not set again.
        ],
        strict=True,
    )
    assert omissions == ()
    assert calls == [
        transform(m11=1 / 256, m22=1 / 64),
        transform(m11=1 / 256, m22=1 / 64, dx=3.0, dy=4.0),
        transform(m11=0.5, m22=2.0, dx=3.0, dy=4.0),
        transform(m11=0.5, m22=2.0, dx=4.0, dy=0.0),
    ]


def test_physical_modes_and_world_transforms():
    calls, omissions = run(
        [
            fixed.SetMapMode(2),  # MM_LOMETRIC: extents from the header millimetres, not a DPI.
            fixed.SetWorldTransform(2.0, 0.0, 0.0, 2.0, 1.0, 0.0),
            fixed.SetWorldTransform(1.0, 0.0, 0.0, 0.0, 0.0, 0.0),  # Singular: rejected.
            fixed.ModifyWorldTransform(2.0, 0.0, 0.0, 2.0, 0.0, 0.0, 9),  # Unknown mode: rejected.
            fixed.ModifyWorldTransform(3.0, 0.0, 0.0, 3.0, 0.0, 0.0, 1),  # MWT_IDENTITY ignores the matrix.
        ],
        strict=True,
    )
    assert omissions == ()
    x, y = float32(1024 / 2710), float32(-768 / 2030)
    assert calls == [
        transform(m11=x, m22=y),
        transform(m11=float32(2 * x), m22=float32(2 * y), dx=x),
        transform(m11=x, m22=y),
    ]


def test_frame_fit_and_saved_transforms():
    trace = TraceContext()
    records = [
        fixed.SaveDC(),
        fixed.SetWorldTransform(2.0, 0.0, 0.0, 2.0, 0.0, 0.0),
        fixed.RestoreDC(-1),
        fixed.SetMapMode(1),
    ]
    play(Metafile.build(records, frame=(100, 0, 1100, 1000)), trace, rect=(10, 20, 74, 52), strict=True)
    fit = dict(
        m11=float32(float32(64 / 1000) * float32(27100 / 1024)), m22=float32(float32(32 / 1000) * float32(20300 / 768))
    )
    fit |= dict(dx=float32(10 - float32(100 * float32(64 / 1000))), dy=20.0)
    assert [call.name for call in trace.calls] == [
        "set_graphics_mode",
        "set_world_transform",
        "save_dc",
        "set_world_transform",
        "restore_dc",
    ]
    assert trace.calls[1] == transform(**fit)
    assert trace.calls[3] == transform(
        **{key: float32(2 * value) if key in ("m11", "m22") else value for key, value in fit.items()}
    )


def test_frames_native_playback_rejects():
    with pytest.raises(PlaybackError, match="reversed"):
        play(Metafile.build([], frame=(10, 0, 0, 10)), TraceContext())
    header = Metafile.build([], frame=UNIT_FRAME).header
    with pytest.raises(PlaybackError, match="device size"):
        play(Metafile(replace(header, millimetres=(0, 1)), (variable.Eof(),)), TraceContext())


def test_blits():
    blit = dict.fromkeys(bitmaps.BitBlt.fields, 0) | {"x": 1, "y": 2, "width": 3, "height": 4, "rop": 0x00F00021}
    blit |= {"src_m11": 1.0, "src_m22": 1.0, "data": b""}
    sourced = blit | {"rop": 0x00CC0020, "bitmap_offset": 100, "bitmap_size": 40, "bits_offset": 140, "bits_size": 4}
    sourced["data"] = DIB + PIXEL
    stretch = sourced | {"bitmap_offset": 108, "bits_offset": 148, "src_width": 5, "src_height": 6}
    calls, omissions = run(
        [
            bitmaps.BitBlt(**blit),
            bitmaps.BitBlt(**sourced),
            bitmaps.StretchBlt(**stretch),
            bitmaps.BitBlt(**sourced | {"src_m11": 2.0}),
            bitmaps.BitBlt(**sourced | {"usage": 1}),
        ]
    )
    source = BitmapData("dib", DIB + PIXEL)
    arguments = {"x": 1, "y": 2, "width": 3, "height": 4, "src_x": 0, "src_y": 0}
    assert calls == [
        Call.make("pat_blt", x=1, y=2, width=3, height=4, rop=0x00F00021),
        Call.make("dib_bit_blt", **arguments, rop=0x00CC0020, source=source),
        Call.make("dib_stretch_blt", **arguments, src_width=5, src_height=6, rop=0x00CC0020, source=source),
    ]
    assert [o.reason for o in omissions] == [
        "Transformed blit sources are not yet supported",
        "Palette-indexed blit sources are not yet supported",
    ]


def test_dib_transfers_join_the_header_and_bits():
    stretch = bitmaps.StretchDIBits(0, 0, 0, 0, 1, 2, 0, 0, 1, 1, 80, 40, 120, 4, 0, 0x00CC0020, 3, 4, DIB + PIXEL)
    device = bitmaps.SetDIBitsToDevice(0, 0, 0, 0, 1, 2, 0, 0, 1, 1, 76, 40, 116, 4, 0, 0, 1, DIB + PIXEL)
    brush = bitmaps.CreateDIBPatternBrushPt(1, 0, 32, 40, 72, 4, DIB + PIXEL)
    calls, omissions = run([stretch, device, brush], strict=True)
    source = BitmapData("dib", DIB + PIXEL)
    assert calls == [
        Call.make(
            "stretch_dib",
            x=1,
            y=2,
            width=3,
            height=4,
            src_x=0,
            src_y=0,
            src_width=1,
            src_height=1,
            rop=0x00CC0020,
            color_usage=0,
            source=source,
        ),
        # A whole-image SetDIBitsToDevice plays as a SRCCOPY stretch.
        Call.make(
            "stretch_dib",
            x=1,
            y=2,
            width=1,
            height=1,
            src_x=0,
            src_y=0,
            src_width=1,
            src_height=1,
            rop=0x00CC0020,
            color_usage=0,
            source=source,
        ),
        Call.make("create_dib_pattern_brush", style=5, color_usage=0, bitmap=source),
    ]


def test_set_dib_to_device_bands():
    tall = DIB[:8] + struct.pack("<i", 2) + DIB[12:]  # Two scan lines, one supplied.
    band = bitmaps.SetDIBitsToDevice(0, 0, 0, 0, 1, 2, 0, 0, 1, 1, 76, 40, 116, 4, 0, 1, 1, tall + PIXEL)
    calls, omissions = run([band], strict=True)
    assert [call.name for call in calls] == ["set_dib_to_device"]
    trace = TraceContext()
    omissions = play(Metafile.build([band], frame=(0, 0, 1000, 1000)), trace, rect=(0, 0, 128, 128))
    assert [o.reason for o in omissions] == ["Scaled SetDIBitsToDevice bands are not yet supported"]


def test_offsets_outside_the_record_are_reported():
    stretch = bitmaps.StretchDIBits(0, 0, 0, 0, 1, 2, 0, 0, 1, 1, 80, 40, 200, 4, 0, 0x00CC0020, 3, 4, DIB + PIXEL)
    calls, omissions = run([stretch])
    assert calls == []
    assert [o.reason for o in omissions] == ["STRETCHDIBITS data lies outside the record"]


def test_text():
    narrow = text.ExtTextOutA(
        (0, 0, 0, 0), 1, 0.0, 0.0, 3, 4, 2, 60, 0x0100, None, 64, b"ab\0\0" + struct.pack("<2i", 5, 6)
    )
    opaque = text.ExtTextOutA((0, 0, 0, 0), 1, 0.0, 0.0, 3, 4, 1, 76, 2, (1, 2, 3, 4), 80, b"a\0\0\0" + bytes(4))
    glyphs = text.ExtTextOutW((0, 0, 0, 0), 1, 0.0, 0.0, 3, 4, 2, 76, 0x10, (1, 2, 3, 4), 0, struct.pack("<2H", 7, 8))
    unicode = text.ExtTextOutW((0, 0, 0, 0), 1, 0.0, 0.0, 3, 4, 1, 76, 0, (1, 2, 3, 4), 0, "é\0".encode("utf-16-le"))
    advanced = text.ExtTextOutA((0, 0, 0, 0), 2, 1.0, 1.0, 3, 4, 1, 76, 0, (1, 2, 3, 4), 0, b"a\0\0\0")
    calls, omissions = run([narrow, opaque, glyphs, unicode, advanced])
    assert calls == [
        Call.make("ext_text_out", x=3, y=4, text=EncodedText(b"ab"), options=0, rectangle=None, advances=(5, 6)),
        Call.make("ext_text_out", x=3, y=4, text=EncodedText(b"a"), options=2, rectangle=(1, 2, 3, 4), advances=(0,)),
        Call.make("ext_text_out", x=3, y=4, text=GlyphIndices((7, 8)), options=0x10, rectangle=None, advances=()),
    ]
    assert [o.reason for o in omissions] == [
        "Unicode text is not yet supported",
        "Advanced graphics-mode text is not yet supported",
    ]


def test_clip_regions_are_combined_from_device_rectangles():
    region = struct.pack("<4I4i", 32, 1, 2, 32, 0, 0, 9, 9) + struct.pack("<8i", 0, 0, 4, 4, 5, 5, 9, 9)
    calls, omissions = run(
        [
            variable.ExtSelectClipRgn(5, region),
            variable.ExtSelectClipRgn(5),
            variable.ExtSelectClipRgn(1, region),
            variable.ExtSelectClipRgn(4),  # Only RGN_COPY plays without a region.
            variable.ExtSelectClipRgn(5, bytes(32)),
            fixed.SetMetaRgn(),
        ]
    )
    geometry = RegionGeometry(((0, 0, 4, 4), (5, 5, 9, 9)))
    assert calls == [
        Call.make("create_region", region=geometry),
        Call.make("ext_select_clip_region", region=Handle(1, "region", None), mode=5),
        Call.make("delete_object", handle=Handle(1, "region", None)),
        Call.make("ext_select_clip_region", region=None, mode=5),
        Call.make("create_region", region=geometry),
        Call.make("ext_select_clip_region", region=Handle(2, "region", None), mode=1),
        Call.make("delete_object", handle=Handle(2, "region", None)),
        Call.make("set_meta_region"),
    ]
    assert [o.reason for o in omissions] == ["Invalid region data"]


def emf_plus(flags: int) -> variable.Comment:
    header = struct.pack("<HHII", 0x4001, flags, 28, 16) + bytes(16)
    return variable.Comment(b"EMF+" + header)


def test_comments_reach_the_hook_and_never_draw():
    seen = []
    records = [variable.Comment(b"GDIC" + bytes(4)), emf_plus(1), emf_plus(0), variable.Comment(b"")]
    calls, omissions = run(records, comment=lambda index, record: seen.append(index))
    assert calls == []
    assert seen == [0, 1, 2, 3]
    assert [(o.record_index, o.reason) for o in omissions] == [
        (2, "EMF+ drawing without a GDI fallback is not rendered")
    ]


def test_unsupported_records_are_reported_or_raise_when_strict():
    records = [fixed.BeginPath(), UnknownRecord(0x7777, b""), UnknownRecord(103, b""), fixed.Rectangle(0, 0, 1, 1)]
    calls, omissions = run(records)
    assert calls == [Call.make("rectangle", left=0, top=0, right=1, bottom=1)]
    assert [(o.record_index, o.function, o.reason) for o in omissions] == [
        (0, 59, "BEGINPATH is not yet supported"),
        (1, 0x7777, "Record type 0x7777 is not yet supported"),
        (2, 103, "GLSBOUNDEDRECORD is not yet supported"),
    ]
    with pytest.raises(UnsupportedOperation, match="Record 0: BEGINPATH"):
        run(records, strict=True)


def test_playback_stops_at_eof_and_enforces_limits():
    file = Metafile.build([fixed.CreatePen(5, 0, 1, 0, 0)], frame=UNIT_FRAME)
    with pytest.raises(PlaybackError, match="resource limit"):
        play(file, TraceContext(), limits=Limits(max_objects=5))
    with pytest.raises(PlaybackError, match="saved-state"):
        play(Metafile.build([fixed.SaveDC()] * 3, frame=UNIT_FRAME), TraceContext(), limits=Limits(max_saved_states=2))


def test_mutated_files_play_or_raise_playback_error():
    from test_emf_codec import CASES, mutations

    records = [case for case in CASES if not isinstance(case, variable.Eof)]
    seed = Metafile.build(records, frame=UNIT_FRAME).to_bytes()
    played = 0
    for data in mutations(seed, random.Random(0x91A7), 1500):
        try:
            metafile = Metafile.from_bytes(data, limits=Limits(max_points=4096, max_records=4096))
        except FormatError:
            continue
        try:
            play(metafile, TraceContext())
        except PlaybackError:
            continue
        played += 1
    assert played > 100
