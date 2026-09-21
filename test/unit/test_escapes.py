"""The RGB playback device has no printer channel or printer graphics state."""

import runpy
from pathlib import Path

import pytest

from pillow_wmf import Metafile, RasterContext, Recorder, UnsupportedOperation, play

PROBE = runpy.run_path(str(Path(__file__).parents[2] / "scripts/escape_cases.py"))


@pytest.mark.parametrize(
    "name,code,payload", tuple(PROBE["escapes"]()), ids=lambda value: value if isinstance(value, str) else None
)
def test_defined_printer_records_preserve_drawing_and_round_trip(name, code, payload):
    recorder = Recorder()
    recorder.escape(code, payload)
    recorder.set_pixel(7, 7, 0x00FF00)
    source = recorder.to_bytes()
    metafile = Metafile.from_bytes(source)
    assert metafile.to_bytes() == source
    actual = RasterContext(8, 8)
    actual.select_object(actual.create_pen(0, 3, 0xAA3300))
    actual.select_object(actual.create_brush(0, 0x55CCEE, 0))
    actual.move_to(2, 3)
    actual.set_pixel(1, 1, 255)
    actual.save_dc()
    expected = actual.image.copy()
    expected.putpixel((7, 7), (0, 255, 0))
    assert play(metafile, actual, strict=True) == ()
    assert actual.image.tobytes() == expected.tobytes()
    assert len(actual._saved) == 1
    actual.save_dc()
    assert actual._saved[0] == actual._saved[1]


@pytest.mark.parametrize("code", [0x0009, 0x101A, 0x7777])
def test_unimplemented_escapes_are_not_blanket_ignored(code):
    dc = RasterContext(8, 8)
    with pytest.raises(UnsupportedOperation, match="escape"):
        dc.escape(code, b"uninterpreted")
    assert not dc.calls
