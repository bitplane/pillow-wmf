# DIB formats and native realization

`bitmap.py` separates packed layout validation, decoding and deterministic
writing. `encode_dib` records integer samples in an explicit depth, RGB table
or channel-mask layout; it does not quantize colours or choose a palette.
`encode_dib24` keeps its existing byte representation unchanged.

## Codec surface

- Core (12-byte), Info (40-byte), V4 (108-byte), V5 (124-byte) headers.
- BI_RGB: indexed 1/4/8-bit and direct 16/24/32-bit pixels. Core supports
  1/4/8/24-bit bottom-up images. Other supported uncompressed formats also
  support top-down rows.
- BI_BITFIELDS: contiguous, non-overlapping RGB masks in 16/32-bit words.
  Info masks follow the header; V4/V5 masks occupy their header fields.
- BI_RLE4/BI_RLE8: encoded and absolute runs, word-aligned literal payloads,
  EOL, EOB and delta commands, with bounded cursor movement and pixel budgets.
- RGBTRIPLE Core tables and RGBQUAD tables in the other headers. Explicit
  short tables are supported; out-of-table pixels are malformed.

RLE decoding returns index data and a separate coverage mask. Skipped locations
depend on the consumer: indexed bitmap realization fills them with colour-table
entry zero, ternary RGB realization uses black, and direct device transfers
preserve the destination. See [compressed scan clipping](gdi-dib-transfers.md#compressed-scan-clipping).
No allocation uses the untrusted `biSizeImage`; dimensions are budget-checked,
and compressed data is bounded by its declared extent and actual payload.

Uncompressed partial bands still read from the beginning of the supplied pixel
buffer, using the requested band height for storage orientation. RLE device
transfers consume the complete compressed image rather than treating it as a
sequence of independently addressable compressed scanlines.

## Conversion is a consumer contract

Ordinary GDI transfers expand a short channel by repeating its bits. A five-bit
value becomes `(v << 3) | (v >> 2)`; wider-than-eight-bit fields discard low bits.
HALFTONE's source loader instead shifts short fields into the high bits and
leaves the low bits zero. Neither path scales by `255 / maximum`.
The distinction also applies to equal-size transfers while HALFTONE is selected.
Ternary ROP transfers downgrade HALFTONE and retain ordinary conversion.

BI_RGB 16-bit pixels use RGB555. The high byte of BI_RGB 32-bit pixels is not
alpha. V4/V5 alpha fields do not cause these WMF raster operations to blend.

The codec can decode valid Core DIBs, but the current Windows WMF playback
profile rejects them in the tested transfer and DIB-brush records. RLE DIB
brushes and V4/V5 BITFIELDS DIB brushes also fail creation; selecting that failed
handle leaves the previous brush selected. These are playback/realization
decisions, not reasons to break an otherwise valid codec.

## Bitmap realization and HALFTONE source fixup

The BitBlt record paths realize a canonical black/white 1-bit table as a
monochrome bitmap. Its zero/one bits use the destination text/background colours.
STRETCHDIB instead retains the explicit RGB table. An unscaled monochrome
DIBBitBlt takes the direct-copy path, bypassing HALFTONE filtering.

`CheckBMPNeedFixup` has separate scan-fixup and replication flags. Eligible
1/4-bit sources and small images (at most 2304 clipped source pixels) enable
both. Larger 8-bit/direct-colour images run the existing bounded colour census;
they can replicate without scan fixup. The census operates on original pixels,
not the additional colours introduced by filtering. The dimension/ratio gate
still applies before either flag is used.

`halftone_fixup.py` models `FixupColorScan`/`FixupGrayScan` before resampling,
including at 1:1 scale, shared by all source depths:

1. Read original adjacent scans, looking for a 2x2 alternating cell `AB/BA`.
2. If alternating neighbours continue horizontally or vertically, overwrite
   the cell's four output pixels with the rounded channel-wise mean of A/B.
3. Otherwise compare `4*R + 8*G + B` and update the brighter diagonal. Each
   update is `(12*previous_output + four_original_neighbours + 8) >> 4`.
4. Traverse rows then columns. Writes accumulate, but pattern decisions use
   original samples. Lookahead reflects the adjacent sample at boundaries.

This is an edge-pattern filter, not bilinear interpolation. Inverted palettes
need not produce complementary results because the brighter diagonal is chosen.
The reduction/expansion and ROP compositors remain shared with other depths.

## Evidence and limits

`dib-format-*` references cover header/depth/orientation combinations, RGB555,
RGB565, RGB444, reversed RGB masks and 10-bit channels; all four stretch modes,
ternary ROPs, mirrors, crops, bands and brushes. Independent unit byte strings
check packing and commands rather than relying exclusively on round trips.
Channel ramps distinguish replication from linear scaling and HALFTONE shifts.
Monochrome cases cover constant, checker and diagonal patterns with six tables;
holdouts enumerate every binary 3x3 neighbourhood in both colour orders.
The copy-dispatch atlas varies DC colours, palette order, operation and mapping
scale. Cross-depth checker/diagonal holdouts cover both sides of the small-image
census boundary; the same RGB source at 1/4/8/24 bits distinguishes source-format
dispatch from filtering arithmetic.

[Logical palettes](gdi-palettes.md) adds DIB_PAL_COLORS and
DIB_PAL_INDICES layout handling and native RGB-device realization.
[Bitmap16](gdi-bitmap16.md) is covered separately.
Unsupported: JPEG/PNG/CMYK payloads, linked/embedded profiles and
ICM colour management. V4/V5 header acceptance is not a claim of ICM support.
Linked/embedded profiles are rejected explicitly and never followed as paths.

Sources: [BITMAPINFOHEADER](https://learn.microsoft.com/en-us/previous-versions/dd183376(v=vs.85)),
[bitmap header types](https://learn.microsoft.com/en-us/windows/win32/gdi/bitmap-header-types),
[RLE command format](https://learn.microsoft.com/en-us/windows/win32/gdi/bitmap-compression),
and [Wine's DIB conversion primitives](https://github.com/wine-mirror/wine/blob/master/dlls/win32u/dibdrv/primitives.c).
Native PNGs, rather than Wine's modern filtering implementation, determine pixel
compatibility for this reference device.
