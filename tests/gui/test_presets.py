"""
Presets in phase 2 (M3, GUI-AUDIT item 19), driven like a player drives them:
a choice saved to a file and loaded back, and a WeiDU.log loaded as a choice.
The file dialogs are answered by the test.
"""
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QFileDialog, QMessageBox  # noqa: E402

from iemod_fetch import api  # noqa: E402
from iemod_fetch_gui import text as qtext  # noqa: E402

from .test_conflicts import NEED, TW, UB, choose, page  # noqa: E402


def answer(monkeypatch, path):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))


def test_a_saved_preset_loads_back_into_the_tree(qtbot, tmp_path, monkeypatch):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (UB, 10), (TW, 100))
    preset = tmp_path / "my build"
    answer(monkeypatch, preset)
    widget.save_preset.click()
    assert (tmp_path / "my build.json").is_file()       # the extension is added
    assert "Preset saved" in widget.status.text()
    choose(qtbot, widget, (UB, 10), (TW, 100), on=False)
    assert widget.chosen() == []
    answer(monkeypatch, tmp_path / "my build.json")
    shown = []
    monkeypatch.setattr(qtext, "information", lambda *a: shown.append(a[2]))
    with qtbot.waitSignal(widget.checked, timeout=5000):
        widget.load_preset.click()
    assert sorted(widget.chosen()) == sorted([(UB, 10), (TW, 100)])
    assert shown == []                                   # nothing to report


def test_a_weidu_log_chooses_what_it_lists_and_names_what_it_cannot(qtbot, tmp_path,
                                                                    monkeypatch):
    widget, _checker = page(qtbot, tmp_path)
    log = tmp_path / "WeiDU.log"
    log.write_text("// Log of Currently Installed WeiDU Mods\n"
                   "~BG1UB\\SETUP-BG1UB.TP2~ #0 #10 // Restored\n"
                   "~NEEDED\\SETUP-NEEDED.TP2~ #0 #0 // Needed\n"
                   "~ghost\\setup-ghost.tp2~ #0 #1 // not in the list\n")
    answer(monkeypatch, log)
    shown = []
    monkeypatch.setattr(qtext, "information", lambda *a: shown.append(a[2]))
    with qtbot.waitSignal(widget.checked, timeout=5000):
        widget.load_preset.click()
    assert sorted(widget.chosen()) == sorted([(UB, 10), (NEED, 0)])
    assert len(shown) == 1 and "ghost/setup-ghost.tp2 #1" in shown[0]


def test_a_file_that_is_no_preset_changes_nothing(qtbot, tmp_path, monkeypatch):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (UB, 10))
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json")
    answer(monkeypatch, bad)
    errors = []
    monkeypatch.setattr(qtext, "critical", lambda *a: errors.append(a[1]))
    widget.load_preset.click()
    assert errors == ["Cannot load the preset"]
    assert widget.chosen() == [(UB, 10)]


def test_a_cancelled_dialog_does_nothing(qtbot, tmp_path, monkeypatch):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (UB, 10))
    answer(monkeypatch, "")
    widget.load_preset.click()
    widget.save_preset.click()
    assert widget.chosen() == [(UB, 10)]
    assert not list(tmp_path.glob("*.json")) or \
        {p.name for p in tmp_path.glob("*.json")} <= {api.SELECTION_FILE,
                                                      api.DECISIONS_FILE}


def test_a_log_with_no_component_changes_nothing(qtbot, tmp_path, monkeypatch):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (UB, 10))
    log = tmp_path / "WeiDU.log"
    log.write_text("// Log of Currently Installed WeiDU Mods\n")
    answer(monkeypatch, log)
    errors = []
    monkeypatch.setattr(qtext, "critical", lambda *a: errors.append(a[2]))
    widget.load_preset.click()
    assert errors and "chooses no component" in errors[0]
    assert widget.chosen() == [(UB, 10)]


def test_replacing_a_choice_asks_first(qtbot, tmp_path, monkeypatch):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (UB, 10))
    log = tmp_path / "WeiDU.log"
    log.write_text("~CDTWEAKS\\SETUP-CDTWEAKS.TP2~ #0 #100 // x\n")
    answer(monkeypatch, log)
    monkeypatch.setattr(qtext, "question",
                        lambda *a, **k: QMessageBox.StandardButton.No)
    widget.load_preset.click()
    assert widget.chosen() == [(UB, 10)]                  # No keeps it
    monkeypatch.setattr(qtext, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    with qtbot.waitSignal(widget.checked, timeout=5000):
        widget.load_preset.click()
    assert widget.chosen() == [(TW, 100)]


@pytest.mark.parametrize("name", ["decisions", "selection.json", "install-order.txt"])
def test_a_preset_never_replaces_the_projects_own_files(qtbot, tmp_path, monkeypatch,
                                                         name):
    # Review of #41: "decisions" became decisions.json, replaced unasked
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (UB, 10))
    (tmp_path / api.DECISIONS_FILE).write_text('{"keep": "me"}')
    answer(monkeypatch, tmp_path / name)
    errors = []
    monkeypatch.setattr(qtext, "critical", lambda *a: errors.append(a[2]))
    monkeypatch.setattr(qtext, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    widget.save_preset.click()
    assert (tmp_path / api.DECISIONS_FILE).read_text() == '{"keep": "me"}'
    assert errors or name == "install-order.txt" and not (tmp_path / name).exists()


def test_a_name_completed_with_json_asks_before_replacing(qtbot, tmp_path, monkeypatch):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (UB, 10))
    (tmp_path / "mine.json").write_text("old")
    answer(monkeypatch, tmp_path / "mine")
    monkeypatch.setattr(qtext, "question",
                        lambda *a, **k: QMessageBox.StandardButton.No)
    widget.save_preset.click()
    assert (tmp_path / "mine.json").read_text() == "old"


def test_presets_wait_for_the_list_being_loaded(qtbot, tmp_path):
    # Review of #41: a preset loaded while another game's list loaded went to
    # the old tree, then was thrown away
    widget, _checker = page(qtbot, tmp_path)
    assert widget.load_preset.isEnabled() and widget.save_preset.isEnabled()
    widget._presets(False)          # as start() does while a list loads
    assert not widget.load_preset.isEnabled() and not widget.save_preset.isEnabled()


def test_the_confirmation_counts_a_repeated_component_once():
    from iemod_fetch_gui.pages.mods import preset_size
    assert preset_size({"chosen": [["bg1ub/bg1ub.tp2", 0], ["BG1UB/BG1UB.TP2", 0],
                                   ["eet/EET.tp2", 0]],
                        "unmatched": ["ghost/setup-ghost.tp2 #1"] * 2}) == 3


def test_a_project_folder_named_another_way_is_the_same_folder(tmp_path):
    from iemod_fetch_gui.pages.mods import same_folder
    (tmp_path / "real").mkdir()
    try:
        (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    except OSError:                 # Windows without the privilege to make links
        pytest.skip("cannot make a symbolic link here")
    assert same_folder(str(tmp_path / "link"), str(tmp_path / "real") + "/")
    assert not same_folder(str(tmp_path), str(tmp_path / "real"))
