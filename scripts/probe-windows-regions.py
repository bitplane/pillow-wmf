"""Inspect native WMF region handles and device clip displacement."""

import ctypes
from ctypes import wintypes
from itertools import product

from windows_wmf_render import bind, check, reference_surface, render_wmf

from pillow_wmf import Metafile, RasterContext, Recorder, play
from pillow_wmf.mapping import Mapping
from pillow_wmf.wmf.objects import Region, Scan


def verify_pixels():
    regions = (
        Region((0, 0, 0, 0), ()),
        Region((8, 8, 8, 16), (Scan(8, 16, (8, 8)),)),
        Region((8, 8, 112, 112), (Scan(8, 32, (8, 112)), Scan(32, 80, (8, 32, 80, 112)), Scan(80, 112, (8, 112)))),
    )
    failures = 0
    for index, (region, operation, state, extent) in enumerate(
        product(
            regions,
            ("rectangle", "ellipse", "round_rect", "arc", "polygon", "polyline"),
            ("select", "intersect", "exclude", "offset", "restore", "clear"),
            ((128, 128), (192, 64), (-128, 128)),
        )
    ):
        recorder = Recorder()
        recorder.set_map_mode(8)
        recorder.set_window_extent(128, 128)
        recorder.select_object(recorder.create_pen(0, 3, 0x00402010))
        recorder.select_object(recorder.create_brush(2 if index % 2 else 0, 0x00CC8844, 5))
        handle = recorder.create_region(region)
        recorder.select_clip_region(handle)
        recorder.delete_object(handle)
        recorder.set_viewport_extent(*extent)
        recorder.set_viewport_origin(128 if extent[0] < 0 else 0, 0)
        if state == "intersect":
            recorder.intersect_clip_rect(16, 16, 96, 96)
        elif state == "exclude":
            recorder.exclude_clip_rect(16, 16, 96, 96)
        elif state == "offset":
            recorder.offset_clip_region(7, -9)
        elif state == "restore":
            recorder.save_dc()
            recorder.select_clip_region(None)
            recorder.restore_dc(-1)
        elif state == "clear":
            recorder.select_clip_region(None)
        recorder.set_rop2(7 if index % 3 == 0 else 13)
        if operation in ("polygon", "polyline"):
            getattr(recorder, operation)(((4, 4), (112, 48), (16, 112), (4, 4)))
        else:
            args = (4, 4, 112, 112)
            if operation == "round_rect":
                args += (16, 24)
            elif operation == "arc":
                args += (112, 32, 4, 80)
            getattr(recorder, operation)(*args)
        data = recorder.to_bytes()
        expected = render_wmf(data, 128, 128)
        context = RasterContext(128, 128)
        assert play(Metafile.from_bytes(data), context, strict=True) == ()
        differing = sum(
            a != b for a, b in zip(expected.get_flattened_data(), context.image.get_flattened_data(), strict=True)
        )
        if differing:
            failures += 1
            print("region-pixels-FAIL", index, operation, state, extent, differing)
    print("region-pixel-matrix", index + 1, failures)
    assert not failures


def main():
    with reference_surface(128, 128) as (gdi, dc, _bits):
        ptr, integer = ctypes.c_void_p, ctypes.c_int
        bind(gdi, "CreateRectRgn", ptr, integer, integer, integer, integer)
        bind(gdi, "SelectClipRgn", integer, ptr, ptr)
        bind(gdi, "OffsetClipRgn", integer, ptr, integer, integer)
        bind(gdi, "GetClipBox", integer, ptr, ctypes.POINTER(wintypes.RECT))
        bind(gdi, "GetObjectType", wintypes.DWORD, ptr)
        bind(gdi, "SetMetaFileBitsEx", ptr, wintypes.UINT, ptr)
        bind(gdi, "DeleteMetaFile", wintypes.BOOL, ptr)
        bind(gdi, "PlayMetaFileRecord", wintypes.BOOL, ptr, ptr, ptr, wintypes.UINT)
        callback_type = ctypes.WINFUNCTYPE(integer, ptr, ctypes.POINTER(ptr), ptr, integer, ctypes.c_ssize_t)
        bind(gdi, "EnumMetaFile", wintypes.BOOL, ptr, ptr, callback_type, ctypes.c_ssize_t)
        observations = []
        for scans in ((), (Scan(8, 16, (8, 8)),), (Scan(8, 16, (8, 32)),)):
            recorder = Recorder()
            recorder.create_region(Region((8, 8, 32, 16), scans))
            data = recorder.to_bytes()
            buffer = ctypes.create_string_buffer(data)
            metafile = check(gdi.SetMetaFileBitsEx(len(data), buffer), "SetMetaFileBitsEx")
            print("region-input", scans)

            @callback_type
            def callback(hdc, handles, record, count, _param):
                result = gdi.PlayMetaFileRecord(hdc, handles, record, count)
                function = ctypes.cast(record, ctypes.POINTER(ctypes.c_ushort))[2]
                if function == 0x6FF:
                    outcome = bool(result), bool(handles[0]), gdi.GetObjectType(handles[0])
                    observations.append(outcome)
                    print("region-handle", *outcome)
                return 1

            try:
                check(gdi.EnumMetaFile(dc, metafile, callback, 0), "EnumMetaFile")
            finally:
                gdi.DeleteMetaFile(metafile)
        assert observations == [(False, False, 0), (True, True, 8), (True, True, 8)]
        region = check(gdi.CreateRectRgn(32, 32, 64, 64), "CreateRectRgn")
        try:
            for extent in ((192, 64), (-192, -64), (80, 80)):
                for x, y in ((7, -9), (-7, 9), (1, 1), (-1, -1), (3, -3)):
                    check(gdi.SetViewportExtEx(dc, *extent, None), "SetViewportExtEx")
                    check(gdi.SelectClipRgn(dc, region), "SelectClipRgn")
                    check(gdi.OffsetClipRgn(dc, x, y), "OffsetClipRgn")
                    check(gdi.SetViewportExtEx(dc, 128, 128, None), "SetViewportExtEx")
                    box = wintypes.RECT()
                    gdi.GetClipBox(dc, ctypes.byref(box))
                    dx, dy = Mapping(viewport_extent=extent).clip_displacement(x, y)
                    assert (box.left, box.top, box.right, box.bottom) == (32 + dx, 32 + dy, 64 + dx, 64 + dy)
                    print("clip-offset", extent, (x, y), (box.left, box.top, box.right, box.bottom))
        finally:
            gdi.SelectClipRgn(dc, None)
            gdi.DeleteObject(region)


if __name__ == "__main__":
    main()
    verify_pixels()
