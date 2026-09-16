# GDI coordinate mapping: design and compatibility plan

Research date: 2026-09-16. This is a design, not implemented coverage or a report
of new Windows measurements. Microsoft documents the contract; Wine supplies
implementation clues and useful test cases. Our Windows runner remains the
pixel oracle. No Wine implementation code is copied into this project.

## Decision

Build a small, independently testable mapping component inside the GDI context.
Keep recorded coordinates logical. Do not normalize the file into twips, resize
a finished image, or let each drawing primitive invent its own mapping rules.

The proposed responsibilities are:

```text
WMF reader / recorder              preserves logical arguments and call order
         |
GDI context                       mapping state, selections, position, save stack
         |
Mapping + primitive realization   device geometry, pen/font sizes, clip updates
         |
Rasterizer                        edge ownership, coverage, clipping, pixel writes
```

This is not one blanket transformation of every numeric argument. Some inputs
are positions, others are distances, and some already describe device pixels.
Keep primitive identity through this boundary.

## Mapping contract

For ordinary left-to-right, axis-aligned WMF drawing, the underlying mapping is:

```text
device_x = viewport_origin_x + (logical_x - window_origin_x)
                              * viewport_extent_x / window_extent_x
device_y = viewport_origin_y + (logical_y - window_origin_y)
                              * viewport_extent_y / window_extent_y
```

This describes the geometry, not a universal rounding algorithm. A distance uses
the scale without the origin translation. Negative extents reverse axes; they
are not automatically invalid. “Window” here means the logical coordinate
window, not an application UI window. [Coordinate spaces][spaces],
[Wine transform construction][wine-dc].

| Mode | Value | Logical unit | Positive Y, before layout effects |
| --- | ---: | --- | --- |
| `MM_TEXT` | 1 | Device pixel | Down |
| `MM_LOMETRIC` | 2 | 0.1 mm | Up |
| `MM_HIMETRIC` | 3 | 0.01 mm | Up |
| `MM_LOENGLISH` | 4 | 0.01 inch | Up |
| `MM_HIENGLISH` | 5 | 0.001 inch | Up |
| `MM_TWIPS` | 6 | 1/1440 inch | Up |
| `MM_ISOTROPIC` | 7 | Application-defined, equal physical scale on both axes | Extent-dependent |
| `MM_ANISOTROPIC` | 8 | Application-defined, independent axis scales | Extent-dependent |

These are GDI drawing modes, not UI-only units. Isotropic means equal physical
distances, not necessarily equal numbers of pixels on an arbitrary device.
[SetMapMode][map-mode].

The core surface is nine mapping operations: set mode; set the two origins and
two extents; offset either origin; scale either extent. Include `set_layout` and
`save_dc` / `restore_dc` in the design: twelve existing GDI operations, with
cross-cutting effects on drawing. No new WMF opcode or codec is required.

### State transitions matter

In the six fixed modes, window/viewport extent setters are ignored. Isotropic
mode adjusts the viewport; Microsoft specifies setting window extents before
viewport extents. We must test intermediate states and setter order, not just
the resulting scale of a completed setup. [SetWindowExtEx][window-ext].

Wine observations, to verify on our Windows target:

- Text mode installs unit extents; physical modes derive extents from device
  metrics. Isotropic mode initially uses the low-metric setup.
- Entering anisotropic mode retains the existing extents; reselecting an
  already-active arbitrary-unit mode does not reset them.
- Extent scaling truncates integer division toward zero and substitutes `1`
  for a zero result. Zero factors fail in arbitrary-unit modes.
- Isotropic adjustment accounts for physical pixel dimensions and shrinks a
  viewport dimension, preserving its sign.

These are implementation observations, not a specification for Windows.
[Wine mapping implementation][wine-mapping]. Wine's tests exercise signed
extents, repeated adjustments and unchanged origins. They also acknowledge
Windows-version differences in physical-mode calculations and use tolerances
in some checks; we should borrow the questions, not their tolerances.
[Wine mapping tests][wine-tests].

Wine checks the fixed-mode no-op before rejecting a zero extent. This ordering
is another native probe, not grounds to reject every zero-valued record during
parsing. [Wine GDI entry points][wine-gdi-dc].

### Numerical boundaries

There are separate decisions for scaling stored extents, transforming points,
realizing object sizes, and converting a primitive into covered pixels. Do not
introduce a universal `gdi_round()` and assume it solves all four.

Wine's point helper uses `floor(value + 0.5)`, unlike Python's ties-to-even
`round()`: positive and negative half-integers need explicit probes.
[Wine rounding helper][wine-round]. Microsoft also warns that `LPtoDP` involves
floating-point calculations and caching, with defined coordinate-range limits
but no promise of bit-identical repeated conversions. A mathematically exact
rational implementation is therefore not automatically a Windows match.
[LPtoDP][lptodp].

Proposed implementation rule: retain integer state and named conversion
boundaries; choose intermediate precision and tie handling from native evidence.
Do not round each arithmetic subexpression. Equally, do not defer every rounding
decision until the last pixel: some primitives may consume integer device points.
Wine's DIB line path does precisely that before stroking. Its rectangle and ellipse
paths have their own realization rules. [Wine DIB drawing][wine-drawing].

GDI's driver path interface can carry 28.4 fixed-point coordinates. That is
evidence that subpixel precision exists, not proof that every WMF primitive goes
through a single 1/16-pixel engine. [PATHOBJ][pathobj]. The existing 1:1 ellipse
failure remains a rasterization investigation; this design does not fix it.

## Device metrics and playback initialization

Separate three things:

1. **Surface:** output pixel dimensions and storage.
2. **Device metrics:** logical DPI, device resolution and physical dimensions.
3. **Playback setup:** initial mode, origins, extents and placement policy.

`GetDeviceCaps` exposes `LOGPIXELSX/Y`, `HORZRES/VERTRES` and
`HORZSIZE/VERTSIZE` as distinct quantities. Do not assume their ratios are
identical or infer them from a 128-by-128 bitmap. [GetDeviceCaps][device-caps].
`CreateCompatibleDC(NULL)` is screen-compatible; `CreateDIBSection` ignores
the bitmap header's pixels-per-metre fields. Setting PNG DPI or those fields
does not establish the native DC's mapping metrics.
[CreateCompatibleDC][compatible-dc], [CreateDIBSection][dib-section].

Before physical-mode goldens, run one native probe on the same kind of DC used
by the renderer. Read its capabilities and the actual origins/extents obtained
after selecting each mode. Use those observations to define one checked-in,
suite-wide reference profile. Validate that profile on reference-generation
runs; fail with a clear environment mismatch rather than mixing incompatible
device assumptions into the same golden set. Actual Windows values are still
unknown; do not invent a 96-DPI profile and label it native.

Keep profile constants in ordinary Python test support, with a short provenance
comment. This is consumed test configuration, not per-image hashes, sidecars or
an automatically rewritten metadata inventory. A profile change is an explicit
compatibility decision, not a reason to regenerate every PNG automatically.

Our existing native helper starts in anisotropic mode, with both extents equal
to the canvas dimensions. `RasterContext` starts in text mode with unit extents.
These map the initial points identically but respond differently to later
commands. Preserve the existing oracle setup and explicitly apply it to the
Python compatibility context. A generic fresh GDI context can still have native
text-mode defaults. Add a fixture that does not reset the mapping itself.

### Placeable WMFs are placement policy

The placeable header provides bounds and units per inch; it does not change
the interpretation of all subsequent records to twips. [Placeable header][placeable].
Playback initialization belongs to the caller, as illustrated by Microsoft's
window/viewport division for metafile playback. [WMF mapping modes][wmf-mapping].

Proposed high-level policies: explicit destination rectangle, or natural size
computed from placeable bounds, units per inch and requested output resolution.
For the usual anisotropic placement, initialize the logical window from the
bounds and the viewport from the destination. Records still execute normally
and can change that setup; do not silently override later mode/extent records
to force a fit. Keep low-level `play()` unchanged. The native adapter must strip
the placeable prefix before passing standard WMF bytes to GDI.

## Consumers: do not transform everything as a point

| Consumer | Design boundary |
| --- | --- |
| Lines, polygons, primitive bounds | Map logical geometry; retain direction and primitive-specific endpoint/edge rules. Do not discard a reflected rectangle because its mapped corners reverse order. |
| Current position | Keep logical state; test `MoveTo`, mapping change, then `LineTo`, including save/restore. |
| Pens | Preserve logical width and style. Width zero is a device-pixel hairline; nonzero width scales as an X scalar. Re-realize after relevant mapping changes. |
| Fonts and text advances | Separate font realization from position/advance mapping; zero font width is not an ordinary zero-length vector. |
| Clip rectangles | Convert logical bounds when modifying the clip, not again at every draw. |
| Selected regions | Region coordinates are device units; selecting a region copies it. Do not apply ordinary point mapping again. |
| Clip offsets | Transform a logical displacement, without origin translation. |
| Bitmap transfers | Keep source bitmap coordinates separate from destination logical coordinates; preserve signed dimensions for mirroring. |
| Pattern origin / layout | Device alignment and reflection are separate policies, not a post-render image flip. |

Pen/font rules: [WMF object scaling][object-scaling], [CreatePen][create-pen].
Clipping rules: [IntersectClipRect][intersect-clip], [SelectClipRgn][select-clip],
[OffsetClipRgn][offset-clip]. Bitmap example: [StretchDIBits][stretch-dib].
The table proposes ownership boundaries; individual families still need their
own Windows tests before claiming support.

Layout is in the WMF surface already. Wine's tests show RTL switching the mode
to anisotropic and reflecting relative to the selected surface width, with
additional clipping interactions. [Wine layout tests][wine-tests]. Windows
also provides bitmap-orientation preservation independently of RTL layout.
[SetLayout][layout]. Represent layout state now; leave non-default layouts
explicitly unsupported until their native tests and implementation land.

## Proposed Python ownership

- `mapping.py`: `MappingState` (mode, origins, extents, layout) and conversion
  logic. Pure state transitions are testable without Pillow. Expose distinct
  point and vector conversions; primitive-specific bounds and pen realization
  stay outside the generic transform. Read-only state snapshots support tests.
- `context.py`: `DCState` containing mapping, logical position, selections,
  clipping and other graphics properties; one save/restore stack. Snapshot state,
  not pixels or the object-allocation table. Selected-object lifetime is a
  separate concern. [SaveDC][save-dc], [RestoreDC][restore-dc].
- `raster.py`: consumes the state and realizes supported drawing operations.
  A transform change must invalidate any dependent pen/font realization cache.
  Wine explicitly reselects those objects after linear-transform changes.
  [Wine DC transform updates][wine-dc].
- Test support: one native-reference device profile and explicit playback setup
  applied to both implementations. No new public profile/configuration framework
  is needed before we know the native values.
- Reader, recorder and `TraceContext`: continue preserving requested operations,
  including setters which a rendering context may ignore. Do not make recording
  depend on a target device. `TraceContext`'s save-depth bookkeeping is not a
  substitute for a real DC-state stack.

Keep supported-invalid operations distinct from unimplemented ones. A native
no-op should remain a no-op; a native failure must preserve the appropriate
state. Probe direct API return values and actual WMF playback before deciding
how failures surface through our command API. Never partially mutate a context
and then raise `UnsupportedOperation`.

## TDD sequence and completion criteria

1. **Establish the oracle context.** Add an on-demand Windows mapping probe using
   the existing DC/DIB setup. Report capabilities, map mode, extents, origins,
   API results, selected `LPtoDP` points and save/restore observations. Keep its
   compact output in the CI log/artifact for review; promote verified numeric
   expectations into ordinary tests. Do not build a new per-fixture manifest.
2. **Define mapping state with failing tests.** Cover all eight modes, origin
   set/offset, signed extents, setter ordering, repeated mode changes, ignored
   setters, extent scaling, zero factors, truncation-to-zero and failure
   atomicity. Include positive/negative half ties and translated half ties.
3. **Integrate the existing primitives.** Add small WMF/PNG cases for translations,
   fractional scales, reflections, mode switches, and inherited initial state.
   Use pixel markers and rectangles to isolate mapping from curve algorithms;
   add line/ellipse cases separately. The four existing goldens remain unchanged.
4. **Integrate complete supported DC snapshots.** Native tests for nested saves,
   positive/negative restores, mapping and position restoration, and selections.
   Object handles and already-painted pixels must not rewind.
5. **Expand consumers.** Hairline versus scaled pen, clip-before-transform versus
   transform-before-clip, placement, then layout and bitmap/text interactions as
   their renderers become available. Unsupported cases stay explicit; do not
   claim complete mapping integration merely because point conversion passes.

The first mapping matrix should include identity, 2x, 1/2, 2/3, independent axes,
both signs, nonzero logical and device origins, and short sequences that change
state between draws. Exercise physical modes with the measured device profile,
and test anisotropic synthetic device metrics at the unit level. Native probes
must also distinguish extent overflow and point overflow from ordinary clipping;
Python's unlimited integers should not accidentally define our compatibility
behaviour. Bound raster work for extreme coordinates independently of that policy.

For each implemented slice: exact numeric assertions locally, reproducible
recorder output, and zero differing RGB pixels against native PNGs. Missing
goldens fail; no tolerances, xfails, or regenerated expectations to bless Python
output. Numeric probes help locate errors but do not replace pixel comparisons.

Keep the existing missing-PNG generation rule. Batch new cases in one Windows
run. Separately fix the workflow's path filter to include PNG changes so the
agreed delete-and-push regeneration workflow actually triggers; the current
filter only includes WMFs and tooling. This document does not modify the runner,
tests, renderer, or reference images.

[spaces]: https://learn.microsoft.com/en-us/windows/win32/gdi/transformation-of-coordinate-spaces
[map-mode]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-setmapmode
[window-ext]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-setwindowextex
[lptodp]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-lptodp
[pathobj]: https://learn.microsoft.com/en-us/windows/win32/api/winddi/ns-winddi-pathobj
[device-caps]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-getdevicecaps
[compatible-dc]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createcompatibledc
[dib-section]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createdibsection
[placeable]: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/828e1864-7fe7-42d8-ab0a-1de161b32f27
[wmf-mapping]: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/2678f2fe-df2e-489d-83db-713a9f6397de
[object-scaling]: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/e2050bf0-9dfa-408c-ab3f-0336565ef5c9
[create-pen]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createpen
[intersect-clip]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-intersectcliprect
[select-clip]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-selectcliprgn
[offset-clip]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-offsetcliprgn
[stretch-dib]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-stretchdibits
[layout]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-setlayout
[save-dc]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-savedc
[restore-dc]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-restoredc
[wine-mapping]: https://github.com/wine-mirror/wine/blob/afccd681bebd7b59d4308d5ef2e5197305277f2a/dlls/win32u/mapping.c
[wine-round]: https://github.com/wine-mirror/wine/blob/afccd681bebd7b59d4308d5ef2e5197305277f2a/dlls/win32u/ntgdi_private.h
[wine-dc]: https://github.com/wine-mirror/wine/blob/afccd681bebd7b59d4308d5ef2e5197305277f2a/dlls/win32u/dc.c
[wine-gdi-dc]: https://github.com/wine-mirror/wine/blob/afccd681bebd7b59d4308d5ef2e5197305277f2a/dlls/gdi32/dc.c
[wine-tests]: https://github.com/wine-mirror/wine/blob/afccd681bebd7b59d4308d5ef2e5197305277f2a/dlls/gdi32/tests/mapping.c
[wine-drawing]: https://github.com/wine-mirror/wine/blob/afccd681bebd7b59d4308d5ef2e5197305277f2a/dlls/win32u/dibdrv/graphics.c
