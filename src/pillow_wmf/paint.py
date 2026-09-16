"""Binary raster operations for RGB pen and brush pixels."""

type RGB = tuple[int, int, int]


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
