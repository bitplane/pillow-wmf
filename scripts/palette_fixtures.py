"""Logical-palette oracle cases on the RGB reference device."""

from struct import pack

from pillow_wmf import Recorder
from pillow_wmf.bitmap import encode_dib
from pillow_wmf.wmf.objects import BitmapData, Palette

ENTRIES = ((213, 31, 67, 0), (17, 179, 93, 1), (59, 83, 229, 4), (191, 137, 23, 1))


def source(depth=4, usage=1, indices=(3, 0, 2, 1), *, top_down=False, rle=False, header=40):
    dib = encode_dib(
        8,
        4,
        tuple((x + y) % 4 for y in range(4) for x in range(8)),
        depth=depth,
        colors=((0, 0, 0),) * 4,
        top_down=top_down,
        rle=rle,
        header_size=header,
    )
    return BitmapData(
        "dib", dib.data[:header] + (pack("4H", *indices) if usage == 1 else b"") + dib.data[header + 16 :]
    )


def draw(r, dib, usage, y, operation="stretch_dib"):
    if operation == "stretch_dib":
        r.stretch_dib(2, y, 112, 12, 0, 0, 8, 4, 0xCC0020, usage, dib)
    elif operation == "device":
        r.set_dib_to_device(2, y, 8, 4, 0, 0, 0, 4, usage, dib)
    else:
        brush = r.create_dib_pattern_brush(5, usage, dib)
        r.select_object(brush)
        r.pat_blt(2, y, 112, 12, 0xF00021)


def cases():
    yield from holdouts()
    for flags in (0, 1, 2, 4):
        r = Recorder()
        r.set_stretch_mode(3)
        entries = (
            tuple((v, 0, 73, flags) for v in (0, 7, 12, 19)) if flags == 2 else tuple((*e[:3], flags) for e in ENTRIES)
        )
        r.select_palette(r.create_palette(Palette(entries=entries)))
        draw(r, source(), 1, 2)
        r.animate_palette(Palette(0, ((31, 71, 131, 0),) * 4))
        draw(r, source(), 1, 22)
        r.animate_palette(Palette(0, ((193, 139, 83, 1),) * 4))
        draw(r, source(), 1, 42)
        r.realize_palette()
        draw(r, source(), 1, 62)
        yield f"palette-entry-flags-{flags}", r

    for usage in (1, 2):
        for operation in ("stretch_dib", "device", "brush"):
            r = Recorder()
            r.set_stretch_mode(3)
            dib = source(usage=usage)
            draw(r, dib, usage, 2, operation)
            palette = r.create_palette(Palette(entries=ENTRIES))
            r.select_palette(palette)
            draw(r, dib, usage, 18, operation)
            r.realize_palette()
            draw(r, dib, usage, 34, operation)
            r.set_palette_entries(Palette(1, ((41, 61, 81, 0), (211, 151, 101, 0))))
            draw(r, dib, usage, 50, operation)
            r.realize_palette()
            draw(r, dib, usage, 66, operation)
            r.animate_palette(Palette(0, ((127, 15, 171, 1),) * 4))
            draw(r, dib, usage, 82, operation)
            r.resize_palette(2)
            r.resize_palette(4)
            draw(r, dib, usage, 98, operation)
            yield f"palette-state-{usage}-{operation}", r

    r = Recorder()
    r.set_stretch_mode(3)
    a = r.create_palette(Palette(entries=ENTRIES))
    b = r.create_palette(Palette(entries=tuple(reversed(ENTRIES))))
    dib = source()
    r.select_palette(a)
    r.save_dc()
    r.select_palette(b)
    r.save_dc()
    r.set_palette_entries(Palette(0, ((37, 57, 97, 0),)))
    draw(r, dib, 1, 2)
    r.restore_dc(-1)
    draw(r, dib, 1, 18)
    r.restore_dc(-1)
    draw(r, dib, 1, 34)
    r.select_palette(b)
    draw(r, dib, 1, 50)
    r.delete_object(a)
    yield "palette-save-selection-not-contents", r

    for depth in (4, 8):
        r = Recorder()
        r.set_stretch_mode(3)
        r.select_palette(r.create_palette(Palette(entries=ENTRIES)))
        for i, (header, top, rle) in enumerate(
            ((40, False, False), (40, True, False), (108, False, False), (124, True, False), (40, False, True))
        ):
            draw(r, source(depth, top_down=top, rle=rle, header=header), 1, 2 + i * 22)
        yield f"palette-dib-formats-{depth}", r

    r = Recorder()
    r.set_stretch_mode(3)
    r.select_palette(r.create_palette(Palette(entries=ENTRIES)))
    for i, indices in enumerate(((0, 1, 2, 3), (4, 5, 6, 7), (20, 255, 256, 65535))):
        draw(r, source(indices=indices), 1, 2 + i * 18)
    yield "palette-dib-index-bounds", r

    r = Recorder()
    r.set_stretch_mode(3)
    r.select_palette(r.create_palette(Palette(entries=ENTRIES)))
    brush = r.create_dib_pattern_brush(5, 1, source())
    r.select_object(brush)
    r.pat_blt(2, 2, 112, 12, 0xF00021)
    r.set_palette_entries(Palette(0, ((21, 43, 65, 0),) * 4))
    r.pat_blt(2, 18, 112, 12, 0xF00021)
    r.select_palette(r.create_palette(Palette(entries=tuple(reversed(ENTRIES)))))
    r.pat_blt(2, 34, 112, 12, 0xF00021)
    r.select_object(brush)
    r.pat_blt(2, 50, 112, 12, 0xF00021)
    yield "palette-brush-realization", r


def holdouts():
    r = Recorder()
    r.set_stretch_mode(3)
    # The default logical palette, including wraparound and high WORD indexes.
    for i in range(8):
        draw(r, source(indices=tuple(range(i * 4, i * 4 + 4))), 1, i * 15)
    yield "palette-default-table", r

    r = Recorder()
    r.set_stretch_mode(3)
    r.select_palette(r.create_palette(Palette(entries=ENTRIES)))
    for i, (depth, count, top) in enumerate(((1, 2, False), (1, 2, True), (4, 3, False), (8, 3, True))):
        dib = encode_dib(
            7,
            3,
            tuple(j % count for j in range(21)),
            depth=depth,
            colors=((0, 0, 0),) * count,
            top_down=top,
        )
        dib = BitmapData(
            "dib", dib.data[:40] + pack("<" + "H" * count, *reversed(range(count))) + dib.data[40 + 4 * count :]
        )
        r.stretch_dib(2, i * 30, 56, 24, 0, 0, 7, 3, 0xCC0020, 1, dib)
        r.select_object(r.create_dib_pattern_brush(5, 1, dib))
        r.pat_blt(64, i * 30, 56, 24, 0xF00021)
    yield "palette-dib-packing", r

    r = Recorder()
    r.select_palette(r.create_palette(Palette(entries=ENTRIES)))
    r.set_stretch_mode(3)
    for i, (depth, usage) in enumerate(((d, u) for d in (16, 24, 32) for u in (1, 2))):
        dib = encode_dib(8, 4, (0x7351,) * 32, depth=depth)
        draw(r, dib, usage, 2 + i * 20)
    yield "palette-direct-depth-usage", r

    # COLORREF palette indexes are separate from DIB colour-table indexes.
    r = Recorder()
    r.select_palette(r.create_palette(Palette(entries=ENTRIES)))
    for row, flag in enumerate((0x01000000, 0x02000000)):
        for i in range(8):
            value = flag | (i if row == 0 else 0x5DAB21 + i * 0x10101)
            r.set_pixel(2 + i * 14, row * 32, value)
            r.select_object(r.create_brush(0, value, 0))
            r.pat_blt(2 + i * 14, row * 32 + 2, 12, 12, 0xF00021)
    yield "palette-colorrefs", r
