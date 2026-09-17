# Legacy Bitmap16 on the Windows reference device

This slice covers `META_BITBLT`, `META_STRETCHBLT`, and
`META_CREATEPATTERNBRUSH`. The target is the existing Windows 2025 x64,
32-bit RGB reference surface, not an emulation of every historical display
driver. There are 84 independent WMF/Windows-PNG cases. PNGs were generated
only when missing; all comparisons and unit tests run locally/Linux.

Native batches: [initial layouts](https://github.com/bitplane/pillow-wmf/actions/runs/35227911644),
[version 1 controls](https://github.com/bitplane/pillow-wmf/actions/runs/35228367402),
[native layout and transfer controls](https://github.com/bitplane/pillow-wmf/actions/runs/35229181264),
[brush realization](https://github.com/bitplane/pillow-wmf/actions/runs/35229499646),
and [depth/ROP holdouts](https://github.com/bitplane/pillow-wmf/actions/runs/35230315161).

## Storage and recording

`bitmap16.py` reads and writes device samples without a DIB header or colour
table. Rows are top-down, WORD-aligned, and packed MSB-first at 1/4 bits or
little-endian at 8/16/24/32 bits. Width and height are positive signed WORDs;
the supported plane count is one. Pixel budgets are checked before decoding.
The reader exposes incomplete pixel arrays; decoding them raises `FormatError`.
The original WMF reader/writer still preserves opaque bytes exactly.

There is no invented palette for an indexed device bitmap: decoding 4/8-bit
samples requires the device's colour table. Likewise, standalone 16-bit
decoding requires explicit device channel masks, rather than assuming the
DIB RGB555 convention. RGB24/32 use BGR channels and ignore the high byte.

`encode_bitmap16(..., pattern=True)` writes the documented Pattern Object
with pixel offset 32. For the measured native layout, also pass
`native_pattern=True`: it writes pixel offset 36. The corresponding reader
option is explicit; payload length does not select a guessed format.

The Bitmap16 transfer path derives row pitch from width/depth. Pattern brush
creation uses `CreateBitmapIndirect` and honours `WidthBytes`, including extra
even row padding; shorter-than-required or odd pitches are invalid.

References: [Bitmap16 Object](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/dc487315-3bb9-40c8-9f49-55ffc6152d8c),
[CreateBitmap](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createbitmap),
and [CreateBitmapIndirect](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createbitmapindirect).

## Native playback findings

The initial spec-layout brushes and embedded transfers produced no bitmap
output. Header version 0x0100 controls behaved identically to 0x0300.
These results were investigated before implementing no-output behaviour.

The inspected Microsoft `gdi32full.dll` is version 10.0.26100.9444, SHA256
`bde2077a56c90f68c5fa1ce5ebd4a40755c97a5080b91a87d2beff47349dd01e`.
The binary and its public PDB came from Microsoft's symbol server:
[binary](https://msdl.microsoft.com/download/symbols/gdi32full.dll/3516563F129000/gdi32full.dll),
[symbols](https://msdl.microsoft.com/download/symbols/gdi32full.pdb/A6245E4F5C78EB06438EA4820F1F6EB41/gdi32full.pdb).
Addresses below are RVAs, not runtime addresses. This inspected build explains
the oracle observations; it is not a claim about all Windows builds.

- `PlayMetaFileRecord` (0x3a270), legacy transfers: the Bitmap16 starts at
  record byte 22 for BITBLT and 26 for STRETCHBLT. `CreateBitmap` receives the
  correct dimensions, planes, depth and bits. At 0x3b09f the old handle returned
  by `SelectObject` is tested; the **nonzero** branch at 0x3b0a2 goes to DC
  cleanup at 0x3bbfb, skipping the actual transfer. Monochrome and matching
  RGB32 bitmaps select successfully, suppressing even PATCOPY and DSTINVERT.
  Other depths fail selection into the RGB32 memory DC and reach the transfer
  call: source-independent ROPs work, but source-dependent ROPs cannot draw
  without a usable selected source. Two full depth/ROP atlases distinguish
  these paths. This is a playback-path quirk, not a rule that Win32 BitBlt
  cannot draw DDBs, nor a blanket no-op for every embedded transfer.
- The pattern handler (0x3c080) copies the record with a two-byte leading pad,
  then reads bits at allocation byte 44: **payload byte 36**, not 32. Its size
  check also requires the additional four bytes. The native-layout positive
  controls draw successfully; the original spec-layout controls remain intact.

With no embedded bitmap, the transfer uses the destination DC as its source.
Source-independent ROPs go through the existing PatBlt path. Source-dependent
operations snapshot the destination and map source coordinates through that DC.
There is no second stretch/ROP rasterizer for Bitmap16.

### Self-copy geometry

The [45 mapped self-copy references](https://github.com/bitplane/pillow-wmf/actions/runs/35238172460)
cover identity, fractional and negative scales, RTL at identity/fractional
scale, nonzero origins, overlap, destination clipping, source bounds, negative
extents, SRCCOPY and SRCINVERT, and COLORONCOLOR/HALFTONE stretching.
Sixteen initially failed; the fixes are in transfer preparation, not filtering
or pixel comparison.

With equal DC transforms, BitBlt transforms and orders two half-open rectangles.
RTL adds one device X unit to both rectangles' edges. The actual copy uses the
destination rectangle's size and the source rectangle's low corner. Their
independently rounded sizes need not agree: this does **not** invoke stretching.
For negative extents, transform the source's low logical corner independently;
subtracting the rounded destination size from the source anchor loses a pixel
at fractional scales. Both SRCCOPY and ternary ROPs use this geometry.

Native `GreBitBltInternal` in the same 26100.9444 win32kfull binary used for
[layout research](gdi-layout.md) establishes this: RVA 0x7a753 constructs the
source rectangle; 0x7a7d5 adds the RTL edge adjustment; 0x7a7e5 orders it.
Destination construction and equivalent steps are at 0x7a808–0x7a8be.
The shared `BlitAxis` scan copier then handles the prepared rectangle, retaining
the original source snapshot and destination-only DC clipping.

StretchBlt still maps independent source and destination extents through the
shared stretch/filter pipeline. A same-DC source already carries the RTL
transform; the DIB-only destination-anchor adjustment must not be applied to it.
The signed RTL references distinguish these contracts. Unit regressions retain
the fractional extent mismatch, negative-height source corner, and overlapping
snapshot semantics. This is tested coverage, not exhaustive proof of every
ROP, stretch mode, clipping region or extreme coordinate combination.

## Brush realization, not shape-specific exceptions

The positive native-layout brush cases establish:

- 1-bit patterns use the live DC text/background colours.
- 8-bit patterns use the device table: the first and last ten stock colours,
  with black entries between. A full 256-index atlas confirms all entries and
  confirms that selecting/realizing a custom logical palette does not change
  either an existing or newly created device pattern.
- 32-bit patterns tile their BGR colours; the high byte is ignored.
- 4/16/24-bit patterns create objects but cannot realize their fill on this
  reference device. Selection does not restore the previous brush. Outlines,
  independent lines and brush-independent PatBlt operations still work.
- An incomplete native payload instead fails object creation, leaving the
  previous brush selected and the object slot free for reuse.

`Brush.realizable` represents the device-format failure separately from a null
object or a null-style brush. The shared brush sampler suppresses unavailable
fill colours; polygons, rectangles and other consumers need no Bitmap16 branch.
Existing brush tiling, monochrome colour realization and Boolean operations
are reused unchanged. Padded and compact rows yield identical native output.

See [CreatePatternBrush](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createpatternbrush)
for monochrome colour semantics. The device table and failed-realization rules
above are native measurements, not claims made by that API documentation.

## Boundaries

This is compatibility with the measured modern WMF playback path. It does not
reconstruct how an old 4/8/16-bit display driver would draw embedded transfers
that modern playback skips. Unusual plane counts, invalid geometry and other
device formats remain explicit validation/unsupported boundaries; native
allocation-failure behaviour is not simulated. Fonts, hardware palette devices,
colour management and embedded JPEG/PNG/CMYK DIB payloads remain separate work.
