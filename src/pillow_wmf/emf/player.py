"""Translate EMF records to backend calls without rasterizing or decoding text.

Playback follows PlayEnhMetaFile: the backend is put in GM_ADVANCED, and the
metafile's mapping records become one world transform that also fits the
picture frame to the target rectangle (see ``transform``). Other records
translate only where their meaning matches an existing GDI call; the rest
are reported as omissions, so a caller can tell a complete rendering from a
partial one. Comments never draw; EMF+ drawing is reported only when a file
has no GDI fallback for it.
"""

import math
import struct
from collections.abc import Callable

from ..binary import FormatError, Limits
from ..bitmap16 import encode_bitmap16
from ..constants import (
    ALTERNATE,
    BLACKONWHITE,
    ETO_CLIPPED,
    ETO_GLYPH_INDEX,
    ETO_OPAQUE,
    GM_ADVANCED,
    OPAQUE,
    R2_COPYPEN,
)
from ..dib_rle import truncate_rle
from ..gdi import GDI, Call, Handle, InvalidOperation, UnsupportedOperation
from ..mapping import fixed as to_fixed
from ..numeric import float32
from ..objects import (
    BitmapData,
    EncodedText,
    FontRequest,
    GlyphIndices,
    PaletteEntries,
    PaletteUpdate,
    RegionGeometry,
    UnicodeText,
)
from ..palette import DEFAULT_COLORS
from ..playback import Omission as Omission
from ..playback import Omissions, PlaybackError, SaveLevels
from . import bitmaps, fixed, system, text, variable
from .constants import CREATION_TYPES, CommentIdentifier, RecordType
from .file import Metafile
from .objects import region_rectangles
from .records import RECORD_CLASSES, UnknownRecord, record_type
from .transform import PlaybackTransform, natural_size

STOCK_OBJECT = 0x80000000
BS_NULL = 1
BS_DIBPATTERN = 5
DIB_RGB_COLORS = 0
DIB_PAL_COLORS = 1
SRCCOPY = 0x00CC0020
GM_COMPATIBLE = 1
ETO_NO_RECT = text.ETO_NO_RECT
ETO_PDY = text.ETO_PDY
EMFPLUS_HEADER = 0x4001
EMFPLUS_DUAL = 0x0001
RGN_COPY = 5
CS_ENABLE = 1
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

# Records with no effect on a bitmap DC's output, established against native
# references: colour management, font linking, OpenGL and escapes.
NO_OP_RECORDS = (
    fixed.SetICMMode,
    fixed.SetColorSpace,
    fixed.DeleteColorSpace,
    fixed.ColorCorrectPalette,
    fixed.ForceUFIMapping,
    system.CreateColorSpace,
    system.CreateColorSpaceW,
    system.SetICMProfileA,
    system.SetICMProfileW,
    system.SetLinkedUFIs,
    system.GlsRecord,
    system.GlsBoundedRecord,
    system.PixelFormat,
    system.DrawEscape,
    system.ExtEscape,
    system.NamedEscape,
)


class Unsupported(Exception):
    """A record with no equivalent GDI call yet; becomes an omission."""


def _rect(record):
    return {"left": record.left, "top": record.top, "right": record.right, "bottom": record.bottom}


def _box_points(record):
    points = {"start_x": record.start_x, "start_y": record.start_y, "end_x": record.end_x, "end_y": record.end_y}
    return _rect(record) | points


def _font(record):
    font = record.font
    return {
        "font": FontRequest(
            font.height,
            font.width,
            font.escapement,
            font.orientation,
            font.weight,
            font.italic,
            font.underline,
            font.strikeout,
            font.charset,
            font.out_precision,
            font.clip_precision,
            font.quality,
            font.pitch_and_family,
            font.face,
        )
    }


def _dib(record) -> BitmapData:
    return BitmapData("dib", record.bitmap_info + record.bits)


def _source_blit(record):
    if not record.bitmap_size:
        # A recorded PatBlt is a BitBlt without a source bitmap.
        # As a BitBlt, a source-less StretchBlt fills with the brush.
        return "pat_blt", {
            "x": record.x,
            "y": record.y,
            "width": record.width,
            "height": record.height,
            "rop": record.rop,
        }
    stretch = isinstance(record, bitmaps.StretchBlt)
    width, height = (record.src_width, record.src_height) if stretch else (record.width, record.height)
    source = _source_rectangle(record, record.src_x, record.src_y, width, height)
    if source is None:
        return None, None
    arguments = {
        "x": record.x,
        "y": record.y,
        "width": record.width,
        "height": record.height,
        "src_x": source[0],
        "src_y": source[1],
        "rop": record.rop,
        "source": _source_dib(record),
    }
    if stretch or source[2:] != (record.width, record.height):
        return "dib_stretch_blt", arguments | {"src_width": source[2], "src_height": source[3]}
    return "dib_bit_blt", arguments


def _source_rectangle(record, x, y, width, height):
    """A logical source rectangle mapped through the recorded source transform.

    Playback selects the bitmap into a DC with that world transform. Scales
    and mirrors give a bitmap-pixel rectangle with each edge rounded half up,
    stretching the transfer; GDI refuses a rotated or sheared source DC, so
    the record draws nothing and this returns None.
    """
    m11, m12, m21, m22, dx, dy = (getattr(record, name) for name in bitmaps.SOURCE_XFORM)
    if (m11, m12, m21, m22, dx, dy) == IDENTITY:
        return x, y, width, height
    if m12 or m21:
        return None
    left, top = _round_half_up(m11 * x + dx), _round_half_up(m22 * y + dy)
    right, bottom = _round_half_up(m11 * (x + width) + dx), _round_half_up(m22 * (y + height) + dy)
    return left, top, right - left, bottom - top


def _round_half_up(value):
    return math.floor(value + 0.5)


def _source_dib(record) -> BitmapData:
    """The record's DIB with any palette-index colour table resolved.

    Playback realizes DIB_PAL_COLORS sources in a memory DC holding the
    default palette, whatever palette the metafile selected; indexes wrap.
    """
    if record.usage == DIB_RGB_COLORS:
        return _dib(record)
    if record.usage != DIB_PAL_COLORS:
        raise Fails  # Other colour usages cannot realize a source bitmap.
    info = record.bitmap_info
    header_size = struct.unpack_from("<I", info)[0] if len(info) >= 4 else 0
    core = header_size == 12
    if len(info) < header_size or not core and (header_size < 40 or len(info) < 36):
        raise Fails
    depth = struct.unpack_from("<H", info, 10 if core else 14)[0]
    used = 0 if core else struct.unpack_from("<I", info, 32)[0]
    if depth > 8:
        return _dib(record)
    count = min(used or 1 << depth, 1 << depth)
    table = info[header_size : header_size + 2 * count]
    if len(table) < 2 * count:
        raise Fails
    entry = (lambda c: bytes(reversed(c))) if core else (lambda c: bytes((*reversed(c), 0)))
    colors = b"".join(
        entry(DEFAULT_COLORS[index % len(DEFAULT_COLORS)]) for index in struct.unpack(f"<{count}H", table)
    )
    return BitmapData("dib", info[:header_size] + colors + record.bits)


def _transparent_blt(record):
    source = _source_rectangle(record, record.src_x, record.src_y, record.src_width, record.src_height)
    if source is None:
        return None, None
    return "transparent_blt", {
        "x": record.x,
        "y": record.y,
        "width": record.width,
        "height": record.height,
        **dict(zip(("src_x", "src_y", "src_width", "src_height"), source, strict=True)),
        "transparent": record.transparent,
        "source": _source_dib(record),
    }


def _gradient_fill(record):
    if record.padding is not None and len(record.padding) != record.reserved:
        raise Stop("Rectangle gradients without reserved mesh space fail native record validation")
    return "gradient_fill", {"mode": record.mode, "vertices": record.vertices, "meshes": record.shapes}


def _alpha_blend(record):
    source = _source_rectangle(record, record.src_x, record.src_y, record.src_width, record.src_height)
    if source is None:
        return None, None
    return "alpha_blend", {
        "x": record.x,
        "y": record.y,
        "width": record.width,
        "height": record.height,
        **dict(zip(("src_x", "src_y", "src_width", "src_height"), source, strict=True)),
        "blend": record.blend,
        "source": _source_dib(record),
    }


def _mask_blt(record):
    source = (record.src_x, record.src_y, record.width, record.height)
    if record.bitmap_size:
        source = _source_rectangle(record, *source)
        if source is None:
            return None, None
    # The mask covers the mapped source rectangle and stretches with it.
    sized = {} if source[2:] == (record.width, record.height) else {"src_size": source[2:]}
    mask = BitmapData("dib", record.mask_info + record.mask_bits) if record.mask_size else None
    return "mask_blt", {
        "x": record.x,
        "y": record.y,
        "width": record.width,
        "height": record.height,
        "src_x": source[0],
        "src_y": source[1],
        "rop": record.rop,
        "source": _source_dib(record) if record.bitmap_size else None,
        "mask": mask,
        "mask_x": record.mask_x,
        "mask_y": record.mask_y,
        "mask_usage": record.mask_usage,
        **sized,
    }


def _color_adjustment(record):
    if record.size != 24:
        raise Fails
    return "set_color_adjustment", {
        "flags": record.values,
        "illuminant": record.illuminant_index,
        "red_gamma": record.red_gamma,
        "green_gamma": record.green_gamma,
        "blue_gamma": record.blue_gamma,
        "black": record.reference_black,
        "white": record.reference_white,
        "contrast": record.contrast,
        "brightness": record.brightness,
        "colorfulness": record.colorfulness,
        "tint": record.red_green_tint,
    }


def _plg_blt(record):
    if not record.bitmap_size:
        raise Fails
    rectangle = (record.src_x, record.src_y, record.src_width, record.src_height)
    source = _source_rectangle(record, *rectangle)
    if source is None:
        return None, None
    mask = BitmapData("dib", record.mask_info + record.mask_bits) if record.mask_size else None
    return "plg_blt", {
        "points": ((record.x0, record.y0), (record.x1, record.y1), (record.x2, record.y2)),
        **dict(zip(("src_x", "src_y", "src_width", "src_height"), source, strict=True)),
        "source": _source_dib(record),
        "mask": mask,
        "mask_x": record.mask_x,
        "mask_y": record.mask_y,
        "mask_usage": record.mask_usage,
    }


def _stretch_dib(record):
    if not record.bitmap_size:
        raise Fails
    return "stretch_dib", {
        "x": record.x,
        "y": record.y,
        "width": record.width,
        "height": record.height,
        "src_x": record.src_x,
        "src_y": record.src_y,
        "src_width": record.src_width,
        "src_height": record.src_height,
        "rop": record.rop,
        "color_usage": record.usage,
        "source": _dib(record),
    }


def _dib_height(info: bytes) -> int | None:
    """The DIB height from a BITMAPCOREHEADER or BITMAPINFOHEADER, if present."""
    if len(info) >= 12 and struct.unpack_from("<I", info)[0] == 12:
        return struct.unpack_from("<h", info, 6)[0]
    return struct.unpack_from("<i", info, 8)[0] if len(info) >= 12 else None


def _set_dib_to_device(record):
    """Native playback scales the transfer with the playback transform.

    A record carrying every scan line plays exactly as a SRCCOPY stretch of
    the whole source rectangle. A partial band carries only its own scan
    lines; see ``_scan_band``.
    """
    if not record.bitmap_size:
        raise Fails
    height = _dib_height(record.bitmap_info)
    if record.start_scan == 0 and height is not None and record.scan_count >= abs(height):
        return "stretch_dib", {
            "x": record.x,
            "y": record.y,
            "width": record.src_width,
            "height": record.src_height,
            "src_x": record.src_x,
            "src_y": record.src_y,
            "src_width": record.src_width,
            "src_height": record.src_height,
            "rop": SRCCOPY,
            "color_usage": record.usage,
            "source": _dib(record),
        }
    return _scan_band(record)


def _scan_band(record):
    """A partial scan band as a stretch of the whole source rectangle.

    The band's lines form a bitmap of their own whose top row is a bottom-up
    band's last line or a top-down band's first. The source rectangle's top
    is row ``start + count - src_y - src_height`` of that bitmap, with a
    bottom-up count limited to the lines the DIB has. The
    rectangle stretches as a whole; its rows outside the band draw nothing.
    """
    info = record.bitmap_info
    if len(info) < 40 or struct.unpack_from("<I", info)[0] < 40:
        raise Fails
    width, height, _, depth, compression = struct.unpack_from("<iiHHI", info, 4)
    rle = compression in (1, 2)
    if not (compression in (0, 3) or (rle and height > 0)) or width <= 0 or height == 0:
        raise Fails  # GDI cannot realize a top-down compressed or empty DIB.
    top_down, lines = height < 0, abs(height)
    if record.start_scan >= lines or not record.scan_count:
        return None, None
    count = record.scan_count if top_down else min(record.scan_count, lines - record.start_scan)
    rows = min(count, lines)
    bits = record.bits
    if rle:
        # A compressed band is the stream from its start, decoded into the
        # band's own lines.
        band = truncate_rle(bits, depth, rows)
    else:
        stride = (width * depth + 31) // 32 * 4
        if len(bits) < stride * rows:
            raise Fails
        scans = [bits[row * stride : (row + 1) * stride] for row in range(rows)]
        # Stored bottom-up, where StretchDIBits measures rows from the last line.
        band = b"".join(reversed(scans) if top_down else scans)
    offset = record.start_scan + count - record.src_y - record.src_height
    if not (-record.src_height < offset < rows):
        return None, None
    # A compressed band keeps its stream's size; an uncompressed one is sized by its lines.
    size = len(band) if rle else 0
    header = info[:4] + struct.pack("<ii", width, rows) + info[12:20] + struct.pack("<I", size) + info[24:]
    # Rows of the rectangle beyond the band have no source scan and are skipped.
    return "stretch_dib", {
        "x": record.x,
        "y": record.y,
        "width": record.src_width,
        "height": record.src_height,
        "src_x": record.src_x,
        "src_y": rows - offset - record.src_height,
        "src_width": record.src_width,
        "src_height": record.src_height,
        "rop": SRCCOPY,
        "color_usage": record.usage,
        "source": BitmapData("dib", header + band),
    }


def _mono_brush(record):
    """CreateMonoBrush is CreatePatternBrush on a monochrome bitmap.

    Its colours come from the text and background colours when drawn, so the
    DIB's own colour table is ignored. The samples become the same native
    pattern storage a WMF pattern brush uses.
    """
    info = record.bitmap_info
    if len(info) < 16 or struct.unpack_from("<I", info)[0] < 40:
        raise Fails
    width, height, _, depth = struct.unpack_from("<iiHH", info, 4)
    if depth != 1 or width <= 0 or height == 0:
        raise Fails
    stride = (width + 31) // 32 * 4
    bits = record.bits
    rows = abs(height)
    if len(bits) < stride * rows:
        raise Fails
    order = range(rows) if height < 0 else range(rows - 1, -1, -1)
    samples = [bits[y * stride + x // 8] >> (7 - x % 8) & 1 for y in order for x in range(width)]
    return "create_pattern_brush", {"bitmap": encode_bitmap16(width, rows, samples, pattern=True, native_pattern=True)}


# Native recording writes this DWORD in place of a DIB pattern pen's
# BitmapInfo size; the header is otherwise an ordinary BITMAPINFOHEADER.
PEN_DIB_MARKER = 0x20000000


def _pen_dib(record) -> BitmapData:
    info = record.bitmap_info
    if len(info) >= 4 and struct.unpack_from("<I", info)[0] == PEN_DIB_MARKER:
        info = struct.pack("<I", 40) + info[4:]
    return BitmapData("dib", info + record.bits)


def _ext_create_pen(record):
    """A pen with its LOGBRUSH; DIB pattern pens carry the record's bitmap."""
    pattern = record.brush_style in (BS_DIBPATTERN, BS_DIBPATTERN + 1)
    return "ext_create_pen", {
        "style": record.style,
        "width": record.width,
        "color": record.color,
        "brush_style": record.brush_style,
        "hatch": record.hatch,
        "entries": tuple(record.style_entries),
        "bitmap": _pen_dib(record) if pattern and record.bitmap_size else None,
    }


# Text records carrying a graphics mode and font transform scales.
TEXT_RECORDS = (text.ExtTextOutA, text.ExtTextOutW, text.PolyTextOutA, text.PolyTextOutW, text.SmallTextOut)


class Stop(Exception):
    """Native playback rejects the record and plays nothing after it."""


class Fails(Exception):
    """Native playback fails the record without drawing; an object it creates is not made."""


def _text_arguments(x, y, value, options, rectangle, advances):
    # Playback passes ETO_NO_RECT through; GDI ignores it.
    options &= ~ETO_NO_RECT
    return {
        "x": x,
        "y": y,
        "text": value,
        "options": options,
        "rectangle": rectangle if options & (ETO_OPAQUE | ETO_CLIPPED) else None,
        "advances": advances,
    }


def _ext_text_out(record):
    if not record.playable():
        raise Stop(f"{record_name(record_type(record))} fails native record validation")
    options = record.options
    advances = record.advances
    if isinstance(record, text.ExtTextOutW):
        data = record.text
        if options & ETO_GLYPH_INDEX:
            value = GlyphIndices(struct.unpack(f"<{len(data) // 2}H", data))
        else:
            value = UnicodeText.from_utf16(data)
    elif options & ETO_GLYPH_INDEX:
        # ExtTextOutA reads WORD glyph indices, as many as the record holds.
        size = len(record.to_bytes())
        count = min(record.chars, max(0, size - record.string_offset) // 2)
        data = record.record_bytes(record.string_offset, 2 * count)
        value = GlyphIndices(struct.unpack(f"<{count}H", data))
        advances = advances[: count * (2 if options & ETO_PDY else 1)]
    else:
        value = EncodedText(record.text)
    return "ext_text_out", _text_arguments(record.x, record.y, value, options, record.rectangle, advances)


# Options GDI neither interprets nor ignores fail text output; ExtTextOut
# records pass ETO_NO_RECT through without failing, but PolyTextOut entries do not.
POLY_TEXT_FAILING_OPTIONS = ~(ETO_OPAQUE | ETO_CLIPPED | 0x3C90) & 0xFFFFFFFF


def _poly_text_out(record):
    """PolyTextOut draws each entry as ExtTextOut, always with its advances."""
    if not record.playable():
        raise Stop(f"{record_name(record_type(record))} fails native record validation")
    calls = []
    for index, entry in enumerate(record.texts):
        if entry.options & POLY_TEXT_FAILING_OPTIONS:
            break  # GDI rejects the entry and draws none after it.
        data = record.text(index) if entry.chars else b""
        if isinstance(record, text.PolyTextOutW):
            if entry.options & ETO_GLYPH_INDEX:
                value = GlyphIndices(struct.unpack(f"<{len(data) // 2}H", data))
            else:
                value = UnicodeText.from_utf16(data)
        elif entry.options & ETO_GLYPH_INDEX:
            value = GlyphIndices(tuple(data))
        else:
            value = EncodedText(data)
        advances = record.advances(index) if entry.chars else ()
        calls.append(_text_arguments(entry.x, entry.y, value, entry.options, entry.rectangle, advances))
    return "poly_text_out", calls


def _small_text_out(record):
    """8-bit SmallTextOut characters widen to UTF-16 code units, not through a code page."""
    expected = -len(record.text) % 4
    if record.trailing or (record.padding is not None and len(record.padding) != expected):
        raise Stop("SMALLTEXTOUT fails native record validation")
    if record.options & text.SMALLTEXT_TYPE_ANSI:
        value = UnicodeText("".join(chr(byte) for byte in record.text))
    else:
        value = UnicodeText.from_utf16(record.text)
    options = record.options & ~(ETO_NO_RECT | text.SMALLTEXT_TYPE_ANSI)
    return "ext_text_out", _text_arguments(record.x, record.y, value, options, record.bounds, ())


def _direct(name, *fields, **renamed):
    def translate(record):
        return name, {field: getattr(record, field) for field in fields} | {
            key: getattr(record, value) for key, value in renamed.items()
        }

    return translate


TRANSLATIONS: dict[type, Callable] = {
    fixed.SetPixelV: _direct("set_pixel", "x", "y", "color"),
    fixed.SetMapperFlags: _direct("set_mapper_flags", "flags"),
    fixed.SetBkMode: _direct("set_background_mode", "mode"),
    fixed.SetPolyFillMode: _direct("set_polygon_fill_mode", "mode"),
    fixed.SetROP2: _direct("set_rop2", "mode"),
    fixed.SetStretchBltMode: _direct("set_stretch_mode", "mode"),
    fixed.SetTextAlign: _direct("set_text_alignment", "alignment"),
    fixed.SetTextColor: _direct("set_text_color", "color"),
    fixed.SetBkColor: _direct("set_background_color", "color"),
    fixed.OffsetClipRgn: _direct("offset_clip_region", "x", "y"),
    fixed.MoveToEx: _direct("move_to", "x", "y"),
    fixed.LineTo: _direct("line_to", "x", "y"),
    fixed.ExcludeClipRect: lambda r: ("exclude_clip_rect", _rect(r)),
    fixed.IntersectClipRect: lambda r: ("intersect_clip_rect", _rect(r)),
    fixed.CreatePen: _direct("create_pen", "style", "width", "color"),
    fixed.CreateBrushIndirect: _direct("create_brush", "style", "color", "hatch"),
    fixed.Ellipse: lambda r: ("ellipse", _rect(r)),
    fixed.Rectangle: lambda r: ("rectangle", _rect(r)),
    fixed.RoundRect: lambda r: (
        "round_rect",
        _rect(r) | {"ellipse_width": r.corner_width, "ellipse_height": r.corner_height},
    ),
    fixed.Arc: lambda r: ("arc", _box_points(r)),
    fixed.Chord: lambda r: ("chord", _box_points(r)),
    fixed.Pie: lambda r: ("pie", _box_points(r)),
    fixed.RealizePalette: _direct("realize_palette"),
    fixed.ExtFloodFill: _direct("ext_flood_fill", "x", "y", "color", "mode"),
    fixed.BeginPath: _direct("begin_path"),
    fixed.EndPath: _direct("end_path"),
    fixed.AbortPath: _direct("abort_path"),
    fixed.CloseFigure: _direct("close_figure"),
    fixed.FillPath: _direct("fill_path"),
    fixed.StrokePath: _direct("stroke_path"),
    fixed.StrokeAndFillPath: _direct("stroke_and_fill_path"),
    fixed.FlattenPath: _direct("flatten_path"),
    fixed.WidenPath: _direct("widen_path"),
    fixed.SelectClipPath: _direct("select_clip_path", "mode"),
    # Native SetArcDirection fails for other values.
    fixed.SetArcDirection: lambda r: (
        ("set_arc_direction", {"direction": r.direction}) if r.direction in (1, 2) else (None, None)
    ),
    fixed.ArcTo: lambda r: ("arc_to", _box_points(r)),
    fixed.AngleArc: lambda r: (
        "angle_arc",
        {"x": r.x, "y": r.y, "radius": r.radius, "start": r.start_angle, "sweep": r.sweep_angle},
    ),
    fixed.SetMetaRgn: _direct("set_meta_region"),
    fixed.SetBrushOrgEx: _direct("set_brush_origin", "x", "y"),
    # Native recording truncates the limit to an integer; playback reads it back.
    fixed.SetMiterLimit: lambda r: ("set_miter_limit", {"limit": float(r.limit)}),
    fixed.SetTextJustification: _direct("set_text_justification", "break_count", "break_extra"),
    variable.Polygon: _direct("polygon", "points"),
    variable.Polygon16: _direct("polygon", "points"),
    variable.Polyline: _direct("polyline", "points"),
    variable.Polyline16: _direct("polyline", "points"),
    variable.PolyPolygon: _direct("poly_polygon", polygons="figures"),
    variable.PolyBezier: _direct("poly_bezier", "points"),
    variable.PolyBezier16: _direct("poly_bezier", "points"),
    variable.PolyBezierTo: _direct("poly_bezier_to", "points"),
    variable.PolyBezierTo16: _direct("poly_bezier_to", "points"),
    variable.PolylineTo: _direct("polyline_to", "points"),
    variable.PolylineTo16: _direct("polyline_to", "points"),
    variable.PolyPolyline: _direct("poly_polyline", polylines="figures"),
    variable.PolyPolyline16: _direct("poly_polyline", polylines="figures"),
    variable.PolyDraw: _direct("poly_draw", "points", "types"),
    variable.PolyDraw16: _direct("poly_draw", "points", "types"),
    variable.PolyPolygon16: _direct("poly_polygon", polygons="figures"),
    variable.CreatePalette: lambda r: ("create_palette", {"palette": PaletteEntries(r.entries) if r.entries else None}),
    variable.ExtCreateFontIndirectW: lambda r: ("create_font", _font(r)),
    bitmaps.BitBlt: _source_blit,
    bitmaps.StretchBlt: _source_blit,
    bitmaps.StretchDIBits: _stretch_dib,
    bitmaps.SetDIBitsToDevice: _set_dib_to_device,
    bitmaps.TransparentBlt: _transparent_blt,
    bitmaps.MaskBlt: _mask_blt,
    bitmaps.PlgBlt: _plg_blt,
    fixed.SetColorAdjustment: _color_adjustment,
    bitmaps.AlphaBlend: _alpha_blend,
    variable.GradientFill: _gradient_fill,
    bitmaps.CreateMonoBrush: _mono_brush,
    bitmaps.CreateDIBPatternBrushPt: lambda r: (
        "create_dib_pattern_brush",
        {"style": BS_DIBPATTERN, "color_usage": r.usage, "bitmap": _dib(r)},
    ),
    bitmaps.ExtCreatePen: _ext_create_pen,
    text.ExtTextOutA: _ext_text_out,
    text.ExtTextOutW: _ext_text_out,
    text.PolyTextOutA: _poly_text_out,
    text.PolyTextOutW: _poly_text_out,
    text.SmallTextOut: _small_text_out,
}


# Records native playback skips when their bounds miss the clip box it reads
# before the first record.
CULLED_RECORDS = (
    bitmaps.AlphaBlend,
    bitmaps.BitBlt,
    bitmaps.MaskBlt,
    bitmaps.PlgBlt,
    bitmaps.SetDIBitsToDevice,
    bitmaps.StretchBlt,
    bitmaps.StretchDIBits,
    bitmaps.TransparentBlt,
    variable.FillRgn,
    variable.FrameRgn,
    variable.InvertRgn,
    variable.PaintRgn,
)
# The reference display's resolution in pixels per millimetre.
REFERENCE_DENSITY = (float32(1024 / 271), float32(768 / 203))
AD_COUNTERCLOCKWISE = 1
# Attributes native playback resets before the first record, after selecting
# the white brush, black pen and default palette. The device default font
# is also selected; that waits for the text work.
RESET_ATTRIBUTES = (
    ("set_background_color", {"color": 0xFFFFFF}),
    ("set_text_color", {"color": 0}),
    ("set_text_character_extra", {"extra": 0}),
    ("set_background_mode", {"mode": OPAQUE}),
    ("set_polygon_fill_mode", {"mode": ALTERNATE}),
    ("set_rop2", {"mode": R2_COPYPEN}),
    ("set_stretch_mode", {"mode": BLACKONWHITE}),
    ("set_text_alignment", {"alignment": 0}),
    ("set_mapper_flags", {"flags": 0}),
    ("set_brush_origin", {"x": 0, "y": 0}),
    ("set_miter_limit", {"limit": 10.0}),
    ("set_text_justification", {"break_count": 0, "break_extra": 0}),
    ("set_arc_direction", {"direction": AD_COUNTERCLOCKWISE}),
    ("move_to", {"x": 0, "y": 0}),
)


def record_bounds(record):
    if isinstance(record, variable.RegionRecord):
        return record.bounds
    return record.bounds_left, record.bounds_top, record.bounds_right, record.bounds_bottom


def culling_box(box, header):
    """The clip box widened by the margin native playback allows for rounding.

    Each axis widens by one logical unit, or by one more than the whole
    number of reference-display pixels per metafile device pixel when the
    metafile's device is denser.
    """
    left, top, right, bottom = box
    margins = []
    for axis in range(2):
        density = float32(float32(header.device[axis]) / float32(header.millimetres[axis]))
        reference = REFERENCE_DENSITY[axis]
        margins.append(int(float32(density / reference)) + 1 if reference < density else 1)
    return left - margins[0], top - margins[1], right + margins[0], bottom + margins[1]


def culled(record, box) -> bool:
    """Whether a record's non-empty bounds lie wholly outside the culling box."""
    left, top, right, bottom = record_bounds(record)
    if right < left or bottom < top:
        return False
    return right < box[0] or box[2] < left or bottom < box[1] or box[3] < top


def fitted_rectangles(rectangles, fit):
    """Region rectangles are reference-device pixels; fit them like points."""
    scale_x, _, _, scale_y, origin_x, origin_y = fit

    def edge(value, scale, origin):
        return (to_fixed(float32(value * scale)) + to_fixed(origin) + 8) // 16

    result = []
    for left, top, right, bottom in rectangles:
        x0, x1 = sorted((edge(left, scale_x, origin_x), edge(right, scale_x, origin_x)))
        y0, y1 = sorted((edge(top, scale_y, origin_y), edge(bottom, scale_y, origin_y)))
        result.append((x0, y0, x1, y1))
    return tuple(result)


def record_name(kind: int) -> str:
    try:
        return RecordType(kind).name
    except ValueError:
        return f"Record type 0x{kind:X}"


def emf_plus_dual(record: variable.Comment) -> bool | None:
    """The dual flag of an EMF+ header comment, or None for other comments."""
    data = record.data
    if not record.emf_plus or len(data) < 8:
        return None
    kind, flags = struct.unpack_from("<HH", data, 4)
    return bool(flags & EMFPLUS_DUAL) if kind == EMFPLUS_HEADER else None


GDICOMMENT_MULTIFORMATS = 0x40000004
ENHMETA_SIGNATURE = 0x464D4520
# Embedded metafiles can embed others; native recursion has no such cap.
MAX_EMBEDDED_DEPTH = 8


def embedded_metafile(record: variable.Comment):
    """The output rectangle and EMF bytes of a GDIC multi-format comment, or None.

    The first format with the enhanced-metafile signature is used; offsets
    count from the start of the comment data.
    """
    data = record.data
    if len(data) < 28:
        return None
    identifier, kind, *output, count = struct.unpack_from("<II4iI", data)
    if identifier != CommentIdentifier.PUBLIC or kind != GDICOMMENT_MULTIFORMATS:
        return None
    for index in range(min(count, (len(data) - 28) // 16)):
        signature, _version, size, offset = struct.unpack_from("<4I", data, 28 + 16 * index)
        if signature == ENHMETA_SIGNATURE and offset + size <= len(data):
            return tuple(output), data[offset : offset + size]
    return None


def play(
    metafile: Metafile,
    backend: GDI,
    *,
    strict: bool = False,
    limits: Limits | None = None,
    rect: tuple[int, int, int, int] | None = None,
    comment: Callable[[int, variable.Comment], None] | None = None,
    parent: tuple[float, float, float, float, float, float] | None = None,
    depth: int = 0,
) -> tuple[Omission, ...]:
    """Play into a supplied context; return diagnostics for unsupported work.

    The picture frame is fitted to ``rect`` in the backend's device pixels;
    the default is the frame's own size in header device pixels at the
    origin. Playback starts as natively: the clip becomes the meta region,
    stock objects and attributes are reset, and when the backend answers
    ``get_clip_box``, transfers and region painting whose record bounds miss
    the widened clip box are skipped. ``comment``
    receives every EMR_COMMENT record with its index, for a front-end that
    interprets EMF+ or other comment payloads.

    A GDIC multi-format comment carrying an enhanced metafile plays it as
    PlayEnhMetaFile would: its frame is fitted to the comment's output
    rectangle in this metafile's logical units, under the current world
    transform (``parent``), inside a saved DC.
    """
    limits = limits if limits is not None else Limits()
    if metafile.header.handle_count > limits.max_objects or len(metafile.records) > limits.max_records:
        raise PlaybackError("Playback resource limit exceeded")
    unavailable = object()
    # Slot 0 refers to the metafile itself and is never an object.
    slots: list[object] = [None] * metafile.header.handle_count
    stock: dict[int, Handle] = {}
    omissions = Omissions(strict=strict)
    levels = SaveLevels()
    transform = PlaybackTransform(
        metafile.header, rect if rect is not None else (0, 0, *natural_size(metafile.header)), parent=parent
    )

    def invoke(index, kind, name, arguments):
        try:
            return True, backend.invoke(Call.make(name, **arguments))
        except (UnsupportedOperation, InvalidOperation) as error:
            if strict and isinstance(error, InvalidOperation):
                raise PlaybackError(f"Record {index}: {error}") from error
            omissions.omit(index, kind, str(error))
            return False, None

    def lookup(index, kind, object_index):
        """The backend object for a file reference; None when the lookup fails natively."""
        if object_index & STOCK_OBJECT:
            # EMF has no record to change the DC brush or pen colour, so those
            # stock objects keep their default colours.
            if object_index not in stock:
                ok, handle = invoke(index, kind, "get_stock_object", {"index": object_index & ~STOCK_OBJECT})
                if not ok:
                    return unavailable
                stock[object_index] = handle
            return stock[object_index]
        if not 0 < object_index < len(slots) or slots[object_index] is None:
            return None
        return slots[object_index]

    def set_transform(index, kind):
        matrix = transform.device
        names = ("m11", "m12", "m21", "m22", "dx", "dy")
        invoke(index, kind, "set_world_transform", dict(zip(names, matrix, strict=True)))

    selected_palette = [None]  # None is the stock default palette the DC starts with.

    def edit_palette(index, kind, record):
        """EMF names the palette to edit; the shared calls edit the selected one."""
        target = lookup(index, kind, record.object_index)
        if target is None or target is unavailable or target.kind != "palette":
            return  # Native palette functions fail on other objects.
        if isinstance(record, variable.SetPaletteEntries):
            name, arguments = "set_palette_entries", {"palette": PaletteUpdate(record.start, record.entries)}
        else:
            name, arguments = "resize_palette", {"count": record.count}
        previous = selected_palette[0]
        if target is not previous:
            invoke(index, kind, "select_palette", {"handle": target})
        invoke(index, kind, name, arguments)
        if target is not previous:
            if previous is None:
                previous = lookup(index, kind, STOCK_OBJECT | 15)
            invoke(index, kind, "select_palette", {"handle": previous})

    def paint_region(index, kind, record):
        """Region painting records carry their region; the brush is a file slot."""
        try:
            geometry = RegionGeometry(region_rectangles(record.region))
        except FormatError as error:
            omissions.omit(index, kind, str(error))
            return
        arguments = {}
        if isinstance(record, (variable.FillRgn, variable.FrameRgn)):
            brush = lookup(index, kind, record.brush)
            if brush is None or brush is unavailable:
                if brush is unavailable:
                    omissions.omit(index, kind, "Object creation was unsupported")
                return  # A missing brush fails natively.
            arguments["brush"] = brush
        if isinstance(record, variable.FrameRgn):
            arguments |= {"width": record.width, "height": record.height}
        name = {
            variable.FillRgn: "fill_region",
            variable.FrameRgn: "frame_region",
            variable.InvertRgn: "invert_region",
            variable.PaintRgn: "paint_region",
        }[type(record)]
        ok, region = invoke(index, kind, "create_region", {"region": geometry})
        if ok:
            invoke(index, kind, name, {"region": region, **arguments})
            invoke(index, kind, "delete_object", {"handle": region})

    def play_embedded(index, kind, output, data):
        if depth >= MAX_EMBEDDED_DEPTH:
            omissions.omit(index, kind, "Embedded metafiles nest too deeply")
            return
        try:
            nested = Metafile.from_bytes(data, limits=limits)
        except (FormatError, PlaybackError) as error:
            omissions.omit(index, kind, f"Embedded metafile: {error}")
            return
        ok, saved = invoke(index, kind, "save_dc", {})
        if not ok:
            return
        try:
            inner = play(
                nested,
                backend,
                strict=strict,
                limits=limits,
                rect=output,
                comment=None,
                parent=transform.device,
                depth=depth + 1,
            )
        except PlaybackError as error:
            inner = (Omission(index, kind, f"Embedded metafile: {error}"),)
        for omission in inner:
            omissions.omit(index, kind, f"Embedded metafile: {omission.reason}")
        invoke(index, kind, "restore_dc", {"saved_dc": -1})
        set_transform(index, kind)

    # Attributed to the header record, which native playback starts from.
    invoke(-1, RecordType.HEADER, "set_graphics_mode", {"mode": GM_ADVANCED})
    set_transform(-1, RecordType.HEADER)
    invoke(-1, RecordType.HEADER, "set_meta_region", {})
    for stock_index, name in ((0, "select_object"), (7, "select_object"), (15, "select_palette")):
        handle = lookup(-1, RecordType.HEADER, STOCK_OBJECT | stock_index)
        if handle is not None and handle is not unavailable:
            invoke(-1, RecordType.HEADER, name, {"handle": handle})
    for name, arguments in RESET_ATTRIBUTES:
        invoke(-1, RecordType.HEADER, name, arguments)
    try:
        box = backend.get_clip_box()
    except UnsupportedOperation:
        box = None
        cull = None
    else:
        if box is None:
            return omissions.result()  # Nothing is visible; native playback plays no records.
        cull = culling_box(box, metafile.header)
    for index, record in enumerate(metafile.records):
        kind = record_type(record)
        if kind == RecordType.EOF:
            break
        if isinstance(record, UnknownRecord):
            # Native playback ignores record types it does not know; a known
            # type whose layout the typed fields cannot express is malformed.
            if kind in RECORD_CLASSES:
                omissions.omit(index, kind, f"Malformed {record_name(kind)} record")
            continue
        if isinstance(record, NO_OP_RECORDS):
            continue
        if isinstance(record, system.ColorMatchToTargetW):
            if record.action == CS_ENABLE and not record.name:
                break  # Native playback stops here; earlier drawing remains.
            continue  # Colour matching has no effect on a bitmap DC.
        if isinstance(record, variable.Comment):
            if comment is not None:
                comment(index, record)
            if emf_plus_dual(record) is False:
                omissions.omit(index, kind, "EMF+ drawing without a GDI fallback is not rendered")
            embedded = embedded_metafile(record)
            if embedded is not None:
                play_embedded(index, kind, *embedded)
            continue
        if isinstance(record, fixed.SaveDC):
            if levels.depth >= limits.max_saved_states:
                raise PlaybackError(f"Record {index}: saved-state limit exceeded")
            levels.save()
            transform.save()
            ok, result = invoke(index, kind, "save_dc", {})
            if ok and not levels.saved(result):
                raise PlaybackError(f"Record {index}: save did not return a valid saved DC identifier")
            continue
        if isinstance(record, fixed.RestoreDC):
            level = record.saved_dc
            if level >= 0:
                continue  # Native playback ignores absolute levels.
            native_saved = levels.restore(level)
            if native_saved is not SaveLevels.MISSING:
                transform.restore(level)
            if native_saved is SaveLevels.MISSING:
                continue  # A failed native restore leaves the DC unchanged.
            if native_saved is None:
                omissions.omit(index, kind, "Saved DC was unsupported")
                continue
            ok, _ = invoke(index, kind, "restore_dc", {"saved_dc": levels.backend_level(native_saved, level)})
            if ok:
                levels.restored(native_saved)
            continue
        if isinstance(record, (fixed.SelectObject, fixed.SelectPalette)):
            handle = lookup(index, kind, record.object_index)
            if handle is None or handle is unavailable:
                if handle is unavailable and not record.object_index & STOCK_OBJECT:
                    omissions.omit(index, kind, "Object creation was unsupported")
                continue
            name = "select_palette" if isinstance(record, fixed.SelectPalette) else "select_object"
            ok, _ = invoke(index, kind, name, {"handle": handle})
            if ok and name == "select_palette":
                selected_palette[0] = handle
            continue
        if isinstance(record, (variable.SetPaletteEntries, fixed.ResizePalette)):
            edit_palette(index, kind, record)
            continue
        if isinstance(record, fixed.DeleteObject):
            if record.object_index & STOCK_OBJECT or not 0 < record.object_index < len(slots):
                continue  # Stock objects are never deleted; bad slots fail natively.
            handle = slots[record.object_index]
            slots[record.object_index] = None
            if isinstance(handle, Handle):
                invoke(index, kind, "delete_object", {"handle": handle})
            continue
        if isinstance(record, PlaybackTransform.MAPPING_RECORDS):
            before = transform.device
            transform.apply(record)
            if transform.device != before:
                set_transform(index, kind)
            continue
        if isinstance(record, variable.ExtSelectClipRgn):
            if not record.region:
                if record.mode == RGN_COPY:
                    invoke(index, kind, "ext_select_clip_region", {"region": None, "mode": RGN_COPY})
                continue  # Native playback rejects other modes without a region.
            try:
                geometry = RegionGeometry(fitted_rectangles(region_rectangles(record.region), transform.fit))
            except FormatError as error:
                omissions.omit(index, kind, str(error))
                continue
            # ExtSelectClipRgn copies the region, so a temporary one suffices.
            ok, region = invoke(index, kind, "create_region", {"region": geometry})
            if ok:
                invoke(index, kind, "ext_select_clip_region", {"region": region, "mode": record.mode})
                invoke(index, kind, "delete_object", {"handle": region})
            continue
        if cull is not None and isinstance(record, CULLED_RECORDS) and culled(record, cull):
            continue
        if isinstance(record, variable.RegionRecord):
            paint_region(index, kind, record)
            continue
        translate = TRANSLATIONS.get(type(record))
        creation = kind in CREATION_TYPES
        if creation and not 0 < record.object_index < len(slots):
            continue  # Native playback cannot store the object.
        try:
            if translate is None:
                raise Unsupported(f"{record_name(kind)} is not yet supported")
            name, arguments = translate(record)
        except Stop:
            break
        except Fails:
            if creation:
                slots[record.object_index] = None
            continue
        except (Unsupported, FormatError) as reason:
            # FormatError: offset-addressed data lies outside the record.
            if creation:
                slots[record.object_index] = unavailable
            omissions.omit(index, kind, str(reason))
            continue
        if name is None:
            continue  # The record fails natively without drawing.
        font_xform = isinstance(record, TEXT_RECORDS) and record.graphics_mode != GM_ADVANCED
        if font_xform:
            # Native playback sizes a GM_COMPATIBLE record's font by the
            # scales it was recorded with, then clears them.
            invoke(index, kind, "set_font_xform", {"x_scale": record.ex_scale, "y_scale": record.ey_scale})
        if name == "poly_text_out":
            ok, result = True, None
            for call in arguments:
                invoke(index, kind, "ext_text_out", call)
        else:
            ok, result = invoke(index, kind, name, arguments)
        if font_xform:
            invoke(index, kind, "set_font_xform", {"x_scale": None, "y_scale": None})
        if creation:
            if ok and not isinstance(result, Handle):
                raise PlaybackError(f"Record {index}: object creation did not return a handle")
            # Replacing an occupied slot leaves the earlier object alive, as natively.
            slots[record.object_index] = result if ok else unavailable
    return omissions.result()
