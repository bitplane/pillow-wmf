"""Native Windows OEM/Mac mapping additions to Python codecs.

Byte tables preserve vendor/private-use values without normalization.
The three full upper-half tables cover pages without a matching Python codec.
Regressions fingerprint every byte against the native NLS probe.
"""

OEM_CODECS = {
    page: f"cp{page}" for page in (437, 720, 737, 775, 850, 852, 855, 857, 858, 860, 861, 862, 863, 864, 865, 866, 869)
}
MAC_CODECS = {
    10000: "mac_roman",
    10004: "mac_arabic",
    10006: "mac_greek",
    10007: "mac_cyrillic",
    10010: "mac_romanian",
    10017: "mac_cyrillic",
    10029: "mac_latin2",
    10079: "mac_iceland",
    10081: "mac_turkish",
    10082: "mac_croatian",
}

OVERRIDES = {
    10000: {0xBD: 0x2126},
    10004: {
        0xA0: 0xF827,
        0xA1: 0xF828,
        0xA2: 0xF829,
        0xA3: 0xF82A,
        0xA4: 0xF82B,
        0xA6: 0xF82C,
        0xA7: 0xF82D,
        0xA8: 0xF82E,
        0xA9: 0xF82F,
        0xAA: 0xF830,
        0xAB: 0xF831,
        0xAD: 0xF832,
        0xAE: 0xF833,
        0xAF: 0xF834,
        0xBA: 0xF835,
        0xBC: 0xF836,
        0xBD: 0xF837,
        0xBE: 0xF838,
        0xC0: 0x066D,
        0xDB: 0xF839,
        0xDC: 0xF83A,
        0xDD: 0xF83B,
        0xDE: 0xF83C,
        0xDF: 0xF83D,
        0xFB: 0xF83E,
        0xFC: 0xF83F,
        0xFD: 0xF840,
    },
    10006: {0x9C: 0x00AD, 0xAF: 0x0387, 0xFF: 0xF8A0},
    10007: {0xA2: 0x00A2, 0xB6: 0x2202, 0xFF: 0x00A4},
    10010: {0xAF: 0x015E, 0xBD: 0x2126, 0xBF: 0x015F, 0xDB: 0x00A4, 0xDE: 0x0162, 0xDF: 0x0163},
    10017: {0xFF: 0x00A4},
    10021: {0x7F: 0x0000},
    10079: {0xBD: 0x2126, 0xDB: 0x00A4},
    10081: {0xBD: 0x2126},
    10082: {0xBD: 0x2126, 0xDB: 0x00A4},
    857: {0xD5: 0xF8BB, 0xE7: 0xF8BC, 0xF2: 0xF8BD},
    864: {0x25: 0x0025, 0x9B: 0x009B, 0x9C: 0x009C, 0x9F: 0x009F, 0xA6: 0xF8BE, 0xA7: 0xF8BF, 0xFF: 0xF8C0},
    869: {
        0x80: 0x0080,
        0x81: 0x0081,
        0x82: 0x0082,
        0x83: 0x0083,
        0x84: 0x0084,
        0x85: 0x0085,
        0x87: 0x0087,
        0x93: 0x0093,
        0x94: 0x0094,
    },
}

UPPER_TABLES = {
    708: (
        "\u2502\u2524\u00e9\u00e2\u2561\u00e0\u2562\u00e7\u00ea\u00eb\u00e8\u00ef\u00ee\u2556\u2555\u2563"
        "\u2551\u2557\u255d\u00f4\u255c\u255b\u00fb\u00f9\u2510\u2514\u009a\u009b\u009c\u009d\u009e\u009f"
        "\uf8c1\u2534\u252c\u251c\u00a4\u2500\u253c\u255e\u255f\u255a\u2554\u2569\u060c\u2566\u00ab\u00bb"
        "\u2591\u2592\u2593\u2560\u2550\u256c\u2567\u2568\u2564\u2565\u2559\u061b\u2558\u2552\u2553\u061f"
        "\u256b\u0621\u0622\u0623\u0624\u0625\u0626\u0627\u0628\u0629\u062a\u062b\u062c\u062d\u062e\u062f"
        "\u0630\u0631\u0632\u0633\u0634\u0635\u0636\u0637\u0638\u0639\u063a\u2588\u2584\u258c\u2590\u2580"
        "\u0640\u0641\u0642\u0643\u0644\u0645\u0646\u0647\u0648\u0649\u064a\u064b\u064c\u064d\u064e\u064f"
        "\u0650\u0651\u0652\uf8c2\uf8c3\uf8c4\uf8c5\uf8c6\uf8c7\u256a\u2518\u250c\u00b5\u00a3\u25a0\u00a0"
    ),
    10005: (
        "\u00c4\u00c5\u00c7\u00c9\u00d1\u00d6\u00dc\u00e1\u00e0\u00e2\u00e4\u00e3\u00e5\u00e7\u00e9\u00e8"
        "\u00ea\u00eb\u00ed\u00ec\u00ee\u00ef\u00f1\u00f3\u00f2\u00f4\u00f6\u00f5\u00fa\u00f9\u00fb\u00fc"
        "\uf7fc\uf7fd\uf7fe\uf7ff\u00a4\uf800\u20aa\uf801\uf802\uf803\uf804\uf805\uf806\uf807\uf808\uf809"
        "\uf80a\uf80b\uf80c\uf80d\uf80e\uf80f\uf810\uf811\uf812\uf813\uf814\uf815\uf816\uf817\uf818\uf819"
        "\uf81a\u201e\uf81b\uf81c\uf81d\u05bd\u05bc\uf81e\uf81f\u2026\u00a0\u05b8\u05b7\u05b5\u05b6\u05b4"
        "\u2013\u2014\u201c\u201d\u2018\u2019\uf820\uf821\u05be\u05b0\u05b2\u05b1\u05bb\u05c1\u05b8\u05b3"
        "\u05d0\u05d1\u05d2\u05d3\u05d4\u05d5\u05d6\u05d7\u05d8\u05d9\u05da\u05db\u05dc\u05dd\u05de\u05df"
        "\u05e0\u05e1\u05e2\u05e3\u05e4\u05e5\u05e6\u05e7\u05e8\u05e9\u05ea\uf822\uf823\uf824\uf825\uf826"
    ),
    10021: (
        "\u00ab\u00bb\u2026\u0e48\u0e49\u0e4a\u0e4b\u0e4c\u0e48\u0e49\u0e4a\u0e4b\u0e4c\u201c\u201d\u0e4d"
        "\u0000\u2022\u0e31\u0e47\u0e34\u0e35\u0e36\u0e37\u0e48\u0e49\u0e4a\u0e4b\u0e4c\u2018\u2019\u0000"
        "\u00a0\u0e01\u0e02\u0e03\u0e04\u0e05\u0e06\u0e07\u0e08\u0e09\u0e0a\u0e0b\u0e0c\u0e0d\u0e0e\u0e0f"
        "\u0e10\u0e11\u0e12\u0e13\u0e14\u0e15\u0e16\u0e17\u0e18\u0e19\u0e1a\u0e1b\u0e1c\u0e1d\u0e1e\u0e1f"
        "\u0e20\u0e21\u0e22\u0e23\u0e24\u0e25\u0e26\u0e27\u0e28\u0e29\u0e2a\u0e2b\u0e2c\u0e2d\u0e2e\u0e2f"
        "\u0e30\u0e31\u0e32\u0e33\u0e34\u0e35\u0e36\u0e37\u0e38\u0e39\u0e3a\ufeff\u200b\u2013\u2014\u0e3f"
        "\u0e40\u0e41\u0e42\u0e43\u0e44\u0e45\u0e46\u0e47\u0e48\u0e49\u0e4a\u0e4b\u0e4c\u0e4d\u2122\u0e4f"
        "\u0e50\u0e51\u0e52\u0e53\u0e54\u0e55\u0e56\u0e57\u0e58\u0e59\u00ae\u00a9\u0000\u0000\u0000\u0000"
    ),
}

OEM_CODECS[708] = None
MAC_CODECS.update({10005: None, 10021: None})
CODECS = OEM_CODECS | MAC_CODECS
OEM_COVERAGE_BITS = {
    codepage: bit
    for bit, codepage in enumerate((869, 866, 865, 864, 863, 862, 861, 860, 857, 855, 852, 775, 737, 708, 850, 437), 48)
}


def decode_environment(data, codepage):
    """Decode a verified, single-byte legacy environment page."""
    if codepage in UPPER_TABLES:
        upper = UPPER_TABLES[codepage]
        text = "".join(upper[b - 128] if b >= 128 else chr(b) for b in data)
    else:
        text = data.decode(CODECS[codepage], errors="surrogateescape")
    overrides = OVERRIDES.get(codepage, {})
    return "".join(chr(overrides[b]) if b in overrides else c for b, c in zip(data, text, strict=True))
