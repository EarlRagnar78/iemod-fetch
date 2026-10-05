"""The BWS-NG per-mod database: integrity data, and the rules' version baseline."""
import json

import pytest

from iemod_fetch.errors import ConfigError
from iemod_fetch.moddb import ModDatabase

RECORD = {
    "name": "Sylmar Battlefield", "version": "1.03a",
    "links": {"homepage": "https://example.invalid/"},
    "files": [{"filename": "1Sylm.zip", "size": 4136467,
               "sha256": "AB" * 32,
               "download": "https://github.com/o/r/releases/download/v1.03a/1Sylm.zip"}],
    "games": ["bg2ee", "eet"],
}


def build(tmp_path, name="1sylm", payload=None):
    (tmp_path / f"{name}.json").write_text(json.dumps(payload or RECORD))
    return ModDatabase.load(str(tmp_path))


def test_a_record_carries_version_and_integrity_data(tmp_path):
    record = build(tmp_path).get("1sylm")
    assert record.version == "1.03a"
    assert record.best_file.sha256 == "ab" * 32          # normalised to lower case
    assert record.best_file.download.endswith("1Sylm.zip")


def test_lookup_is_name_insensitive(tmp_path):
    db = build(tmp_path)
    assert db.get("1SYLM") is not None and db.get("nope", "1sylm") is not None


def test_a_file_with_a_digest_beats_one_without(tmp_path):
    payload = dict(RECORD, files=[{"download": "https://a/x.zip"},
                                  {"download": "https://b/y.zip", "sha256": "cd" * 32}])
    assert build(tmp_path, payload=payload).get("1sylm").best_file.sha256 == "cd" * 32


def test_a_record_with_no_files_has_no_best_file(tmp_path):
    assert build(tmp_path, payload=dict(RECORD, files=[])).get("1sylm").best_file is None


def test_malformed_records_are_skipped_not_fatal(tmp_path):
    (tmp_path / "good.json").write_text(json.dumps(RECORD))
    (tmp_path / "bad.json").write_text("{not json")
    (tmp_path / "list.json").write_text("[]")
    db = ModDatabase.load(str(tmp_path))
    assert len(db) == 1 and db.skipped == 2


def test_a_missing_directory_is_a_configuration_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        ModDatabase.load(str(tmp_path / "nope"))


def test_a_single_file_can_be_loaded(tmp_path):
    path = tmp_path / "one.json"
    path.write_text(json.dumps(RECORD))
    assert len(ModDatabase.load(str(path))) == 1
