"""Translate logical GDI objects into representable WMF wire objects."""

from ..clip import RegionMask
from ..constants import ETO_PDY
from ..gdi import UnsupportedOperation
from ..objects import EncodedFaceName, EncodedText, GlyphIndices
from .objects import Font, Palette, Region, Scan


def font_record(request):
    values = vars(request).copy()
    name = request.face_name
    if isinstance(name, EncodedFaceName):
        values["face_name"] = name.data
    else:
        # ASCII is independent of the eventual playback ANSI environment.
        # Non-ASCII export must explicitly select its encoded representation.
        try:
            values["face_name"] = name.encode("ascii")
        except UnicodeEncodeError as error:
            raise UnsupportedOperation("WMF font export requires an explicitly encoded non-ASCII face name") from error
    return Font(**values)


def region_record(geometry):
    if geometry is None:
        return Region((0, 0, 0, 0), ())
    rectangles = geometry.rectangles
    # Validate before converting the unsigned scan fields to their wire form.
    if any(not -32768 <= value <= 32767 for rectangle in rectangles for value in rectangle):
        raise ValueError("Region coordinates must fit a signed WMF word")
    bands = RegionMask.from_rectangles(rectangles).bands
    if not bands:
        return Region((0, 0, 0, 0), (Scan(0, 0, (0, 0)),))
    bounds = (
        min(endpoints[0] for _, _, endpoints in bands),
        bands[0][0],
        max(endpoints[-1] for _, _, endpoints in bands),
        bands[-1][1],
    )
    scans = tuple(
        Scan(top & 0xFFFF, bottom & 0xFFFF, tuple(x & 0xFFFF for x in endpoints)) for top, bottom, endpoints in bands
    )
    return Region(bounds, scans)


def wire_arguments(name, arguments):
    arguments = arguments.copy()
    if name in ("text_out", "ext_text_out"):
        text = arguments["text"]
        if isinstance(text, EncodedText):
            arguments["text"] = text.data
        elif isinstance(text, GlyphIndices):
            arguments["text"] = b"".join(index.to_bytes(2, "little") for index in text.indices)
            advances = arguments.get("advances", ())
            if advances:
                # WMF declares a byte count, including for WORD glyph IDs.
                stride = 2 if arguments.get("options", 0) & ETO_PDY else 1
                if len(advances) != len(text.indices) * stride:
                    raise ValueError("Glyph advance count must match the glyph count")
                arguments["advances"] = advances + (0,) * len(advances)
    elif name == "create_font":
        arguments["font"] = font_record(arguments["font"])
    elif name == "create_region":
        arguments["region"] = region_record(arguments["region"])
    elif name == "create_palette":
        palette = arguments["palette"]
        arguments["palette"] = Palette(entries=palette.entries if palette is not None else ())
    elif name in ("set_palette_entries", "animate_palette"):
        update = arguments["palette"]
        arguments["palette"] = Palette(update.start, update.entries)
    return arguments
