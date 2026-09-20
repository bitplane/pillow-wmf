"""Input rejection is recoverable; failures while applying effects are not."""

from dataclasses import replace
from pathlib import Path

import pytest

from pillow_wmf import FontCollection, FontFace, Metafile, PlaybackError, RasterContext, play
from pillow_wmf.gdi import InvalidOperation
from pillow_wmf.wmf import fixed, variable
from pillow_wmf.wmf.objects import Font


@pytest.mark.parametrize(
    "records,reason",
    [
        ([fixed.CreatePenIndirect(0, 3, 0, 0), fixed.InvertRegion(0)], "Wrong object type"),
        (
            [
                variable.CreateFontIndirect(Font(height=-24, quality=3, face_name=b"Pillow WMF Test".ljust(32, b"\0"))),
                fixed.SelectObject(0),
                variable.ExtTextOut(0, 0, b"ABA", advances=(10,)),
            ],
            "advance count",
        ),
    ],
)
def test_rejected_record_does_not_abort_tolerant_playback(records, reason):
    fonts = FontCollection([FontFace.from_path(Path(__file__).parents[1] / "fonts/layout.ttf")])
    metafile = Metafile.from_bytes(Metafile.build([*records, fixed.SetPixel(255, 2, 3)]).to_bytes())
    dc = RasterContext(16, 16, fonts=fonts)
    omissions = play(metafile, dc)
    assert len(omissions) == 1
    assert reason in omissions[0].reason
    assert dc.image.getpixel((3, 2)) == (255, 0, 0)
    assert len(dc.calls) == len(records)
    with pytest.raises(PlaybackError, match=reason):
        play(metafile, RasterContext(16, 16, fonts=fonts), strict=True)


def test_prepare_rejection_leaves_context_usable(monkeypatch):
    dc = RasterContext(16, 16)

    def reject(call):
        raise InvalidOperation("Bad input")

    with monkeypatch.context() as patch:
        patch.setattr(dc, "_prepare_effect", reject)
        with pytest.raises(InvalidOperation):
            dc.create_pen(0, 1, 0)
    assert not dc.calls and not dc._live and not dc._objects
    assert dc.create_pen(0, 1, 0).serial == 1


def test_apply_failure_is_fatal_and_does_not_publish_a_handle(monkeypatch):
    dc = RasterContext(16, 16)

    def fail(call, prepared, result):
        dc.image.putpixel((0, 0), (255, 0, 0))
        raise InvalidOperation("Too late to reject the input")

    monkeypatch.setattr(dc, "_apply_create_pen", fail)
    with pytest.raises(RuntimeError, match="Failed drawing effect"):
        play(Metafile.build([fixed.CreatePenIndirect(0, 1, 0, 0)]), dc)
    assert not dc.calls and not dc._live
    assert dc._next_handle == 1
    with pytest.raises(RuntimeError, match="unusable"):
        dc.set_pixel(1, 1, 0)


@pytest.mark.parametrize("allocated", [False, True])
def test_empty_slot_deletion_and_selection_are_native_noops(allocated):
    records = [fixed.CreatePenIndirect(0, 3, 0, 0)] if allocated else []
    metafile = Metafile.build(
        [*records, fixed.DeleteObject(0), fixed.DeleteObject(0), fixed.SelectObject(0), fixed.SetPixel(255, 2, 3)]
    )
    metafile = replace(metafile, header=replace(metafile.header, object_count=1))
    dc = RasterContext(16, 16)
    assert play(metafile, dc, strict=True) == ()
    assert dc.image.getpixel((3, 2)) == (255, 0, 0)
    assert not dc._live


@pytest.mark.parametrize("width", [0, 3])
@pytest.mark.parametrize("count", [0, 1, 2])
def test_native_short_polygon_boundary(width, count):
    dc = RasterContext(128, 128)
    dc.select_object(dc.create_pen(0, width, 0))
    dc.polygon(((30, 30), (60, 50))[:count])
    ink = sum(pixel != (255, 255, 255) for pixel in dc.image.get_flattened_data())
    expected = (31 if width == 0 else 115) if count == 2 else 0
    assert ink == expected
