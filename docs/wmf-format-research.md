# WMF format research and implementation scope

Research date: 2026-09-16. Baseline: Microsoft's **[MS-WMF] revision 18.0,
2024-04-23**, a 213-page specification. This report surveys the format's record,
object, state, bitmap, text, and escape surfaces and the product-behavior appendix.
It is an implementation scope and design proposal, not a completed compatibility
experiment. No Windows probes or rendering implementation were performed here.

Primary source: [MS-WMF publication and downloads][spec]. Section references in
this report refer to that revision. The [complete record inventory][inventory]
lists every top-level opcode and every enumerated escape, with section numbers.

## Findings

The reader/writer is a finite, approachable task. Pixel parity is substantially
larger because records interact through a stateful graphics device. Build broad
format coverage and a recording interface before tackling rasterization in
vertical slices.

| Surface | Count | What it actually means |
| --- | ---: | --- |
| Top-level record codes | 70 | 6 bitmap, 1 EOF, 20 drawing, 11 object, 31 state, 1 escape envelope |
| Additional headers | 2 | Standard header and optional placeable prefix; neither is an opcode |
| Graphics object types | 5 | Brush, font, palette, pen, region |
| Supporting structure types | 22 | Geometry, bitmap headers/data, color and palette structures |
| Enumeration families | 31 | Includes opcodes, escapes, raster operations, fonts, mapping and styles |
| Flag families | 4 | Font clipping, extended text output, horizontal/vertical text alignment |
| Escape subfunctions | 60 | 43 have dedicated payload sections; 17 are enumeration-only |
| Binary raster operations | 16 | Boolean functions of drawing color and destination |
| Ternary raster operations | 256 | Boolean functions of pattern, source and destination |

Counts were checked against the enum definitions and section inventory in the
downloaded specification. They are not estimates of equal-sized implementation
tasks. In particular, the 256 raster operations can share a Boolean evaluator;
they do not require 256 bespoke drawing algorithms. One text or bitmap record can
require far more work than several state records combined. [MS-WMF §§2.1–2.3][spec]

## Define the compatibility target

Proposed target: Windows GDI playback into a specified true-color memory bitmap,
with explicit canvas size, initial pixels, initial DC state, and device metrics.
Compare decoded RGB pixels exactly for non-text cases. Keep font qualifications
specific to cases, and still test text positioning, background rectangles,
clipping, and state changes.

This qualification matters: WMF can describe output to displays, printers and
plotters, and its initial state depends on the destination. A standard header
does not supply a universal pixel canvas. Placeable bounds and units help with
placement but do not replace the playback environment. Printer escapes,
PostScript passthrough, palette devices and device fonts make unrestricted
"pixel-perfect for every WMF on every device" an ill-defined goal.
[MS-WMF §§1.3, 1.5, 3.1.1–3.1.5][spec]

Proposed scope has three independently measurable parts:

1. **Structural coverage:** read/write all 70 record types, both headers, and
   their supported layout variants; preserve unknown records and escape bytes.
2. **Playback coverage:** implement the WMF object table and DC semantics;
   classify every operation as implemented, required-ignore, or unsupported for
   the chosen device. Expose diagnostics for skipped work.
3. **Rendering coverage:** match Windows for each supported operation and its
   meaningful state combinations, rather than counting a decoded opcode as done.

Printer job control, raw printer languages, device callbacks and embedded foreign
metafile execution should be outside the initial raster target. Preserve their
bytes and document their playback policy. These exclusions are recommendations
for the project, not claims that those features are absent from WMF.

## File framing and round trips

WMF is little-endian. The standard header is 18 bytes (9 words); it records the
metafile type, version, total word count, object-table capacity information,
largest record size, and an unused member count. The version enumeration has
0x0100 and 0x0300; the latter supports DIBs. The placeable prefix adds 22 bytes,
the key 0x9AC6CDD7, bounds, units per inch, reserved fields and an XOR checksum.
Treat the prefix separately when calculating standard-stream sizes.
[MS-WMF §§1.3.3, 2.1.1.18–19, 2.3.2][spec]

Ordinary records have a four-byte word count and a two-byte function word.
Lengths include the record header; the framing minimum is three words. EOF has
function 0. Do not assume the high byte of a function word is a reliable parameter
count: most records are identified by their low byte, with specific exceptions
listed in §2.1.1.1. Four bitmap transfer families have separate layouts with and
without an embedded bitmap, distinguished using size and function information.
[MS-WMF §§2.1.1.1, 2.3, 2.3.1][spec]

Wire layouts also are not a generic reversed argument list. Individual point
arguments often appear as y,x and drawing rectangles as bottom,right,top,left;
PointS arrays contain x,y and Rect structures contain left,top,right,bottom.
Field signedness varies. Several state records have optional reserved words.
Text strings have word padding. Old pattern brushes have a special partial
bitmap header plus reserved bytes. These need explicit per-record schemas.
[MS-WMF §§2.2.2.16–18, 2.3.3–2.3.5][spec]

Keep two writer contracts distinct:

- **Preserving serialization:** an unmodified, accepted file can round-trip
  exactly, retaining function words, reserved bytes, padding, uninterpreted data,
  and original header values. Define treatment of trailing bytes explicitly.
- **Constructed serialization:** new or edited typed records get consistent
  lengths, deterministic padding, checksums and header accounting. A recorder
  manages handle allocation; direct record construction can express unusual
  variants without passing through drawing semantics.

Store raw record envelopes alongside typed interpretation, with a clear rule for
when edits invalidate the original encoding. Decoding a bitmap or text string
must not destroy its source representation. Do not claim byte identity for
"play into recorder then save": playback may normalize records, object handles,
defaults or ignored operations.

Bound every read by its record before inspecting internal counts. Limit total
bytes, records, points, object capacity, saved states, bitmap pixels and decoded
data. Reject truncation and impossible lengths without guessing the next record
boundary. Preserve well-framed unknown types. Parsing need not allocate the output
bitmap or realize fonts.

The specification explicitly requires skipping undocumented or unsupported
record types and continuing to the next valid record (§2.3). Normal playback
should follow that rule and report omissions; an optional strict development
mode can fail on unsupported work so compatibility tests cannot pass silently.
Malformed framing and unsupported drawing are different conditions.

## Objects and the GDI context

The five reusable object types are created independently of selection. Creation
assigns the lowest free WMF table index, starting at zero; deletion makes that
slot reusable. Selection replaces the current object of that kind. Palettes and
clipping have dedicated selection operations. Some drawing records take explicit
object references: FillRegion and FrameRegion name both a brush and a region.
Do not implement all objects as merely "whatever is currently selected".
[MS-WMF §§2.3.4, 3.1.4][spec]

The WMF player should own the mapping from file indexes to backend handles. The
GDI implementation should own object lifetimes and DC selections. The recorder
needs the reverse mapping and the same lowest-free-slot rule for emitted records.
Keep this table distinct from saved DC state: save/restore concerns selections
and graphics properties; it is not a snapshot of destination pixels or an excuse
to rewind object allocation. Selected-object deletion and saved references need
native probes before we settle their exact behavior.

The proposed context needs the following state from the outset:

| State family | Contents and interactions |
| --- | --- |
| Device description | Pixel dimensions, resolution/device metrics, color depth, initial pixels, capability policy |
| Objects | Default and selected pen, brush, font, palette; object lifetime and realization |
| Mapping | One of 8 map modes, window/viewport origins and extents, scale ratios, layout orientation |
| Position | Current drawing point; operations that update it, including relevant text modes |
| Clipping | Selected/derived region, rectangle intersection/exclusion, offset, surface bounds |
| Painting | Background color/mode, ROP2, polygon fill mode, stretch mode, pattern alignment |
| Text | Foreground color, alignment, character extra, break extra/count, mapper flags |
| Saved contexts | Stack with positive absolute and negative relative RestoreDC references |

The file exposes 31 state record types, including the reserved SETRELABS record
which must be ignored. Not every relevant device property has a WMF setter: for
example, brush-origin behavior still matters. Defaults belong in an explicit
playback profile, not scattered through primitive implementations.
[MS-WMF §§2.3.5, 3.1.5][spec]

Mapping is more than applying a final resize. Fixed physical-unit modes depend
on device metrics; isotropic and anisotropic modes use extents and origins.
Zero-width pens remain one device pixel, while nonzero pen width scales as an
x-axis scalar. Fonts have their own width/height realization rules. Regions are
device dependent; do not simply transform them as polygons at every draw.
[MS-WMF §§2.1.1.16, 3.1.1, 3.1.3–3.1.4.2][spec]

## Drawing and rasterization surface

The 20 drawing records cover lines/polylines, polygons/poly-polygons, rectangle
and rounded rectangle, ellipse/arc/chord/pie, pixel output, pattern blit, two
flood fills, four region operations, and two text operations. There is no core
general path or Bezier record. Path-related names occur in printer escapes;
they should not dictate a universal path renderer for the core primitives.
[MS-WMF §2.3.3 and §2.3.6][spec]

Keep primitive identity through the backend boundary. Converting every rectangle,
ellipse or polyline into one generic path too early may erase differences in
edge ownership, endpoint inclusion and pen behavior that we need for parity.
Likewise, clipping, fill and ROP application need a documented order. Flood fill
and inversion require reading the existing destination; this is not only a
vector-to-mask pipeline.

Pen and brush variants multiply the cases: null/solid/dashed/inside-frame pens,
width and scale, solid/null/hatched/bitmap brushes, six hatches, transparent or
opaque backgrounds, and pattern phase. The enum lists more styles than a legacy
pen creation call necessarily supports. For example, Windows documents solid
fallback for wide dashed pens. Verify behavior through WMF playback before
turning every enum value into a rendering feature. [CreatePen documentation][pen]

Use a shared bitwise compositor for all 16 ROP2 and 256 ROP3 truth tables, with
separate operand preparation and pixel-format handling. ROP3's index and its
encoded 32-bit wire value are distinct; preserve/write the correct complete
code. Test all truth-table inputs locally, then native image cases for masking,
brushes, missing sources and color conversion. Bitmap stretch modes are AND,
OR, scan deletion, and halftone; Pillow resampling modes are not a specification
for these operations. [MS-WMF §§2.1.1.2, 2.1.1.30–31][spec]

## Bitmaps are a substantial nested format

The six bitmap records share machinery, but differ in layout, source type,
color usage, raster operation, source/destination rectangles and scan-range
selection. Four have both embedded-source and no-embedded-source forms.
Pattern brushes reuse bitmap machinery too. [MS-WMF §§2.3.1, 2.3.4.4/8][spec]

| Bitmap dimension | Coverage required or policy to establish |
| --- | --- |
| Legacy Bitmap16 | Separate header and word-aligned rows; device-dependent interpretation |
| DIB headers | Core (12), Info (40), V4 (108), V5 (124) bytes; preserve extension data |
| Bit depths | 1, 4, 8, 16, 24, 32; depth 0 for compressed image payloads |
| Pixel layout | DWORD-aligned DIB rows, packed pixels, top-down/bottom-up orientation |
| Colors | RGB tables, logical-palette indexes, direct palette-index pixels, bit masks |
| Compression | RGB, RLE4, RLE8, bitfields; JPEG/PNG and CMYK variants need device-policy probes |
| Advanced metadata | Color space, gamma/endpoints, V5 embedded/linked profiles, alpha mask |
| Transfers | Partial scans, crop/stretch/mirroring, ROP operands and clipping |

These are format dimensions, not a promise that every combination is valid or
accepted by the reference device. RLE includes absolute runs, repeated runs,
delta moves, end-of-line/end-of-bitmap codes and word padding. Do not use the
declared image size blindly for uncompressed data. The high byte of BI_RGB
32-bit pixels is unused, not automatically an alpha channel. A V4 alpha mask
does not imply that a WMF blit performs alpha blending.
[MS-WMF §§2.1.1.3/6/7, 2.2.2.1–9, 3.1.6][spec]

Parsing should retain bitmap data independently of decoding. Existing Pillow
codecs may help later, but palette-dependent DIBs, Bitmap16, masks and native
transfer semantics need their own tests. Linked color-profile names should remain
data; opening arbitrary external files is not part of our image-loading contract.

## Text scope, even with font parity relaxed

TEXTOUT and EXTTEXTOUT carry byte strings whose interpretation depends on the
selected logical font and charset. A parser cannot reliably turn every string
into Unicode in isolation. Font definitions include height/width, escapement,
orientation, weight, style, charset, precision, quality, pitch/family and a face
name. Preserve the original bytes and defer decoding/realization to playback.
[MS-WMF §§2.2.1.2, 2.3.3.5/20][spec]

Coverage still needs odd-byte padding, multibyte encodings, optional character
advances, rectangle clipping/opaquing, alignment, current-position updates,
character spacing, justification, rotated/vertical text and layout flags. The
exact availability/interpretation of glyph-index and paired-displacement flags
in legacy WMF needs probing; enum membership alone is insufficient.

Font substitution and glyph rasterization can be qualified without abandoning
these semantics. Use explicit fonts for reference cases, record resolved font
information where possible, and test backgrounds/clipping separately from glyph
pixels. Define the acceptable font exceptions before claiming WMF parity.

## Escape surface and limits

META_ESCAPE contains a function, byte count and payload within the normal record
envelope. Its 60 enumerated functions fall broadly into printer lifecycle and
paper control; capability/metric queries; printer drawing and paths; font
operations; raw data/PostScript; compressed-image capability checks; and embedded
metafile data. The inventory lists all 60, including the 17 without individual
payload sections. [MS-WMF §§2.1.1.17, 2.3.6][spec]

Implement lossless generic escape parsing immediately. Typed payloads can then
be added where defined, independently of executing them. Reserve an explicit
escape/capability hook in the backend. For the proposed bitmap device, report
unsupported printer effects and skip them under normal playback policy. Never
interpret SETABORTPROC data as executable callbacks.

One unavoidable format fact: a WMF escape can contain chunks of an enhanced
metafile. Preserve those chunks as WMF payloads; interpreting the nested format
remains deferred. This is not a reason to introduce a second public parser now.

## Specification discrepancies and early Windows probes

The specification is useful but not sufficient to generate a correct renderer
mechanically. Keep the following uncertainties visible, with minimal reproducers
and native results before choosing behavior:

| Issue | Evidence | Probe / design consequence |
| --- | --- | --- |
| No-source blits | §§2.3.1.1–3/5 describe the DC as source, but the no-bitmap subsections say source-requiring ROPs fail | Try SRCCOPY versus source-independent ROPs; do not assume a self-blit |
| Coordinate units | §2.3.5.7 labels window offsets device units; §2.3.5.29 labels viewport origins logical units; Win32 APIs say the reverse | Nonidentity scales distinguish the interpretations; see [window offset][window] and [viewport origin][viewport] |
| Core DIB palette width | §2.2.2.9 describes RGBQuad/index colors; Win32 BITMAPCOREINFO uses RGBTRIPLE | Construct tiny indexed Core DIBs; see [BITMAPCOREINFO][coreinfo] |
| Optional text arrays | EXTTEXTOUT flags include glyph/paired-displacement options but its payload description gives a simple byte string and one advance per character | Test each accepted flag/layout, especially multibyte strings |
| Pattern-brush variant | §2.3.4.8 calls Target a DIB but describes a Bitmap16-style result for BS_PATTERN | Probe both styles and preserve bytes regardless |
| Escape identifiers | §§2.3.6.31/33 say 0x1005/0x1006; enum says 0x1015/0x1016 | Verify against SDK/native acceptance before typed support |
| Escape lengths | CLIP_TO_PATH's stated 14-word size does not match its displayed 14-byte fields | Bound parsing by envelope; validate with independent input |
| Embedded stream lengths | §2.3.6.25's ByteCount wording uses total embedded size while also specifying per-chunk size | Preserve first; resolve before typed reassembly |
| Object lifecycle | Selected objects, saved selections, deletion/reuse, clip reset and failed creation interact | Trace handles and state, not only resulting pixels |
| Header object count | Header prose says objects in the file; table semantics reuse slots | Compare Windows-generated create/delete/recreate streams before fixing recorder accounting |

Other native probes: noncanonical function high bytes; optional state words;
zero/negative extents and rounding; stock defaults; transformed clips; wide and
zero-width pens; arc direction under reflection; pattern origins; ROP edge
ownership; palette changes after selection; rejected records and whether playback
continues. These are behavioral questions, not permission to accept unsafe bounds.

Appendix A matters too: it says Windows does not emit CREATEPATTERNBRUSH but
retains playback support, and reads Core DIB headers without writing them.
Therefore a recorder that merely mirrors what current Windows emits cannot
generate the entire reader test corpus. Direct record construction is necessary.

## Proposed architecture before drawing implementation

```text
WMF bytes <-> raw envelopes + typed records <-> record writer
                         |
                         v
                   WMF player
                 (file handle table)
                         |
                         v
              GDI operations interface
                 /       |        \
                /        |         \
       tracing backend  WMF recorder  stateful raster context
                                          |
                                          v
                                Pillow pixel surface
```

The reader/writer share explicit record and object definitions. The player
translates wire order and file indexes into readable operations and backend
handles. The recorder emits records from those operations, managing its own file
indexes. The tracing backend records operations and logical handle identities
without rasterizing. The raster context maintains DC semantics and ultimately
writes pixels into a Pillow image.

Stub the operation families broadly: object creation/selection/deletion; DC
save/restore; mapping/layout; clipping; palette operations; drawing modes; every
primitive; bitmap transfers; text; escapes. Do not require the recorder to run a
pixel renderer. Keep source bitmaps optional where the wire format allows it and
preserve coordinate units and primitive identities in operation arguments.

Define return values as well as inputs: creation returns handles, save returns a
state identifier, and failures need an explicit representation. The exact Python
signatures should follow the initial native probes, especially handles and
selection; the research does not justify freezing those today.

## Tests and Windows reference process implied by the research

Use three distinct round trips:

1. Bytes → parsed file → preserving writer → identical bytes.
2. GDI calls → recorder → WMF → player → equivalent trace (normalize handle
   identities, and account explicitly for omitted/default/ignored operations).
3. Exact WMF bytes → native Windows playback and our playback → pixel comparison.

Add independent binary fixtures and Windows-generated WMFs so a shared bug in
our reader/writer does not validate itself. The specification's §3.2 example is
useful independent evidence, but review its raw bytes against the prose before
using it as an unquestioned semantic golden.

Proposed native route: load the standard WMF stream with [SetMetaFileBitsEx][bits],
play with [PlayMetaFile][play] into a selected [CreateDIBSection][dib] bitmap in a
memory DC, flush GDI before reading pixels, and encode RGB PNG. Handle placeable
metadata as explicit harness setup. This tests native GDI directly; the Windows
oracle should not depend on our record decoder to decide what to draw.
[EnumMetaFile][enum] is useful for diagnostic enumeration and later per-record
inspection, but PNG equality remains separate evidence.

Specify a fresh DC and bitmap per case; explicit initial pixels; dimensions;
mapping, clipping, colors and selected defaults; observed device metrics; font
policy; and the treatment of the unused fourth byte in 32-bit RGB output.
CreateDIBSection does not establish device DPI from its pixels-per-meter fields,
so a metadata DPI value alone cannot configure native physical mapping modes.
[CreateDIBSection documentation][dib]

For economical CI, compute stale cases on Linux before allocating a Windows job.
Use a fingerprint of exact WMF bytes, fixture playback options and an explicit
reference-renderer/profile revision. A missing PNG or mismatched fingerprint is
stale. Record OS/image/font provenance but do not automatically invalidate the
whole corpus whenever the hosted runner image changes. Detect drift with a small
sentinel set, then make intentional baseline refreshes. Batch stale cases into
one Windows job; no stale cases means no Windows job.

The current updater is still a placeholder. Before relying on it, fix its commit
check to include untracked PNGs/sidecars (plain git diff misses them), stage only
generated paths, and retain artifacts on failures. If the branch moves during
rendering, publish results only with their original input fingerprints and verify
those inputs still match; rebasing a bot commit alone does not establish that.
These are follow-up requirements, not changes made by this research.

## Work packages and completion gates

| Work package | Completion evidence | Relative uncertainty |
| --- | --- | --- |
| Framing and lossless codec | Both headers, 70 record codes/variants, bounded unknown/escape preservation, independent byte fixtures | Low–medium |
| Nested structures | All 5 graphics and 22 supporting structure types accounted for, with explicit opaque/device-specific cases | Medium |
| GDI interface, player and recorder | Every core record mapped; operation traces round-trip; handle/DC behavior tested | Medium |
| Windows oracle | Exact-input PNGs, profile/provenance, drift sentinel, stale-case scheduling, recoverable publication | Medium |
| Mapping, regions, objects and modes | State traces plus native interaction cases; default/invalid-operation policy | High |
| Vector rasterizer and compositor | Primitive boundaries, pen/brush variants, clipping and all ROP truth tables | High |
| Bitmap decoding and transfer | Valid depth/header/compression cases, stretch/palette/ROP interactions | High |
| Text | Byte/charset/layout semantics; named and bounded font exceptions | Very high for glyph parity |
| Compatibility hardening | Independent corpus, fuzzing, resource limits, minimized native discrepancies | Open-ended tail |

The complete supporting-structure inventory is: Bitmap16; BitmapCoreHeader;
BitmapInfoHeader; BitmapV4Header; BitmapV5Header; CIEXYZ; CIEXYZTriple; ColorRef;
DeviceIndependentBitmap; LogBrush; LogColorSpace; LogColorSpaceW; PaletteEntry;
PitchAndFamily; PointL; PointS; PolyPolygon; Rect; RectL; RGBQuad; Scan; SizeL.
Some are supporting definitions rather than separately creatable GDI objects.
[MS-WMF §2.2.2][spec]

Recommended first implementation milestone: a complete top-level record model,
bounded reader, preserving/canonical writer, and GDI recorder/player with a
tracing backend. Give nested bitmap/escape payloads explicit coverage status;
opaque preservation alone is not typed decoding. Use a handful of Windows probes
to settle framing and handle questions while building this foundation. Then
complete the real reference-image loop and start renderer slices.

Expect hundreds of focused cases and eventually thousands of generated parameter
combinations, not merely 70 images. That is a planning estimate, not measured
workload. The finite codec/API surface can be planned now; a trustworthy calendar
estimate for pixel parity needs an initial batch of native mismatches and evidence
of how quickly we can explain and fix them.

[spec]: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/4813e7fd-52d0-4f42-965f-228c8b7488d2
[inventory]: wmf-record-inventory.md
[pen]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createpen
[coreinfo]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-bitmapcoreinfo
[window]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-offsetwindoworgex
[viewport]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-setviewportorgex
[bits]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-setmetafilebitsex
[play]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-playmetafile
[dib]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createdibsection
[enum]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-enummetafile
