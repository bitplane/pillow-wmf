"""Shared test inputs; development utilities remain ordinary scripts."""

import runpy
from dataclasses import replace
from pathlib import Path

import pytest

from pillow_wmf import Call, FontFace

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def playback_calls():
    """Expected calls after native WMF normalization, not codec rewriting."""

    def normalize(calls):
        return [
            Call.make("create_font", font=replace(call.kwargs["font"], charset=1))
            if call.name == "create_font" and call.kwargs["font"].charset == 254
            else call
            for call in calls
        ]

    return normalize


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
