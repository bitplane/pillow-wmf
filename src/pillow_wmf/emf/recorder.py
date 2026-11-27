"""Record GDI calls into EMF the way a native enhanced-metafile DC does.

Unlike the WMF recorder, which writes one record per call, an EMF recording
DC is emulated: Windows rewrites some calls as it records them, and the
header summarizes the drawing.

- Objects are written lazily. A created pen, brush, font or palette gets its
  creation record and the lowest free 1-based slot when it is first
  selected; an object that is never selected never appears, nor does its
  deletion. Stock objects are selected as ``0x80000000 | index``.
- In GM_COMPATIBLE, box shapes become lower-right inclusive: the right and
  bottom edges are mapped to device pixels, moved in by one, and mapped
  back.
- Point records use their 16-bit forms whenever every coordinate fits.
- Records with a bounds field, and the header, carry inclusive device
  bounds. Regions are written inline as region data, never as objects.

The recording DC starts in MM_TEXT and GM_COMPATIBLE on ``device``. Text
records as EMR_EXTTEXTOUTW, measured with the recorder's fonts; see
``docs/emf.md``.
"""

from __future__ import annotations

import heapq
import struct
from copy import deepcopy
from dataclasses import dataclass, field, replace
from fractions import Fraction
from math import cos, floor, radians, sin

from ..bitmap import encode_dib24, read_dib
from ..bitmap16 import read_bitmap16
from ..constants import (
    ETO_CLIPPED,
    ETO_GLYPH_INDEX,
    ETO_OPAQUE,
    GM_ADVANCED,
    GM_COMPATIBLE,
    MM_TEXT,
    PS_INSIDEFRAME,
    PS_NULL,
)
from ..ellipse import advanced_arc, arc_figure
from ..gdi import Call, Handle, InvalidOperation, UnsupportedOperation
from ..geometry import DevicePath, coverage_spans
from ..limits import DEFAULT_LIMITS
from ..mapping import IDENTITY_TRANSFORM, REFERENCE_DEVICE, Mapping, ReferenceDevice, _round_half_away
from ..mapping import fixed as to_fixed
from ..numeric import float32
from ..objects import BitmapData, EncodedText, FontRequest, RegionGeometry
from ..raster import POSITION_INVALIDATING_CALLS
from ..stroke import realize_pen
from ..trace import TraceContext
from ..world import modified as modified_world
from . import bitmaps, fixed, text, variable
from .file import Metafile
from .objects import FACE_NAME_BYTES, LogFont

STOCK_OBJECT = 0x80000000
_RADIAL_ARGUMENTS = ("left", "top", "right", "bottom", "start_x", "start_y", "end_x", "end_y")
DEFAULT_PALETTE = 15
NULL_PEN = 8
BLACK_PEN = 7
# Native recording marks bitmap brushes with this DWORD before their
# BitmapInfo; a DIB pattern pen carries it in place of the header size.
BRUSH_MARKER = struct.pack("<I", 0x20000000)
# Native recording writes LOGFONTEXDV: empty full name, style and script,
# then a design vector with no axes.
FONT_EXTENSION = bytes(256) + struct.pack("<II", 0x08007664, 0)
NULL_BRUSH = 5
BS_NULL = 1
PT_MOVETO = 6
RGN_COPY = 5
FLOODFILLBORDER = 0
DIB_RGB_COLORS = 0
SRCCOPY = 0x00CC0020
# The reference display's size at 96 DPI, which native recordings carry in
# the header's micrometre extension rather than the rounded millimetres.
REFERENCE_MICROMETRES = (270933, 203200)

Rect = tuple[int, int, int, int]


def region_data(rectangles) -> bytes:
    """A RegionData object (MS-EMF 2.2.24) holding ``rectangles`` as given."""
    rectangles = tuple(tuple(rectangle) for rectangle in rectangles)
    if rectangles:
        bound = (
            min(r[0] for r in rectangles),
            min(r[1] for r in rectangles),
            max(r[2] for r in rectangles),
            max(r[3] for r in rectangles),
        )
    else:
        bound = (0, 0, 0, 0)
    header = struct.pack("<4I4i", 32, 1, len(rectangles), 16 * len(rectangles), *bound)
    return header + b"".join(struct.pack("<4i", *rectangle) for rectangle in rectangles)


def _dib_header(width, height, depth, compression, image_size) -> bytes:
    return struct.pack("<IiiHHIIiiII", 40, width, height, 1, depth, compression, image_size, 0, 0, 0, 0)


def _rows(layout) -> list[bytes]:
    """Uncompressed DIB rows top-down, each trimmed to its samples and
    re-padded to a DWORD with zeros."""
    used = (layout.width * layout.depth + 7) // 8
    stride = ((layout.width * layout.depth + 31) // 32) * 4
    rows = []
    for row in range(layout.height):
        start = layout.offset + row * layout.stride
        data = bytearray(layout.data[start : start + used].ljust(stride, b"\0"))
        if layout.depth < 8 and layout.width * layout.depth % 8:
            data[used - 1] &= 0xFF << (8 - layout.width * layout.depth % 8) & 0xFF
        rows.append(bytes(data))
    return rows if layout.top_down else rows[::-1]


def _remap_indices(row: bytes, depth: int, width: int, remap) -> bytes:
    data = bytearray(row)
    per_byte, mask = 8 // depth, (1 << depth) - 1
    for x in range(width):
        shift = 8 - depth * (x % per_byte + 1)
        index = data[x // per_byte] >> shift & mask
        data[x // per_byte] = data[x // per_byte] & ~(mask << shift) & 0xFF | remap[index] << shift
    return bytes(data)


def device_bitmap(bitmap) -> tuple[bytes, bytes]:
    """The (BitmapInfo, bits) a recording DC writes for a source DC's bitmap.

    GetDIBits re-encodes it bottom-up with zero padding and its image size.
    Indexed bitmaps carry a full 2^depth colour table, padded with zeros,
    and declare none used; 16- and 32-bit samples are written as
    BI_BITFIELDS with their masks (5-5-5 and 8-8-8 by default).
    """
    layout = read_dib(bitmap)
    if layout.compression not in (0, 3) or not layout.complete or layout.depth not in (1, 4, 8, 16, 24, 32):
        # The source DC holds the decoded bitmap: unwritten pixels are black.
        return device_bitmap(encode_dib24(layout.decode(gap_color=(0, 0, 0))))
    rows = _rows(layout)
    if layout.depth <= 8:
        count = 1 << layout.depth
        colours = list(layout.colors[:count])
        padded = colours + [(0, 0, 0)] * (count - len(colours))
        if layout.depth == 4:
            # 4-bpp sources are re-matched by colour: indices past a short
            # table read as black, and each colour takes the first nearest
            # entry of the zero-padded table. 1- and 8-bpp indices are kept.
            def nearest(colour):
                return min(
                    range(count), key=lambda i: sum((a - b) ** 2 for a, b in zip(padded[i], colour, strict=True))
                )

            remap = [nearest(padded[i] if i < len(colours) else (0, 0, 0)) for i in range(count)]
            rows = [_remap_indices(row, layout.depth, layout.width, remap) for row in rows]
        bits = b"".join(reversed(rows))
        table = b"".join(bytes((blue, green, red, 0)) for red, green, blue in padded)
        return _dib_header(layout.width, layout.height, layout.depth, 0, len(bits)) + table, bits
    bits = b"".join(reversed(rows))
    if layout.depth == 24:
        return _dib_header(layout.width, layout.height, 24, 0, len(bits)), bits
    header = _dib_header(layout.width, layout.height, layout.depth, 3, len(bits))
    return header + struct.pack("<3I", *layout.masks), bits


def _source_background(bitmap, state) -> int:
    """The background a transfer records: for an indexed source, the colour
    of its table entry nearest the DC's background colour (the first of any
    equally near), otherwise the background colour itself."""
    layout = read_dib(bitmap)
    background = state.background
    if layout.depth > 8 or not layout.colors:
        return background
    target = (background & 0xFF, background >> 8 & 0xFF, background >> 16 & 0xFF)
    table = list(layout.colors[: 1 << layout.depth])
    table += [(0, 0, 0)] * ((1 << layout.depth) - len(table))
    red, green, blue = min(table, key=lambda colour: sum((a - b) ** 2 for a, b in zip(colour, target, strict=True)))
    return red | green << 8 | blue << 16


def mask_bitmap(bitmap) -> tuple[bytes, bytes]:
    """A 1-bpp mask as written: no colour table, bottom-up, DIB_PAL_INDICES."""
    layout = read_dib(bitmap, color_usage=2)
    if layout.depth != 1 or layout.compression != 0 or not layout.complete:
        return False
    bits = b"".join(reversed(_rows(layout)))
    return _dib_header(layout.width, layout.height, 1, 0, len(bits)), bits


def packed_bitmap(bitmap) -> tuple[bytes, bytes]:
    """A packed DIB re-encoded as CreateDIBPatternBrushPt records it."""
    layout = read_dib(bitmap)
    if not layout.complete:
        # Missing samples are recorded as zeros.
        bitmap = replace(bitmap, data=bitmap.data.ljust(layout.offset + layout.stride * abs(layout.height), b"\0"))
        layout = read_dib(bitmap)
    bits = b"".join(reversed(_rows(layout)))
    info = bytearray(bitmap.data[: layout.offset])
    struct.pack_into("<i", info, 8, abs(layout.height))
    struct.pack_into("<I", info, 20, len(bits))
    return bytes(info), bits


def _offset_record(cls, values: dict, *blocks, lead: bytes = b""):
    """Place (info, bits) blocks after the fixed fields, as native records do.

    ``lead`` is written between the fixed fields and the first block.
    """
    offset = 8 + struct.calcsize("<" + cls.wire_layout) + len(lead)
    names = (("bitmap_offset", "bitmap_size", "bits_offset", "bits_size"),)
    names += (("mask_offset", "mask_size", "mask_bits_offset", "mask_bits_size"),)
    data = b""
    for group, block in zip(names, blocks, strict=False):
        if block is None:
            continue  # Absent blocks keep zero offsets and sizes.
        info, bits = block
        values |= dict(
            zip(group, (offset + len(data), len(info), offset + len(data) + len(info), len(bits)), strict=True)
        )
        data += info + bits
    return cls(**values, data=lead + data)


def _fits16(points) -> bool:
    return all(-32768 <= value <= 32767 for point in points for value in point)


def _union(first: Rect | None, second: Rect | None) -> Rect | None:
    if first is None:
        return second
    if second is None:
        return first
    return (min(first[0], second[0]), min(first[1], second[1]), max(first[2], second[2]), max(first[3], second[3]))


def _intersection(first: Rect, second: Rect) -> Rect | None:
    box = (max(first[0], second[0]), max(first[1], second[1]), min(first[2], second[2]), min(first[3], second[3]))
    return box if box[0] <= box[2] and box[1] <= box[3] else None


def _box(points) -> Rect | None:
    points = tuple(points)
    if not points:
        return None
    xs, ys = [x for x, _ in points], [y for _, y in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _log_font(request: FontRequest) -> LogFont:
    name = request.face_name
    if not isinstance(name, str):
        # CreateFontIndirectA converts the face name through the ANSI code page.
        data = name.data if hasattr(name, "data") else bytes(name)
        name = data.split(b"\0", 1)[0].decode("cp1252", "replace")
    encoded = name.encode("utf-16-le")[: FACE_NAME_BYTES - 2]
    values = {key: getattr(request, key) for key in LogFont.__dataclass_fields__ if key != "face_name"}
    return LogFont(**values, face_name=encoded.ljust(FACE_NAME_BYTES, b"\0"))


def _region_box(spans, contours) -> Rect:
    """The inclusive box GDI gives the region a path's fill coverage makes.

    A figure without area (an open line closed onto itself) covers nothing,
    yet each of its non-horizontal edges ends a scan band at the first pixel
    row whose centre it does not reach, stretching the box: up to that row
    above the coverage, or to the row before it below. With no coverage the
    region is empty.
    """
    box = _box(point for y, start, end in spans for point in ((start, y), (end - 1, y)))
    if box is None:
        return (0, 0, -1, -1)
    left, top, right, bottom = box
    for points in contours:
        closed = list(zip(points, points[1:] + points[:1], strict=True))
        if sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in closed):
            continue  # A figure with area bounds the region by its coverage.
        for (_, y0), (_, y1) in closed:
            if y0 != y1:
                end = -((8 - max(y0, y1)) // 16)  # ceil((max - 8) / 16) in 28.4
                top, bottom = min(top, end), max(bottom, end - 1)
    return left, top, right, bottom


def _poly_draw_valid(types, count) -> bool:
    """Whether PolyDraw accepts these point types: moves, lines and whole cubics."""
    if len(types) != count:
        return False
    index = 0
    while index < count:
        kind = types[index] & ~1
        if kind in (2, 6):  # PT_LINETO, PT_MOVETO
            index += 1
        elif kind == 4 and index + 2 < count and all(t & ~1 == 4 for t in types[index : index + 3]):
            index += 3
        else:
            return False
    return True


@dataclass
class _Object:
    kind: str
    create: object = None  # A function from slot to creation record, for written kinds.
    region: RegionGeometry | None = None
    stock: int | None = None
    slot: int | None = None
    # Pens: width, PS_* style and whether joins are mitred, for bounds.
    width: int = 0
    style: int = 0
    miter: bool = False
    square: bool = False
    # Pens: the creating call's name and arguments, to realize it for WidenPath.
    realize: tuple | None = None
    # A creation that fails natively: selecting it records nothing.
    null: bool = False
    # Fonts: the logical font, to lay out recorded text.
    request: FontRequest | None = None


@dataclass
class _State:
    mapping: Mapping
    graphics_mode: int = GM_COMPATIBLE
    objects: dict[int, _Object] = field(default_factory=dict)
    free: list[int] = field(default_factory=list)
    capacity: int = 1
    pen: _Object = field(default_factory=lambda: _Object("pen"))
    position: tuple[int, int] = (0, 0)
    # The exact 28.4 device point an arc left the current position at, which
    # the next *To call starts from; None once a logical point sets it.
    fixed_position: tuple[int, int] | None = None
    # The cached 28.4 device position ArcTo starts from (see raster_state).
    # On a recording DC drawing refreshes it under the current transform.
    device_position: tuple[int, int] | None = (0, 0)
    # Whether the DC has ever held a non-identity world transform. From then
    # on GM_COMPATIBLE curved shapes keep their far edges in their bounds,
    # whatever transform follows.
    world_transformed: bool = False
    bounds: Rect | None = None
    path: Rect | None = None
    recording_path: bool = False
    # Path figures as (28.4 device points, closed), while they can be traced;
    # None once a figure the recorder does not trace joins the path.
    figures: list | None = field(default_factory=list)
    # A raster DC building the same path, for figures the recorder does not
    # trace; None once it cannot follow the path.
    shadow: object | None = None
    shadow_pen: _Object | None = None
    widened: bool = False
    fill_mode: int = 1
    miter_limit: float = 10.0
    # The clip region's inclusive device bounding box; None when unclipped.
    clip: Rect | None = None
    brush_null: bool = False
    # Every colour written to a palette record, for the EOF palette.
    colours: list = field(default_factory=list)
    palette: _Object | None = None
    background: int = 0xFFFFFF
    # Arc direction: what the program set, and what the file last recorded.
    arc_direction: int = 1
    recorded_arc_direction: int = 1
    # Text state the recorded advances and bounds follow.
    font: _Object | None = None
    text_alignment: int = 0
    background_mode: int = 2
    character_extra: int = 0
    justification: tuple[int, int] = (0, 0)
    # (logical position, 28.4 device position) after current-position text.
    text_position: tuple | None = None
    saved: list = field(default_factory=list)


class Recorder(TraceContext):
    """A recording DC emulator producing native-shaped EMF records."""

    def __init__(
        self,
        *,
        device: ReferenceDevice = REFERENCE_DEVICE,
        micrometres: tuple[int, int] | None = REFERENCE_MICROMETRES,
        max_objects: int = DEFAULT_LIMITS.max_objects,
        max_saved_states: int = DEFAULT_LIMITS.max_saved_states,
        trace_calls: bool = True,
        fonts=None,
    ):
        super().__init__(max_objects=max_objects, max_saved_states=max_saved_states, trace_calls=trace_calls)
        # Fonts lay out recorded text: its advances and bounds.
        self.fonts = fonts
        self.device = device
        self.micrometres = micrometres
        self.records: list = []
        mapping = Mapping(mode=MM_TEXT, window_extent=(1, 1), viewport_extent=(1, 1), device=device)
        mapping.surface_width = device.pixels[0]
        self._state = _State(mapping)

    # Bookkeeping -----------------------------------------------------------

    def prepare(self, call: Call):
        token = super().prepare(call)
        state = deepcopy(self._state)
        records = self._record(token.call, state)
        for record in records:
            record.to_bytes()  # Validate before anything is committed.
        return replace(token, payload=(records, state))

    def _execute(self, prepared):
        records, state = prepared.payload
        result = self._commit(prepared.call)
        self._state = state
        self.records.extend(records)
        return result

    def _object(self, state: _State, handle: Handle) -> _Object:
        return state.objects[handle.serial]

    def is_null_object(self, handle: Handle) -> bool:
        entry = self._state.objects.get(handle.serial)
        return entry is not None and entry.null

    def _collect(self, state: _State, entries) -> None:
        for red, green, blue, _ in entries:
            if (red, green, blue, 0) not in state.colours:
                state.colours.append((red, green, blue, 0))

    def _slot(self, state: _State, entry: _Object, records: list) -> int:
        """The file slot of an object, writing its creation record on first use."""
        if entry.stock is not None:
            return STOCK_OBJECT | entry.stock
        if entry.slot is None:
            if state.free:
                entry.slot = heapq.heappop(state.free)
            else:
                entry.slot = state.capacity
                state.capacity += 1
            record = entry.create(entry.slot)
            if isinstance(record, variable.CreatePalette):
                self._collect(state, record.entries)
            records.append(record)
        return entry.slot

    # Geometry ----------------------------------------------------------------

    def _device(self, state: _State, x: int, y: int) -> tuple[int, int]:
        return state.mapping.device_point(x, y)

    def _device_box(self, state: _State, points) -> Rect | None:
        """The device pixels points cover; under rotation or shear, the pixels
        their exact 28.4 positions lie across."""
        if state.mapping.rotated:
            exact = [state.mapping.fixed_point(x, y) for x, y in points]
            if not exact:
                return None
            xs, ys = [x for x, _ in exact], [y for _, y in exact]
            return min(xs) >> 4, min(ys) >> 4, (max(xs) + 15) >> 4, (max(ys) + 15) >> 4
        return _box(self._device(state, x, y) for x, y in points)

    def _device_rect(
        self, state: _State, left: int, top: int, right: int, bottom: int, *, closed=False, curved=False
    ) -> Rect:
        """The inclusive device box of a logical box, as bounds count it.

        In GM_COMPATIBLE the device right and bottom edges are moved in by
        one pixel; in GM_ADVANCED the mapped edges are used as they are. Once
        the DC has held a non-identity world transform, a ``curved`` shape's
        box keeps its GM_COMPATIBLE edges. Under rotation or shear the box spans the pixels its four corners'
        exact positions lie across; the far edges are exclusive except for a
        ``closed`` box (a GM_ADVANCED rectangle includes its lower-right edges).
        """
        if state.mapping.rotated:
            corners = ((left, top), (right, top), (right, bottom), (left, bottom))
            exact = [state.mapping.fixed_point(x, y) for x, y in corners]
            xs, ys = [x for x, _ in exact], [y for _, y in exact]
            inset = 0 if closed else 1
            return min(xs) >> 4, min(ys) >> 4, ((max(xs) + 15) >> 4) - inset, ((max(ys) + 15) >> 4) - inset
        (x0, y0), (x1, y1) = self._device(state, left, top), self._device(state, right, bottom)
        if state.graphics_mode == GM_COMPATIBLE and not (curved and state.world_transformed):
            x1, y1 = x1 - 1, y1 - 1
        return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    def _inclusive(self, state: _State, right: int, bottom: int) -> tuple[int, int]:
        """GM_COMPATIBLE box edges moved in by one device pixel's logical size.

        The logical size of a device pixel is the window extent over the
        viewport extent; the result rounds half to even.
        """
        if state.graphics_mode != GM_COMPATIBLE:
            return right, bottom
        mapping = state.mapping
        steps = (Fraction(w, v) for w, v in zip(mapping.window_extent, mapping.viewport_extent, strict=True))
        return tuple(round(edge - step) for edge, step in zip((right, bottom), steps, strict=True))

    def _extent(self, state: _State, *, frame: bool = False) -> tuple[int, int]:
        """How far a wide stroke reaches past its figure, per axis in 28.4.

        The pen width's (w, w) and (w, -w) vectors are mapped to the device;
        each axis takes the larger magnitude, halved, plus one pixel. Square
        caps add half of that again; mitred strokes (Rectangle frames, and
        geometric pens with miter joins) take it times the miter limit. Null
        and one-pixel pens reach nothing.
        """
        pen = state.pen
        if pen.style == PS_NULL or abs(pen.width * state.mapping.linear_scale[0]) <= 1:
            return (0, 0)
        mapping, width = state.mapping, pen.width
        if mapping.rotated:
            m11, m12, m21, m22 = mapping.world[:4]
        else:
            (m11, _), (m22, _) = mapping._transform()
            m12 = m21 = 0.0
        vectors = [
            tuple(to_fixed(float32(float32(x * a) + float32(y * b))) for a, b in ((m11, m21), (m12, m22)))
            for x, y in ((width, width), (width, -width))
        ]
        extent = [(max(abs(vector[axis]) for vector in vectors) >> 1) + 16 for axis in (0, 1)]
        if pen.square:
            extent = [value + (value >> 1) for value in extent]
        if frame or pen.miter:
            extent = [_round_half_away(float32(float32(value) * float32(state.miter_limit))) for value in extent]
        return extent[0], extent[1]

    def _stroked(self, state: _State, box: Rect | None, *, frame: bool = False, fixed_points=()) -> Rect | None:
        """A figure's device box, as a stroke reaches past it.

        A wide stroke reaches its 28.4 extent past the figure, here the device
        box with any exact 28.4 points; the low edges round down and the high
        edges up.
        """
        if box is None and not fixed_points:
            return None
        if state.recording_path:
            return box  # Path figures are measured unstroked.
        ex, ey = self._extent(state, frame=frame)
        corners = [*(point for point in fixed_points)]
        if box is not None:
            corners += [(box[0] * 16, box[1] * 16), (box[2] * 16, box[3] * 16)]
        if not (ex or ey):
            if not fixed_points:
                return box
            return _union(box, _box((x >> 4, y >> 4) for x, y in fixed_points))
        xs, ys = [x for x, _ in corners], [y for _, y in corners]
        return ((min(xs) - ex) >> 4, (min(ys) - ey) >> 4, -((-(max(xs) + ex)) >> 4), -((-(max(ys) + ey)) >> 4))

    def _start(self, state: _State) -> tuple[tuple, tuple, tuple]:
        """The current position for a *To call's bounds: logical points, exact
        28.4 points, then device pixels.

        After an arc a wide pen starts from the exact 28.4 point; one-pixel
        pens from its floored logical point and the device pixel the exact
        point rounds up to.
        """
        if state.fixed_position is not None:
            if self._extent(state) != (0, 0):
                return (), (state.fixed_position,), ()
            x, y = state.fixed_position
            pixel = ((x + 15) >> 4, (y + 15) >> 4)
            # Under rotation or shear only the exact point counts.
            return ((), (), (pixel,)) if state.mapping.rotated else ((state.position,), (), (pixel,))
        return (state.position,), (), ()

    def _clipped(self, state: _State, box: Rect | None) -> Rect | None:
        """Record bounds are clipped like the header's, outside path brackets."""
        if box is None or state.clip is None or state.recording_path:
            return box
        return _intersection(box, state.clip)

    def _draw(self, state: _State, box: Rect | None) -> None:
        """Account a drawn device box in the header bounds and any open path.

        The header only counts what the clip region lets through.
        """
        if box is None:
            return
        if state.recording_path:
            # Drawing inside a path bracket only measures the path.
            state.path = _union(state.path, box)
            return
        if state.clip is not None:
            box = _intersection(box, state.clip)
            if box is None:
                return
        state.bounds = _union(state.bounds, box)

    # Translation -------------------------------------------------------------

    def _record(self, call: Call, state: _State) -> list:
        name, a = call.name, call.kwargs
        records: list = []
        simple = _SIMPLE.get(name)
        if simple is not None:
            records.append(simple(a))
            if name == "set_background_mode":
                state.background_mode = a["mode"]
            elif name == "set_text_alignment":
                state.text_alignment = a["alignment"]
            if name == "save_dc":
                state.saved.append({key: deepcopy(getattr(state, key)) for key in _SAVED})
            elif name == "restore_dc":
                level = a["saved_dc"]
                index = level - 1 if level > 0 else len(state.saved) + level
                if not 0 <= index < len(state.saved):
                    raise InvalidOperation("Invalid saved DC reference")
                for key, value in state.saved[index].items():
                    setattr(state, key, value)
                del state.saved[index:]
            return records
        handler = getattr(self, f"_record_{name}", None)
        if handler is None:
            raise UnsupportedOperation(f"EMF recording of {name} is not yet supported")
        if state.recording_path and state.shadow is not None and name in _PATH_CALLS:
            self._follow_path(call, state)
        handler(a, state, records)
        if name in POSITION_INVALIDATING_CALLS and state.device_position is not None:
            # A recording DC's drawing refreshes a valid cached device
            # position under the current transform.
            state.device_position = state.mapping.fixed_point(*state.position)
        return records

    # Objects

    def _created(self, state: _State, entry: _Object) -> None:
        # Preparation and application are sequential, so the next handle
        # serial is the one this creation will receive.
        state.objects[self._next_handle] = entry

    def _record_get_stock_object(self, a, state, records):
        from ..execution import STOCK_OBJECT_KINDS

        index = a["index"]
        style = PS_NULL if index == NULL_PEN else BS_NULL if index == NULL_BRUSH else 0
        self._created(state, _Object(STOCK_OBJECT_KINDS[index], stock=index, style=style))

    def _record_create_pen(self, a, state, records):
        style, width, color = a["style"], a["width"], a["color"]
        if style & 15 == PS_NULL:
            # CreatePen returns the stock NULL_PEN for PS_NULL.
            self._created(state, _Object("pen", stock=NULL_PEN, style=PS_NULL))
            return
        self._created(
            state,
            _Object(
                "pen",
                lambda slot: fixed.CreatePen(slot, style, width, 0, color),
                width=width,
                style=style & 15,
                realize=("create_pen", dict(a)),
            ),
        )

    def _record_ext_create_pen(self, a, state, records):
        style, width, color, brush_style, hatch = (
            a[key] for key in ("style", "width", "color", "brush_style", "hatch")
        )
        entries = tuple(a["entries"])
        # LOGPENEX always carries one style entry, used or not.
        offset = 8 + struct.calcsize("<" + bitmaps.ExtCreatePen.wire_layout) + 4 + 4 * max(1, len(entries))
        padding = b"" if entries else bytes(4)
        info = bits = b""
        if a["bitmap"] is not None:
            if read_dib(a["bitmap"]).compression in (1, 2):
                # As for DIB pattern brushes, creation from an RLE DIB fails.
                self._created(state, _Object("pen", null=True))
                return
            info, bits = packed_bitmap(a["bitmap"])
            info = BRUSH_MARKER + info[4:]  # The marker takes the header size's place.

        def create(slot):
            return bitmaps.ExtCreatePen(
                slot,
                offset,
                len(info),
                offset + len(info),
                len(bits),
                style,
                width,
                brush_style,
                color,
                hatch,
                entries,
                padding + info + bits,
            )

        geometric = bool(style & 0x00010000)
        self._created(
            state,
            _Object(
                "pen",
                create,
                width=width if geometric else 0,
                style=style & 15,
                miter=geometric and style & 0x0000F000 == 0x00002000,
                square=geometric and style & 0x00000F00 == 0x00000100,
                realize=("ext_create_pen", dict(a)),
            ),
        )

    def _record_create_brush(self, a, state, records):
        style, color, hatch = a["style"], a["color"], a["hatch"]
        if style == BS_NULL:
            # CreateBrushIndirect returns the stock NULL_BRUSH for BS_NULL.
            self._created(state, _Object("brush", stock=NULL_BRUSH, style=BS_NULL))
            return
        self._created(state, _Object("brush", lambda slot: fixed.CreateBrushIndirect(slot, style, color, hatch)))

    def _record_create_font(self, a, state, records):
        font = _log_font(a["font"])
        self._created(
            state,
            _Object(
                "font", lambda slot: variable.ExtCreateFontIndirectW(slot, font, FONT_EXTENSION), request=a["font"]
            ),
        )

    def _record_create_pattern_brush(self, a, state, records):
        from ..bitmap16 import read_bitmap16

        layout = read_bitmap16(a["bitmap"])
        if layout.depth == 32:
            # A 32-bit device bitmap is recorded as a bit-field DIB pattern.
            stride = layout.width * 4
            rows = [layout.data[layout.offset + y * layout.stride :][:stride] for y in range(layout.height)]
            bits = b"".join(reversed(rows))
            info = _dib_header(layout.width, layout.height, 32, 3, len(bits))
            colour_block = (info + struct.pack("<3I", 0xFF0000, 0x00FF00, 0x0000FF), bits)

            def create_colour(slot):
                values = {"object_index": slot, "usage": 0}
                return _offset_record(bitmaps.CreateDIBPatternBrushPt, values, colour_block, lead=BRUSH_MARKER)

            self._created(state, _Object("brush", create_colour))
            return
        if layout.depth != 1:
            # Native CreateBitmap only makes 1-bpp and display-depth bitmaps:
            # creation fails.
            self._created(state, _Object("brush", null=True))
            return
        used = (layout.width + 7) // 8
        stride = ((layout.width + 31) // 32) * 4
        rows = [
            layout.data[layout.offset + y * layout.stride : layout.offset + y * layout.stride + used].ljust(
                stride, b"\0"
            )
            for y in range(layout.height)
        ]
        bits = b"".join(reversed(rows))
        block = (_dib_header(layout.width, layout.height, 1, 0, len(bits)), bits)

        def create(slot):
            values = {"object_index": slot, "usage": 2}
            return _offset_record(bitmaps.CreateMonoBrush, values, block, lead=BRUSH_MARKER)

        self._created(state, _Object("brush", create))

    def _record_create_dib_pattern_brush(self, a, state, records):
        if read_dib(a["bitmap"]).compression in (1, 2):
            # Native creation from an RLE DIB fails, leaving nothing to record.
            self._created(state, _Object("brush", null=True))
            return
        block = packed_bitmap(a["bitmap"])
        usage = a["color_usage"]

        def create(slot):
            values = {"object_index": slot, "usage": usage}
            return _offset_record(bitmaps.CreateDIBPatternBrushPt, values, block, lead=BRUSH_MARKER)

        self._created(state, _Object("brush", create))

    def _record_create_palette(self, a, state, records):
        # Native recording clears the palette entry flags.
        palette = a["palette"]
        entries = tuple((r, g, b, 0) for r, g, b, _ in palette.entries) if palette is not None else ()
        self._created(state, _Object("palette", lambda slot: variable.CreatePalette(slot, entries, 0x300)))

    def _record_create_region(self, a, state, records):
        self._created(state, _Object("region", region=a["region"] or RegionGeometry()))

    def _record_select_object(self, a, state, records):
        handle = a["handle"]
        if handle is None:
            return  # Selecting a null object fails natively without a record.
        entry = self._object(state, handle)
        if entry.null:
            return  # As a null object selection.
        if entry.kind == "region":
            self._record_ext_select_clip_region({"region": handle, "mode": RGN_COPY}, state, records)
            return
        records.append(fixed.SelectObject(self._slot(state, entry, records)))
        if entry.kind == "pen":
            state.pen = entry
        elif entry.kind == "brush":
            state.brush_null = entry.style == BS_NULL
        elif entry.kind == "font":
            state.font = entry

    def _record_set_text_justification(self, a, state, records):
        state.justification = (a["break_count"], a["break_extra"])  # Not recorded; advances include it.

    def _record_set_text_character_extra(self, a, state, records):
        state.character_extra = a["extra"]  # EMF has no record; recorded advances include it.

    def _record_text_out(self, a, state, records):
        self._record_ext_text_out({**a, "options": 0, "rectangle": None, "advances": ()}, state, records)

    def _text_shadow(self, state: _State):
        """A raster DC in the recording DC's text state, to lay out text."""
        from ..raster import RasterContext

        shadow = RasterContext(1, 1, trace_calls=False, fonts=self.fonts)
        shadow.mapping = deepcopy(state.mapping)
        shadow.mapping.graphics_mode = state.graphics_mode
        if state.font is not None and state.font.request is not None:
            shadow.select_object(shadow.create_font(state.font.request))
        shadow.set_text_alignment(state.text_alignment)
        shadow.set_background_mode(state.background_mode)
        shadow.set_text_character_extra(state.character_extra)
        shadow.set_text_justification(*state.justification)
        shadow._state.position = state.position
        shadow._state.text_position = state.text_position
        return shadow

    def _text_scales(self, state: _State) -> tuple[float, float]:
        """A GM_COMPATIBLE record's font transform: 0.01 mm per logical unit on the reference device."""
        if state.graphics_mode == GM_ADVANCED:
            return 0.0, 0.0
        # The page transform alone: a world transform left from GM_ADVANCED
        # still places the text but does not enter the scales.
        mapping = state.mapping
        sx, sy = (float32(v / w) for v, w in zip(mapping.viewport_extent, mapping.window_extent, strict=True))
        (px, py), (mx, my) = self.device.pixels, self.device.millimetres
        return tuple(
            float32(float32(float32(float32(mm) * float32(scale)) * 100) / float32(pixels))
            for mm, scale, pixels in ((mx, sx, px), (my, sy, py))
        )

    def _text_record(self, state, x, y, units, options, rectangle, advances, bounds):
        data = b"".join(ord(unit).to_bytes(2, "little") for unit in units)
        data += bytes(-len(data) % 4)
        dx_offset = 0x4C + len(data)
        data += b"".join(struct.pack("<i", value) for value in advances)
        return text.ExtTextOutW(
            bounds or (0, 0, -1, -1),
            state.graphics_mode,
            *self._text_scales(state),
            x,
            y,
            len(units),
            0x4C,
            options,
            tuple(rectangle) if options & (ETO_OPAQUE | ETO_CLIPPED) else (0, 0, -1, -1),
            dx_offset,
            data,
        )

    def _text_rectangle(self, state, rectangle) -> Rect | None:
        """A text rectangle as the inclusive device box it fills."""
        (x0, y0), (x1, y1) = (state.mapping.device_point(*rectangle[:2]), state.mapping.device_point(*rectangle[2:]))
        left, right, top, bottom = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
        return (left, top, right - 1, bottom - 1) if left < right and top < bottom else None

    def _record_ext_text_out(self, a, state, records):
        content, options = a["text"], a.get("options", 0)
        rectangle, advances = a.get("rectangle"), tuple(a.get("advances", ()))
        opaque = self._text_rectangle(state, rectangle) if rectangle is not None and options & ETO_OPAQUE else None
        if not content:
            if opaque is not None:
                # GDI records the empty call, then fills the rectangle as glyph output.
                records.append(self._text_record(state, a["x"], a["y"], "", options, rectangle, (), None))
                bounds = self._clipped(state, opaque)
                records.append(
                    self._text_record(state, a["x"], a["y"], "", options | ETO_GLYPH_INDEX, rectangle, (), bounds)
                )
                self._draw(state, bounds)
            return
        shadow = self._text_shadow(state)
        units, measured, box, position, fixed_position = shadow.measure_text(a)
        if isinstance(content, EncodedText) and advances:
            advances = shadow_advances = advances  # noqa: F841 - byte-indexed advances map per character below.
        recorded = advances or measured
        bounds = None
        if box is not None:
            bounds = (box[0], box[1], box[2] - 1, box[3] - 1)
        if options & ETO_CLIPPED and rectangle is not None:
            clip = self._text_rectangle(state, rectangle)
            bounds = _intersection(bounds, clip) if bounds is not None and clip is not None else None
        if opaque is not None:
            bounds = _union(bounds, opaque)
        bounds = self._clipped(state, bounds)
        records.append(self._text_record(state, a["x"], a["y"], units, options, rectangle, recorded, bounds))
        self._draw(state, bounds)
        if position is not None:
            state.position = position
            state.device_position = None
            state.text_position = (position, fixed_position)
            state.fixed_position = None

    def _record_select_palette(self, a, state, records):
        handle = a["handle"]
        if handle is None:
            return  # As a null object selection.
        entry = self._object(state, handle)
        records.append(fixed.SelectPalette(self._slot(state, entry, records)))
        state.palette = entry

    def _selected_palette_slot(self, state, records) -> int | None:
        entry = state.palette
        if entry is None or entry.stock is not None:
            return None  # The stock palette is not edited through the file.
        return self._slot(state, entry, records)

    def _record_set_palette_entries(self, a, state, records):
        slot = self._selected_palette_slot(state, records)
        if slot is not None:
            update = a["palette"]
            records.append(variable.SetPaletteEntries(slot, update.start, tuple(update.entries)))
            self._collect(state, update.entries)

    def _record_resize_palette(self, a, state, records):
        slot = self._selected_palette_slot(state, records)
        if slot is not None:
            records.append(fixed.ResizePalette(slot, a["count"]))

    def _record_animate_palette(self, a, state, records):
        pass  # AnimatePalette is not recorded natively.

    def _record_delete_object(self, a, state, records):
        entry = state.objects.pop(a["handle"].serial)
        if entry.slot is not None:
            records.append(fixed.DeleteObject(entry.slot))
            heapq.heappush(state.free, entry.slot)

    # Mapping

    def _record_set_map_mode(self, a, state, records):
        state.mapping.set_mode(a["mode"])
        records.append(fixed.SetMapMode(a["mode"]))

    def _record_set_window_origin(self, a, state, records):
        state.mapping.window_origin = (a["x"], a["y"])
        records.append(fixed.SetWindowOrgEx(a["x"], a["y"]))

    def _record_set_viewport_origin(self, a, state, records):
        state.mapping.viewport_origin = (a["x"], a["y"])
        records.append(fixed.SetViewportOrgEx(a["x"], a["y"]))

    def _record_offset_window_origin(self, a, state, records):
        x, y = state.mapping.window_origin
        self._record_set_window_origin({"x": x + a["x"], "y": y + a["y"]}, state, records)

    def _record_offset_viewport_origin(self, a, state, records):
        x, y = state.mapping.viewport_origin
        self._record_set_viewport_origin({"x": x + a["x"], "y": y + a["y"]}, state, records)

    def _record_set_window_extent(self, a, state, records):
        state.mapping.set_extent(window=True, x=a["x"], y=a["y"])
        records.append(fixed.SetWindowExtEx(a["x"], a["y"]))

    def _record_set_viewport_extent(self, a, state, records):
        state.mapping.set_extent(window=False, x=a["x"], y=a["y"])
        records.append(fixed.SetViewportExtEx(a["x"], a["y"]))

    def _scale(self, a, state, records, *, window):
        values = (a["x_numerator"], a["x_denominator"], a["y_numerator"], a["y_denominator"])
        state.mapping.scale_extent(window=window, xn=values[0], xd=values[1], yn=values[2], yd=values[3])
        records.append((fixed.ScaleWindowExtEx if window else fixed.ScaleViewportExtEx)(*values))

    def _record_scale_window_extent(self, a, state, records):
        self._scale(a, state, records, window=True)

    def _record_scale_viewport_extent(self, a, state, records):
        self._scale(a, state, records, window=False)

    def _record_set_graphics_mode(self, a, state, records):
        # There is no EMF record; playback is always in GM_ADVANCED.
        if a["mode"] not in (GM_COMPATIBLE, GM_ADVANCED):
            raise InvalidOperation(f"Graphics mode {a['mode']}")
        state.graphics_mode = state.mapping.graphics_mode = a["mode"]

    def _record_set_polygon_fill_mode(self, a, state, records):
        records.append(fixed.SetPolyFillMode(a["mode"]))
        state.fill_mode = a["mode"]

    def _record_set_background_color(self, a, state, records):
        records.append(fixed.SetBkColor(a["color"]))
        state.background = a["color"]

    def _record_set_arc_direction(self, a, state, records):
        # Recorded lazily, before the next arc that depends on it.
        state.arc_direction = a["direction"]

    def _arc_direction(self, state, records):
        if state.arc_direction != state.recorded_arc_direction:
            records.append(fixed.SetArcDirection(state.arc_direction))
            state.recorded_arc_direction = state.arc_direction

    def _record_set_miter_limit(self, a, state, records):
        # Native recording truncates the float limit to the record's integer.
        if not a["limit"] >= 1:
            raise InvalidOperation("Miter limits are at least 1")
        records.append(fixed.SetMiterLimit(int(a["limit"])))
        state.miter_limit = float(a["limit"])

    def _record_set_world_transform(self, a, state, records):
        values = tuple(a[key] for key in ("m11", "m12", "m21", "m22", "dx", "dy"))
        # Native recording follows SetWorldTransform with MWT_SET of the same
        # matrix, even in GM_COMPATIBLE, where the call itself then fails.
        records.append(fixed.SetWorldTransform(*values))
        records.append(fixed.ModifyWorldTransform(*values, 4))
        if state.graphics_mode == GM_ADVANCED:
            state.mapping.world = values
            state.world_transformed |= tuple(map(float, values)) != IDENTITY_TRANSFORM

    def _record_modify_world_transform(self, a, state, records):
        values = tuple(a[key] for key in ("m11", "m12", "m21", "m22", "dx", "dy"))
        records.append(fixed.ModifyWorldTransform(*values, a["mode"]))
        if state.graphics_mode == GM_ADVANCED:
            world = modified_world(state.mapping.world, a["mode"], tuple(float32(v) for v in values))
            if world is not None:
                state.mapping.world = world
                state.world_transformed |= world != IDENTITY_TRANSFORM

    # Drawing

    def _turned_over(self, state, a, right, bottom) -> bool:
        """Whether GM_COMPATIBLE's inclusive edges turn a curved shape's box over.

        The recording DC then records nothing, and nothing is drawn.
        """
        return state.graphics_mode == GM_COMPATIBLE and (
            right < a["left"] <= a["right"] or bottom < a["top"] <= a["bottom"]
        )

    def _figure_box(self, state, call) -> Rect:
        """The device box a rotated curved shape's figure spans, control points included.

        The shape is built as it is drawn, on a shadow DC with the recording
        DC's transform; the box floors its least and ceils its greatest 28.4
        coordinates.
        """
        from ..raster import RasterContext

        shadow = RasterContext(1, 1, trace_calls=False)
        shadow.mapping = deepcopy(state.mapping)
        shadow._state.arc_direction = state.arc_direction
        shadow.begin_path()
        shadow.invoke(call)
        shadow.end_path()
        points = [point for path in shadow._path_figures(close=False) for command in path.commands for point in command]
        xs, ys = [x for x, _ in points], [y for _, y in points]
        return min(xs) >> 4, min(ys) >> 4, (max(xs) + 15) >> 4, (max(ys) + 15) >> 4

    def _record_box(self, a, state, records, record_type, *extra):
        left, top = a["left"], a["top"]
        right, bottom = self._inclusive(state, a["right"], a["bottom"])
        if record_type is not fixed.Rectangle and self._turned_over(state, a, right, bottom):
            return
        if record_type is fixed.Rectangle and state.recording_path and state.pen.style != PS_INSIDEFRAME:
            # Inside-frame pens inset the box; the shadow DC follows that.
            box = self._device_rect(state, left, top, a["right"], a["bottom"])
            corners = ((box[2], box[1]), (box[0], box[1]), (box[0], box[3]), (box[2], box[3]))
            if state.figures is not None:
                state.figures.append(([(x * 16, y * 16) for x, y in corners], True))
        else:
            self._untraced(state)
        records.append(record_type(left, top, right, bottom, *extra))
        rectangle = record_type is fixed.Rectangle
        box = self._device_rect(state, left, top, a["right"], a["bottom"], closed=rectangle, curved=not rectangle)
        if state.mapping.rotated and not rectangle and state.pen.style not in (PS_NULL, PS_INSIDEFRAME):
            name = "ellipse" if record_type is fixed.Ellipse else "round_rect"
            arguments = {k: a[k] for k in ("left", "top", "right", "bottom")}
            if extra:
                arguments |= {"ellipse_width": extra[0], "ellipse_height": extra[1]}
            box = self._figure_box(state, Call.make(name, **arguments))
        if state.pen.style == PS_NULL:
            if state.brush_null:
                return  # Neither outline nor interior is drawn.
            # Without a pen only the interior is drawn.
            box = (box[0], box[1], box[2] - 1, box[3] - 1)
        elif state.pen.style == PS_INSIDEFRAME:
            width = round(abs(state.pen.width * state.mapping.linear_scale[0]))
            box = (box[0] + width // 2, box[1] + width // 2, box[2] - (width - 1) // 2, box[3] - (width - 1) // 2)
        self._draw(state, self._stroked(state, box, frame=record_type is fixed.Rectangle))

    def _record_rectangle(self, a, state, records):
        self._record_box(a, state, records, fixed.Rectangle)

    def _record_ellipse(self, a, state, records):
        self._record_box(a, state, records, fixed.Ellipse)

    def _record_round_rect(self, a, state, records):
        self._record_box(a, state, records, fixed.RoundRect, a["ellipse_width"], a["ellipse_height"])

    def _radial(self, a, state, records, record_type):
        """Arcs, chords and pies count only the drawn sweep, and a pie its centre."""
        left, top = a["left"], a["top"]
        right, bottom = self._inclusive(state, a["right"], a["bottom"])
        if self._turned_over(state, a, right, bottom):
            return
        self._untraced(state)
        start, end = (a["start_x"], a["start_y"]), (a["end_x"], a["end_y"])
        self._arc_direction(state, records)
        records.append(record_type(left, top, right, bottom, *start, *end))
        x0, y0, x1, y1 = self._device_rect(state, left, top, a["right"], a["bottom"], curved=True)
        closure = {fixed.Arc: "open", fixed.ArcTo: "open", fixed.Chord: "chord", fixed.Pie: "pie"}[record_type]
        # A logical box without width or height sweeps its whole ellipse.
        degenerate = a["left"] == a["right"] or a["top"] == a["bottom"]
        figure = arc_figure(
            x0,
            y0,
            x1 + 1,
            y1 + 1,
            self._device(state, *start),
            self._device(state, *end),
            closure=closure,
            radial_bounds=(x0, y0, x0 if degenerate else x1 + 1, y1 + 1),
        )
        points = [point for command in figure.commands for point in command]
        xs, ys = [x for x, _ in points], [y for _, y in points]
        box = (min(xs) >> 4, min(ys) >> 4, (max(xs) + 15) >> 4, (max(ys) + 15) >> 4)
        if state.mapping.rotated and state.pen.style not in (PS_NULL, PS_INSIDEFRAME):
            name = {fixed.Arc: "arc", fixed.ArcTo: "arc", fixed.Chord: "chord", fixed.Pie: "pie"}[record_type]
            box = self._figure_box(state, Call.make(name, **{k: a[k] for k in _RADIAL_ARGUMENTS}))
        if record_type is fixed.ArcTo:
            box = _union(box, self._device_box(state, (state.position,)))
        self._draw(state, self._stroked(state, box))

    def _record_arc(self, a, state, records):
        self._radial(a, state, records, fixed.Arc)

    def _record_chord(self, a, state, records):
        self._radial(a, state, records, fixed.Chord)

    def _record_pie(self, a, state, records):
        self._radial(a, state, records, fixed.Pie)

    def _arc_path(self, state, box, start, end, *, direction, radial_box=None, inside_frame=False):
        """The GM_ADVANCED arc a metafile DC strokes for ArcTo and AngleArc.

        ``radial_box`` normalizes the radials when it differs from the drawn box.
        With ``inside_frame``, a wide inside-frame pen insets the radial box at
        its corners, and a box narrower than the pen gives None.
        """
        width, pen = 0, state.pen
        if inside_frame and pen.style == PS_INSIDEFRAME:
            geometric = pen.realize is not None and pen.realize[0] == "ext_create_pen"
            if not realize_pen(pen.width, *state.mapping.linear_scale, geometric=geometric).cosmetic:
                width, box = pen.width, radial_box or box
        return advanced_arc(
            state.mapping, box, start, end, direction=direction, inside_frame=width, radial_box=radial_box
        )

    @staticmethod
    def _floor_logical(state, point):
        """The logical point at or below a 28.4 device point, as GetCurrentPositionEx reports it."""
        mapping = state.mapping
        if mapping.rotated:
            m11, m12, m21, m22, dx, dy = mapping.world
            x, y = point[0] / 16 - dx, point[1] / 16 - dy
            det = m11 * m22 - m12 * m21
            return floor((x * m22 - y * m21) / det), floor((y * m11 - x * m12) / det)
        return tuple(
            floor((Fraction(value, 16) - Fraction(origin)) / Fraction(scale))
            for value, (scale, origin) in zip(point, mapping._transform(), strict=True)
        )

    def _stroke_from_position(self, state, path, end, *, cached=False):
        """Account a line from the current position into ``path``; move to ``end``.

        The current position is the exact logical end point, floored. With
        ``cached`` the line starts from the cached device position while it
        is valid.
        """
        points = [point for command in path.commands for point in command]
        if cached and state.device_position is not None:
            x, y = state.device_position
            logical, exact, pixels = (), ((x, y),), ((x >> 4, y >> 4),)
        else:
            logical, exact, pixels = self._start(state)
        if pixels:
            logical_box = self._device_box(state, logical)
            start = _union(logical_box, _box(pixels)) if logical_box is not None else _box(pixels)
        else:
            start = self._device_box(state, logical)
        if self._extent(state) != (0, 0):
            box = self._stroked(state, start, fixed_points=(*exact, *points))
        elif state.mapping.rotated:
            # A rotated figure spans the pixels its 28.4 points lie across.
            xs, ys = [x for x, _ in points], [y for _, y in points]
            box = (min(xs) >> 4, min(ys) >> 4, (max(xs) + 15) >> 4, (max(ys) + 15) >> 4)
            box = self._stroked(state, _union(box, start), fixed_points=exact)
        else:
            box = _box(((x + 15) // 16, (y + 15) // 16) for x, y in points)
            box = self._stroked(state, _union(box, start), fixed_points=exact)
        self._draw(state, box)
        state.position = (floor(end[0]), floor(end[1]))
        state.device_position = None
        state.fixed_position = path.commands[-1][-1]

    def _record_arc_to(self, a, state, records):
        left, top = a["left"], a["top"]
        right, bottom = self._inclusive(state, a["right"], a["bottom"])
        if self._turned_over(state, a, right, bottom):
            return
        self._untraced(state)
        start, end = (a["start_x"], a["start_y"]), (a["end_x"], a["end_y"])
        self._arc_direction(state, records)
        records.append(fixed.ArcTo(left, top, right, bottom, *start, *end))
        # The ellipse fills the inclusive box; the radials keep the given box.
        path = self._arc_path(
            state,
            (left, top, right, bottom),
            start,
            end,
            direction=state.arc_direction,
            radial_box=(left, top, a["right"], a["bottom"]),
            inside_frame=True,
        )
        if path is None:
            return  # A box narrower than an inside-frame pen: the call does nothing.
        # The current position is the arc's 28.4 end, floored to a logical point.
        # A DC whose position was never set starts ArcTo from the device origin.
        self._stroke_from_position(
            state, path, self._floor_logical(state, path.commands[-1][-1]), cached=state.fixed_position is None
        )

    def _record_move_to(self, a, state, records):
        records.append(fixed.MoveToEx(a["x"], a["y"]))
        state.position, state.fixed_position = (a["x"], a["y"]), None
        state.device_position = None
        self._trace(state, ((a["x"], a["y"]),))

    def _record_line_to(self, a, state, records):
        records.append(fixed.LineTo(a["x"], a["y"]))
        self._trace(state, (state.position, (a["x"], a["y"])), extend=True)
        logical, exact, pixels = self._start(state)
        box = self._device_box(state, (*logical, (a["x"], a["y"])))
        if pixels:
            box = _union(box, _box(pixels))
        self._draw(state, self._stroked(state, box, fixed_points=exact))
        state.position, state.fixed_position = (a["x"], a["y"]), None
        state.device_position = state.mapping.fixed_point(a["x"], a["y"])

    def _points(self, a, state, records, wide, narrow, *, key="points", to=False):
        points = tuple(tuple(point) for point in a[key])
        cubic = wide in (variable.PolyBezier, variable.PolyBezierTo)
        if wide is variable.PolyDraw:
            self._untraced(state)
        elif to:
            self._trace(state, (state.position, *points), extend=True, cubic=cubic)
        else:
            self._trace(state, points, closed=wide is variable.Polygon, cubic=cubic)
        # The *To forms start from the current position, unless PolyDraw
        # opens with a move.
        moves = "types" in a and a["types"][:1] == bytes((PT_MOVETO,))
        logical, exact, pixels = self._start(state) if to and not moves else ((), (), ())
        box = self._device_box(state, (*logical, *points))
        if pixels:
            box = _union(box, _box(pixels))
        bounds = self._clipped(state, self._stroked(state, box, fixed_points=exact))
        record_type = narrow if _fits16(points) else wide
        extra = (a["types"],) if "types" in a else ()
        # Inside a path bracket the record's own bounds are empty.
        written = None if state.recording_path else bounds
        records.append(record_type(written or (0, 0, -1, -1), points, *extra))
        self._draw(state, bounds)
        if to and points and ("types" not in a or _poly_draw_valid(a["types"], len(points))):
            # A PolyDraw that fails validation is recorded but moves nothing.
            state.position, state.fixed_position = points[-1], None
            state.device_position = state.mapping.fixed_point(*points[-1])

    def _record_polyline(self, a, state, records):
        self._points(a, state, records, variable.Polyline, variable.Polyline16)

    def _record_polygon(self, a, state, records):
        self._points(a, state, records, variable.Polygon, variable.Polygon16)

    def _record_poly_bezier(self, a, state, records):
        self._points(a, state, records, variable.PolyBezier, variable.PolyBezier16)

    def _record_polyline_to(self, a, state, records):
        self._points(a, state, records, variable.PolylineTo, variable.PolylineTo16, to=True)

    def _record_poly_bezier_to(self, a, state, records):
        self._points(a, state, records, variable.PolyBezierTo, variable.PolyBezierTo16, to=True)

    def _record_poly_draw(self, a, state, records):
        self._points(a, state, records, variable.PolyDraw, variable.PolyDraw16, to=True)

    def _figures(self, figures, state, records, wide, narrow):
        figures = tuple(tuple(tuple(point) for point in figure) for figure in figures)
        for figure in figures:
            self._trace(state, figure, closed=wide is variable.PolyPolygon)
        flat = tuple(point for figure in figures for point in figure)
        bounds = self._clipped(state, self._stroked(state, self._device_box(state, flat)))
        record_type = narrow if _fits16(flat) else wide
        written = None if state.recording_path else bounds
        records.append(record_type(written or (0, 0, -1, -1), figures))
        self._draw(state, bounds)

    def _record_poly_polygon(self, a, state, records):
        self._figures(a["polygons"], state, records, variable.PolyPolygon, variable.PolyPolygon16)

    def _record_poly_polyline(self, a, state, records):
        self._figures(a["polylines"], state, records, variable.PolyPolyline, variable.PolyPolyline16)

    def _record_angle_arc(self, a, state, records):
        self._untraced(state)
        x, y, radius = a["x"], a["y"], a["radius"]
        self._arc_direction(state, records)
        records.append(fixed.AngleArc(x, y, radius, a["start"], a["sweep"]))
        # Angles reduce to one turn first, as native trigonometry does.
        first, last = radians(a["start"] % 360), radians((a["start"] + a["sweep"]) % 360)
        start = (x + radius * cos(first), y - radius * sin(first))
        end = (x + radius * cos(last), y - radius * sin(last))
        # AngleArc sweeps counterclockwise for positive angles, whatever the arc
        # direction; a sweep of a turn or more covers the whole circle.
        box = (x - radius, y - radius, x + radius, y + radius)
        path = self._arc_path(
            state, box, start, start if abs(a["sweep"]) >= 360 else end, direction=2 if a["sweep"] < 0 else 1
        )
        self._stroke_from_position(state, path, end)

    def _record_set_pixel(self, a, state, records):
        records.append(fixed.SetPixelV(a["x"], a["y"], a["color"]))
        self._draw(state, self._device_box(state, ((a["x"], a["y"]),)))

    def _record_flood_fill(self, a, state, records):
        self._record_ext_flood_fill(a | {"mode": FLOODFILLBORDER}, state, records)

    def _record_ext_flood_fill(self, a, state, records):
        records.append(fixed.ExtFloodFill(a["x"], a["y"], a["color"], a["mode"]))
        # A flood can reach anywhere: it claims the whole reference device.
        width, height = self.device.pixels
        self._draw(state, (0, 0, width - 1, height - 1))

    # Paths

    def _path_point(self, state, x, y):
        if state.graphics_mode == GM_ADVANCED:
            return state.mapping.fixed_point(x, y)
        px, py = state.mapping.device_point(x, y)
        return px * 16, py * 16

    def _trace(self, state, points, *, closed=False, extend=False, cubic=False):
        """Add a traced figure to the open path, flattening Bézier points."""
        if not state.recording_path or state.figures is None:
            return
        device = [self._path_point(state, x, y) for x, y in points]
        if cubic:
            start = device[0]
            commands = tuple((start, *device[i : i + 3]) for i in range(1, len(device) - 2, 3))
            flat, previous = [start], start
            for command in commands:
                command = (previous, *command[1:])
                flat += DevicePath((command,)).vertices[1:]
                previous = command[-1]
            device = flat
        if extend and state.figures and not state.figures[-1][1]:
            figure = state.figures[-1][0]
            if figure and figure[-1] == device[0]:
                device = device[1:]
            figure.extend(device)
        else:
            state.figures.append((device, closed))

    def _untraced(self, state):
        if state.recording_path:
            state.figures = None

    def _record_begin_path(self, a, state, records):
        from ..raster import RasterContext

        records.append(fixed.BeginPath())
        state.recording_path, state.path = True, None
        state.figures, state.widened = [], False
        state.shadow, state.shadow_pen = RasterContext(1, 1, trace_calls=False), None
        state.shadow.begin_path()

    def _shadow_pen(self, state: _State) -> None:
        """Select the recording DC's pen into the shadow DC.

        Inside-frame pens inset the shapes a path is built from.
        """
        shadow, pen = state.shadow, state.pen
        if state.shadow_pen is pen:
            return
        if pen.realize is not None:
            name, arguments = pen.realize
            handle = shadow.invoke(Call.make(name, **arguments))
        else:
            handle = shadow.get_stock_object(pen.stock if pen.stock is not None else BLACK_PEN)
        shadow.select_object(handle)
        state.shadow_pen = pen

    def _follow_path(self, call: Call, state: _State) -> None:
        """Replay a path-building call on the shadow DC from the current state.

        In GM_COMPATIBLE, ArcTo and AngleArc build their figures as in
        GM_ADVANCED, ArcTo from its inclusive box, as the recording DC does.
        """
        shadow = state.shadow
        graphics_mode = state.graphics_mode
        if call.name == "arc_to" and graphics_mode != GM_ADVANCED:
            # The figure the recording DC builds: see _record_arc_to.
            a = call.kwargs
            right, bottom = self._inclusive(state, a["right"], a["bottom"])
            path = self._arc_path(
                state,
                (a["left"], a["top"], right, bottom),
                (a["start_x"], a["start_y"]),
                (a["end_x"], a["end_y"]),
                direction=state.arc_direction,
                radial_box=(a["left"], a["top"], a["right"], a["bottom"]),
                inside_frame=True,
            )
            if path is None:
                return
            try:
                if not shadow._state.path:
                    shadow._state.position = state.position
                    shadow._state.device_position = state.device_position
                    shadow._state.fixed_position = state.fixed_position
                shadow.mapping = deepcopy(state.mapping)
                shadow._stroke_from_position(
                    path,
                    self._floor_logical(state, path.commands[-1][-1]),
                    cached=state.fixed_position is None,
                )
            except InvalidOperation:
                pass  # The call failed before changing the path, as natively.
            except UnsupportedOperation:
                state.shadow = None
            return
        if call.name == "angle_arc" and graphics_mode != GM_ADVANCED:
            graphics_mode = GM_ADVANCED
        try:
            self._shadow_pen(state)
            shadow.mapping = deepcopy(state.mapping)
            shadow.mapping.graphics_mode = graphics_mode
            if not shadow._state.path:
                # The path starts at the DC's current position; afterwards the
                # shadow keeps its own, so figures continue across curves.
                shadow._state.position = state.position
                shadow._state.device_position = state.device_position
                shadow._state.fixed_position = state.fixed_position
            shadow._state.arc_direction = state.arc_direction
            shadow.invoke(call)
        except InvalidOperation:
            pass  # The call failed before changing the path, as natively.
        except UnsupportedOperation:
            state.shadow = None

    def _record_close_figure(self, a, state, records):
        records.append(fixed.CloseFigure())
        if state.recording_path and state.figures:
            state.figures[-1] = (state.figures[-1][0], True)

    def _record_flatten_path(self, a, state, records):
        records.append(fixed.FlattenPath())  # Traced figures are already flat.

    def _record_widen_path(self, a, state, records):
        records.append(fixed.WidenPath())
        shadow = state.shadow
        if shadow is None:
            state.widened = True
            return
        try:
            # The shadow DC widens the path with the selected pen, as natively.
            self._shadow_pen(state)
            shadow.mapping = deepcopy(state.mapping)
            shadow.mapping.graphics_mode = state.graphics_mode
            shadow.set_miter_limit(state.miter_limit)
            shadow.widen_path()
        except InvalidOperation:
            return  # WidenPath failed and left the path as it was.
        except UnsupportedOperation:
            state.shadow = None
        state.widened = True

    def _clip_path_box(self, state) -> Rect | None:
        """The bounding box of the region SelectClipPath makes from the path.

        A path, widened or not, is filled by the polygon fill mode. None for a
        path without figures, which makes no region and keeps the clip.
        """
        figures = state.figures
        if figures is None and not state.widened and state.shadow is not None:
            # Shapes and arcs: the shadow DC's flattened figures, closed.
            figures = [(list(path.flattened().vertices), True) for path in state.shadow._path_figures(close=True)]
        if state.widened:
            # The shadow DC's widened outlines, filled with the DC's polygon
            # fill mode, as any clip path.
            if state.shadow is None:
                raise UnsupportedOperation("SelectClipPath of this widened path is not recorded")
            contours = tuple(
                list(path.flattened().vertices) for path in state.shadow._path_figures(close=True) if path.vertices
            )
            if not contours:
                return None
            xs = [x for points in contours for x, _ in points]
            ys = [y for points in contours for _, y in points]
            left, top, right, bottom = min(xs) // 16 - 1, min(ys) // 16 - 1, max(xs) // 16 + 2, max(ys) // 16 + 2
            spans = coverage_spans(contours, left, top, right, bottom, fill_mode=state.fill_mode)
            return _region_box(spans, contours)
        if figures is None:
            raise UnsupportedOperation("SelectClipPath of this path is not recorded")
        figures = [(points, closed) for points, closed in figures if points]
        if not figures:
            return None
        xs = [x for points, _ in figures for x, _ in points]
        ys = [y for points, _ in figures for _, y in points]
        margin = 16 * (abs(state.pen.width) * max(1, max(abs(v) for v in state.mapping.linear_scale)) + 4)
        left, top = (min(xs) - margin) // 16, (min(ys) - margin) // 16
        right, bottom = (max(xs) + margin) // 16 + 1, (max(ys) + margin) // 16 + 1
        contours = tuple(list(points) for points, _ in figures)
        spans = coverage_spans(contours, left, top, right, bottom, fill_mode=state.fill_mode)
        return _region_box(spans, contours)

    def _record_end_path(self, a, state, records):
        records.append(fixed.EndPath())
        state.recording_path = False

    def _record_abort_path(self, a, state, records):
        records.append(fixed.AbortPath())
        state.recording_path, state.path = False, None

    def _consume_path(self, state, records, record_type):
        records.append(record_type(*(state.path or (0, 0, -1, -1))))
        self._draw(state, state.path)
        state.path = None

    def _record_fill_path(self, a, state, records):
        self._consume_path(state, records, fixed.FillPath)

    def _record_stroke_path(self, a, state, records):
        self._consume_path(state, records, fixed.StrokePath)

    def _record_stroke_and_fill_path(self, a, state, records):
        self._consume_path(state, records, fixed.StrokeAndFillPath)

    def _record_select_clip_path(self, a, state, records):
        box = self._clip_path_box(state)
        records.append(fixed.SelectClipPath(a["mode"]))
        if box is not None:
            self._combine_clip(state, box, a["mode"])
        state.path, state.figures, state.shadow = None, [], None

    # Regions and clipping

    def _region(self, state, handle) -> RegionGeometry:
        return self._object(state, handle).region

    def _region_bounds(self, geometry: RegionGeometry) -> Rect:
        box = _union(None, None)
        for left, top, right, bottom in geometry.rectangles:
            box = _union(box, (left, top, right - 1, bottom - 1))
        return box or (0, 0, -1, -1)

    def _clip_rect(self, state, a) -> Rect:
        return self._device_rect(state, a["left"], a["top"], a["right"], a["bottom"])

    def _record_intersect_clip_rect(self, a, state, records):
        records.append(fixed.IntersectClipRect(a["left"], a["top"], a["right"], a["bottom"]))
        rect = self._clip_rect(state, a)
        state.clip = rect if state.clip is None else (_intersection(state.clip, rect) or (0, 0, -1, -1))

    def _record_exclude_clip_rect(self, a, state, records):
        """The clip box becomes the bounding box of what the exclusion leaves."""
        records.append(fixed.ExcludeClipRect(a["left"], a["top"], a["right"], a["bottom"]))
        width, height = self.device.pixels
        box = state.clip or (0, 0, width - 1, height - 1)
        hole = self._clip_rect(state, a)
        left, top, right, bottom = box
        pieces = (
            (left, top, right, hole[1] - 1),
            (left, hole[3] + 1, right, bottom),
            (left, max(top, hole[1]), hole[0] - 1, min(bottom, hole[3])),
            (hole[2] + 1, max(top, hole[1]), right, min(bottom, hole[3])),
        )
        remaining = None
        for piece in pieces:
            piece = _intersection(piece, box) if piece[0] <= piece[2] and piece[1] <= piece[3] else None
            remaining = _union(remaining, piece)
        state.clip = remaining or (0, 0, -1, -1)

    def _record_offset_clip_region(self, a, state, records):
        records.append(fixed.OffsetClipRgn(a["x"], a["y"]))
        if state.clip is not None:
            dx, dy = (round(value) for value in state.mapping.clip_displacement(a["x"], a["y"]))
            left, top, right, bottom = state.clip
            state.clip = (left + dx, top + dy, right + dx, bottom + dy)

    def _combine_clip(self, state, box: Rect | None, mode: int) -> None:
        if mode == RGN_COPY:
            state.clip = box
        elif mode == 1:  # RGN_AND
            if state.clip is None:
                state.clip = box
            elif box is not None:
                state.clip = _intersection(state.clip, box) or (0, 0, -1, -1)
        elif mode in (2, 3) and state.clip is not None:  # RGN_OR, RGN_XOR
            state.clip = None if box is None else _union(state.clip, box)

    def _record_select_clip_region(self, a, state, records):
        self._record_ext_select_clip_region({"region": a["region"], "mode": RGN_COPY}, state, records)

    def _record_ext_select_clip_region(self, a, state, records):
        if a["region"] is None:
            records.append(variable.ExtSelectClipRgn(a["mode"], b""))
            if a["mode"] == RGN_COPY:
                state.clip = None
            return
        geometry = self._region(state, a["region"])
        records.append(variable.ExtSelectClipRgn(a["mode"], region_data(geometry.rectangles)))
        bounds = self._region_bounds(geometry)
        self._combine_clip(state, bounds if bounds[0] <= bounds[2] else (0, 0, -1, -1), a["mode"])

    def _record_fill_region(self, a, state, records):
        geometry = self._region(state, a["region"])
        brush = self._slot(state, self._object(state, a["brush"]), records)
        bounds = self._region_bounds(geometry)
        records.append(variable.FillRgn(bounds=bounds, brush=brush, region=region_data(geometry.rectangles)))
        self._draw(state, bounds)

    def _record_frame_region(self, a, state, records):
        geometry = self._region(state, a["region"])
        brush = self._slot(state, self._object(state, a["brush"]), records)
        bounds = self._region_bounds(geometry)
        records.append(
            variable.FrameRgn(
                bounds=bounds,
                brush=brush,
                width=a["width"],
                height=a["height"],
                region=region_data(geometry.rectangles),
            )
        )
        self._draw(state, bounds)

    def _record_paint_region(self, a, state, records):
        geometry = self._region(state, a["region"])
        bounds = self._region_bounds(geometry)
        records.append(variable.PaintRgn(bounds=bounds, region=region_data(geometry.rectangles)))
        self._draw(state, bounds)

    def _record_invert_region(self, a, state, records):
        geometry = self._region(state, a["region"])
        bounds = self._region_bounds(geometry)
        records.append(variable.InvertRgn(bounds=bounds, region=region_data(geometry.rectangles)))
        self._draw(state, bounds)

    # Transfers

    def _transfer_bounds(self, state, x, y, width, height) -> Rect:
        return self._device_rect(state, x, y, x + width, y + height)

    def _blit(self, cls, a, state, records, *, source=True, extra=None, mask=None):
        bounds = self._clipped(state, self._transfer_bounds(state, a["x"], a["y"], a["width"], a["height"]))
        values = dict.fromkeys(cls.fields, 0)
        values |= dict(
            zip(("bounds_left", "bounds_top", "bounds_right", "bounds_bottom"), bounds or (0, 0, -1, -1), strict=True)
        )
        values |= {key: a[key] for key in ("x", "y", "width", "height")}
        values |= {"src_m11": 1.0, "src_m22": 1.0}
        values |= extra or {}
        blocks = ()
        if source and a.get("source") is not None:
            values |= {"src_x": a["src_x"], "src_y": a["src_y"], "background": _source_background(a["source"], state)}
            blocks = (device_bitmap(a["source"]), mask)
        records.append(_offset_record(cls, values, *blocks))
        self._draw(state, bounds)

    def _record_pat_blt(self, a, state, records):
        self._blit(bitmaps.BitBlt, a, state, records, source=False, extra={"rop": a["rop"]})

    def _record_bit_blt(self, a, state, records):
        """A legacy-bitmap BitBlt as a recording DC sees it (see ``_legacy_source``); without a source, PatBlt."""
        if a["source"] is None:
            self._record_pat_blt(a, state, records)
            return
        source = _legacy_source(a["source"])
        if source is not None:
            self._record_dib_bit_blt({**a, "source": source}, state, records)

    def _record_stretch_blt(self, a, state, records):
        """A legacy-bitmap StretchBlt as a recording DC sees it (see ``_legacy_source``); without a source, PatBlt."""
        if a["source"] is None:
            self._record_pat_blt(a, state, records)
            return
        source = _legacy_source(a["source"])
        if source is not None:
            self._record_dib_stretch_blt({**a, "source": source}, state, records)

    def _record_escape(self, a, state, records):
        pass  # An EMF DC records no escape, MFCOMMENT included; comments come from GdiComment.

    def _record_gdi_comment(self, a, state, records):
        records.append(variable.Comment(a["data"]))

    def _record_set_mapper_flags(self, a, state, records):
        pass  # A recording DC keeps no mapper flags.

    def _record_set_font_xform(self, a, state, records):
        pass  # Playback's per-record font scales; a recording DC derives its own.

    def _record_dib_bit_blt(self, a, state, records):
        self._blit(bitmaps.BitBlt, a, state, records, extra={"rop": a["rop"]})

    def _record_dib_stretch_blt(self, a, state, records):
        sizes = {"src_width": a["src_width"], "src_height": a["src_height"], "rop": a["rop"]}
        self._blit(bitmaps.StretchBlt, a, state, records, extra=sizes)

    def _record_alpha_blend(self, a, state, records):
        sizes = {"src_width": a["src_width"], "src_height": a["src_height"], "blend": a["blend"]}
        self._blit(bitmaps.AlphaBlend, a, state, records, extra=sizes)

    def _record_transparent_blt(self, a, state, records):
        sizes = {"src_width": a["src_width"], "src_height": a["src_height"], "transparent": a["transparent"]}
        self._blit(bitmaps.TransparentBlt, a, state, records, extra=sizes)

    def _record_mask_blt(self, a, state, records):
        if a["source"] is None:
            return  # Native recording writes nothing for a source-less MaskBlt.
        mask = mask_bitmap(a["mask"]) if a["mask"] is not None else None
        if mask is False:
            return  # GDI fails a MaskBlt whose mask is not a 1-bpp bitmap.
        extra = {"rop": a["rop"], "mask_x": a["mask_x"], "mask_y": a["mask_y"], "mask_usage": 2}
        if a.get("src_size") is not None:
            # A stretched source is a scaling source transform.
            extra |= {"src_m11": a["src_size"][0] / a["width"], "src_m22": a["src_size"][1] / a["height"]}
        self._blit(bitmaps.MaskBlt, a, state, records, extra=extra, mask=mask)

    def _record_plg_blt(self, a, state, records):
        (x0, y0), (x1, y1), (x2, y2) = a["points"]
        corners = ((x0, y0), (x1, y1), (x2, y2), (x1 + x2 - x0, y1 + y2 - y0))
        box = self._device_box(state, corners)
        bounds = self._clipped(state, (box[0], box[1], box[2] - 1, box[3] - 1))
        values = dict.fromkeys(bitmaps.PlgBlt.fields, 0)
        values |= dict(
            zip(("bounds_left", "bounds_top", "bounds_right", "bounds_bottom"), bounds or (0, 0, -1, -1), strict=True)
        )
        values |= {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "x2": x2, "y2": y2}
        values |= {key: a[key] for key in ("src_x", "src_y", "src_width", "src_height", "mask_x", "mask_y")}
        values |= {"src_m11": 1.0, "src_m22": 1.0, "mask_usage": 2}
        values["background"] = _source_background(a["source"], state)
        mask = mask_bitmap(a["mask"]) if a["mask"] is not None else None
        if mask is False:
            return  # GDI fails a PlgBlt whose mask is not a 1-bpp bitmap.
        records.append(_offset_record(bitmaps.PlgBlt, values, device_bitmap(a["source"]), mask))
        self._draw(state, bounds)

    def _record_set_dib_to_device(self, a, state, records):
        # A packed DIB is recorded as given.
        layout = read_dib(a["source"], color_usage=a["color_usage"])
        info, bits = a["source"].data[: layout.offset], a["source"].data[layout.offset :]
        bounds = self._clipped(state, self._transfer_bounds(state, a["x"], a["y"], a["width"], a["height"]))
        values = dict.fromkeys(bitmaps.SetDIBitsToDevice.fields, 0)
        values |= dict(
            zip(("bounds_left", "bounds_top", "bounds_right", "bounds_bottom"), bounds or (0, 0, -1, -1), strict=True)
        )
        values |= {"x": a["x"], "y": a["y"], "src_x": a["src_x"], "src_y": a["src_y"]}
        values |= {"src_width": a["width"], "src_height": a["height"], "usage": a["color_usage"]}
        values |= {"start_scan": a["start_scan"], "scan_count": a["scan_count"]}
        records.append(_offset_record(bitmaps.SetDIBitsToDevice, values, (info, bits)))
        self._draw(state, bounds)

    def _record_gradient_fill(self, a, state, records):
        vertices = tuple(tuple(vertex) for vertex in a["vertices"])
        box = self._device_box(state, ((x, y) for x, y, *_ in vertices))
        bounds = self._clipped(state, (box[0], box[1], box[2] - 1, box[3] - 1) if box else None)
        meshes = tuple(tuple(mesh) for mesh in a["meshes"])
        records.append(variable.GradientFill(bounds or (0, 0, -1, -1), a["mode"], vertices, meshes))
        self._draw(state, bounds)

    def _record_stretch_dib(self, a, state, records):
        data = a["source"].data
        layout = read_dib(a["source"])
        info, bits = data[: layout.offset], data[layout.offset :]
        bounds = self._transfer_bounds(state, a["x"], a["y"], a["width"], a["height"])
        cls = bitmaps.StretchDIBits
        offset = 8 + struct.calcsize("<" + cls.wire_layout)
        records.append(
            cls(
                *bounds,
                a["x"],
                a["y"],
                a["src_x"],
                a["src_y"],
                a["src_width"],
                a["src_height"],
                offset,
                len(info),
                offset + len(info),
                len(bits),
                a["color_usage"],
                a["rop"],
                a["width"],
                a["height"],
                info + bits,
            )
        )
        self._draw(state, bounds)

    # Output ------------------------------------------------------------------

    @property
    def bounds(self) -> Rect:
        """The inclusive device bounds of everything recorded, or (0, 0, -1, -1)."""
        return self._state.bounds or (0, 0, -1, -1)

    def frame(self) -> Rect:
        """The picture frame native recording derives from the bounds, in 0.01 mm."""
        (width, height), (mm_x, mm_y) = self.device.pixels, self.device.millimetres
        left, top, right, bottom = self.bounds
        scale_x, scale_y = mm_x * 100 / width, mm_y * 100 / height
        return tuple(
            floor(value * scale + 0.5)
            for value, scale in zip((left, top, right, bottom), (scale_x, scale_y, scale_x, scale_y), strict=True)
        )

    def metafile(self, *, frame: Rect | None = None, description: str | None = None) -> Metafile:
        result = Metafile.build(
            (*self.records, variable.Eof(tuple(self._state.colours))),
            bounds=self.bounds,
            frame=self.frame() if frame is None else frame,
            device=self.device,
            description=description,
        )
        if self.micrometres is None:
            return result
        extra = bytearray(result.header.extra)
        extra[12:20] = struct.pack("<2i", *self.micrometres)
        return replace(result, header=replace(result.header, extra=bytes(extra)))

    def to_bytes(self, *, frame: Rect | None = None, description: str | None = None) -> bytes:
        return self.metafile(frame=frame, description=description).to_bytes()


# Recording-DC state that SaveDC and RestoreDC carry.
# Calls that build the open path, which the shadow DC follows.
_PATH_CALLS = frozenset(
    (
        "move_to",
        "line_to",
        "polyline",
        "polyline_to",
        "polygon",
        "poly_polygon",
        "poly_polyline",
        "poly_bezier",
        "poly_bezier_to",
        "poly_draw",
        "rectangle",
        "ellipse",
        "round_rect",
        "arc",
        "arc_to",
        "chord",
        "pie",
        "angle_arc",
        "close_figure",
        "end_path",
        "flatten_path",
    )
)

MFCOMMENT = 15
# The reference display's colour depth.
REFERENCE_BITS = 32
# A memory DC's default bitmap: 1x1, monochrome, black.
DEFAULT_MEMORY_BITMAP = BitmapData(
    "dib",
    struct.pack("<IiiHHIIiiII", 40, 1, 1, 1, 1, 0, 4, 0, 0, 0, 0) + bytes((0, 0, 0, 0, 255, 255, 255, 0, 0, 0, 0, 0)),
)


def _legacy_source(bitmap: BitmapData) -> BitmapData | None:
    """The source a recording DC transfers from a legacy (Bitmap16) bitmap.

    The bitmap is selected into a memory DC compatible with the recording
    DC. A monochrome or reference-depth bitmap selects, and the transfer then
    records nothing; any other depth fails to select, so the transfer reads
    the memory DC's default bitmap.
    """
    if read_bitmap16(bitmap).depth in (1, REFERENCE_BITS):
        return None
    return DEFAULT_MEMORY_BITMAP


_SAVED = (
    "mapping",
    "graphics_mode",
    "pen",
    "position",
    "fixed_position",
    "device_position",
    "clip",
    "miter_limit",
    "brush_null",
    "background",
    "arc_direction",
    "font",
    "text_alignment",
    "background_mode",
    "character_extra",
    "justification",
    "text_position",
)

_SIMPLE = {
    "save_dc": lambda a: fixed.SaveDC(),
    "restore_dc": lambda a: fixed.RestoreDC(a["saved_dc"]),
    "realize_palette": lambda a: fixed.RealizePalette(),
    "set_background_mode": lambda a: fixed.SetBkMode(a["mode"]),
    "set_rop2": lambda a: fixed.SetROP2(a["mode"]),
    "set_stretch_mode": lambda a: fixed.SetStretchBltMode(a["mode"]),
    "set_text_alignment": lambda a: fixed.SetTextAlign(a["alignment"]),
    "set_text_color": lambda a: fixed.SetTextColor(a["color"]),
    "set_brush_origin": lambda a: fixed.SetBrushOrgEx(a["x"], a["y"]),
    "set_meta_region": lambda a: fixed.SetMetaRgn(),
    "set_layout": lambda a: fixed.SetLayout(a["layout"]),
    "set_color_adjustment": lambda a: fixed.SetColorAdjustment(
        24,
        a["flags"],
        a["illuminant"],
        a["red_gamma"],
        a["green_gamma"],
        a["blue_gamma"],
        a["black"],
        a["white"],
        a["contrast"],
        a["brightness"],
        a["colorfulness"],
        a["tint"],
    ),
}
