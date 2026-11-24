# pillow-wmf

A Windows Metafile reader/writer/renderer for Pillow.

Like in the old Windows days, a GDI backend draws graphics and can also record
actions to a Windows Metafile. Rasterizing one of these WMFs is just a matter
of playing it back, which produces a Pillow Image.

## Links

* [🏠 home](https://bitplane.net/dev/python/pillow-wmf)
* [😺 source](https://github.com/bitplane/pillow-wmf)
* [🐍 pypi](https://pypi.org/project/pillow-wmf)

## Usage

```python
from PIL import Image
import pillow_wmf  # registers the WMF loader ahead of Pillow's built-in stub

with Image.open("drawing.wmf") as image:
    image.load(size=(640, 480))
    image.save("drawing.png")
```

### Pillow loading

`Image.open()` reads and validates the file but does not rasterize it. Pixels
are produced by the first `load()`, which accepts keyword options:

* `size=(width, height)` renders onto a canvas of that many pixels.
* `dpi=d` or `dpi=(x, y)` scales a placeable WMF's bounds from its
  units-per-inch. It requires valid placeable bounds and cannot be combined
  with `size`.
* `fonts=` supplies the font collection (see below).

Without options, a WMF with valid placeable bounds renders at those bounds at
72 DPI, setting `info["dpi"]` and `info["wmf_bbox"]`; any other WMF renders at
128×128. Options are only accepted by the first `load()`; reopen the file to
render it differently. Invalid options raise `ValueError`. Unsupported
records, invalid playback and resource limits raise `OSError`, and Pillow's
decompression-bomb limit applies to the output size. EMF files are left to
Pillow's own handler.

`pillow_wmf.render(data, size, fonts=...)` renders bytes to an RGB image
without Pillow's file handling. It raises the library's own exceptions.

## Fonts

Text is rendered from TrueType outlines with Windows-compatible metrics, so
the result depends on which font files are used. There are two collections:

* `FontCollection(faces)` uses only the `FontFace` objects you supply, for
  example `FontFace.from_path("arial.ttf")`. A request for a family that is not
  supplied (or mapped with `aliases=`) raises `UnsupportedOperation`. Nothing
  is read from the host. Use this for reproducible output.
* `SystemFontCollection()` discovers installed fonts through `fc-list`, or the
  platform's font directories when Fontconfig is unavailable, and substitutes
  similar families when the requested one is missing. Pass `paths=` to
  restrict it to particular files. Substitutions are recorded in its
  `substitutions` list. Construct one per rendering job. Discovery is cached
  for the process; call `SystemFontCollection.clear_cache()` after installing
  or replacing fonts.

The Pillow loader uses a new `SystemFontCollection()` unless `fonts=` is
given, so its output depends on the fonts installed on the machine. When a
`SystemFontCollection` renders the image, through either the loader or
`render()`, `info["wmf_font_substitutions"]` lists its `FontSubstitution`
records (`requested`, `selected`, `reason`). `render()` uses an empty
`FontCollection` unless `fonts=` is given, so text records fail rather than
silently using host fonts.

Only static TrueType (`glyf`) outlines are supported. CFF-flavoured OpenType
and variable fonts are skipped during discovery and rejected by `FontFace`.
Both collections can fall back to bundled Wingdings and Symbol substitutes
(`wingdings_fallback=` and `symbol_fallback=` on `FontCollection`; always on
for `SystemFontCollection`).

## Rendering limits

`render(data, size, limits=Limits(...))` bounds input bytes, records, points,
objects and saved DC states. `max_bitmap_pixels` limits each decoded bitmap
or glyph. `max_geometry_points` (default 1,000,000) limits cumulative curve
flattening and dynamic pen expansion, including their stroke caps, joins and
repeated realizations. Input polygon points, fixed-size stroke bodies and
fixed-table pens (including their caps and joins) do not spend this expansion
budget.
Pen realization and identical stroke coverage are reused within one drawing
operation. Reusing them does not spend the allowance again; subsequent
operations generate and charge their own geometry.
The geometry allowance belongs to the raster context and is not restored by
`RestoreDC`. Each flattened curve also has a fixed 65,536-point limit.
`RasterContext` accepts `max_objects`, `max_saved_states`, `max_bitmap_pixels`
and `max_geometry_points` for direct drawing. `render()` passes its `Limits`
object's object/save allowances to the backend; Pillow loading uses the defaults.
Default policy values are defined in `pillow_wmf.limits`.

Resource exhaustion raises `pillow_wmf.binary.ResourceLimitError`, including
during `play(..., strict=False)`; it is never treated as a recoverable omission.
An execution-time failure makes the context unusable and may leave partial
pixels. Pillow reports rendering resource failures as `OSError`. These limits
bound particular allocations and generated geometry, not total rendering time.

## Drawing diagnostics

`RasterContext` and `Recorder` retain requested calls by default for existing
diagnostic callers. Pass `trace_calls=False` to omit that history; WMF recording,
handle validation and saved drawing state still work. `RecordingContext` also
accepts this option for its own history, independently of its two backends.
`render()` and the Pillow loader disable call history because they only return
pixels. `TraceContext` remains the backend for collecting a command trace.

## Threads

`FontFace` and `FontCollection` objects can be shared by renders running in
different threads; glyph rasterization is serialized per realized font size.
A `RasterContext`, `Recorder` or `SystemFontCollection` serves one rendering
job at a time.

## License

pillow-wmf is WTFPL with one additional clause:

1. Don't blame me.

Fonts have their own licenses, rip them out if you don't want to comply:

* [Wingdings fallback (OFL-1.1)](src/pillow_wmf/fonts/OFL.txt)
* [Wine Symbol (LGPL-2.1-or-later)](src/pillow_wmf/fonts/symbol/COPYING.LIB)

