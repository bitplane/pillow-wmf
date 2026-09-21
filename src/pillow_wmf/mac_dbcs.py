"""Windows Macintosh DBCS mappings, distinct from the similarly named ANSI pages."""

from .dbcs_tables import _rows

CODECS = {10001: "cp932", 10002: "cp950", 10003: "euc_kr", 10008: "gb2312"}
LEAD_RANGES = {
    10001: ((0x81, 0x9F), (0xE0, 0xFC)),
    10002: ((0x81, 0xFC),),
    10003: ((0xA1, 0xAC), (0xB0, 0xC8), (0xCA, 0xFD)),
    10008: ((0xA1, 0xA9), (0xB0, 0xF7)),
}


def _sequence(start, characters):
    return {start + index: character for index, character in enumerate(characters)}


# Japanese enclosed numbers, abbreviations and corporate symbols have Mac
# assignments in rows that the Windows Japanese page uses differently.
JAPANESE = {
    0xA0: "\xa0",
    0xFD: "©",
    0xFE: "™",
    0xFF: "…",
    **_sequence(0x8540, "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"),
    **_sequence(0x859F, "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"),
    **_sequence(0x85B3, "ⅰⅱⅲⅳⅴⅵⅶⅷⅸⅹ"),
    0x8640: "㎜",
    0x8642: "㎝",
    0x8646: "㎡",
    0x8648: "㎞",
    0x864A: "㎎",
    0x864C: "㎏",
    0x864D: "㏄",
    **_sequence(0x869B, "№㏍℡"),
    **_sequence(0x86D3, "→←↑↓"),
    **_sequence(0x8740, "日月火水木金土祭祝自至㈹呼㈱資名㈲学財社特監企協労"),
    **_sequence(0x8791, "大小㊤㊥㊦㊧㊨医財優労印控秘㍉㌢㍍㌔"),
    **_sequence(0x87A7, "㌃㌶㌘"),
    **_sequence(0x87AB, "㌧㍑㍊"),
    **_sequence(0x87AF, "㍗㌍"),
    **_sequence(0x87B2, "㌣㌦㌻㌫"),
    **_sequence(0x87E5, "㍾㍽㍼㍻"),
    **_sequence(0x8840, "∮∟⊿"),
}

# Private-use Big5 rows are numbered monotonically by encoded byte position;
# the ANSI page orders these same rows differently.
_BIG5_TRAILS = (*range(0x40, 0x7F), *range(0xA1, 0xFF))
BIG5 = {
    0x80: "\x80",
    0xFD: "©",
    0xFE: "™",
    0xFF: "…",
    0xA3E1: "?",
    **_rows(range(0x81, 0xA1), _BIG5_TRAILS, 0xE000),
    **_rows((0xC6,), range(0xA1, 0xFF), 0xF3A0),
    **_rows((0xC7, 0xC8), _BIG5_TRAILS, 0xF3FE),
    **_rows(range(0xFA, 0xFD), _BIG5_TRAILS, 0xF538),
}
KOREAN = {
    **{byte: chr(byte) for byte in range(0x80, 0xA0)},
    **dict(zip((0xA0, 0xAD, 0xAE, 0xAF, 0xFE, 0xFF), map(chr, range(0xF8E6, 0xF8EC)), strict=True)),
    0xC9: "\0",
    0xA2E6: "?",
    0xA2E7: "?",
    0xA4D4: "ㅤ",
    0xB4D3: "닖",
}
SIMPLIFIED = {
    0x80: "\x80",
    **{byte: chr(0xF8D8 + byte - 0x81) for byte in range(0x81, 0xA1)},
    **dict.fromkeys(range(0xAA, 0xB0), "\0"),
    **{byte: chr(0xF8F8 + byte - 0xF8) for byte in range(0xF8, 0x100)},
    0xA1AC: "∥",
}
OVERRIDES = {10001: JAPANESE, 10002: BIG5, 10003: KOREAN, 10008: SIMPLIFIED}
