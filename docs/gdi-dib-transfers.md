# Unscaled 24-bit DIB transfers

The raster backend implements `dib_bit_blt` and `set_dib_to_device` for the
[24-bit BI_RGB profile](gdi-dib-brushes.md). It shares the bitmap decoder,
device mapping, clipping, brush sampler and Boolean ROP3 evaluator. It does
not use Pillow's resize or drawing algorithms.

## Transfer geometry and composition

Native pixels establish three realization rules, not a single rectangle rule:

| Operation | Source and destination geometry |
| --- | --- |
| Source-independent ROP3 | Existing PatBlt: ordered half-open destination edges, no source clipping |
| SRCCOPY | Pixel-addressed signed extents, source clipping, optional reflection |
| Other source-dependent ROP3 | Half-open BitBlt when unreflected; pixel-addressed source realization followed by composition when reflected |

For a pixel-addressed negative extent, the low coordinate is `origin + extent
+ 1`; a half-open negative extent instead uses `origin + extent`. The same
normalization applies to source and destination. `BlitAxis` then intersects the
source interval with the bitmap bounds, translates that interval to the ordered
destination bounds, and reverses its sampling direction if the signs differ.
There are no dimension-specific corrections or fixture lookups.

A reflected ternary blit behaves as though SRCCOPY first produces a zero-filled
intermediate bitmap and the requested ROP then combines the entire destination.
This is an **inferred realization model**, tested across all 256 truth tables:
unavailable source pixels become black inputs, rather than clipping away the
subsequent operation. The implementation evaluates this without allocating an
intermediate surface. Direct SRCCOPY leaves unavailable pixels untouched.

WMF source Y also depends on this realization: SRCCOPY uses top-left coordinates
for either storage orientation. The ternary path for a top-down DIB uses
`bitmap_height - src_y - height` before interval normalization. Bottom-up DIBs
use `src_y` after the decoder has normalized storage. This behavior is native
evidence, not an assumption that DIB API documentation alone describes WMF.

All source transfers bypass DC ROP2. Pattern sampling is device-anchored and
opaque, including hatch gaps regardless of background mode. A null brush blocks
only pattern-dependent truth tables. The no-embedded-DIB record uses PatBlt;
it does not copy pixels from the playback surface. ROP truth-table bits, not
the low opcode word, choose the Boolean operation.

Mapped source-dependent transfers now also use the shared
[stretch sampler](gdi-dib-stretching.md) for modes 1–3 and native fixed-point
HALFTONE, including source clipping on replication and filtered paths.

## SetDIBitsToDevice bands

This call maps the destination origin only. Its width, height and source
coordinates stay in pixels; mapping does not stretch or reflect the pixels.
WMF WORD coordinates and extents are sign-extended at playback, while scan
indexes and counts remain unsigned.

Let `start` be StartScan, `count` be cLines, and `h` be the requested height:

- Bottom-up data clamps `count` to `bitmap_height - start`; top-down data
  retains the count for positioning.
- Decode the first `min(count, bitmap_height)` rows of the supplied pixel
  buffer in its storage orientation. **StartScan does not skip buffer rows.**
- The source Y within this decoded band is `start + count - src_y - h`.
- Transfer the visible intersection using SRCCOPY. Empty sizes/counts and
  out-of-range starting scans draw nothing.

WMF requires the full packed DIB buffer even when transferring a band. Short
buffers are ignored by native playback, including when `biSizeImage` is zero,
the band's byte count, or the full image byte count. This differs from the raw
Win32 pointer API's documented ability to supply only a band. The packed-object
backend follows WMF here; the low-level decoder can still decode a bounded band.
Header validity and the full-image pixel budget are checked before allocation.

## Evidence and remaining scope

The 45 committed WMF/PNG pairs cover source cropping, padding, both orientations,
signed extents, translated/reflected mappings, destination clipping, full ROP3
atlases with solid/null/hatch/pattern brushes, source-independent clipping,
negative/reflected ternary atlases, low ROP code bits, band positioning,
scaled destination-origin mapping and short-buffer validation.

Windows only generated missing images, in three focused runs:
[initial 30](https://github.com/bitplane/pillow-wmf/actions/runs/35197119747),
[eight boundary cases](https://github.com/bitplane/pillow-wmf/actions/runs/35197480275),
[seven realization cases](https://github.com/bitplane/pillow-wmf/actions/runs/35197816588).
All exact comparisons and unit tests run locally/Linux; no reference images or
pixel tolerances were changed to accommodate the implementation.

Sources consulted: [MS-WMF DIBBITBLT](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/524aa748-f274-4bd3-a4c1-f280bd6cac09),
[SetDIBitsToDevice](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-setdibitstodevice),
[StretchDIBits](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-stretchdibits),
[Wine DIB realization](https://github.com/wine-mirror/wine/blob/master/dlls/win32u/dib.c)
and [Wine WMF playback](https://github.com/wine-mirror/wine/blob/master/dlls/gdi32/metafile.c).
Wine corroborates separate copy/ternary and band paths, but Windows remains
the oracle. The implementation is not a transcription of Wine's source.

Still unsupported: indexed and other pixel formats, additional headers,
compression, palettes and legacy Bitmap16 blits.
Fonts remain deferred.
