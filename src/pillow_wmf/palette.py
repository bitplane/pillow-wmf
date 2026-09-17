"""Logical palette objects for the RGB reference device.

DC snapshots retain an object reference, not a copy of its mutable entries.
There is no display-wide hardware palette to animate on this device.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PaletteIndex:
    index: int


DEFAULT_COLORS = (
    (0, 0, 0),
    (128, 0, 0),
    (0, 128, 0),
    (128, 128, 0),
    (0, 0, 128),
    (128, 0, 128),
    (0, 128, 128),
    (192, 192, 192),
    (192, 220, 192),
    (166, 202, 240),
    (255, 251, 240),
    (160, 160, 164),
    (128, 128, 128),
    (255, 0, 0),
    (0, 255, 0),
    (255, 255, 0),
    (0, 0, 255),
    (255, 0, 255),
    (0, 255, 255),
    (255, 255, 255),
)


@dataclass(eq=False)
class LogicalPalette:
    entries: tuple
    stock: bool = False

    @classmethod
    def default(cls):
        return cls(tuple((*c, 0) for c in DEFAULT_COLORS), stock=True)

    def update(self, start, entries, *, animate=False):
        if self.stock:
            return
        values = list(self.entries)
        for i, entry in enumerate(entries, start):
            if i >= len(values):
                break
            if not animate or values[i][3] & 1:
                values[i] = entry
        self.entries = tuple(values)

    def resize(self, count):
        if not self.stock and count:
            self.entries = self.entries[:count] + ((0, 0, 0, 0),) * max(0, count - len(self.entries))

    def colors(self):
        return tuple(self.color(i) for i in range(len(self.entries)))

    def color(self, index):
        entry = self.entries[index % len(self.entries)]
        # PC_EXPLICIT addresses a hardware palette. The RGB reference device
        # has no hardware entries; its translation is black.
        return (0, 0, 0) if entry[3] & 2 else entry[:3]

    def colorref(self, color):
        if isinstance(color, PaletteIndex):
            # COLORREF indexes fall back to entry zero; DIB WORD tables wrap.
            return self.color(color.index if color.index < len(self.entries) else 0)
        return color
