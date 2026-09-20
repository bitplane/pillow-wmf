"""Complete WMF rendering; use ``play`` when collecting omissions is required."""

from PIL import Image

from .bitmap import DEFAULT_MAX_BITMAP_PIXELS
from .raster import RasterContext
from .text import FontCollection
from .wmf import Limits, Metafile
from .wmf.player import play


def render(
    data: bytes,
    size: tuple[int, int],
    *,
    fonts: FontCollection | None = None,
    background=(255, 255, 255),
    limits: Limits | None = None,
    max_bitmap_pixels: int = DEFAULT_MAX_BITMAP_PIXELS,
) -> Image.Image:
    """Render to an RGB image, raising if any record cannot be rendered.

    Size is the output canvas in pixels. Playback uses the WMF's mapping calls;
    neither placeable bounds nor drawing bounds implicitly fit the image.
    Fonts are supplied explicitly. For partial rendering with diagnostics, use
    ``play(metafile, context, strict=False)`` and inspect its omissions instead.
    """
    metafile = Metafile.from_bytes(data, limits=limits)
    context = RasterContext(*size, background=background, fonts=fonts, max_bitmap_pixels=max_bitmap_pixels)
    play(metafile, context, strict=True, limits=limits)
    return context.image
