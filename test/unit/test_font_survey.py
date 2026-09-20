from pillow_wmf import Font, Recorder


def test_survey_tracks_selected_fonts_save_restore_and_deletion(load_script):
    survey_type = load_script("survey-corpus-fonts.py")["TextSurvey"]
    first = Font(face_name=b"First".ljust(32, b"\0"))
    second = Font(face_name=b"Second".ljust(32, b"\0"))
    r = Recorder()
    r.create_font(Font(face_name=b"Unused"))
    one = r.create_font(first)
    two = r.create_font(second)
    r.text_out(0, 0, b"default")
    r.select_object(one)
    r.save_dc()
    r.select_object(two)
    r.text_out(0, 0, b"second")
    r.restore_dc(-1)
    r.delete_object(one)
    r.text_out(0, 0, b"first")
    r.text_out(0, 0, b"")
    from pillow_wmf import Metafile, play

    survey = survey_type()
    assert not play(Metafile.from_bytes(r.to_bytes()), survey, strict=True)
    assert [font for font, _, _ in survey.runs] == [None, second, first]


def test_survey_reports_malformed_input_separately(load_script, tmp_path):
    scan = load_script("survey-corpus-fonts.py")["scan"]
    (tmp_path / "bad.wmf").write_bytes(b"bad")
    groups, failures, count, files = scan(tmp_path)
    assert count == 1
    assert not groups and not files
    assert failures[0]["file"] == "bad.wmf"


def test_review_page_is_filterable_and_escapes_corpus_names(load_script, tmp_path):
    write_page = load_script("survey-corpus-fonts.py")["write_page"]
    name = '<Unknown "family">'
    report = {
        "inputs": 1,
        "text_files": 1,
        "scan_failures": [],
        "groups": [
            {
                "family": name,
                "weight": 400,
                "italic": False,
                "charset": 2,
                "files": ["input.wmf"],
                "status": "blocked",
                "error": "Missing symbol font",
            }
        ],
        "reviews": {"input.wmf": {"status": "blocked", "error": "Missing symbol font"}},
    }
    write_page(report, tmp_path)
    page = (tmp_path / "index.html").read_text()
    assert name not in page
    assert "&lt;Unknown &quot;family&quot;&gt;" in page
    assert 'id="family"' in page and 'id="case-0"' in page
    assert "Missing symbol font" in page
    assert "<img" not in page
