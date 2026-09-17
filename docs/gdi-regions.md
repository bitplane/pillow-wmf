# WMF region creation and clipping

The first region slice implements `CreateRegion`, `SelectClipRegion`, region
selection through `SelectObject`, and composition with existing rectangular
clipping, offsets and SaveDC/RestoreDC. Region painting and framing remain the
next slice; text and bitmap support are not prerequisites for this one.

## Coordinate and object contracts

[SelectClipRgn](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-selectcliprgn)
copies a region in device units. Selection replaces the application clip; it
does not intersect the previous clip. Subsequent mapping changes do not move
the region, and deleting the source object does not release the selected clip.
SaveDC preserves the clip value independently of the source object's lifetime.

The WMF [Scan structure](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/ae8f7607-b1dc-4d58-a958-70f517c6d152)
describes unsigned words and logical units. Native playback nevertheless treats
the scan coordinates as signed 16-bit device coordinates. The structural codec
preserves the raw unsigned words; raster realization interprets the sign.
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

The native handle probe observes both the creation return value and
`GetObjectType`, distinguishing those outcomes rather than inferring them from
a blank image; see [the initial measurement run](https://github.com/bitplane/pillow-wmf/actions/runs/35171737945).
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

## Verification

Committed Windows references cover rings/holes, overlap, negative coordinates,
misleading bounds, mapping changes, replacement, offsets, save/restore,
intersection/exclusion, reset, null objects and slot-zero selection. The manual
`probe-windows-regions.py` additionally asserts native object creation outcomes,
15 displacement cases, and exact cross-primitive pixel comparisons.
