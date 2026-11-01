"""
The mods a player can choose from, merged from every source given (M1).

A UI's selection screen starts here, before any WeiDU.log exists: one entry
per mod, whatever mix of the download manifest, the lcc-docs catalogue and the
BWS-NG / krion64 mod database knows about it, with the facts each source adds.
"""
import json
import os

import pytest

from iemod_fetch.available import SCHEMA_VERSION, available_mods, mods_document
from iemod_fetch.catalogues import CatalogueSet, SupplementaryCatalogue
from iemod_fetch.manifest import parse_manifest
from iemod_fetch.moddb import ModDatabase, ModFile, ModRecord

SCHEMA = os.path.join(os.path.dirname(__file__), os.pardir, "schemas",
                      "mods-v1.schema.json")

MANIFEST = parse_manifest({"mods": [
    {"name": "EE Fixpack", "tp2": "eefixpack", "github": "gibberlings3/ee_fixpack",
     "url": "https://github.com/gibberlings3/ee_fixpack"},
    {"name": "DLC Merger", "tp2": "DlcMerger", "github": "Argent77/A7-DlcMerger",
     "url": "https://github.com/Argent77/A7-DlcMerger/releases"}]})

LCC = CatalogueSet([SupplementaryCatalogue.from_entries([
    {"tp2": "eefixpack", "name": "EE Fixpack", "games": ["BGEE", "BG2EE", "EET"],
     "categories": ["Correctifs"], "safe": 2, "status": [], "last_update": "2025-06-01",
     "urls": ["https://github.com/Gibberlings3/EE_Fixpack"]},
    {"tp2": "oldmod", "name": "Old Mod", "games": ["BG2EE"], "safe": 0,
     "status": ["obsolete"], "last_update": "2012-01-01",
     "urls": ["https://example.org/oldmod.zip"]},
], name="lcc")])

DB = ModDatabase(records={"eefixpack": ModRecord(
    key="eefixpack", name="EE Fixpack", version="1.2",
    files=[ModFile(download="https://x/eefixpack-1.2.zip", sha256="ab" * 32)],
    games=["eet"])}, origin="bws")


def by_key(mods):
    return {m.key: m for m in mods}


def test_every_source_contributes_one_entry_per_mod():
    mods = by_key(available_mods(MANIFEST, LCC, DB))
    assert sorted(mods) == ["dlcmerger", "eefixpack", "oldmod"]
    fix = mods["eefixpack"]
    assert fix.in_manifest
    assert fix.games == ("BG2EE", "BGEE", "EET")
    assert (fix.safe, fix.last_update, fix.version) == (2, "2025-06-01", "1.2")
    assert {s["origin"] for s in fix.sources} == {"manifest", "lcc", "bws"}
    assert any(s.get("sha256") == "ab" * 32 for s in fix.sources)


def test_a_mod_only_a_catalogue_knows_is_offered_with_its_advisories():
    old = by_key(available_mods(MANIFEST, LCC, DB))["oldmod"]
    assert not old.in_manifest
    assert old.blocking
    assert any("obsolete" in note for note in old.advisories)


def test_nothing_but_a_manifest_is_enough():
    mods = available_mods(MANIFEST)
    assert [m.key for m in mods] == ["dlcmerger", "eefixpack"]   # sorted by name
    assert mods[0].name == "DLC Merger"


def test_the_document_is_versioned_and_valid_json():
    doc = json.loads(mods_document(available_mods(MANIFEST, LCC, DB)))
    assert doc["schema_version"] == SCHEMA_VERSION
    assert len(doc["mods"]) == 3


def test_the_json_schema_accepts_the_document():
    jsonschema = pytest.importorskip("jsonschema")
    with open(SCHEMA, encoding="utf-8") as fh:
        schema = json.load(fh)
    jsonschema.validate(json.loads(mods_document(available_mods(MANIFEST, LCC, DB))),
                        schema)


# --- lcc-docs' date as a second signal (ADR-0044, GUI-AUDIT item 50) ----------

from iemod_fetch.available import AvailableMod, mark_fetched, newer_by_day  # noqa: E402


@pytest.mark.parametrize("date, since, expected", [
    ("2025-08-25", "2025-08-24", True),
    ("2025-08-25", "2025-08-25", False),                 # the same day: not newer
    ("2025-08-25", "2025-08-25T23:59:59Z", False),       # cut to the day, no zone guessed
    ("2025-08-26", "2025-08-25T23:59:59Z", True),
    ("2025-08-24", "2025-08-25", False),
    (None, "2025-08-25", False), ("2025-08-25", None, False),    # unknown: silence
    ("soon", "2025-08-25", False), ("2025-08-25", "", False),
])
def test_dates_are_compared_by_day_and_doubt_says_nothing(date, since, expected):
    assert newer_by_day(date, since) is expected


def test_a_date_is_never_a_version_or_an_update():
    mod = AvailableMod(key="bg1ub", tp2="bg1ub", name="BG1UB", last_update="2025-08-25")
    mark_fetched([mod], {"bg1ub": "2025-01-02T10:00:00Z"})
    assert mod.fetched == "2025-01-02" and mod.maybe_updated
    assert mod.update_available is None and mod.latest is None and mod.version is None
    assert "maybe_updated" not in mod.as_dict()          # not in the CLI's mods-v1


def test_a_copy_with_no_fetch_day_is_not_marked():
    mod = AvailableMod(key="x", tp2="x", name="X", last_update="2025-08-25")
    mark_fetched([mod], {"x": "not a time", "other": "2020-01-01T00:00:00Z"})
    assert mod.fetched is None and not mod.maybe_updated


def test_the_page_is_a_page_not_an_archive_lcc_docs_links():
    from iemod_fetch.available import available_mods
    from iemod_fetch.catalogues import CatalogueSet
    import json as _json
    import tempfile
    entry = {"id": 1, "name": "M", "tp2": "m", "games": ["bgee"], "status": [],
             "categories": [], "last_update": "2025-08-25",
             "urls": ["https://example.org/m-v2.zip", "http://example.org/m/"]}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        _json.dump([entry], fh)
    (mod,) = available_mods(None, CatalogueSet.load([fh.name]))
    assert mod.page == "http://example.org/m/"          # the archive is skipped


def test_the_release_seen_and_krion64s_notes_reach_the_mod_not_the_cli():
    from iemod_fetch.available import available_mods
    from iemod_fetch.freshness import Release
    from iemod_fetch.moddb import ModDatabase, ModRecord
    db = ModDatabase(records={"bg1ub": ModRecord(
        key="bg1ub", name="BG1UB", version="v17",
        homepage="https://github.com/Pocket-Plane-Group/bg1ub",
        notes=[("Notes", "Restores cut content.")])}, origin="krion64")
    releases = {"pocket-plane-group/bg1ub": Release(
        "v17", "2025-01-01", None, archived=True, name="v17", notes="Fixes", pushed="2025-02")}
    (mod,) = available_mods(None, None, db, releases=releases)
    assert mod.release == {"repo": "pocket-plane-group/bg1ub", "tag": "v17", "name": "v17",
                           "date": "2025-01-01", "notes": "Fixes", "pushed": "2025-02",
                           "archived": True}
    assert mod.notes == [("Notes", "Restores cut content.")]
    assert "release" not in mod.as_dict() and "notes" not in mod.as_dict()   # mods-v1
