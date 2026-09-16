# WMF foundation: implemented surface and contracts

The first milestone implements a bounded reader/writer and a non-rendering GDI
command interface. The [research](wmf-format-research.md) and
[record inventory](wmf-record-inventory.md) remain the reference for future work.
The [coordinate-mapping design](gdi-coordinate-mapping.md) details GDI state,
device metrics, rounding boundaries, and the next native compatibility probes.

## Current coverage

| Surface | Implemented | Still needed |
| --- | --- | --- |
| File framing | Standard/placeable headers, checksum, EOF, original metadata and file trailer preservation | Native compatibility probes for unusual headers |
| Fixed records | 51 record classes with explicit field widths, signedness and wire order | Behavioral interpretation of state and drawing modes |
| Variable records | 19 record classes, including all six bitmap transfer envelopes | Native probes for ambiguous layouts |
| Text | Raw strings, word padding, optional rectangle and raw advances | Charset/glyph interpretation, layout and drawing |
| Objects | Pen/brush record fields, font, palette, region/scan structures | Native object realization and selected/saved-object quirks |
| Bitmap payloads | Explicit `BitmapData` values; Bitmap16/DIB/legacy-pattern distinction | Header/pixel decoding, compression, palette resolution, validation of nested bitmap contents |
| Escapes | Function code, length-delimited payload, padding and trailing data | Typed payload interpretation and device capability policy |
| GDI | 68 named operations, backend handles, tracing and recording; raster mapping, rectangular clipping, pens/brushes, ROP2, lines, polygons, Rectangle, Ellipse, Arc, Chord and Pie | RoundRect, regions, bitmap transfers, palette behavior and text |
| Playback | File-slot mapping, lowest-free allocation, references, unsupported-operation diagnostics | Native behavioral validation and device-state emulation |
| Recording | GDI calls to WMF, independent handle indexes, header accounting | Native acceptance tests and platform-specific normalization findings |

The 70 opcode total includes EOF and the required-ignore SETRELABS record, so
there are 68 callable operations. All 70 have structural round-trip tests.
This does **not** mean 70 operations render correctly. The raster backend rejects
unsupported operations explicitly. See the individual GDI design notes for
measured coverage and limits, including [Arc](gdi-arcs.md), [Chord](gdi-chords.md)
and [Pie](gdi-pies.md).

The structural reader parses fields without realizing graphics objects. A valid
envelope containing `BitmapData` is not certification that the bitmap itself is
valid. Escape payloads likewise stay opaque. The 22 supporting structures from
the inventory are not all implemented as typed nested codecs yet.

## Read and write

```python
from dataclasses import replace

from pillow_wmf import Metafile
from pillow_wmf.wmf.fixed import MoveTo

data = Metafile.build([MoveTo(x=2, y=-3)]).to_bytes()
file = Metafile.from_bytes(data)
assert file.to_bytes() == data

# Preserve original metadata by default. Recalculate it explicitly after edits.
edited = replace(file, records=(MoveTo(x=10, y=20), *file.records[1:]))
data = edited.to_bytes(canonical=True)
```

`Metafile.build` appends EOF when necessary and computes file size, largest record
and object-table capacity from lowest-free-slot allocation. This is the recorder's
accounting model; native cross-checks remain pending. Direct record construction
does not check drawing semantics or object references, making it suitable for
constructing invalid test cases as well as ordinary fixtures.

`from_bytes` requires an immutable byte string and checks outer bounds before
walking records. `Limits` controls input bytes, record count, declared object
capacity, and per-record point/scan/advance counts. Playback also checks record,
object and saved-state limits. Writers check wire representability, but do not
serve as a security validator for arbitrary nested payloads.

Read records retain the original function word and uninterpreted trailing bytes.
Known text records retain padding separately. Parsed header fields are preserved
even where they are advisory (for example maximum record size); declared stream
size still bounds record reads. Bytes after EOF are retained as the file trailer,
including any that fall within the declared size. Canonical output excludes that
trailer from the recalculated stream size while retaining the bytes.

Canonical output recomputes the header, placeable checksum and standard record
function words. It retains explicit reserved/padding/trailing bytes. It does not
silently repair arbitrary malformed input or decode and recompress images.

Invalid framing/counts raise `FormatError`, a `ValueError` subclass. Unknown
well-framed opcodes become `UnknownRecord`. An optional
`validate_checksum=False` permits inspection/preservation of a damaged placeable
checksum. Invalid units-per-inch, truncation and record bounds are still checked.

## Record and replay commands

```python
from pillow_wmf import Metafile, PlaceableHeader, Recorder, TraceContext, play

recorder = Recorder()
pen = recorder.create_pen(style=0, width=1, color=0x000000FF)
recorder.select_object(pen)
recorder.move_to(10, 10)
recorder.line_to(90, 90)

wmf = recorder.to_bytes(placeable=PlaceableHeader(0, 0, 100, 100, inch=96))
trace = TraceContext()
assert play(Metafile.from_bytes(wmf), trace, strict=True) == ()
assert trace.calls == recorder.calls
```

Color integers use the WMF COLORREF representation, not Pillow tuples. The
placeable header supplies placement metadata; no output image is created by this
example.

`GDI` declares named calls for each operation family. To implement a backend,
override `invoke(Call)`. Each call contains a name and a sorted immutable argument
tuple; `call.kwargs` gives a dictionary copy. Geometry retains primitive identity
and logical coordinates. Sequence/buffer inputs are snapshotted. Creation returns
a `Handle`, and save returns a state identifier. The default backend raises
`UnsupportedOperation` for every call, providing an explicit renderer stub.

`TraceContext` validates handle ownership/type/lifetime and save-stack references;
it logs requested operations and supplies deterministic handles. It does not
compute transforms, clipping, default graphics objects or selected-object
semantics. In particular, acceptance of a delete call is not a claim that Windows
allows deleting that object in the same selected/saved state.

`Recorder` also translates handles to file slots and validates a record's encoding
before committing it. Failed recording calls do not advance handles or append
commands. Deletion makes a file slot reusable; backend handle identities remain
distinct. Saving/restoring does not rewind object allocation. Both recorder and
trace context have configurable live-object and saved-state limits.

`play` accepts a fresh backend context; its saved-DC numbering assumes the file's
stack begins empty. It reports unsupported records/operations as `Omission`
values, or raises in strict mode. SETRELABS is always ignored. Unsupported object
creations still occupy file slots, so subsequent objects cannot acquire the wrong
index. References to those unavailable objects are reported and skipped; invalid
or deleted file references raise `PlaybackError`.

The caller owns the supplied backend. Playback inserts no implicit reset or
cleanup calls into the command trace. A future native/raster backend will need a
separate resource-lifetime boundary around playback. This differs from native
PlayMetaFile cleanup and must be implemented before exposing native resources.

The reader/writer retain more information than GDI playback: function high bytes,
padding, reserved fields, unknown records and opaque tails need not survive a
play-into-recorder cycle. Use preserving serialization for byte-exact round trips;
use command traces for semantic round trips. Escape and bitmap payloads are
carried through recording, not executed by the trace backend.

## Verification and next work

The unit suite checks all record classes and both blit layouts, independently
specified wire bytes, truncation/count/limit failures, sequence snapshots, handle
reuse, save references, unsupported operations, and mixed command round trips.
Windows renders missing WMF references and commits PNGs. The
compatibility suite compares every pixel through `RasterContext`. New WMFs
require a PNG and unsupported operations fail explicitly. Chord adds 16 references
covering closure, fill/stroke state, mapping and degenerate geometry. Further
fixtures expand that ratchet. Native acceptance probes for other record
families and nested bitmap codecs remain open work.
