"""Native RTL layout keeps glyphs readable while mirroring reference edges."""

import pytest

from pillow_wmf import Font, FontCollection, RasterContext
from pillow_wmf.objects import EncodedText


def rtl_context(face, *, width=192, alignment=25, angle=0, extent=(128, 128)):
    dc = RasterContext(width, 128, fonts=FontCollection([face]))
    dc.select_object(dc.create_font(Font(height=-24, quality=3, escapement=angle, face_name=face.family.encode())))
    dc.set_layout(1)
    dc.set_window_extent(128, 128)
    dc.set_viewport_extent(*extent)
    dc.set_window_origin(-3, 2)
    dc.set_viewport_origin(7, 5)
    dc.set_background_mode(1)
    dc.set_background_color(0x99CCFF)
    dc.set_text_alignment(alignment)
    dc.move_to(45, 65)
    return dc


def text_arguments(options=0):
    return dict(
        x=80,
        y=80,
        text=EncodedText(b"ABA"),
        options=options,
        advances=(19, 7, 23, -5, 17, 11) if options & 0x2000 else (19, 23, 17),
        rectangle=(35, 40, 105, 90) if options & 6 else None,
    )


@pytest.mark.parametrize(
    "alignment,options,angle,extent,position",
    [
        (25, 0, 0, (128, 128), (104, 65)),
        (27, 0, 0, (128, 128), (-14, 65)),
        (31, 0, 0, (128, 128), (45, 65)),
        (25, 6, 0, (128, 128), (104, 65)),
        (25, 0, 900, (128, 128), (45, 6)),
        (25, 0, 300, (128, 128), (97, 35)),
        (25, 0, 0, (192, 160), (104, 64)),
        (25, 0x2000, 0, (128, 128), (104, 78)),
        (27, 0x2000, 0, (128, 128), (-14, 52)),
        (31, 0x2000, 0, (128, 128), (45, 65)),
    ],
)
def test_native_rtl_current_position(face, alignment, options, angle, extent, position):
    dc = rtl_context(face, alignment=alignment, angle=angle, extent=extent)
    layout, _ = dc._prepare_text(text_arguments(options))
    # GetCurrentPositionEx exposes integer logical coordinates. The renderer
    # retains the fractional inverse mapping for subsequent device placement.
    if alignment == 31:
        assert layout.position is None
        assert dc._position == position
    else:
        assert tuple(int(value) for value in layout.position) == position
    assert dc._position == (45, 65)


@pytest.mark.parametrize("alignment,expected", [(25, (104, 78)), (31, (45, 65))])
def test_rtl_drawing_commits_prepared_position(face, alignment, expected):
    dc = rtl_context(face, alignment=alignment)
    dc.ext_text_out(**text_arguments(0x2000))
    assert dc._position == expected


@pytest.mark.parametrize("width,last_glyph_x", [(128, 23), (192, 87)])
def test_fractional_right_alignment_rounds_after_subtracting_run_width(face, width, last_glyph_x):
    dc = rtl_context(face, width=width, extent=(192, 160))
    layout, _ = dc._prepare_text(text_arguments())
    # The 88.5-pixel run is aligned at different fractional reference points.
    # These ink origins are measured in the native PNGs at both canvas widths.
    assert layout.glyphs[-1][:2] == (last_glyph_x, 63)
