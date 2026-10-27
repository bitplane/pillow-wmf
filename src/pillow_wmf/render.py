"""Complete WMF rendering; use ``play`` when collecting omissions is required."""

from PIL import Image

from .bitmap import DEFAULT_MAX_BITMAP_PIXELS
from .geometry import DEFAULT_MAX_GEOMETRY_POINTS
from .raster import RasterContext
from .system_fonts import SystemFontCollection
from .text import FontCollection
from .wmf import FormatError, Limits, Metafile
from .wmf.player import play


def _read_metafile(data, limits=None):
    """Read for an explicitly sized DC; the placeable wrapper is not GDI data.

    Keep codec validation strict for callers inspecting the wrapper. Native
    playback receives only the enclosed WMF, independent of wrapper checksum,
    physical units or suggested bounds. Byte limits still include the wrapper.
    """
    limits = limits if limits is not None else Limits()
    if not isinstance(data, bytes):
        raise TypeError("Input must be immutable bytes")
    if len(data) > limits.max_bytes:
        raise FormatError("File byte limit exceeded")
    if data.startswith(b"\xd7\xcd\xc6\x9a"):
        if len(data) < 22:
            raise FormatError("Truncated placeable WMF header")
        data = data[22:]
    return Metafile.from_bytes(data, limits=limits)


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

    Size is the output canvas in pixels. Playback uses the WMF's mapping calls;
    neither placeable bounds nor drawing bounds implicitly fit the image.
    Fonts are supplied explicitly. For partial rendering with diagnostics, use
    ``play(metafile, context, strict=False)`` and inspect its omissions instead.
    """
    limits = limits if limits is not None else Limits()
    metafile = _read_metafile(data, limits)
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
    play(metafile, context, strict=True, limits=limits)
    if isinstance(fonts, SystemFontCollection):
        context.image.info["wmf_font_substitutions"] = tuple(fonts.substitutions)
    return context.image
