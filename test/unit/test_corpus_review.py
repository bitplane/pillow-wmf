"""Review selection is bounded and never pads the page with exact matches."""


def test_charset_selection_prefers_unreviewed_mismatches_within_limit(tmp_path, load_script):
    select = load_script("review-corpus-text.py")["select_examples"]
    rows = [
        {"file": "exact.wmf", "status": "exact", "has_text": True, "differing_pixels": 0},
        {"file": "old.wmf", "status": "different", "has_text": True, "differing_pixels": 100},
        {"file": "new.wmf", "status": "different", "has_text": True, "differing_pixels": 20},
    ]
    survey = {
        "reviews": {"old.wmf": {"status": "different"}},
        "groups": [{"charset": 128, "files": [r["file"] for r in rows]}],
    }
    selected = select(rows, survey, tmp_path, 1)
    assert list(selected) == ["new.wmf"]


def test_weight_candidates_are_taken_from_the_report_not_fixed_corpus_names(tmp_path, load_script):
    select = load_script("review-corpus-text.py")["select_examples"]
    survey = {"reviews": {"example.wmf": {"status": "blocked", "error": "wingdings weight=500"}}, "groups": []}
    assert list(select([], survey, tmp_path, 1)) == ["example.wmf"]
