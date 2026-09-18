import pytest

from pillow_wmf import Metafile, RasterContext, Recorder, UnsupportedOperation, play
from pillow_wmf.wmf.objects import Font


@pytest.mark.parametrize("code", [0x000F, 0x0026, 0x1000, 0x1001, 0x1002])
def test_bitmap_device_escapes_do_not_suppress_or_clip_drawing(code):
    recorder = Recorder()
    recorder.set_pixel(2, 2, 0x000000FF)
    recorder.escape(code, b"\x01\x00")
    recorder.set_pixel(3, 3, 0x0000FF00)
    context = RasterContext(8, 8)
    assert play(Metafile.from_bytes(recorder.to_bytes()), context, strict=True) == ()
    assert context.image.getpixel((2, 2)) == (255, 0, 0)
    assert context.image.getpixel((3, 3)) == (0, 255, 0)


@pytest.mark.parametrize("data", [b"", b"MrEd", b"WMFC\x01\x00\x00\x00", b"\xff" * 24])
def test_comment_payload_is_opaque_to_bitmap_device(data):
    context = RasterContext(8, 8)
    before = context.image.tobytes()
    context.escape(0x000F, data)
    assert context.image.tobytes() == before
    assert context.calls[-1].kwargs["data"] == data


def test_unknown_escape_is_still_rejected_without_committing_call():
    context = RasterContext(8, 8)
    with pytest.raises(UnsupportedOperation, match="escape"):
        context.escape(0x7777, b"opaque")
    assert context.calls == []


def test_text_setup_is_recorded_and_saved_without_rendering_text():
    recorder = Recorder()
    recorder.set_text_alignment(6)
    recorder.set_text_character_extra(2)
    recorder.set_text_justification(3, 7)
    recorder.set_mapper_flags(1)
    recorder.save_dc()
    recorder.set_text_alignment(0)
    recorder.set_text_character_extra(4)
    recorder.set_text_justification(0, 0)
    recorder.set_mapper_flags(0)
    recorder.restore_dc(-1)
    context = RasterContext(8, 8)
    before = context.image.tobytes()
    assert play(Metafile.from_bytes(recorder.to_bytes()), context, strict=True) == ()
    assert context._text_state.alignment == 6
    assert context._text_state.character_extra == 2
    assert context._text_state.justification == (3, 7)
    assert context._text_state.mapper_flags == 1
    assert context.image.tobytes() == before
    # Accepting setup is not permission to silently omit glyphs.
    with pytest.raises(UnsupportedOperation, match="text_out"):
        context.text_out(1, 1, b"text")


def test_nested_saves_keep_independent_text_state():
    context = RasterContext(8, 8)
    original = context._text_state
    first = context.save_dc()
    context.set_text_alignment(6)
    second = context.save_dc()
    context.set_text_alignment(2)
    context.restore_dc(second)
    assert context._text_state.alignment == 6
    context.restore_dc(first)
    assert context._text_state == original


@pytest.mark.parametrize("operation", ["text_out", "ext_text_out", "create_font"])
def test_text_setup_does_not_enable_font_operations(operation):
    context = RasterContext(8, 8)
    context.set_text_alignment(6)
    before = list(context.calls)
    with pytest.raises(UnsupportedOperation, match=operation):
        if operation == "create_font":
            context.create_font(Font())
        else:
            getattr(context, operation)(1, 1, b"text")
    assert context.calls == before
