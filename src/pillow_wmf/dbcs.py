"""Decoded text retains byte spans for ANSI GDI's byte-indexed advances."""

from dataclasses import dataclass

from .gdi import InvalidOperation


@dataclass(frozen=True)
class DecodedText:
    text: str
    byte_lengths: tuple[int, ...]

    @classmethod
    def single_byte(cls, text):
        return cls(text, (1,) * len(text))


def collapse_advances(advances, byte_lengths):
    """Sum each character's byte entries, including signed x or y offsets."""
    if not advances:
        return ()
    if len(advances) != sum(byte_lengths):
        raise InvalidOperation("Text advance count must match the byte count")
    result = []
    start = 0
    for length in byte_lengths:
        result.append(sum(advances[start : start + length]))
        start += length
    return tuple(result)


def decode_cp932(data):
    """Decode Windows Japanese text, preserving NLS replacement boundaries.

    A malformed pair consumes both bytes and becomes KATAKANA MIDDLE DOT.
    NUL is the exception: it is retained as a separate character. A dangling
    lead byte also becomes the middle dot. Valid mappings use Python's CP932
    table, verified against native NLS for all singles and lead/trail pairs.
    """
    characters, lengths = [], []
    index = 0
    while index < len(data):
        first = data[index]
        length = 2 if 0x81 <= first <= 0x9F or 0xE0 <= first <= 0xFC else 1
        if length == 2 and index + 1 < len(data) and data[index + 1] == 0:
            length = 1
        part = data[index : index + length]
        try:
            character = part.decode("cp932")
        except UnicodeDecodeError:
            character = "\u30fb"
        characters.append(character)
        lengths.append(len(part))
        index += length
    return DecodedText("".join(characters), tuple(lengths))
