"""
What a player chooses from (M3 phase 2, ADR-0035): each mod's components, from
its own tp2 once staged, else from krion64's records - which carry 1,471 of
the 1,529 components WeiDU lists for 105 real mods (docs/TESTING.md).
"""
import json
import os

import pytest

from iemod_fetch import api
from iemod_fetch.choices import KRION, TP2, folder_key, from_described, from_krion, merged
from iemod_fetch.errors import ConfigError

HERE = os.path.dirname(__file__)
LCC = os.path.join(HERE, "data", "lcc-sample.json")

BG1UB = {"t": "bg1ub", "co": [
    {"n": "Ice Island Level Two Restoration", "cn": 0, "wc": 0, "wp": "bg1ub\\setup-bg1ub.tp2"},
    {"n": "Portraits: classic", "cn": 1, "wc": 10, "wp": "bg1ub/setup-bg1ub.tp2", "g": 7,
     "scn": "Portraits"},
    {"n": "Portraits: new", "cn": 2, "wc": 11, "wp": "bg1ub/setup-bg1ub.tp2", "g": 7,
     "scn": "Portraits"},
    {"n": "Needs the first", "cn": 3, "wc": 20, "wp": "bg1ub/setup-bg1ub.tp2", "rd": 0},
    {"n": "Removed long ago", "cn": 4, "wc": 30, "wp": "bg1ub/setup-bg1ub.tp2", "gone": True},
    "not a component", {"n": "no number", "wp": "bg1ub/setup-bg1ub.tp2"},
]}


def test_krion64_records_give_numbers_exclusive_groups_and_needs():
    (tp2,) = from_krion([BG1UB])["bg1ub"]
    assert tp2.tp2 == "bg1ub/setup-bg1ub.tp2" and tp2.origin == KRION
    by = {c.number: c for c in tp2.components}
    assert sorted(by) == [0, 10, 11, 20]                     # gone and broken left out
    assert by[10].exclusive == by[11].exclusive == "g:7" and by[10].subgroup == "Portraits"
    assert by[0].exclusive == "" and by[20].requires == [0]   # rd is an index into co[]


def test_a_staged_tp2_names_its_subgroups_and_hides_deprecated():
    described = [{"tp2": "bg1ub/setup-bg1ub.tp2", "components": [
        {"number": 0, "name": "Restoration", "title": "Restoration", "subgroup": None},
        {"number": 10, "name": "Portraits -> classic", "title": "classic",
         "subgroup": "Portraits", "forced": True},
        {"number": 30, "name": "Old", "title": "Old", "deprecated": True}]}]
    (tp2,) = from_described(described)["bg1ub"]
    assert tp2.origin == TP2 and [c.number for c in tp2.components] == [0, 10]
    assert tp2.components[1].exclusive == "sub:Portraits" and tp2.components[1].forced
    assert tp2.components[1].name == "classic"


def test_the_staged_tp2_replaces_krion64_for_its_mod_only():
    staged = from_described([{"tp2": "bg1ub/setup-bg1ub.tp2", "components": []}])
    krion = from_krion([BG1UB, {"co": [{"wc": 0, "n": "x", "wp": "other/other.tp2"}]}])
    both = merged(staged, krion)
    assert both["bg1ub"][0].origin == TP2 and both["other"][0].origin == KRION


def test_a_folder_key_is_the_catalogues_key():
    assert folder_key("BG1UB\\Setup-BG1UB.tp2") == folder_key("bg1ub/x.tp2")


# ------------------------------------------------------------------ the api
def krion_dir(tmp_path, *records):
    root = tmp_path / "krion"
    (root / "mods").mkdir(parents=True)
    for number, record in enumerate(records):
        (root / "mods" / f"{number}.json").write_text(json.dumps(record))
    return str(root)


def test_mod_choices_carry_their_components_and_where_they_come_from(tmp_path):
    mods = api.mod_choices("BGEE", catalogues=[LCC], krion=krion_dir(tmp_path, BG1UB),
                           data_dir=str(tmp_path / "no-cache"))
    by = {m["key"]: m for m in mods}
    assert "bg1ub" in by and "impasylum" not in by          # BG2/BGT only: not BGEE
    (tp2,) = by["bg1ub"]["tp2s"]
    assert tp2["origin"] == "krion64" and len(tp2["components"]) == 4
    assert all(m["tp2s"] == [] for k, m in by.items() if k != "bg1ub")


def test_a_staged_mod_offers_what_its_own_tp2_says(tmp_path):
    target = tmp_path / "Mods" / "bg1ub"
    target.mkdir(parents=True)
    (target / "setup-bg1ub.tp2").write_text("BEGIN ~Only this~ DESIGNATED 5\n")
    mods = api.mod_choices("BGEE", target=str(tmp_path / "Mods"), catalogues=[LCC],
                           krion=krion_dir(tmp_path, BG1UB), data_dir=str(tmp_path / "x"))
    (tp2,) = next(m for m in mods if m["key"] == "bg1ub")["tp2s"]
    assert tp2["origin"] == "tp2"
    assert [(c["number"], c["name"]) for c in tp2["components"]] == [(5, "Only this")]


def test_a_saved_selection_is_one_the_cli_reads(tmp_path):
    path = api.save_selection(str(tmp_path), "bgee",
                              [("bg1ub/setup-bg1ub.tp2", 0), ("bg1ub/setup-bg1ub.tp2", 10)],
                              labels={("bg1ub/setup-bg1ub.tp2", 0): "Restoration"})
    (install,) = api.load_selection(path).installs
    assert install.game == "BGEE"
    assert [(c.tp2, c.component, c.label) for c in install.components] == [
        ("bg1ub/setup-bg1ub.tp2", 0, "Restoration"), ("bg1ub/setup-bg1ub.tp2", 10, "")]


def test_a_selection_leaving_its_folder_is_refused_before_anything_is_written(tmp_path):
    with pytest.raises(ConfigError):
        api.save_selection(str(tmp_path), "EET", [("../../evil.tp2", 0)])
    assert not (tmp_path / api.SELECTION_FILE).exists()


# --------------------------------------------- review follow-ups (#32)
def test_a_component_listed_twice_is_offered_once():
    twice = {"co": [{"n": "a", "wc": 1, "wp": "m/m.tp2"}, {"n": "a again", "wc": 1,
                                                           "wp": "M/M.TP2"}]}
    (tp2,) = from_krion([twice, twice])["m"]
    assert [(c.number, c.name) for c in tp2.components] == [(1, "a")]


def test_a_name_with_a_tilde_or_a_line_break_is_saved_as_one_line(tmp_path):
    path = api.save_selection(str(tmp_path), "EET", [("bg1npc/setup-bg1npc.tp2", 110)],
                              labels={("bg1npc/setup-bg1npc.tp2", 110):
                                      "Banter Timing: Normal (~27 min)\nsecond line"})
    (install,) = api.load_selection(path).installs
    assert install.components[0].label == "Banter Timing: Normal (-27 min) second line"


def test_a_tp2_path_selection_json_refuses_is_marked_not_offered(tmp_path):
    record = {"co": [{"n": "x", "wc": 0, "wp": "OUT, BRIEF CANDLEKEEP!/setup~x.tp2"}]}
    catalogue = tmp_path / "lcc.json"
    catalogue.write_text(json.dumps({"mods": [{"name": "Odd", "tp2": "OUT, BRIEF CANDLEKEEP!",
                                               "games": ["EET"]}]}))
    mods = api.mod_choices("EET", catalogues=[str(catalogue)],
                           krion=krion_dir(tmp_path, record), data_dir=str(tmp_path / "x"))
    (tp2,) = mods[0]["tp2s"]
    assert "unsafe" in tp2["refused"]


def test_a_failed_write_leaves_no_temporary_file(tmp_path, monkeypatch):
    def broken(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError):
        api.save_selection(str(tmp_path), "EET", [("m/m.tp2", 0)])
    assert os.listdir(tmp_path) == []


def test_a_copy_fetched_before_lcc_docs_date_is_maybe_updated(tmp_path):
    """ADR-0044: the day this tool fetched the copy (install.State), not the
    tp2's mtime - a zip unpacks with today's, a tar with the archive's."""
    mods_dir = tmp_path / "Mods"
    (mods_dir / "bg1ub").mkdir(parents=True)
    (mods_dir / "bg1ub" / "setup-bg1ub.tp2").write_text("BEGIN ~Only this~\n")
    state = {"version": 1, "mods": {"bg1ub": {"installed_at": "2025-08-01T09:00:00Z"}}}
    (mods_dir / ".iemod-fetch-state.json").write_text(json.dumps(state))
    mods = api.mod_choices("BGEE", target=str(mods_dir), catalogues=[LCC],
                           krion=krion_dir(tmp_path, BG1UB), data_dir=str(tmp_path / "x"))
    bg1ub = next(m for m in mods if m["key"] == "bg1ub")
    assert bg1ub["maybe_updated"] and bg1ub["fetched"] == "2025-08-01"
    assert bg1ub["last_update"] == "2025-08-25"
    assert bg1ub["page"] == "https://www.pocketplane.net/bg1-unfinished-business/"
    assert bg1ub["update_available"] is not True        # a date says no version


def test_a_copy_put_there_by_hand_has_no_day_and_no_mark(tmp_path):
    mods_dir = tmp_path / "Mods"
    (mods_dir / "bg1ub").mkdir(parents=True)
    (mods_dir / "bg1ub" / "setup-bg1ub.tp2").write_text("BEGIN ~Only this~\n")
    mods = api.mod_choices("BGEE", target=str(mods_dir), catalogues=[LCC],
                           krion=krion_dir(tmp_path, BG1UB), data_dir=str(tmp_path / "x"))
    bg1ub = next(m for m in mods if m["key"] == "bg1ub")
    assert bg1ub["fetched"] is None and not bg1ub["maybe_updated"]


def _fetched_state(mods_dir, **fields):
    entry = {"installed_at": "2025-08-01T09:00:00Z", **fields}
    (mods_dir / ".iemod-fetch-state.json").write_text(
        json.dumps({"version": 1, "mods": {"bg1ub": entry}}))


def _bg1ub(tmp_path, mods_dir):
    krion = tmp_path / "krion"
    if not krion.exists():
        krion = krion_dir(tmp_path, BG1UB)
    mods = api.mod_choices("BGEE", target=str(mods_dir), catalogues=[LCC],
                           krion=str(krion), data_dir=str(tmp_path / "x"))
    return next(m for m in mods if m["key"] == "bg1ub")


def test_a_record_whose_folder_is_gone_marks_nothing(tmp_path):
    """Review of #122: the record outlives a folder the player deleted."""
    mods_dir = tmp_path / "Mods"
    mods_dir.mkdir()
    _fetched_state(mods_dir)
    assert not _bg1ub(tmp_path, mods_dir)["maybe_updated"]


def test_a_copy_replaced_by_hand_with_another_version_marks_nothing(tmp_path):
    """Review of #122: a newer release unpacked over the folder keeps the old
    record (the runner skips it as installed); its tp2 VERSION tells."""
    mods_dir = tmp_path / "Mods"
    (mods_dir / "bg1ub").mkdir(parents=True)
    (mods_dir / "bg1ub" / "setup-bg1ub.tp2").write_text("VERSION ~v18~\nBEGIN ~One~\n")
    _fetched_state(mods_dir, mod_version="v17", tp2_file="setup-bg1ub.tp2")
    assert not _bg1ub(tmp_path, mods_dir)["maybe_updated"]
    (mods_dir / "bg1ub" / "setup-bg1ub.tp2").write_text("VERSION ~v17~\nBEGIN ~One~\n")
    assert _bg1ub(tmp_path, mods_dir)["maybe_updated"]       # the copy fetched, still there


def test_krion64s_day_comes_from_the_cache_record(tmp_path):
    data = tmp_path / "data"
    (data / "krion64" / "data").mkdir(parents=True)
    (data / "krion64" / "data" / "version_cache.json").write_text("{}")
    (data / "sources.json").write_text(json.dumps(
        {"krion64": {"commit": "abc", "date": "2026-10-22T20:41:00Z"}}))
    mods = api.mod_choices("BGEE", catalogues=[LCC], krion=krion_dir(tmp_path, BG1UB),
                           data_dir=str(data))
    assert {m["krion_date"] for m in mods} == {"2026-10-22"}
    (tmp_path / "elsewhere.json").write_text("{}")
    other = api.mod_choices("BGEE", catalogues=[LCC], data_dir=str(data),
                            releases=str(tmp_path / "elsewhere.json"))
    assert {m["krion_date"] for m in other} == {None}     # not the cache's: no day
