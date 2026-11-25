"""Translate EMF records to backend calls without rasterizing or decoding text.

Playback follows PlayEnhMetaFile: the backend is put in GM_ADVANCED, and the
metafile's mapping records become one world transform that also fits the
picture frame to the target rectangle (see ``transform``). Other records
translate only where their meaning matches an existing GDI call; the rest
are reported as omissions, so a caller can tell a complete rendering from a
partial one. Comments never draw; EMF+ drawing is reported only when a file
has no GDI fallback for it.
"""

import struct
from collections.abc import Callable

from ..binary import FormatError, Limits
from ..constants import ETO_CLIPPED, ETO_GLYPH_INDEX, ETO_OPAQUE, GM_ADVANCED, PS_NULL, PS_SOLID
from ..gdi import GDI, Call, Handle, InvalidOperation, UnsupportedOperation
from ..mapping import fixed as to_fixed
from ..numeric import float32
from ..objects import BitmapData, EncodedText, FontRequest, GlyphIndices, PaletteEntries, RegionGeometry
from ..playback import Omission as Omission
from ..playback import Omissions, PlaybackError, SaveLevels
from . import bitmaps, fixed, text, variable
from .constants import CREATION_TYPES, RecordType
from .file import Metafile
from .objects import region_rectangles
from .records import UnknownRecord, record_type
from .transform import PlaybackTransform, natural_size

STOCK_OBJECT = 0x80000000
BS_NULL = 1
BS_DIBPATTERN = 5
DIB_RGB_COLORS = 0
SRCCOPY = 0x00CC0020
GM_COMPATIBLE = 1
ETO_NO_RECT = text.ETO_NO_RECT
PS_GEOMETRIC = 0x00010000
PS_TYPE_MASK = 0x000F0000
PS_STYLE_MASK = 0x0000000F
PS_USERSTYLE = 7
EMFPLUS_HEADER = 0x4001
EMFPLUS_DUAL = 0x0001
RGN_COPY = 5
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

# Stock brushes and pens (MS-EMF 2.1.31) as equivalent creations. Stock
# fonts, the default palette and the DC brush and pen are not emulated.
STOCK_CREATIONS = {
    0x80000000: ("create_brush", {"style": 0, "color": 0xFFFFFF, "hatch": 0}),  # WHITE_BRUSH
    0x80000001: ("create_brush", {"style": 0, "color": 0xC0C0C0, "hatch": 0}),  # LTGRAY_BRUSH
    0x80000002: ("create_brush", {"style": 0, "color": 0x808080, "hatch": 0}),  # GRAY_BRUSH
    0x80000003: ("create_brush", {"style": 0, "color": 0x404040, "hatch": 0}),  # DKGRAY_BRUSH
    0x80000004: ("create_brush", {"style": 0, "color": 0x000000, "hatch": 0}),  # BLACK_BRUSH
    0x80000005: ("create_brush", {"style": BS_NULL, "color": 0, "hatch": 0}),  # NULL_BRUSH
    0x80000006: ("create_pen", {"style": PS_SOLID, "width": 0, "color": 0xFFFFFF}),  # WHITE_PEN
    0x80000007: ("create_pen", {"style": PS_SOLID, "width": 0, "color": 0x000000}),  # BLACK_PEN
    0x80000008: ("create_pen", {"style": PS_NULL, "width": 0, "color": 0}),  # NULL_PEN
}


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
        if isinstance(record, bitmaps.StretchBlt):
            raise Unsupported("Source-less StretchBlt")
        return "pat_blt", {
            "x": record.x,
            "y": record.y,
            "width": record.width,
            "height": record.height,
            "rop": record.rop,
        }
    source_transform = (record.src_m11, record.src_m12, record.src_m21, record.src_m22, record.src_dx, record.src_dy)
    if source_transform != IDENTITY:
        raise Unsupported("Transformed blit sources are not yet supported")
    if record.usage != DIB_RGB_COLORS:
        raise Unsupported("Palette-indexed blit sources are not yet supported")
    arguments = {
        "x": record.x,
        "y": record.y,
        "width": record.width,
        "height": record.height,
        "src_x": record.src_x,
        "src_y": record.src_y,
        "rop": record.rop,
        "source": _dib(record),
    }
    if isinstance(record, bitmaps.StretchBlt):
        return "dib_stretch_blt", arguments | {"src_width": record.src_width, "src_height": record.src_height}
    return "dib_bit_blt", arguments


def _stretch_dib(record):
    if not record.bitmap_size:
        raise Unsupported("StretchDIBits without a bitmap")
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


def _set_dib_to_device(record, matrix):
    """Native playback scales the transfer with the playback transform.

    A record carrying every scan line plays exactly as a SRCCOPY stretch of
    the whole source rectangle. Partial bands are unverified unless the
    transform only translates.
    """
    if not record.bitmap_size:
        raise Unsupported("SetDIBitsToDevice without a bitmap")
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
    if (matrix[0], matrix[3]) != (1.0, 1.0):
        raise Unsupported("Scaled SetDIBitsToDevice bands are not yet supported")
    return "set_dib_to_device", {
        "x": record.x,
        "y": record.y,
        "width": record.src_width,
        "height": record.src_height,
        "src_x": record.src_x,
        "src_y": record.src_y,
        "start_scan": record.start_scan,
        "scan_count": record.scan_count,
        "color_usage": record.usage,
        "source": _dib(record),
    }


def _ext_create_pen(record):
    """Pens that CreatePen can also make; patterned, styled and other pens are not."""
    style = record.style & PS_STYLE_MASK
    pen_type = record.style & PS_TYPE_MASK
    if record.brush_style != 0 or record.style_entries or style == PS_USERSTYLE or style > PS_USERSTYLE:
        raise Unsupported("Extended pen brushes and styles are not yet supported")
    if pen_type == 0 and record.width <= 1:
        return "create_pen", {"style": style, "width": record.width, "color": record.color}
    if pen_type == PS_GEOMETRIC and record.width > 1 and style in (PS_SOLID, PS_NULL, 6):
        return "create_pen", {"style": record.style & ~PS_TYPE_MASK, "width": record.width, "color": record.color}
    raise Unsupported("Extended pen type is not yet supported")


def _ext_text_out(record):
    if record.graphics_mode != GM_COMPATIBLE:
        raise Unsupported("Advanced graphics-mode text is not yet supported")
    options = record.options & ~ETO_NO_RECT
    if isinstance(record, text.ExtTextOutW):
        if not options & ETO_GLYPH_INDEX:
            raise Unsupported("Unicode text is not yet supported")
        data = record.text
        value = GlyphIndices(struct.unpack(f"<{len(data) // 2}H", data))
    else:
        value = EncodedText(record.text)
    rectangle = record.rectangle if options & (ETO_OPAQUE | ETO_CLIPPED) else None
    return "ext_text_out", {
        "x": record.x,
        "y": record.y,
        "text": value,
        "options": options,
        "rectangle": rectangle,
        "advances": record.advances,
    }


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
    fixed.SetLayout: _direct("set_layout", "layout"),
    fixed.SetTextJustification: _direct("set_text_justification", "break_count", "break_extra"),
    variable.Polygon: _direct("polygon", "points"),
    variable.Polygon16: _direct("polygon", "points"),
    variable.Polyline: _direct("polyline", "points"),
    variable.Polyline16: _direct("polyline", "points"),
    variable.PolyPolygon: _direct("poly_polygon", polygons="figures"),
    variable.PolyPolygon16: _direct("poly_polygon", polygons="figures"),
    variable.CreatePalette: lambda r: ("create_palette", {"palette": PaletteEntries(r.entries) if r.entries else None}),
    variable.ExtCreateFontIndirectW: lambda r: ("create_font", _font(r)),
    bitmaps.BitBlt: _source_blit,
    bitmaps.StretchBlt: _source_blit,
    bitmaps.StretchDIBits: _stretch_dib,
    bitmaps.CreateDIBPatternBrushPt: lambda r: (
        "create_dib_pattern_brush",
        {"style": BS_DIBPATTERN, "color_usage": r.usage, "bitmap": _dib(r)},
    ),
    bitmaps.ExtCreatePen: _ext_create_pen,
    text.ExtTextOutA: _ext_text_out,
    text.ExtTextOutW: _ext_text_out,
}


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


def play(
    metafile: Metafile,
    backend: GDI,
    *,
    strict: bool = False,
    limits: Limits | None = None,
    rect: tuple[int, int, int, int] | None = None,
    comment: Callable[[int, variable.Comment], None] | None = None,
) -> tuple[Omission, ...]:
    """Play into a supplied context; return diagnostics for unsupported work.

    The picture frame is fitted to ``rect`` in the backend's device pixels;
    the default is the frame's own size in header device pixels at the
    origin. The caller owns the backend's other initial state. ``comment``
    receives every EMR_COMMENT record with its index, for a front-end that
    interprets EMF+ or other comment payloads.
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
    transform = PlaybackTransform(metafile.header, rect if rect is not None else (0, 0, *natural_size(metafile.header)))

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
            if object_index not in STOCK_CREATIONS:
                omissions.omit(index, kind, f"Stock object {object_index & 0xFF} is not yet supported")
                return unavailable
            if object_index not in stock:
                name, arguments = STOCK_CREATIONS[object_index]
                ok, handle = invoke(index, kind, name, arguments)
                if not ok:
                    return unavailable
                stock[object_index] = handle
            return stock[object_index]
        if not 0 < object_index < len(slots) or slots[object_index] is None:
            return None
        return slots[object_index]

    def set_transform(index, kind):
        matrix = transform.matrix()
        names = ("m11", "m12", "m21", "m22", "dx", "dy")
        invoke(index, kind, "set_world_transform", dict(zip(names, matrix, strict=True)))

    # Attributed to the header record, which native playback starts from.
    invoke(-1, RecordType.HEADER, "set_graphics_mode", {"mode": GM_ADVANCED})
    set_transform(-1, RecordType.HEADER)
    for index, record in enumerate(metafile.records):
        kind = record_type(record)
        if kind == RecordType.EOF:
            break
        if isinstance(record, UnknownRecord):
            omissions.omit(index, kind, f"{record_name(kind)} is not yet supported")
            continue
        if isinstance(record, variable.Comment):
            if comment is not None:
                comment(index, record)
            if emf_plus_dual(record) is False:
                omissions.omit(index, kind, "EMF+ drawing without a GDI fallback is not rendered")
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
                omissions.omit(index, kind, "Absolute RestoreDC levels are not yet supported")
                continue
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
            invoke(index, kind, name, {"handle": handle})
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
            before = transform.matrix()
            transform.apply(record)
            if transform.matrix() != before:
                set_transform(index, kind)
            continue
        if isinstance(record, variable.ExtSelectClipRgn):
            if record.mode != RGN_COPY:
                omissions.omit(index, kind, "Combining clip regions is not yet supported")
            elif not record.region:
                invoke(index, kind, "select_clip_region", {"region": None})
            else:
                try:
                    geometry = RegionGeometry(fitted_rectangles(region_rectangles(record.region), transform.fit))
                except FormatError as error:
                    omissions.omit(index, kind, str(error))
                    continue
                # ExtSelectClipRgn copies the region, so a temporary one suffices.
                ok, region = invoke(index, kind, "create_region", {"region": geometry})
                if ok:
                    invoke(index, kind, "select_clip_region", {"region": region})
                    invoke(index, kind, "delete_object", {"handle": region})
            continue
        translate = TRANSLATIONS.get(type(record))
        if isinstance(record, bitmaps.SetDIBitsToDevice):
            matrix = transform.matrix()

            def translate(record, matrix=matrix):
                return _set_dib_to_device(record, matrix)

        creation = kind in CREATION_TYPES
        if creation and not 0 < record.object_index < len(slots):
            continue  # Native playback cannot store the object.
        try:
            if translate is None:
                raise Unsupported(f"{record_name(kind)} is not yet supported")
            name, arguments = translate(record)
        except (Unsupported, FormatError) as reason:
            # FormatError: offset-addressed data lies outside the record.
            if creation:
                slots[record.object_index] = unavailable
            omissions.omit(index, kind, str(reason))
            continue
        ok, result = invoke(index, kind, name, arguments)
        if creation:
            if ok and not isinstance(result, Handle):
                raise PlaybackError(f"Record {index}: object creation did not return a handle")
            # Replacing an occupied slot leaves the earlier object alive, as natively.
            slots[record.object_index] = result if ok else unavailable
    return omissions.result()
