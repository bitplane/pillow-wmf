"""The probe dispatcher keeps each workflow probe's command and artifact."""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/update-goldens.yml"

# Transcribed from the per-probe workflow steps this dispatcher replaced:
# command after ``python``, artifact directory, stdout tee, upload on failure.
EXPECTED = {
    "record-rejection": (
        "scripts/probe-windows-record-rejection.py --output record-rejection",
        "record-rejection",
        True,
        True,
    ),
    "corpus-rejection": (
        "scripts/probe-windows-record-rejection.py --output record-rejection --corpus",
        "record-rejection",
        True,
        True,
    ),
    "corpus-headers": (
        "scripts/probe-windows-record-rejection.py --output record-rejection --headers",
        "record-rejection",
        True,
        True,
    ),
    "corpus-palettes": (
        "scripts/probe-windows-record-rejection.py --output record-rejection --palettes",
        "record-rejection",
        True,
        True,
    ),
    "colorrefs": ("scripts/probe-windows-colorrefs.py --output colorref-probe", "colorref-probe", True, True),
    "mapping": ("scripts/probe-windows-mapping.py", None, False, None),
    "precision": ("scripts/probe-windows-precision.py", None, False, None),
    "text": ("scripts/probe-windows-text.py --output text-probe", "text-probe", False, False),
    "symbol": ("scripts/probe-windows-symbol.py --output symbol-probe", "symbol-probe", True, True),
    "mt-extra": ("scripts/probe-windows-mtextra.py --output mtextra-probe", "mtextra-probe", True, True),
    "dbcs": ("scripts/probe-windows-dbcs.py --output dbcs-probe", "dbcs-probe", True, True),
    "dbcs-extended": ("scripts/probe-windows-dbcs.py --output dbcs-probe --extended", "dbcs-probe", True, True),
    "dbcs-spacing": (
        "scripts/probe-windows-dbcs.py --output dbcs-probe --extended --spacing",
        "dbcs-probe",
        True,
        True,
    ),
    "codepages": ("scripts/probe-windows-codepages.py --output codepages-probe", "codepages-probe", True, True),
    "text-environments": (
        "scripts/probe-windows-environments.py --output environments-probe",
        "environments-probe",
        True,
        True,
    ),
    "utf8-mac": ("scripts/probe-windows-utf8-mac.py --output utf8-mac-probe", "utf8-mac-probe", True, True),
    "utf8-font": (
        "scripts/probe-windows-utf8-mac.py --output utf8-mac-probe --font-only",
        "utf8-mac-probe",
        True,
        True,
    ),
    "real-text": ("scripts/probe-windows-real-text.py --output real-text-probe", "real-text-probe", True, True),
    "text-layout": (
        "scripts/probe-windows-real-text.py --output real-text-probe --layout",
        "real-text-probe",
        True,
        True,
    ),
    "text-styles": (
        "scripts/probe-windows-real-text.py --output real-text-probe --styles",
        "real-text-probe",
        True,
        True,
    ),
    "text-quality": (
        "scripts/probe-windows-real-text.py --output real-text-probe --quality",
        "real-text-probe",
        True,
        True,
    ),
    "text-decorations": (
        "scripts/probe-windows-text-decorations.py --output text-decorations",
        "text-decorations",
        True,
        True,
    ),
    "wingdings": ("scripts/probe-windows-wingdings.py --output wingdings-probe", "wingdings-probe", True, True),
    "wingdings-visual": (
        "scripts/probe-windows-wingdings.py --output wingdings-probe --visual",
        "wingdings-probe",
        True,
        True,
    ),
    "wingdings-metrics": (
        "scripts/probe-windows-wingdings.py --output wingdings-probe --metadata-only",
        "wingdings-probe",
        True,
        True,
    ),
    "text-encoding": (
        "scripts/probe-windows-encoding.py --output text-encoding-probe",
        "text-encoding-probe",
        True,
        True,
    ),
    "text-encoding-extended": (
        "scripts/probe-windows-encoding.py --output text-encoding-probe --extended-only",
        "text-encoding-probe",
        True,
        True,
    ),
    "text-missing": (
        "scripts/probe-windows-encoding.py --output text-encoding-probe --missing-only",
        "text-encoding-probe",
        True,
        True,
    ),
    "text-options": ("scripts/probe-windows-text-options.py --output text-options", "text-options", True, True),
    "text-placement": (
        "scripts/probe-windows-text-options.py --output text-options --placement",
        "text-options",
        True,
        True,
    ),
    "text-rtl": ("scripts/probe-windows-text-options.py --output text-options --rtl", "text-options", True, True),
    "escapes": ("scripts/probe-windows-escapes.py --output escapes", "escapes", True, True),
    "text-fallback-sizing": (
        "scripts/probe-windows-encoding.py --sizing-only --output text-fallback-sizing",
        "text-fallback-sizing",
        True,
        True,
    ),
    "layout": ("scripts/probe-windows-layout.py", None, False, None),
    "patblt": ("scripts/probe-windows-patblt.py", None, False, None),
    "dib-brush": ("scripts/probe-windows-dib-brush.py", None, False, None),
    "dib-boundaries": ("scripts/probe-windows-dib-boundaries.py --output dib-boundaries", "dib-boundaries", True, True),
    "paths": ("scripts/probe-windows-paths.py", None, False, None),
    "strokes": ("scripts/probe-windows-strokes.py", None, False, None),
    "pen-support": ("scripts/probe-windows-pen-support.py", None, False, None),
    "ellipse-support": ("scripts/probe-windows-ellipse-support.py", None, False, None),
    "polygon-support": ("scripts/probe-windows-polygon-support.py", None, False, None),
    "arcs": ("scripts/probe-windows-arcs.py", None, False, None),
    "edge-cases": ("scripts/probe-windows-edge-cases.py", None, False, None),
    "regions": ("scripts/probe-windows-regions.py", None, False, None),
    "region-paint": ("scripts/probe-windows-region-paint.py", None, False, None),
    "insideframe": ("scripts/probe-windows-insideframe.py", None, False, None),
    "insideframe-inset": ("scripts/probe-windows-insideframe-inset.py", None, False, None),
    "roundrects": ("scripts/probe-windows-roundrects.py", None, False, None),
    "pies": ("scripts/probe-windows-pies.py", None, False, None),
    "chords": ("scripts/probe-windows-chords.py", None, False, None),
    "emf-frame": ("scripts/probe-windows-emf-frame.py", "emf-frame", True, True),
    "emf-transforms": ("scripts/probe-windows-emf-transforms.py", "emf-transforms", True, True),
    "advanced-paths": ("scripts/probe-windows-advanced-paths.py", "advanced-paths", True, True),
    "emf-record": ("scripts/probe-windows-emf-record.py", "emf-record", True, True),
    "pen-widen": ("scripts/probe-windows-pen-widen.py", "pen-widen", True, True),
    "gradient": ("scripts/probe-windows-gradient.py", "gradient", True, True),
    "rotated-paths": ("scripts/probe-windows-rotated-paths.py", "rotated-paths", True, True),
    "rotated-pens": ("scripts/probe-windows-rotated-pens.py", "rotated-pens", True, True),
    "rotated-strokes": ("scripts/probe-windows-rotated-strokes.py", "rotated-strokes", True, True),
    "emf-layout": ("scripts/probe-windows-emf-layout.py", "emf-layout", True, True),
    "color-adjustment": ("scripts/probe-windows-color-adjustment.py", "color-adjustment", True, True),
    "color-match": ("scripts/probe-windows-color-match.py", "color-match", True, True),
    "emf-recording": ("scripts/probe-windows-emf-recording.py", "emf-recording", True, True),
    "rotated-regions": ("scripts/probe-windows-rotated-regions.py", "rotated-regions", True, True),
    "rotated-transfers": ("scripts/probe-windows-rotated-transfers.py", "rotated-transfers", True, True),
    "rotated-blends": ("scripts/probe-windows-rotated-blends.py", "rotated-blends", True, True),
    "rotated-wide-pens": ("scripts/probe-windows-rotated-wide-pens.py", "rotated-wide-pens", True, True),
    "rotated-pen-styles": ("scripts/probe-windows-rotated-pen-styles.py", "rotated-pen-styles", True, True),
    "pen-style-ends": ("scripts/probe-windows-pen-style-ends.py", "pen-style-ends", True, True),
    "angle-arc-turns": ("scripts/probe-windows-angle-arc-turns.py", "angle-arc-turns", True, True),
    "cosmetic-widen": ("scripts/probe-windows-cosmetic-widen.py", "cosmetic-widen", True, True),
    "color-engine": ("scripts/probe-windows-color-engine.py", "color-engine", True, True),
    "module-ids": ("scripts/probe-windows-module-ids.py", "module-ids", True, True),
    "color-engine-phase": ("scripts/probe-windows-color-engine-phase.py", "color-engine-phase", True, True),
    "coordinate-limits": ("scripts/probe-windows-coordinate-limits.py", "coordinate-limits", True, True),
    "glyph-transforms": ("scripts/probe-windows-glyph-transforms.py", "glyph-transforms", True, True),
    "compatible-arcs": ("scripts/probe-windows-compatible-arcs.py", "compatible-arcs", True, True),
    "charset-mapping": ("scripts/probe-windows-charset-mapping.py", "charset-mapping", True, True),
    "text-samples": ("scripts/probe-windows-text-samples.py --output text-samples", "text-samples", True, True),
    "degenerate-shapes": ("scripts/probe-windows-degenerate-shapes.py", "degenerate-shapes", True, True),
    "current-position": ("scripts/probe-windows-current-position.py", "current-position", True, True),
}


@pytest.fixture
def dispatcher(load_script):
    return load_script("run-probe.py")


def test_every_probe_keeps_its_command_and_artifact(dispatcher):
    probes = dispatcher["PROBES"]
    assert set(probes) == set(EXPECTED)
    for name, (command, artifact, tee, upload_on_failure) in EXPECTED.items():
        probe = probes[name]
        assert " ".join(probe.command()) == command, name
        assert (probe.output, probe.tee) == (artifact, tee), name
        if artifact is not None:
            assert probe.upload_on_failure == upload_on_failure, name
        assert (ROOT / probe.command()[0]).is_file(), name


def test_workflow_choices_dispatch_through_one_step(dispatcher):
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load(WORKFLOW.read_text())
    triggers = workflow[True]  # YAML 1.1 reads the ``on`` key as True.
    choices = triggers["workflow_dispatch"]["inputs"]["probe"]["options"]
    assert choices[0] == "none" and set(choices[1:]) == set(dispatcher["PROBES"])
    assert len(choices) == len(set(choices))
    # Pushes still only react to reference inputs; probes need a dispatch.
    assert triggers["push"] == {
        "branches": ["master"],
        "paths": [
            "test/compatibility/wmf/**/*.wmf",
            "test/compatibility/wmf/**/*.png",
            "test/compatibility/emf/**/*.emf",
            "test/compatibility/emf/**/*.png",
        ],
    }
    update = workflow["jobs"]["update"]
    assert "inputs.probe != 'none'" in update["if"]
    assert "needs.preflight.outputs.missing == 'true'" in update["if"]
    runs = [step.get("run", "") for step in update["steps"]]
    assert sum("run-probe.py run" in run for run in runs) == 1
    assert not any("probe-windows-" in run for run in runs)


def test_run_tees_output_and_describe_sets_outputs(dispatcher, monkeypatch, tmp_path, capfd):
    script = tmp_path / "scripts" / "probe.py"
    script.parent.mkdir()
    script.write_text("import sys\nprint('seen', sys.argv[1:])\nsys.exit(3)\n")
    probe = dispatcher["Probe"]("probe.py", ("--output", "out", "-x"), "out")
    monkeypatch.chdir(tmp_path)
    assert dispatcher["run"](probe) == 3
    expected = f"seen ['--output', 'out', '-x']{os.linesep}"
    assert (tmp_path / "out/observations.txt").read_bytes() == expected.encode()
    assert capfd.readouterr().out == expected

    outputs = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    assert dispatcher["main"](["describe", "text"]) == 0
    assert outputs.read_bytes() == b"artifact=text-probe\nupload-on-failure=false\n"
    assert dispatcher["main"](["describe", "patblt"]) == 0
    assert outputs.read_bytes().endswith(b"artifact=\nupload-on-failure=true\n")
    assert dispatcher["main"](["run", "unknown"]) == 2


def test_printed_probes_run_with_the_current_interpreter(dispatcher, monkeypatch):
    calls = []

    class Completed:
        returncode = 0

    def run(command, check):
        calls.append(command)
        return Completed()

    monkeypatch.setattr(dispatcher["subprocess"], "run", run)
    assert dispatcher["run"](dispatcher["PROBES"]["patblt"]) == 0
    assert calls == [(sys.executable, "scripts/probe-windows-patblt.py")]
