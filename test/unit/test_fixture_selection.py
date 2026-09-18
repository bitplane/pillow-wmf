"""Local regressions and the release corpus partition the recorder fixtures."""

import runpy
from pathlib import Path

import pytest

from pillow_wmf import Recorder

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "generate-wmf-fixtures.py"


def test_fixture_suites_partition_all_generated_inputs():
    factory = runpy.run_path(str(SCRIPT))
    all_names = {name for name, _ in factory["all_cases"]()}
    local = {name for name, _ in factory["cases"]()}
    corpus = {name for name, _ in factory["cases"](corpus=True)}
    assert local and corpus
    assert local == factory["LOCAL_CASES"]
    assert local.isdisjoint(corpus)
    assert local | corpus == all_names


def test_misspelled_local_selection_is_rejected(monkeypatch):
    cases = runpy.run_path(str(SCRIPT))["cases"]
    monkeypatch.setitem(cases.__globals__, "all_cases", lambda: iter((("known", Recorder()),)))
    monkeypatch.setitem(cases.__globals__, "LOCAL_CASES", {"misspelled"})
    with pytest.raises(ValueError, match="Unknown local regression names.*misspelled"):
        list(cases())


def test_duplicate_generator_names_are_rejected(monkeypatch):
    cases = runpy.run_path(str(SCRIPT))["cases"]
    monkeypatch.setitem(cases.__globals__, "all_cases", lambda: iter((("known", Recorder()),) * 2))
    monkeypatch.setitem(cases.__globals__, "LOCAL_CASES", {"known"})
    with pytest.raises(ValueError, match="Duplicate generated fixture: known"):
        list(cases())
