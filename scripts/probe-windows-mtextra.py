"""Render with the real Equation Editor font, privately loaded from Microsoft.

The proprietary font is never committed, packaged, or uploaded as an artifact.
"""

import argparse
import hashlib
import runpy
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen

from mtextra_cases import SIZE, cases
from windows_wmf_render import private_fonts, render_wmf

FONT_URL = "https://download.microsoft.com/download/3/b/c/3bc07d0c-2748-4300-84dd-694857e582f1/MTEXTRA.TTF"
FONT_SHA256 = "6c469962f33b7222f07b8d1ae8025f177f4a5f5db3eb62fa1523f261a270991f"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    observe = runpy.run_path(str(Path(__file__).with_name("probe-windows-text.py")))["observe"]
    with urlopen(FONT_URL, timeout=60) as response:
        data = response.read(1024 * 1024)
    if hashlib.sha256(data).hexdigest() != FONT_SHA256:
        raise ValueError("Unexpected MT Extra reference font bytes")
    with TemporaryDirectory(prefix="mtextra-") as temporary:
        path = Path(temporary) / "MTEXTRA.TTF"
        path.write_bytes(data)
        with private_fonts([path]):
            for name, recorder in cases():
                print(f"\n[{name}]", flush=True)
                source = recorder.to_bytes()
                observe(source, family=None, size=SIZE, sample=b"hI", characters="\uf068\uf049")
                (args.output / f"{name}.wmf").write_bytes(source)
                render_wmf(source, *SIZE).save(args.output / f"{name}.png")


if __name__ == "__main__":
    main()
