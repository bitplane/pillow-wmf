"""Local checks for publishing inputs without publishing anything."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_distribution_build_removes_only_stale_archives(tmp_path):
    venv = tmp_path / ".venv/bin"
    venv.mkdir(parents=True)
    (venv / "activate").write_text("")
    python = venv / "python"
    python.write_text('#!/bin/sh\n[ "$*" = "-m build ." ] || exit 1\ntouch dist/current.whl\n')
    python.chmod(0o755)
    dist = tmp_path / "dist"
    dist.mkdir()
    for name in ("old.whl", "old.tar.gz", "notes.txt"):
        (dist / name).write_text("old")
    subprocess.run(
        ["bash", str(ROOT / "scripts/dist.sh")],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{venv}{os.pathsep}{os.environ['PATH']}"},
        check=True,
    )
    assert {path.name for path in dist.iterdir()} == {"current.whl", "notes.txt"}
