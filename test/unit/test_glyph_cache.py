"""Glyph masks are unpacked exactly and cached within a byte budget."""

from dataclasses import replace
from pathlib import Path

import freetype as ft
import pytest

from pillow_wmf.font import Glyph, GlyphCache, _unpack_bitmap
from pillow_wmf.wmf.objects import Font

FONTS = Path(__file__).resolve().parents[1] / "fonts"
MODES = (
    (ft.FT_LOAD_TARGET_MONO, ft.FT_RENDER_MODE_MONO, True),
    (ft.FT_LOAD_TARGET_NORMAL, ft.FT_RENDER_MODE_NORMAL, False),
    (ft.FT_LOAD_TARGET_LCD, ft.FT_RENDER_MODE_LCD, False),
)


def _per_sample(bitmap, mono):
    packed = bitmap.buffer
    if mono:
        return bytes(
            255 if packed[y * bitmap.pitch + x // 8] & (128 >> (x % 8)) else 0
            for y in range(bitmap.rows)
            for x in range(bitmap.width)
        )
    return bytes(packed[y * bitmap.pitch + x] for y in range(bitmap.rows) for x in range(bitmap.width))


@pytest.mark.parametrize("name", ("layout.ttf", "symbols.ttf", "encoding.ttf"))
@pytest.mark.parametrize("load, render, mono", MODES)
def test_unpacked_masks_match_per_sample_reference(name, load, render, mono):
    face = ft.Face(str(FONTS / name))
    padded = 0
    for size in (3, 7, 13, 21, 40):
        face.set_char_size(size * 64, size * 64, 72, 72)
        for index in range(min(face.num_glyphs, 40)):
            face.load_glyph(index, load | ft.FT_LOAD_NO_AUTOHINT | ft.FT_LOAD_NO_BITMAP)
            face.glyph.render(render)
            bitmap = face.glyph.bitmap
            padded += bitmap.rows > 0 and bitmap.pitch != ((bitmap.width + 7) // 8 if mono else bitmap.width)
            assert _unpack_bitmap(bitmap, mono=mono) == _per_sample(bitmap, mono)
    # Row padding (pitch wider than the samples) must be exercised where
    # FreeType produces it; grey rows are unpadded.
    assert padded or render == ft.FT_RENDER_MODE_NORMAL


def _glyph(index, size):
    return Glyph((size, 1), (0, 0), bytes(size), 1, index)


def test_cache_evicts_least_recently_used_within_budget():
    cache = GlyphCache(limit=10)
    for index in range(3):
        cache.store(index, _glyph(index, 4))
    assert list(cache) == [1, 2] and cache.size == 8
    assert cache.lookup(1).index == 1
    cache.store(3, _glyph(3, 4))
    assert list(cache) == [1, 3] and cache.size == 8
    assert cache.lookup(2) is None
    # A single glyph above the budget is still retained.
    cache.store(4, _glyph(4, 50))
    assert list(cache) == [4] and cache.size == 50
    cache.store(4, _glyph(4, 2))
    assert cache.size == 2


def test_evicted_glyphs_are_rerendered_identically(face):
    font = face.realize(Font(height=-40, quality=4, face_name=b"Pillow WMF Test"), (1, 1))
    font = replace(font, _glyphs=GlyphCache(limit=1))
    first = font.glyph("A", 100000)
    font.glyph("B", 100000)
    assert list(font._glyphs) == [face.cmap[ord("B")]]
    assert font.glyph("A", 100000) == first


def test_replaced_fonts_adopt_a_bounded_cache(face):
    font = face.realize(Font(height=-12, face_name=b"Pillow WMF Test"), (1, 1))
    assert isinstance(replace(font, _glyphs={})._glyphs, GlyphCache)
