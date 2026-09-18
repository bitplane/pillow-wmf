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


@pytest.mark.parametrize("operation", ["text_out", "ext_text_out"])
def test_font_selection_does_not_enable_text_drawing(operation):
    context = RasterContext(8, 8)
    context.set_text_alignment(6)
    context.select_object(context.create_font(Font(height=-12)))
    before = list(context.calls)
    with pytest.raises(UnsupportedOperation, match=operation):
        getattr(context, operation)(1, 1, b"text")
    assert context.calls == before


def test_logical_fonts_are_selected_lazily_and_saved_independently_of_brushes():
    context = RasterContext(8, 8)
    brush = context._brush
    default = context.save_dc()
    requested = Font(height=-13, charset=204, face_name=b"Not installed")
    first = context.create_font(requested)
    assert context._text_state.font is None  # Creation does not select or resolve.
    context.select_object(first)
    selected = context.save_dc()
    context.select_object(context.create_font(Font(height=20)))
    context.restore_dc(selected)
    assert context._text_state.font is requested
    assert context._brush is brush
    context.restore_dc(default)
    assert context._text_state.font is None


def test_font_creation_validation_does_not_allocate_a_handle():
    context = RasterContext(8, 8)
    with pytest.raises(ValueError):
        context.create_font(Font(face_name=b"x" * 33))
    assert not context.calls
    assert not context._objects
    assert context.create_font(Font()).serial == 1


def test_font_only_metafile_does_not_block_non_text_drawing():
    recorder = Recorder()
    handle = recorder.create_font(Font(face_name=b"Unavailable".ljust(32, b"\0")))
    recorder.select_object(handle)
    recorder.set_pixel(2, 3, 0xFF)
    recorder.delete_object(handle)
    context = RasterContext(8, 8)
    assert play(Metafile.from_bytes(recorder.to_bytes()), context, strict=True) == ()
    assert context.image.getpixel((2, 3)) == (255, 0, 0)
    with pytest.raises(UnsupportedOperation):
        context.text_out(0, 0, b"still unsupported")
