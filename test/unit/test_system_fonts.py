"""Automatic font policy tested with controlled inventories, never host fonts."""

from dataclasses import replace
from pathlib import Path

import pytest
from fontTools.ttLib import TTCollection, TTFont

from pillow_wmf import Font, FontCollection, Recorder, SystemFontCollection, UnsupportedOperation, render
from pillow_wmf.system_fonts import font_paths

SOURCE = Path(__file__).parents[1] / "fonts/layout.ttf"


@pytest.fixture
def installed(tmp_path):
    def make(family, *, weight=400, italic=False, keep=None, source=SOURCE):
        path = tmp_path / f"{family}-{weight}-{italic}.ttf"
        with TTFont(source) as font:
            for record in font["name"].names:
                if record.nameID in (1, 16):
                    record.string = family.encode(record.getEncoding())
            font["OS/2"].usWeightClass = weight
            font["OS/2"].fsSelection = 1 if italic else 0
            if keep is not None:
                for table in font["cmap"].tables:
                    table.cmap = {c: g for c, g in table.cmap.items() if c in keep}
            font.save(path)
        return path

    return make


def request(name="Arial", **kwargs):
    return Font(face_name=name.encode(), height=-16, **kwargs)


def test_discovery_is_lazy_and_explicit_collection_never_discovers(monkeypatch, face):
    def forbidden():
        raise AssertionError("host discovery")

    monkeypatch.setattr("pillow_wmf.system_fonts.font_paths", forbidden)
    SystemFontCollection()
    fonts = FontCollection([face])
    assert fonts.resolve(request(face.family)) is face


def test_requested_family_and_style_win_over_substitutes(installed):
    paths = [installed("Liberation Sans"), installed("Arial"), installed("Arial", weight=700, italic=True)]
    fonts = SystemFontCollection(paths=paths)
    face = fonts.resolve(request(weight=700, italic=1))
    assert (face.family, face.weight, face.italic) == ("Arial", 700, True)
    assert not fonts.substitutions


def test_family_substitution_and_default_are_reported_once(installed):
    fonts = SystemFontCollection(paths=[installed("Liberation Sans")])
    assert fonts.resolve(None).family == "Liberation Sans"
    assert fonts.resolve(request()).family == "Liberation Sans"
    assert len(fonts.substitutions) == 1
    assert fonts.substitutions[0].reason == "family"


@pytest.mark.parametrize("family,target", [("Times New Roman", "Liberation Serif"), ("Courier New", "Liberation Mono")])
def test_familiar_families_choose_matching_substitutes(installed, family, target):
    fonts = SystemFontCollection(paths=[installed("Liberation Sans"), installed(target)])
    assert fonts.resolve(request(family)).family == target


def test_pitch_family_guides_unknown_names(installed):
    fonts = SystemFontCollection(paths=[installed("Liberation Sans"), installed("Liberation Mono")])
    assert fonts.resolve(request("Unavailable", pitch_and_family=1)).family == "Liberation Mono"


@pytest.mark.parametrize("hint,target", [(0, "Liberation Sans"), (16, "Liberation Serif"), (49, "Liberation Mono")])
def test_unknown_charset_discards_ordinary_family_but_retains_hints(installed, hint, target):
    paths = [installed(name) for name in ("Original", "Liberation Sans", "Liberation Serif", "Liberation Mono")]
    fonts = SystemFontCollection(paths=paths)
    selected = fonts.resolve(request("Original", charset=160, pitch_and_family=hint))
    assert selected.family == target
    assert fonts.substitutions[-1].requested == "Original"
    assert fonts.substitutions[-1].reason == "charset 160 fallback to ANSI"


def test_oem_wingdings_request_selects_ordinary_text_font(installed):
    fonts = SystemFontCollection(paths=[installed("Liberation Sans")])
    req = request("Wingdings", charset=255)
    selected = fonts.resolve(req)
    assert selected.family == "Liberation Sans"
    assert fonts.decode(req, selected, b"\x80") == "Ç"
    assert fonts.substitutions[-1].reason == "charset 255 fallback to OEM"


def test_ansi_request_skips_custom_symbol_face_but_default_selects_it(installed):
    fonts = SystemFontCollection(paths=[SOURCE.with_name("symbols.ttf"), installed("Liberation Sans")])
    req = request("Pillow WMF Symbols", charset=0)
    selected = fonts.resolve(req)
    assert selected.family == "Liberation Sans"
    assert fonts.decode(req, selected, b"AB\x80") == "AB\u20ac"
    for charset in (1, 2):
        selected = fonts.resolve(replace(req, charset=charset))
        assert selected.family == "Pillow WMF Symbols" and selected.symbol


def test_coverage_fallback_preserves_primary_and_reports_holes(installed):
    fonts = SystemFontCollection(paths=[installed("Arial", keep={65}), installed("Other", keep={66})])
    req = request()
    face = fonts.resolve(req)
    run = fonts.layout_font(req, face, (1, 1), characters="ABZ")
    assert len(run.fallbacks) == 1
    assert run.primary.cmap.get(65)
    assert run.fallbacks[0].cmap.get(66)
    assert {s.reason for s in fonts.substitutions} == {"glyph coverage", "missing glyph"}


def test_substitution_does_not_change_byte_encoding(installed):
    fonts = SystemFontCollection(paths=[installed("Arial", keep={65})])
    req = request(charset=204)
    face = fonts.resolve(req)
    assert fonts.decode(req, face, b"\xc0") == "А"
    assert fonts.decode(replace(req, charset=128), face, b"\x83\xa1") == "\u0393"
    assert fonts.decode(replace(req, charset=160), face, b"\xe9") == "é"
    assert fonts.substitutions[-1].reason == "charset 160 fallback to ANSI"


def test_wingdings_and_missing_symbol_families_work_without_system_fonts():
    fonts = SystemFontCollection(paths=[])
    req = request("Wingdings", charset=2)
    face = fonts.resolve(req)
    assert fonts.decode(req, face, b"!") != "!"
    assert fonts.substitutions[0].reason == "symbol mapping"
    for family in ("Webdings", "Wingdings 2"):
        assert fonts.resolve(request(family, charset=2)) is face
        assert fonts.substitutions[-1].reason == "symbol charset fallback"


@pytest.mark.parametrize("hint", (0, 16, 32, 48, 64, 80))
@pytest.mark.parametrize("pitch", (0, 1, 2))
def test_native_missing_symbol_pitch_and_family_selection(installed, hint, pitch):
    fonts = SystemFontCollection(paths=[installed("Webdings", source=SOURCE.with_name("symbols.ttf"))])
    req = request("Unavailable", charset=2, pitch_and_family=hint | pitch)
    expected = {
        0: ("Pillow WMF Wingdings Fallback", "Webdings", "Pillow WMF Wingdings Fallback"),
        16: ("Symbol", "Webdings", "Symbol"),
    }.get(hint, ("Pillow WMF Wingdings Fallback",) * 3)[pitch]
    assert fonts.resolve(req).family == expected
    assert fonts.substitutions[-1].reason == "symbol charset fallback"


def test_missing_webdings_fallback_does_not_recurse_or_change_encoding():
    fonts = SystemFontCollection(paths=[])
    for family in ("Unavailable", "Webdings"):
        with pytest.raises(UnsupportedOperation, match="Native symbol fallback 'Webdings'"):
            fonts.resolve(request(family, charset=2, pitch_and_family=17))


def test_glyph_indices_cannot_use_substituted_family(installed):
    fonts = SystemFontCollection(paths=[installed("Liberation Sans")])
    req = request()
    with pytest.raises(UnsupportedOperation, match="Glyph-index"):
        fonts.layout_font(req, fonts.resolve(req), (1, 1))


def test_bad_font_inventory_entry_is_ignored(installed, tmp_path):
    broken = tmp_path / "broken.ttf"
    broken.write_bytes(b"not a font")
    fonts = SystemFontCollection(paths=[broken, installed("Arial")])
    assert fonts.resolve(request()).family == "Arial"


def test_collection_face_indices_are_preserved(installed, tmp_path):
    paths = [installed("First"), installed("Second")]
    collection = TTCollection()
    collection.fonts = [TTFont(path) for path in paths]
    path = tmp_path / "faces.ttc"
    try:
        collection.save(path)
    finally:
        collection.close()
    fonts = SystemFontCollection(paths=[path])
    assert fonts.resolve(request("Second")).index == 1


def test_variable_face_is_not_selected(installed):
    from fontTools.ttLib import newTable

    path = installed("Arial")
    with TTFont(path) as font:
        font["fvar"] = newTable("fvar")
        font.save(path)
    fonts = SystemFontCollection(paths=[path, installed("Liberation Sans")])
    assert fonts.resolve(request()).family == "Liberation Sans"


def test_style_substitution_rejects_glyph_indices(installed):
    fonts = SystemFontCollection(paths=[installed("Arial")])
    req = request(weight=700)
    face = fonts.resolve(req)
    assert fonts.substitutions[0].reason == "style"
    with pytest.raises(UnsupportedOperation, match="Glyph-index"):
        fonts.layout_font(req, face, (1, 1))


def test_empty_inventory_is_explicit_failure():
    with pytest.raises(UnsupportedOperation, match="No usable installed font"):
        SystemFontCollection(paths=[]).resolve(request())


def test_render_exposes_substitutions_and_keeps_explicit_api_strict(installed):
    recorder = Recorder()
    recorder.text_out(4, 20, b"AB")
    fonts = SystemFontCollection(paths=[installed("Liberation Sans")])
    image = render(recorder.to_bytes(), (64, 32), fonts=fonts)
    assert image.info["wmf_font_substitutions"] == tuple(fonts.substitutions)
    assert any(color != (255, 255, 255) for color in image.get_flattened_data())
    with pytest.raises(UnsupportedOperation):
        render(recorder.to_bytes(), (64, 32))


def test_fontconfig_inventory_is_deduplicated(monkeypatch):
    from subprocess import CompletedProcess

    monkeypatch.setattr(
        "pillow_wmf.system_fonts.subprocess.run", lambda *a, **k: CompletedProcess(a, 0, "/b.ttf\n/a.ttf\n/b.ttf\n")
    )
    assert font_paths() == [Path("/a.ttf"), Path("/b.ttf")]
