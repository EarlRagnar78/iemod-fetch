"""
The wizard's first phase, driven like a player drives it (M3, GUI-AUDIT items
14-15). The folders are synthetic games WeiDU itself would identify (marker
files, as tests/test_real_weidu.py); nothing needs a real game.
"""
import os

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402

from iemod_fetch import api  # noqa: E402
from iemod_fetch.config import load_config  # noqa: E402
from iemod_fetch_gui.pages.game import GamePage  # noqa: E402
from iemod_fetch_gui.window import PHASES, MainWindow  # noqa: E402
from test_project import bg2ee, bgee  # noqa: E402


def no_plan(*_args):
    return {"phases": [], "cycles": [], "violations": [], "planned": False, "custom": False}


def no_check(*_args):
    return {"findings": [], "stale": [], "rules_checked": 0, "planned": False,
            "problem": None}


def window(qtbot, folder):
    # No test reaches the network: the catalogue comes from an empty loader.
    main = MainWindow(str(folder), load=lambda game, project: [], check=no_check,
                      plan=no_plan)
    qtbot.addWidget(main)
    return main


def choose(page, bgee_dir="", bg2ee_dir=""):
    page.bgee.edit.setText(bgee_dir)
    page.bg2ee.edit.setText(bg2ee_dir)
    page.check()


def test_next_waits_for_folders_that_are_what_eet_needs(qtbot, tmp_path):
    main = window(qtbot, tmp_path / "project")
    (tmp_path / "project").mkdir()
    assert main.game.game() == "EET" and not main.next.isEnabled()
    assert "BGEE_DIR: no folder chosen" in main.game.findings.text()
    choose(main.game, bg2ee(tmp_path), bgee(tmp_path))            # swapped
    assert not main.next.isEnabled() and "not BGEE" in main.game.findings.text()
    choose(main.game, bgee(tmp_path / "a"), bg2ee(tmp_path / "a"))
    assert main.next.isEnabled()
    assert "The folders are what EET needs" in main.game.findings.text()


def test_next_saves_the_project_the_cli_reads(qtbot, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    main = window(qtbot, project)
    first, second = bgee(tmp_path), bg2ee(tmp_path)
    choose(main.game, first, second)
    main.game.preferred.setCurrentIndex(main.game.preferred.findData("it_IT"))
    main.game.fallback.setCurrentIndex(main.game.fallback.findData("en_US"))
    qtbot.mouseClick(main.next, Qt.MouseButton.LeftButton)
    assert main.current == 1
    values = load_config(explicit=str(project / api.PROJECT_FILE)).values
    assert values == {"bgee_dir": first, "bg2ee_dir": second,
                      "language_preference": "it_IT,en_US"}
    qtbot.mouseClick(main.back, Qt.MouseButton.LeftButton)
    assert main.current == 0


def test_one_game_shows_only_its_folder(qtbot, tmp_path):
    page = GamePage(str(tmp_path))
    qtbot.addWidget(page)
    page.show()
    page.radios["BG2EE"].setChecked(True)
    assert page.bg2ee.isVisible() and not page.bgee.isVisible()
    choose(page, "", bg2ee(tmp_path))
    assert page.is_complete()
    assert api.load_project(page.save().rsplit(os.sep, 1)[0])["game"] == "BG2EE"


def test_a_saved_project_opens_where_it_was_left(qtbot, tmp_path):
    first = bgee(tmp_path)
    api.save_project(str(tmp_path), "BGEE", first, None, ["fr_FR", "en_US"])
    page = GamePage(str(tmp_path))
    qtbot.addWidget(page)
    assert page.game() == "BGEE" and page.bgee.path() == first
    assert page.language_preference() == ["fr_FR", "en_US"] and page.is_complete()


def test_typing_a_path_rechecks_once_the_typing_stops(qtbot, tmp_path):
    page = GamePage(str(tmp_path))
    qtbot.addWidget(page)
    page.radios["BG2EE"].setChecked(True)
    folder = bg2ee(tmp_path)
    with qtbot.waitSignal(page.completeChanged, timeout=2000,
                          check_params_cb=lambda complete: complete) as signal:
        page.bg2ee.edit.setText(folder)
        assert not page.is_complete()          # unchecked until the typing stops
    assert signal.args == [True]


def test_the_phases_are_bws_ngs_and_the_last_one_installs(qtbot, tmp_path):
    from iemod_fetch_gui.pages.install import InstallPage
    main = window(qtbot, tmp_path)
    assert [main.phases.item(i).text() for i in range(main.phases.count())] == [
        f"{n}  {name}" for n, name in enumerate(PHASES, start=1)]
    assert isinstance(main.pages[4], InstallPage)           # M4 item 22c


def test_next_never_saves_a_path_typed_after_the_last_check(qtbot, tmp_path):
    """Review of #31: typing, then Next within the re-check delay."""
    project = tmp_path / "project"
    main = window(qtbot, project)
    main.game.radios["BGEE"].setChecked(True)
    choose(main.game, bgee(tmp_path), "")
    assert main.next.isEnabled()
    main.game.bgee.edit.setText(str(tmp_path / "nowhere"))      # timer pending
    assert not main.next.isEnabled()
    main.go_next()                                               # e.g. a shortcut
    assert main.current == 0 and not (project / api.PROJECT_FILE).exists()


def test_a_broken_project_file_still_opens_the_wizard(qtbot, tmp_path):
    (tmp_path / api.PROJECT_FILE).write_text("[iemod-fetch]\nworkers = many\n")
    main = window(qtbot, tmp_path)
    assert "could not be read" in main.game.findings.text()


def test_the_window_builds_the_tls_context_before_it_is_shown(qtbot, tmp_path, monkeypatch):
    """ADR-0048: on Windows building it reads the certificate store holding
    the GIL; built in a download's thread it froze the window 50-240 ms."""
    from iemod_fetch import net
    monkeypatch.setattr(net, "_HTTPS_CONTEXT", None)
    window(qtbot, tmp_path)                     # constructed, never shown
    assert net._HTTPS_CONTEXT is not None
