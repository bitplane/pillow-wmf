"""Defined byte positions in Windows Symbol's legacy encoding.

The other positions select the missing glyph, including 0xA0 (not Euro) and
0xF0 (not the Apple glyph found in some PostScript-compatible Symbol fonts).
This repertoire is verified through WMF playback and native glyph lookup.
Glyph identities and outlines come from the selected Symbol font's cmap.
"""

WINDOWS_SYMBOL_BYTES = frozenset((*range(0x20, 0x7F), *range(0xA1, 0xF0), *range(0xF1, 0xFF)))
