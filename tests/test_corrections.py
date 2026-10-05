"""The reviewed manifest corrections, and guards against undoing them."""
import json
import os

import pytest

from iemod_fetch.manifest import load_manifest
from iemod_fetch.plan import build_plan
from iemod_fetch.resolvers import repo_from_url
from iemod_fetch.weidu import parse_weidu_files

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "tests", "data")
ORIGINAL = os.path.join(DATA, "mod_downloads.json")
CORRECTED = os.path.join(DATA, "mod_downloads.corrected.json")


def corrected():
    return load_manifest(CORRECTED)


def test_the_original_manifest_had_three_cleartext_urls():
    warnings = [w for w in load_manifest(ORIGINAL).warnings if "http://" in w]
    assert len(warnings) == 3


def test_the_corrected_manifest_has_none():
    assert [w for w in corrected().warnings if "http://" in w] == []


@pytest.mark.parametrize("key,repo", [
    ("sirinescall", "Pocket-Plane-Group/Lure_Of_Sirines_Call"),
    ("fishingfortrouble", "Spellhold-Studios/FishingForTrouble"),
    ("fowlwish", "Glittergear/A-Fowl-Wish"),
])
def test_migrated_mods_now_point_at_a_resolvable_repository(key, repo):
    source = corrected().sources[key]
    assert source.github == repo
    assert repo_from_url(source.url) == repo      # url alone would also resolve


def test_fowlwish_no_longer_points_at_a_bare_user_profile():
    """The original entry was https://github.com/Glittergear with github: null."""
    assert repo_from_url(load_manifest(ORIGINAL).sources["fowlwish"].url) is None
    assert repo_from_url(corrected().sources["fowlwish"].url) is not None


def test_haerdalis_romance_is_not_substituted_with_the_friendship_mod():
    """
    SpellholdStudios/HaerdalisFriendship is a DIFFERENT mod with a different
    tp2. Substituting it would be exactly the supply-chain error the legacy
    script made. Only the URL scheme was changed.
    """
    source = corrected().sources["haerdalisromance"]
    assert source.github is None
    assert "Friendship" not in (source.url or "")
    assert source.url.startswith("https://www.shsforums.net/")
    assert "unverified" in (source.notes or "")


def test_corrections_do_not_change_any_tp2_key():
    """A changed key would silently break the WeiDU join."""
    def keys(path):
        with open(path, encoding="utf-8") as fh:
            return {m["tp2"] for m in json.load(fh)["mods"]}

    before, after = keys(ORIGINAL), keys(CORRECTED)
    assert before == after


def test_the_corrected_manifest_still_joins_against_the_weidu_logs():
    logs = parse_weidu_files([os.path.join(DATA, "WeiDU.log"),
                              os.path.join(DATA, "WeiDUBGEE.log")])
    plan = build_plan(logs, corrected())
    assert len(plan.items) == 138 and len(plan.unresolved) == 10


def test_applying_the_corrections_twice_is_a_no_op(tmp_path):
    from tools.apply_corrections import apply
    once = tmp_path / "a.json"
    twice = tmp_path / "b.json"
    apply(ORIGINAL, os.path.join(ROOT, "tools", "corrections.json"), str(once))
    apply(str(once), os.path.join(ROOT, "tools", "corrections.json"), str(twice))
    assert json.loads(once.read_text()) == json.loads(twice.read_text())


def test_merge_pins_carries_integrity_fields_across_a_regeneration(tmp_path):
    """
    Infinity Mod Forge rewrites mod_downloads.json from scratch. Without a
    merge step every regeneration silently discards the sha256 pins and drops
    you back to 'latest'.
    """
    from tools.apply_corrections import merge_pins

    pinned = tmp_path / "pinned.json"
    pinned.write_text(json.dumps({"mods": [
        {"name": "DLC Merger", "tp2": "DlcMerger", "github": "Argent77/A7-DlcMerger",
         "sha256": "ab" * 32, "release_tag": "v1.4", "asset": "DlcMerger.iemod"}]}))

    regenerated = {"mods": [{"name": "DLC Merger", "tp2": "DlcMerger",
                             "github": "Argent77/A7-DlcMerger"}]}
    carried, dropped = merge_pins(regenerated, str(pinned))

    assert carried == 1 and dropped == []
    entry = regenerated["mods"][0]
    assert entry["sha256"] == "ab" * 32
    assert entry["release_tag"] == "v1.4" and entry["asset"] == "DlcMerger.iemod"


def test_merge_pins_reports_mods_that_left_the_catalogue(tmp_path):
    from tools.apply_corrections import merge_pins
    pinned = tmp_path / "pinned.json"
    pinned.write_text(json.dumps({"mods": [
        {"name": "Gone", "tp2": "removedmod", "sha256": "cd" * 32}]}))
    _, dropped = merge_pins({"mods": [{"name": "X", "tp2": "x"}]}, str(pinned))
    assert dropped == ["removedmod"]


def test_merge_pins_never_overwrites_a_fresher_value(tmp_path):
    from tools.apply_corrections import merge_pins
    pinned = tmp_path / "pinned.json"
    pinned.write_text(json.dumps({"mods": [
        {"name": "X", "tp2": "x", "github": "Old/Repo", "sha256": "11" * 32}]}))
    regenerated = {"mods": [{"name": "X", "tp2": "x", "github": "New/Repo"}]}
    merge_pins(regenerated, str(pinned))
    assert regenerated["mods"][0]["github"] == "New/Repo"     # catalogue wins
    assert regenerated["mods"][0]["sha256"] == "11" * 32      # pin carried


# ------------------------------------------------------ catalogue enrichment
def test_enrichment_fills_missing_repositories_from_the_catalogue(tmp_path):
    from tools.enrich_from_lcc import enrich
    out = tmp_path / "enriched.json"
    added, _ = enrich(CORRECTED, [os.path.join(DATA, "lcc-sample.json")], str(out))
    keys = dict(added)
    assert keys["haerdalisromance"] == "Spellhold-Studios/HaerDalis-Romance"
    assert load_manifest(str(out)).sources["haerdalisromance"].github == keys["haerdalisromance"]


def test_enrichment_never_overwrites_an_existing_repository(tmp_path):
    from tools.enrich_from_lcc import enrich
    out = tmp_path / "enriched.json"
    before = load_manifest(CORRECTED).sources["dlcmerger"].github
    enrich(CORRECTED, [os.path.join(DATA, "lcc-sample.json")], str(out))
    assert load_manifest(str(out)).sources["dlcmerger"].github == before


def test_enrichment_records_provenance_in_notes(tmp_path):
    from tools.enrich_from_lcc import enrich
    out = tmp_path / "enriched.json"
    enrich(CORRECTED, [os.path.join(DATA, "lcc-sample.json")], str(out))
    notes = load_manifest(str(out)).sources["haerdalisromance"].notes or ""
    assert "github from lcc-sample.json" in notes


def test_enrichment_output_is_still_a_valid_manifest(tmp_path):
    from tools.enrich_from_lcc import enrich
    out = tmp_path / "enriched.json"
    enrich(CORRECTED, [os.path.join(DATA, "lcc-sample.json")], str(out))
    enriched = load_manifest(str(out))
    assert len(enriched.sources) == 148
    assert [w for w in enriched.warnings if "http://" in w] == []
