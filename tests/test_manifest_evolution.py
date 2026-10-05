"""
What happens when Infinity Mod Forge regenerates mod_downloads.json?

Nothing in the tool hardcodes a mod, a repository or a count: the manifest is
read, validated and joined at runtime. These tests pin down the behaviour for
each way a regenerated catalogue can differ, so "will it still work?" has an
answer per case rather than a promise.
"""
import json

import pytest

from iemod_fetch.errors import ManifestError
from iemod_fetch.manifest import parse_manifest
from iemod_fetch.plan import build_plan
from iemod_fetch.weidu import parse_weidu_log

LOG = ("~DlcMerger\\DlcMerger.tp2~ #0 #0 // Merge DLC\n"
       "~eefixpack\\SETUP-EEFIXPACK.TP2~ #0 #0 // Core Fixes\n")

BASE = {"mods": [
    {"name": "DLC Merger", "tp2": "DlcMerger", "github": "Argent77/A7-DlcMerger"},
    {"name": "EE Fixpack", "tp2": "eefixpack", "github": "gibberlings3/ee_fixpack"},
]}


def plan_for(catalogue, log=LOG):
    return build_plan(parse_weidu_log(log), parse_manifest(catalogue))


# ------------------------------------------------------- benign regeneration
def test_reordering_entries_changes_nothing():
    shuffled = {"mods": list(reversed(BASE["mods"]))}
    assert {i.folder for i in plan_for(shuffled).items} == {"DlcMerger", "eefixpack"}


def test_a_new_mod_you_have_not_installed_is_ignored():
    grown = {"mods": BASE["mods"] + [{"name": "New", "tp2": "brandnew",
                                      "github": "o/new"}]}
    plan = plan_for(grown)
    assert len(plan.items) == 2                       # driven by the WeiDU log
    assert plan.unused_sources == ["brandnew"]        # but reported, not hidden


def test_a_new_mod_you_have_installed_is_picked_up_automatically():
    grown = {"mods": BASE["mods"] + [{"name": "Karatur", "tp2": "karatur",
                                      "github": "The-Gate-Project/Kara-Tur"}]}
    plan = plan_for(grown, LOG + "~karatur\\karatur.tp2~ #0 #0 // Kara-Tur\n")
    assert len(plan.items) == 3


def test_a_changed_url_or_repo_is_simply_used():
    moved = json.loads(json.dumps(BASE))
    moved["mods"][0]["github"] = "SomeoneElse/A7-DlcMerger-fork"
    item = next(i for i in plan_for(moved).items if i.folder == "DlcMerger")
    assert item.source.github == "SomeoneElse/A7-DlcMerger-fork"


def test_new_unknown_fields_are_warned_about_not_fatal():
    extended = json.loads(json.dumps(BASE))
    extended["mods"][0]["imf_internal_id"] = 4711
    extended["mods"][0]["category"] = "quest"
    manifest = parse_manifest(extended)
    assert len(manifest.sources) == 2
    assert sum("unknown field" in w for w in manifest.warnings) == 2


def test_integrity_fields_you_added_survive_regeneration_only_if_imf_keeps_them():
    """
    Honest caveat: IMF regenerates the file, so a pinned sha256 you added by
    hand is lost unless you re-apply it. Keep the pinned copy as a separate
    committed file and pass it with -m.
    """
    regenerated = parse_manifest(BASE)
    assert regenerated.sources["dlcmerger"].sha256 is None


# ------------------------------------------------------- lossy regeneration
def test_a_mod_dropped_from_the_catalogue_is_reported_never_silently_skipped():
    shrunk = {"mods": [BASE["mods"][0]]}
    plan = plan_for(shrunk)
    assert [i.folder for i in plan.unresolved] == ["eefixpack"]


def test_a_renamed_tp2_key_breaks_the_join_and_says_so():
    renamed = json.loads(json.dumps(BASE))
    renamed["mods"][1]["tp2"] = "ee_fixpack_v2"
    plan = plan_for(renamed)
    assert [i.folder for i in plan.unresolved] == ["eefixpack"]
    # and the suggestion engine points at the renamed entry
    assert plan.suggestions[0].candidate_key == "ee_fixpack_v2"


def test_a_stale_alias_pointing_at_a_removed_entry_is_reported():
    shrunk = {"mods": [BASE["mods"][0]]}
    plan = build_plan(parse_weidu_log(LOG), parse_manifest(shrunk),
                      aliases={"eefixpack": "gone"})
    assert any("names no manifest entry" in w for w in plan.warnings)


def test_a_github_field_that_becomes_null_falls_back_to_the_url():
    nulled = json.loads(json.dumps(BASE))
    nulled["mods"][0]["github"] = None
    nulled["mods"][0]["url"] = "https://github.com/Argent77/A7-DlcMerger/releases"
    from iemod_fetch.resolvers import repo_from_url
    source = parse_manifest(nulled).sources["dlcmerger"]
    assert source.github is None
    assert repo_from_url(source.url) == "Argent77/A7-DlcMerger"


# ------------------------------------------------------ structural breakage
def test_a_renamed_top_level_key_is_a_configuration_error_not_a_silent_no_op():
    """The legacy script printed 'all mods present' for this."""
    with pytest.raises(ManifestError, match="no 'mods' key"):
        parse_manifest({"modules": BASE["mods"]})


def test_a_bare_array_manifest_is_accepted():
    """If IMF ever drops the wrapper object, the tool still reads it."""
    assert len(parse_manifest(BASE["mods"]).sources) == 2


def test_an_entry_missing_tp2_is_fatal_and_names_the_index():
    with pytest.raises(ManifestError, match=r"\[1\].*'tp2'"):
        parse_manifest({"mods": [BASE["mods"][0], {"name": "broken"}]})


def test_a_newly_unsafe_tp2_value_is_refused():
    hostile = {"mods": [{"name": "x", "tp2": "../../etc", "github": "o/r"}]}
    with pytest.raises(ManifestError, match="not a safe directory name"):
        parse_manifest(hostile)


def test_an_empty_regenerated_catalogue_fails_loudly():
    with pytest.raises(ManifestError, match="empty"):
        parse_manifest({"mods": []})
