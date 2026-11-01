"""
The wizard's first phase without a window (M3, GUI-AUDIT item 15): checking
game folders as WeiDU's GAME_IS sees them, and the project file the GUI saves
and the command line reads.
"""
import os

import pytest

from iemod_fetch import api
from iemod_fetch.config import load_config, read_section, write_values
from iemod_fetch.errors import ConfigError
from test_gamedir import game


def bgee(tmp_path, sod=True):
    return game(tmp_path, "bgee", override=["oh1000.are"],
                files=[os.path.join("movies", "sodcin05.wbm")] if sod else [])


def bg2ee(tmp_path):
    return game(tmp_path, "bg2ee", override=["oh6000.are"])


# ------------------------------------------------------------ the folders
def test_eet_needs_a_bgee_with_sod_and_a_clean_bg2ee(tmp_path):
    result = api.check_game_folders("EET", bgee(tmp_path), bg2ee(tmp_path))
    assert result["ok"] and result["games"] == {"bgee": "BGEE", "bg2ee": "BG2EE"}
    assert result["sod"] == "merged"


def test_folders_not_chosen_are_named_not_called_missing(tmp_path):
    result = api.check_game_folders("EET", None, bg2ee(tmp_path))
    assert not result["ok"] and result["problems"] == ["BGEE_DIR: no folder chosen"]


def test_the_folders_swapped_are_refused(tmp_path):
    result = api.check_game_folders("EET", bg2ee(tmp_path), bgee(tmp_path))
    assert not result["ok"]
    assert any("is BG2EE, not BGEE" in p for p in result["problems"])


def test_sod_as_a_dlc_archive_is_a_note_at_this_phase(tmp_path):
    folder = game(tmp_path, "bgee", override=["oh1000.are"], files=["sod-dlc.zip"])
    result = api.check_game_folders("EET", folder, bg2ee(tmp_path))
    assert result["ok"] and result["sod"] == "dlc"
    assert "DlcMerger #1 will be needed first" in result["notes"][0]


@pytest.mark.parametrize("name, make, other", [("BGEE", bgee, bg2ee), ("BG2EE", bg2ee, bgee)])
def test_one_game_needs_one_folder_of_that_game(tmp_path, name, make, other):
    right = make(tmp_path)
    args = (right, None) if name == "BGEE" else (None, right)
    assert api.check_game_folders(name, *args)["ok"]
    wrong = other(tmp_path / "x")
    args = (wrong, None) if name == "BGEE" else (None, wrong)
    assert not api.check_game_folders(name, *args)["ok"]


def test_a_folder_without_chitin_key_is_not_a_game(tmp_path):
    result = api.check_game_folders("BG2EE", None, str(tmp_path))
    assert result["problems"] == [f"BG2EE_DIR {tmp_path} has no chitin.key: not a game folder"]


def test_an_eet_folder_is_not_a_bg2ee(tmp_path):
    folder = game(tmp_path, "eet", override=["oh6000.are", "EET.flag"])
    assert "is EET" in api.check_game_folders("BG2EE", None, folder)["problems"][0]


# ------------------------------------------------------------ the project
def test_a_saved_project_is_what_the_cli_reads(tmp_path):
    first, second = bgee(tmp_path), bg2ee(tmp_path)
    path = api.save_project(str(tmp_path), "EET", first, second, ["it_IT", "en_US"])
    assert path == str(tmp_path / "iemod-fetch.ini")
    values = load_config(explicit=path).values
    assert values == {"bgee_dir": first, "bg2ee_dir": second,
                      "language_preference": "it_IT,en_US"}
    assert api.load_project(str(tmp_path)) == {
        "path": path, "game": "EET", "bgee_dir": first, "bg2ee_dir": second,
        "language_preference": ["it_IT", "en_US"], "target": None, "problem": None}


def test_saving_keeps_the_rest_of_the_file_and_drops_an_unused_folder(tmp_path):
    ini = tmp_path / "iemod-fetch.ini"
    ini.write_text("[iemod-fetch]\nworkers = 3\nbgee_dir = /old\n\n[other]\nx = 1\n")
    api.save_project(str(tmp_path), "BG2EE", "/ignored", "/games/bg2ee", ["en_US"])
    values = load_config(explicit=str(ini)).values
    assert values == {"workers": 3, "bg2ee_dir": "/games/bg2ee", "language_preference": "en_US"}
    assert read_section(str(ini), "other") == {"x": "1"}
    assert api.load_project(str(tmp_path))["game"] == "BG2EE"


def test_an_empty_project_folder_loads_as_nothing_chosen(tmp_path):
    assert api.load_project(str(tmp_path))["game"] is None


def test_a_bad_game_or_language_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="unknown game"):
        api.save_project(str(tmp_path), "IWD", None, None)
    with pytest.raises(ConfigError, match="unknown language"):
        api.save_project(str(tmp_path), "EET", None, None, ["klingon"])
    assert not (tmp_path / "iemod-fetch.ini").exists()


def test_only_known_options_are_written(tmp_path):
    with pytest.raises(ConfigError, match="unknown option"):
        write_values(str(tmp_path / "x.ini"), {"not_an_option": 1})


def test_languages_name_every_code_the_preference_accepts():
    codes = [language["code"] for language in api.languages()]
    assert "it_IT" in codes and "en_US" in codes and len(codes) == len(set(codes))


def test_the_gui_contract_forbids_every_module_but_the_api():
    """.importlinter lists the modules the GUI may not import; a new module
    must be added there, or the GUI could reach past the api unnoticed."""
    root = os.path.join(os.path.dirname(__file__), os.pardir)
    with open(os.path.join(root, ".importlinter"), encoding="utf-8") as fh:
        text = fh.read()
    section = text.split("[importlinter:contract:gui-only-through-api]")[1]
    listed = {line.strip() for line in section.splitlines()
              if line.strip().startswith("iemod_fetch.")}
    modules = {f"iemod_fetch.{name[:-3]}" for name in os.listdir(os.path.join(root, "iemod_fetch"))
               if name.endswith(".py") and name not in ("__init__.py", "__main__.py", "api.py")}
    assert listed == modules


# ------------------------------------------------- review follow-ups (#31)
@pytest.mark.parametrize("text", [
    "[iemod-fetch]\nworkers = many\n",
    "[iemod-fetch]\nlanguage_preference = klingon\n",
    "no section header\n",
    "[iemod-fetch]\nbgee_dir = C:/100%BG\n",
])
def test_an_unreadable_project_file_is_a_problem_not_a_crash(tmp_path, text):
    (tmp_path / "iemod-fetch.ini").write_text(text)
    project = api.load_project(str(tmp_path))
    assert project["problem"] and project["game"] is None


def test_a_foreign_gui_section_with_a_percent_is_ignored(tmp_path):
    (tmp_path / "iemod-fetch.ini").write_text("[iemod-fetch-gui]\ngame = 50%\n")
    assert read_section(str(tmp_path / "iemod-fetch.ini"), "iemod-fetch-gui") == {}


def test_a_path_with_a_percent_is_saved_and_read_back_by_the_cli(tmp_path):
    path = api.save_project(str(tmp_path), "BGEE", "C:/Games/100%BG", None)
    assert "100%%BG" in (tmp_path / "iemod-fetch.ini").read_text()
    assert load_config(explicit=path).values["bgee_dir"] == "C:/Games/100%BG"
    assert api.load_project(str(tmp_path))["bgee_dir"] == "C:/Games/100%BG"


def test_the_hyphenated_spelling_the_cli_accepts_is_replaced_too(tmp_path):
    ini = tmp_path / "iemod-fetch.ini"
    ini.write_text("[iemod-fetch]\nbgee-dir = C:/old\n")
    api.save_project(str(tmp_path), "BG2EE", None, "C:/bg2")
    assert load_config(explicit=str(ini)).values == {"bg2ee_dir": "C:/bg2"}


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_saving_keeps_the_files_permissions(tmp_path):
    ini = tmp_path / "iemod-fetch.ini"
    ini.write_text("[iemod-fetch]\n")
    os.chmod(ini, 0o400)          # read-only for its owner: not what mkstemp would give
    api.save_project(str(tmp_path), "EET", None, None)
    assert oct(os.stat(ini).st_mode & 0o777) == "0o400"
    (tmp_path / "new").mkdir()
    api.save_project(str(tmp_path / "new"), "EET", None, None)    # a new file: owner only
    assert os.stat(tmp_path / "new" / "iemod-fetch.ini").st_mode & 0o077 == 0
