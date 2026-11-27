"""Play the text sample sheets natively for visual QA of glyph rendering.

Writes each sheet's EMF and its PlayEnhMetaFile rendering with the runner's
installed fonts (``NAME.emf``, ``NAME.png``) to the output directory, then
prints the module versions and each sheet's canvas size. Compare locally with
``text-samples-side-by-side.py``.
"""

import argparse
import platform
from pathlib import Path

from text_samples import SHEETS, sheet_bytes
from windows_wmf_render import module_versions, render_emf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output
    output.mkdir(parents=True, exist_ok=True)
    print(f"Windows text samples: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    for name in SHEETS:
        data, (width, height) = sheet_bytes(name)
        (output / f"{name}.emf").write_bytes(data)
        render_emf(data, width, height).save(output / f"{name}.png")
        print(f"sheet {name} size={width}x{height}")


if __name__ == "__main__":
    main()
