"""Native glyph realization and placement of the controlled layout font under world transforms.

For each case the DC is put in GM_ADVANCED with a world transform and the
controlled font selected, unantialiased. The probe prints, per character,
GetGlyphOutlineW's metrics and monochrome bitmap, then the pixels ExtTextOutW
paints for that character alone and for the run "AB A", at a fixed origin
with baseline alignment:

    case NAME height=H transform=(m11, m12, m21, m22) escapement=E [orientation=O] [weight=700 italic=1]
    glyph CH box=W,H origin=X,Y cell=CX,CY
    bits ROW MASK              (# marks a set bit)
    text LABEL [align=A]       (baseline alignment unless given)
    row Y X0 MASK              (one per changed row)

Then three sweeps: ``box`` lines give the bounds GetBoundsRect accumulates
for runs of a rotated font (identity world, so device pixels), without and
with explicit advances; ``sweep`` blocks draw upright glyphs along a
differing escapement at sixteen sub-pixel offsets per axis (``pair`` blocks
add glyph pairs and explicit advances); ``opaque`` blocks show rotated
and sheared background cells at sub-pixel origins; ``outline``
blocks give GGO_NATIVE points across sizes, transforms and simulated bold
italic.
"""

import ctypes
import platform
import struct
from ctypes import wintypes

from test_font import FAMILY, FONT_PATH
from windows_wmf_render import bind, check, module_versions, private_fonts, reference_surface

SIZE = 96
ORIGIN = (40, 48)
TRANSFORMS = {
    "identity": (1.0, 0.0, 0.0, 1.0),
    "mirror-x": (-1.0, 0.0, 0.0, 1.0),
    "mirror-y": (1.0, 0.0, 0.0, -1.0),
    "scale": (1.5, 0.0, 0.0, 0.75),
    "rotate": (0.9, 0.4, -0.4, 0.9),
    "shear": (1.0, 0.0, 0.45, 1.0),
}


class XForm(ctypes.Structure):
    _fields_ = [(name, ctypes.c_float) for name in ("m11", "m12", "m21", "m22", "dx", "dy")]


class GlyphMetrics(ctypes.Structure):
    _fields_ = [
        ("width", wintypes.UINT),
        ("height", wintypes.UINT),
        ("origin", wintypes.POINT),
        ("cell_x", ctypes.c_short),
        ("cell_y", ctypes.c_short),
    ]


class Fixed(ctypes.Structure):
    _fields_ = [("fract", wintypes.WORD), ("value", ctypes.c_short)]


class Mat2(ctypes.Structure):
    _fields_ = [("m11", Fixed), ("m12", Fixed), ("m21", Fixed), ("m22", Fixed)]


class LogFont(ctypes.Structure):
    _fields_ = [
        ("height", wintypes.LONG),
        ("width", wintypes.LONG),
        ("escapement", wintypes.LONG),
        ("orientation", wintypes.LONG),
        ("weight", wintypes.LONG),
        ("italic", wintypes.BYTE),
        ("underline", wintypes.BYTE),
        ("strikeout", wintypes.BYTE),
        ("charset", wintypes.BYTE),
        ("out_precision", wintypes.BYTE),
        ("clip_precision", wintypes.BYTE),
        ("quality", wintypes.BYTE),
        ("pitch_family", wintypes.BYTE),
        ("face", ctypes.c_wchar * 32),
    ]


def print_native(data):
    """TTPOLYGONHEADER contours of 16.16 device points (y up), one line each."""
    position = 0
    while position < len(data):
        size, _kind = struct.unpack_from("<II", data, position)
        points = [struct.unpack_from("<ii", data, position + 8)]
        cursor = position + 16
        while cursor < position + size:
            kind, count = struct.unpack_from("<HH", data, cursor)
            points += [struct.unpack_from("<ii", data, cursor + 4 + 8 * i) for i in range(count)]
            cursor += 4 + 8 * count
        print("native " + " ".join(f"{x},{y}" for x, y in points))
        position += size


def cases():
    """(name, height, transform, escapement, orientation) cases."""
    for height in (-10, -25):
        for name, matrix in TRANSFORMS.items():
            yield name, height, matrix, 0, 0
    yield "escapement", -10, TRANSFORMS["identity"], 300, 300
    yield "escapement-scale", -10, TRANSFORMS["scale"], 300, 300
    # A 4-unit em under the EMF fixtures' 128/51 playback scale: fractional
    # device em sizes.
    for name, matrix in TRANSFORMS.items():
        yield f"{name}-fractional", -4, tuple(value * 128 / 51 for value in matrix), 0, 0
    # Upright glyphs along a different escapement (per-glyph projection).
    for name, escapement in (("identity", 300), ("identity", 900), ("rotate", 300), ("mirror-x", 300)):
        yield f"upright-{name}-{escapement}", -25, TRANSFORMS[name], escapement, 0
    # The default height (zero) at the EMF fixtures' fractional playback scale.
    for name in ("identity", "mirror-x", "scale"):
        yield f"default-{name}-fractional", 0, tuple(value * 128 / 51 for value in TRANSFORMS[name]), 0, 0
    # Simulated bold italic (the controlled face has neither) at the EMF
    # style fixture's sizes.
    for name in ("identity", "mirror-x", "rotate", "shear"):
        yield f"synthetic-{name}", -8, TRANSFORMS[name], 0, 0
        yield f"synthetic-{name}-fractional", -8, tuple(value * 128 / 51 for value in TRANSFORMS[name]), 0, 0
    # The EMF escapement fixture's own size.
    for name in ("rotate", "shear", "mirror-x"):
        yield f"upright-{name}-300-small", -8, TRANSFORMS[name], 300, 0


def main():
    print(f"Windows glyph transform probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    with private_fonts([FONT_PATH]), reference_surface(SIZE, SIZE) as (gdi, dc, bits):
        ptr = ctypes.c_void_p
        set_mode = bind(gdi, "SetGraphicsMode", ctypes.c_int, ptr, ctypes.c_int)
        set_world = bind(gdi, "SetWorldTransform", wintypes.BOOL, ptr, ctypes.POINTER(XForm))
        create_font = bind(gdi, "CreateFontIndirectW", ptr, ctypes.POINTER(LogFont))
        select = bind(gdi, "SelectObject", ptr, ptr, ptr)
        delete = bind(gdi, "DeleteObject", wintypes.BOOL, ptr)
        outline = bind(
            gdi, "GetGlyphOutlineW", wintypes.DWORD, ptr, wintypes.UINT, wintypes.UINT, ptr, wintypes.DWORD, ptr, ptr
        )
        text_out = bind(
            gdi,
            "ExtTextOutW",
            wintypes.BOOL,
            ptr,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
            ptr,
            ctypes.c_wchar_p,
            wintypes.UINT,
            ptr,
        )
        set_align = bind(gdi, "SetTextAlign", wintypes.UINT, ptr, wintypes.UINT)
        set_bk = bind(gdi, "SetBkMode", ctypes.c_int, ptr, ctypes.c_int)
        pixels = ctypes.cast(bits, ctypes.POINTER(ctypes.c_uint32))
        identity = Mat2(Fixed(0, 1), Fixed(0, 0), Fixed(0, 0), Fixed(0, 1))
        check(set_mode(dc, 2), "SetGraphicsMode")
        set_bk(dc, 1)
        set_align(dc, 24)  # TA_BASELINE
        for name, height, matrix, escapement, orientation in cases():
            extra = f" orientation={orientation}" if orientation != escapement else ""
            weight, italic = (700, 1) if name.startswith("synthetic-") else (400, 0)
            extra += " weight=700 italic=1" if italic else ""
            print(f"case {name} height={height} transform={matrix} escapement={escapement}{extra}")
            check(set_world(dc, ctypes.byref(XForm(*matrix, 0.0, 0.0))), "SetWorldTransform")
            logfont = LogFont(height, 0, escapement, orientation, weight, italic, 0, 0, 0, 0, 0, 3, 0, FAMILY)
            font = check(create_font(ctypes.byref(logfont)), "CreateFontIndirectW")
            previous = select(dc, font)
            for character in "AB ":
                metrics = GlyphMetrics()
                size = outline(dc, ord(character), 1, ctypes.byref(metrics), 0, None, ctypes.byref(identity))
                buffer = ctypes.create_string_buffer(max(1, size))
                if size not in (0, 0xFFFFFFFF):
                    outline(dc, ord(character), 1, ctypes.byref(metrics), size, buffer, ctypes.byref(identity))
                print(
                    f"glyph {character!r} box={metrics.width},{metrics.height} "
                    f"origin={metrics.origin.x},{metrics.origin.y} cell={metrics.cell_x},{metrics.cell_y}"
                )
                native = outline(dc, ord(character), 2, ctypes.byref(metrics), 0, None, ctypes.byref(identity))
                if native not in (0, 0xFFFFFFFF):
                    data = ctypes.create_string_buffer(native)
                    outline(dc, ord(character), 2, ctypes.byref(metrics), native, data, ctypes.byref(identity))
                    print_native(data.raw)
                if size not in (0, 0xFFFFFFFF) and metrics.width:
                    stride = (metrics.width + 31) // 32 * 4
                    for row in range(metrics.height):
                        line = buffer.raw[row * stride : row * stride + stride]
                        mask = "".join(
                            "#" if line[column // 8] >> (7 - column % 8) & 1 else "." for column in range(metrics.width)
                        )
                        print(f"bits {row} {mask}")
            # The world origin maps to the device origin; draw at its inverse.
            runs = [("A", 24), ("B", 24), ("AB A", 24), ("AB A", 0), ("AB A", 8), ("AB A", 30), ("AB A", 26)]
            if name.endswith("-fractional"):
                runs += [("AB", 24), ("BA", 24), ("AA", 24), ("A A", 24), ("AAAA", 24)]
            for label, alignment in runs:
                ctypes.memset(bits, 0xFF, SIZE * SIZE * 4)
                set_align(dc, alignment)
                set_world(dc, ctypes.byref(XForm(*matrix, float(ORIGIN[0]), float(ORIGIN[1]))))
                text_out(dc, 0, 0, 0, None, label, len(label), None)
                set_world(dc, ctypes.byref(XForm(*matrix, 0.0, 0.0)))
                print(f"text {label!r}" + (f" align={alignment}" if alignment != 24 else ""))
                for y in range(SIZE):
                    row = [pixels[y * SIZE + x] & 0xFFFFFF != 0xFFFFFF for x in range(SIZE)]
                    if any(row):
                        first = row.index(True)
                        last = SIZE - 1 - row[::-1].index(True)
                        print(f"row {y} {first} " + "".join("#" if value else "." for value in row[first : last + 1]))
            select(dc, previous)
            delete(font)

        def make_font(height, escapement, orientation, weight=400, italic=0):
            logfont = LogFont(height, 0, escapement, orientation, weight, italic, 0, 0, 0, 0, 0, 3, 0, FAMILY)
            return check(create_font(ctypes.byref(logfont)), "CreateFontIndirectW")

        def print_rows(label):
            print(label)
            for y in range(SIZE):
                row = [pixels[y * SIZE + x] & 0xFFFFFF != 0xFFFFFF for x in range(SIZE)]
                if any(row):
                    first = row.index(True)
                    last = SIZE - 1 - row[::-1].index(True)
                    print(f"row {y} {first} " + "".join("#" if value else "." for value in row[first : last + 1]))

        # Accumulated bounds of single runs under a rotated font and an identity
        # world (device = logical), without and with explicit advances.
        set_bounds = bind(gdi, "SetBoundsRect", wintypes.UINT, ptr, ptr, wintypes.UINT)
        get_bounds = bind(gdi, "GetBoundsRect", wintypes.UINT, ptr, ctypes.POINTER(wintypes.RECT), wintypes.UINT)
        extent = bind(
            gdi,
            "GetTextExtentExPointW",
            wintypes.BOOL,
            ptr,
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.c_int,
            ptr,
            ctypes.POINTER(ctypes.c_int),
            ptr,
        )
        create_emf = bind(gdi, "CreateEnhMetaFileW", ptr, ptr, ctypes.c_wchar_p, ptr, ctypes.c_wchar_p)
        close_emf = bind(gdi, "CloseEnhMetaFile", ptr, ptr)
        get_bits = bind(gdi, "GetEnhMetaFileBits", wintypes.UINT, ptr, wintypes.UINT, ptr)
        delete_emf = bind(gdi, "DeleteEnhMetaFile", wintypes.BOOL, ptr)

        def recorded_boxes(world, height, angle, calls):
            """Record the calls into an EMF on this DC; print each EXTTEXTOUTW record's bounds."""
            emf = check(create_emf(dc, None, None, None), "CreateEnhMetaFileW")
            set_mode(emf, 2)
            set_world(emf, ctypes.byref(XForm(*world)))
            font = make_font(height, angle, angle)
            previous = select(emf, font)
            for text, mode, advances in calls:
                set_bk(emf, mode)
                set_align(emf, 0)
                array = (ctypes.c_int * len(text))(*advances) if advances else None
                text_out(emf, 40, 40, 0, None, text, len(text), array)
            select(emf, previous)
            metafile = close_emf(emf)
            delete(font)
            size = get_bits(metafile, 0, None)
            data = ctypes.create_string_buffer(size)
            get_bits(metafile, size, data)
            delete_emf(metafile)
            raw, position, index = data.raw, 0, 0
            while position < len(raw):
                kind, length = struct.unpack_from("<II", raw, position)
                if kind == 84:
                    text, mode, advances = calls[index]
                    label = "dx=" + ",".join(map(str, advances)) if advances else "dx=none"
                    bounds = ",".join(map(str, struct.unpack_from("<4i", raw, position + 8)))
                    recorded = ",".join(
                        map(
                            str,
                            struct.unpack_from(
                                f"<{len(text)}i", raw, position + struct.unpack_from("<I", raw, position + 72)[0]
                            ),
                        )
                    )
                    print(f"emfbox {text!r} mode={mode} {label} -> {bounds} recorded_dx={recorded}")
                    index += 1
                position += length

        check(set_world(dc, ctypes.byref(XForm(1.0, 0.0, 0.0, 1.0, 0.0, 0.0))), "SetWorldTransform")
        strings = (
            "A",
            "B",
            " ",
            "AA",
            "AB",
            "BA",
            "BB",
            "A B",
            "B A",
            "AB A",
            "ABA",
            "BAB",
            "AAB",
            "ABB",
            "BBA",
            "AAAA",
        )
        for height, angle in ((-10, 240), (-10, 300), (-10, 1200), (-25, 240)):
            font = make_font(height, angle, angle)
            previous = select(dc, font)
            print(f"bounds height={height} escapement={angle}")
            calls = []
            for text in strings:
                partial = (ctypes.c_int * len(text))()
                extent(dc, text, len(text), 0, None, partial, ctypes.byref(wintypes.SIZE()))
                dx = [partial[0]] + [partial[i] - partial[i - 1] for i in range(1, len(text))]
                for mode in (1, 2):
                    set_bk(dc, mode)
                    for advances in (None, dx):
                        array = (ctypes.c_int * len(text))(*advances) if advances else None
                        set_bounds(dc, None, 1 | 4)  # DCB_RESET | DCB_ENABLE
                        set_align(dc, 0)
                        text_out(dc, 40, 40, 0, None, text, len(text), array)
                        rect = wintypes.RECT()
                        get_bounds(dc, ctypes.byref(rect), 0)
                        label = "dx=" + ",".join(map(str, advances)) if advances else "dx=none"
                        print(f"box {text!r} mode={mode} {label} -> {rect.left},{rect.top},{rect.right},{rect.bottom}")
                        calls.append((text, mode, advances))
            set_bk(dc, 1)
            set_bounds(dc, None, 0)
            select(dc, previous)
            delete(font)
            recorded_boxes((1.0, 0.0, 0.0, 1.0, 0.0, 0.0), height, angle, calls)
        # The same strings recorded under a rotating world transform, as the
        # recorder fixture draws them.
        font = make_font(-10, 0, 0)
        previous = select(dc, font)
        calls = []
        for text in strings:
            for mode in (1, 2):
                calls.append((text, mode, None))
        select(dc, previous)
        delete(font)
        print("bounds world=(0.9, 0.4, -0.4, 0.9, 10.0, 10.0) height=-10 escapement=0")
        recorded_boxes((0.9, 0.4, -0.4, 0.9, 10.0, 10.0), -10, 0, calls)

        # Upright glyphs along a differing escapement, drawn at sixteen sub-pixel
        # offsets on each axis: where pixels jump pins each glyph's 28.4 position.
        for name, height, matrix in (
            ("identity", -25, TRANSFORMS["identity"]),
            ("rotate", -8, TRANSFORMS["rotate"]),
            ("mirror-x", -25, TRANSFORMS["mirror-x"]),
        ):
            font = make_font(height, 300, 0)
            check(set_world(dc, ctypes.byref(XForm(*matrix, 0.0, 0.0))), "SetWorldTransform")
            previous = select(dc, font)
            for text in ("A", "B", "BA", "AB", "B A", "AB A"):
                for axis in (0, 1):
                    for step in range(16):
                        ctypes.memset(bits, 0xFF, SIZE * SIZE * 4)
                        set_align(dc, 24)
                        shift = (step / 16, 0.0) if axis == 0 else (0.0, step / 16)
                        set_world(dc, ctypes.byref(XForm(*matrix, ORIGIN[0] + shift[0], ORIGIN[1] + shift[1])))
                        text_out(dc, 0, 0, 0, None, text, len(text), None)
                        print_rows(
                            f"sweep upright-{name} height={height} transform={matrix} text {text!r} "
                            f"shift={shift[0]},{shift[1]}"
                        )
            set_world(dc, ctypes.byref(XForm(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)))
            select(dc, previous)
            delete(font)

        # Glyph pairs along a differing escapement, with and without explicit
        # advances (zero advances stack every glyph at its own back extent).
        pairs = (
            ("B ", None),
            (" A", None),
            (" ", None),
            ("AB ", None),
            ("  A", None),
            ("B  A", None),
            ("AAB A", None),
            ("A A", None),
            ("BB A", None),
            ("B AB", None),
            ("AB", (0, 0)),
            ("BA", (0, 0)),
            ("B A", (0, 0, 0)),
            ("AB A", (0, 0, 0, 0)),
            ("B A", (12, 12, 12)),
            ("AB A", (12, 12, 12, 12)),
        )
        for name, height, matrix in (("identity", -25, TRANSFORMS["identity"]), ("rotate", -8, TRANSFORMS["rotate"])):
            font = make_font(height, 300, 0)
            check(set_world(dc, ctypes.byref(XForm(*matrix, 0.0, 0.0))), "SetWorldTransform")
            previous = select(dc, font)
            for text, advances in pairs:
                if advances and height == -25 and any(advances):
                    continue
                array = (ctypes.c_int * len(text))(*advances) if advances else None
                label = f" dx={','.join(map(str, advances))}" if advances else ""
                for axis in (0, 1):
                    for step in range(16):
                        ctypes.memset(bits, 0xFF, SIZE * SIZE * 4)
                        set_align(dc, 24)
                        shift = (step / 16, 0.0) if axis == 0 else (0.0, step / 16)
                        set_world(dc, ctypes.byref(XForm(*matrix, ORIGIN[0] + shift[0], ORIGIN[1] + shift[1])))
                        text_out(dc, 0, 0, 0, None, text, len(text), array)
                        print_rows(
                            f"pair upright-{name} height={height} transform={matrix} text {text!r}{label} "
                            f"shift={shift[0]},{shift[1]}"
                        )
            set_world(dc, ctypes.byref(XForm(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)))
            select(dc, previous)
            delete(font)

        # Opaque cells under rotation and shear at sub-pixel origins, with the
        # text drawn in white so only the black background cell remains.
        set_text_color = bind(gdi, "SetTextColor", wintypes.DWORD, ptr, wintypes.DWORD)
        set_bk_color = bind(gdi, "SetBkColor", wintypes.DWORD, ptr, wintypes.DWORD)
        set_text_color(dc, 0xFFFFFF)
        set_bk_color(dc, 0x000000)
        set_bk(dc, 2)
        for matrix in ((0.9, 0.4, -0.4, 0.9), (1.0, 0.0, 0.45, 1.0), (0.8, 0.6, -0.6, 0.8), (0.6, -0.8, 0.8, 0.6)):
            for height in (-8, -13):
                font = make_font(height, 0, 0)
                previous = select(dc, font)
                for alignment in (0, 24):
                    for sx in (0, 4, 9, 13):
                        for sy in (0, 4, 9, 13):
                            ctypes.memset(bits, 0xFF, SIZE * SIZE * 4)
                            set_align(dc, alignment)
                            shift = (ORIGIN[0] + sx / 16, ORIGIN[1] + sy / 16)
                            set_world(dc, ctypes.byref(XForm(*matrix, *shift)))
                            text_out(dc, 0, 0, 0, None, "AB A", 4, None)
                            print_rows(
                                f"opaque height={height} transform={matrix} align={alignment} shift={sx / 16},{sy / 16}"
                            )
                set_world(dc, ctypes.byref(XForm(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)))
                select(dc, previous)
                delete(font)
        set_bk(dc, 1)
        set_text_color(dc, 0x000000)
        set_bk_color(dc, 0xFFFFFF)

        # Exact native outlines across sizes, transforms and simulated styles.
        for name in ("identity", "rotate", "shear", "mirror-x", "scale"):
            for fractional in (False, True):
                matrix = tuple(value * (128 / 51 if fractional else 1) for value in TRANSFORMS[name])
                check(set_world(dc, ctypes.byref(XForm(*matrix, 0.0, 0.0))), "SetWorldTransform")
                for height in range(-6, -31, -2):
                    for weight, italic in ((400, 0), (700, 1)):
                        font = make_font(height, 0, 0, weight, italic)
                        previous = select(dc, font)
                        for character in "AB":
                            metrics = GlyphMetrics()
                            native = outline(
                                dc, ord(character), 2, ctypes.byref(metrics), 0, None, ctypes.byref(identity)
                            )
                            print(
                                f"outline {name}{'-fractional' if fractional else ''} height={height} "
                                f"transform={matrix} weight={weight} italic={italic} glyph {character!r}"
                            )
                            if native not in (0, 0xFFFFFFFF):
                                data = ctypes.create_string_buffer(native)
                                outline(
                                    dc, ord(character), 2, ctypes.byref(metrics), native, data, ctypes.byref(identity)
                                )
                                print_native(data.raw)
                        select(dc, previous)
                        delete(font)
        check(set_world(dc, ctypes.byref(XForm(1.0, 0.0, 0.0, 1.0, 0.0, 0.0))), "SetWorldTransform")


if __name__ == "__main__":
    main()
