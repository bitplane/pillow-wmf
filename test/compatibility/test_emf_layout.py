import runpy
from pathlib import Path

import pytest

from pillow_wmf.emf import Metafile

ROOT = Path(__file__).resolve().parents[2]
EMF_ROOT = Path(__file__).parent / "emf"
compare_reference = runpy.run_path(str(ROOT / "scripts" / "reference_compare.py"))["compare_reference"]
discover_pairs = runpy.run_path(str(ROOT / "scripts" / "reference_cases.py"))["discover_pairs"]
PAIRS = discover_pairs(EMF_ROOT)


def test_generated_fixtures_are_reproducible_and_playable() -> None:
    cases = runpy.run_path(str(ROOT / "scripts" / "generate-emf-fixtures.py"))["cases"]
    generated = set()
    for name, metafile in cases():
        assert name not in generated, f"Duplicate generated fixture: {name}"
        generated.add(name)
        source = (EMF_ROOT / f"{name}.emf").read_bytes()
        assert source == metafile.to_bytes()
        assert Metafile.from_bytes(source).to_bytes() == source
    committed = {path.stem for path in EMF_ROOT.glob("*.emf")}
    assert committed == generated, f"Stale generated fixtures: {sorted(committed - generated)}"


@pytest.mark.parametrize("source_path,png_path", PAIRS, ids=[png.relative_to(EMF_ROOT).as_posix() for _, png in PAIRS])
def test_windows_pixels(source_path: Path, png_path: Path) -> None:
    assert png_path.is_file(), f"Missing Windows reference: {png_path.name}"
    result = compare_reference(source_path, png_path)
    assert result.differing_pixels == 0, (
        f"{source_path.name}: {result.differing_pixels} pixels differ from Windows; "
        f"first (x, y, actual, Windows): {result.first}"
    )
