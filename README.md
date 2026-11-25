# pillow-wmf

Open Windows Metafiles (WMF) and Enhanced Metafiles (EMF) with Pillow.

```sh
pip install pillow-wmf
```

```python
from PIL import Image
import pillow_wmf  # registers the WMF and EMF loader

with Image.open("drawing.wmf") as image:
    image.load(size=(640, 480))
    image.save("drawing.png")
```

Omit the `load()` call to use the default size. An EMF is fitted to the
requested size through its picture frame, as `PlayEnhMetaFile` does, and by
default is drawn at the frame's size in its reference-device pixels. EMF+
(GDI+) drawing is not rendered; files with a GDI fallback draw that instead.
Records that cannot yet be drawn exactly raise rather than produce partial art.

## License

[Code](LICENSE.md) · [Wingdings fallback](src/pillow_wmf/fonts/OFL.txt) ·
[Wine Symbol](src/pillow_wmf/fonts/symbol/COPYING.LIB)
