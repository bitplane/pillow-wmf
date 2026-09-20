"""The RGB playback device has no printer channel or printer graphics state."""

import runpy
from pathlib import Path

import pytest

from pillow_wmf import Metafile, RasterContext, UnsupportedOperation, play

PROBE = runpy.run_path(str(Path(__file__).parents[2] / "scripts/escape_cases.py"))


@pytest.mark.parametrize(
    "name,recorder", tuple(PROBE["cases"]()), ids=lambda value: value if isinstance(value, str) else None
)
def test_defined_printer_records_preserve_drawing_and_round_trip(name, recorder):
    source = recorder.to_bytes()
    metafile = Metafile.from_bytes(source)
    assert metafile.to_bytes() == source
    actual, expected = RasterContext(128, 128), RasterContext(128, 128)
    assert play(metafile, actual, strict=True) == ()
    play(Metafile.from_bytes(PROBE["drawing"]().to_bytes()), expected, strict=True)
    assert actual.image.tobytes() == expected.image.tobytes()
    assert actual._position == expected._position


@pytest.mark.parametrize("code", [0x0009, 0x101A, 0x7777])
def test_unimplemented_escapes_are_not_blanket_ignored(code):
    dc = RasterContext(8, 8)
    with pytest.raises(UnsupportedOperation, match="escape"):
        dc.escape(code, b"uninterpreted")
    assert not dc.calls
