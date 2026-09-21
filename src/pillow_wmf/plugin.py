"""Pillow's WMF entry point; EMF remains with Pillow's existing handler."""

import math
import struct

from PIL import Image, ImageFile, WmfImagePlugin

from .raster import RasterContext
from .render import _read_metafile
from .system_fonts import SystemFontCollection
from .wmf import Limits
from .wmf.player import play


def _accept(prefix):
    return prefix.startswith((b"\xd7\xcd\xc6\x9a", b"\x01\x00\x09\x00", b"\x02\x00\x09\x00"))


class WmfImageFile(ImageFile.ImageFile):
    format = "WMF"
    format_description = "Windows Metafile"

    def _open(self):
        # Bound the read before parsing; header mtSize is only advisory.
        self._metafile = _read_metafile(data := self.fp.read(Limits().max_bytes + 1))
        self._bounds = None
        self._inch = None
        self._size = (128, 128)
        if data.startswith(b"\xd7\xcd\xc6\x9a"):
            left, top, right, bottom, inch = struct.unpack_from("<4hH", data, 6)
            if right > left and bottom > top and inch:
                self._bounds = (left, top, right, bottom)
                self._inch = inch
                self._size = (max(1, (right - left) * 72 // inch), max(1, (bottom - top) * 72 // inch))
                self.info.update(dpi=72, wmf_bbox=self._bounds)
        self._mode = "RGB"

    def load(self, *, size=None, dpi=None, fonts=None):
        """Rasterize once; choose size or placeable DPI before the first load.

        Plain WMFs have no physical size. Invalid placeable bounds fall back
        to the same 128-square canvas. Records can override the initial mapping.
        Unsupported drawing fails explicitly rather than returning partial art.
        """
        if self._im is not None:
            if size is not None or dpi is not None or fonts is not None:
                raise ValueError("WMF is already loaded; reopen it to change rendering options")
            return Image.Image.load(self)
        if size is not None and dpi is not None:
            raise ValueError("Specify size or dpi, not both")
        target = self.size if size is None else size
        if dpi is not None:
            if self._bounds is None:
                raise ValueError("DPI requires valid placeable bounds; use size instead")
            density = dpi if isinstance(dpi, tuple) else (dpi, dpi)
            if len(density) != 2 or any(not math.isfinite(v) or v <= 0 for v in density):
                raise ValueError("DPI must contain two positive finite values")
            left, top, right, bottom = self._bounds
            target = tuple(
                max(1, int(extent * value / self._inch))
                for extent, value in zip((right - left, bottom - top), density, strict=True)
            )
        if len(target) != 2 or any(not isinstance(v, int) or isinstance(v, bool) or v <= 0 for v in target):
            raise ValueError("Size must contain two positive integers")
        target = tuple(target)
        Image._decompression_bomb_check(target)
        fonts = SystemFontCollection() if fonts is None else fonts
        context = RasterContext(*target, fonts=fonts)
        if self._bounds is not None:
            left, top, right, bottom = self._bounds
            context.mapping.window_origin = (left, top)
            context.mapping.window_extent = (right - left, bottom - top)
        play(self._metafile, context, strict=True)
        self._im = context.image.im
        self._size = target
        if dpi is not None:
            self.info["dpi"] = dpi
        if isinstance(fonts, SystemFontCollection):
            self.info["wmf_font_substitutions"] = tuple(fonts.substitutions)
        del self._metafile
        if self._exclusive_fp:
            self.fp.close()
        self.fp = None
        return Image.Image.load(self)


def _factory(fp, filename):
    prefix = fp.read(16)
    fp.seek(0)
    if _accept(prefix):
        return WmfImageFile(fp, filename)
    return WmfImagePlugin.WmfStubImageFile(fp, filename)


def register():
    # Importing the built-in module above first prevents lazy Pillow plugin
    # initialization from subsequently replacing this registry entry.
    Image.register_open("WMF", _factory, lambda prefix: _accept(prefix) or WmfImagePlugin._accept(prefix))
    Image.register_extension("WMF", ".wmf")
