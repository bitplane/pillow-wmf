import hashlib
import json
import runpy
from pathlib import Path

from PIL import Image

from pillow_wmf import Metafile, TraceContext, play

ROOT = Path(__file__).resolve().parents[2]
WMF_ROOT = Path(__file__).parent / "wmf"


def test_wmf_suite_is_present() -> None:
    assert WMF_ROOT.is_dir()
    assert sorted(path.stem for path in WMF_ROOT.glob("*.wmf")) == ["blank", "line", "overlap", "rectangle"]


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


def test_committed_references_are_current_when_present() -> None:
    renderer_hash = hashlib.sha256((ROOT / "scripts" / "windows_wmf_render.py").read_bytes()).hexdigest()
    for source_path in sorted(WMF_ROOT.glob("*.wmf")):
        png_path = source_path.with_suffix(".png")
        metadata_path = source_path.with_suffix(".json")
        if not png_path.exists() and not metadata_path.exists():
            continue  # Initial push: the Windows job creates both files.
        assert png_path.exists() and metadata_path.exists()
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert metadata["source_sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()
        assert metadata["png_sha256"] == hashlib.sha256(png_path.read_bytes()).hexdigest()
        assert metadata["renderer_sha256"] == renderer_hash
        assert metadata["oracle_version"] == 1
        assert metadata["settings"] == {
            "width": 128,
            "height": 128,
            "background": "white",
            "map_mode": "MM_ANISOTROPIC",
        }
        with Image.open(png_path) as image:
            assert image.format == "PNG"
            assert image.mode == "RGB"
            assert image.size == (128, 128)
