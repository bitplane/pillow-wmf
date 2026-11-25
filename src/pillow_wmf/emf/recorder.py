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

The recording DC starts in MM_TEXT and GM_COMPATIBLE on ``device``. Text,
palette editing, pattern brushes, DIB pattern pens and masked, blended or
parallelogram transfers are not yet recorded and are refused.
"""

from __future__ import annotations

import heapq
import struct
from copy import deepcopy
from dataclasses import dataclass, field, replace
from math import ceil, floor

from ..bitmap import read_dib
from ..constants import GM_ADVANCED, GM_COMPATIBLE, MM_TEXT, PS_INSIDEFRAME, PS_NULL
from ..ellipse import arc_figure
from ..gdi import Call, Handle, InvalidOperation, UnsupportedOperation
from ..limits import DEFAULT_LIMITS
from ..mapping import REFERENCE_DEVICE, Mapping, ReferenceDevice
from ..objects import FontRequest, RegionGeometry
from ..trace import TraceContext
from . import bitmaps, fixed, variable
from .file import Metafile
from .objects import FACE_NAME_BYTES, LogFont

STOCK_OBJECT = 0x80000000
DEFAULT_PALETTE = 15
NULL_PEN = 8
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
        raise UnsupportedOperation("EMF fonts record face names as text")
    encoded = name.encode("utf-16-le")[: FACE_NAME_BYTES - 2]
    values = {key: getattr(request, key) for key in LogFont.__dataclass_fields__ if key != "face_name"}
    return LogFont(**values, face_name=encoded.ljust(FACE_NAME_BYTES, b"\0"))


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


@dataclass
class _State:
    mapping: Mapping
    graphics_mode: int = GM_COMPATIBLE
    objects: dict[int, _Object] = field(default_factory=dict)
    free: list[int] = field(default_factory=list)
    capacity: int = 1
    pen: _Object = field(default_factory=lambda: _Object("pen"))
    position: tuple[int, int] = (0, 0)
    bounds: Rect | None = None
    path: Rect | None = None
    recording_path: bool = False
    miter_limit: float = 10.0
    # The clip region's inclusive device bounding box; None when unclipped.
    clip: Rect | None = None
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
    ):
        super().__init__(max_objects=max_objects, max_saved_states=max_saved_states, trace_calls=trace_calls)
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
            records.append(entry.create(entry.slot))
        return entry.slot

    # Geometry ----------------------------------------------------------------

    def _device(self, state: _State, x: int, y: int) -> tuple[int, int]:
        return state.mapping.device_point(x, y)

    def _device_box(self, state: _State, points) -> Rect | None:
        return _box(self._device(state, x, y) for x, y in points)

    def _device_rect(self, state: _State, left: int, top: int, right: int, bottom: int) -> Rect:
        """The inclusive device box of a logical box, as bounds count it.

        In GM_COMPATIBLE the device right and bottom edges are moved in by
        one pixel; in GM_ADVANCED the mapped edges are used as they are.
        """
        (x0, y0), (x1, y1) = self._device(state, left, top), self._device(state, right, bottom)
        if state.graphics_mode == GM_COMPATIBLE:
            x1, y1 = x1 - 1, y1 - 1
        return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    def _inclusive(self, state: _State, right: int, bottom: int) -> tuple[int, int]:
        """GM_COMPATIBLE box edges moved in by one device pixel, in logical units."""
        if state.graphics_mode != GM_COMPATIBLE:
            return right, bottom
        x, y = state.mapping.point(right, bottom)
        return state.mapping.logical_point(x - 1, y - 1)

    def _inflation(self, state: _State, *, frame: bool = False) -> int:
        """How far a stroke reaches past its figure's device bounds.

        Mitred strokes (Rectangle frames, and geometric pens with miter
        joins) reach the miter limit times the half width plus one; others
        reach the half width, rounded up, plus one. One-pixel pens add
        nothing.
        """
        pen = state.pen
        if pen.style == PS_NULL:
            return 0
        width = abs(pen.width * state.mapping.linear_scale[0])
        if width <= 1:
            return 0
        if frame or pen.miter:
            return floor(state.miter_limit * (width / 2 + 1))
        return ceil(width / 2) + 1

    def _stroked(self, state: _State, box: Rect | None, *, frame: bool = False) -> Rect | None:
        if box is None:
            return None
        grow = self._inflation(state, frame=frame)
        return (box[0] - grow, box[1] - grow, box[2] + grow, box[3] + grow)

    def _draw(self, state: _State, box: Rect | None) -> None:
        """Account a drawn device box in the header bounds and any open path.

        The header only counts what the clip region lets through.
        """
        if box is None:
            return
        if state.clip is not None and not state.recording_path:
            box = _intersection(box, state.clip)
            if box is None:
                return
        if state.recording_path:
            state.path = _union(state.path, box)
        state.bounds = _union(state.bounds, box)

    # Translation -------------------------------------------------------------

    def _record(self, call: Call, state: _State) -> list:
        name, a = call.name, call.kwargs
        records: list = []
        simple = _SIMPLE.get(name)
        if simple is not None:
            records.append(simple(a))
            if name == "save_dc":
                state.saved.append(
                    (
                        deepcopy(state.mapping),
                        state.graphics_mode,
                        state.pen,
                        state.position,
                        state.clip,
                        state.miter_limit,
                    )
                )
            elif name == "restore_dc":
                level = a["saved_dc"]
                index = level - 1 if level > 0 else len(state.saved) + level
                if not 0 <= index < len(state.saved):
                    raise InvalidOperation("Invalid saved DC reference")
                (
                    state.mapping,
                    state.graphics_mode,
                    state.pen,
                    state.position,
                    state.clip,
                    state.miter_limit,
                ) = state.saved[index]
                del state.saved[index:]
            return records
        handler = getattr(self, f"_record_{name}", None)
        if handler is None:
            raise UnsupportedOperation(f"EMF recording of {name} is not yet supported")
        handler(a, state, records)
        return records

    # Objects

    def _created(self, state: _State, entry: _Object) -> None:
        # Preparation and application are sequential, so the next handle
        # serial is the one this creation will receive.
        state.objects[self._next_handle] = entry

    def _record_get_stock_object(self, a, state, records):
        from ..execution import STOCK_OBJECT_KINDS

        self._created(state, _Object(STOCK_OBJECT_KINDS[a["index"]], stock=a["index"]))

    def _record_create_pen(self, a, state, records):
        style, width, color = a["style"], a["width"], a["color"]
        if style & 15 == PS_NULL:
            # CreatePen returns the stock NULL_PEN for PS_NULL.
            self._created(state, _Object("pen", stock=NULL_PEN, style=PS_NULL))
            return
        self._created(
            state,
            _Object("pen", lambda slot: fixed.CreatePen(slot, style, width, 0, color), width=width, style=style & 15),
        )

    def _record_ext_create_pen(self, a, state, records):
        if a["bitmap"] is not None:
            raise UnsupportedOperation("EMF recording of DIB pattern pens is not yet supported")
        style, width, color, brush_style, hatch = (
            a[key] for key in ("style", "width", "color", "brush_style", "hatch")
        )
        entries = tuple(a["entries"])
        # LOGPENEX always carries one style entry, used or not.
        offset = 8 + struct.calcsize("<" + bitmaps.ExtCreatePen.wire_layout) + 4 + 4 * max(1, len(entries))
        padding = b"" if entries else bytes(4)

        def create(slot):
            return bitmaps.ExtCreatePen(
                slot, offset, 0, offset, 0, style, width, brush_style, color, hatch, entries, padding
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
            ),
        )

    def _record_create_brush(self, a, state, records):
        style, color, hatch = a["style"], a["color"], a["hatch"]
        self._created(state, _Object("brush", lambda slot: fixed.CreateBrushIndirect(slot, style, color, hatch)))

    def _record_create_font(self, a, state, records):
        font = _log_font(a["font"])
        self._created(state, _Object("font", lambda slot: variable.ExtCreateFontIndirectW(slot, font)))

    def _record_create_palette(self, a, state, records):
        entries = a["palette"].entries if a["palette"] is not None else ()
        self._created(state, _Object("palette", lambda slot: variable.CreatePalette(slot, entries, 0x300)))

    def _record_create_region(self, a, state, records):
        self._created(state, _Object("region", region=a["region"] or RegionGeometry()))

    def _record_select_object(self, a, state, records):
        handle = a["handle"]
        if handle is None:
            raise UnsupportedOperation("A null object selection has no EMF record")
        entry = self._object(state, handle)
        if entry.kind == "region":
            self._record_ext_select_clip_region({"region": handle, "mode": RGN_COPY}, state, records)
            return
        records.append(fixed.SelectObject(self._slot(state, entry, records)))
        if entry.kind == "pen":
            state.pen = entry

    def _record_select_palette(self, a, state, records):
        handle = a["handle"]
        if handle is None:
            raise UnsupportedOperation("A null palette selection has no EMF record")
        records.append(fixed.SelectPalette(self._slot(state, self._object(state, handle), records)))

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

    def _record_set_miter_limit(self, a, state, records):
        # Native recording truncates the float limit to the record's integer.
        if not a["limit"] >= 1:
            raise InvalidOperation("Miter limits are at least 1")
        records.append(fixed.SetMiterLimit(int(a["limit"])))
        state.miter_limit = float(a["limit"])

    def _record_set_world_transform(self, a, state, records):
        if state.graphics_mode != GM_ADVANCED:
            raise InvalidOperation("World transforms require GM_ADVANCED")
        values = tuple(a[key] for key in ("m11", "m12", "m21", "m22", "dx", "dy"))
        state.mapping.world = values
        records.append(fixed.SetWorldTransform(*values))

    # Drawing

    def _record_box(self, a, state, records, record_type, *extra):
        left, top = a["left"], a["top"]
        right, bottom = self._inclusive(state, a["right"], a["bottom"])
        records.append(record_type(left, top, right, bottom, *extra))
        box = self._device_rect(state, left, top, a["right"], a["bottom"])
        if state.pen.style == PS_NULL:
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
        start, end = (a["start_x"], a["start_y"]), (a["end_x"], a["end_y"])
        records.append(record_type(left, top, right, bottom, *start, *end))
        x0, y0, x1, y1 = self._device_rect(state, left, top, a["right"], a["bottom"])
        closure = {fixed.Arc: "open", fixed.ArcTo: "open", fixed.Chord: "chord", fixed.Pie: "pie"}[record_type]
        figure = arc_figure(
            x0,
            y0,
            x1 + 1,
            y1 + 1,
            self._device(state, *start),
            self._device(state, *end),
            closure=closure,
            radial_bounds=(x0, y0, x1 + 1, y1 + 1),
        )
        box = _box(((x + 15) // 16, (y + 15) // 16) for command in figure.commands for x, y in command)
        if record_type is fixed.ArcTo:
            box = _union(box, self._device_box(state, (state.position,)))
        self._draw(state, self._stroked(state, box))

    def _record_arc(self, a, state, records):
        self._radial(a, state, records, fixed.Arc)

    def _record_chord(self, a, state, records):
        self._radial(a, state, records, fixed.Chord)

    def _record_pie(self, a, state, records):
        self._radial(a, state, records, fixed.Pie)

    def _record_arc_to(self, a, state, records):
        self._radial(a, state, records, fixed.ArcTo)

    def _record_move_to(self, a, state, records):
        records.append(fixed.MoveToEx(a["x"], a["y"]))
        state.position = (a["x"], a["y"])

    def _record_line_to(self, a, state, records):
        records.append(fixed.LineTo(a["x"], a["y"]))
        self._draw(state, self._stroked(state, self._device_box(state, (state.position, (a["x"], a["y"])))))
        state.position = (a["x"], a["y"])

    def _points(self, a, state, records, wide, narrow, *, key="points", to=False):
        points = tuple(tuple(point) for point in a[key])
        bounds = self._stroked(state, self._device_box(state, points))
        record_type = narrow if _fits16(points) else wide
        extra = (a["types"],) if "types" in a else ()
        records.append(record_type(bounds or (0, 0, -1, -1), points, *extra))
        self._draw(state, self._stroked(state, self._device_box(state, (state.position, *points))) if to else bounds)
        if to and points:
            state.position = points[-1]

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
        flat = tuple(point for figure in figures for point in figure)
        bounds = self._stroked(state, self._device_box(state, flat))
        record_type = narrow if _fits16(flat) else wide
        records.append(record_type(bounds or (0, 0, -1, -1), figures))
        self._draw(state, bounds)

    def _record_poly_polygon(self, a, state, records):
        self._figures(a["polygons"], state, records, variable.PolyPolygon, variable.PolyPolygon16)

    def _record_poly_polyline(self, a, state, records):
        self._figures(a["polylines"], state, records, variable.PolyPolyline, variable.PolyPolyline16)

    def _record_angle_arc(self, a, state, records):
        x, y, radius = a["x"], a["y"], a["radius"]
        records.append(fixed.AngleArc(x, y, radius, a["start"], a["sweep"]))
        box = self._device_box(state, ((x - radius, y - radius), (x + radius, y + radius)))
        self._draw(state, self._stroked(state, box))

    def _record_set_pixel(self, a, state, records):
        records.append(fixed.SetPixelV(a["x"], a["y"], a["color"]))
        self._draw(state, self._device_box(state, ((a["x"], a["y"]),)))

    def _record_flood_fill(self, a, state, records):
        records.append(fixed.ExtFloodFill(a["x"], a["y"], a["color"], FLOODFILLBORDER))

    def _record_ext_flood_fill(self, a, state, records):
        records.append(fixed.ExtFloodFill(a["x"], a["y"], a["color"], a["mode"]))

    # Paths

    def _record_begin_path(self, a, state, records):
        records.append(fixed.BeginPath())
        state.recording_path, state.path = True, None

    def _record_end_path(self, a, state, records):
        records.append(fixed.EndPath())
        state.recording_path = False

    def _record_abort_path(self, a, state, records):
        records.append(fixed.AbortPath())
        state.recording_path, state.path = False, None

    def _consume_path(self, state, records, record_type):
        records.append(record_type(*(state.path or (0, 0, -1, -1))))
        state.path = None

    def _record_fill_path(self, a, state, records):
        self._consume_path(state, records, fixed.FillPath)

    def _record_stroke_path(self, a, state, records):
        self._consume_path(state, records, fixed.StrokePath)

    def _record_stroke_and_fill_path(self, a, state, records):
        self._consume_path(state, records, fixed.StrokeAndFillPath)

    def _record_select_clip_path(self, a, state, records):
        records.append(fixed.SelectClipPath(a["mode"]))
        self._combine_clip(state, state.path or (0, 0, -1, -1), a["mode"])
        state.path = None

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
        # Excluding a rectangle can only shrink the box; it is kept as is.
        records.append(fixed.ExcludeClipRect(a["left"], a["top"], a["right"], a["bottom"]))

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

    def _record_pat_blt(self, a, state, records):
        bounds = self._transfer_bounds(state, a["x"], a["y"], a["width"], a["height"])
        values = dict.fromkeys(bitmaps.BitBlt.fields, 0)
        values |= dict(zip(("bounds_left", "bounds_top", "bounds_right", "bounds_bottom"), bounds, strict=True))
        values |= {key: a[key] for key in ("x", "y", "width", "height", "rop")}
        values |= {"src_m11": 1.0, "src_m22": 1.0}
        records.append(bitmaps.BitBlt(**values, data=b""))
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
            self.records,
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


_SIMPLE = {
    "save_dc": lambda a: fixed.SaveDC(),
    "restore_dc": lambda a: fixed.RestoreDC(a["saved_dc"]),
    "realize_palette": lambda a: fixed.RealizePalette(),
    "set_background_mode": lambda a: fixed.SetBkMode(a["mode"]),
    "set_polygon_fill_mode": lambda a: fixed.SetPolyFillMode(a["mode"]),
    "set_rop2": lambda a: fixed.SetROP2(a["mode"]),
    "set_stretch_mode": lambda a: fixed.SetStretchBltMode(a["mode"]),
    "set_text_alignment": lambda a: fixed.SetTextAlign(a["alignment"]),
    "set_text_color": lambda a: fixed.SetTextColor(a["color"]),
    "set_background_color": lambda a: fixed.SetBkColor(a["color"]),
    "set_mapper_flags": lambda a: fixed.SetMapperFlags(a["flags"]),
    "set_arc_direction": lambda a: fixed.SetArcDirection(a["direction"]),
    "set_brush_origin": lambda a: fixed.SetBrushOrgEx(a["x"], a["y"]),
    "set_meta_region": lambda a: fixed.SetMetaRgn(),
    "set_layout": lambda a: fixed.SetLayout(a["layout"]),
    "set_text_justification": lambda a: fixed.SetTextJustification(a["break_extra"], a["break_count"]),
    "close_figure": lambda a: fixed.CloseFigure(),
    "flatten_path": lambda a: fixed.FlattenPath(),
    "widen_path": lambda a: fixed.WidenPath(),
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
