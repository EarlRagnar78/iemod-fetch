"""
Presets (M3, GUI-AUDIT item 19): a choice saved to a file and loaded back, or
taken from what other tools write - a WeiDU.log, a BIO share code, a Project
Infinity list - told apart by what the file holds, and matched to the
catalogue's tp2s as the wizard lists them.
"""
import json
import os

import pytest

from iemod_fetch import api
from iemod_fetch.errors import ConfigError

from test_pi import DLC_TP2, KRION_DLC, KRION_FIXPACK, LIST, stage

HERE = os.path.dirname(__file__)
MOCK = os.path.join(HERE, "data", "eetmock")
BIO = os.path.join(HERE, "data", "bio", "eet-mock.bio")
KNOWN = ["DlcMerger/DlcMerger.tp2", "eefixpack/setup-eefixpack.tp2", "bg1ub/bg1ub.tp2"]


def test_a_saved_preset_loads_back_as_it_was(tmp_path):
    chosen = [("eefixpack/setup-eefixpack.tp2", 0), ("DlcMerger/DlcMerger.tp2", 1)]
    path = api.export_selection(str(tmp_path / "my build.json"), "BGEE", chosen,
                                data_dir=str(tmp_path / "no-cache"))
    # the same file the project keeps, so the command line reads it too
    assert api.load_selection(path).installs[0].game == "BGEE"
    got = api.import_selection(path, "BGEE", KNOWN)
    assert got["kind"] == "selection" and got["games"] == ["BGEE"]
    assert got["chosen"] == [list(pair) for pair in chosen]
    assert got["unmatched"] == [] and got["notes"] == []


def test_a_preset_is_byte_for_byte_the_projects_selection(tmp_path):
    chosen = [("DlcMerger/DlcMerger.tp2", 1)]
    preset = api.export_selection(str(tmp_path / "p.json"), "BGEE", chosen,
                                  data_dir=str(tmp_path / "no-cache"))
    project = api.save_selection(str(tmp_path), "BGEE", chosen,
                                 data_dir=str(tmp_path / "no-cache"))
    with open(preset, "rb") as a, open(project, "rb") as b:
        assert a.read() == b.read()


def test_a_weidu_log_is_matched_to_the_list_ignoring_case_and_spelling(tmp_path):
    log = tmp_path / "WeiDU.log"
    log.write_text("// Log of Currently Installed WeiDU Mods\n"
                   "~DLCMERGER\\DLCMERGER.TP2~ #0 #1 // Merge SoD\n"
                   "~EEFIXPACK\\SETUP-EEFIXPACK.TP2~ #0 #0 // Core Fixes\n"
                   "~ghost\\setup-ghost.tp2~ #0 #3 // not in the list\n")
    got = api.import_selection(str(log), "BGEE", KNOWN)
    assert got["kind"] == "weidu-log"
    assert got["chosen"] == [["DlcMerger/DlcMerger.tp2", 1],
                             ["eefixpack/setup-eefixpack.tp2", 0]]
    assert got["unmatched"] == ["ghost/setup-ghost.tp2 #3"]


def test_a_bio_share_code_is_read_from_its_file():
    got = api.import_selection(BIO, "EET", KNOWN)
    assert got["kind"] == "bio-code"
    assert got["chosen"] and set(got["games"]) <= {"BGEE", "EET"}


def test_a_project_infinity_list_resolves_through_krion64(tmp_path):
    krion = tmp_path / "krion" / "mods"
    krion.mkdir(parents=True)
    for record in (KRION_DLC, KRION_FIXPACK):
        (krion / f"{record['t']}.json").write_text(json.dumps(record))
    pi_list = tmp_path / "install-BGEE.txt"
    pi_list.write_text(LIST)
    got = api.import_selection(str(pi_list), "BGEE", KNOWN,
                               order_catalogue=str(tmp_path / "krion"))
    assert got["kind"] == "pi-list"
    assert got["chosen"] == [["DlcMerger/DlcMerger.tp2", 1],
                             ["eefixpack/setup-eefixpack.tp2", 0]]


def test_a_pi_label_of_a_staged_mod_comes_from_its_tp2(tmp_path):
    stage(str(tmp_path / "Mods"), "DlcMerger", "DlcMerger.tp2", DLC_TP2)
    pi_list = tmp_path / "list.txt"
    pi_list.write_text("A7-DLCMERGER-MERGE_SOD;DLC Merger\n")
    got = api.import_selection(str(pi_list), "BGEE", KNOWN, target=str(tmp_path / "Mods"),
                               data_dir=str(tmp_path / "no-cache"))
    assert got["chosen"] == [["DlcMerger/DlcMerger.tp2", 1]]


def test_a_preset_for_another_game_says_so(tmp_path):
    log = tmp_path / "WeiDU.log"
    log.write_text("~DlcMerger\\DlcMerger.tp2~ #0 #1 // Merge SoD\n")
    selection = tmp_path / "s.json"
    selection.write_text(json.dumps({"schema_version": 1, "installs": [
        {"game": "BG2EE", "components": [{"tp2": "DlcMerger/DlcMerger.tp2",
                                          "component": 1}]}]}))
    got = api.import_selection(str(selection), "BGEE", KNOWN)
    assert got["notes"] == ["the preset is for BG2EE; the project is BGEE"]


def test_a_bg_ee_build_loaded_into_an_eet_project_says_so(tmp_path):
    path = tmp_path / "bgee.json"
    path.write_text(json.dumps({"schema_version": 1, "installs": [
        {"game": "BGEE", "components": [{"tp2": "bg1ub/bg1ub.tp2", "component": 0}]}]}))
    got = api.import_selection(str(path), "EET", [])
    assert got["notes"] == [("the preset is a BG:EE build, not EET; its components are "
                             "chosen for this EET build")]
    assert got["chosen"] == [["bg1ub/bg1ub.tp2", 0]]


def test_a_log_that_names_no_game_is_read_as_the_projects():
    got = api.import_selection(os.path.join(MOCK, "WeiDU-BGEE.log"), "EET", [])
    assert got["kind"] == "weidu-log" and got["games"] == ["EET"] and got["notes"] == []
    assert ["bg1ub/bg1ub.tp2", 0] in got["chosen"]


def test_an_eet_build_reads_both_installs(tmp_path):
    chosen = [("bg1ub/bg1ub.tp2", 0), ("eet/EET.tp2", 0)]
    path = tmp_path / "eet.json"
    path.write_text(json.dumps({"schema_version": 1, "installs": [
        {"game": "BGEE", "components": [{"tp2": chosen[0][0], "component": 0}]},
        {"game": "EET", "components": [{"tp2": chosen[1][0], "component": 0}]}]}))
    got = api.import_selection(str(path), "EET", [])
    assert got["games"] == ["BGEE", "EET"] and got["notes"] == []
    assert got["chosen"] == [list(pair) for pair in chosen]


@pytest.mark.parametrize("text", [
    "// Log of Currently Installed WeiDU Mods\n// The top of the file is the 'oldest' mod\n",
    "", "   \n",
    '{"schema_version": 1, "installs": [{"game": "BGEE", "components": []}]}'])
def test_a_preset_that_chooses_nothing_is_refused_not_a_cleared_choice(tmp_path, text):
    # Review of #41: a fresh game's WeiDU.log (its header only) was read as an
    # empty Project Infinity list and silently cleared the whole choice
    path = tmp_path / "WeiDU.log"
    path.write_text(text)
    with pytest.raises(ConfigError, match="chooses no component"):
        api.import_selection(str(path), "BGEE", KNOWN, data_dir=str(tmp_path / "no-cache"))


@pytest.mark.parametrize("text", ["{ not json", "BIO-MODLIST-V1:!!!",
                                  "nothing;here\nat all"])
def test_a_file_that_is_no_preset_is_a_configuration_error(tmp_path, text):
    bad = tmp_path / "bad.txt"
    bad.write_text(text)
    with pytest.raises(ConfigError):
        api.import_selection(str(bad), "BGEE", KNOWN, data_dir=str(tmp_path / "no-cache"))


def test_a_missing_or_huge_file_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        api.import_selection(str(tmp_path / "nope.json"), "BGEE")
    big = tmp_path / "big.json"
    big.write_bytes(b" " * (8 * 1024 * 1024 + 1))
    with pytest.raises(ConfigError, match="larger than"):
        api.import_selection(str(big), "BGEE")
