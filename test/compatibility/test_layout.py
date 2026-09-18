import runpy
from pathlib import Path

import pytest
from PIL import Image

from pillow_wmf import FontCollection, FontFace, Metafile, TraceContext, play

ROOT = Path(__file__).resolve().parents[2]
WMF_ROOT = Path(__file__).parent / "wmf"
compare_reference = runpy.run_path(str(ROOT / "scripts" / "reference_compare.py"))["compare_reference"]
discover_pairs = runpy.run_path(str(ROOT / "scripts" / "reference_cases.py"))["discover_pairs"]
PAIRS = discover_pairs(WMF_ROOT)


@pytest.fixture(scope="module")
def fonts():
    return FontCollection([FontFace.from_path(ROOT / "test/fonts/layout.ttf")])


def test_wmf_suite_is_present() -> None:
    assert WMF_ROOT.is_dir()
    assert list(WMF_ROOT.glob("*.wmf"))


def test_generated_fixtures_are_reproducible_and_playable() -> None:
    cases = runpy.run_path(str(ROOT / "scripts" / "generate-wmf-fixtures.py"))["cases"]
    generated = set()
    for name, recorder in cases():
        assert name not in generated, f"Duplicate generated fixture: {name}"
        generated.add(name)
        source = (WMF_ROOT / f"{name}.wmf").read_bytes()
        assert source == recorder.to_bytes()
        parsed = Metafile.from_bytes(source)
        assert parsed.to_bytes() == source
        trace = TraceContext()
        assert play(parsed, trace, strict=True) == ()
        assert trace.calls == recorder.calls
    committed = {path.stem for path in WMF_ROOT.glob("*.wmf")}
    assert committed == generated, f"Stale generated fixtures: {sorted(committed - generated)}"


def test_committed_references_are_valid() -> None:
    for source_path, png_path in PAIRS:
        assert png_path.is_file(), f"Missing Windows reference: {png_path.name}"
        with Image.open(png_path) as image:
            assert image.format == "PNG"
            assert image.mode == "RGB"
            assert image.width > 0 and image.height > 0


@pytest.mark.parametrize("source_path,png_path", PAIRS, ids=[png.relative_to(WMF_ROOT).as_posix() for _, png in PAIRS])
def test_windows_pixels(source_path: Path, png_path: Path, fonts) -> None:
    assert png_path.is_file(), f"Missing Windows reference: {png_path.name}"
    result = compare_reference(source_path, png_path, fonts=fonts)
    assert result.differing_pixels == 0, (
        f"{source_path.name}: {result.differing_pixels} pixels differ from Windows; "
        f"first (x, y, actual, Windows): {result.first}"
    )
