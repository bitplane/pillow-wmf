from pathlib import Path


def test_wmf_suite_is_present() -> None:
    compatibility_root = Path(__file__).parent

    assert (compatibility_root / "wmf").is_dir()
