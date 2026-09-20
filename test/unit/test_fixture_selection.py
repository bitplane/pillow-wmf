"""Local regressions and the release corpus partition the recorder fixtures."""

import pytest

from pillow_wmf import Recorder


def test_fixture_suites_partition_all_generated_inputs(load_script):
    factory = load_script("generate-wmf-fixtures.py")
    all_names = {name for name, _ in factory["all_cases"]()}
    local = {name for name, _ in factory["cases"]()}
    corpus = {name for name, _ in factory["cases"](corpus=True)}
    assert local and corpus
    assert local == factory["LOCAL_CASES"]
    assert local.isdisjoint(corpus)
    assert local | corpus == all_names


def test_misspelled_local_selection_is_rejected(monkeypatch, load_script):
    cases = load_script("generate-wmf-fixtures.py")["cases"]
    monkeypatch.setitem(cases.__globals__, "all_cases", lambda: iter((("known", Recorder()),)))
    monkeypatch.setitem(cases.__globals__, "LOCAL_CASES", {"misspelled"})
    with pytest.raises(ValueError, match="Unknown local regression names.*misspelled"):
        list(cases())


def test_duplicate_generator_names_are_rejected(monkeypatch, load_script):
    cases = load_script("generate-wmf-fixtures.py")["cases"]
    monkeypatch.setitem(cases.__globals__, "all_cases", lambda: iter((("known", Recorder()),) * 2))
    monkeypatch.setitem(cases.__globals__, "LOCAL_CASES", {"known"})
    with pytest.raises(ValueError, match="Duplicate generated fixture: known"):
        list(cases())
