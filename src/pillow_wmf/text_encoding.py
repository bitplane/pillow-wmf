"""Windows text code pages and source-byte spans."""

from .dbcs import LEAD_RANGES, DecodedText, decode_dbcs
from .environment_codepages import CODECS, decode_environment
from .gdi import UnsupportedOperation

C1_CONTROLS = "".join(map(chr, range(0x80, 0xA0)))

# LOGFONT charset -> Windows code page and OpenType OS/2 coverage bit.
# DEFAULT_CHARSET (1) uses the explicitly configured ANSI environment.
SINGLE_BYTE_CHARSETS = {
    0: (1252, 0),
    238: (1250, 1),
    204: (1251, 2),
    161: (1253, 3),
    162: (1254, 4),
    186: (1257, 7),
    177: (1255, 5),
    178: (1256, 6),
    163: (1258, 8),
    222: (874, 16),
}
TEXT_CHARSETS = SINGLE_BYTE_CHARSETS | {
    128: (932, 17),
    134: (936, 18),
    129: (949, 19),
    136: (950, 20),
    130: (1361, 21),
}
CODEPAGE_BITS = dict(TEXT_CHARSETS.values())

# Windows NLS retains vendor mappings absent from Python's codec tables.
# Other undefined bytes map to the same-valued Unicode character.
UNDEFINED_BYTE_MAPPINGS = {
    1253: {0xAA: 0xF8F9, 0xD2: 0xF8FA, 0xFF: 0xF8FB},
    1255: {
        0xCA: 0x05BA,
        **dict(zip(range(0xD9, 0xE0), range(0xF88D, 0xF894), strict=True)),
        0xFB: 0xF894,
        0xFC: 0xF895,
        0xFF: 0xF896,
    },
    1257: {0xA1: 0xF8FC, 0xA5: 0xF8FD},
    874: {
        **dict(zip(range(0xDB, 0xDF), range(0xF8C1, 0xF8C5), strict=True)),
        **dict(zip(range(0xFC, 0x100), range(0xF8C5, 0xF8C9), strict=True)),
    },
}


def decode_single_byte(data, codepage):
    """Decode using Windows NLS mappings, including undefined/vendor bytes."""
    if codepage in CODECS:
        return decode_environment(data, codepage)
    if codepage not in CODEPAGE_BITS or codepage in LEAD_RANGES:
        raise UnsupportedOperation(f"Unsupported text code page: {codepage}")
    decoded = data.decode(f"cp{codepage}", errors="surrogateescape")
    overrides = UNDEFINED_BYTE_MAPPINGS.get(codepage, {})
    return "".join(
        chr(overrides.get(ord(c) - 0xDC00, ord(c) - 0xDC00)) if 0xDC80 <= ord(c) <= 0xDCFF else c for c in decoded
    )


def decode_codepage(data, codepage):
    """Decode characters and their source spans through one code-page policy."""
    if codepage in LEAD_RANGES:
        return decode_dbcs(data, codepage)
    return DecodedText.single_byte(decode_single_byte(data, codepage))
