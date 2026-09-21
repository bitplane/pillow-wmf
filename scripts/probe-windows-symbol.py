"""Observe native Symbol selection and render a bounded byte/style sample."""

import argparse
import runpy
from pathlib import Path

from symbol_cases import SIZE, cases, custom_selection_case
from windows_wmf_render import private_fonts, render_wmf


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
            sample=b"\xc5" if name.startswith("symbol-missing-") else bytes(range(256)),
            characters="\uf0c5"
            if name.startswith("symbol-missing-")
            else "".join(chr(0xF000 | byte) for byte in range(256)),
        )
        (args.output / f"{name}.wmf").write_bytes(source)
        render_wmf(source, *SIZE).save(args.output / f"{name}.png")

    # The ANSI row selects a host Latin face: this is a mapper probe, not an
    # exact controlled-font compatibility fixture. Always report the real face.
    with private_fonts([Path(__file__).resolve().parents[1] / "test/fonts/symbols.ttf"]):
        source = custom_selection_case().to_bytes()
        print("\n[custom-symbol-selection]", flush=True)
        observe(source, family=None, sample=b"AB")
        (args.output / "custom-symbol-selection.wmf").write_bytes(source)
        render_wmf(source, 128, 128).save(args.output / "custom-symbol-selection.png")


if __name__ == "__main__":
    main()
