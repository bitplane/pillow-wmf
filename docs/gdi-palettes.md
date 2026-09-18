# Logical palettes on the RGB reference device

The renderer implements CreatePalette, SelectPalette, RealizePalette,
SetPalEntries, AnimatePalette and ResizePalette. A DC initially selects the
20-entry Windows default logical palette. Palette objects own mutable entries;
SaveDC/RestoreDC retains the selected object, not a snapshot of its contents.

Entry updates stop at the existing palette boundary. Animation replaces only
entries whose **old** flags include PC_RESERVED, including replacing their
flags. Shrinking discards entries; growing supplies black entries with zero
flags. Stock-palette mutations and unsuccessful selections leave state intact.

This is an RGB device, not an emulated 256-colour display. RealizePalette does
not remap a hardware colour table or recolour pixels already drawn. Subsequent
draws observe logical entry changes without requiring realization. PC_EXPLICIT
references a hardware palette; on this target those entries translate to black.
PC_NOCOLLAPSE has no visible effect on this target.

## DIB consumers

The DIB layout retains unresolved WORD entries for DIB_PAL_COLORS. A logical
palette must be supplied to decode them; the codec does not invent a DC or
default palette. DIB table indexes wrap modulo the logical palette's length.
Transfers resolve once, then use the same RGB raster/ROP/HALFTONE pipeline as
literal-colour DIBs. Indexed 1/4/8-bit, RLE, orientation and Info/V4/V5 layouts
share that resolution step.

Palette DIB brushes retain their table and packed samples. Drawing resolves
them against the drawing DC's current palette, including mutations, a different
selected palette, and restore operations. They must not capture RGB pixels at
creation time. The packed-brush storage path DWORD-aligns the WORD table;
separate transfer header/bits pointers do not. Odd-count probes and explicit
padding sentinels distinguish these layouts. The native brush copy's terminal
alignment space is zero-filled in the measured cases; this is modelled only
after validating the original image extent, not as general truncation recovery.

DIB_PAL_INDICES has no table. The codec can interpret its indexed samples with
an explicit palette, but native playback on the RGB target rejects the indexed
transfers and brushes. This is a device/consumer decision, not a malformed-file
decision. Table-free 32-bit RGB copies do work: their depth matches the native
reference surface, so no colour translation is needed. This same device-depth
check is shared by transfers and brushes; 16/24-bit direct-index sources fail.

`encode_dib(..., color_usage=1, colors=(...))` writes WORD indexes;
`color_usage=2` writes table-free samples. The usage still belongs in the WMF
record; it is not a field in the DIB header. RGB writer output is unchanged.

## COLORREFs

PALETTEINDEX colours are logical references, distinct from literal RGB tuples.
Out-of-range COLORREF indexes fall back to entry zero, unlike DIB-table modulo
indexing. PALETTERGB is literal RGB on this true-colour target; it is not rounded
to the nearest logical palette entry.

## Evidence and scope

`palette-*` WMF/PNG pairs cover default entries, selection, object mutation,
animation flags, shrink/growth, nested saves, DIB transfers and brushes, table
bounds and packing, colour-reference realization and direct-index rejection.
Native PNGs are produced by missing-only Windows jobs; comparisons run locally
or on Linux with zero pixel tolerance. Existing references are not regenerated.

Hardware palette allocation, foreground/background palette competition,
display-wide animation and ICM are not implemented.
[Legacy Bitmap16](gdi-bitmap16.md) is covered separately.
The reference device's RGB behaviour must not be mistaken for a claim
to emulate every historical display depth.

References: [WMF ColorUsage](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/30403797-a408-40ca-b024-dd8a1acb39be),
[palette objects](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/3ff2d783-b934-4049-bba3-67fe157fb3d5),
[palette flags](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/45e5c320-55b4-4f3a-af55-40f9e0f6e3ac),
[logical palettes](https://learn.microsoft.com/en-us/windows/win32/gdi/logical-palette),
[packed DIB brushes](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createdibpatternbrushpt).
Wine's [palette](https://github.com/wine-mirror/wine/blob/master/dlls/win32u/palette.c)
and [brush](https://github.com/wine-mirror/wine/blob/master/dlls/win32u/brush.c)
implementations informed the separation of logical objects and device
realization; native PNGs determine the actual reference-device behaviour.
