"""Selected drawing objects and the state retained by SaveDC."""

from dataclasses import dataclass, field, replace

from .bitmap import DIBLayout, RGBBitmap
from .clip import ClipRegion
from .constants import ALTERNATE, BLACKONWHITE, BS_SOLID, OPAQUE, PS_SOLID, R2_COPYPEN
from .mapping import Mapping
from .objects import FontRequest
from .palette import LogicalPalette, PaletteIndex


@dataclass(frozen=True)
class Pen:
    color: tuple[int, int, int] | PaletteIndex
    width: int = 1
    style: int = PS_SOLID


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
    clip: ClipRegion = field(default_factory=ClipRegion)
    polygon_fill_mode: int = ALTERNATE
    rop2: int = R2_COPYPEN
    background_mode: int = OPAQUE
    background_color: tuple[int, int, int] | PaletteIndex = (255, 255, 255)
    text_color: tuple[int, int, int] | PaletteIndex = (0, 0, 0)
    stretch_mode: int = BLACKONWHITE
    palette: LogicalPalette = field(default_factory=LogicalPalette.default)
    text_state: TextState = field(default_factory=TextState)

    def snapshot(self):
        return replace(self, mapping=replace(self.mapping))


# Retain the previous raster module's import name.
SavedDC = DrawingState
