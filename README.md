# pillow-wmf

A Windows Metafile loader for Pillow, under development. The current milestone
provides a WMF reader/writer and a GDI recording/playback interface. Pixel rendering
and Pillow plugin integration are not implemented yet.

Requires Python 3.13 or newer.

```python
from pillow_wmf import Metafile, Recorder, TraceContext, play

recorder = Recorder()
pen = recorder.create_pen(style=0, width=1, color=0x000000FF)
recorder.select_object(pen)
recorder.move_to(10, 10)
recorder.line_to(90, 90)

data = recorder.to_bytes()
metafile = Metafile.from_bytes(data)
assert metafile.to_bytes() == data

trace = TraceContext()
play(metafile, trace, strict=True)
assert trace.calls == recorder.calls
```

`make test` runs unit tests; `make compatibility` runs the compatibility suite;
`make test-all` runs both. Four small WMFs and their Windows-rendered reference
PNGs are committed as compatibility inputs. Delete a PNG to have the Windows
workflow recreate it. Pixel comparisons will follow the first raster backend slice.

- [Implementation contracts and coverage](docs/wmf-implementation.md)
- [Format research and scope](docs/wmf-format-research.md)
- [Complete record inventory](docs/wmf-record-inventory.md)
