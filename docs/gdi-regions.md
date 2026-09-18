# WMF regions: creation, clipping and painting

The backend implements `CreateRegion`, `SelectClipRegion`, region
selection through `SelectObject`, and composition with existing rectangular
clipping, offsets and SaveDC/RestoreDC. `FillRegion`, `PaintRegion`,
`InvertRegion` and `FrameRegion` paint through the same clip and brush
compositing machinery.

## Coordinate and object contracts

[SelectClipRgn](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-selectcliprgn)
copies a region in device units. Selection replaces the application clip; it
does not intersect the previous clip. Subsequent mapping changes do not move
the region, and deleting the source object does not release the selected clip.
SaveDC preserves the clip value independently of the source object's lifetime.

The WMF [Scan structure](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/ae8f7607-b1dc-4d58-a958-70f517c6d152)
describes unsigned words and logical units. Native playback nevertheless treats
the scan coordinates as signed 16-bit values and applies no mapping during
creation. Clip selection uses those values as device coordinates; painting
uses them as logical coordinates. The structural codec preserves the raw
unsigned words; raster realization interprets the sign.
The scan rectangles, rather than the advisory region bounds, determine coverage.
Overlapping scans form a union. Left/top edges are included; right/bottom are
excluded. These rules agree with the relevant region playback construction in
[Wine](https://github.com/wine-mirror/wine/blob/master/dlls/gdi32/metafile.c),
but Windows PNGs and direct native measurements are the test oracle.

Two distinct null conventions matter:

- `META_SELECTCLIPREGION` index zero removes clipping, even if object slot zero
  contains an object. The GDI API accepts `select_clip_region(None)` for this.
  The recorder rejects a non-null region in slot zero rather than silently
  recording a reset. `select_object(region)` can select that region instead;
  alternatively create another object before creating the clip region.
- Native `META_CREATEREGION` with zero scans fails and leaves a null object in
  its slot. Selecting it as a clip removes clipping; `SelectObject` on it fails
  without changing state. A nonzero scan count with zero covered area instead
  creates a real empty region, which suppresses all drawing when selected.

Backend handles retain the file object's identity, including
the null result, so subsequent records preserve native behavior.

Failed creations do not occupy native WMF object slots. Playback asks the
backend whether a creation produced a null object and keeps that slot available
for the next allocation. Unallocated table entries represent native null
objects when selected; explicit deleted-handle and out-of-table references
retain the player's validation errors. Non-emulating trace/recording backends
retain their structural allocation model: recording a deliberately failed
creation can therefore produce different subsequent native selections. Use a
zero-area scan, not zero scans, when recording a valid empty region.

`OffsetClipRgn` maps a displacement without origins and rounds half ties away
from zero. For scale `(1.5, 0.5)`, `(7,-9)` becomes `(11,-5)`. This differs from
ordinary coordinate rounding and has its own mapping operation and native
assertions; changing the general point-rounding rule would be incorrect.

## Representation

`RegionMask` uses immutable, disjoint horizontal bands with sorted horizontal
interval endpoints. An event sweep unions the input rectangles and merges
adjacent identical bands. Point membership uses binary searches, not a scan of
every input rectangle or a bitmap-sized allocation.

`ClipRegion` combines an optional finite mask with rectangular constraints.
No finite mask means unrestricted application clipping; an empty mask means
empty clipping. Off-surface coordinates are retained so offsetting can move
them into view. Every drawing primitive uses the existing final pixel clip;
there are no per-primitive region rendering branches.

## Painting and frame realization

Unlike clip selection, painting maps region coordinates into device space at
the time of the paint call. The region object itself remains unchanged.
`PaintRegion` uses the selected brush; `FillRegion` and `FrameRegion` use their
explicit brush without changing the selection. These three operations use
ROP2 and the shared device-space hatch/background rules. `InvertRegion`
complements destination RGB irrespective of the selected brush and ROP2,
without modifying either state. All four obey the application clip.

The frame is an **inner rectangular morphological border**, not the outlines
of the individual scan rectangles. Dilating the region's complement and
intersecting it with the region handles holes, narrow arms, disconnected
islands and concave corners without introducing scan-band seams. The complement
is formed in source coordinates before mapping: collapsing a narrow gap must
not erase the source contour. A gap mapped to a line retains a framed seam
with flat ends; a gap mapped to a point has no remaining edge. Region
subtraction and dilation operate on bands, not bitmap-sized masks.

Realize the device footprint as follows:

1. Map stored edges with the shared driver-point conversion, retaining source
   boundary topology. Quantize translation and scaled coordinates separately
   to signed 28.4 before rounding to pixels.
2. Take absolute logical dimensions. Use twice the larger dimension as a
   common geometric-pen width and normalize the shorter axis of its transform.
   The normalization and transform multiplication use IEEE single precision.
3. Transform the signed full pen bases to 28.4 fixed point, then halve away
   from zero. Realize the pen with the shared polygonal-pen machinery.
4. Intersect its edges with the axis normals. The native widener rounds the
   edge midpoint and interpolation separately; for an odd positive edge
   difference this can advance the intersection by one fixed unit. Contour
   traversal order matters. Quantize x support inward and y support outward
   on the half-pixel grid using the existing body-support rule.
5. Split the resulting footprint: ceil-half on left/top,
   floor-half on right/bottom. An odd footprint is therefore asymmetric.
6. Paint the resulting border with the explicit brush and existing ROP2/clip.

A zero dimension paints nothing. Negative dimensions are made positive before
normalization; a reflected mapping still affects signed basis conversion.
Simply rounding the doubled mapped dimensions is not equivalent. In particular, under a 3/4
horizontal scale with unit vertical scale, logical widths 1, 3 and 5 (height 1)
produce full device widths 1, 4 and 8, rather than 2, 5 and 8. There is no
width-specific adjustment: the same pen-edge arithmetic produces these values.

Microsoft's [FrameRgn documentation](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-framergn)
establishes the logical-unit parameters. Wine's
[painting fallbacks](https://github.com/wine-mirror/wine/blob/master/dlls/win32u/painting.c)
are useful for brush and ROP semantics, but its
[region framing](https://github.com/wine-mirror/wine/blob/master/dlls/win32u/region.c)
explicitly notes a difference from Windows and is not our framing oracle.

## Verification

WMF/PNG comparisons cover holes, overlapping scans, signed coordinates,
misleading bounds, clip replacement and offsets, save/restore, null objects,
slot reuse, and all four region paint operations. Frame cases cover fractional
and reflected mappings, collapsed gaps and fixed-point edge thresholds.

Rectangle's block fill simplifies brush-independent ROPs before hatch
transparency; region/path fills retain the transparent pattern mask even for
BLACK, WHITE and NOT. Brush realization handles that distinction; the pixel
compositor and hatch definition are shared. Cross-primitive fixtures exercise
these painting policies with explicit and selected brushes.
