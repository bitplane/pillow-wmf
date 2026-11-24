"""Print the world transform native EMF playback derives after each record.

During playback the DC stays in MM_TEXT and GM_ADVANCED; the picture-frame
fit, the metafile's page mapping and its world transform are combined into
the DC's world transform. Cases are generated deterministically, so each
output line names a case and record index instead of repeating its inputs:

    case record-index record-type m11 m12 m21 m22 dx dy   (float32 bit patterns)

``record-index`` 0 is the header. No reference images are written.
"""

import ctypes
import platform
import random
import struct
from ctypes import wintypes
from dataclasses import replace

from windows_wmf_render import bind, check, module_versions, reference_surface

from pillow_wmf.emf import Header, Metafile, fixed
from pillow_wmf.mapping import REFERENCE_DEVICE, ReferenceDevice

SIZE = 16


class XForm(ctypes.Structure):
    _fields_ = [(name, ctypes.c_float) for name in ("m11", "m12", "m21", "m22", "dx", "dy")]


def f32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


FLOATS = (0.0, 1.0, -1.0, 0.5, 2.0, 0.1, -0.3, 1.5, 3.25, 1e-3, 7.0 / 3.0, -12.75, 100.0, 0.7071067811865476)


def header(frame, rect, device=REFERENCE_DEVICE, micrometres=None):
    result = Header.create((0, 0, -1, -1), frame, device=device)
    if micrometres is not None:
        result = replace(result, extra=result.extra[:12] + struct.pack("<2i", *micrometres))
    return result, rect


def frame_cases(rng):
    """(name, header, rect): only the header's transform is observed."""
    full = (0, 0, 128, 128)
    for right in range(3370, 3406):
        yield f"near-{right}", *header((0, 0, right, right), full)
    for size in (16, 64, 100, 256, 1000, 4096):
        nominal = size * 27100 / 1024
        for delta in (-3, -2, -1, 0, 1, 2, 3):
            right = round(nominal) + delta
            yield (
                f"near-rect-{size}-{delta}",
                *header((0, 0, right, round(size * 20300 / 768) + delta), (0, 0, size, size)),
            )
    for offset in (1, -1, 37, 5000):
        yield f"near-offset-{offset}", *header((offset, offset, offset + 3386, offset + 3386), full)
        yield f"near-rect-offset-{offset}", *header((0, 0, 3386, 3386), (offset, offset, offset + 128, offset + 128))
    yield "near-reversed", *header((0, 0, 3386, 3386), (128, 128, 0, 0))
    yield "near-device-800", *header((0, 0, 3200, 3200), full, ReferenceDevice((800, 600), (200, 150)))
    yield "near-micrometres", *header((0, 0, 3386, 3386), full, micrometres=(270000, 200000))
    yield "micrometres", *header((0, 0, 1000, 1000), full, micrometres=(135500, 101500))
    yield "empty-frame-x", *header((0, 0, 0, 1000), full)
    yield "empty-frame-y", *header((0, 0, 1000, 0), full)
    yield "reversed-frame", *header((1000, 1000, 0, 0), full)
    for index in range(400):
        width = rng.choice((rng.randint(1, 40), rng.randint(1, 20000)))
        height = rng.choice((rng.randint(1, 40), rng.randint(1, 20000)))
        left, top = rng.randint(-5000, 5000), rng.randint(-5000, 5000)
        rect_left, rect_top = rng.randint(-200, 200), rng.randint(-200, 200)
        rect = (rect_left, rect_top, rect_left + rng.randint(1, 600), rect_top + rng.randint(1, 600))
        device = ReferenceDevice(
            (rng.randint(100, 4000), rng.randint(100, 4000)), (rng.randint(50, 800), rng.randint(50, 800))
        )
        yield f"random-{index}", *header((left, top, left + width, top + height), rect, device)


def random_record(rng):
    coordinate = lambda: rng.choice((rng.randint(-20, 20), rng.randint(-40000, 40000)))  # noqa: E731
    matrix = lambda: [f32(rng.choice(FLOATS)) for _ in range(6)]  # noqa: E731
    choice = rng.randrange(11)
    if choice == 0:
        return fixed.SetMapMode(rng.randint(1, 8))
    if choice == 1:
        return fixed.SetWindowOrgEx(coordinate(), coordinate())
    if choice == 2:
        return fixed.SetWindowExtEx(coordinate(), coordinate())
    if choice == 3:
        return fixed.SetViewportOrgEx(coordinate(), coordinate())
    if choice == 4:
        return fixed.SetViewportExtEx(coordinate(), coordinate())
    if choice == 5:
        return fixed.ScaleWindowExtEx(*(rng.randint(-5, 9) for _ in range(4)))
    if choice == 6:
        return fixed.ScaleViewportExtEx(*(rng.randint(-5, 9) for _ in range(4)))
    if choice == 7:
        return fixed.SetWorldTransform(*matrix())
    if choice == 8:
        return fixed.ModifyWorldTransform(*matrix(), rng.randint(1, 4))
    if choice == 9:
        return fixed.SaveDC()
    return fixed.RestoreDC(-1)


def sequence_cases(rng):
    """(name, header, rect, records)."""
    page = [fixed.SetMapMode(8), fixed.SetWindowExtEx(300, 200), fixed.SetViewportExtEx(37, 37)]
    for mode in range(1, 9):
        yield f"mode-{mode}", *header((0, 0, 1000, 1000), (0, 0, 128, 128)), [fixed.SetMapMode(mode)]
        device = ReferenceDevice((800, 600), (200, 150))
        yield f"mode-{mode}-device", *header((0, 0, 1000, 1000), (0, 0, 128, 128), device), [fixed.SetMapMode(mode)]
        yield (
            f"mode-{mode}-micrometres",
            *header((0, 0, 1000, 1000), (0, 0, 128, 128), micrometres=(135500, 101500)),
            [fixed.SetMapMode(mode)],
        )
    yield "page", *header((0, 0, 1000, 1000), (0, 0, 128, 128)), page
    yield "page-near-identity", *header((0, 0, 3386, 3386), (0, 0, 128, 128)), page
    for index in range(300):
        frame = (rng.randint(-500, 500), rng.randint(-500, 500))
        frame += (frame[0] + rng.randint(1, 9000), frame[1] + rng.randint(1, 9000))
        records = [random_record(rng) for _ in range(rng.randint(2, 9))]
        yield f"sequence-{index}", *header(frame, (0, 0, 128, 128)), records


def bits(transform):
    return " ".join(struct.pack("<f", getattr(transform, name)).hex() for name, _ in XForm._fields_)


def run(name, emf_header, rect, records, gdi):
    data = Metafile(emf_header, Metafile.build(records).records).to_bytes(canonical=True)
    lines = []
    callback_type = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, wintypes.LPARAM
    )
    position = [0]

    def visit(hdc, table, record, handles, _):
        kind = ctypes.cast(record, ctypes.POINTER(wintypes.DWORD))[0]
        played = gdi.PlayEnhMetaFileRecord(hdc, table, record, handles)
        transform = XForm()
        check(gdi.GetWorldTransform(hdc, ctypes.byref(transform)), "GetWorldTransform")
        extra = f" mode={gdi.GetMapMode(hdc)} gm={gdi.GetGraphicsMode(hdc)}" if not position[0] else ""
        failed = "" if played else " failed"
        lines.append(f"{name} {position[0]} {kind} {bits(transform)}{extra}{failed}")
        position[0] += 1
        return 1

    with reference_surface(SIZE, SIZE) as (_, dc, _bits):
        buffer = ctypes.create_string_buffer(data)
        metafile = check(gdi.SetEnhMetaFileBits(len(data), buffer), "SetEnhMetaFileBits")
        try:
            callback = callback_type(visit)
            enum = bind(
                gdi,
                "EnumEnhMetaFile",
                wintypes.BOOL,
                ctypes.c_void_p,
                ctypes.c_void_p,
                callback_type,
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.RECT),
            )
            result = enum(dc, metafile, callback, None, ctypes.byref(wintypes.RECT(*rect)))
        finally:
            gdi.DeleteEnhMetaFile(metafile)
    print("\n".join(lines) + ("" if result else f"\n{name} enumeration-failed"))


def main():
    print(f"Windows EMF transform probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    ptr = ctypes.c_void_p
    bind(gdi, "GetWorldTransform", wintypes.BOOL, ptr, ctypes.POINTER(XForm))
    bind(gdi, "GetMapMode", ctypes.c_int, ptr)
    bind(gdi, "GetGraphicsMode", ctypes.c_int, ptr)
    bind(gdi, "SetEnhMetaFileBits", ptr, wintypes.UINT, ptr)
    bind(gdi, "DeleteEnhMetaFile", wintypes.BOOL, ptr)
    bind(gdi, "PlayEnhMetaFileRecord", wintypes.BOOL, ptr, ptr, ptr, wintypes.UINT)
    for name, emf_header, rect in frame_cases(random.Random(0xEF1)):
        run(name, emf_header, rect, [], gdi)
    for name, emf_header, rect, records in sequence_cases(random.Random(0xEF2)):
        run(name, emf_header, rect, records, gdi)


if __name__ == "__main__":
    main()
