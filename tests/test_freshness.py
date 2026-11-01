"""
Is there a newer version than the one installed? (M2d)

The cases are real: tags and versions as krion64's release cache, BWS-NG and
the mods' own tp2s spell them (2026-10). The rule - the newest version any
source names - and its measurement are in freshness.py and docs/TESTING.md.
"""
import io
import json
import os

import pytest

from iemod_fetch import api
from iemod_fetch.available import available_mods
from iemod_fetch.catalogues import CatalogueSet
from iemod_fetch.errors import ConfigError
from iemod_fetch.freshness import (RELEASE, Candidate, github_repo, latest,
                                   parse_release_cache, update_available)
from iemod_fetch.versions import compare_published

HERE = os.path.dirname(__file__)
RELEASES = os.path.join(HERE, "data", "krion", "version_cache.json")


# ----------------------------------------------------------- comparisons
@pytest.mark.parametrize("a,b", [
    ("v071", "0.71"),          # thepicturestandard: tag without the dot
    ("V19", "v1.9"),           # ajocmod
    ("v53", "v5.3"),           # finchnpc
    ("2.0.2", "v2.02"),        # karatur
    ("Version 6.1", "v6.1"),   # deratsogre's tp2
    ("v14.1", "14.1"),
    ("1.0", "1"),
])
def test_two_spellings_of_one_release_are_the_same(a, b):
    assert compare_published(a, b) == 0
    assert compare_published(b, a) == 0


def test_different_releases_stay_different():
    assert compare_published("1.10", "11.0") == -1       # different first number
    assert compare_published("v12", "1.3") == 1          # different digits
    assert compare_published("v14.1", "v14.0") == 1


def test_pre_a_version_is_the_work_towards_it():
    """RoT's tp2 says `pre-v6.0`: newer than v5.0, older than v6.0."""
    assert compare_published("pre-v6.0", "v5.0") == 1
    assert compare_published("v5.0", "pre-v6.0") == -1
    assert compare_published("pre-v6.0", "v6.0") == -1


# ------------------------------------------------------------- sources
def test_github_repo_from_any_github_url():
    assert github_repo("https://github.com/K4thos/EET/releases/tag/v14.1") == "k4thos/eet"
    assert github_repo("https://github.com/Gibberlings3/SCS.git") == "gibberlings3/scs"
    assert github_repo("https://www.shsforums.net/files/file/564") is None


def test_the_release_cache_keeps_only_repositories_with_a_release():
    with open(RELEASES, encoding="utf-8") as fh:
        cache = parse_release_cache(json.load(fh))
    assert cache["k4thos/eet"].tag == "v14.1"
    assert "gibberlings3/ee_fixpack" not in cache          # tag "": no release
    assert parse_release_cache(["not", "a", "dict"]) == {}


def test_latest_is_the_newest_any_source_names():
    """UB: the release is tagged v28, BWS-NG already downloads 29."""
    newest = latest([Candidate("v28", RELEASE, "2021-01-03"),
                     Candidate("29", "bws-ng"), Candidate("v28", "krion64")])
    assert (newest.version, newest.origin) == ("29", "bws-ng")


def test_on_a_tie_the_github_release_is_reported():
    newest = latest([Candidate("v14.1", RELEASE, "2026-09-10"), Candidate("14.1", "bws-ng")])
    assert newest.origin == RELEASE and newest.date == "2026-09-10"


def test_unrankable_versions_are_unknown_not_an_update():
    assert update_available("vEAOB.9", Candidate("v1_Beta260923", RELEASE)) is None
    assert update_available(None, Candidate("v1", RELEASE)) is None
    assert update_available("v1", None) is None
    assert update_available("v14.0", Candidate("v14.1", RELEASE)) is True
    assert update_available("v14.1", Candidate("14.1", "bws-ng")) is False


# -------------------------------------------------------- the mod list
def catalogue(tmp_path, urls):
    path = tmp_path / "lcc.json"
    path.write_text(json.dumps([{"id": 1, "name": "EET", "tp2": "eet", "urls": urls,
                                 "games": ["EET"], "categories": [], "status": []}]))
    return CatalogueSet.load([str(path)])


def test_a_mod_says_installed_latest_and_whether_it_is_an_update(tmp_path):
    with open(RELEASES, encoding="utf-8") as fh:
        releases = parse_release_cache(json.load(fh))
    (mod,) = available_mods(catalogues=catalogue(tmp_path, ["https://github.com/K4thos/EET"]),
                            releases=releases, installed={"eet": "v14.0"})
    entry = mod.as_dict()
    assert entry["installed"] == "v14.0"
    assert entry["latest"] == {"version": "v14.1", "origin": RELEASE,
                               "date": mod.latest.date, "url": mod.latest.url}
    assert entry["update_available"] is True


def test_without_versions_nothing_is_claimed(tmp_path):
    (mod,) = available_mods(catalogues=catalogue(tmp_path, ["https://example.org/eet"]))
    assert mod.as_dict()["latest"] is None and mod.as_dict()["update_available"] is None


def test_the_repository_named_like_the_mod_is_preferred(tmp_path):
    """CTB's sub-mods link Check the Bodies too; its release is not theirs."""
    releases = {"spellholdstudios/check_the_bodies": parse_release_cache(
                    {"x": {"tag": "v3.0"}})["x"],
                "k4thos/eet": parse_release_cache({"x": {"tag": "v14.1"}})["x"]}
    (mod,) = available_mods(
        catalogues=catalogue(tmp_path, ["https://github.com/SpellholdStudios/Check_the_Bodies",
                                        "https://github.com/K4thos/EET"]),
        releases=releases)
    assert mod.latest.version == "v14.1"


# --------------------------------------------------------- the notice
def test_the_run_prints_the_update_notice(tmp_path):
    log = tmp_path / "WeiDU.log"
    log.write_text("~EET/EET.TP2~ #0 #0 // EET core (resource importation): v14.0\n")
    lcc = tmp_path / "lcc.json"
    lcc.write_text(json.dumps([{"id": 1, "name": "EET", "tp2": "eet",
                                "urls": ["https://github.com/K4thos/EET"],
                                "games": ["EET"], "categories": [], "status": []}]))
    out = io.StringIO()
    settings = api.Settings(weidu_log=[f"{log}:EET"], catalogue=[str(lcc)],
                            releases=RELEASES)
    api._render_updates(settings, out)
    text = out.getvalue()
    assert "1 of 1 installed mods with a version have a newer one" in text
    assert "v14.0 -> v14.1 (github release" in text


def test_list_mods_reports_installed_and_latest(tmp_path):
    log = tmp_path / "WeiDU.log"
    log.write_text("~EET/EET.TP2~ #0 #0 // EET core (resource importation): v14.1\n")
    lcc = tmp_path / "lcc.json"
    lcc.write_text(json.dumps([{"id": 1, "name": "EET", "tp2": "eet",
                                "urls": ["https://github.com/K4thos/EET"],
                                "games": ["EET"], "categories": [], "status": []}]))
    (mod,) = api.list_mods(None, catalogues=[str(lcc)], releases=RELEASES,
                           weidu_logs=[f"{log}:EET"])
    assert (mod.installed, mod.update_available) == ("v14.1", False)


def test_an_unreadable_release_cache_is_a_configuration_error(tmp_path):
    bad = tmp_path / "version_cache.json"
    bad.write_text("{not json")
    with pytest.raises(ConfigError):
        api.list_mods(None, catalogues=[], releases=str(bad))


# --- what the scan saw of a repository, as text (GUI-AUDIT item 51) ----------

def test_release_notes_and_activity_are_read_as_text():
    from iemod_fetch.freshness import NOTES_MAX, parse_release_cache
    raw = {"Argent77/A7-DlcMerger": {
        "tag": "v2.1", "release_date": "2026-07-03", "release_name": "DLC Merger 2.1",
        "pushed": "2026-09-06", "archived": False,
        "body": "Changelog:\r\n- one\x1b[31m red\x07\n- two" + "x" * 3000}}
    release = parse_release_cache(raw)["argent77/a7-dlcmerger"]
    assert release.name == "DLC Merger 2.1" and release.pushed == "2026-09-06"
    assert release.notes.startswith("Changelog:\n- one[31m red\n- two")   # controls out
    assert len(release.notes) <= NOTES_MAX + 4 and release.notes.endswith(" ...")


def test_notes_that_are_not_text_are_none():
    from iemod_fetch.freshness import parse_release_cache, plain_text
    release = parse_release_cache({"a/b": {"tag": "v1", "body": {"x": 1}, "pushed": 5}})["a/b"]
    assert release.notes is None and release.pushed is None
    assert plain_text("  \x00 ") is None


def test_bidi_overrides_and_lone_carriage_returns_do_not_survive():
    """Review of #123: an RLO would turn the following lines around."""
    from iemod_fetch.freshness import plain_text
    assert plain_text("a\u202eb\u2066c\u200fd") == "abcd"
    assert plain_text("one\rtwo\r\nthree") == "one\ntwo\nthree"


def test_the_scan_day_tag_and_date_are_text_with_a_cap():
    from iemod_fetch.freshness import parse_release_cache
    raw = {"a/b": {"tag": "v1" + "x" * 500, "release_date": {"no": 1},
                   "checked": "2026-03-14T08:00:00Z"},
           "c/d": {"tag": 5}}
    releases = parse_release_cache(raw)
    assert set(releases) == {"a/b"}
    assert len(releases["a/b"].tag) <= 104 and releases["a/b"].date is None
    assert releases["a/b"].checked == "2026-03-14T08:00:00Z"
