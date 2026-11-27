#!/usr/bin/env python3
"""Run one named native Windows probe for the reference-image workflow.

    python scripts/run-probe.py describe NAME   # set GitHub step outputs
    python scripts/run-probe.py run NAME        # run the probe

Probes that write an output directory are uploaded as an artifact of the same
name. ``tee`` probes also copy their standard output to observations.txt in
that directory. Upload normally happens even when the probe fails, so partial
observations survive; ``text`` uploads only after success.
"""

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Probe:
    script: str
    args: tuple[str, ...] = ()
    output: str | None = None
    tee: bool = True
    upload_on_failure: bool = True

    def command(self):
        return ("scripts/" + self.script, *self.args)


def _family(script, output, flags):
    return {name: Probe(script, ("--output", output, *extra), output) for name, extra in flags.items()}


def _printed(script):
    """A probe that reports only to the job log."""
    return Probe(script, tee=False)


# One entry per workflow_dispatch probe choice (other than "none").
PROBES = {
    **_family(
        "probe-windows-record-rejection.py",
        "record-rejection",
        {
            "record-rejection": (),
            "corpus-rejection": ("--corpus",),
            "corpus-headers": ("--headers",),
            "corpus-palettes": ("--palettes",),
        },
    ),
    **_family("probe-windows-colorrefs.py", "colorref-probe", {"colorrefs": ()}),
    "mapping": _printed("probe-windows-mapping.py"),
    "precision": _printed("probe-windows-precision.py"),
    "text": Probe("probe-windows-text.py", ("--output", "text-probe"), "text-probe", False, False),
    **_family("probe-windows-symbol.py", "symbol-probe", {"symbol": ()}),
    **_family("probe-windows-mtextra.py", "mtextra-probe", {"mt-extra": ()}),
    **_family(
        "probe-windows-dbcs.py",
        "dbcs-probe",
        {"dbcs": (), "dbcs-extended": ("--extended",), "dbcs-spacing": ("--extended", "--spacing")},
    ),
    **_family("probe-windows-codepages.py", "codepages-probe", {"codepages": ()}),
    **_family("probe-windows-environments.py", "environments-probe", {"text-environments": ()}),
    **_family("probe-windows-utf8-mac.py", "utf8-mac-probe", {"utf8-mac": (), "utf8-font": ("--font-only",)}),
    **_family(
        "probe-windows-real-text.py",
        "real-text-probe",
        {
            "real-text": (),
            "text-layout": ("--layout",),
            "text-styles": ("--styles",),
            "text-quality": ("--quality",),
        },
    ),
    **_family("probe-windows-text-decorations.py", "text-decorations", {"text-decorations": ()}),
    **_family(
        "probe-windows-wingdings.py",
        "wingdings-probe",
        {"wingdings": (), "wingdings-visual": ("--visual",), "wingdings-metrics": ("--metadata-only",)},
    ),
    **_family(
        "probe-windows-encoding.py",
        "text-encoding-probe",
        {
            "text-encoding": (),
            "text-encoding-extended": ("--extended-only",),
            "text-missing": ("--missing-only",),
        },
    ),
    **_family(
        "probe-windows-text-options.py",
        "text-options",
        {"text-options": (), "text-placement": ("--placement",), "text-rtl": ("--rtl",)},
    ),
    **_family("probe-windows-escapes.py", "escapes", {"escapes": ()}),
    "text-fallback-sizing": Probe(
        "probe-windows-encoding.py", ("--sizing-only", "--output", "text-fallback-sizing"), "text-fallback-sizing"
    ),
    "layout": _printed("probe-windows-layout.py"),
    "patblt": _printed("probe-windows-patblt.py"),
    "dib-brush": _printed("probe-windows-dib-brush.py"),
    **_family("probe-windows-dib-boundaries.py", "dib-boundaries", {"dib-boundaries": ()}),
    "paths": _printed("probe-windows-paths.py"),
    "strokes": _printed("probe-windows-strokes.py"),
    "pen-support": _printed("probe-windows-pen-support.py"),
    "ellipse-support": _printed("probe-windows-ellipse-support.py"),
    "polygon-support": _printed("probe-windows-polygon-support.py"),
    "arcs": _printed("probe-windows-arcs.py"),
    "edge-cases": _printed("probe-windows-edge-cases.py"),
    "regions": _printed("probe-windows-regions.py"),
    "region-paint": _printed("probe-windows-region-paint.py"),
    "insideframe": _printed("probe-windows-insideframe.py"),
    "insideframe-inset": _printed("probe-windows-insideframe-inset.py"),
    "roundrects": _printed("probe-windows-roundrects.py"),
    "pies": _printed("probe-windows-pies.py"),
    "chords": _printed("probe-windows-chords.py"),
    "emf-frame": Probe("probe-windows-emf-frame.py", output="emf-frame"),
    "emf-transforms": Probe("probe-windows-emf-transforms.py", output="emf-transforms"),
    "advanced-paths": Probe("probe-windows-advanced-paths.py", output="advanced-paths"),
    "emf-record": Probe("probe-windows-emf-record.py", output="emf-record"),
    "pen-widen": Probe("probe-windows-pen-widen.py", output="pen-widen"),
    "gradient": Probe("probe-windows-gradient.py", output="gradient"),
    "rotated-paths": Probe("probe-windows-rotated-paths.py", output="rotated-paths"),
    "rotated-pens": Probe("probe-windows-rotated-pens.py", output="rotated-pens"),
    "rotated-strokes": Probe("probe-windows-rotated-strokes.py", output="rotated-strokes"),
    "emf-layout": Probe("probe-windows-emf-layout.py", output="emf-layout"),
    "color-adjustment": Probe("probe-windows-color-adjustment.py", output="color-adjustment"),
    "color-match": Probe("probe-windows-color-match.py", output="color-match"),
    "emf-recording": Probe("probe-windows-emf-recording.py", output="emf-recording"),
    "rotated-regions": Probe("probe-windows-rotated-regions.py", output="rotated-regions"),
    "rotated-transfers": Probe("probe-windows-rotated-transfers.py", output="rotated-transfers"),
    "rotated-blends": Probe("probe-windows-rotated-blends.py", output="rotated-blends"),
    "rotated-wide-pens": Probe("probe-windows-rotated-wide-pens.py", output="rotated-wide-pens"),
    "rotated-pen-styles": Probe("probe-windows-rotated-pen-styles.py", output="rotated-pen-styles"),
    "pen-style-ends": Probe("probe-windows-pen-style-ends.py", output="pen-style-ends"),
    "angle-arc-turns": Probe("probe-windows-angle-arc-turns.py", output="angle-arc-turns"),
    "cosmetic-widen": Probe("probe-windows-cosmetic-widen.py", output="cosmetic-widen"),
    "color-engine": Probe("probe-windows-color-engine.py", output="color-engine"),
    "module-ids": Probe("probe-windows-module-ids.py", output="module-ids"),
    "color-engine-phase": Probe("probe-windows-color-engine-phase.py", output="color-engine-phase"),
    "coordinate-limits": Probe("probe-windows-coordinate-limits.py", output="coordinate-limits"),
    "glyph-transforms": Probe("probe-windows-glyph-transforms.py", output="glyph-transforms"),
    "compatible-arcs": Probe("probe-windows-compatible-arcs.py", output="compatible-arcs"),
    "charset-mapping": Probe("probe-windows-charset-mapping.py", output="charset-mapping"),
    **_family("probe-windows-text-samples.py", "text-samples", {"text-samples": ()}),
    "degenerate-shapes": Probe("probe-windows-degenerate-shapes.py", output="degenerate-shapes"),
    "current-position": Probe("probe-windows-current-position.py", output="current-position"),
}


def describe(probe):
    return {
        "artifact": probe.output or "",
        "upload-on-failure": "true" if probe.upload_on_failure else "false",
    }


def run(probe):
    command = (sys.executable, *probe.command())
    if not probe.tee:
        return subprocess.run(command, check=False).returncode
    Path(probe.output).mkdir(parents=True, exist_ok=True)
    with (
        open(Path(probe.output) / "observations.txt", "wb") as observations,
        subprocess.Popen(command, stdout=subprocess.PIPE) as process,
    ):
        for line in process.stdout:
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
            observations.write(line)
    return process.returncode


def main(argv):
    if len(argv) != 2 or argv[0] not in ("describe", "run") or argv[1] not in PROBES:
        print(f"usage: run-probe.py describe|run {{{','.join(PROBES)}}}", file=sys.stderr)
        return 2
    action, name = argv
    probe = PROBES[name]
    if action == "describe":
        lines = "".join(f"{key}={value}\n" for key, value in describe(probe).items())
        print(lines, end="")
        if path := os.environ.get("GITHUB_OUTPUT"):
            # Write LF endings directly; redirected text stdout is CRLF on Windows.
            with open(path, "a", encoding="utf-8", newline="\n") as outputs:
                outputs.write(lines)
        return 0
    return run(probe)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
