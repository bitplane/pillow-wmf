"""Drawing state stays local to a DC and follows nested native save levels."""

from pillow_wmf import RasterContext
from pillow_wmf.wmf.objects import Palette


def test_new_context_does_not_inherit_another_contexts_mapping_or_selections():
    first = RasterContext(12, 4)
    first.set_viewport_origin(4, 0)
    first.select_object(first.create_brush(0, 255, 0))
    first.intersect_clip_rect(0, 0, 1, 1)

    second = RasterContext(12, 4, background=(0, 0, 0))
    second.pat_blt(0, 0, 3, 1, 0xF00021)
    assert list(second.image.crop((0, 0, 4, 1)).get_flattened_data()) == [(255, 255, 255)] * 3 + [(0, 0, 0)]
    first.pat_blt(0, 0, 3, 1, 0xF00021)
    assert first.image.getpixel((4, 0)) == (255, 0, 0)
    assert first.image.getpixel((5, 0)) == (255, 255, 255)


def test_nested_restore_uses_saved_mapping_clip_and_brush_with_live_palette_entries():
    dc = RasterContext(12, 4)
    dc.select_palette(dc.create_palette(Palette(entries=((17, 31, 53, 0),))))
    dc.select_object(dc.create_brush(0, 0x01000000, 0))
    outer = dc.save_dc()

    dc.set_viewport_origin(4, 0)
    dc.intersect_clip_rect(0, 0, 2, 2)
    dc.select_object(dc.create_brush(0, 0xFF0000, 0))
    dc.save_dc()
    dc.set_palette_entries(Palette(0, ((71, 97, 131, 0),)))
    dc.select_palette(dc.create_palette(Palette(entries=((3, 5, 7, 0),))))
    dc.select_object(dc.create_brush(0, 0x00FF00, 0))
    dc.set_viewport_origin(8, 0)

    dc.restore_dc(-1)
    dc.pat_blt(0, 0, 3, 1, 0xF00021)
    assert list(dc.image.crop((4, 0, 7, 1)).get_flattened_data()) == [(0, 0, 255)] * 2 + [(255, 255, 255)]

    dc.restore_dc(outer)
    dc.pat_blt(0, 1, 3, 1, 0xF00021)
    assert list(dc.image.crop((0, 1, 4, 2)).get_flattened_data()) == [(71, 97, 131)] * 3 + [(255, 255, 255)]
