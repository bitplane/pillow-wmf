"""Observe native Symbol selection and render a bounded byte/style sample."""

import argparse
import runpy
from pathlib import Path

from symbol_cases import SIZE, cases
from windows_wmf_render import render_wmf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    observe = runpy.run_path(str(Path(__file__).with_name("probe-windows-text.py")))["observe"]
    for name, recorder in cases():
        print(f"\n[{name}]", flush=True)
        source = recorder.to_bytes()
        # Discovery probe: report the selected face rather than assuming the
        # requested charset must select Symbol. No private fonts are installed.
        observe(
            source,
            family=None,
            size=SIZE,
            sample=b"AaWw\xe6\xe7\xe8",
            characters="\uf041\uf061\uf057\uf077\uf0e6\uf0e7\uf0e8",
        )
        (args.output / f"{name}.wmf").write_bytes(source)
        render_wmf(source, *SIZE).save(args.output / f"{name}.png")


if __name__ == "__main__":
    main()
