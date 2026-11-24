# pillow-wmf

Open Windows Metafiles (WMF) with Pillow.

```sh
pip install pillow-wmf
```

```python
from PIL import Image
import pillow_wmf  # registers the WMF loader

with Image.open("drawing.wmf") as image:
    image.load(size=(640, 480))
    image.save("drawing.png")
```

Omit the `load()` call to use the default size.

## License

[Code](LICENSE.md) · [Wingdings fallback](src/pillow_wmf/fonts/OFL.txt) ·
[Wine Symbol](src/pillow_wmf/fonts/symbol/COPYING.LIB)
