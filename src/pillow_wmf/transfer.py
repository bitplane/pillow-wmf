"""Prepare source transfers without changing pixels or drawing state."""

from dataclasses import dataclass, replace
from enum import Enum, auto

from .bitmap import RGBBitmap, read_dib
from .bitmap16 import read_bitmap16
from .blit import BlitAxis, StretchAxis
from .clip import ClipRegion, RegionMask
from .color_adjustment import AdjustedBitmap, ColorAdjustment
from .color_engine import MappedBitmap, MappedView
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
from .surface import Surface


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
    # JPEG, PNG, alpha bit fields, CMYK, 2- and 64-bit sources and OS/2
    # Huffman or RLE24 sources do not draw on it.
    return (
        layout.header_size != 12
        and layout.compression in (0, 1, 2, 3)
        and layout.depth in (1, 4, 8, 16, 24, 32)
        and not (layout.header_size == 64 and layout.compression == 3)
        and (layout.color_usage != 2 or layout.depth == 32)
    )


@dataclass(frozen=True)
class TransferPreparation:
    """Inputs from the current DC, valid during one preparation operation.

    The surface is read only here; self-blits snapshot it before execution.
    Mapping, palette and clipping retain their current native semantics.
    """

    surface: Surface
    mapping: Mapping
    palette: LogicalPalette
    clip: ClipRegion
    stretch_mode: int
    color_adjustment: ColorAdjustment
    text_color: tuple[int, int, int] | PaletteIndex
    background_color: tuple[int, int, int] | PaletteIndex
    max_bitmap_pixels: int

    def prepare_device(self, args) -> SourceTransfer | TransferAction:
        """Realize a scan band without stretching its device-pixel geometry."""
        if args["color_usage"] not in (0, 1, 2):
            return TransferAction.NOOP  # Other colour usages fail natively.
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
        bitmap = self.surface.snapshot()
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
        if a.get("color_usage", 0) not in (0, 1, 2):
            return TransferAction.NOOP  # Other colour usages fail natively.
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
        right = min(self.surface.width, horizontal.destination + horizontal.length)
        bottom = min(self.surface.height, vertical.destination + vertical.length)
        clip = RegionMask()
        if left < right and top < bottom:
            clip = self.clip.within((left, top, right, bottom)).offset(
                horizontal.source - horizontal.destination, vertical.source - vertical.destination
            )
        return layout.decode(preserve_gaps=True, palette=self.palette.colors(), clip_spans=clip.spans)

    def _engine_source(self, bitmap, hx, hy, sw, sh, dw, dh, content):
        """The source, and a wrapper for the filtered view, for the colour engine.

        Enlargements map source scans as they are read, each read advancing
        the dither one row; reductions map the reduced destination pixels.
        Dithering starts at the first visible destination column modulo 65
        (each dither row holds 64 thresholds and a copy of its first) and at
        the first visible row, or the last for a vertically flipped transfer,
        which counts down. Scans start at the first source column and row a
        visible pixel samples (by the stretch's centre-phase step), and:

        - replication reads from there;
        - the fast enlargement filter first reads two more scans, re-reading
          the bitmap's top row where it has none above (when mirrored, two
          scans whatever is above);
        - the general filter, and the fast one when mirrored, first read up
          to two real columns, and the general one up to two real scans;
        - scans beyond the bitmap's edges are each dithered afresh.
        """
        width, height = abs(dw), abs(dh)
        left, top = hx.destination, hy.destination
        bounds = (
            max(0, left),
            max(0, top),
            min(self.surface.width, left + width),
            min(self.surface.height, top + height),
        )
        visible = list(self.clip.within(bounds).rectangles()) if bounds[0] < bounds[2] and bounds[1] < bounds[3] else []
        if not visible:
            return bitmap, None
        x0, y0 = min(r[0] for r in visible), min(r[1] for r in visible)
        x1, y1 = max(r[2] for r in visible), max(r[3] for r in visible)
        table = self.color_adjustment.colour_map
        mode = halftone_bitmap(bitmap, hx.source, hy.source, abs(sw), abs(sh), width, height, content=content)
        replicate = mode is HalftoneMode.REPLICATE or mode is HalftoneMode.NOOP
        if not replicate and not isinstance(mode, HalftoneExpansion):
            column = left + width - 1 if hx.mirrored else left
            row = top + height - 1 if hy.mirrored else top
            x_step, y_step = (-1 if hx.mirrored else 1), (-1 if hy.mirrored else 1)
            return bitmap, lambda view: MappedView(view, table, column, row, x_step, y_step, x0 % 65 - x0)
        fast = not replicate and mode.fast
        general = not replicate and not fast
        mirrored = hx.mirrored or hy.mirrored

        def first(offset, source, source_length, length):
            if fast:
                return source + ((2 * offset + 1) * source_length - 1) // (2 * length)
            return source + (2 * offset + 1) * source_length // (2 * length)

        source_x = first(left + width - x1 if hx.mirrored else x0 - left, hx.source, abs(sw), width)
        source_y = first(top + height - y1 if hy.mirrored else y0 - top, hy.source, abs(sh), height)
        column = x0 % 65 - source_x + (min(2, max(0, source_x)) if general or (fast and mirrored) else 0)
        if general:
            lead = min(2, max(0, source_y))
        elif fast:
            lead = 2 if mirrored else 2 - min(2, max(0, source_y))
        else:
            lead = 0
        if hy.mirrored:
            mapped = MappedBitmap(bitmap, table, column, y1 - 1 - lead + source_y, -1)
        else:
            mapped = MappedBitmap(bitmap, table, column, y0 + lead - source_y)
        return (mapped.materialize() if replicate else mapped), None

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
        engine_view = None
        if scaled and halftone and self.color_adjustment.engine:
            bitmap, engine_view = self._engine_source(bitmap, hx, hy, sw, sh, dw, dh, content)
        if scaled and halftone:
            filtered = halftone_bitmap(
                bitmap, hx.source, hy.source, abs(sw), abs(sh), abs(dw), abs(dh), content=content
            )
            if filtered is HalftoneMode.NOOP:
                return TransferAction.NOOP
            if filtered is not HalftoneMode.REPLICATE:
                if not filtered.valid:
                    return TransferAction.NOOP
                if engine_view:
                    filtered = engine_view(filtered)
                if not self.color_adjustment.neutral_tables:
                    filtered = AdjustedBitmap(filtered, self.color_adjustment)
                return SourceTransfer(
                    filtered,
                    BlitAxis(hx.destination, abs(dw) - 1 if hx.mirrored else 0, abs(dw), -1 if hx.mirrored else 1),
                    BlitAxis(hy.destination, abs(dh) - 1 if hy.mirrored else 0, abs(dh), -1 if hy.mirrored else 1),
                    a["rop"],
                )
        if scaled and halftone and not self.color_adjustment.neutral_tables:
            # Replicated HALFTONE enlargements are colour-adjusted too.
            bitmap = AdjustedBitmap(bitmap, self.color_adjustment)
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
