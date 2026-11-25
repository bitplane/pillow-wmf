"""Complete WMF or EMF rendering; use ``play`` when collecting omissions is required."""

from PIL import Image

from .bitmap import DEFAULT_MAX_BITMAP_PIXELS
from .emf import loader as emf_loader
from .emf import play as play_emf
from .geometry import DEFAULT_MAX_GEOMETRY_POINTS
from .raster import RasterContext
from .system_fonts import SystemFontCollection
from .text import FontCollection
from .wmf import Limits
from .wmf.loader import read
from .wmf.player import play


def render(
    data: bytes,
    size: tuple[int, int],
    *,
    fonts: FontCollection | None = None,
    background=(255, 255, 255),
    limits: Limits | None = None,
    max_bitmap_pixels: int = DEFAULT_MAX_BITMAP_PIXELS,
    max_geometry_points: int = DEFAULT_MAX_GEOMETRY_POINTS,
) -> Image.Image:
    """Render to an RGB image, raising if any record cannot be rendered.

    Size is the output canvas in pixels. WMF playback uses the file's mapping
    calls; neither placeable bounds nor drawing bounds implicitly fit the
    image. EMF playback fits the picture frame to the whole canvas, as
    PlayEnhMetaFile does with that rectangle.
    Fonts are supplied explicitly. For partial rendering with diagnostics, use
    ``play(metafile, context, strict=False)`` and inspect its omissions instead.
    """
    limits = limits if limits is not None else Limits()
    emf = emf_loader.accepts(data[: emf_loader.HEADER_BYTES])
    metafile = emf_loader.read(data, limits) if emf else read(data, limits)
    context = RasterContext(
        *size,
        background=background,
        fonts=fonts,
        max_bitmap_pixels=max_bitmap_pixels,
        max_geometry_points=max_geometry_points,
        max_objects=limits.max_objects,
        max_saved_states=limits.max_saved_states,
        trace_calls=False,
    )
    if emf:
        play_emf(metafile, context, strict=True, limits=limits, rect=(0, 0, *size))
    else:
        play(metafile, context, strict=True, limits=limits)
    if isinstance(fonts, SystemFontCollection):
        context.image.info["wmf_font_substitutions"] = tuple(fonts.substitutions)
    return context.image
