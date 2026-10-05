"""The lockfile path: promote what a run observed back into the manifest."""
import json

from iemod_fetch.manifest import parse_manifest
from iemod_fetch.pinning import build_pinned_manifest
from iemod_fetch.report import Record, Status


def manifest():
    return parse_manifest({"mods": [
        {"name": "DLC Merger", "tp2": "DlcMerger", "github": "Argent77/A7-DlcMerger",
         "url": "https://github.com/Argent77/A7-DlcMerger/releases"},
        {"name": "Southern Edge", "tp2": "SouthernEdge",
         "url": "https://downloads.weaselmods.net/download/southern-edge/"}]})


def test_a_completed_run_pins_tag_asset_and_digest():
    records = [Record("DlcMerger", Status.OK, "installed", source_key="DlcMerger",
                      url="https://github.com/o/r/releases/download/v1.4/DlcMerger.iemod",
                      sha256="ab" * 32, version="v1.4", origin="release-asset")]
    payload = build_pinned_manifest(manifest(), records)
    entry = payload["mods"][0]
    assert entry["release_tag"] == "v1.4"
    assert entry["asset"] == "DlcMerger.iemod"
    assert entry["sha256"] == "ab" * 32
    assert payload["pinned_entries"] == 1


def test_the_pinned_output_is_still_a_valid_manifest():
    """A lockfile that the tool cannot read back would be useless."""
    records = [Record("DlcMerger", Status.OK, "", source_key="DlcMerger",
                      url="https://github.com/o/r/releases/download/v1/DlcMerger.iemod",
                      sha256="cd" * 32, version="v1", origin="release-asset")]
    payload = build_pinned_manifest(manifest(), records)
    reparsed = parse_manifest(json.loads(json.dumps(payload)))
    assert reparsed.sources["dlcmerger"].sha256 == "cd" * 32
    assert reparsed.sources["dlcmerger"].release_tag == "v1"


def test_unpinned_entries_are_marked_not_silently_dropped():
    payload = build_pinned_manifest(manifest(), [])
    assert len(payload["mods"]) == 2
    assert payload["pinned_entries"] == 0 and payload["unpinned_entries"] == 2
    assert all("NOT PINNED" in m["notes"] for m in payload["mods"])


def test_a_source_snapshot_is_not_pinned_as_an_asset():
    records = [Record("DlcMerger", Status.OK, "", source_key="DlcMerger",
                      url="https://api.github.com/repos/o/r/zipball/v1",
                      sha256="ef" * 32, version="v1", origin="source-snapshot")]
    entry = build_pinned_manifest(manifest(), records)["mods"][0]
    assert "asset" not in entry            # zipball basename is not a stable filename
    assert entry["sha256"] == "ef" * 32


def test_a_dry_run_pins_the_tag_but_not_the_digest():
    records = [Record("DlcMerger", Status.PLANNED, "", source_key="DlcMerger",
                      url="https://github.com/o/r/releases/download/v2/DlcMerger.iemod",
                      version="v2", origin="release-asset")]
    entry = build_pinned_manifest(manifest(), records)["mods"][0]
    assert entry["release_tag"] == "v2" and entry["asset"] == "DlcMerger.iemod"
    assert "sha256" not in entry and "NOT PINNED" in entry["notes"]


def test_state_file_fills_in_mods_that_were_skipped_this_run():
    records = [Record("DlcMerger", Status.SKIPPED, "already installed",
                      source_key="DlcMerger")]
    state = {"dlcmerger": {"sha256": "12" * 32, "version": "v9"}}
    entry = build_pinned_manifest(manifest(), records, state=state)["mods"][0]
    assert entry["sha256"] == "12" * 32 and entry["release_tag"] == "v9"


def test_existing_manifest_pins_survive_a_run_that_pinned_nothing():
    base = parse_manifest({"mods": [{"name": "X", "tp2": "x", "github": "o/r",
                                     "sha256": "aa" * 32, "release_tag": "v1",
                                     "asset": "x.iemod"}]})
    entry = build_pinned_manifest(base, [])["mods"][0]
    assert entry["sha256"] == "aa" * 32 and entry["asset"] == "x.iemod"
