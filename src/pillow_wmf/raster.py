"""GDI rasterization into a Pillow RGB image."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from fractions import Fraction

from .binary import FormatError, ResourceLimitError
from .bitmap import DEFAULT_MAX_BITMAP_PIXELS, read_dib
from .bitmap16 import read_bitmap16
from .blit import StretchAxis
from .clip import RegionMask, region_outlines
from .color_adjustment import ColorAdjustment
from .constants import (
    ALTERNATE,
    BLACKONWHITE,
    BS_HATCHED,
    BS_NULL,
    BS_PATTERN,
    BS_SOLID,
    COLORONCOLOR,
    ETO_CLIPPED,
    ETO_GLYPH_INDEX,
    ETO_NUMERICSLATIN,
    ETO_NUMERICSLOCAL,
    ETO_OPAQUE,
    ETO_PDY,
    ETO_RTLREADING,
    FLOODFILLBORDER,
    FLOODFILLSURFACE,
    GM_ADVANCED,
    GM_COMPATIBLE,
    HALFTONE,
    MM_ANISOTROPIC,
    MM_TEXT,
    OPAQUE,
    PS_ALTERNATE,
    PS_INSIDEFRAME,
    PS_NULL,
    PS_SOLID,
    PS_USERSTYLE,
    R2_BLACK,
    R2_NOP,
    R2_NOT,
    R2_WHITE,
    TA_UPDATECP,
    WHITEONBLACK,
    WINDING,
)
from .dbcs import DecodedText
from .ellipse import (
    advanced_arc,
    advanced_ellipse_cubics,
    arc_figure,
    box_corners,
    corner_ellipse_cubics,
    ellipse_cubics,
    inside_frame_bounds,
    round_rect_figure,
)
from .execution import CREATED_KINDS, ExecutionContext
from .gdi import Call, Handle, InvalidOperation, UnsupportedOperation
from .geometry import DEFAULT_MAX_GEOMETRY_POINTS, DevicePath, GeometryBudget, Polygon, coverage_spans
from .gradient import mesh_triangles
from .limits import DEFAULT_LIMITS
from .mapping import IDENTITY_TRANSFORM, Mapping
from .numeric import float32
from .objects import EncodedText, FontRequest, GlyphIndices, UnicodeText
from .paint import pattern_rop2
from .palette import DEFAULT_COLORS, LogicalPalette, PaletteIndex
from .raster_paint import RasterPainter
from .raster_state import Brush as Brush
from .raster_state import DrawingState
from .raster_state import Pen as Pen
from .raster_state import SavedDC as SavedDC
from .raster_state import TextState as TextState
from .stroke import frame_footprint
from .surface import Surface
from .text import FontCollection
from .text_layout import TextLayout, layout_text
from .text_math import text_rotation
from .text_transform import TransformedFont, baseline_vector, decoration_areas, opaque_area, place_run
from .transfer import SourceTransfer as SourceTransfer
from .transfer import TransferAction as TransferAction
from .transfer import TransferPreparation, accepts_dib


def rgb(colorref: int) -> tuple[int, int, int]:
    return colorref & 255, (colorref >> 8) & 255, (colorref >> 16) & 255


# Geometric predefined styles, in multiples of the pen width.
GEOMETRIC_DASHES = {1: (3, 1), 2: (1, 1), 3: (3, 1, 1, 1), 4: (3, 1, 1, 1, 1, 1)}
BS_DIBPATTERN, BS_DIBPATTERNPT = 5, 6


def logical_color(colorref):
    # PALETTEINDEX is a flag, not an exclusive high-byte value. Other high
    # bits do not cancel it, including sign-extended colours in legacy files.
    return PaletteIndex(colorref & 65535) if colorref & 0x01000000 else rgb(colorref)


# MS-WMF's defined escape records are printer operations or embedded metadata.
# They do not affect the native RGB memory device. Keep the verified set
# explicit: other escape numbers, including callbacks and XPS, are unsupported.
BITMAP_NOOP_ESCAPES = frozenset(
    {
        0x0001,  # NEWFRAME
        0x0002,  # ABORTDOC
        0x0003,  # NEXTBAND
        0x0004,  # SETCOLORTABLE
        0x0005,  # GETCOLORTABLE
        0x0008,  # QUERYESCSUPPORT
        0x000A,  # STARTDOC
        0x000B,  # ENDDOC
        0x000C,  # GETPHYSPAGESIZE
        0x000D,  # GETPRINTINGOFFSET
        0x000E,  # GETSCALINGFACTOR
        0x000F,  # META_ESCAPE_ENHANCED_METAFILE
        0x0011,  # SETCOPYCOUNT
        0x0013,  # PASSTHROUGH
        0x0015,  # SETLINECAP
        0x0016,  # SETLINEJOIN
        0x0017,  # SETMITERLIMIT
        0x0019,  # DRAWPATTERNRECT
        0x0021,  # EPSPRINTING
        0x0025,  # POSTSCRIPT_DATA
        0x0026,  # POSTSCRIPT_IGNORE
        0x002A,  # GETDEVICEUNITS
        0x0100,  # GETEXTENDEDTEXTMETRICS
        0x0102,  # GETPAIRKERNTABLE
        0x0200,  # EXTTEXTOUT (escape, not META_EXTTEXTOUT)
        0x0201,  # GETFACENAME
        0x0202,  # DOWNLOADFACE
        0x0801,  # METAFILE_DRIVER
        0x0C01,  # QUERYDIBSUPPORT
        0x1000,  # BEGIN_PATH
        0x1001,  # CLIP_TO_PATH
        0x1002,  # END_PATH
        0x100E,  # OPENCHANNEL
        0x100F,  # DOWNLOADHEADER
        0x1010,  # CLOSECHANNEL
        0x1013,  # POSTSCRIPT_PASSTHROUGH
        0x1014,  # ENCAPSULATED_POSTSCRIPT
        0x1015,  # POSTSCRIPT_IDENTIFY
        0x1016,  # POSTSCRIPT_INJECTION
        0x1017,  # CHECKJPEGFORMAT
        0x1018,  # CHECKPNGFORMAT
        0x1019,  # GET_PS_FEATURESETTING
        0x11D8,  # SPCLPASSTHROUGH2
    }
)


SRCCOPY = 0x00CC0020


# Operations whose GM_ADVANCED output has no native references yet. They
# raise rather than reuse GM_COMPATIBLE rules that may not match.
@dataclass(frozen=True)
class ParallelogramTransfer:
    """A source rectangle bound for a 28.4 parallelogram, with an optional mask test."""

    source: object
    corners: tuple
    rectangle: tuple[int, int, int, int]
    sample: object = None
    # Set for transfers made under a rotating transform, rather than PlgBlt.
    rop: int | None = None
    background_rop: int | None = None
    # ``blend(sample, destination, x, y)`` replaces the ROP for AlphaBlend and
    # TransparentBlt; ``x, y`` locate the sample and None leaves the pixel.
    blend: object = None


# Calls that stroke with the selected pen. Extended geometric pens build
# their outlines from axis-aligned scales, so they are refused when rotated.
PEN_STROKES = frozenset(
    {
        "arc",
        "chord",
        "ellipse",
        "line_to",
        "pie",
        "poly_bezier",
        "poly_bezier_to",
        "poly_draw",
        "poly_polygon",
        "poly_polyline",
        "polygon",
        "polyline",
        "polyline_to",
        "rectangle",
        "round_rect",
        "stroke_and_fill_path",
        "stroke_path",
    }
)

UNVERIFIED_IN_ADVANCED_MODE = frozenset(
    {
        "set_map_mode",
        "set_window_origin",
        "set_window_extent",
        "set_viewport_origin",
        "set_viewport_extent",
        "offset_window_origin",
        "offset_viewport_origin",
        "scale_window_extent",
        "scale_viewport_extent",
        "set_layout",
    }
)


def _round_half_away(value) -> int:
    magnitude = math.floor(abs(value) + 0.5)
    return magnitude if value >= 0 else -magnitude


def div255(value: int) -> int:
    """GDI's rounded division by 255."""
    return (value + 128 + ((value + 128) >> 8)) >> 8


def alpha_channel(source, destination, source_alpha, constant):
    """One channel of AlphaBlend's source-over with premultiplied alpha.

    The constant scales the source alpha, then both premultiplied terms are
    rounded separately; this matches native output with and without
    per-pixel alpha, at full and partial constant alpha.
    """
    if source_alpha is None:
        return div255(source * constant + destination * (255 - constant))
    alpha = div255(source_alpha * constant)
    return min(255, div255(source * constant) + div255(destination * (255 - alpha)))


class RasterContext(ExecutionContext[DrawingState]):
    """Draw the currently supported GDI calls into an RGB Pillow image.

    Unsupported modes and primitives raise rather than silently draw an
    approximate image. Playback with ``strict=True`` exposes that boundary.
    """

    def __init__(
        self,
        width: int,
        height: int,
        *,
        background=(255, 255, 255),
        max_bitmap_pixels: int = DEFAULT_MAX_BITMAP_PIXELS,
        max_geometry_points: int = DEFAULT_MAX_GEOMETRY_POINTS,
        max_objects: int = DEFAULT_LIMITS.max_objects,
        max_saved_states: int = DEFAULT_LIMITS.max_saved_states,
        trace_calls: bool = True,
        fonts: FontCollection | None = None,
    ):
        super().__init__(max_objects=max_objects, max_saved_states=max_saved_states, trace_calls=trace_calls)
        self._geometry_budget = GeometryBudget(max_geometry_points)
        self.surface = Surface(width, height, background)
        if max_bitmap_pixels < 0:
            raise ValueError("Bitmap pixel limit must be nonnegative")
        self.max_bitmap_pixels = max_bitmap_pixels
        self.fonts = fonts if fonts is not None else FontCollection()
        self._objects: dict[Handle, Pen | Brush | FontRequest | RegionMask | LogicalPalette | None] = {}
        self._state = DrawingState(
            Mapping(window_extent=(width, height), viewport_extent=(width, height), surface_width=width)
        )
        # The DC starts with the stock default palette selected.
        self._default_palette: LogicalPalette | None = self._state.palette
        self._font_xform = None

    @property
    def image(self):
        """The live canvas owned by ``surface``."""
        return self.surface.image

    @property
    def mapping(self):
        return self._state.mapping

    @mapping.setter
    def mapping(self, value):
        self._state.mapping = value

    def _point(self, x: int, y: int) -> tuple[int, int]:
        return self.mapping.device_point(x, y)

    def is_null_object(self, handle: Handle) -> bool:
        return handle.owner is self and handle in self._objects and self._objects[handle] is None

    def _clip_mask(self, region):
        if region is not None and self.mapping.rtl:
            return region.transformed(lambda x, y: (self.surface.width - x, y))
        return region

    def _region_point(self, x: int, y: int) -> tuple[int, int]:
        """Region corners: GM_ADVANCED takes the ceiling of each 28.4 coordinate."""
        if self.mapping.graphics_mode == GM_ADVANCED:
            return tuple((value + 15) // 16 for value in self.mapping.fixed_point(x, y))
        return self._point(x, y)

    def _path_point(self, x: int, y: int) -> tuple[int, int]:
        """A 28.4 path vertex: whole pixels in GM_COMPATIBLE, sixteenths in GM_ADVANCED."""
        if self.mapping.graphics_mode == GM_ADVANCED:
            return self.mapping.fixed_point(x, y)
        x, y = self._point(x, y)
        return x * 16, y * 16

    def _mapped_path(self, points) -> Polygon:
        return [self._path_point(x, y) for x, y in points]

    def _prepare_effect(self, call):
        """Preparation lives beside its handler; simple state calls need none."""
        if self.mapping.graphics_mode == GM_ADVANCED and call.name in UNVERIFIED_IN_ADVANCED_MODE:
            raise UnsupportedOperation(f"{call.name} in GM_ADVANCED is not yet verified")
        prepare = getattr(self, f"_prepare_{call.name}", None)
        return prepare(call.kwargs) if prepare is not None else None

    def prepare(self, call: Call):
        token = super().prepare(call)
        call = token.call
        handler = getattr(self, f"_apply_{call.name}", None)
        if handler is None:
            raise UnsupportedOperation(call.name)
        try:
            prepared = self._prepare_effect(call)
        except ResourceLimitError:
            raise
        except FormatError as error:
            raise UnsupportedOperation(f"{call.name}: malformed input: {error}") from error
        return replace(
            token,
            payload=(handler, prepared),
            # Creation preparation returns the realized object, or None for a native null object.
            null_object=call.name in CREATED_KINDS and prepared is None,
        )

    def _execute(self, token):
        call = token.call
        handler, prepared = token.payload
        result = self._result(call)
        # Input rejection belongs in prepare; execution failures are fatal.
        with self._geometry_budget.activate():
            handler(call, prepared, result)
        self._commit(call)
        if isinstance(result, Handle) and self.is_null_object(result):
            # Intern failed creations so file-slot reuse cannot leak handles.
            del self._live[result.serial]
            del self._objects[result]
            result = Handle(0, result.kind, self)
            self._objects[result] = None
        return result

    def _prepare_escape(self, a):
        if a["escape_function"] not in BITMAP_NOOP_ESCAPES:
            raise UnsupportedOperation(f"escape {a['escape_function']:#06x}")

    def _apply_escape(self, call, prepared, result):
        pass  # Accepted printer metadata has no effect on a bitmap DC.

    _apply_realize_palette = _apply_escape

    def _prepare_text_out(self, a):
        try:
            return self._prepare_text(a)
        except UnsupportedOperation as error:
            raise UnsupportedOperation(f"text_out: {error}") from error

    def _apply_text_out(self, call, prepared, result):
        a = call.kwargs
        self._draw_text(*prepared, a.get("options", 0))

    def _prepare_ext_text_out(self, a):
        try:
            return self._prepare_text(a)
        except UnsupportedOperation as error:
            raise UnsupportedOperation(f"ext_text_out: {error}") from error

    _apply_ext_text_out = _apply_text_out

    def _store_object(self, call, prepared, result):
        # Store native null creations too; execution normalizes their handles.
        self._objects[result] = prepared

    def _prepare_create_palette(self, a):
        palette = a["palette"]
        return LogicalPalette(palette.entries) if palette is not None and palette.entries else None

    _apply_create_palette = _store_object

    def _apply_select_palette(self, call, prepared, result):
        a = call.kwargs
        if a["handle"] is not None and self._objects[a["handle"]] is not None:
            self._state.palette = self._objects[a["handle"]]

    def _apply_set_palette_entries(self, call, prepared, result):
        name = call.name
        a = call.kwargs
        self._state.palette.update(a["palette"].start, a["palette"].entries, animate=name == "animate_palette")

    _apply_animate_palette = _apply_set_palette_entries

    def _prepare_resize_palette(self, a):
        if not 0 <= a["count"] <= 65535:
            raise ValueError("Palette size outside WORD range")

    def _apply_resize_palette(self, call, prepared, result):
        a = call.kwargs
        self._state.palette.resize(a["count"])

    def _prepare_set_map_mode(self, a):
        if a["mode"] not in range(MM_TEXT, MM_ANISOTROPIC + 1):
            raise UnsupportedOperation(f"Map mode {a['mode']}")

    def _apply_set_map_mode(self, call, prepared, result):
        a = call.kwargs
        self.mapping.set_mode(a["mode"])

    def _apply_set_brush_origin(self, call, prepared, result):
        self._state.brush_origin = (call.kwargs["x"], call.kwargs["y"])

    def _prepare_set_arc_direction(self, a):
        if a["direction"] not in (1, 2):
            raise InvalidOperation("Arc direction is AD_COUNTERCLOCKWISE or AD_CLOCKWISE")

    def _apply_set_arc_direction(self, call, prepared, result):
        self._state.arc_direction = call.kwargs["direction"]

    def _advanced_arc(self, box, start, end, closure="open", angles=None, *, inside_frame=False):
        """A GM_ADVANCED arc figure in world orientation; see ``advanced_arc``.

        With ``inside_frame``, a wide inside-frame pen insets the box, and a
        box narrower than the pen gives None.
        """
        width = 0
        if inside_frame and self._state.pen.style == PS_INSIDEFRAME and not self._painter().realized_pen.cosmetic:
            width = self._state.pen.width
        return advanced_arc(
            self.mapping,
            box,
            start,
            end,
            direction=self._state.arc_direction,
            closure=closure,
            null_pen=self._state.pen.style == PS_NULL,
            angles=angles,
            inside_frame=width,
        )

    def _stroke_from_position(self, path, end):
        """Stroke a line from the current position into ``path``; move to ``end``.

        The current position is the exact logical end point, floored, as
        native recording reports it after AngleArc and ArcTo.
        """
        start = self._start_point()
        self._stroke_path(DevicePath(((start, path.commands[0][0]), *path.commands)), extend=True)
        self._state.position = (math.floor(end[0]), math.floor(end[1]))
        self._state.fixed_position = path.commands[-1][-1]

    def _start_point(self):
        """The 28.4 point a *To call starts from: the exact point an arc left, else the position."""
        if self._state.fixed_position is not None:
            return self._state.fixed_position
        return self._path_point(*self._state.position)

    def _prepare_arc_to(self, a):
        if self.mapping.graphics_mode != GM_ADVANCED:
            raise UnsupportedOperation("arc_to in GM_COMPATIBLE")

    def _apply_arc_to(self, call, prepared, result):
        a = call.kwargs
        box = (a["left"], a["top"], a["right"], a["bottom"])
        end = (a["end_x"], a["end_y"])
        path = self._advanced_arc(box, (a["start_x"], a["start_y"]), end, inside_frame=True)
        if path is None:
            return  # A box narrower than an inside-frame pen: nothing happens.
        # The current position is the arc's 28.4 end, floored to a logical point.
        self._stroke_from_position(path, self._floor_logical(path.commands[-1][-1]))

    def _floor_logical(self, point):
        """The logical point at or below a 28.4 device point, as GetCurrentPositionEx reports it."""
        if self.mapping.rotated:
            m11, m12, m21, m22, dx, dy = self.mapping.world
            x, y = point[0] / 16 - dx, point[1] / 16 - dy
            det = m11 * m22 - m12 * m21
            return math.floor((x * m22 - y * m21) / det), math.floor((y * m11 - x * m12) / det)
        return tuple(
            math.floor((Fraction(value, 16) - Fraction(origin)) / Fraction(scale))
            for value, (scale, origin) in zip(point, self.mapping._transform(), strict=True)
        )

    def _prepare_angle_arc(self, a):
        if self.mapping.graphics_mode != GM_ADVANCED:
            raise UnsupportedOperation("angle_arc in GM_COMPATIBLE")
        if a["radius"] < 0:
            raise UnsupportedOperation("angle_arc: negative radii")

    def _apply_angle_arc(self, call, prepared, result):
        a = call.kwargs
        x, y, radius = a["x"], a["y"], a["radius"]
        box = (x - radius, y - radius, x + radius, y + radius)

        def point(angle):
            # Angles reduce to one turn first, as native trigonometry does.
            angle = math.radians(angle % 360)
            return (x + radius * math.cos(angle), y - radius * math.sin(angle))

        def arc(start, sweep):
            """Bezier pieces of one arc; a zero sweep is one zero-length piece."""
            angles = (start, start + sweep)
            commands = self._advanced_arc(box, point(start), point(start + sweep), angles=angles).commands
            return ((commands[0][0],) * 4,) if not sweep else commands

        # A sweep of a turn or more draws the remainder, then each turn as the
        # arc from the remainder's end round to the start and the remainder again.
        start, sweep = a["start"], a["sweep"]
        turns = int(abs(sweep) // 360)
        remainder = sweep - math.copysign(360 * turns, sweep)
        direction = self._state.arc_direction
        # AngleArc sweeps counterclockwise for positive angles, whatever the arc direction.
        self._state.arc_direction = 2 if sweep < 0 else 1
        try:
            commands = arc(start, remainder if turns else sweep)
            for _ in range(turns):
                commands += arc(start + remainder, math.copysign(360, sweep) - remainder) + arc(start, remainder)
        finally:
            self._state.arc_direction = direction
        self._stroke_from_position(DevicePath(tuple(commands)), point(start + sweep))

    def _prepare_set_miter_limit(self, a):
        if not a["limit"] >= 1:
            raise InvalidOperation("Miter limits are at least 1")

    def _apply_set_miter_limit(self, call, prepared, result):
        self._state.miter_limit = float(call.kwargs["limit"])

    def _prepare_set_graphics_mode(self, a):
        if a["mode"] not in (GM_COMPATIBLE, GM_ADVANCED):
            raise InvalidOperation(f"Graphics mode {a['mode']}")
        if a["mode"] == GM_COMPATIBLE and self.mapping.world != IDENTITY_TRANSFORM:
            raise InvalidOperation("GM_COMPATIBLE requires an identity world transform")

    def _apply_set_graphics_mode(self, call, prepared, result):
        self.mapping.graphics_mode = call.kwargs["mode"]

    def _prepare_set_world_transform(self, a):
        transform = tuple(float32(a[name]) for name in ("m11", "m12", "m21", "m22", "dx", "dy"))
        if self.mapping.graphics_mode != GM_ADVANCED:
            raise InvalidOperation("World transforms require GM_ADVANCED")
        if transform[0] * transform[3] - transform[1] * transform[2] == 0:
            raise InvalidOperation("Singular world transform")
        if (transform[1] or transform[2]) and not self.mapping.identity_page:
            raise UnsupportedOperation("Rotated or sheared world transforms need an identity page mapping")
        return transform

    def _apply_set_world_transform(self, call, prepared, result):
        self.mapping.world = prepared

    def _prepare_set_layout(self, a):
        if a["layout"] & ~9:
            raise UnsupportedOperation(f"Layout {a['layout']}")

    def _apply_set_layout(self, call, prepared, result):
        a = call.kwargs
        self.mapping.set_layout(a["layout"])

    def _apply_set_polygon_fill_mode(self, call, prepared, result):
        # Any value other than WINDING fills as ALTERNATE.
        self._state.polygon_fill_mode = WINDING if call.kwargs["mode"] == WINDING else ALTERNATE

    def _apply_set_rop2(self, call, prepared, result):
        # GDI keeps the low byte and wraps it into the sixteen mixes, so 0 is
        # R2_WHITE and 17 is R2_BLACK.
        self._state.rop2 = (((call.kwargs["mode"] & 0xFF) - 1) & 15) + 1

    def _prepare_set_color_adjustment(self, a):
        adjustment = ColorAdjustment(
            a["flags"],
            a["illuminant"],
            (a["red_gamma"], a["green_gamma"], a["blue_gamma"]),
            a["black"],
            a["white"],
            a["contrast"],
            a["brightness"],
            a["colorfulness"],
            a["tint"],
        )
        if not (
            min(adjustment.gamma) >= 2500
            and max(adjustment.gamma) <= 65000
            and 0 <= adjustment.black <= 4000
            and 6000 <= adjustment.white <= 10000
            and all(
                -100 <= value <= 100
                for value in (adjustment.contrast, adjustment.brightness, adjustment.colorfulness, adjustment.tint)
            )
            and adjustment.illuminant <= 8
            and not adjustment.flags & ~3
        ):
            raise InvalidOperation("COLORADJUSTMENT field out of range")
        return adjustment

    def _apply_set_color_adjustment(self, call, prepared, result):
        self._state.color_adjustment = prepared

    def _apply_set_stretch_mode(self, call, prepared, result):
        # Values outside the four modes stretch as WHITEONBLACK.
        mode = call.kwargs["mode"]
        self._state.stretch_mode = (
            mode if mode in (BLACKONWHITE, WHITEONBLACK, COLORONCOLOR, HALFTONE) else WHITEONBLACK
        )

    def _apply_set_background_mode(self, call, prepared, result):
        # The value is kept as given; drawing paints a background only for OPAQUE.
        self._state.background_mode = call.kwargs["mode"]

    def _apply_set_background_color(self, call, prepared, result):
        a = call.kwargs
        self._state.background_color = logical_color(a["color"])

    def _apply_set_text_color(self, call, prepared, result):
        a = call.kwargs
        self._state.text_color = logical_color(a["color"])

    def _apply_set_text_alignment(self, call, prepared, result):
        a = call.kwargs
        self._state.text_state = replace(self._state.text_state, alignment=a["alignment"])

    def _apply_set_text_character_extra(self, call, prepared, result):
        a = call.kwargs
        self._state.text_state = replace(self._state.text_state, character_extra=a["extra"])

    def _apply_set_text_justification(self, call, prepared, result):
        a = call.kwargs
        self._state.text_state = replace(self._state.text_state, justification=(a["break_count"], a["break_extra"]))

    def _apply_set_mapper_flags(self, call, prepared, result):
        a = call.kwargs
        self._state.text_state = replace(self._state.text_state, mapper_flags=a["flags"])

    def _apply_set_window_origin(self, call, prepared, result):
        a = call.kwargs
        self.mapping.window_origin = a["x"], a["y"]

    def _apply_set_viewport_origin(self, call, prepared, result):
        a = call.kwargs
        self.mapping.viewport_origin = a["x"], a["y"]

    def _apply_set_window_extent(self, call, prepared, result):
        a = call.kwargs
        self.mapping.set_extent(window=True, x=a["x"], y=a["y"])

    def _apply_set_viewport_extent(self, call, prepared, result):
        a = call.kwargs
        self.mapping.set_extent(window=False, x=a["x"], y=a["y"])

    def _apply_offset_window_origin(self, call, prepared, result):
        a = call.kwargs
        x, y = self.mapping.window_origin
        self.mapping.window_origin = x + a["x"], y + a["y"]

    def _apply_offset_viewport_origin(self, call, prepared, result):
        a = call.kwargs
        x, y = self.mapping.viewport_origin
        self.mapping.viewport_origin = x + a["x"], y + a["y"]

    def _apply_scale_window_extent(self, call, prepared, result):
        name = call.name
        a = call.kwargs
        self.mapping.scale_extent(
            window=name == "scale_window_extent",
            xn=a["x_numerator"],
            xd=a["x_denominator"],
            yn=a["y_numerator"],
            yd=a["y_denominator"],
        )

    _apply_scale_viewport_extent = _apply_scale_window_extent

    def _prepare_create_pen(self, a):
        # CreatePenIndirect uses CreatePen, not ExtCreatePen: unrecognized
        # styles become PS_SOLID, including styles with join/cap bits.
        # Normalize the realized object only; preserve the requested call.
        style = a["style"] if a["style"] in range(PS_SOLID, PS_INSIDEFRAME + 1) else PS_SOLID
        return Pen(logical_color(a["color"]), abs(a["width"]), style)

    _apply_create_pen = _store_object

    def _prepare_ext_create_pen(self, a):
        style = a["style"]
        kind, line_style = style & 0x000F0000, style & 0x0F
        cap, join = (style >> 8) & 0x0F, (style >> 12) & 0x0F
        entries = tuple(a["entries"])
        if style & ~0x000FFF0F or kind not in (0, 0x00010000) or cap > 2 or join > 2 or line_style > PS_ALTERNATE:
            raise InvalidOperation("Unrecognized extended pen style")
        if (line_style == PS_USERSTYLE) != bool(entries) or len(entries) > 16 or any(e < 0 for e in entries):
            raise InvalidOperation("User styles need between one and sixteen entries")
        color = logical_color(a["color"])
        brush = None
        if a["brush_style"] == BS_HATCHED:
            brush = self._prepare_create_brush({"style": BS_HATCHED, "color": a["color"], "hatch": a["hatch"]})
        elif a["brush_style"] in (BS_DIBPATTERN, BS_DIBPATTERNPT) and a["bitmap"] is not None:
            # The LOGBRUSH colour of a DIB pattern pen is its colour usage.
            arguments = {"style": BS_DIBPATTERN, "color_usage": a["color"], "bitmap": a["bitmap"]}
            brush = self._prepare_create_dib_pattern_brush(arguments)
            if brush is None:
                raise InvalidOperation("Unusable pattern pen bitmap")
        elif a["brush_style"] != BS_SOLID:
            raise UnsupportedOperation("Extended pen brush style is not supported")
        if brush is not None and not kind:
            raise InvalidOperation("Cosmetic pens need a solid brush")
        if not kind:
            if line_style == PS_INSIDEFRAME:
                raise InvalidOperation("Cosmetic pens cannot be inside-frame")
            # Cosmetic pens are one device pixel wide whatever their width.
            # User style units are three pixels, like the predefined styles.
            pattern = {PS_ALTERNATE: (1, 1), PS_USERSTYLE: tuple(3 * e for e in entries)}.get(line_style, ())
            return Pen(color, 0, PS_SOLID if pattern else line_style, pattern=pattern, cosmetic=True)
        if a["width"] <= 0 or line_style == PS_ALTERNATE:
            raise InvalidOperation("Geometric pens need a positive width and no alternate style")
        if line_style == PS_USERSTYLE:
            pattern = entries
        else:
            pattern = tuple(a["width"] * factor for factor in GEOMETRIC_DASHES.get(line_style, ()))
        return Pen(color, a["width"], line_style, geometric=True, cap=cap, join=join, pattern=pattern, brush=brush)

    _apply_ext_create_pen = _store_object

    def _prepare_get_stock_object(self, a):
        """Stock brushes and pens are ordinary objects; the default palette is shared."""
        index = a["index"]
        brushes = {0: 0xFFFFFF, 1: 0xC0C0C0, 2: 0x808080, 3: 0x404040, 4: 0, 18: 0xFFFFFF}
        if index in brushes:
            return Brush(logical_color(brushes[index]), BS_SOLID)
        if index == 5:
            return Brush((0, 0, 0), BS_NULL)
        pens = {6: (0xFFFFFF, PS_SOLID), 7: (0, PS_SOLID), 8: (0, PS_NULL), 19: (0, PS_SOLID)}
        if index in pens:
            color, style = pens[index]
            return Pen(logical_color(color), 0, style)
        if index == 15:
            if self._default_palette is None:
                self._default_palette = LogicalPalette.default()
            return self._default_palette
        raise UnsupportedOperation(f"Stock font {index}")

    _apply_get_stock_object = _store_object

    def _prepare_create_brush(self, a):
        if a["style"] not in (BS_SOLID, BS_NULL, BS_HATCHED) or (
            a["style"] == BS_HATCHED and a["hatch"] not in range(6)
        ):
            raise UnsupportedOperation("Only solid, null and six hatch brushes are supported")
        return Brush(logical_color(a["color"]), a["style"], a["hatch"])

    _apply_create_brush = _store_object

    def _prepare_create_font(self, a):
        return a["font"]

    _apply_create_font = _store_object

    def _prepare_create_pattern_brush(self, a):
        layout = read_bitmap16(a["bitmap"], native_pattern=True, max_pixels=self.max_bitmap_pixels)
        # A DDB keeps its device format. Only monochrome, the default
        # indexed device palette, and matching RGB32 realize on this DC.
        pattern = None
        if layout.complete and layout.depth in (1, 8, 32):
            colors = DEFAULT_COLORS[:10] + ((0, 0, 0),) * 236 + DEFAULT_COLORS[10:]
            pattern = layout.decode(colors=colors if layout.depth == 8 else None)
        return (
            Brush(
                (0, 0, 0),
                style=BS_PATTERN,
                pattern=pattern,
                monochrome=layout.depth == 1,
                realizable=pattern is not None,
            )
            if layout.complete
            else None
        )

    _apply_create_pattern_brush = _store_object

    def _prepare_create_dib_pattern_brush(self, a):
        layout = read_dib(
            a["bitmap"],
            color_usage=0 if a["style"] == 3 else a["color_usage"],
            max_pixels=self.max_bitmap_pixels,
        )
        if layout.color_usage == 1 and layout.complete:
            # Packed brush storage DWORD-aligns the WORD palette table.
            # The allocation's tail is zero-filled, unlike the separate
            # header/bits pointers used by transfer records.
            padding = -layout.offset % 4
            layout = replace(layout, offset=layout.offset + padding, data=layout.data + bytes(padding))
        pattern = (
            None
            if not accepts_dib(layout)
            or layout.compression in (1, 2)
            or (layout.header_size > 40 and layout.compression == 3)
            else layout.decode(palette=self._state.palette.colors())
        )
        if pattern is not None and layout.color_usage == 1 and layout.depth <= 8:
            # Validate the packed samples now, but retain their palette
            # references. Pattern colours are realized against the drawing
            # DC, including subsequent palette edits and selections.
            pattern = layout
        if a["style"] == 3 and pattern is not None:
            # The legacy record path realizes a monochrome DDB in a
            # compatible memory DC. Its bitmap creation rejects top-down
            # dimensions; failed selection preserves the previous brush.
            pattern = None if layout.top_down else pattern.monochrome()
        return (
            Brush((0, 0, 0), style=BS_PATTERN, pattern=pattern, monochrome=a["style"] == BS_PATTERN)
            if pattern is not None
            else None
        )

    _apply_create_dib_pattern_brush = _store_object

    def _prepare_create_region(self, a):
        return RegionMask.from_rectangles(a["region"].rectangles) if a["region"] is not None else None

    _apply_create_region = _store_object

    def _apply_select_clip_region(self, call, prepared, result):
        a = call.kwargs
        region = self._objects[a["region"]] if a["region"] is not None else None
        self._state.clip = self._state.clip.select(self._clip_mask(region) if region is not None else None)

    def _prepare_ext_select_clip_region(self, a):
        if a["mode"] not in range(1, 6):
            raise InvalidOperation(f"Region mode {a['mode']}")
        if a["region"] is None and a["mode"] != 5:
            raise InvalidOperation("Only RGN_COPY accepts a null region")

    def _apply_ext_select_clip_region(self, call, prepared, result):
        a = call.kwargs
        region = self._objects[a["region"]] if a["region"] is not None else None
        mask = self._clip_mask(region) if region is not None else None
        if a["mode"] == 5:
            self._state.clip = self._state.clip.select(mask)
        else:
            bounds = (0, 0, self.surface.width, self.surface.height)
            self._state.clip = self._state.clip.combine(mask or RegionMask(), a["mode"], bounds)

    def get_clip_box(self):
        """GetClipBox: the effective clip's bounding box in logical units, or None when empty.

        A rotating or shearing transform maps the box's four corners back and
        bounds them; otherwise the two corners map back to their nearest
        logical points.
        """
        region = self._state.clip.within((0, 0, self.surface.width, self.surface.height))
        if not region.bands:
            return None
        left = min(endpoints[0] for _, _, endpoints in region.bands)
        right = max(endpoints[-1] for _, _, endpoints in region.bands)
        top, bottom = region.bands[0][0], region.bands[-1][1]
        if self.mapping.rotated:
            corners = [self.mapping.rotated_logical_point(x * 16, y * 16) for x in (left, right) for y in (top, bottom)]
            xs, ys = [x for x, _ in corners], [y for _, y in corners]
            return min(xs), min(ys), max(xs), max(ys)
        (left, top), (right, bottom) = self.mapping.logical_point(left, top), self.mapping.logical_point(right, bottom)
        return min(left, right), min(top, bottom), max(left, right), max(top, bottom)

    def _apply_set_meta_region(self, call, prepared, result):
        self._state.clip = self._state.clip.with_meta((0, 0, self.surface.width, self.surface.height))

    def _apply_select_object(self, call, prepared, result):
        a = call.kwargs
        obj = self._objects[a["handle"]] if a["handle"] is not None else None
        if isinstance(obj, Pen):
            self._state.pen = obj
        elif isinstance(obj, FontRequest):
            self._state.text_state = replace(self._state.text_state, font=obj)
        elif isinstance(obj, RegionMask):
            self._state.clip = self._state.clip.select(self._clip_mask(obj))
        elif obj is None:
            pass  # Selecting a null object fails without changing state.
        else:
            self._state.brush = obj

    def _apply_delete_object(self, call, prepared, result):
        a = call.kwargs
        if not self.is_null_object(a["handle"]):
            del self._objects[a["handle"]]

    def _apply_move_to(self, call, prepared, result):
        a = call.kwargs
        self._state.position = a["x"], a["y"]
        self._state.fixed_position = None

    def _apply_line_to(self, call, prepared, result):
        a = call.kwargs
        start = self._start_point()
        self._stroke_path(DevicePath.polyline((start, self._path_point(a["x"], a["y"]))), extend=True)
        self._state.position = a["x"], a["y"]
        self._state.fixed_position = None

    def _apply_polyline(self, call, prepared, result):
        a = call.kwargs
        self._stroke_path(DevicePath.polyline(self._mapped_path(a["points"])))

    def _prepare_poly_bezier(self, a):
        if len(a["points"]) % 3 != 1:
            raise InvalidOperation("PolyBezier needs a start point and three points per cubic")

    def _apply_poly_bezier(self, call, prepared, result):
        points = self._mapped_path(call.kwargs["points"])
        self._stroke_path(DevicePath(tuple(tuple(points[i : i + 4]) for i in range(0, len(points) - 1, 3))))

    def _prepare_poly_bezier_to(self, a):
        if len(a["points"]) % 3:
            raise InvalidOperation("PolyBezierTo needs three points per cubic")

    def _apply_poly_bezier_to(self, call, prepared, result):
        logical = (self._state.position, *call.kwargs["points"])
        points = [self._start_point(), *self._mapped_path(logical[1:])]
        if len(points) > 1:
            self._stroke_path(
                DevicePath(tuple(tuple(points[i : i + 4]) for i in range(0, len(points) - 1, 3))), extend=True
            )
            self._state.position, self._state.fixed_position = logical[-1], None

    def _apply_polyline_to(self, call, prepared, result):
        logical = (self._state.position, *call.kwargs["points"])
        if len(logical) > 1:
            points = [self._start_point(), *self._mapped_path(logical[1:])]
            self._stroke_path(DevicePath.polyline(points), extend=True)
            self._state.position, self._state.fixed_position = logical[-1], None

    def _apply_poly_polyline(self, call, prepared, result):
        for polyline in call.kwargs["polylines"]:
            if len(polyline) > 1:
                self._stroke_path(DevicePath.polyline(self._mapped_path(polyline)))

    def _prepare_poly_draw(self, a):
        points, types = a["points"], a["types"]
        if len(types) != len(points):
            raise InvalidOperation("PolyDraw needs one type per point")
        figures, figure, closed = [], [], []
        position = self._state.position
        start = position
        index = 0
        while index < len(points):
            kind = types[index] & ~1
            if kind == 6:  # PT_MOVETO
                if figure:
                    figures.append((tuple(figure), False))
                figure, start, position = [], points[index], points[index]
                index += 1
                continue
            if kind == 2:  # PT_LINETO
                figure.append((position, points[index]))
                position = points[index]
                last = index
                index += 1
            elif kind == 4 and index + 2 < len(points) and all(t & ~1 == 4 for t in types[index : index + 3]):
                figure.append((position, *points[index : index + 3]))
                position = points[index + 2]
                last = index + 2
                index += 3
            else:
                raise InvalidOperation("Invalid PolyDraw point type")
            if types[last] & 1:  # PT_CLOSEFIGURE
                figure.append((position, start))
                figures.append((tuple(figure), True))
                figure, position = [], start
        if figure:
            figures.append((tuple(figure), False))
        del closed
        return tuple(figures), position

    def _apply_poly_draw(self, call, prepared, result):
        figures, position = prepared
        for commands, closed in figures:
            mapped = tuple(tuple(self._path_point(*point) for point in command) for command in commands)
            self._stroke_path(DevicePath(mapped, closed=closed))
        if figures or position != self._state.position:
            self._state.fixed_position = None
        self._state.position = position

    def _apply_polygon(self, call, prepared, result):
        name = call.name
        a = call.kwargs
        polygons = (a["points"],) if name == "polygon" else a["polygons"]
        # Polygon and PolyPolygon reject contours with fewer than two points.
        # PolyPolygon validates the entire contour list before painting.
        # Dropping short contours would incorrectly draw the valid ones.
        if any(len(points) < 2 for points in polygons):
            return
        paths = tuple(self._mapped_path(points) for points in polygons)
        self._paint_polygons(tuple(DevicePath.polyline(path, closed=True) for path in paths))

    _apply_poly_polygon = _apply_polygon

    def _apply_set_pixel(self, call, prepared, result):
        a = call.kwargs
        self._pixel(*self._point(a["x"], a["y"]), logical_color(a["color"]))

    def _apply_pat_blt(self, call, prepared, result):
        a = call.kwargs
        if prepared is not None:
            self._painter().transform_pat_blt(prepared, a["rop"])
            return
        self._pat_blt(a["x"], a["y"], a["width"], a["height"], a["rop"])

    def _rotated_legacy(self, transfer, a):
        """Under rotation, a destination-DC source fails as native GDI rejects
        a rotated source DC; pattern operations fill the parallelogram."""
        if not self.mapping.rotated:
            return transfer
        if transfer is TransferAction.PATTERN:
            return self._prepare_pat_blt(a)
        return TransferAction.NOOP

    def _prepare_pat_blt(self, a):
        if self.mapping.rotated:
            x, y = a["x"], a["y"]
            points = ((x, y), (x + a["width"], y), (x, y + a["height"]))
            return tuple(self.mapping.fixed_point(*point) for point in points)
        return None

    def _prepare_bit_blt(self, a):
        return self._rotated_legacy(self._prepare_legacy_transfer("bit_blt", a), a)

    def _prepare_stretch_blt(self, a):
        return self._rotated_legacy(self._prepare_legacy_transfer("stretch_blt", a), a)

    def _prepare_dib_bit_blt(self, a):
        if self.mapping.rotated:
            return self._prepare_rotated_transfer("dib_bit_blt", a)
        return self._prepare_transfer("dib_bit_blt", a)

    def _prepare_dib_stretch_blt(self, a):
        if self.mapping.rotated:
            return self._prepare_rotated_transfer("dib_stretch_blt", a)
        return self._prepare_transfer("dib_stretch_blt", a)

    def _prepare_stretch_dib(self, a):
        if self.mapping.rotated:
            return self._prepare_rotated_transfer("stretch_dib", a)
        return self._prepare_transfer("stretch_dib", a)

    def _prepare_set_dib_to_device(self, a):
        return self._prepare_device_transfer(a)

    def _prepare_transparent_blt(self, a):
        # TransparentBlt stretches without combining samples, then skips the key.
        if self.mapping.rotated:
            transfer = self._prepare_rotated_transfer("dib_stretch_blt", {**a, "rop": SRCCOPY})
            key = self._state.palette.colorref(logical_color(a["transparent"]))
            blend = lambda sample, destination, x, y: None if sample == key else sample  # noqa: E731
            return replace(transfer, blend=blend), key
        preparation = replace(self._transfer_preparation(), stretch_mode=COLORONCOLOR)
        transfer = preparation.prepare_dib("dib_stretch_blt", {**a, "rop": SRCCOPY})
        return transfer, self._state.palette.colorref(logical_color(a["transparent"]))

    def _apply_transparent_blt(self, call, prepared, result):
        transfer, transparent = prepared
        if isinstance(transfer, ParallelogramTransfer):
            self._apply_plg_blt(call, transfer, result)
        elif isinstance(transfer, SourceTransfer):
            self._painter().source_blt(
                transfer.bitmap,
                transfer.horizontal,
                transfer.vertical,
                SRCCOPY,
                transparent=transparent,
                mode=COLORONCOLOR,
            )

    def _prepare_alpha_blend(self, a):
        operation, flags, constant, alpha_format = (a["blend"] >> shift & 255 for shift in (0, 8, 16, 24))
        if operation != 0 or flags != 0 or alpha_format not in (0, 1):
            raise InvalidOperation("Unsupported BLENDFUNCTION")
        layout = read_dib(a["source"], max_pixels=self.max_bitmap_pixels)
        alpha = None
        if alpha_format:
            if layout.depth != 32 or layout.compression != 0 or not layout.complete:
                raise UnsupportedOperation("alpha_blend: per-pixel alpha needs a 32-bit BI_RGB DIB")
            # The fourth byte of each BGRA sample, in top-down order.
            rows = [
                layout.data[layout.offset + row * layout.stride : layout.offset + (row + 1) * layout.stride][3::4]
                for row in range(layout.height)
            ]
            alpha = b"".join(rows if layout.top_down else reversed(rows))
        if self.mapping.rotated:
            transfer = self._prepare_rotated_transfer("dib_stretch_blt", {**a, "rop": SRCCOPY})
            width = transfer.source.width

            def blend(sample, destination, x, y):
                source_alpha = alpha[y * width + x] if alpha is not None else None
                return tuple(
                    alpha_channel(s, d, source_alpha, constant) for s, d in zip(sample, destination, strict=True)
                )

            return replace(transfer, blend=blend), None, None
        preparation = replace(self._transfer_preparation(), stretch_mode=COLORONCOLOR)
        transfer = preparation.prepare_dib("dib_stretch_blt", {**a, "rop": SRCCOPY})
        return transfer, alpha, constant

    def _apply_alpha_blend(self, call, prepared, result):
        transfer, alpha, constant = prepared
        if isinstance(transfer, ParallelogramTransfer):
            self._apply_plg_blt(call, transfer, result)
        elif isinstance(transfer, SourceTransfer):
            self._painter().alpha_blt(
                transfer.bitmap, alpha, transfer.horizontal, transfer.vertical, constant, alpha_channel
            )

    def _prepare_gradient_fill(self, a):
        size = {0: 2, 1: 2, 2: 3}.get(a["mode"])
        if size is None:
            raise InvalidOperation(f"Gradient mode {a['mode']}")
        for vertex in a["vertices"]:
            if len(vertex) != 6 or not all(0 <= channel <= 0xFFFF for channel in vertex[2:]):
                raise InvalidOperation("TRIVERTEX needs a position and four 16-bit channels")
        for mesh in a["meshes"]:
            if len(mesh) != size or not all(0 <= index < len(a["vertices"]) for index in mesh):
                raise InvalidOperation("Gradient mesh index out of range")

    def _apply_gradient_fill(self, call, prepared, result):
        a = call.kwargs
        vertices = tuple((*self._point(x, y), red, green, blue) for x, y, red, green, blue, _ in a["vertices"])
        painter = self._painter()
        if a["mode"] == 2 and not self.mapping.rotated:
            clip = self._state.clip.within((0, 0, self.surface.width, self.surface.height)).rectangles()
            clip = list(clip)
            if clip:
                bounds = (
                    min(r[0] for r in clip),
                    min(r[1] for r in clip),
                    max(r[2] for r in clip),
                    max(r[3] for r in clip),
                )
                for corners in mesh_triangles(vertices, a["meshes"], bounds):
                    painter.gradient_triangle(corners)
            return
        for mesh in a["meshes"]:
            corners = tuple(vertices[index] for index in mesh)
            if self.mapping.rotated and a["mode"] != 2:
                # A rotated rectangle is shaded as two triangles between its
                # pixel-rounded corners, coloured by the edge each lies on.
                first, second = (a["vertices"][index] for index in mesh)
                axis = a["mode"]
                if first[axis] > second[axis]:
                    first, second = second, first
                (left, right), (top, bottom) = sorted((first[0], second[0])), sorted((first[1], second[1]))
                ends = (first[2:5], second[2:5])

                def corner(x, y, ends=ends, axis=axis, near=(left, top)):
                    return (*self.mapping.device_point(x, y), *ends[(x, y)[axis] != near[axis]])

                top_left, top_right = corner(left, top), corner(right, top)
                bottom_right, bottom_left = corner(right, bottom), corner(left, bottom)
                painter.gradient_triangle((top_left, top_right, bottom_right))
                painter.gradient_triangle((top_left, bottom_right, bottom_left))
            elif a["mode"] == 2:
                painter.gradient_triangle(corners)
            else:
                painter.gradient_rectangle(corners, vertical=a["mode"] == 1)

    def _prepare_plg_blt(self, a):
        corners = tuple(self.mapping.fixed_point(x, y) for x, y in a["points"])
        (x0, y0), (x1, y1), (x2, y2) = corners
        if y1 == y0 and x2 == x0 and not any(value & 15 for value in (x0, y0, x1, x2, y2)):
            return self._prepare_rectangular_plg_blt(a, x0 >> 4, y0 >> 4, (x1 - x0) >> 4, (y2 - y0) >> 4)
        source = self._parallelogram_source(a["source"])
        rectangle = (a["src_x"], a["src_y"], a["src_width"], a["src_height"])
        sample = None
        if a["mask"] is not None:
            mask = self._plg_mask(a)

            def sample(u, v):
                # A sheared or rotated parallelogram reads the mask at the source pixel.
                mx, my = u - a["src_x"] + a["mask_x"], v - a["src_y"] + a["mask_y"]
                return 0 <= mx < mask.width and 0 <= my < mask.height and mask.index(mx, my) == 1

        return ParallelogramTransfer(source, corners, self._source_rectangle(source, rectangle), sample)

    def _plg_mask(self, a):
        mask = read_dib(a["mask"], color_usage=a["mask_usage"], max_pixels=self.max_bitmap_pixels)
        if mask.depth != 1 or not mask.complete:
            raise UnsupportedOperation("plg_blt: masks are complete 1-bpp DIBs")
        return mask

    def _prepare_rectangular_plg_blt(self, a, x, y, width, height):
        """A parallelogram that is a whole-pixel device rectangle is a stretch.

        It copies (a BitBlt at equal extents outside HALFTONE) or stretches the
        source onto the device rectangle in the DC's stretch mode, a negative
        extent mirroring the source. The mask lies over the destination: a
        mirrored axis reads it mirrored within the source rectangle.
        """
        sw, sh = a["src_width"], a["src_height"]
        arguments = {key: a[key] for key in ("src_x", "src_y", "source")}
        arguments |= {"x": x, "y": y, "width": width, "height": height, "rop": SRCCOPY}
        name = "dib_bit_blt"
        if (width, height) != (sw, sh) or self._state.stretch_mode == HALFTONE:
            name = "dib_stretch_blt"
            arguments |= {"src_width": sw, "src_height": sh}
        device = Mapping(mode=MM_TEXT, window_extent=(1, 1), viewport_extent=(1, 1), surface_width=self.surface.width)
        transfer = replace(self._transfer_preparation(), mapping=device).prepare_dib(name, arguments)
        if not isinstance(transfer, SourceTransfer) or a["mask"] is None:
            return transfer, None
        mask = self._plg_mask(a)
        flip_x, flip_y = width < 0, height < 0

        def sample(u, v):
            u, v = u - a["src_x"], v - a["src_y"]
            if flip_x:
                u = sw - 1 - u
            if flip_y:
                v = sh - 1 - v
            mx, my = u + a["mask_x"], v + a["mask_y"]
            return 0 <= mx < mask.width and 0 <= my < mask.height and mask.index(mx, my) == 1

        return transfer, (sample, 0x00AA0029)

    def _parallelogram_source(self, bitmap):
        layout = read_dib(bitmap, max_pixels=self.max_bitmap_pixels)
        if not accepts_dib(layout) or not layout.complete:
            raise UnsupportedOperation("Parallelogram transfers need a complete, directly decodable DIB")
        return layout.decode()

    @staticmethod
    def _source_rectangle(source, rectangle):
        x, y, width, height = rectangle
        if width <= 0 or height <= 0:
            raise UnsupportedOperation("Parallelogram transfers of empty or mirrored source rectangles")
        if x < 0 or y < 0 or x + width > source.width or y + height > source.height:
            raise UnsupportedOperation("Parallelogram transfers of rectangles outside the source")
        return rectangle

    def _prepare_rotated_transfer(self, name, a):
        """A rotating or shearing transform maps a destination rectangle to a
        parallelogram; see ``RasterPainter.transform_blt``."""
        if a.get("color_usage", 0) != 0 or a["source"] is None:
            raise UnsupportedOperation(f"{name}: only RGB transfers with a source under a rotating transform")
        source = self._parallelogram_source(a["source"])
        width, height = a.get("src_width", a["width"]), a.get("src_height", a["height"])
        top = a["src_y"]
        if name == "stretch_dib" and read_dib(a["source"], max_pixels=self.max_bitmap_pixels).top_down is False:
            # StretchDIBits measures a bottom-up source from its last row.
            top = source.height - a["src_y"] - height
        x, y = a["x"], a["y"]
        corners = tuple(
            self.mapping.fixed_point(*point) for point in ((x, y), (x + a["width"], y), (x, y + a["height"]))
        )
        rectangle = self._source_rectangle(source, (a["src_x"], top, width, height))
        return ParallelogramTransfer(source, corners, rectangle, rop=a["rop"])

    def _apply_plg_blt(self, call, prepared, result):
        if isinstance(prepared, tuple):
            transfer, mask = prepared
            if isinstance(transfer, SourceTransfer):
                self._painter().source_blt(transfer.bitmap, transfer.horizontal, transfer.vertical, SRCCOPY, mask=mask)
            return
        if prepared.rop is not None:
            self._painter().transform_blt(
                prepared.source,
                prepared.corners,
                prepared.rectangle,
                prepared.rop,
                mask=prepared.sample,
                background_rop=prepared.background_rop,
                blend=prepared.blend,
            )
            return
        self._painter().plg_blt(prepared.source, prepared.corners, prepared.rectangle, prepared.sample)

    def _prepare_mask_blt(self, a):
        """MAKEROP4 packs the background ROP3's table in the high byte."""
        foreground = a["rop"] & 0x00FFFFFF
        background = ((a["rop"] >> 24) & 255) << 16
        arguments = {key: a[key] for key in ("x", "y", "width", "height", "src_x", "src_y", "source")}
        source_width, source_height = a.get("src_size") or (a["width"], a["height"])
        name = "dib_bit_blt"
        if (source_width, source_height) != (a["width"], a["height"]):
            name = "dib_stretch_blt"
            arguments |= {"src_width": source_width, "src_height": source_height}
        if a["source"] is None:
            if pattern_rop2(foreground) is None or (a["mask"] is not None and pattern_rop2(background) is None):
                raise UnsupportedOperation("mask_blt: source-less operation uses its source")
            if a["mask"] is None:
                return TransferAction.PATTERN, foreground, None
            raise UnsupportedOperation("mask_blt: masked pattern transfers")
        if self.mapping.rotated:
            return self._prepare_rotated_mask_blt(a, arguments, foreground, background), foreground, None
        if a["mask"] is None:
            return self._prepare_transfer(name, {**arguments, "rop": foreground}), foreground, None
        # Realize the source as for a copy; each pixel's ROP3 is chosen later.
        transfer = self._prepare_transfer(name, {**arguments, "rop": SRCCOPY})
        if not isinstance(transfer, SourceTransfer):
            return transfer, foreground, None
        scaled = any(isinstance(axis, StretchAxis) for axis in (transfer.horizontal, transfer.vertical))
        if scaled and (foreground >> 16) & 255 != 0xCC:
            # As for other stretches, a foreground other than SRCCOPY pads
            # samples outside the source with black.
            horizontal, vertical = transfer.horizontal, transfer.vertical
            bounds = (horizontal.destination, vertical.destination)
            bounds += (bounds[0] + horizontal.length, bounds[1] + vertical.length)
            transfer = replace(transfer, pad_bounds=bounds)
        mask = read_dib(a["mask"], color_usage=a["mask_usage"], max_pixels=self.max_bitmap_pixels)
        source = read_dib(a["source"], max_pixels=self.max_bitmap_pixels)
        if mask.depth != 1 or not mask.complete:
            raise UnsupportedOperation("mask_blt: masks are complete 1-bpp DIBs")
        # Source samples are top-down; place the mask's rectangle over the source's.
        source_top = a["src_y"] if source.top_down else source.height - a["src_y"] - source_height
        mask_top = a["mask_y"] if mask.top_down else mask.height - a["mask_y"] - source_height

        def sample(x, y):
            mx, my = x - a["src_x"] + a["mask_x"], y - source_top + mask_top
            return 0 <= mx < mask.width and 0 <= my < mask.height and mask.index(mx, my) == 1

        return transfer, foreground, (sample, background)

    def _prepare_rotated_mask_blt(self, a, arguments, foreground, background):
        transfer = self._prepare_rotated_transfer("dib_bit_blt", {**arguments, "rop": foreground})
        if a["mask"] is None:
            return transfer
        mask = read_dib(a["mask"], color_usage=a["mask_usage"], max_pixels=self.max_bitmap_pixels)
        if mask.depth != 1 or not mask.complete:
            raise UnsupportedOperation("mask_blt: masks are complete 1-bpp DIBs")
        mask_top = (
            a["mask_y"] if mask.top_down else mask.height - a["mask_y"] - arguments.get("src_height", a["height"])
        )
        left, top = transfer.rectangle[:2]

        def sample(x, y):
            mx, my = x - left + a["mask_x"], y - top + mask_top
            return 0 <= mx < mask.width and 0 <= my < mask.height and mask.index(mx, my) == 1

        return replace(transfer, sample=sample, background_rop=background)

    def _apply_mask_blt(self, call, prepared, result):
        transfer, foreground, mask = prepared
        a = call.kwargs
        if isinstance(transfer, ParallelogramTransfer):
            self._apply_plg_blt(call, transfer, result)
        elif isinstance(transfer, SourceTransfer):
            self._painter().source_blt(
                transfer.bitmap,
                transfer.horizontal,
                transfer.vertical,
                foreground,
                mask=mask,
                pad_bounds=transfer.pad_bounds,
            )
        elif transfer is TransferAction.PATTERN:
            if self.mapping.rotated:
                self._painter().transform_pat_blt(self._prepare_pat_blt(a), foreground)
                return
            self._pat_blt(a["x"], a["y"], a["width"], a["height"], foreground)

    def _apply_bit_blt(self, call, prepared, result):
        a = call.kwargs
        if isinstance(prepared, tuple):  # A rotated pattern parallelogram.
            self._painter().transform_pat_blt(prepared, a["rop"])
        elif isinstance(prepared, ParallelogramTransfer):
            self._apply_plg_blt(call, prepared, result)
        elif isinstance(prepared, SourceTransfer):
            self._source_blt(
                prepared.bitmap,
                prepared.horizontal,
                prepared.vertical,
                prepared.operation,
                pad_bounds=prepared.pad_bounds,
            )
        elif prepared is TransferAction.PATTERN:
            self._pat_blt(a["x"], a["y"], a["width"], a["height"], a["rop"])

    _apply_stretch_blt = _apply_bit_blt
    _apply_dib_bit_blt = _apply_bit_blt
    _apply_set_dib_to_device = _apply_bit_blt
    _apply_dib_stretch_blt = _apply_bit_blt
    _apply_stretch_dib = _apply_bit_blt

    def _apply_flood_fill(self, call, prepared, result):
        a = call.kwargs
        self._flood_fill(
            self._point(a["x"], a["y"]), self._state.palette.colorref(logical_color(a["color"])), a.get("mode", 0)
        )

    def _prepare_ext_flood_fill(self, a):
        if a["mode"] not in (FLOODFILLBORDER, FLOODFILLSURFACE):
            raise UnsupportedOperation(f"Flood fill mode {a['mode']}")

    _apply_ext_flood_fill = _apply_flood_fill

    def _capture_saved_state(self):
        return self._state.snapshot()

    def _restore_saved_state(self, state):
        self._state = state

    def _apply_save_dc(self, call, prepared, result):
        pass  # The execution base commits the snapshot and stack together.

    _apply_restore_dc = _apply_save_dc

    def _polygon_mask(self, contours, *, fill_mode=ALTERNATE) -> RegionMask:
        """The pixels a polygon fill of 28.4 ``contours`` covers, as a region."""
        contours = tuple(tuple(contour) for contour in contours if contour)
        if not contours:
            return RegionMask()
        xs = [x for contour in contours for x, _ in contour]
        ys = [y for contour in contours for _, y in contour]
        bounds = (min(xs) // 16, min(ys) // 16, max(xs) // 16 + 1, max(ys) // 16 + 1)
        spans = coverage_spans(contours, *bounds, fill_mode=fill_mode)
        return RegionMask.from_rectangles((start, y, end, y + 1) for y, start, end in spans)

    def _apply_intersect_clip_rect(self, call, prepared, result):
        name = call.name
        a = call.kwargs
        if self.mapping.rotated:
            # Under rotation the clip rectangle becomes a filled parallelogram:
            # IntersectClipRect rounds its corners to device pixels first,
            # ExcludeClipRect keeps them in 28.4.
            corners = (
                (a["left"], a["top"]),
                (a["right"], a["top"]),
                (a["right"], a["bottom"]),
                (a["left"], a["bottom"]),
            )
            if name == "intersect_clip_rect":
                polygon = [tuple(16 * value for value in self.mapping.device_point(*point)) for point in corners]
            else:
                polygon = [self.mapping.fixed_point(*point) for point in corners]
            bounds = (0, 0, self.surface.width, self.surface.height)
            mode = 1 if name == "intersect_clip_rect" else 4
            self._state.clip = self._state.clip.combine(self._polygon_mask((polygon,)), mode, bounds)
            return
        left, top = self.mapping.clip_point(a["left"], a["top"])
        right, bottom = self.mapping.clip_point(a["right"], a["bottom"])
        rectangle = (min(left, right), min(top, bottom), max(left, right), max(top, bottom))
        if name == "intersect_clip_rect":
            self._state.clip = self._state.clip.intersect(rectangle)
        else:
            self._state.clip = self._state.clip.exclude(rectangle)

    _apply_exclude_clip_rect = _apply_intersect_clip_rect

    def _apply_offset_clip_region(self, call, prepared, result):
        a = call.kwargs
        dx, dy = self.mapping.clip_displacement(a["x"], a["y"])
        if self.mapping.rotated:
            # The logical offset is mapped by the transform's linear part and rounded.
            m11, m12, m21, m22 = self.mapping.world[:4]
            dx, dy = (
                (1 if value >= 0 else -1) * math.floor(abs(value) + 0.5)
                for value in (a["x"] * m11 + a["y"] * m21, a["x"] * m12 + a["y"] * m22)
            )
        self._state.clip = self._state.clip.offset(dx, dy)

    def _apply_fill_region(self, call, prepared, result):
        name = call.name
        a = call.kwargs
        painter = self._painter()
        region = self._objects[a["region"]]
        if region is not None and self.mapping.rotated:
            # The region's outline is transformed and filled as a polygon.
            loops = region_outlines(region.rectangles())
            contours = tuple([self.mapping.fixed_point(*point) for point in loop] for loop in loops)
            mask = self._polygon_mask(contours)
            if name == "frame_region":
                mask = self._rotated_frame(contours, mask, abs(a["width"]), abs(a["height"]))
            brush = self._objects[a["brush"]] if "brush" in a else self._state.brush
            for left, top, right, bottom in mask.rectangles():
                if name == "invert_region":
                    for y in range(max(0, top), min(self.surface.height, bottom)):
                        painter.span(y, left, right, (0, 0, 0), operation=R2_NOT)
                else:
                    painter.fill_box(left, top, right, bottom, brush)
            return
        if region is not None:
            if name == "frame_region":
                region = region.frame(
                    *frame_footprint(
                        a["width"],
                        a["height"],
                        *self.mapping.linear_scale,
                    ),
                    point=self._region_point,
                )
            else:
                region = region.transformed(self._region_point)
            brush = self._objects[a["brush"]] if "brush" in a else self._state.brush
            for left, top, right, bottom in region.rectangles():
                if name == "invert_region":
                    for y in range(max(0, top), min(self.surface.height, bottom)):
                        painter.span(y, left, right, (0, 0, 0), operation=R2_NOT)
                else:
                    painter.fill_box(left, top, right, bottom, brush)

    def _rotated_frame(self, contours, mask, width, height) -> RegionMask:
        """FrameRgn as native GDI draws it: the region's widened outline within the region.

        The outline is widened by a geometric pen with mitred joins and the DC's
        miter limit, twice the larger frame size wide, whose world transform
        squeezes the smaller axis by the sizes' ratio: an ellipse of twice
        the frame sizes in logical units. Its winding fill is intersected with
        the region.
        """
        if width < 1 or height < 1:
            return RegionMask()
        m11, m12, m21, m22, dx, dy = self.mapping.world
        ratio = float32(float32(2 * min(width, height)) / float32(2 * max(width, height)))
        if 2 * width < 2 * height:
            m11, m12 = float32(ratio * m11), float32(ratio * m12)
        else:
            m21, m22 = float32(ratio * m21), float32(ratio * m22)
        mapping = replace(self.mapping, world=(m11, m12, m21, m22, dx, dy))
        pen = Pen((0, 0, 0), 2 * max(width, height), PS_SOLID, geometric=True, cap=0, join=2)
        painter = RasterPainter(self.surface, replace(self._state, pen=pen, mapping=mapping))
        figures = tuple(DevicePath.polyline(contour + contour[:1], closed=True) for contour in contours)
        outlines = tuple(painter.widened_outlines(figures))
        frame = self._polygon_mask(outlines, fill_mode=WINDING)
        return frame.intersection(mask)

    _apply_paint_region = _apply_fill_region
    _apply_invert_region = _apply_fill_region
    _apply_frame_region = _apply_fill_region

    def _apply_rectangle(self, call, prepared, result):
        name = call.name
        a = call.kwargs
        painter = self._painter()
        pen = painter.realized_pen
        # Native EBOX decrements RTL logical X edges before transforming.
        # Rectangle's wide-pen path enters EBOX after its own decrement.
        shift = int(self.mapping.rtl) * (1 + (name == "rectangle" and not pen.cosmetic))
        advanced_bounds = corners = None
        if self.mapping.graphics_mode == GM_ADVANCED:
            # GM_ADVANCED paths use the transformed 28.4 box itself, lower-right
            # inclusive. The integer box takes the ceiling of each edge.
            # The logical box is normalized before it is transformed.
            logical_left, logical_right = sorted((a["left"], a["right"]))
            logical_top, logical_bottom = sorted((a["top"], a["bottom"]))
            # Native maps three corners and reflects the fourth through them.
            lt, rt, lb = (
                self.mapping.fixed_point(logical_left, logical_top),
                self.mapping.fixed_point(logical_right, logical_top),
                self.mapping.fixed_point(logical_left, logical_bottom),
            )
            width = self._state.pen.width
            covered = width > min(logical_right - logical_left, logical_bottom - logical_top)
            if self._state.pen.style == PS_INSIDEFRAME and not pen.cosmetic and not covered:
                lt, rt, lb = self.mapping.inside_frame_corners(lt, rt, lb, width)
            rb = (rt[0] + lb[0] - lt[0], rt[1] + lb[1] - lt[1])
            corners = (lt, rt, rb, lb) if self.mapping.rotated else None
            (x0, y0), (x1, y1) = lt, rb
            # Curves are built in world orientation; a mirroring transform
            # reverses the box edges rather than the construction.
            oriented_bounds = (x0, y0, x1, y1)
            if corners:
                xs, ys = [p[0] for p in corners], [p[1] for p in corners]
                x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
            x0, x1 = sorted((x0, x1))
            y0, y1 = sorted((y0, y1))
            advanced_bounds = (x0, y0, x1, y1)
            left, top, right, bottom = ((value + 15) // 16 for value in advanced_bounds)
        else:
            left, top = self._point(a["left"] - shift, a["top"])
            right, bottom = self._point(a["right"] - shift, a["bottom"])
        left, right = sorted((left, right))
        top, bottom = sorted((top, bottom))
        if self.mapping.graphics_mode == GM_ADVANCED:
            right, bottom = right + 1, bottom + 1
        if right > left and bottom > top:
            drawing_bounds = advanced_bounds
            covered = False
            if self._state.pen.style == PS_INSIDEFRAME and not pen.cosmetic:
                covered, inset_bounds = inside_frame_bounds(
                    (a["left"], a["top"], a["right"], a["bottom"]),
                    (left, top, right, bottom),
                    self._state.pen.width,
                    self.mapping.linear_scale,
                )
                if advanced_bounds is None:
                    # GM_ADVANCED boxes were inset at their transformed corners.
                    drawing_bounds = inset_bounds
                if covered and name in {"arc", "chord", "pie"}:
                    return
            rectangle = name == "rectangle"
            if name == "rectangle":
                bounds = (left * 16, top * 16, (right - 1) * 16, (bottom - 1) * 16)
                # Hairline rectangles use the integer box, except in paths.
                if drawing_bounds and not (pen.cosmetic and advanced_bounds and not self._state.recording_path):
                    bounds = drawing_bounds
                path = DevicePath.polyline(box_corners(bounds), closed=True)
                if corners:
                    lt, rt, rb, lb = corners
                    path = DevicePath.polyline((rt, lt, lb, rb), closed=True)
            elif name == "ellipse" and corners:
                path = DevicePath(corner_ellipse_cubics(corners), closed=True)
            elif name == "ellipse" and advanced_bounds is not None and drawing_bounds is advanced_bounds:
                path = DevicePath(advanced_ellipse_cubics(*oriented_bounds), closed=True)
            elif name == "ellipse":
                path = DevicePath(
                    ellipse_cubics(
                        left,
                        top,
                        right,
                        bottom,
                        null_pen=self._state.pen.style == PS_NULL,
                        drawing_bounds=drawing_bounds,
                        clockwise=self.mapping.rtl,
                    ),
                    closed=True,
                )
            elif name == "round_rect":
                advanced = advanced_bounds is not None and drawing_bounds is advanced_bounds
                # Corner proportions are established before integer device
                # mapping, just like arc radial directions.
                width = Fraction(abs(a["ellipse_width"]) * (right - left), abs(a["right"] - a["left"]))
                height = Fraction(abs(a["ellipse_height"]) * (bottom - top), abs(a["bottom"] - a["top"]))
                rectangle = not width or not height
                path = round_rect_figure(
                    left,
                    top,
                    right,
                    bottom,
                    width,
                    height,
                    null_pen=self._state.pen.style == PS_NULL,
                    drawing_bounds=oriented_bounds if advanced else drawing_bounds,
                    clockwise=self.mapping.rtl,
                    advanced=advanced,
                    corners=corners,
                )
            else:
                advanced = advanced_bounds is not None and drawing_bounds is advanced_bounds
                # GM_COMPATIBLE arcs run counterclockwise in device space, so
                # a mirroring mapping reflects the radials; GM_ADVANCED arcs
                # run counterclockwise in world space.
                sx, sy = (1, 1) if advanced else (1 if value >= 0 else -1 for value in self.mapping.linear_scale)
                start = sx * a["start_x"], sy * a["start_y"]
                end = sx * a["end_x"], sy * a["end_y"]
                x0, x1 = sorted((sx * (a["left"] - shift), sx * (a["right"] - shift)))
                y0, y1 = sorted((sy * a["top"], sy * a["bottom"]))
                path = arc_figure(
                    left,
                    top,
                    right,
                    bottom,
                    start,
                    end,
                    closure="open" if name == "arc" else name,
                    null_pen=self._state.pen.style == PS_NULL,
                    drawing_bounds=oriented_bounds if advanced else drawing_bounds,
                    radial_bounds=(x0, y0, x1, y1),
                    clockwise=self.mapping.rtl,
                    advanced=advanced,
                    corners=corners,
                )
                if advanced and self._state.arc_direction == 2:
                    path = self._advanced_arc(
                        (a["left"], a["top"], a["right"], a["bottom"]),
                        (a["start_x"], a["start_y"]),
                        (a["end_x"], a["end_y"]),
                        closure="open" if name == "arc" else name,
                        inside_frame=True,
                    )
            if self._state.recording_path:
                # A path keeps the box an inside-frame pen would fill.
                self._record_figure(path if name == "arc" else replace(path, closed=True))
            elif covered:
                for x, y in painter.contour_pixels((path.vertices,)):
                    painter.pen_pixel(x, y)
            elif name == "arc":
                painter.stroke_path(path)
            else:
                brush = self._state.brush
                # Rectangle's block-fill realization simplifies ROPs
                # independent of the pattern before applying hatch
                # transparency. Region/path fills retain the hatch mask.
                if rectangle and brush.style == BS_HATCHED and self._state.rop2 in (R2_BLACK, R2_NOT, R2_NOP, R2_WHITE):
                    brush = replace(brush, style=0)
                painter.paint_polygons((path,), miter=rectangle, reserve_outline=rectangle, brush=brush)

    _apply_ellipse = _apply_rectangle
    _apply_arc = _apply_rectangle
    _apply_chord = _apply_rectangle
    _apply_pie = _apply_rectangle
    _apply_round_rect = _apply_rectangle

    def _transfer_preparation(self):
        return TransferPreparation(
            surface=self.surface,
            mapping=self.mapping,
            palette=self._state.palette,
            clip=self._state.clip,
            stretch_mode=self._state.stretch_mode,
            color_adjustment=self._state.color_adjustment,
            text_color=self._state.text_color,
            background_color=self._state.background_color,
            max_bitmap_pixels=self.max_bitmap_pixels,
        )

    def _prepare_device_transfer(self, args):
        return self._transfer_preparation().prepare_device(args)

    def _prepare_legacy_transfer(self, name, args):
        return self._transfer_preparation().prepare_legacy(name, args)

    def _prepare_transfer(self, name, args):
        return self._transfer_preparation().prepare_dib(name, args)

    def _painter(self):
        return RasterPainter(self.surface, self._state)

    def _source_blt(self, bitmap, horizontal, vertical, operation, *, pad_bounds=None):
        self._painter().source_blt(bitmap, horizontal, vertical, operation, pad_bounds=pad_bounds)

    def _pat_blt(self, x, y, width, height, rop):
        self._painter().pat_blt(x, y, width, height, rop)

    def _flood_fill(self, seed, color, mode):
        self._painter().flood_fill(seed, color, mode)

    def _prepare_text(self, args):
        options = args.get("options", 0)
        # Reading order and numeral substitution do not alter our supported
        # left-to-right code pages. Arabic/Hebrew remain explicit boundaries.
        if options & ~(
            ETO_OPAQUE
            | ETO_CLIPPED
            | ETO_RTLREADING
            | ETO_NUMERICSLOCAL
            | ETO_NUMERICSLATIN
            | ETO_GLYPH_INDEX
            | ETO_PDY
        ):
            raise UnsupportedOperation("Text output options")
        rectangle = args.get("rectangle")
        if options & (ETO_OPAQUE | ETO_CLIPPED) and rectangle is None:
            raise InvalidOperation("Text output options require a rectangle")
        sx, sy = self.mapping.linear_scale
        if rectangle is not None:
            rectangle = (*self._point(*rectangle[:2]), *self._point(*rectangle[2:]))
            left, top, right, bottom = rectangle
            rectangle = min(left, right), min(top, bottom), max(left, right), max(top, bottom)
            if self.mapping.rtl:
                rectangle = rectangle[0] + 1, rectangle[1], rectangle[2] + 1, rectangle[3]
        if not args["text"]:
            return TextLayout(), rectangle
        request = self._state.text_state.font or self.fonts.default_font
        face = self.fonts.resolve(request)
        if sx * sy < 0:
            request = replace(request, escapement=-request.escapement)
        # Mapper flags constrain physical-font selection, not drawing with an
        # already explicitly supplied TrueType face. Retain them in DC state.
        update = self._state.text_state.alignment & TA_UPDATECP
        origin = self._state.position if update else (args["x"], args["y"])
        continued = self._state.text_position
        if update and continued is not None and continued[0] == self._state.position:
            fixed_origin = continued[1]
            origin = tuple((value + 8) >> 4 for value in fixed_origin)
        else:
            fixed_origin = self.mapping.fixed_point(*origin)
            origin = self._point(*origin)
        precise_origin = tuple(Fraction(value, 16) for value in fixed_origin)
        alignment = self._state.text_state.alignment
        # RTL layout swaps reference edges, not glyph masks or byte order.
        if self.mapping.rtl and alignment & 6 != 6:
            alignment ^= 2
        text = args["text"]
        glyph_indices = text.indices if isinstance(text, GlyphIndices) else None
        unicode = text.text if isinstance(text, UnicodeText) else None
        if unicode is not None and face.symbol:
            # The symbol cmap places its glyphs at U+F020-U+F0FF; character
            # codes below U+0100 reach them as ANSI bytes do.
            unicode = "".join(chr(0xF000 | ord(c)) if ord(c) < 0x100 else c for c in unicode)
        # Unicode text has one advance per code unit; stand-in bytes keep the
        # layout's one-byte-per-character spans.
        data = text.data if isinstance(text, EncodedText) else bytes(len(unicode or ""))
        advances = args.get("advances", ())
        vertical_advances = ()
        if options & ETO_PDY and not advances:
            # Paired displacement output requires explicit advances.
            return TextLayout(), None
        if options & ETO_PDY and advances:
            vertical_advances = advances[1::2]
            advances = advances[::2]
        if unicode is not None:
            decoded = DecodedText.single_byte(unicode)
        else:
            decoded = self.fonts.decode_run(request, face, data) if glyph_indices is None else None
        characters = decoded.text if decoded is not None else None
        if self._general_text(request):
            layout = self._transformed_text(
                request, face, characters, glyph_indices, fixed_origin, alignment, advances, options, vertical_advances
            )
            return layout, rectangle
        layout = layout_text(
            self.fonts.layout_font(
                request,
                face,
                (abs(sx), abs(sy)),
                characters=characters,
                advanced=self.mapping.graphics_mode == GM_ADVANCED,
                aspect=self._font_aspect(),
            ),
            data,
            *origin,
            alignment,
            advances,
            opaque=self._state.background_mode == OPAQUE,
            max_pixels=self.max_bitmap_pixels,
            scale=abs(sx),
            extra=self._state.text_state.character_extra,
            justification=self._state.text_state.justification,
            characters=characters,
            byte_lengths=decoded.byte_lengths if decoded is not None else (),
            byte_indexed_advances=decoded.byte_indexed_advances if decoded is not None else True,
            escapement=request.escapement,
            glyph_indices=glyph_indices,
            vertical_advances=vertical_advances,
            vertical_scale=abs(sy),
            mirrored_layout=self.mapping.rtl,
            precise_origin=precise_origin,
        )
        if layout.position is not None:
            layout = replace(
                layout,
                position=self.mapping.advance_logical_position(self._state.position, origin, layout.position),
                fixed_position=tuple(
                    start + math.floor((end - pixel) * 16)
                    for start, end, pixel in zip(fixed_origin, layout.position, origin, strict=True)
                ),
            )
        return layout, rectangle

    def _linear_transform(self):
        """The world-to-device linear part (m11, m12, m21, m22), page scaling included."""
        if self.mapping.rotated:
            return self.mapping.world[:4]
        (sx, _), (sy, _) = self.mapping._transform()
        return (sx, 0.0, 0.0, sy)

    def _general_text(self, request):
        """GM_ADVANCED text whose font transform is not a positive scale takes general placement."""
        if self.mapping.graphics_mode != GM_ADVANCED:
            return False
        m11, m12, m21, m22 = self._linear_transform()
        return bool(m12 or m21 or m11 < 0 or m22 < 0 or request.escapement % 3600)

    def _transformed_text(
        self, request, face, characters, glyph_indices, fixed_origin, alignment, advances, options, vertical_advances
    ):
        """Realize and place a run from its 28.4 origin through its full notional-to-device matrix.

        See ``text_transform``.
        """
        text_state = self._state.text_state
        compatible = self._font_xform is not None
        upem = face.units_per_em
        m11, m12, m21, m22 = (Fraction(value) for value in self._linear_transform())
        if request.height < 0:
            em_height = Fraction(-request.height)
        elif request.height > 0:
            em_height = Fraction(request.height * upem, face.ascent + face.descent)
            em_height = Fraction(int(em_height * 65536), 65536)
        else:
            # The default height is a 16 pixel em on the device's y axis.
            em_height = Fraction(16) / Fraction(math.sqrt(float(m21 * m21 + m22 * m22)))
        if request.width:
            em_width = Fraction(abs(request.width) * upem, face.average_width)
        else:
            em_width = em_height * self._font_aspect()

        def notional_matrix(angle):
            # Notional (u, v), y up, to logical (x, y), y down, rotated by the angle.
            sine, cosine = text_rotation(angle)
            l11, l12 = em_width / upem * Fraction(cosine), -em_height / upem * Fraction(sine)
            l21, l22 = -em_width / upem * Fraction(sine), -em_height / upem * Fraction(cosine)
            return (
                m11 * l11 + m21 * l21,
                m11 * l12 + m21 * l22,
                m12 * l11 + m22 * l21,
                m12 * l12 + m22 * l22,
            )

        # GM_ADVANCED rotates glyphs by the orientation and lays the baseline
        # along the escapement; compatible records use the escapement for both.
        orientation = request.escapement if compatible else request.orientation
        matrix = notional_matrix(orientation)
        advance_matrix = notional_matrix(request.escapement) if orientation != request.escapement else None
        sine, cosine = text_rotation(request.escapement)
        font = TransformedFont(
            face.data,
            face.index,
            matrix,
            upem,
            # Vertical alignment takes the cell for scale-only transforms and
            # the font-wide outline bounds for rotating or shearing ones.
            *(face.outline_cell if matrix[1] or matrix[2] else (face.ascent, face.descent)),
            face.design_advances,
            quality=request.quality,
            ink_spans=face.ink_spans,
            advance_matrix=advance_matrix,
            oblique=bool(request.italic) and not face.italic,
            embolden=request.weight >= 700 > face.weight,
        )
        if glyph_indices is None:
            indices = []
            for character in characters:
                codepoint = ord(character)
                index = face.cmap.get(codepoint, 0)
                if not index and face.symbol and 0xF000 <= codepoint <= 0xF0FF:
                    index = face.cmap.get(codepoint - 0xF000, 0)
                if not index and self.fonts.missing_glyph == "error":
                    raise UnsupportedOperation(f"Missing glyph for U+{codepoint:04X}")
                indices.append(index)
        else:
            indices = list(glyph_indices)
        world_baseline = (
            float(m11) * float(cosine) - float(m21) * float(sine),
            float(m12) * float(cosine) - float(m22) * float(sine),
        )
        baseline = baseline_vector(advance_matrix or matrix, world_baseline)
        world_side = (
            -float(m11) * float(sine) - float(m21) * float(cosine),
            -float(m12) * float(sine) - float(m22) * float(cosine),
        )
        side = baseline_vector((matrix[1], 0, matrix[3], 0), world_side)
        scale = baseline[2]
        extra = _round_half_away(float32(text_state.character_extra * scale))
        break_count, break_total = text_state.justification
        break_extra = int(_round_half_away(float32(break_total * scale)) / break_count) if break_count > 0 else 0
        breaks = tuple(
            number for number, index in enumerate(indices) if index and index == face.cmap.get(face.break_character)
        )
        run = place_run(
            font,
            indices,
            fixed_origin,
            alignment,
            advances=advances,
            vertical_advances=vertical_advances,
            baseline=baseline,
            side=side,
            extra=extra,
            break_extra=break_extra,
            breaks=breaks,
            max_pixels=self.max_bitmap_pixels,
        )

        def pixels(points):
            return tuple((Fraction(x, 16), Fraction(y, 16)) for x, y in points)

        background = pixels(opaque_area(font, run, indices)) if self._state.background_mode == OPAQUE else None
        metrics = [
            m
            for m, on in ((face.underline_metrics, request.underline), (face.strikeout_metrics, request.strikeout))
            if on
        ]
        decorations = tuple(pixels(area) for area in decoration_areas(font, run, metrics))
        position = fixed_position = None
        if alignment & TA_UPDATECP and alignment & 6 != 6:
            # The current position moves by the run's advance, back for TA_RIGHT.
            sign = -1 if alignment & 6 == 2 else 1
            fixed_position = tuple(start + sign * step for start, step in zip(fixed_origin, run.advance, strict=True))
            position = self.mapping.logical_from_fixed(*fixed_position)
        return TextLayout(run.glyphs, background, position, decorations, fixed_position)

    def _font_aspect(self):
        """A metafile text record's font transform stretches the width by its y over x scale."""
        if self._font_xform is None:
            return 1
        x_scale, y_scale = self._font_xform
        if not x_scale or not y_scale:
            return 1
        return Fraction(abs(y_scale)) / Fraction(abs(x_scale))

    def _apply_set_font_xform(self, call, prepared, result):
        # A DC field, not saved by SaveDC: playback sets and clears it per record.
        a = call.kwargs
        self._font_xform = None if a["x_scale"] is None else (float32(a["x_scale"]), float32(a["y_scale"]))

    def _draw_text(self, layout, rectangle, options):
        painter = self._painter()
        painter.text(layout, rectangle, options)
        if layout.position is not None:
            self._state.position = layout.position
            self._state.text_position = (layout.position, layout.fixed_position)
        painter.decorations(layout, rectangle, options)

    def _pixel(self, x, y, color, *, operation=None):
        self._painter().pixel(x, y, color, operation=operation)

    def _line(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        self._stroke_path(DevicePath.polyline([(start[0] * 16, start[1] * 16), (end[0] * 16, end[1] * 16)]))

    def _stroke_path(self, path, *, miter=False, extend=False):
        """Stroke, or while recording a path add ``path`` as a figure.

        ``extend`` continues the open figure that ends where ``path`` starts,
        as LineTo and the other current-position calls do.
        """
        if self._state.recording_path:
            self._record_figure(path, extend=extend)
            return
        self._painter().stroke_path(path, miter=miter)

    def _record_figure(self, path, *, extend=False):
        if not path.commands:
            return
        figures = list(self._state.path or ())
        if extend and figures and not figures[-1][1] and figures[-1][0][-1][-1] == path.commands[0][0]:
            figures[-1] = (figures[-1][0] + path.commands, path.closed)
        else:
            figures.append((path.commands, path.closed))
        self._state.path = tuple(figures)

    def _stroke_fragments(self, paths, *, miter=False):
        return self._painter().stroke_fragments(paths, miter=miter)

    def _paint_polygons(self, paths, *, miter=False, reserve_outline=False, brush=None):
        if self._state.recording_path:
            for path in paths:
                self._record_figure(replace(path, closed=True))
            return
        self._painter().paint_polygons(paths, miter=miter, reserve_outline=reserve_outline, brush=brush)

    def _path_figures(self, *, close):
        """The recorded figures as device paths, explicitly closed when ``close``."""
        result = []
        for commands, closed in self._state.path or ():
            start, end = commands[0][0], commands[-1][-1]
            if (close or closed) and start != end:
                commands = (*commands, (end, start))
            result.append(DevicePath(commands, closed=close or closed))
        return tuple(result)

    def _apply_begin_path(self, call, prepared, result):
        self._state.path, self._state.recording_path = (), True

    def _apply_end_path(self, call, prepared, result):
        self._state.recording_path = False

    def _apply_abort_path(self, call, prepared, result):
        self._state.path, self._state.recording_path = None, False

    def _apply_close_figure(self, call, prepared, result):
        figures = list(self._state.path or ())
        if self._state.recording_path and figures and not figures[-1][1]:
            commands, _ = figures[-1]
            start, end = commands[0][0], commands[-1][-1]
            figures[-1] = ((*commands, (end, start)) if start != end else commands, True)
            self._state.path = tuple(figures)

    def _completed_path(self):
        """Path operations fail natively, drawing nothing, without a completed path."""
        return not self._state.recording_path and self._state.path is not None

    def _apply_fill_path(self, call, prepared, result):
        if not self._completed_path():
            return
        figures = self._path_figures(close=True)
        self._state.path = None
        unpenned = replace(self._state, pen=Pen((0, 0, 0), 0, PS_NULL))
        RasterPainter(self.surface, unpenned).paint_polygons(figures)

    def _apply_stroke_path(self, call, prepared, result):
        if not self._completed_path():
            return
        figures = self._path_figures(close=False)
        self._state.path = None
        painter = self._painter()
        for figure in figures:
            painter.stroke_path(figure)

    def _apply_stroke_and_fill_path(self, call, prepared, result):
        if not self._completed_path():
            return
        figures = self._path_figures(close=True)
        self._state.path = None
        self._painter().paint_polygons(figures)

    def _apply_flatten_path(self, call, prepared, result):
        if not self._completed_path():
            return
        figures = []
        for commands, closed in self._state.path:
            flat = DevicePath(commands).flattened()
            figures.append((flat.commands, closed))
        self._state.path = tuple(figures)

    def _apply_widen_path(self, call, prepared, result):
        # A cosmetic ExtCreatePen pen fails, keeping the path. CreatePen
        # styles are ignored: a styled pen widens as the solid pen does.
        if not self._completed_path() or self._state.pen.cosmetic:
            return
        # Each figure, flattened, becomes the closed outlines its pen strokes.
        outlines = self._painter().widened_outlines(self._path_figures(close=False))
        self._state.path = tuple(
            (DevicePath.polyline(outline, closed=True).commands, True) for outline in outlines if outline
        )

    def _prepare_select_clip_path(self, a):
        if a["mode"] not in range(1, 6):
            raise InvalidOperation(f"Region mode {a['mode']}")

    def _apply_select_clip_path(self, call, prepared, result):
        if not self._completed_path():
            return
        figures = self._path_figures(close=True)
        self._state.path = None
        if not figures:
            return  # A path without figures makes no region; the clip is kept.
        spans = self._painter().contour_spans(
            tuple(figure.flattened().vertices for figure in figures), fill_mode=self._state.polygon_fill_mode
        )
        region = RegionMask.from_rectangles((start, y, end, y + 1) for y, start, end in spans)
        if call.kwargs["mode"] == 5:
            self._state.clip = self._state.clip.select(region)
        else:
            bounds = (0, 0, self.surface.width, self.surface.height)
            self._state.clip = self._state.clip.combine(region, call.kwargs["mode"], bounds)
