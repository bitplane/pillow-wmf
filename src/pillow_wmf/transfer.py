"""Prepare source transfers without changing pixels or drawing state."""

from dataclasses import dataclass, replace
from enum import Enum, auto

from PIL import Image

from .bitmap import RGBBitmap, read_dib
from .bitmap16 import read_bitmap16
from .blit import BlitAxis, StretchAxis
from .clip import ClipRegion, RegionMask
from .constants import HALFTONE
from .halftone import (
    HalftoneExpansion,
    HalftoneMode,
    HalftoneReduction,
    classify_content,
    fixup_candidate,
    halftone_bitmap,
)
from .halftone_fixup import fixup_bitmap
from .mapping import Mapping
from .paint import pattern_rop2
from .palette import LogicalPalette, PaletteIndex


class TransferAction(Enum):
    NOOP = auto()
    PATTERN = auto()


@dataclass(frozen=True)
class SourceTransfer:
    bitmap: RGBBitmap | HalftoneReduction | HalftoneExpansion
    horizontal: BlitAxis | StretchAxis
    vertical: BlitAxis | StretchAxis
    operation: int
    pad_bounds: tuple[int, int, int, int] | None = None


def accepts_dib(layout):
    # The native reference surface is a 32-bit RGB DIB. PAL_INDICES avoids
    # colour translation and requires matching source/device pixel depths.
    return (
        layout.header_size != 12
        and layout.compression in (0, 1, 2, 3)
        and (layout.color_usage != 2 or layout.depth == 32)
    )


@dataclass(frozen=True)
class TransferPreparation:
    """Inputs from the current DC, valid during one preparation operation.

    The image is read only here; self-blits snapshot it before execution.
    Mapping, palette and clipping retain their current native semantics.
    """

    image: Image.Image
    mapping: Mapping
    palette: LogicalPalette
    clip: ClipRegion
    stretch_mode: int
    text_color: tuple[int, int, int] | PaletteIndex
    background_color: tuple[int, int, int] | PaletteIndex
    max_bitmap_pixels: int

    def prepare_device(self, args) -> SourceTransfer | TransferAction:
        """Realize a scan band without stretching its device-pixel geometry."""
        layout = read_dib(args["source"], color_usage=args["color_usage"], max_pixels=self.max_bitmap_pixels)
        x, y, width, height, source_x, source_y = (args[key] for key in ("x", "y", "width", "height", "src_x", "src_y"))
        start, count = args["start_scan"], args["scan_count"]
        # This operation accepts a complete packed DIB, even for a scan band.
        # Short buffers are rejected regardless of SizeImage.
        if (
            not accepts_dib(layout)
            or not layout.complete
            or width <= 0
            or height <= 0
            or not count
            or start >= layout.height
        ):
            return TransferAction.NOOP
        if layout.compression in (1, 2):
            start, count = 0, layout.height
        if not layout.top_down:
            count = min(count, layout.height - start)
        x, y = self.mapping.device_point(x, y)
        if self.mapping.rtl:
            # Device scans keep their order; only the destination
            # rectangle is reflected about the anchor pixel.
            x -= width - 1
        horizontal = BlitAxis(x, source_x, width)
        vertical = BlitAxis(y, start + count - source_y - height, height)
        if layout.compression in (1, 2):
            bitmap = self._decode_device_rle(layout, horizontal, vertical)
        else:
            bitmap = layout.decode(min(count, layout.height), preserve_gaps=True, palette=self.palette.colors())
        return SourceTransfer(bitmap, horizontal, vertical, 0xCC0020)

    def prepare_legacy(self, name, a) -> SourceTransfer | TransferAction:
        if a["source"] is not None:
            layout = read_bitmap16(a["source"], max_pixels=self.max_bitmap_pixels)
            # PlayMetaFileRecord exits after successful bitmap selection,
            # before testing the ROP. Other depths fail selection into the
            # RGB32 memory DC; only source-independent operations can execute
            # without a source bitmap. See gdi-bitmap16.md and native controls.
            if layout.complete and layout.depth not in (1, 32) and pattern_rop2(a["rop"]) is not None:
                return TransferAction.PATTERN
            return TransferAction.NOOP
        if pattern_rop2(a["rop"]) is not None:
            return TransferAction.PATTERN
        # Without embedded bits Windows uses the destination DC as source.
        # Snapshot before painting so overlapping transfers read original data.
        bitmap = RGBBitmap(self.image.width, self.image.height, self.image.tobytes())
        if name == "bit_blt":
            # Equal transforms order both half-open rectangles, then use the
            # destination size and source's low corner. Fractional rounding
            # can give the source a different size; that does not stretch it.
            x, y = self.mapping.edge_point(a["x"], a["y"])
            right, bottom = self.mapping.edge_point(a["x"] + a["width"], a["y"] + a["height"])
            sx, sy = self.mapping.edge_point(
                a["src_x"] + (a["width"] if right < x else 0),
                a["src_y"] + (a["height"] if bottom < y else 0),
            )
            left, top = min(x, right), min(y, bottom)
            return SourceTransfer(
                bitmap,
                BlitAxis(left, sx, abs(right - x)),
                BlitAxis(top, sy, abs(bottom - y)),
                a["rop"],
            )
        sx, sy = self.mapping.device_point(a["src_x"], a["src_y"])
        sw, sh = a.get("src_width", a["width"]), a.get("src_height", a["height"])
        right, bottom = self.mapping.device_point(a["src_x"] + sw, a["src_y"] + sh)
        a = dict(a, src_x=sx, src_width=right - sx, src_height=bottom - sy)
        return self._prepare_bitmap_transfer(
            a, bitmap, sy, depth=32, halftone=self.stretch_mode == HALFTONE, source_dc=True
        )

    def prepare_dib(self, name, a) -> SourceTransfer | TransferAction:
        if pattern_rop2(a["rop"]) is not None:
            return TransferAction.PATTERN
        if a["source"] is None:
            return TransferAction.NOOP
        layout = read_dib(a["source"], color_usage=a.get("color_usage", 0), max_pixels=self.max_bitmap_pixels)
        if not accepts_dib(layout):
            return TransferAction.NOOP
        copy = (a["rop"] >> 16) & 255 == 0xCC
        # DIB[STRETCH]BITBLT realizes a canonical black/white table as a
        # monochrome bitmap. Its bits use the destination DC's text/background
        # colours; STRETCHDIB keeps an explicit RGB table instead.
        monochrome = name != "stretch_dib" and layout.depth == 1 and layout.colors == ((0, 0, 0), (255, 255, 255))
        if monochrome:
            layout = replace(
                layout, colors=tuple(self.palette.colorref(c) for c in (self.text_color, self.background_color))
            )
        sy = a["src_y"]
        # STRETCHDIB exposes DIB-origin coordinates; DIB[STRETCH]BITBLT
        # adapts the source to top-left. The native ternary path also retains
        # the top-down storage distinction documented in gdi-dib-transfers.md.
        if (name == "stretch_dib") != (layout.top_down and not copy):
            sy = layout.height - sy - a.get("src_height", a["height"])
        # A positive, unstretched SRCCOPY from the DIB origin can be sent
        # straight to device scans. Other blits first realize a source bitmap.
        # The distinction is observable for RLE run phase and unwritten gaps.
        direct = (
            copy
            and self.stretch_mode != HALFTONE
            and self.mapping.translation_only
            and a["src_x"] == 0
            and a["src_y"] == 0
            and a["width"] == a.get("src_width", a["width"])
            and a["height"] == a.get("src_height", a["height"])
            and a["width"] > 0
            and a["height"] > 0
        )
        if layout.compression in (1, 2) and direct:
            x, y = self.mapping.device_point(a["x"], a["y"])
            horizontal = BlitAxis.unscaled(x, a["width"], 0, a["width"], layout.width)
            vertical = BlitAxis.unscaled(y, a["height"], sy, a["height"], layout.height)
            bitmap = self._decode_device_rle(layout, horizontal, vertical)
            return SourceTransfer(bitmap, horizontal, vertical, a["rop"])
        bitmap = layout.decode(
            replicate_channels=not (self.stretch_mode == HALFTONE and copy),
            palette=self.palette.colors(),
            # Ternary RLE blits realize a cleared RGB bitmap, not a cleared
            # indexed bitmap: unwritten source pixels are black, not index 0.
            gap_color=None if copy else (0, 0, 0),
        )
        return self._prepare_bitmap_transfer(
            a,
            bitmap,
            sy,
            depth=layout.depth,
            halftone=self.stretch_mode == HALFTONE,
            monochrome_bitblt=monochrome and name == "dib_bit_blt",
        )

    def _decode_device_rle(self, layout, horizontal, vertical):
        """Clip compressed runs at the transfer boundary, before RGB realization."""
        left = max(0, horizontal.destination)
        top = max(0, vertical.destination)
        right = min(self.image.width, horizontal.destination + horizontal.length)
        bottom = min(self.image.height, vertical.destination + vertical.length)
        clip = RegionMask()
        if left < right and top < bottom:
            clip = self.clip.within((left, top, right, bottom)).offset(
                horizontal.source - horizontal.destination, vertical.source - vertical.destination
            )
        return layout.decode(preserve_gaps=True, palette=self.palette.colors(), clip_spans=clip.spans)

    def _prepare_bitmap_transfer(self, a, bitmap, sy, *, depth, halftone, monochrome_bitblt=False, source_dc=False):
        x, y = self.mapping.device_point(a["x"], a["y"])
        right, bottom = self.mapping.device_point(a["x"] + a["width"], a["y"] + a["height"])
        sw, sh = a.get("src_width", a["width"]), a.get("src_height", a["height"])
        dw, dh = right - x, bottom - y
        if self.mapping.rtl and dw > 0 and not source_dc:
            # A second X reflection restores forward scan order. Its anchor
            # is then the exclusive RTL edge rather than the mirrored pixel;
            # negative device extents get this conversion in Blit/StretchAxis.
            # A source using the same DC already shares the RTL transform.
            x += 1
        if not all((sw, sh, dw, dh)):
            return TransferAction.NOOP
        scaled = abs(dw) != abs(sw) or abs(dh) != abs(sh)
        mirrored = (dw < 0) != (sw < 0) or (dh < 0) != (sh < 0)
        copy = (a["rop"] >> 16) & 255 == 0xCC
        halftone = halftone and copy and not (monochrome_bitblt and not scaled)
        if halftone:
            hx = StretchAxis.create(x, dw, a["src_x"], sw, bitmap.width)
            hy = StretchAxis.create(y, dh, sy, sh, bitmap.height)
            left, top = max(0, hx.source), max(0, hy.source)
            right, bottom = min(bitmap.width, hx.source + abs(sw)), min(bitmap.height, hy.source + abs(sh))
            if left >= right or top >= bottom:
                return TransferAction.NOOP
            # Classify the original source once: filtering introduces colours
            # which must not change CheckBMPNeedFixup's dispatch decision.
            content = classify_content(bitmap, left, top, right - left, bottom - top, depth=depth)
            if content.fixup and fixup_candidate(abs(sw), abs(sh), abs(dw), abs(dh)):
                bitmap = fixup_bitmap(bitmap, left, top, right, bottom)
        if scaled and halftone:
            filtered = halftone_bitmap(
                bitmap, hx.source, hy.source, abs(sw), abs(sh), abs(dw), abs(dh), content=content
            )
            if filtered is HalftoneMode.NOOP:
                return TransferAction.NOOP
            if filtered is not HalftoneMode.REPLICATE:
                if not filtered.valid:
                    return TransferAction.NOOP
                return SourceTransfer(
                    filtered,
                    BlitAxis(hx.destination, abs(dw) - 1 if hx.mirrored else 0, abs(dw), -1 if hx.mirrored else 1),
                    BlitAxis(hy.destination, abs(dh) - 1 if hy.mirrored else 0, abs(dh), -1 if hy.mirrored else 1),
                    a["rop"],
                )
        if scaled:
            horizontal = StretchAxis.create(x, dw, a["src_x"], sw, bitmap.width)
            vertical = StretchAxis.create(y, dh, sy, sh, bitmap.height)
        else:
            horizontal = BlitAxis.unscaled(x, dw, a["src_x"], sw, bitmap.width, anchor_pixel=copy or mirrored)
            vertical = BlitAxis.unscaled(y, dh, sy, sh, bitmap.height, anchor_pixel=copy or mirrored)
        pad_bounds = None
        if (scaled or mirrored) and (not copy or (scaled and self.stretch_mode == HALFTONE)):
            left, top = x + min(0, dw + 1), y + min(0, dh + 1)
            pad_bounds = (left, top, left + abs(dw), top + abs(dh))
        return SourceTransfer(bitmap, horizontal, vertical, a["rop"], pad_bounds)
