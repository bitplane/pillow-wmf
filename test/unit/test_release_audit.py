"""Ad-hoc audits must not count blocked records or absent PNGs as matches."""

import json

from PIL import Image

from pillow_wmf import Recorder


def test_strict_comparison_and_review_selection(tmp_path, load_script):
    script = load_script("audit-release.py")
    root, output = tmp_path / "inputs", tmp_path / "report"
    (root / "128x128").mkdir(parents=True)
    output.mkdir()
    recorder = Recorder()
    (root / "case.wmf").write_bytes(recorder.to_bytes())
    script["initialize"](root, output, [], {"case.wmf": "old charset blocker"})
    assert script["compare"]("case.wmf")["status"] == "missing-reference"
    Image.new("RGB", (8, 9), "white").save(root / "128x128/case.png")
    exact = script["compare"]("case.wmf")
    assert exact["status"] == "exact"
    assert exact["has_text"] is False
    assert "review" not in exact
    Image.new("RGB", (8, 9), "black").save(root / "128x128/case.png")
    different = script["compare"]("case.wmf")
    assert different["status"] == "different"
    assert different["differing_pixels"] == 72
    assert different["size"] == (8, 9)
    assert (output / (different["review"] + "-ours.png")).is_file()
    script["write_page"](output, [different], {"case.wmf": "old charset blocker"}, 2)
    summary = json.loads((output / "summary.json").read_text())
    assert summary["completed"] == 1
    assert summary["total"] == 2
    assert summary["review_cases"] == 1


def test_invalid_record_remains_blocked(tmp_path, load_script):
    script = load_script("audit-release.py")
    (tmp_path / "128x128").mkdir()
    recorder = Recorder()
    recorder.set_background_mode(0)
    (tmp_path / "bad.wmf").write_bytes(recorder.to_bytes())
    Image.new("RGB", (8, 8), "white").save(tmp_path / "128x128/bad.png")
    script["initialize"](tmp_path, tmp_path, [], {})
    result = script["compare"]("bad.wmf")
    assert result["status"] == "blocked"
    assert "Background mode 0" in result["error"]
    assert "differing_pixels" not in result
