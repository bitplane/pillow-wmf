"""Selected drawing objects and the state retained by SaveDC."""

from dataclasses import dataclass, field, replace

from .bitmap import DIBLayout, RGBBitmap
from .clip import ClipRegion
from .color_adjustment import NEUTRAL, ColorAdjustment
from .constants import ALTERNATE, BLACKONWHITE, BS_SOLID, OPAQUE, PS_SOLID, R2_COPYPEN
from .mapping import Mapping
from .objects import FontRequest
from .palette import LogicalPalette, PaletteIndex


@dataclass(frozen=True)
class Pen:
    color: tuple[int, int, int] | PaletteIndex
    width: int = 1
    style: int = PS_SOLID
    # ExtCreatePen geometric pens choose their end cap and join (PS_ENDCAP_*
    # and PS_JOIN_* indices). CreatePen pens are never geometric.
    geometric: bool = False
    cap: int = 0
    join: int = 0
    # Extended styles as alternating dash and gap lengths: logical units for
    # geometric pens, device pixels for cosmetic pens. Empty is unstyled.
    pattern: tuple = ()
    # A hatched or pattern brush that fills a geometric pen's footprint.
    brush: "Brush | None" = None
    # An ExtCreatePen PS_COSMETIC pen, which WidenPath cannot widen.
    cosmetic: bool = False


@dataclass(frozen=True)
class Brush:
    color: tuple[int, int, int] | PaletteIndex
    style: int = BS_SOLID
    hatch: int = 0
    pattern: RGBBitmap | DIBLayout | None = None
    monochrome: bool = False
    realizable: bool = True


@dataclass(frozen=True)
class TextState:
    """Logical font, alignment and spacing retained by SaveDC/RestoreDC."""

    alignment: int = 0
    character_extra: int = 0
    justification: tuple[int, int] = (0, 0)
    mapper_flags: int = 0
    font: FontRequest | None = None  # None uses the caller's configured default, if any.


@dataclass
class DrawingState:
    """Live DC state, also used for snapshots of its selected objects.

    Snapshotting copies the mutable mapping. Immutable pens, brushes, clips
    and text settings retain their identity. Palettes deliberately remain
    shared: their entries belong to the object, not to the saved DC.
    Images, font caches and handle allocation are owned by the context.
    """

    mapping: Mapping
    pen: Pen = field(default_factory=lambda: Pen((0, 0, 0), width=0))
    brush: Brush = field(default_factory=lambda: Brush((255, 255, 255)))
    position: tuple[int, int] = (0, 0)
    # The exact 28.4 current point after ArcTo or AngleArc, which the next
    # LineTo, PolylineTo or PolyBezierTo starts from; None otherwise.
    fixed_position: tuple[int, int] | None = None
    # The DC's cached 28.4 device position, which ArcTo starts from: the
    # device origin on a fresh DC and the device end point after LineTo,
    # PolylineTo, PolyBezierTo or PolyDraw; None (recomputed from the
    # logical position) after MoveTo, arcs, text and other drawing. A world
    # transform change does not update it.
    device_position: tuple[int, int] | None = (0, 0)
    # (logical position, 28.4 device position) after current-position text:
    # the next such run continues from the device point while the logical
    # position is unchanged.
    text_position: tuple[tuple, tuple[int, int]] | None = None
    clip: ClipRegion = field(default_factory=ClipRegion)
    polygon_fill_mode: int = ALTERNATE
    rop2: int = R2_COPYPEN
    background_mode: int = OPAQUE
    background_color: tuple[int, int, int] | PaletteIndex = (255, 255, 255)
    text_color: tuple[int, int, int] | PaletteIndex = (0, 0, 0)
    stretch_mode: int = BLACKONWHITE
    color_adjustment: ColorAdjustment = NEUTRAL
    miter_limit: float = 10.0
    brush_origin: tuple[int, int] = (0, 0)
    arc_direction: int = 1  # AD_COUNTERCLOCKWISE
    # The DC path: figures of (device commands, closed), and whether drawing
    # calls are being recorded into it rather than painted.
    path: tuple | None = None
    recording_path: bool = False
    palette: LogicalPalette = field(default_factory=LogicalPalette.default)
    text_state: TextState = field(default_factory=TextState)

    def snapshot(self):
        return replace(self, mapping=replace(self.mapping))


# Retain the previous raster module's import name.
SavedDC = DrawingState
