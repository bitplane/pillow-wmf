# DIB pattern brushes

`bitmap.py` separates pixel decoding from WMF envelopes and rendering. Its
immutable `RGBBitmap` holds top-down RGB bytes. `encode_dib24` writes packed
BITMAPINFOHEADER DIBs for recording; `decode_dib` validates and decodes the same
pixel representation without changing the original `BitmapData` or its lossless round trip.

```python
from pillow_wmf import Recorder
from pillow_wmf.bitmap import RGBBitmap, encode_dib24

tile = RGBBitmap(2, 1, bytes((255, 0, 0, 0, 128, 255)))
recorder = Recorder()
brush = recorder.create_dib_pattern_brush(5, 0, encode_dib24(tile))
recorder.select_object(brush)
recorder.pat_blt(0, 0, 128, 128, 0x00F00021)
source = recorder.to_bytes()
```

## Pixel storage and limits

The example uses 24-bit BI_RGB data with BGR triples and DWORD-padded rows.
The decoder also supports the headers, depths, compression and palette layouts
listed in [DIB formats](gdi-dib-formats.md) and [palettes](gdi-palettes.md).
Both storage orientations become a canonical top-down bitmap.

Required bytes are computed from dimensions, stride and table length, not
allocated from `biSizeImage`. Validate geometry, planes, truncation and decoded
pixel budget before allocation. `RasterContext(max_bitmap_pixels=...)` and the
decoder's `max_pixels` bound each bitmap, not the aggregate across saved objects.
Unsupported formats raise `UnsupportedOperation`; malformed supported data
raises `FormatError` before allocating a renderer handle.

## Brush realization

Ordinary DIB brushes repeat the complete tile in device coordinates with origin
(0, 0), using modulo width/height. They are not forced to 8x8, scaled with the
logical mapping, restarted at a clip boundary or made transparent by background
mode. A single brush sampler serves PatBlt, rectangles, ellipses, polygons,
regions and flood fills, with their existing ROP2/ROP3 rules.

The record's BS_PATTERN (style 3) path differs from ordinary DIB brushes:

1. Positive-height RGB input is realized as monochrome: exact white becomes
   one, every other RGB value becomes zero. This is colour-key conversion, not
   a luminance threshold or a palette quantizer.
2. At painting time, zero uses the DC text colour and one uses its background
   colour, even in transparent background mode. `SetTextColor` is therefore
   implemented as drawing state and included in SaveDC/RestoreDC; glyph/font
   rendering remains unsupported.
3. Top-down input fails native legacy brush creation. A null handle is recorded
   and selecting it leaves the previous brush unchanged, using the existing
   failed-object/file-slot machinery.
4. Style 3 forces RGB colour usage. Other tested style values (0, 1, 2, 5, 6, 8)
   use the ordinary DIB-pattern path, including supported logical-palette usage.

These rules are measured against the reference DC, not inferred from the colour
depth of the final RGB output image. A compatible monochrome DDB intermediate
explains the legacy conversion; Wine's current WMF player treats the styles as
equivalent and is not an oracle for this distinction.

## Coverage and references

WMF/PNG cases cover row padding, non-8x8 tiles, both orientations, shared paint
consumers, Boolean operations, mapping, clipping, saved/deleted brushes, style
aliases, creation failure and live monochrome colours.

References: [BITMAPINFOHEADER](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-bitmapinfoheader),
[CreateDIBPatternBrushPt](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createdibpatternbrushpt),
[CreateDIBitmap](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createdibitmap),
and [Wine WMF playback](https://github.com/wine-mirror/wine/blob/master/dlls/gdi32/metafile.c).

## Related operations

[Unstretched DIB transfers](gdi-dib-transfers.md) reuse the decoder and Boolean
ROP3 evaluator. See also [DIB formats](gdi-dib-formats.md),
[stretching](gdi-dib-stretching.md), [palettes](gdi-palettes.md), and
[legacy Bitmap16](gdi-bitmap16.md).
