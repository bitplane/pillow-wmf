"""Boolean raster operations for RGB pattern, source and destination pixels."""

type RGB = tuple[int, int, int]


def rop3(rop: int, pattern: RGB, source: RGB, destination: RGB) -> RGB:
    """Evaluate the eight-entry P,S,D table in bits 16..23 of a GDI ROP.

    Split on P: each half is an S,D binary table. This covers all 256
    functions without a catalogue of named raster-operation exceptions.
    """
    table = (rop >> 16) & 255
    zero = rop2((table & 15) + 1, source, destination)
    one = rop2((table >> 4) + 1, source, destination)
    return tuple((a & ~p) | (b & p) for p, a, b in zip(pattern, zero, one, strict=True))


def pattern_rop2(rop: int) -> int | None:
    """Reduce a source-independent ROP3 to ROP2; otherwise return None."""
    table = (rop >> 16) & 255
    if (table & 0x33) != ((table >> 2) & 0x33):
        return None
    return ((table & 3) | ((table >> 2) & 12)) + 1


def rop2(mode: int, source: RGB, destination: RGB) -> RGB:
    """Apply the four-entry P,D truth table encoded by a WMF ROP2 value.

    The entries are ordered (P,D) = 00, 01, 10, 11. Windows numbers the
    sixteen possible tables from 1 through 16, so the table bits are mode-1.
    """
    if not 1 <= mode <= 16:
        raise ValueError("ROP2 mode must be between 1 and 16")
    table = mode - 1
    channels = []
    for p, d in zip(source, destination, strict=True):
        value = (
            ((table & 1) * (~p & ~d))
            | (((table >> 1) & 1) * (~p & d))
            | (((table >> 2) & 1) * (p & ~d))
            | (((table >> 3) & 1) * (p & d))
        )
        channels.append(value & 255)
    return tuple(channels)
