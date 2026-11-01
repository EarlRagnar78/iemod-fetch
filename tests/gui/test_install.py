"""
Phase 5, installation, driven like a player drives it (GUI-AUDIT M4 item 22c,
ADR-0045, ADR-0046): the programs found or not - said in their own words -
WeiDU downloaded only after a confirmation naming its licence, a backup of
each game folder first, then the install: the real api.start_install over a
stand-in mod_installer (tests/data/fake_mod_installer.py), its output shown,
its question asked on the page, Cancel honoured.
"""
import json
import os
import sys

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from iemod_fetch import api  # noqa: E402
from iemod_fetch.errors import ConfigError  # noqa: E402
from iemod_fetch.toolchain import Found, Pin  # noqa: E402
from iemod_fetch_gui.pages.install import InstallPage, Services  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
FAKE = os.path.join(DATA, "fake_mod_installer.py")
CHOSEN = [("ub/setup-ub.tp2", 0)]
PIN = Pin("weidu", "25100", "https://github.com/WeiDUorg/weidu/releases/download/v251.00/x.zip",
          "0" * 64, "x/weidu", "0" * 64)


@pytest.fixture
def world(tmp_path):
    """A BG2:EE game, its mods, a stand-in mod_installer and the page's services."""
    game = tmp_path / "bg2ee"
    game.mkdir()
    (game / "chitin.key").write_text("")
    mods = tmp_path / "mods"
    (mods / "ub").mkdir(parents=True)
    if os.name == "nt":
        program = tmp_path / "mod_installer.cmd"
        program.write_text(f'@"{sys.executable}" "{FAKE}" %*\r\n')
    else:
        program = tmp_path / "mod_installer"
        program.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
        program.chmod(0o755)
    state = {"backups": [], "downloads": [], "plans": [], "find": [], "weidu": True,
             "changed": [], "violations": [], "plan_lines": ["~UB/SETUP-UB.TP2~ #0 #0 // x"]}

    def find(mod_installer=None, weidu=None):
        state["find"].append((mod_installer, weidu))
        tools = {"mod_installer": Found("mod_installer", str(program), "16.0.0", "bundled")}
        tools["weidu"] = (Found("weidu", str(program), "25100", "downloaded") if state["weidu"]
                          else Found("weidu", problem="no weidu given, none on PATH"))
        return tools

    def download(tool, progress=None, cancel=None):
        state["downloads"].append(tool)
        progress(500, 1000)
        state["weidu"] = True
        return Found("weidu", str(program), "25100", "downloaded")

    def backup(folder, on_event=None, cancel=None):
        on_event({"event": "backup_started", "files": 1, "bytes": 10})
        state["backups"].insert(0, {"path": f"{folder}-backup", "created": "2026-10-24T09:00",
                                    "files": 1, "game_dir": folder})
        state["changed"] = []                    # a fresh backup: the game is as it is
        return f"{folder}-backup"

    def plan(game_name, chosen, labels, folder):
        state["plans"].append((game_name, list(chosen)))
        plan_dir = tmp_path / "install-plan"
        plan_dir.mkdir(exist_ok=True)
        (plan_dir / "WeiDU.log").write_text(
            "// Log of Currently Installed WeiDU Mods\n"
            + "".join(line + "\n" for line in state["plan_lines"]))
        return {"plan_dir": str(plan_dir), "logs": [], "languages": ["languages: en_US"],
                "violations": list(state["violations"]), "cycles": []}

    def restore_plan(backup_path, folder):
        return {"put_back": list(state["changed"]), "displace": [], "cannot_restore": [],
                "backed_up_from": folder}

    services = Services(find=find, pin=lambda tool: PIN, download=download,
                        backups=lambda folder: list(state["backups"]), backup=backup,
                        plan=plan, games=lambda project: {"BG2EE": str(game)},
                        restore_plan=restore_plan,
                        mods_dir=lambda project: str(mods),
                        timing={"quiet_s": 0.3, "grace_s": 1.0})
    return {"services": services, "state": state, "game": game, "tmp": tmp_path}


def page_of(qtbot, world, answers=()):
    page = InstallPage(str(world["tmp"]), world["services"])
    qtbot.addWidget(page)
    asked = []
    page.confirm = lambda title, text: asked.append((title, text)) or (
        answers[len(asked) - 1] if len(asked) <= len(answers) else True)
    page.confirmed = asked
    page.prepare("BG2EE", CHOSEN, {})
    settled(qtbot, page)
    return page


def settled(qtbot, page):
    """The backups' check (a thread of its own) has ended."""
    qtbot.waitUntil(lambda: page._checking is None, timeout=10000)


def run_to_end(qtbot, page):
    with qtbot.waitSignal(page.finished, timeout=30000):
        page.install()


# ------------------------------------------------------------ the programs
def test_a_missing_program_is_said_in_its_own_words_and_stops_the_install(qtbot, world):
    world["state"]["weidu"] = False
    page = page_of(qtbot, world)
    assert page.tool_state["weidu"].text() == "no weidu given, none on PATH"
    assert "16.0.0 (bundled)" in page.tool_state["mod_installer"].text()
    assert not page.install_button.isEnabled()
    assert "WeiDU: no weidu given, none on PATH" in page.needs.text()
    assert not page.download_weidu.isHidden()             # offered, since it is missing


def test_weidu_is_downloaded_only_once_its_licence_and_source_were_shown(qtbot, world):
    world["state"]["weidu"] = False
    page = page_of(qtbot, world, answers=(False,))
    page.offer_weidu()                                   # the player says no
    assert world["state"]["downloads"] == []
    title, text = page.confirmed[0]
    assert title == "Download WeiDU"
    assert PIN.url in text and "GPL-2.0" in text and "github.com/WeiDUorg/weidu" in text
    with qtbot.waitSignal(page.finished, timeout=10000):
        page.offer_weidu()                               # and now yes
    assert world["state"]["downloads"] == ["weidu"]
    assert page.found["weidu"].ok and "WeiDU downloaded" in page.summary.text()


def test_a_program_chosen_by_hand_is_the_one_looked_at(qtbot, world):
    page = page_of(qtbot, world)
    assert page.download_weidu.isHidden()                 # WeiDU found: nothing to offer
    page.use("weidu", "/my/weidu")
    assert world["state"]["find"][-1] == (None, "/my/weidu")


# ------------------------------------------------------------ the backups
def test_no_backup_no_install_and_one_made_here_counts(qtbot, world):
    page = page_of(qtbot, world)
    folder = str(world["game"])
    assert "no backup yet" in page.backup_state[folder].text()
    assert not page.install_button.isEnabled()
    assert f"no backup of {folder} as it is now" in page.needs.text()
    with qtbot.waitSignal(page.finished, timeout=10000):
        page.back_up(folder)
    settled(qtbot, page)
    assert page.backed_up[folder] == f"{folder}-backup"
    assert "backed up 2026-10-24T09:00" in page.backup_state[folder].text()
    assert "the game is as it was then" in page.backup_state[folder].text()
    assert page.install_button.isEnabled() and page.needs.text() == ""


# ------------------------------------------------------------ the install
def backed_up(world):
    folder = str(world["game"])
    world["state"]["backups"].append({"path": f"{folder}-backup",
                                      "created": "2026-10-24T08:00", "files": 1,
                                      "game_dir": folder})


def test_the_install_asks_first_then_runs_and_shows_mod_installer(qtbot, world):
    backed_up(world)
    page = page_of(qtbot, world, answers=(False,))
    run_to_end(qtbot, page)                              # the player says no
    assert page.outcome is None and not page.running()
    assert "Not installed" in page.summary.text()
    assert not (world["game"] / "WeiDU.log").exists()
    title, text = page.confirmed[0]
    assert title == "Install" and str(world["game"]) in text and "-backup" in text
    settled(qtbot, page)                                 # the backups looked at again
    run_to_end(qtbot, page)
    # written from the selection each time, just before it is confirmed
    assert world["state"]["plans"] == [("BG2EE", CHOSEN)] * 2
    assert page.outcome.ok and page.is_complete()
    shown = page.output.toPlainText()
    assert "Beginning normal install process" in shown and "== setup-ub.tp2 #0" in shown
    assert "languages: en_US" in shown
    assert "Installed." in page.summary.text()
    assert "SETUP-UB.TP2" in (world["game"] / "WeiDU.log").read_text()


def test_a_question_is_asked_on_the_page_and_its_answer_goes_back(qtbot, world, monkeypatch):
    backed_up(world)
    monkeypatch.setenv("FAKE_QUESTIONS", json.dumps({"setup-ub.tp2#0": ["Which portraits?"]}))
    monkeypatch.setenv("FAKE_TRANSCRIPT", str(world["tmp"] / "answers.txt"))
    page = page_of(qtbot, world)
    questions = []
    page.ask_player = lambda question: questions.append(question) or "2"
    run_to_end(qtbot, page)
    # shown whole, WeiDU's lines before it as context, as mod_installer sends it
    assert len(questions) == 1 and questions[0].endswith("Which portraits?")
    assert "Installing [SETUP-UB.TP2 component 0]" in questions[0] and page.outcome.ok
    assert (world["tmp"] / "answers.txt").read_text().split() == ["2"]
    assert "-> 2  (player)" in page.output.toPlainText()


def test_cancelling_a_question_stops_the_install_and_says_how_to_start_again(qtbot, world,
                                                                            monkeypatch):
    backed_up(world)
    monkeypatch.setenv("FAKE_QUESTIONS", json.dumps({"setup-ub.tp2#0": ["Which portraits?"]}))
    page = page_of(qtbot, world)
    page.ask_player = lambda question: None
    run_to_end(qtbot, page)
    assert page.outcome.cancelled and not page.is_complete()
    assert "restore the backup" in page.summary.text()


def test_cancel_while_it_runs(qtbot, world, monkeypatch):
    backed_up(world)
    monkeypatch.setenv("FAKE_SLOW", "20")
    page = page_of(qtbot, world)
    with qtbot.waitSignal(page.finished, timeout=30000):
        page.install()
        qtbot.waitUntil(lambda: "Beginning normal" in page.output.toPlainText(),
                        timeout=10000)
        assert page.running() and page.cancel_button.isEnabled()
        assert not page.install_button.isEnabled()
        page.stop()
    assert page.outcome.cancelled


def test_what_stops_it_before_it_starts_is_said(qtbot, world):
    backed_up(world)

    def refuse(*_args, **_kwargs):
        raise ConfigError("BG2EE: /x already has mods installed (WeiDU.log)")
    world["services"].start = refuse
    page = page_of(qtbot, world)
    run_to_end(qtbot, page)
    assert page.summary.text() == "BG2EE: /x already has mods installed (WeiDU.log)"
    assert page.outcome is None


def test_the_window_installs_last_and_keeps_back_locked_while_it_runs(qtbot, world,
                                                                     monkeypatch):
    from iemod_fetch_gui.window import MainWindow
    backed_up(world)
    monkeypatch.setenv("FAKE_SLOW", "20")
    main = MainWindow(str(world["tmp"]), load=lambda game, project: [],
                      install=world["services"])
    qtbot.addWidget(main)
    main.install.confirm = lambda title, text: True
    main.install.prepare("BG2EE", CHOSEN, {})
    settled(qtbot, main.install)
    main.stack.setCurrentIndex(4)
    main._refresh()
    with qtbot.waitSignal(main.install.finished, timeout=30000):
        main.install.install()
        qtbot.waitUntil(lambda: not main.back.isEnabled(), timeout=5000)
        main.go_back()
        assert main.current == 4                         # Back does nothing meanwhile
        main.install.stop()
    qtbot.waitUntil(lambda: main.back.isEnabled(), timeout=5000)


def test_the_real_plan_writer_names_the_project_folder(tmp_path, monkeypatch):
    """Services' default plan writer is the api's, over the project folder."""
    from iemod_fetch_gui.pages import install
    seen = {}
    monkeypatch.setattr(api, "write_install_plan",
                        lambda *args, **kwargs: seen.update(args=args, kwargs=kwargs) or {})
    install._plan("EET", CHOSEN, {}, str(tmp_path))
    assert seen["kwargs"]["folder"] == str(tmp_path) and seen["kwargs"]["fetch_metadata"]


# ------------------------------------------------------------ review of #87
def test_the_plan_is_always_the_selection_as_it_is_now(qtbot, world):
    """(1) Entering again with another selection: that one is planned."""
    backed_up(world)
    page = page_of(qtbot, world, answers=(False,))
    other = [("ub/setup-ub.tp2", 0), ("ub/setup-ub.tp2", 10)]
    page.prepare("BG2EE", other, {})
    settled(qtbot, page)
    run_to_end(qtbot, page)
    assert world["state"]["plans"] == [("BG2EE", other)]


def test_what_the_order_breaks_is_named_and_needs_a_yes(qtbot, world):
    """(2) Order rules the plan breaks: listed (ten, then a count), and the
    install happens only on "Install anyway"."""
    backed_up(world)
    world["state"]["violations"] = [f"ub before mod{n}" for n in range(12)]
    page = page_of(qtbot, world, answers=(False,))
    run_to_end(qtbot, page)
    title, text = page.confirmed[0]
    assert title == "Install anyway"
    assert "breaks 12 rule(s)" in text and "ub before mod9" in text
    assert "ub before mod10" not in text and "and 2 more" in text
    assert page.outcome is None and not (world["game"] / "WeiDU.log").exists()


def test_a_backup_of_a_game_changed_since_does_not_count(qtbot, world):
    """(3) Restoring it would lose what changed: it is said, and it is not
    the backup the install relies on."""
    backed_up(world)
    world["state"]["changed"] = ["override/x.itm", "WeiDU.log"]
    page = page_of(qtbot, world)
    folder = str(world["game"])
    assert folder not in page.backed_up and not page.install_button.isEnabled()
    assert "changed after the backup" in page.backup_state[folder].text()
    assert "2 file(s) differ" in page.backup_state[folder].text()
    assert f"no backup of {folder} as it is now" in page.needs.text()


def test_a_backup_of_another_folder_does_not_count(qtbot, world):
    world["state"]["backups"].append({"path": "/elsewhere-backup", "created": "x",
                                      "files": 1, "game_dir": "/another/game"})
    page = page_of(qtbot, world)
    folder = str(world["game"])
    assert folder not in page.backed_up
    assert "of another folder (/another/game)" in page.backup_state[folder].text()


def test_a_real_backup_then_a_changed_game_file_is_seen(qtbot, world, tmp_path):
    """(3) with the real backup and plan_restore: a file changed after the
    backup is found, and the backup stops counting."""
    services = world["services"]
    services.backup, services.backups = api.backup_game, api.list_backups
    services.restore_plan = api.plan_restore
    page = page_of(qtbot, world)
    folder = str(world["game"])
    with qtbot.waitSignal(page.finished, timeout=20000):
        page.back_up(folder)
    settled(qtbot, page)
    assert folder in page.backed_up
    (world["game"] / "chitin.key").write_text("changed")
    page.refresh()
    settled(qtbot, page)
    assert folder not in page.backed_up
    assert "changed after the backup" in page.backup_state[folder].text()


# ------------------------------------------------------------ resuming (item 23)
def game_lines(world):
    path = world["game"] / "WeiDU.log"
    return [line for line in path.read_text().splitlines() if line.startswith("~")] \
        if path.exists() else []


def test_a_stopped_install_resumes_with_only_what_is_left(qtbot, world, monkeypatch):
    backed_up(world)
    world["state"]["plan_lines"] = ["~UB/SETUP-UB.TP2~ #0 #0 // x",
                                    "~UB/SETUP-UB.TP2~ #0 #10 // y"]
    monkeypatch.setenv("FAKE_FAIL", "setup-ub.tp2#10")
    page = page_of(qtbot, world)
    run_to_end(qtbot, page)
    assert not page.outcome.ok and "Install resumes from there" in page.summary.text()
    settled(qtbot, page)
    assert page.progress["state"] == "partial"
    assert "1 of 2 component(s) are in, next ub/setup-ub.tp2 #10" in page.resume_state.text()
    assert page.install_button.isEnabled()          # the backup from before still counts

    monkeypatch.delenv("FAKE_FAIL")
    run_to_end(qtbot, page)
    title, text = page.confirmed[-1]
    assert title == "Resume" and "1 of 2 component(s) are already in" in text
    assert page.outcome.ok
    assert [line.split("#")[-1].split()[0] for line in game_lines(world)] == ["0", "10"]
    settled(qtbot, page)
    assert page.resume_state.text() == "Every planned component is in the games."


def test_games_that_are_not_the_plans_install_are_not_installed_into(qtbot, world):
    backed_up(world)
    plan_dir = world["tmp"] / "install-plan"
    plan_dir.mkdir()
    (plan_dir / "WeiDU.log").write_text("~UB/SETUP-UB.TP2~ #0 #0 // x\n")
    (world["game"] / "WeiDU.log").write_text("~OTHER/OTHER.TP2~ #0 #0 // x\n")
    page = page_of(qtbot, world)
    assert page.progress["state"] == "mismatch" and not page.install_button.isEnabled()
    assert "not this plan's install" in page.needs.text()
    assert "Restore the backup to start again" in page.resume_state.text()


def test_while_resuming_the_backup_from_before_counts_though_the_game_changed(qtbot, world):
    backed_up(world)
    world["state"]["changed"] = ["override/ub.itm"]
    plan_dir = world["tmp"] / "install-plan"
    plan_dir.mkdir()
    (plan_dir / "WeiDU.log").write_text("~UB/SETUP-UB.TP2~ #0 #0 // x\n"
                                        "~UB/SETUP-UB.TP2~ #0 #10 // y\n")
    (world["game"] / "WeiDU.log").write_text("~UB/SETUP-UB.TP2~ #0 #0 // x\n")
    page = page_of(qtbot, world)
    folder = str(world["game"])
    assert page.progress["state"] == "partial" and folder in page.backed_up
    assert "before the install that stopped" in page.backup_state[folder].text()


def test_a_component_stopped_half_way_is_said_and_not_installed_into(qtbot, world):
    """Review of item 23: WeiDU's uninstall record of the next component is in
    the game, its log line is not - restoring the backup is the way."""
    backed_up(world)
    plan_dir = world["tmp"] / "install-plan"
    plan_dir.mkdir()
    (plan_dir / "WeiDU.log").write_text("~UB/SETUP-UB.TP2~ #0 #0 // x\n"
                                        "~UB/SETUP-UB.TP2~ #0 #10 // y\n")
    (world["game"] / "WeiDU.log").write_text("~UB/SETUP-UB.TP2~ #0 #0 // x\n")
    (world["game"] / "UB" / "backup" / "10").mkdir(parents=True)
    (world["game"] / "UB" / "backup" / "10" / "UNINSTALL.10").write_text("override/x\n")
    page = page_of(qtbot, world)
    assert page.progress["state"] == "mismatch" and not page.install_button.isEnabled()
    assert "ub/setup-ub.tp2 #10 stopped half-way" in page.resume_state.text()
    assert "Restore the backup to start again" in page.resume_state.text()


def test_resuming_after_a_cancel_inside_a_component_says_so(qtbot, world):
    """A net under the uninstall-record check (review of #89): the page knows
    which components the cancelled run was in, and says so before resuming."""
    backed_up(world)
    world["state"]["plan_lines"] = ["~UB/SETUP-UB.TP2~ #0 #0 // x",
                                    "~UB/SETUP-UB.TP2~ #0 #10 // y"]
    (world["game"] / "WeiDU.log").write_text("~UB/SETUP-UB.TP2~ #0 #0 // x\n")
    page = page_of(qtbot, world, answers=(False,))
    page.cancelled_in = "setup-ub.tp2 #10"
    run_to_end(qtbot, page)
    title, text = page.confirmed[-1]
    assert title == "Resume"
    assert "cancelled while it installed setup-ub.tp2 #10" in text
    assert "restoring the backup is the safe way" in text


def test_a_known_issue_is_said_before_installing_and_the_player_decides(qtbot, world):
    """Item 65: EET's Documents-path bug, as the api says it - in the
    confirmation, not a refusal; no stops, yes installs."""
    backed_up(world)
    world["services"].known_issues = lambda games, mods: [
        "EET's core will write the game's settings to a folder the game never reads"]
    page = page_of(qtbot, world, answers=(False, True))
    assert page.install_button.isEnabled()                 # not a refusal
    run_to_end(qtbot, page)
    title, text = page.confirmed[-1]
    assert title == "Install despite a known issue"
    assert "Known issue(s) this install will meet:" in text and "never reads" in text
    assert page.outcome is None                            # the player said no
    settled(qtbot, page)
    run_to_end(qtbot, page)
    assert page.confirmed[-1][0] == "Install despite a known issue" and page.outcome.ok


def test_a_known_issue_while_resuming_says_resume(qtbot, world, monkeypatch):
    backed_up(world)
    world["state"]["plan_lines"] = ["~UB/SETUP-UB.TP2~ #0 #0 // x",
                                    "~UB/SETUP-UB.TP2~ #0 #10 // y"]
    (world["game"] / "WeiDU.log").write_text("~UB/SETUP-UB.TP2~ #0 #0 // x\n")
    world["services"].known_issues = lambda games, mods: ["a known fault"]
    page = page_of(qtbot, world, answers=(False,))
    run_to_end(qtbot, page)
    assert page.confirmed[-1][0] == "Resume despite a known issue"


def test_a_known_issue_and_broken_rules_say_both_in_the_title(qtbot, world):
    backed_up(world)
    world["state"]["violations"] = ["UB before EET"]
    world["services"].known_issues = lambda games, mods: ["a known fault"]
    page = page_of(qtbot, world, answers=(False,))
    run_to_end(qtbot, page)
    assert page.confirmed[-1][0] == "Install anyway, despite a known issue"


# ------------------------------------------------- the questionnaire (ADR-0049)
UB_TP2 = ("BACKUP ~ub/backup~\nLANGUAGE ~English~ ~english~\n"
          "BEGIN ~Portraits~ DESIGNATED 0\n  PRINT ~Which portraits?~\n"
          "  ACTION_READLN portraits\n")


def asking_mod(world, monkeypatch):
    (world["tmp"] / "mods" / "ub" / "setup-ub.tp2").write_text(UB_TP2)
    monkeypatch.setenv("FAKE_QUESTIONS", json.dumps({"setup-ub.tp2#0": ["Which portraits?"]}))
    monkeypatch.setenv("FAKE_TRANSCRIPT", str(world["tmp"] / "answers.txt"))


def test_questions_are_answered_before_the_install_and_never_asked_during_it(
        qtbot, world, monkeypatch):
    backed_up(world)
    asking_mod(world, monkeypatch)
    page = page_of(qtbot, world)
    shown, asked_live = [], []

    def answer(components, kept):
        shown.append([(c["tp2"], [q["text"] for q in c["questions"]]) for c in components])
        return {"setup-ub.tp2#0": {"Which portraits?": "2"}}
    page.answer_questions = answer
    page.ask_player = lambda question: asked_live.append(question) or "9"
    run_to_end(qtbot, page)
    assert shown == [[("UB/SETUP-UB.TP2", ["Which portraits?"])]]
    assert asked_live == [] and page.outcome.ok            # given from the log
    assert (world["tmp"] / "answers.txt").read_text().split() == ["2"]
    assert "Every question found is answered" in page.confirmed[-1][1]
    # kept in the project: the next install does not ask again
    assert api.load_install_answers(str(world["tmp"])) == {
        "setup-ub.tp2#0": {"Which portraits?": "2"}}
    (world["game"] / "WeiDU.log").unlink()
    shown.clear()
    settled(qtbot, page)
    run_to_end(qtbot, page)
    assert shown == [] and asked_live == []


def test_cancelling_the_questionnaire_installs_nothing(qtbot, world, monkeypatch):
    backed_up(world)
    asking_mod(world, monkeypatch)
    page = page_of(qtbot, world)
    page.answer_questions = lambda components, kept: None
    run_to_end(qtbot, page)
    assert page.outcome is None and page.confirmed == []
    assert "the questions were not answered" in page.summary.text()
    assert not (world["game"] / "WeiDU.log").exists()


def test_a_component_that_cannot_be_read_is_said_in_the_confirmation(qtbot, world):
    backed_up(world)                    # ub has no tp2 here: its questions are unknown
    page = page_of(qtbot, world, answers=(False,))
    run_to_end(qtbot, page)
    text = page.confirmed[-1][1]
    assert "1 component(s) may stop the install to ask" in text
    assert "UB/SETUP-UB.TP2 #0: could not be read in full" in text


def test_the_questionnaire_dialog_fills_what_is_kept_and_refuses_a_comma(qtbot):
    from iemod_fetch_gui.pages.install import _Questionnaire
    components = [{"tp2": "UB/SETUP-UB.TP2", "number": 0, "questions": [
        {"key": "@1", "text": "Which portraits?", "beforehand": True, "repeats": False,
         "known": True, "conditional": False},
        {"key": "@2", "text": "Do you want it sometimes?", "beforehand": False,
         "repeats": False, "known": True, "conditional": True, "by_question": True},
        {"key": "@2", "text": "Do you want it sometimes?", "beforehand": False,
         "repeats": False, "known": True, "conditional": True, "by_question": True},  # once
        {"key": "@3", "text": "How many?", "beforehand": False, "repeats": False,
         "known": True, "conditional": True, "by_question": False},  # not recognisable
        {"key": "x.tp2:9:v#0", "text": "", "beforehand": False, "repeats": False,
         "known": False, "conditional": False}]}]                  # unknown: not offered
    QWidget = pytest.importorskip("PySide6.QtWidgets").QWidget
    parent = QWidget()
    qtbot.addWidget(parent)
    dialog = _Questionnaire(parent, components, {"setup-ub.tp2#0": {"@1": "3"}})
    assert [(key, field.text()) for _name, key, field in dialog.fields] == [("@1", "3"),
                                                                            ("@2", "")]
    dialog.fields[0][2].setText("1,2")
    dialog._accept()
    assert "cannot hold a comma or a line break: Which portraits?" in dialog.problem.text()
    dialog.problem.setText("")
    dialog.fields[0][2].setText("a\nb")              # pasted: a QLineEdit keeps it
    dialog._accept()
    assert "line break" in dialog.problem.text()
    assert dialog.result() != dialog.DialogCode.Accepted
    dialog.fields[0][2].setText(" 4 ")
    # left empty: asked during the install (None), not an Enter
    assert dialog.answers() == {"setup-ub.tp2#0": {"@1": "4", "@2": None}}


CONDITIONAL_TP2 = ("BACKUP ~ub/backup~\nLANGUAGE ~English~ ~english~\n"
                   "BEGIN ~Portraits~ DESIGNATED 0\n"
                   "  ACTION_IF NOT FILE_EXISTS ~ub/prefs.txt~ BEGIN\n"
                   "    PRINT ~Which portraits do you want, old or new?~\n"
                   "    ACTION_READLN portraits\n  END\n"
                   "  PRINT ~Please enter how many extra kits should be installed:~\n"
                   "  ACTION_READLN kits\n")


def test_a_question_under_a_condition_is_answered_by_its_text(qtbot, world, monkeypatch):
    """ADR-0049: the log's order cannot answer a question under a condition;
    recognised by its text when it comes, it is answered by its key."""
    backed_up(world)
    (world["tmp"] / "mods" / "ub" / "setup-ub.tp2").write_text(CONDITIONAL_TP2)
    monkeypatch.setenv("FAKE_QUESTIONS", json.dumps({"setup-ub.tp2#0": [
        "Which portraits do you want, old or new?", "Please enter how many extra kits should be installed:"]}))
    monkeypatch.setenv("FAKE_TRANSCRIPT", str(world["tmp"] / "answers.txt"))
    page = page_of(qtbot, world)
    shown, live = [], []

    def answer(components, kept):
        shown.extend(q["text"] for c in components for q in c["questions"])
        return {"setup-ub.tp2#0": {"Which portraits do you want, old or new?": "new",
                                   "Please enter how many extra kits should be installed:": "3"}}
    page.answer_questions = answer
    page.ask_player = lambda question: live.append(question) or "9"
    run_to_end(qtbot, page)
    assert shown == ["Which portraits do you want, old or new?",
                     "Please enter how many extra kits should be installed:"]
    assert live == [] and page.outcome.ok
    assert (world["tmp"] / "answers.txt").read_text().split() == ["new", "3"]
    assert "-> new  (by question)" in page.output.toPlainText()
    assert "Every question found is answered" in page.confirmed[-1][1]


def test_a_question_under_a_condition_that_is_not_asked_shifts_nothing(qtbot, world,
                                                                     monkeypatch):
    """The condition is false (prefs.txt answers it): only the second question
    comes, and it gets its own answer, not the first one's."""
    backed_up(world)
    (world["tmp"] / "mods" / "ub" / "setup-ub.tp2").write_text(CONDITIONAL_TP2)
    monkeypatch.setenv("FAKE_QUESTIONS", json.dumps({"setup-ub.tp2#0": [
        "Please enter how many extra kits should be installed:"]}))
    monkeypatch.setenv("FAKE_TRANSCRIPT", str(world["tmp"] / "answers.txt"))
    page = page_of(qtbot, world)
    page.answer_questions = lambda components, kept: {"setup-ub.tp2#0": {
        "Which portraits do you want, old or new?": "new",
        "Please enter how many extra kits should be installed:": "3"}}
    page.ask_player = lambda question: "9"
    run_to_end(qtbot, page)
    assert (world["tmp"] / "answers.txt").read_text().split() == ["3"]


def test_after_the_install_each_component_and_how_to_start_the_game_are_said(qtbot, world):
    """Items 69 and 71: what each component came to, in the output and the
    summary, and EEex's advice - for the game that is played."""
    backed_up(world)
    world["services"].launch = lambda plan_dir: [
        {"log": "WeiDU.log", "tp2": "eeex.tp2", "component": 1, "program": "InfinityLoader.exe",
         "why": "EEex is installed: start the game with InfinityLoader.exe.",
         "platform_note": ""}]
    page = page_of(qtbot, world)
    run_to_end(qtbot, page)
    assert page.outcome.ok
    summary = page.summary.text()
    assert "1 installed" in summary and "InfinityLoader.exe" in summary


def test_eeex_in_bgee_s_log_of_an_eet_install_is_not_said(qtbot, world):
    """EET: BG:EE's folder is not the game played - its log's advice is not
    said; the EET game's is."""
    page = InstallPage(str(world["tmp"]), world["services"])
    qtbot.addWidget(page)
    page.games = {"BGEE": "/b", "EET": "/e"}
    page._installing = {"plan_dir": "/p"}
    page.services.launch = lambda plan_dir: [
        {"log": "WeiDU-BGEE.log", "why": "start BG:EE with it", "platform_note": ""}]
    assert page._launch_advice() == ""
    page.services.launch = lambda plan_dir: [
        {"log": "WeiDU-BGEE.log", "why": "start BG:EE with it", "platform_note": ""},
        {"log": "WeiDU.log", "why": "start EET with it", "platform_note": "Through Proton."}]
    assert page._launch_advice() == "start EET with it Through Proton."


def test_a_component_that_needs_a_look_is_listed(qtbot, world):
    from types import SimpleNamespace
    page = InstallPage(str(world["tmp"]), world["services"])
    qtbot.addWidget(page)
    results = [SimpleNamespace(key=("a.tp2", 0), name="A", status="installed", note=""),
               SimpleNamespace(key=("a.tp2", 1), name="B", status="installed with warnings",
                               note=""),
               SimpleNamespace(key=("b.tp2", 0), name="", status="not reached", note="")]
    said = page._show_results(results)
    assert said == "1 installed, 1 installed with warnings, 1 not reached"
    out = page.output.toPlainText()
    assert "a.tp2 #1 B: installed with warnings" in out and "b.tp2 #0: not reached" in out
    assert "a.tp2 #0" not in out


def test_eeex_left_out_by_this_run_is_not_advised_and_quiet_notes_are_not_listed(qtbot, world):
    """Review of #113: the advice follows what was installed, not only the
    plan; an earlier run's EEex (not in this run's results) still counts.
    A note that says nothing went wrong is not a look."""
    from types import SimpleNamespace
    page = InstallPage(str(world["tmp"]), world["services"])
    qtbot.addWidget(page)
    page.games = {"BG2EE": "/g"}
    page._installing = {"plan_dir": "/p"}
    page.services.launch = lambda plan_dir: [
        {"log": "WeiDU.log", "tp2": "eeex.tp2", "component": 1, "why": "use the loader",
         "platform_note": ""}]
    skipped = [SimpleNamespace(key=("eeex.tp2", 1), name="", status="not reached", note="")]
    assert page._launch_advice(skipped) == ""
    assert page._launch_advice([]) == "use the loader"           # an earlier run's
    quiet = [SimpleNamespace(key=("a.tp2", 0), name="A", status="installed",
                             note="no word on it in the debug file")]
    assert page._show_results(quiet) == "1 installed"
    assert "a.tp2 #0" not in page.output.toPlainText()


def test_room_and_weidu_are_said_in_the_confirmation_never_refused(qtbot, world):
    """Item 49: install_readiness's warnings, read on the plan's worker, are
    in the confirmation; the install still goes on when the player says yes."""
    backed_up(world)
    seen = []

    def readiness(games, mods, weidu):
        seen.append((dict(games), weidu))
        return ["BG2EE: the install may need up to 3.0 GiB; 1.0 GiB is free there"]
    world["services"].readiness = readiness
    page = page_of(qtbot, world)
    run_to_end(qtbot, page)
    assert seen and seen[0][1]                                   # WeiDU's path given
    text = page.confirmed[-1][1]
    assert "Before installing, check:" in text and "1.0 GiB is free" in text
    assert page.outcome.ok


def test_a_readiness_check_that_fails_says_nothing_and_none_adds_nothing(qtbot, world):
    backed_up(world)

    def broken(games, mods, weidu):
        raise OSError("drive gone")
    world["services"].readiness = broken
    page = page_of(qtbot, world)
    run_to_end(qtbot, page)
    assert "Before installing, check" not in page.confirmed[-1][1] and page.outcome.ok
