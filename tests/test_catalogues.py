"""Supplementary catalogue support (ADR-0009), against a real LCC sample."""
import os

import pytest

from iemod_fetch.catalogues import CatalogueSet, SupplementaryCatalogue
from iemod_fetch.errors import ConfigError

DATA = os.path.join(os.path.dirname(__file__), "data")
LCC = os.path.join(DATA, "lcc-sample.json")


@pytest.fixture(scope="module")
def lcc():
    return SupplementaryCatalogue.load(LCC)


# ------------------------------------------------------------------ loading
def test_a_real_lcc_export_loads(lcc):
    assert len(lcc) >= 12
    assert lcc.lookup("dlcmerger") is not None


def test_non_weidu_entries_are_skipped(lcc):
    assert lcc.lookup("non-weidu") is None
    assert lcc.skipped >= 1


def test_malformed_entries_do_not_abort_the_load():
    catalogue = SupplementaryCatalogue.from_entries(
        ["not a dict", {"no": "tp2"}, {"tp2": "", "name": "x"},
         {"tp2": "good", "name": "Good", "urls": ["https://github.com/o/good"]}])
    assert len(catalogue) == 1 and catalogue.skipped == 3


def test_a_missing_or_invalid_file_is_a_configuration_error(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        SupplementaryCatalogue.load(str(tmp_path / "nope.json"))
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(ConfigError, match="not valid JSON"):
        SupplementaryCatalogue.load(str(bad))


# ----------------------------------------------------------------- resolving
def test_it_supplies_a_repository_the_manifest_lacks(lcc):
    """The real gap: your manifest has no github for haerdalisromance."""
    entry = lcc.lookup("haerdalisromance")
    assert entry.github == "Spellhold-Studios/HaerDalis-Romance"


def test_the_best_matching_repository_wins_over_the_first_listed():
    entry = SupplementaryCatalogue.from_entries([{
        "tp2": "kivan", "name": "Kivan",
        "urls": ["https://github.com/SomeOrg/Collected-Mods",
                 "https://github.com/Gibberlings3/kivan"]}]).lookup("kivan")
    assert entry.github == "Gibberlings3/kivan"


def test_a_forum_only_entry_reports_no_repository(lcc):
    entry = lcc.lookup("Yvette")
    assert entry is not None and entry.github is None
    assert entry.http_urls                       # but it does have URLs to try


def test_lookup_accepts_either_the_folder_or_the_manifest_key(lcc):
    assert lcc.lookup("nope", "d0questpack") is not None
    assert lcc.lookup(None, "", "eefixpack") is not None


def test_an_entry_with_a_repository_is_preferred_over_a_bare_link():
    catalogue = SupplementaryCatalogue.from_entries([
        {"tp2": "dupe", "name": "forum only", "urls": ["https://forums.example/t/1"]},
        {"tp2": "dupe", "name": "on github", "urls": ["https://github.com/o/dupe"]}])
    assert catalogue.lookup("dupe").github == "o/dupe"


# ---------------------------------------------------------------- advisories
def test_quality_and_status_advisories_are_surfaced(lcc):
    notes = lcc.lookup("Vampire_World").advisories()
    assert any("may cause problems" in n for n in notes)
    assert any("beta" in n for n in notes)


def test_a_healthy_mod_raises_nothing(lcc):
    assert lcc.lookup("dlcmerger").advisories() == []


@pytest.mark.parametrize("payload,blocking", [
    ({"safe": 0, "status": ["stable"]}, True),
    ({"safe": 2, "status": ["obsolete"]}, True),
    ({"safe": 2, "status": ["missing"]}, True),
    ({"safe": 1, "status": ["beta"]}, False),
    ({"safe": 2, "status": ["stable"]}, False),
])
def test_blocking_classification(payload, blocking):
    entry = SupplementaryCatalogue.from_entries(
        [dict(tp2="x", name="X", urls=[], **payload)]).lookup("x")
    assert entry.blocking is blocking


# ----------------------------------------------------------------------- set
def test_the_first_catalogue_listing_a_mod_wins():
    first = SupplementaryCatalogue.from_entries(
        [{"tp2": "x", "name": "first", "urls": ["https://github.com/a/x"]}], name="first")
    second = SupplementaryCatalogue.from_entries(
        [{"tp2": "x", "name": "second", "urls": ["https://github.com/b/x"]}], name="second")
    assert CatalogueSet([first, second]).lookup("x").github == "a/x"


def test_an_empty_set_is_falsy():
    assert not CatalogueSet([])
    assert CatalogueSet.load([]) is not None


# ------------------------------------------------------- game compatibility
def test_a_mod_not_listed_for_the_game_is_flagged(lcc):
    entry = lcc.lookup("bg1ub")
    notes = entry.game_advisories("EET")
    assert notes and "EET-compatible" in notes[0]


def test_a_mod_listed_for_the_game_is_silent(lcc):
    assert lcc.lookup("bg1ub").game_advisories("BGEE") == []


def test_an_unknown_game_produces_no_warnings(lcc):
    """bg1ub lives in the BGEE log, whose game cannot be inferred - stay quiet."""
    assert lcc.lookup("bg1ub").game_advisories(None) == []


def test_a_catalogue_entry_with_no_games_produces_no_warnings():
    entry = SupplementaryCatalogue.from_entries(
        [{"tp2": "x", "name": "X", "urls": [], "games": []}]).lookup("x")
    assert entry.game_advisories("EET") == []


def test_requires_and_conflicts_are_captured(lcc):
    entry = SupplementaryCatalogue.from_entries([{
        "tp2": "x", "name": "X", "urls": [],
        "compatibilities": {"requires": ["EE version >= 2.5"], "conflicts": [42]}}]).lookup("x")
    assert entry.requires == ("EE version >= 2.5",) and entry.conflicts == (42,)


# --------------------------------------------------------- direct downloads
def test_a_direct_archive_url_is_recognised(lcc):
    """The real case: LCC points at the archive inside a collection repo."""
    entry = lcc.lookup("vampire_world")
    assert entry.direct_urls == (
        "https://github.com/Spellhold-Studios/Miscellaneous/raw/refs/heads/main/"
        "mods/Vampire_world_mod_v.0.56_EET.zip",)


def test_a_repository_page_is_not_a_direct_url(lcc):
    entry = lcc.lookup("dlcmerger")
    assert entry.github and entry.direct_urls == ()


@pytest.mark.parametrize("url,direct", [
    ("https://host/mods/x.zip", True),
    ("https://host/mods/x.7z", True),
    ("https://host/mods/x.iemod", True),
    ("https://host/mods/x.tar.gz", True),
    ("https://github.com/o/r/raw/refs/heads/main/x.zip", True),
    ("https://github.com/o/r/releases/download/v1/x.zip", True),
    ("https://github.com/o/r", False),
    ("https://forums.example/t/1234", False),
    ("https://host/setup.exe", False),          # never auto-selected
    ("https://host/x.zip?token=1", True),
])
def test_direct_url_classification(url, direct):
    entry = SupplementaryCatalogue.from_entries(
        [{"tp2": "x", "name": "X", "urls": [url]}]).lookup("x")
    assert bool(entry.direct_urls) is direct


# ---------------------------------------------- finding an entry by its repository
def test_an_entry_is_findable_by_the_repository_the_manifest_names():
    """
    `Reflections` matches neither the catalogue tp2 (`Reflections_of_Destiny`)
    nor any key - but the manifest names the repo, and the catalogue lists it.
    """
    catalogue = SupplementaryCatalogue.from_entries([{
        "tp2": "Reflections_of_Destiny", "name": "Reflections of Destiny",
        "urls": ["https://www.gibberlings3.net/forums/topic/38225-x/",
                 "https://github.com/subtledoctor/Reflections-of-Destiny/"]}])
    assert catalogue.lookup("Reflections") is None
    assert catalogue.lookup_repo("subtledoctor/Reflections-of-Destiny") is not None


def test_find_tries_folder_then_key_then_repo():
    catalogue = CatalogueSet([SupplementaryCatalogue.from_entries([{
        "tp2": "Reflections_of_Destiny", "name": "R",
        "urls": ["https://github.com/subtledoctor/Reflections-of-Destiny"]}])])
    hit = catalogue.find(folder="Reflections", key="Reflections",
                         repo="subtledoctor/Reflections-of-Destiny")
    assert hit.expected_tp2 == "Reflections_of_Destiny"


# -------------------------------------------------------------- expected_tp2
def test_the_catalogue_tp2_is_offered_as_the_expected_name():
    entry = SupplementaryCatalogue.from_entries(
        [{"tp2": "d0questpack", "name": "Quest Pack", "urls": []}]).lookup("d0questpack")
    assert entry.expected_tp2 == "d0questpack"


@pytest.mark.parametrize("tp2,expected", [
    ("d0questpack", "d0questpack"),
    ("Reflections_of_Destiny", "Reflections_of_Destiny"),
    ("c#endlessbg1", "c#endlessbg1"),
    ("NSC Portraits", None),          # real data: a display name, not a tp2
    ("some/path", None),
    ("", None),
])
def test_only_a_real_tp2_name_is_offered_as_the_expected_one(tp2, expected):
    from iemod_fetch.catalogues import CatalogueEntry
    assert CatalogueEntry(tp2=tp2, name="X").expected_tp2 == expected


# --------------------------------------------------------- extra health signals
def test_a_mod_embedded_in_another_is_flagged():
    entry = SupplementaryCatalogue.from_entries(
        [{"tp2": "apr", "name": "APR on Spec", "urls": [], "embedded_in": 1277}]).lookup("apr")
    assert any("already included in another mod" in n for n in entry.advisories())


def test_an_ee_mod_untouched_since_before_ee_2_0_is_flagged():
    entry = SupplementaryCatalogue.from_entries([{
        "tp2": "old", "name": "Old", "urls": [], "games": ["BG2EE"],
        "last_update": "2014-05-23"}]).lookup("old")
    assert entry.is_outdated
    assert any("before the Enhanced Edition patch" in n for n in entry.advisories())


def test_an_interface_mod_from_before_ee_2_6_is_flagged():
    entry = SupplementaryCatalogue.from_entries([{
        "tp2": "ui", "name": "UI", "urls": [], "games": ["BG2EE"],
        "categories": ["Interface"], "last_update": "2018-01-01"}]).lookup("ui")
    assert entry.is_outdated


def test_a_current_mod_is_not_flagged():
    entry = SupplementaryCatalogue.from_entries([{
        "tp2": "new", "name": "New", "urls": [], "games": ["EET"],
        "last_update": "2026-01-01"}]).lookup("new")
    assert not entry.is_outdated and entry.advisories() == []


def test_a_pre_ee_only_mod_is_not_judged_by_the_ee_rule():
    entry = SupplementaryCatalogue.from_entries([{
        "tp2": "classic", "name": "Classic", "urls": [], "games": ["BG2", "BGT"],
        "last_update": "2005-01-01"}]).lookup("classic")
    assert not entry.is_outdated


def test_links_of_a_mod_marked_missing_are_not_offered():
    """The catalogue keeps dead links on record; its own page hides them."""
    entry = SupplementaryCatalogue.from_entries([{
        "tp2": "gone", "name": "Gone", "status": ["missing"],
        "urls": ["https://dead.example/mod.zip"]}]).lookup("gone")
    assert entry.urls and entry.http_urls == () and entry.direct_urls == ()
