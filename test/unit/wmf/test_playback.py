from dataclasses import replace

import pytest

from pillow_wmf import GDI, Call, Limits, Metafile, PlaybackError, Recorder, TraceContext, UnsupportedOperation, play
from pillow_wmf.wmf import UnknownRecord, fixed
from pillow_wmf.wmf.objects import BitmapData, Font, Palette, Region, Scan


def test_utf8_extension_is_normalized_only_at_wmf_playback():
    source = Recorder()
    request = Font(face_name=b"Example".ljust(32, b"\0"), charset=254)
    source.create_font(request)
    data = source.to_bytes()
    metafile = Metafile.from_bytes(data)
    assert metafile.to_bytes() == data
    trace = TraceContext()
    play(metafile, trace, strict=True)
    assert trace.calls[0].kwargs["font"] == replace(request, charset=1).to_gdi("create_font")
    assert source.calls[0].kwargs["font"] == request.to_gdi("create_font")


def draw_program(dc):
    pen = dc.create_pen(0, 1, 0x000000FF)
    brush = dc.create_brush(0, 0x0000FF00, 0)
    font = dc.create_font(Font(height=-12))
    palette = dc.create_palette(Palette(entries=((255, 0, 0, 0),)))
    region = dc.create_region(Region((0, 0, 20, 20), (Scan(0, 20, (0, 20)),)))
    dc.select_object(pen)
    dc.select_object(brush)
    dc.select_object(font)
    dc.select_palette(palette)
    dc.select_clip_region(region)
    dc.set_map_mode(8)
    dc.set_window_origin(-10, -20)
    dc.set_window_extent(100, 200)
    dc.set_viewport_origin(1, 2)
    dc.set_viewport_extent(300, 400)
    dc.offset_window_origin(1, 2)
    dc.offset_viewport_origin(3, 4)
    dc.scale_window_extent(1, 2, 3, 4)
    dc.scale_viewport_extent(5, 6, 7, 8)
    dc.offset_clip_region(1, 2)
    dc.intersect_clip_rect(0, 0, 10, 10)
    dc.exclude_clip_rect(0, 0, 1, 1)
    dc.set_background_color(0xFFFFFF)
    dc.set_background_mode(2)
    dc.set_text_color(0)
    dc.set_text_alignment(0)
    dc.set_text_character_extra(1)
    dc.set_text_justification(2, 4)
    dc.set_mapper_flags(0)
    dc.set_polygon_fill_mode(1)
    dc.set_stretch_mode(3)
    dc.set_rop2(13)
    dc.realize_palette()
    dc.resize_palette(2)
    dc.animate_palette(Palette(0, ((0, 255, 0, 1),)))
    dc.set_palette_entries(Palette(0, ((0, 0, 255, 0),)))
    saved = dc.save_dc()
    dc.move_to(10, 20)
    dc.line_to(30, 40)
    dc.rectangle(1, 2, 3, 4)
    dc.ellipse(1, 2, 3, 4)
    dc.round_rect(1, 2, 3, 4, 5, 6)
    dc.arc(1, 2, 3, 4, 5, 6, 7, 8)
    dc.pie(1, 2, 3, 4, 5, 6, 7, 8)
    dc.chord(1, 2, 3, 4, 5, 6, 7, 8)
    dc.set_pixel(1, 2, 0)
    dc.flood_fill(1, 2, 0)
    dc.ext_flood_fill(1, 2, 0, 1)
    dc.pat_blt(1, 2, 3, 4, 0x005A0049)
    dc.polygon(((0, 0), (10, 0), (10, 10)))
    dc.polyline(((0, 0), (10, 0)))
    dc.poly_polygon((((0, 0), (10, 0), (10, 10)),))
    dc.fill_region(region, brush)
    dc.frame_region(region, brush, 1, 2)
    dc.paint_region(region)
    dc.invert_region(region)
    dc.text_out(10, 20, b"a\x00\xff")
    dc.ext_text_out(10, 20, b"abc", 6, (0, 0, 100, 30), (5, 6, 7))
    dc.set_layout(0)
    dc.escape(0x7777, b"odd")
    dc.restore_dc(saved)
    dc.delete_object(pen)
    replacement = dc.create_pen(0, 0, 0)
    dc.select_object(replacement)


def test_gdi_writer_reader_player_trace_round_trip():
    expected = TraceContext()
    draw_program(expected)
    recorder = Recorder()
    draw_program(recorder)
    data = recorder.to_bytes()
    parsed = Metafile.from_bytes(data)
    actual = TraceContext()
    assert play(parsed, actual, strict=True) == ()
    assert actual.calls == expected.calls
    assert parsed.header.object_count == 5
    # Slot zero was freed/reused; the replacement has a new backend identity.
    assert parsed.records[-2].object_index == 0
    assert actual.calls[-1].kwargs["handle"].serial == 6


def test_player_can_target_another_recorder():
    source = Recorder()
    draw_program(source)
    destination = Recorder()
    play(Metafile.from_bytes(source.to_bytes()), destination, strict=True)
    assert destination.to_bytes() == source.to_bytes()


def test_handle_lifetime_does_not_rewind_with_dc():
    recorder = Recorder()
    pen = recorder.create_pen(0, 1, 0)
    recorder.save_dc()
    recorder.delete_object(pen)
    replacement = recorder.create_brush(0, 0, 0)
    recorder.restore_dc(-1)
    with pytest.raises(ValueError, match="deleted handle"):
        recorder.select_object(pen)
    recorder.select_object(replacement)
    assert recorder.records[-1].object_index == 0
    assert recorder.metafile().header.object_count == 1


def test_handle_ownership_and_type():
    recorder = Recorder()
    foreign = Recorder().create_pen(0, 1, 0)
    with pytest.raises(ValueError, match="handle"):
        recorder.select_object(foreign)
    palette = recorder.create_palette(Palette())
    with pytest.raises(ValueError, match="type"):
        recorder.select_object(palette)
    recorder.select_palette(palette)


def test_failed_recording_does_not_change_context():
    recorder = Recorder()
    with pytest.raises(ValueError):
        recorder.create_pen(0, 100_000, 0)
    assert recorder.records == []
    assert recorder.calls == []
    pen = recorder.create_pen(0, 1, 0)
    assert pen.serial == 1


def test_save_restore_ids_and_limits():
    recorder = Recorder(max_saved_states=2)
    assert recorder.save_dc() == 1
    assert recorder.save_dc() == 2
    with pytest.raises(ValueError, match="limit"):
        recorder.save_dc()
    recorder.restore_dc(1)
    assert recorder.save_dc() == 1
    recorder.restore_dc(-1)
    with pytest.raises(ValueError, match="saved DC"):
        recorder.restore_dc(-1)


def test_unknown_records_reported_and_reserved_record_ignored():
    file = Metafile.build([UnknownRecord(0x12FE, b""), fixed.SetRelAbs(), fixed.MoveTo(2, 1)])
    trace = TraceContext()
    omissions = play(file, trace)
    assert len(omissions) == 1
    assert omissions[0].record_index == 0
    assert trace.calls == [Call.make("move_to", x=1, y=2)]
    with pytest.raises(UnsupportedOperation, match="Unknown"):
        play(file, TraceContext(), strict=True)
    assert play(Metafile.build([fixed.SetRelAbs()]), TraceContext(), strict=True) == ()


def test_unimplemented_backend_reports_omissions():
    omissions = play(Metafile.build([fixed.MoveTo(2, 1)]), GDI())
    assert omissions[0].reason == "move_to"


def test_unsupported_deletion_still_releases_file_slot():
    class NoDelete(TraceContext):
        def invoke(self, call):
            if call.name == "delete_object":
                raise UnsupportedOperation("deletion")
            return super().invoke(call)

    source = Recorder()
    first = source.create_pen(0, 1, 0)
    source.delete_object(first)
    second = source.create_pen(0, 2, 0)
    source.select_object(second)
    backend = NoDelete()
    omissions = play(Metafile.from_bytes(source.to_bytes()), backend)
    assert len(omissions) == 1
    assert omissions[0].reason == "deletion"
    assert backend.calls[-1].kwargs["handle"].serial == 2


def test_unsupported_creation_does_not_shift_later_handles():
    class NoFonts(TraceContext):
        def invoke(self, call):
            if call.name == "create_font":
                raise UnsupportedOperation("font support")
            return super().invoke(call)

    source = Recorder()
    font = source.create_font(Font())
    pen = source.create_pen(0, 1, 255)
    source.select_object(font)
    source.select_object(pen)
    source.delete_object(font)
    brush = source.create_brush(0, 0, 0)
    source.select_object(brush)
    trace = NoFonts()
    omissions = play(source.metafile(), trace)
    assert len(omissions) == 3
    assert [call.kwargs["handle"].kind for call in trace.calls if call.name == "select_object"] == ["pen", "brush"]


@pytest.mark.parametrize(
    "file",
    [
        Metafile.build([fixed.SelectObject(0)]),
    ],
)
def test_native_out_of_range_selection_is_noop(file):
    trace = TraceContext()
    assert play(file, trace, strict=True) == ()
    assert trace.calls == []


def test_header_capacity_is_enforced():
    file = Metafile.build([fixed.CreatePenIndirect(0, 1, 0, 0)])
    file = replace(file, header=replace(file.header, object_count=0))
    trace = TraceContext()
    assert play(file, trace, strict=True) == ()
    assert trace.calls == []


def test_backend_creation_must_return_a_handle():
    class Broken(GDI):
        def invoke(self, call):
            return None

    with pytest.raises(PlaybackError, match="return a handle"):
        play(Metafile.build([fixed.CreatePenIndirect(0, 1, 0, 0)]), Broken())


def test_playback_resource_limit():
    with pytest.raises(PlaybackError, match="limit"):
        play(Metafile.build([fixed.MoveTo(1, 2)]), TraceContext(), limits=Limits(max_records=1))


def test_bitmap_envelope_arguments_survive_playback():
    source = BitmapData("dib", bytes(40))
    recorder = Recorder()
    recorder.create_pattern_brush(BitmapData("pattern16", bytes(34)))
    recorder.create_dib_pattern_brush(5, 0, source)
    legacy = BitmapData("bitmap16", bytes(12))
    recorder.bit_blt(1, 2, 3, 4, 5, 6, 0x00CC0020, legacy)
    recorder.stretch_blt(1, 2, 3, 4, 5, 6, 7, 8, 0x00CC0020, legacy)
    recorder.dib_bit_blt(1, 2, 3, 4, 5, 6, 0x00CC0020, source)
    recorder.dib_stretch_blt(1, 2, 3, 4, 5, 6, 7, 8, 0x00CC0020, source)
    recorder.stretch_dib(1, 2, 3, 4, 5, 6, 7, 8, 0x00CC0020, 0, source)
    recorder.set_dib_to_device(1, 2, 3, 4, 5, 6, 0, 1, 0, source)
    trace = TraceContext()
    play(Metafile.from_bytes(recorder.to_bytes()), trace, strict=True)
    assert trace.calls == recorder.calls


def test_player_saved_state_limit_with_independent_backend():
    file = Metafile.build([fixed.SaveDC(), fixed.SaveDC()])
    with pytest.raises(PlaybackError, match="saved-state limit"):
        play(file, TraceContext(), limits=Limits(max_saved_states=1))


def test_unsupported_save_restore_reports_both_records():
    file = Metafile.build([fixed.SaveDC(), fixed.RestoreDC(-1)])
    assert len(play(file, GDI())) == 2


@pytest.mark.parametrize("absolute", [False, True])
def test_rejected_saves_do_not_shift_backend_restore_levels(absolute):
    class RejectSecondSave(TraceContext):
        attempts = 0

        def invoke(self, call):
            if call.name == "save_dc":
                self.attempts += 1
                if self.attempts == 2:
                    raise UnsupportedOperation("save")
            return super().invoke(call)

    file = Metafile.build(
        [
            fixed.SaveDC(),
            fixed.SaveDC(),
            fixed.SaveDC(),
            fixed.RestoreDC(3 if absolute else -1),
            fixed.RestoreDC(2 if absolute else -1),
            fixed.RestoreDC(1 if absolute else -1),
        ]
    )
    backend = RejectSecondSave()
    omissions = play(file, backend)
    assert [issue.record_index for issue in omissions] == [1, 4]
    assert backend._save_depth == 0


def test_rejected_restore_keeps_backend_frames_accounted_for():
    class RejectFirstRestore(TraceContext):
        attempts = 0

        def invoke(self, call):
            if call.name == "restore_dc":
                self.attempts += 1
                if self.attempts == 1:
                    raise UnsupportedOperation("restore")
            return super().invoke(call)

    file = Metafile.build(
        [
            fixed.SaveDC(),
            fixed.SaveDC(),
            fixed.RestoreDC(-1),
            fixed.RestoreDC(-1),
        ]
    )
    backend = RejectFirstRestore()
    assert len(play(file, backend)) == 1
    assert backend.calls[-1] == Call.make("restore_dc", saved_dc=-2)
    assert backend._save_depth == 0


def test_absolute_restore_is_relative_to_the_files_own_save_stack():
    backend = TraceContext()
    backend.save_dc()
    file = Metafile.build([fixed.SaveDC(), fixed.RestoreDC(1)])
    assert play(file, backend, strict=True) == ()
    assert backend.calls[-1] == Call.make("restore_dc", saved_dc=2)
    assert backend._save_depth == 1


def test_malformed_bitmap_is_omitted_before_any_state_changes():
    from pillow_wmf import RasterContext

    recorder = Recorder()
    recorder.dib_stretch_blt(0, 0, 2, 2, 0, 0, 2, 2, 0x00CC0020, BitmapData("dib", b"\x28" + bytes(47)))
    recorder.set_pixel(1, 1, 255)
    context = RasterContext(3, 3)
    issues = play(recorder.metafile(), context)
    assert len(issues) == 1
    assert "malformed input" in issues[0].reason
    assert [call.name for call in context.calls] == ["set_pixel"]
    assert context.image.getpixel((1, 1)) == (255, 0, 0)
    with pytest.raises(UnsupportedOperation, match="malformed input"):
        play(recorder.metafile(), RasterContext(3, 3), strict=True)


def test_bitmap_limits_are_fatal_even_in_tolerant_playback():
    from pillow_wmf import RasterContext
    from pillow_wmf.bitmap import RGBBitmap, encode_dib24
    from pillow_wmf.wmf.binary import ResourceLimitError

    recorder = Recorder()
    recorder.dib_stretch_blt(0, 0, 2, 2, 0, 0, 2, 2, 0x00CC0020, encode_dib24(RGBBitmap(2, 2, bytes(12))))
    with pytest.raises(ResourceLimitError):
        play(recorder.metafile(), RasterContext(3, 3, max_bitmap_pixels=1))


def test_sequence_inputs_are_snapshotted():
    points = [[1, 2], [3, 4]]
    text = bytearray(b"hello")
    entries = [[255, 0, 0, 0]]
    recorder = Recorder()
    recorder.polygon(points)
    recorder.text_out(0, 0, text)
    recorder.create_palette(Palette(entries=entries))
    before = recorder.to_bytes()
    points[0][0] = 999
    text[0] = 0
    entries[0][0] = 0
    assert recorder.to_bytes() == before


def test_deleted_file_slot_uses_lowest_available_index():
    recorder = Recorder()
    handles = [recorder.create_pen(0, 1, 0) for _ in range(3)]
    recorder.delete_object(handles[2])
    recorder.delete_object(handles[0])
    first = recorder.create_pen(0, 1, 0)
    second = recorder.create_pen(0, 1, 0)
    recorder.select_object(first)
    recorder.select_object(second)
    assert [record.object_index for record in recorder.records[-2:]] == [0, 2]
    assert recorder.metafile().header.object_count == 3
