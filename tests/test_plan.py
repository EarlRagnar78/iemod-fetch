"""The WeiDU <-> catalogue join, and the separation of suggestion from decision."""
import json
import os

from iemod_fetch.manifest import load_manifest, parse_manifest
from iemod_fetch.plan import build_plan, load_aliases, suggest
from iemod_fetch.weidu import parse_weidu_files, parse_weidu_log

DATA = os.path.join(os.path.dirname(__file__), "data")


def logs():
    return parse_weidu_files([os.path.join(DATA, "WeiDU.log"),
                              os.path.join(DATA, "WeiDUBGEE.log")])


def catalogue():
    return load_manifest(os.path.join(DATA, "mod_downloads.json"))


# ------------------------------------------------------------- the real join
def test_real_data_join_is_exactly_138_of_148():
    plan = build_plan(logs(), catalogue())
    assert len(plan.items) == 138
    assert len(plan.unresolved) == 10
    assert len(plan.unused_sources) == 10


def test_case_only_differences_still_join():
    """30 real pairs differ only in case, e.g. manifest 'EET' vs folder 'eet'."""
    plan = build_plan(logs(), catalogue())
    by_folder = {i.folder: i for i in plan.items}
    assert by_folder["eet"].source.key == "EET"
    assert by_folder["BGGO"].source.key == "bggo"


def test_install_folder_is_the_weidu_spelling_not_the_manifest_spelling():
    plan = build_plan(logs(), catalogue())
    by_folder = {i.folder: i for i in plan.items}
    assert "eet" in by_folder and "EET" not in by_folder


def test_every_unresolved_folder_except_one_gets_a_correct_suggestion():
    """
    Measured on the real corpus: 9 of the 10 unmatched WeiDU folders have a
    catalogue entry under a different name; the 10th genuinely has no source.
    """
    manifest = catalogue()
    expected = {
        "HiddenGameplayOptions": "a7-hiddengameplayoptions",
        "BloodAndFaith": "BLOODFAITH",
        "questpack": "d0questpack",
        "ISNF": "l#isnf",
        "JuniperAndTheStoneLeech": "l#juniperstone",
        "c#solaufein": "jasteys_solaufein",
        "Yvette": "l#coi-yvette",
        "VerrBG2": "l#verrszabg2",
        "Romance_Expanded": "OWRomanceExpanded",
    }
    plan = build_plan(logs(), manifest)
    unresolved = {i.folder for i in plan.unresolved}
    assert unresolved == set(expected) | {"HPS_PORTRAITS_PROJECT"}

    for folder, want in expected.items():
        top = suggest(folder, manifest)
        assert top and top[0].candidate_key == want, f"{folder} -> {top[:1]}"

    assert suggest("HPS_PORTRAITS_PROJECT", manifest) == []


# ------------------------------------------------------- suggestion vs decision
def _small():
    log = parse_weidu_log("~questpack\\questpack.tp2~ #0 #0 // Quest Pack\n")
    manifest = parse_manifest({"mods": [{"name": "Quest Pack", "tp2": "d0questpack",
                                         "github": "o/r"}]})
    return log, manifest


def test_a_suggestion_is_never_applied_automatically():
    log, manifest = _small()
    plan = build_plan(log, manifest)
    assert plan.items == []
    assert [i.folder for i in plan.unresolved] == ["questpack"]
    assert plan.suggestions[0].candidate_key == "d0questpack"


def test_accept_suggestions_opts_in_explicitly():
    log, manifest = _small()
    plan = build_plan(log, manifest, accept_suggestions=True)
    assert len(plan.items) == 1
    assert plan.items[0].match == "suggested"
    assert plan.items[0].folder == "questpack"          # install dir stays WeiDU's


def test_an_explicit_alias_resolves_without_fuzzy_matching(tmp_path):
    log, manifest = _small()
    alias_file = tmp_path / "aliases.json"
    alias_file.write_text(json.dumps({"questpack": "d0questpack"}))
    plan = build_plan(log, manifest, aliases=load_aliases(str(alias_file)))
    assert len(plan.items) == 1 and plan.items[0].match == "alias"


def test_an_alias_pointing_nowhere_is_reported():
    log, manifest = _small()
    plan = build_plan(log, manifest, aliases={"questpack": "does-not-exist"})
    assert plan.unresolved and any("names no manifest entry" in w for w in plan.warnings)


def test_manifest_only_entries_are_excluded_unless_requested():
    log, manifest = _small()
    manifest2 = parse_manifest({"mods": [
        {"name": "Quest Pack", "tp2": "questpack", "github": "o/r"},
        {"name": "Extra", "tp2": "EET_end", "github": "o/x"}]})
    assert len(build_plan(log, manifest2).items) == 1
    assert len(build_plan(log, manifest2, include_manifest_only=True).items) == 2


def test_alias_files_may_carry_underscore_comments(tmp_path):
    path = tmp_path / "aliases.json"
    path.write_text(json.dumps({"_comment": "reviewed 2026-09", "questpack": "d0questpack"}))
    assert load_aliases(str(path)) == {"questpack": "d0questpack"}


def test_the_shipped_alias_file_resolves_nine_of_the_ten_gaps():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    aliases = load_aliases(os.path.join(repo_root, "aliases.json"))
    plan = build_plan(logs(), catalogue(), aliases=aliases)
    assert len(plan.items) == 147
    assert [i.folder for i in plan.unresolved] == ["HPS_PORTRAITS_PROJECT"]
