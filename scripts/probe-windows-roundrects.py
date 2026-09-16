"""Capture native RoundRect controls before reconstructing corner geometry."""

import ctypes
from ctypes import wintypes
from itertools import product

from windows_wmf_render import bind, check, reference_surface, render_wmf

from pillow_wmf import Metafile, RasterContext, Recorder, play
from pillow_wmf.ellipse import round_rect_figure


def verify_pixels():
    failures = 0
    cases = product(
        ((13, 17, 113, 110), (6, 9, 29, 32), (61, 8, 62, 120), (8, 8, 8, 64)),
        ((0, 13), (1, 1), (3, 5), (17, 29), (200, 200), (-17, -29)),
        ((0, 1), (0, 7), (4, 1), (5, 1)),
        (0, 1, 2),
    )
    for index, (box, size, pen, brush) in enumerate(cases):
        recorder = Recorder()
        recorder.select_object(recorder.create_pen(*pen, 0x00402010))
        recorder.select_object(recorder.create_brush(brush, 0x00CC8844, 5))
        recorder.set_rop2(7 if index % 3 == 0 else 13)
        recorder.set_background_mode(1 if index % 2 else 2)
        if index % 5 == 0:
            recorder.intersect_clip_rect(17, 23, 91, 103)
        recorder.round_rect(*box, *size)
        data = recorder.to_bytes()
        native = render_wmf(data, 128, 128)
        context = RasterContext(128, 128)
        assert play(Metafile.from_bytes(data), context, strict=True) == ()
        differing = sum(
            a != b for a, b in zip(native.get_flattened_data(), context.image.get_flattened_data(), strict=True)
        )
        if differing:
            failures += 1
            print("roundrect-pixels-FAIL", index, box, size, pen, brush, differing)
    print("roundrect-pixel-matrix", index + 1, failures)
    assert not failures


def main():
    with reference_surface(128, 128) as (gdi, dc, _bits):
        ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
        for name in ("BeginPath", "EndPath", "AbortPath"):
            bind(gdi, name, boolean, ptr)
        bind(gdi, "RoundRect", boolean, ptr, *([integer] * 6))
        bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
        bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)
        for style, width in ((0, 1), (0, 7), (5, 1)):
            pen = check(gdi.CreatePen(style, width, 0), "CreatePen")
            old = check(gdi.SelectObject(dc, pen), "SelectObject")
            try:
                for box, size in product(
                    ((8, 16, 120, 112), (5, 6, 26, 28)),
                    ((17, 29), (0, 0), (0, 12), (1, 1), (2, 2), (3, 5), (21, 22), (200, 200), (-17, 29)),
                ):
                    check(gdi.BeginPath(dc), "BeginPath")
                    check(gdi.RoundRect(dc, *box, *size), "RoundRect")
                    check(gdi.EndPath(dc), "EndPath")
                    check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                    count = gdi.GetPath(dc, None, None, 0)
                    assert count >= 0
                    points = (wintypes.POINT * count)()
                    kinds = (ctypes.c_ubyte * count)()
                    assert gdi.GetPath(dc, points, kinds, count) == count
                    path = round_rect_figure(*box, *size, null_pen=style == 5)
                    expected = (path.commands[0][0], *(p for c in path.commands[:-1] for p in c[1:]))
                    assert tuple((p.x, p.y) for p in points) == expected, (style, width, box, size)
                    expected_kinds = [6]
                    for command in path.commands[:-1]:
                        expected_kinds.extend([4] * 3 if len(command) == 4 else [2])
                    expected_kinds[-1] |= 1
                    assert tuple(kinds) == tuple(expected_kinds)
                    print(
                        "RoundRect",
                        style,
                        width,
                        box,
                        size,
                        tuple((p.x, p.y, k) for p, k in zip(points, kinds, strict=True)),
                    )
                    check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")
                    check(gdi.AbortPath(dc), "AbortPath")
            finally:
                gdi.SelectObject(dc, old)
                gdi.DeleteObject(pen)


if __name__ == "__main__":
    main()
    verify_pixels()
