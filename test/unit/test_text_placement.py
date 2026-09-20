"""Physical glyph indices and two-dimensional text placement."""

from pathlib import Path
from struct import pack

import pytest

from pillow_wmf import FontCollection, FontFace, RasterContext
from pillow_wmf.wmf.objects import Font


def context():
    face = FontFace.from_path(Path(__file__).parents[1] / "fonts/layout.ttf")
    dc = RasterContext(192, 128, fonts=FontCollection([face]))
    dc.select_object(dc.create_font(Font(height=-24, quality=3, face_name=face.family.encode())))
    dc.set_background_mode(1)
    dc.set_text_alignment(25)
    dc.move_to(80, 80)
    return dc


@pytest.mark.parametrize("suffix", [b"", b"Z"])
def test_glyph_ids_bypass_character_decoding_and_ignore_odd_tail(suffix):
    indexed, ordinary = context(), context()
    indexed.ext_text_out(0, 0, pack("<3H", 2, 3, 2) + suffix, options=0x10)
    ordinary.ext_text_out(0, 0, b"ABA")
    assert indexed.image.tobytes() == ordinary.image.tobytes()
    assert indexed._position == ordinary._position == (119, 80)


def test_glyph_ids_use_first_spacing_entries_not_byte_pair_sums():
    indexed, ordinary = context(), context()
    indexed.ext_text_out(0, 0, pack("<3H", 2, 3, 2), options=0x10, advances=(19, 23, 17, 31, 37, 41))
    ordinary.ext_text_out(0, 0, b"ABA", advances=(19, 23, 17))
    assert indexed.image.tobytes() == ordinary.image.tobytes()
    assert indexed._position == ordinary._position == (139, 80)


def test_invalid_glyph_ids_use_notdef_without_unicode_fallback():
    invalid, notdef = context(), context()
    invalid.ext_text_out(0, 0, pack("<3H", 0, 0xFFFF, 2), options=0x10)
    notdef.ext_text_out(0, 0, pack("<3H", 0, 0, 2), options=0x10)
    assert invalid.image.tobytes() == notdef.image.tobytes()
    assert invalid._position == (118, 80)


@pytest.mark.parametrize("alignment,position", [(25, (139, 67)), (27, (21, 67)), (31, (80, 80))])
def test_paired_advance_current_position(alignment, position):
    dc = context()
    dc.set_text_alignment(alignment)
    dc.ext_text_out(0, 0, b"ABA", options=0x2000, advances=(19, 7, 23, -5, 17, 11))
    assert dc._position == position


def test_paired_glyph_spacing_shares_character_placement():
    indexed, ordinary = context(), context()
    advances = (19, 7, 23, -5, 17, 11)
    indexed.ext_text_out(0, 0, pack("<3H", 2, 3, 2), options=0x2010, advances=advances * 2)
    ordinary.ext_text_out(0, 0, b"ABA", options=0x2000, advances=advances)
    assert indexed.image.tobytes() == ordinary.image.tobytes()
    assert indexed._position == ordinary._position == (139, 67)


def test_paired_output_without_spacing_is_a_native_noop():
    dc = context()
    before = dc.image.tobytes()
    dc.ext_text_out(0, 0, b"ABA", options=0x2000)
    assert dc.image.tobytes() == before
    assert dc._position == (80, 80)


def test_rotated_opaque_paired_output_bounds_positioned_cells():
    dc = context()
    dc.select_object(dc.create_font(Font(height=-24, quality=3, escapement=900, face_name=b"Pillow WMF Test")))
    dc.set_background_mode(2)
    args = dict(x=0, y=0, text=b"ABA", options=0x2000, advances=(19, 7, 23, -5, 17, 11))
    layout, _ = dc._prepare_text(args)
    assert layout.background == ((51, 24), (88, 24), (88, 81), (51, 81))
    dc.ext_text_out(**args)
    assert dc._position == (67, 21)


@pytest.mark.parametrize(
    "size,angle,cell",
    [(24, 1800, (22, 7)), (24, 900, (22, 8)), (24, 300, (18, 6)), (31, -300, (23, 7)), (19, 1200, (14, 5))],
)
def test_native_rotated_cell_metrics(size, angle, cell):
    face = FontFace.from_path(Path(__file__).parents[1] / "fonts/layout.ttf")
    assert face.at_size(size, escapement=angle).background_cell == cell


def test_oblique_cell_uses_outline_bounds_not_normalized_windows_metrics():
    face = FontFace.from_path(Path(__file__).parents[1] / "fonts/layout.ttf")
    # The outline box and Windows cell are independent font inputs.
    face.ascent, face.descent = 1100, 400
    assert face.at_size(31, escapement=300).background_cell == (23, 7)
