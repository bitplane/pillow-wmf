# Escapes on the RGB device

The renderer emulates an RGB memory DC, not a printer. The defined
[WMF escape records](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/2a1786c2-dd0f-40b4-8da0-a84c0f0d18a0)
do not alter this device's pixels or GDI state. Printer queries have no result
consumer in a recorded WMF. Printer cap/join/miter settings are not replacements
for bitmap pen semantics; PostScript paths do not create bitmap clipping paths.
The EXTTEXTOUT escape is distinct from the ordinary text drawing record.

Payloads remain opaque and round-trip unchanged. Playback never opens a printer,
executes PostScript, follows a document path, downloads a font, or installs a
callback. Embedded enhanced-metafile data remains opaque; only the surrounding
WMF drawing records are played.

The accepted codes are explicitly listed in `BITMAP_NOOP_ESCAPES` in
[the raster backend](../src/pillow_wmf/raster.py). Other enumeration values,
including SETABORTPROC and MXDC_ESCAPE, remain unsupported, as do unknown codes.
Acceptance here does not imply support for printer output or every extension
listed in the escape enumeration.

The named `escapes` native probe checks individual records and a combined
sequence against a drawing-only baseline. Wide lines, joins, fills, saved state
and a continuation pixel distinguish device no-ops from changed drawing state.
One combined WMF/PNG retains the native result; unit tests cover individual
payload preservation and strict playback. The byte envelope and resource limits
are still validated even when the device does not interpret an escape payload.
