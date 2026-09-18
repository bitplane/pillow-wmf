# Flood fills

`FloodFill` and `ExtFloodFill` share a four-connected device-pixel scanline
search. Border mode accepts pixels different from the supplied colour; surface
mode accepts only that colour. The mapped seed must be on the image, inside the
clip and eligible. Otherwise no pixels change. The image edge and excluded clip
pixels stop connectivity, not just painting. Diagonal contact does not connect
components; a one-pixel orthogonal bridge does.

Discovery finishes before painting. Disjoint spans are visited once using a
byte-per-image-pixel visitation map and an explicit work stack, avoiding Python
recursion limits. The existing brush sampler and ROP2 compositor then paint the
spans. Transparent hatch gaps, null brushes, unchanged colours and destination-
dependent raster operations do not change which component is discovered.
No drawing state or current position is changed.

## Evidence

[Microsoft's ExtFloodFill contract](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-extfloodfill)
defines both colour predicates and rejected seeds.
[Wine's DIB driver](https://github.com/wine-mirror/wine/blob/master/dlls/win32u/dibdrv/graphics.c)
provides supporting evidence for clip-bounded scanline discovery separated from
brush painting; the implementation here is independent and non-recursive.

WMF/PNG comparisons cover both modes, all 16 ROP2 operations with solid/null/opaque
hatch/transparent hatch brushes, multicoloured interiors, diagonal contacts,
one-pixel bridges, clip holes/walls/disconnected regions, invalid seeds,
unbounded fills, mapped/reflected seeds, unchanged output and legacy FloodFill.
Unit tests compare span discovery to an independent pixel breadth-first search
over deterministic random surfaces and exercise a 10,000-row component.

The target is an RGB surface; colour resolution and brush sampling use shared
DC state. Unknown fill modes remain explicitly unsupported.
