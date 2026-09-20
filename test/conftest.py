"""Shared test inputs; development utilities remain ordinary scripts."""

import runpy
from pathlib import Path

import pytest

from pillow_wmf import FontFace

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def face():
    """Fresh controlled layout face, with no cache shared between tests."""
    return FontFace.from_path(ROOT / "test/fonts/layout.ttf")


@pytest.fixture
def load_script(monkeypatch):
    scripts = ROOT / "scripts"
    monkeypatch.syspath_prepend(str(scripts))

    def load(name):
        return runpy.run_path(str(scripts / name))

    return load
