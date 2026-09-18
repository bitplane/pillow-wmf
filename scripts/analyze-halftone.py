"""Exact whole-metafile comparisons for the original HALFTONE reduction corpus.

Uses production playback and dispatch, including colour classification and scan
history. Optional positional paths select individual WMF/PNG pairs.
Run with .venv/bin/python scripts/analyze-halftone.py [case.wmf ...].
"""

import sys
from pathlib import Path

from reference_cases import selected_pairs
from reference_compare import run_comparisons

ROOT = Path(__file__).resolve().parents[1] / "test" / "compatibility" / "wmf"


def main(paths=None):
    if paths is None:
        paths = sorted(ROOT.glob("halftone-kernel-*.wmf")) + sorted(ROOT.glob("halftone-basis-*.wmf"))
        paths += [ROOT / f"{name}.wmf" for name in ("halftone-two-dimensional", "dib-stretch-ratios-blt-0-4")]
    return run_comparisons(selected_pairs(paths))


if __name__ == "__main__":
    raise SystemExit(main([Path(arg) for arg in sys.argv[1:]] or None))
