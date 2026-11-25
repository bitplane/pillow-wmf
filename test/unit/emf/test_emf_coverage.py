"""docs/emf.md must list every record with codec and reference columns that match the code."""

import re
from pathlib import Path

from pillow_wmf.emf import RECORD_CLASSES, Metafile, RecordType
from pillow_wmf.emf.records import record_type

ROOT = Path(__file__).resolve().parents[3]
ROW = re.compile(r"^\| `(\w+)` \| (typed|opaque) \| (full|partial|no) \| (yes|no) \| (.*) \|$")


def rows():
    return {
        match[1]: match.groups()[1:]
        for line in (ROOT / "docs/emf.md").read_text().splitlines()
        if (match := ROW.match(line))
    }


def fixture_records():
    used = {RecordType.HEADER}
    for path in (ROOT / "test/compatibility/emf").glob("*.emf"):
        used |= {record_type(record) for record in Metafile.from_bytes(path.read_bytes()).records}
    return used


def test_every_record_is_listed_once():
    assert set(rows()) == {kind.name for kind in RecordType}


def test_codec_and_reference_columns_match():
    used = fixture_records()
    for name, (codec, playback, referenced, note) in rows().items():
        kind = RecordType[name]
        assert (codec == "typed") == (kind in RECORD_CLASSES or kind == RecordType.HEADER), name
        assert (referenced == "yes") == (kind in used), name
        if playback == "partial":
            assert note, f"{name}: partial playback needs a note"
