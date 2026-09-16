"""The coverage wrapper must preserve test outcomes while writing reports."""

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("expected, exit_code", [(2, 0), (3, 1)])
def test_coverage_script_preserves_test_result(tmp_path, expected, exit_code):
    script = Path(__file__).resolve().parents[1] / "scripts" / "coverage.sh"
    activate = tmp_path / ".venv" / "bin" / "activate"
    activate.parent.mkdir(parents=True)
    activate.write_text(f"export PATH={shlex.quote(str(Path(sys.executable).parent))}:$PATH\n")
    source = tmp_path / "src" / "example_package"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("result = 1 + 1\n")
    (tmp_path / "test_example.py").write_text(
        "import runpy\n"
        "def test_result():\n"
        f"    assert runpy.run_path('src/example_package/__init__.py')['result'] == {expected}\n"
    )
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        ["bash", str(script), "example-package"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == exit_code, result.stdout + result.stderr
    report = (tmp_path / "htmlcov" / "coverage_report.txt").read_text()
    assert ("1 failed" if exit_code else "1 passed") in report
    assert "Missing" in (tmp_path / "htmlcov" / "missing_coverage.txt").read_text()
    assert (tmp_path / "htmlcov" / "index.html").is_file()
