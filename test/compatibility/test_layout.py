import runpy
from pathlib import Path

import pytest
from PIL import Image

from pillow_wmf import Metafile, TraceContext, play
from pillow_wmf.raster import RasterContext

ROOT = Path(__file__).resolve().parents[2]
WMF_ROOT = Path(__file__).parent / "wmf"


def test_wmf_suite_is_present() -> None:
    assert WMF_ROOT.is_dir()
    assert list(WMF_ROOT.glob("*.wmf"))


def test_generated_fixtures_are_reproducible_and_playable() -> None:
    cases = runpy.run_path(str(ROOT / "scripts" / "generate-wmf-fixtures.py"))["cases"]
    for name, recorder in cases():
        source = (WMF_ROOT / f"{name}.wmf").read_bytes()
        assert source == recorder.to_bytes()
        parsed = Metafile.from_bytes(source)
        assert parsed.to_bytes() == source
        trace = TraceContext()
        assert play(parsed, trace, strict=True) == ()
        assert trace.calls == recorder.calls


def test_committed_references_are_valid() -> None:
    for source_path in sorted(WMF_ROOT.glob("*.wmf")):
        png_path = source_path.with_suffix(".png")
        assert png_path.is_file(), f"Missing Windows reference: {png_path.name}"
        with Image.open(png_path) as image:
            assert image.format == "PNG"
            assert image.mode == "RGB"
            assert image.size == (128, 128)


@pytest.mark.parametrize("source_path", sorted(WMF_ROOT.glob("*.wmf")), ids=lambda path: path.stem)
def test_windows_pixels(source_path: Path) -> None:
    png_path = source_path.with_suffix(".png")
    assert png_path.is_file(), f"Missing Windows reference: {png_path.name}"
    with Image.open(png_path) as reference:
        expected = reference.convert("RGB")
    context = RasterContext(expected.width, expected.height)
    assert play(Metafile.from_bytes(source_path.read_bytes()), context, strict=True) == ()
    actual = context.image
    differing = sum(
        left != right for left, right in zip(actual.get_flattened_data(), expected.get_flattened_data(), strict=True)
    )
    assert differing == 0, f"{source_path.name}: {differing} pixels differ from Windows"
