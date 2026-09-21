"""Decoded text retains byte spans for ANSI GDI's byte-indexed advances."""

from dataclasses import dataclass

from .dbcs_tables import OVERRIDES
from .gdi import InvalidOperation, UnsupportedOperation
from .mac_dbcs import CODECS as MAC_CODECS
from .mac_dbcs import LEAD_RANGES as MAC_LEAD_RANGES
from .mac_dbcs import OVERRIDES as MAC_OVERRIDES

LEAD_RANGES = {
    932: ((0x81, 0x9F), (0xE0, 0xFC)),
    936: ((0x81, 0xFE),),
    949: ((0x81, 0xFE),),
    950: ((0x81, 0xFE),),
    1361: ((0x84, 0xD3), (0xD8, 0xDE), (0xE0, 0xF9)),
    **MAC_LEAD_RANGES,
}


@dataclass(frozen=True)
class DecodedText:
    text: str
    byte_lengths: tuple[int, ...]
    byte_indexed_advances: bool = True

    @classmethod
    def single_byte(cls, text):
        return cls(text, (1,) * len(text))


def collapse_advances(advances, byte_lengths, *, byte_indexed=True):
    """Map ANSI advances to characters, including signed x or y offsets.

    GDI collapses byte entries only for CP932/936/949/950. Johab and Mac pages
    keep the first character-count entries; trailing byte entries are unused.
    The WMF array must still supply an entry for every source byte.
    """
    if not advances:
        return ()
    if len(advances) != sum(byte_lengths):
        raise InvalidOperation("Text advance count must match the byte count")
    if not byte_indexed:
        return advances[: len(byte_lengths)]
    result = []
    start = 0
    for length in byte_lengths:
        result.append(sum(advances[start : start + length]))
        start += length
    return tuple(result)


def decode_cp932(data):
    """Decode Windows Japanese text with source-byte spans."""
    return decode_dbcs(data, 932)


def decode_dbcs(data, codepage):
    """Decode Windows DBCS text, preserving NLS replacement boundaries.

    A malformed pair consumes both bytes and becomes the page's replacement
    character: KATAKANA MIDDLE DOT for Japanese pages, question mark for others.
    NUL is the exception: it is retained as a separate character. A dangling
    lead byte also becomes the replacement. Python codecs provide the base
    mappings; explicit Windows extensions preserve vendor and Jamo mappings.
    """
    if codepage not in LEAD_RANGES:
        raise UnsupportedOperation(f"Unsupported DBCS code page: {codepage}")
    ranges = LEAD_RANGES[codepage]
    overrides = MAC_OVERRIDES.get(codepage, OVERRIDES.get(codepage, {}))
    codec = MAC_CODECS.get(codepage, f"cp{codepage}")
    replacement = "\u30fb" if codepage in (932, 10001) else "?"
    characters, lengths = [], []
    index = 0
    while index < len(data):
        first = data[index]
        length = 2 if any(low <= first <= high for low, high in ranges) else 1
        if length == 2 and index + 1 < len(data) and data[index + 1] == 0:
            length = 1
        part = data[index : index + length]
        character = overrides.get(int.from_bytes(part, "big"))
        if character is None:
            try:
                character = part.decode(codec)
            except UnicodeDecodeError:
                character = replacement
        characters.append(character)
        lengths.append(len(part))
        index += length
    return DecodedText("".join(characters), tuple(lengths), byte_indexed_advances=codepage in (932, 936, 949, 950))
