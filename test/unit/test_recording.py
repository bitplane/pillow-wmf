"""Staged execution and live recording must agree without partial rejection."""

import pytest

from pillow_wmf import (
    Call,
    FontCollection,
    FontRequest,
    InvalidOperation,
    Metafile,
    RasterContext,
    Recorder,
    RecordingContext,
    RegionGeometry,
    TraceContext,
    UnsupportedOperation,
    play,
)


@pytest.mark.parametrize("factory", [TraceContext, Recorder, lambda: RasterContext(16, 16)])
def test_preparation_does_not_publish_and_tokens_are_single_use(factory):
    context = factory()
    operation = Call.make("create_pen", style=0, width=1, color=0)
    first = context.prepare(operation)
    other = context.prepare(operation)
    assert not context.calls and not context._live
    assert context._next_handle == 1
    assert not getattr(context, "records", ())
    result = context.apply(first)
    assert result.serial == 1 and len(context.calls) == 1
    for stale in (first, other):
        with pytest.raises(InvalidOperation, match="stale"):
            context.apply(stale)
    assert len(context.calls) == 1


def test_preparations_cannot_cross_contexts():
    left, right = TraceContext(), TraceContext()
    token = left.prepare(Call.make("move_to", x=1, y=2))
    with pytest.raises(InvalidOperation, match="another context"):
        right.apply(token)
    assert not right.calls
    left.apply(token)


@pytest.mark.parametrize("rejecting_side", [0, 1])
def test_either_backend_can_reject_before_either_is_modified(rejecting_side):
    class Rejecting(TraceContext):
        def prepare(self, call):
            if call.name == "line_to":
                raise InvalidOperation("Rejected during preparation")
            return super().prepare(call)

    backends = [TraceContext(), TraceContext()]
    backends[rejecting_side] = Rejecting()
    context = RecordingContext(*backends)
    with pytest.raises(InvalidOperation, match="preparation"):
        context.line_to(1, 2)
    assert not context.calls and all(not backend.calls for backend in backends)
    context.move_to(3, 4)  # Ordinary rejection does not invalidate the pair.
    assert len(context.calls) == 1


def test_unrepresentable_wmf_command_does_not_draw():
    drawing, recorder = RasterContext(16, 16), Recorder()
    context = RecordingContext(drawing, recorder)
    before = context.image.tobytes()
    with pytest.raises(ValueError):
        context.line_to(100_000, 8)
    assert context.image.tobytes() == before
    assert not drawing.calls and not recorder.records and not context.calls


def test_unrenderable_command_does_not_enter_the_recording():
    context = RecordingContext(RasterContext(16, 16), Recorder())
    with pytest.raises(UnsupportedOperation):
        context.create_brush(999, 0, 0)
    assert not context.recorder.records and not context.calls
    assert context.create_pen(0, 1, 0).serial == 1


def test_native_null_creations_and_changed_playback_semantics_are_rejected():
    context = RecordingContext(RasterContext(16, 16), Recorder())
    with pytest.raises(UnsupportedOperation, match="successful object"):
        context.create_region(None)
    with pytest.raises(UnsupportedOperation, match="different drawing semantics"):
        context.create_font(FontRequest(charset=254))
    assert not context.calls and not context.recorder.records and not context.drawing.calls


@pytest.mark.parametrize("failing_side", [0, 1])
def test_execution_failure_invalidates_the_pair_without_publishing_wrapper_state(failing_side):
    class Broken(TraceContext):
        def _execute(self, prepared):
            raise InvalidOperation("An unexpected execution failure")

    backends = [TraceContext(), TraceContext()]
    backends[failing_side] = Broken()
    context = RecordingContext(*backends)
    with pytest.raises(RuntimeError, match="Failed drawing effect"):
        context.create_pen(0, 1, 0)
    assert not context.calls and not context._live and context._next_handle == 1
    with pytest.raises(RuntimeError, match="unusable"):
        context.move_to(1, 2)


def test_recording_requires_fresh_exclusive_contexts():
    used = TraceContext()
    used.move_to(1, 2)
    with pytest.raises(ValueError, match="fresh"):
        RecordingContext(used, Recorder())
    fresh = TraceContext()
    with pytest.raises(ValueError, match="distinct"):
        RecordingContext(fresh, fresh)
    drawing, recorder = TraceContext(), Recorder()
    context = RecordingContext(drawing, recorder)
    token = context.prepare(Call.make("move_to", x=3, y=4))
    recorder.move_to(9, 9)
    with pytest.raises(RuntimeError, match="independently"):
        context.apply(token)
    assert not drawing.calls and not context.calls


def test_wrapper_translates_handles_and_absolute_and_relative_saved_states():
    class OffsetSaves(TraceContext):
        def prepare(self, call):
            if call.name == "restore_dc":
                call = Call.make("restore_dc", saved_dc=call.kwargs["saved_dc"] - 100)
            return super().prepare(call)

        def _execute(self, prepared):
            result = super()._execute(prepared)
            return result + 100 if prepared.call.name == "save_dc" else result

    drawing, recorder = OffsetSaves(), Recorder()
    drawing._next_handle = 41
    recorder._next_handle = 81
    context = RecordingContext(drawing, recorder)
    pen = context.create_pen(0, 1, 0)
    context.select_object(pen)
    assert drawing.calls[-1].kwargs["handle"].serial == 41
    assert recorder.calls[-1].kwargs["handle"].serial == 81
    first = context.save_dc()
    context.save_dc()
    context.restore_dc(-1)
    context.restore_dc(first)
    assert not context._saved
    assert drawing._save_depth == recorder._save_depth == context._save_depth == 0
    context.delete_object(pen)
    with pytest.raises(InvalidOperation):
        context.select_object(pen)
    assert not context._handles


def test_live_image_matches_wmf_replay_exactly(face):
    def raster():
        return RasterContext(48, 40, fonts=FontCollection([face]))

    context = RecordingContext(raster(), Recorder())
    brush = context.create_brush(0, 0x3399CC, 0)
    pen = context.create_pen(0, 1, 0x000000)
    context.select_object(brush)
    context.select_object(pen)
    context.rectangle(2, 2, 45, 36)
    saved = context.save_dc()
    region = context.create_region(RegionGeometry(((8, 6, 40, 30),)))
    context.select_clip_region(region)
    context.set_viewport_origin(3, -2)
    context.set_rop2(7)
    context.move_to(0, 0)
    context.line_to(47, 39)
    context.restore_dc(saved)
    context.delete_object(region)
    font = context.create_font(FontRequest(height=-12, face_name=face.family, quality=3))
    context.select_object(font)
    context.set_background_mode(1)
    context.text_out(10, 12, b"AB")
    context.delete_object(pen)
    context.select_object(context.create_pen(0, 1, 0x00FF00))
    context.ellipse(20, 18, 38, 34)
    replay = raster()
    assert play(Metafile.from_bytes(context.recorder.to_bytes()), replay, strict=True) == ()
    assert context.image.tobytes() == replay.image.tobytes()
