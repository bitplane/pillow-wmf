"""Update compatibility reference images on a Windows runner.

The fixture format and renderer are deliberately introduced with the first
WMF vertical slice. Until then this command verifies that there are no
unhandled source fixtures, allowing the workflow and permissions to be tested
without choosing those interfaces prematurely.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPATIBILITY_ROOT = ROOT / "test" / "compatibility"


def main() -> int:
    source_metafiles = sorted(COMPATIBILITY_ROOT.glob("**/*.wmf"))

    if source_metafiles:
        print(
            "Metafile fixtures exist, but the native reference renderer has "
            "not been introduced yet:\n  " + "\n  ".join(map(str, source_metafiles)),
            file=sys.stderr,
        )
        return 1

    print("No metafile fixtures require reference images")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
