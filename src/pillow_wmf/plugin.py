"""Pillow's entry point for the metafile formats rendered here.

Formats without a loader, such as EMF, remain with Pillow's existing handler.
"""

import math

from PIL import Image, ImageFile, WmfImagePlugin

from .gdi import UnsupportedOperation
from .raster import RasterContext
from .system_fonts import SystemFontCollection
from .wmf import FormatError, Limits
from .wmf import loader as wmf_loader
from .wmf.player import PlaybackError

# Each loader identifies its format from a prefix, reads the declared
# placement from the headers, and plays the whole file into a context.
LOADERS = (wmf_loader,)
HEADER_BYTES = max(loader.HEADER_BYTES for loader in LOADERS)


def _loader(prefix):
    return next((loader for loader in LOADERS if loader.accepts(prefix)), None)


class WmfImageFile(ImageFile.ImageFile):
    format = "WMF"
    format_description = "Windows Metafile"

    def _open(self):
        # Identify from the headers only; records are read by load().
        data = self.fp.read(HEADER_BYTES)
        self._loader = _loader(data)
        if self._loader is None:
            raise SyntaxError("Not a supported metafile")
        try:
            self._placement = self._loader.placement(data)
        except FormatError as error:
            raise SyntaxError(str(error)) from error
        self._size = (128, 128)
        if self._placement is not None:
            left, top, right, bottom = self._placement.bounds
            inch = self._placement.units_per_inch
            self._size = (max(1, (right - left) * 72 // inch), max(1, (bottom - top) * 72 // inch))
            self.info.update(dpi=72, wmf_bbox=self._placement.bounds)
        self._mode = "RGB"

    def load(self, *, size=None, dpi=None, fonts=None):
        """Rasterize once; choose size or placement DPI before the first load.

        Files without a declared placement have no physical size and use a
        128-square canvas. Records can override the initial mapping.
        Opening validates only the headers; records are read and parsed here,
        so malformed records, like unsupported drawing, raise OSError rather
        than returning partial art. Invalid caller options raise ValueError.
        """
        if self._im is not None:
            if size is not None or dpi is not None or fonts is not None:
                raise ValueError("WMF is already loaded; reopen it to change rendering options")
            return Image.Image.load(self)
        if size is not None and dpi is not None:
            raise ValueError("Specify size or dpi, not both")
        target = self.size if size is None else size
        if dpi is not None:
            if self._placement is None:
                raise ValueError("DPI requires valid placeable bounds; use size instead")
            density = dpi if isinstance(dpi, tuple) else (dpi, dpi)
            if len(density) != 2 or any(not math.isfinite(v) or v <= 0 for v in density):
                raise ValueError("DPI must contain two positive finite values")
            left, top, right, bottom = self._placement.bounds
            target = tuple(
                max(1, int(extent * value / self._placement.units_per_inch))
                for extent, value in zip((right - left, bottom - top), density, strict=True)
            )
        if len(target) != 2 or any(not isinstance(v, int) or isinstance(v, bool) or v <= 0 for v in target):
            raise ValueError("Size must contain two positive integers")
        target = tuple(target)
        Image._decompression_bomb_check(target)
        fonts = SystemFontCollection() if fonts is None else fonts
        context = RasterContext(*target, fonts=fonts, trace_calls=False)
        try:
            # Bound the read before parsing; header sizes are only advisory.
            self.fp.seek(0)
            self._loader.play_into(context, self.fp.read(Limits().max_bytes + 1), self._placement)
        except (UnsupportedOperation, PlaybackError, FormatError) as error:
            raise OSError(f"Cannot render WMF: {error}") from error
        self._im = context.image.im
        self._size = target
        if dpi is not None:
            self.info["dpi"] = dpi
        if isinstance(fonts, SystemFontCollection):
            self.info["wmf_font_substitutions"] = tuple(fonts.substitutions)
        if self._exclusive_fp:
            self.fp.close()
        self.fp = None
        return Image.Image.load(self)


def _factory(fp, filename):
    prefix = fp.read(16)
    fp.seek(0)
    if _loader(prefix) is not None:
        return WmfImageFile(fp, filename)
    return WmfImagePlugin.WmfStubImageFile(fp, filename)


def register():
    # Importing the built-in module above first prevents lazy Pillow plugin
    # initialization from subsequently replacing this registry entry.
    Image.register_open("WMF", _factory, lambda prefix: _loader(prefix) is not None or WmfImagePlugin._accept(prefix))
    Image.register_extension("WMF", ".wmf")
