"""Windows NLS additions to Python's DBCS codecs.

These are encoding mappings, not font substitutions. User-defined character
areas retain their private-use code points even without a matching EUDC font.
Rows are traversed in lead-byte, then trail-byte order. GBK hole-range endpoints
below are inclusive.
"""

from itertools import product


def _rows(leads, trails, start):
    return {lead * 256 + trail: chr(start + index) for index, (lead, trail) in enumerate(product(leads, trails))}


GBK = {
    0x80: "\u20ac",
    0xFF: "\uf8f5",
    **_rows(range(0xAA, 0xB0), range(0xA1, 0xFF), 0xE000),
    **_rows(range(0xF8, 0xFF), range(0xA1, 0xFF), 0xE234),
    **_rows(range(0xA1, 0xA8), (*range(0x40, 0x7F), *range(0x80, 0xA1)), 0xE4C6),
}
# The remaining GBK user-defined positions fill holes in the symbol rows.
for _first, _last, _unicode in (
    (0xA2AB, 0xA2B0, 0xE766),
    (0xA2E3, 0xA2E4, 0xE76C),
    (0xA2EF, 0xA2F0, 0xE76E),
    (0xA2FD, 0xA2FE, 0xE770),
    (0xA4F4, 0xA4FE, 0xE772),
    (0xA5F7, 0xA5FE, 0xE77D),
    (0xA6B9, 0xA6C0, 0xE785),
    (0xA6D9, 0xA6DF, 0xE78D),
    (0xA6EC, 0xA6ED, 0xE794),
    (0xA6F3, 0xA6F3, 0xE796),
    (0xA6F6, 0xA6FE, 0xE797),
    (0xA7C2, 0xA7D0, 0xE7A0),
    (0xA7F2, 0xA7FE, 0xE7AF),
    (0xA896, 0xA8A0, 0xE7BC),
    (0xA8BC, 0xA8BC, 0xE7C7),
    (0xA8BF, 0xA8BF, 0xE7C8),
    (0xA8C1, 0xA8C4, 0xE7C9),
    (0xA8EA, 0xA8FE, 0xE7CD),
    (0xA958, 0xA958, 0xE7E2),
    (0xA95B, 0xA95B, 0xE7E3),
    (0xA95D, 0xA95F, 0xE7E4),
    (0xA989, 0xA995, 0xE7E7),
    (0xA997, 0xA9A3, 0xE7F4),
    (0xA9F0, 0xA9FE, 0xE801),
    (0xD7FA, 0xD7FE, 0xE810),
    (0xFE50, 0xFE7E, 0xE815),
    (0xFE80, 0xFEA0, 0xE844),
):
    GBK.update({code: chr(_unicode + code - _first) for code in range(_first, _last + 1)})

KOREAN = {0x80: "\x80", 0xFF: "\uf8f7", **_rows((0xC9, 0xFE), range(0xA1, 0xFF), 0xE000)}

_BIG5_TRAILS = (*range(0x40, 0x7F), *range(0xA1, 0xFF))
BIG5 = {
    0x80: "\x80",
    0xFF: "\uf8f8",
    **_rows(range(0xFA, 0xFF), _BIG5_TRAILS, 0xE000),
    **_rows(range(0x8E, 0xA1), _BIG5_TRAILS, 0xE311),
    **_rows(range(0x81, 0x8E), _BIG5_TRAILS, 0xEEB8),
    **_rows((0xC6,), range(0xA1, 0xFF), 0xF6B1),
    **_rows((0xC7, 0xC8), _BIG5_TRAILS, 0xF70F),
}

# Johab's isolated initial, medial and final components map to conjoining
# Jamo, not the compatibility Jamo returned by Python's codec. Full syllables
# still use the codec's algorithm. The all-empty component is undefined.
JOHAB = {
    **{code: chr(code) for code in range(0x80, 0x84)},
    **dict(zip((*range(0xD4, 0xD8), 0xDF, *range(0xFA, 0x100)), map(chr, range(0xF8EC, 0xF8F7)), strict=True)),
    **_rows((0xD8,), (*range(0x31, 0x7F), *range(0x91, 0xFF)), 0xE000),
    0x8441: "?",
    **{0x8841 + index * 0x400: chr(0x1100 + index) for index in range(19)},
    **{
        0x8001 + component * 0x20: chr(0x1161 + index)
        for index, component in enumerate((*range(35, 40), *range(42, 48), *range(50, 56), *range(58, 62)))
    },
    **dict(zip((*range(0x8442, 0x8452), *range(0x8453, 0x845E)), map(chr, range(0x11A8, 0x11C3)), strict=True)),
}
# Archaic Jamo in the symbol row have non-contiguous Unicode assignments.
JOHAB.update(
    dict(
        zip(
            range(0xDAD4, 0xDAFF),
            map(
                chr,
                (
                    0x115F,
                    0x1114,
                    0x1115,
                    0x11C7,
                    0x11C8,
                    0x11CC,
                    0x11CE,
                    0x11D3,
                    0x11D7,
                    0x11D9,
                    0x111C,
                    0x11DD,
                    0x11DF,
                    0x111D,
                    0x111E,
                    0x1120,
                    0x1122,
                    0x1123,
                    0x1127,
                    0x1128,
                    0x112B,
                    0x112C,
                    0x112D,
                    0x112E,
                    0x112F,
                    0x1132,
                    0x1136,
                    0x1140,
                    0x1147,
                    0x114C,
                    0x1145,
                    0x1146,
                    0x1157,
                    0x1158,
                    0x1159,
                    0x1184,
                    0x1185,
                    0x1188,
                    0x1191,
                    0x1192,
                    0x1194,
                    0x119E,
                    0x11A1,
                ),
            ),
            strict=True,
        )
    )
)

OVERRIDES = {936: GBK, 949: KOREAN, 950: BIG5, 1361: JOHAB}
