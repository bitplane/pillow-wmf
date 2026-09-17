# Failed objects and retained selections

The raster backend distinguishes a failed creation from a real object that
cannot realize on the reference device. For example, an incomplete legacy
pattern brush is null; a complete unsupported-depth pattern brush is a real,
unrealizable brush. These must not share selection or allocation semantics.

## Null results

Failed creations return an interned, owner-checked null handle per object kind.
They consume neither the live-object budget nor an ever-growing object table.
The WMF player continues to retain the null value in the file slot while marking
that slot available for the next creation. TraceContext and Recorder still
record requested creations as ordinary handles: they do not predict native
realization failures.

Null values preserve argument type checking. They cannot be passed between
contexts or used where another object kind is required. Deleting a null value
does not invalidate other references to null, change a selected object, or
release a real object's allocation. The player independently marks a deleted
file slot unavailable, retaining its existing deleted-reference validation.

Brush sampling always receives an explicit brush value. A failed brush means
no paint; it never means "use the selected brush." PaintRegion chooses the
selected brush, while FillRegion and FrameRegion use their explicit argument.
Native cases distinguish these after failed Core-DIB and incomplete Bitmap16
brush creation, including XOR. The selected brush survives the failed call.

## Selected and saved objects

Six native WMF sequences delete a pen, brush or palette while selected in the
current DC or retained in a saved DC. Drawing continues with the retained object;
switching selection, restoring the saved state, and allocating another object
into the released file slot do not replace that retained value. The existing
object-reference snapshots already match these sequences; no deletion-specific
pixel branch was added.

This establishes those WMF playback sequences, not a complete emulation of
Win32 DeleteObject return values, stale native handles or font lifetimes.
TraceContext's checked logical-handle rules remain distinct from device state.

## Evidence

[Native reference run 35239504770](https://github.com/bitplane/pillow-wmf/actions/runs/35239504770)
generated 22 missing PNGs: four failed explicit-brush cases, six deletion cases,
and twelve signed-scale FrameRegion controls. Eight RTL frame controls initially
failed because frame pen realization omitted layout's X sign. Frame footprints,
ordinary pens and arc radial directions now consume `Mapping.linear_scale`;
point/translation rounding retains its separate native contract.

Local tests exercise repeated failures with a one-object budget, file playback,
bounded null storage, owner/type validation and retained null references after
deletion. All image comparisons remain exact and run locally/Linux.
