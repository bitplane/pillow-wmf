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
`RasterContext` accepts `max_geometry_points` for direct drawing; Pillow loading
uses the defaults.

Resource exhaustion raises `pillow_wmf.binary.ResourceLimitError`, including
during `play(..., strict=False)`; it is never treated as a recoverable omission.
An execution-time failure makes the context unusable and may leave partial
pixels. Pillow reports rendering resource failures as `OSError`. These limits
bound particular allocations and generated geometry, not total rendering time.

## License

pillow-wmf is WTFPL with one additional clause:

1. Don't blame me.

Fonts have their own licenses, rip them out if you don't want to comply:

* [Wingdings fallback (OFL-1.1)](src/pillow_wmf/fonts/OFL.txt)
* [Wine Symbol (LGPL-2.1-or-later)](src/pillow_wmf/fonts/symbol/COPYING.LIB)

