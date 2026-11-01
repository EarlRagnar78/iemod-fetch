"""
The install the wizard runs (GUI-AUDIT M4 item 22, ADR-0045): mod_installer
as a child of this program, its output read line by line, WeiDU's questions
answered - EET's with the BG:EE folder, then what the planned log records
(`// @wlb-inputs:`), then by asking the player - and stopped on Cancel.

mod_installer is played by tests/data/fake_mod_installer.py, which prints
what the real one logs and asks the way it asks; the real mod_installer is
run against a stand-in WeiDU by test_real_mod_installer.py when it is built.
"""
import os
import sys
import threading

import pytest

from iemod_fetch import api
from iemod_fetch.errors import ConfigError
from iemod_fetch.install_run import command, preflight
from iemod_fetch.prompts import OutputReader, question_line, recorded_answers, wlb_inputs

HERE = os.path.dirname(__file__)
FAKE = os.path.join(HERE, "data", "fake_mod_installer.py")
EET_QUESTION = "Enter the full path to your BG:EE+SoD installation then press Enter."


# ----------------------------------------------------------- the answers
def test_recorded_answers_are_read_left_to_right_with_blanks():
    assert wlb_inputs("~A\\A.TP2~ #0 #10 // Confirm: v1.0 // @wlb-inputs: y,,c") == ["y", "", "c"]
    assert wlb_inputs("~A\\A.TP2~ #0 #10 // Confirm: v1.0") is None
    assert wlb_inputs(r"~EET\EET.TP2~ #0 #0 // EET core // @wlb-inputs: C:\My Games\BG2") == [
        r"C:\My Games\BG2"]
    log = ("// Log of Currently Installed WeiDU Mods\n"
           "~EET\\EET.TP2~ #0 #0 // EET core (resource importation): v14.0\n"
           "~VIENXAY/VIENXAY.TP2~ #0 #0 // Vienxay NPC: 1.67 // @wlb-inputs: 1,2\n")
    assert recorded_answers(log) == {("vienxay.tp2", 0): ["1", "2"]}


def test_the_output_is_read_into_batches_and_questions():
    reader = OutputReader()
    kinds = []
    for line in [
            ("[2026-10-24T00:00:00Z INFO  mod_installer::installers] Installing mod "
             'WeiduBatchedComponents([WeiduComponent { tp_file: "SETUP-UB.TP2", name: "ub", '
             'lang: "0", component: "0", component_name: "", sub_component: "", '
             'version: "" }, WeiduComponent { tp_file: "SETUP-UB.TP2", name: "ub", lang: "0", '
             'component: "10", component_name: "", sub_component: "", version: "" }])\n'),
            "some WeiDU output\n",
            "[2026-10-24T00:00:00Z INFO  mod_installer::runner] User Input required\n",
            "[2026-10-24T00:00:00Z INFO  mod_installer::runner] Question is\n",
            "[2026-10-24T00:00:00Z INFO  mod_installer::runner] Which portraits?\n",
            "1] classic\n", "2] new\n"]:
        kinds += [(e.kind, e.batch) for e in reader.feed(line) if e.kind != "line"]
    assert kinds == [("batch", (("setup-ub.tp2", 0), ("setup-ub.tp2", 10)))]
    assert reader.asking
    question = reader.question()
    assert question.text == "Which portraits?\n1] classic\n2] new"
    assert question.batch == (("setup-ub.tp2", 0), ("setup-ub.tp2", 10))
    assert not reader.asking and reader.question() is None


def test_mod_installer_12s_one_component_lines_and_ticks_are_read_too():
    """12.1.1, a player's own on Windows or macOS: `Component { ... }`, one
    at a time, and a row of dots logged each tick while WeiDU works."""
    reader = OutputReader()
    events = []
    for line in [
            ("[2026-10-24T00:00:00Z INFO  mod_installer::installers] Installing mod "
             'Component { tp_file: "ASKER.TP2", name: "asker", lang: "0", component: "3", '
             'component_name: "Asks", sub_component: "", version: "1" }\n'),
            "[2026-10-24T00:00:00Z INFO  mod_installer::weidu] \n",
            "[2026-10-24T00:00:00Z INFO  mod_installer::weidu] ...\n"]:
        events += reader.feed(line)
    assert [(e.kind, e.batch) for e in events if e.kind == "batch"] == \
        [("batch", (("asker.tp2", 3),))]
    assert [e for e in events if e.kind == "line" and set(e.text.split("] ")[-1]) <= {"."}] \
        == []                                    # the ticks say nothing


# ---------------------------------------------------------- the install
@pytest.fixture
def setup(tmp_path):
    """Two fresh games, the staged mods, the planned logs and the programs."""
    games = {}
    for name in ("BGEE", "EET"):
        folder = tmp_path / name.lower()
        folder.mkdir()
        (folder / "chitin.key").write_text("")
        games[name] = str(folder)
    mods = tmp_path / "mods"
    for folder in ("eet", "ub", "vienxay"):
        (mods / folder).mkdir(parents=True)
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "WeiDU-BGEE.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "~VIENXAY/VIENXAY.TP2~ #0 #0 // Vienxay NPC: 1.67 // @wlb-inputs: 1,\n")
    (plan / "WeiDU.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "~EET/EET.TP2~ #0 #0 // EET core (resource importation): v14.0\n"
        "~UB/SETUP-UB.TP2~ #0 #0 // Restorations: v30\n")
    if os.name == "nt":
        program = tmp_path / "mod_installer.cmd"
        program.write_text(f'@"{sys.executable}" "{FAKE}" %*\r\n')
    else:
        program = tmp_path / "mod_installer"
        program.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
        program.chmod(0o755)
    return {"games": games, "mods": str(mods), "plan": str(plan),
            "program": str(program), "transcript": tmp_path / "answers.txt"}


def run(setup, monkeypatch, questions, ask=lambda _q, _b: None, **extra):
    import json
    monkeypatch.setenv("FAKE_QUESTIONS", json.dumps(questions))
    monkeypatch.setenv("FAKE_TRANSCRIPT", str(setup["transcript"]))
    events = []
    install = api.start_install(setup["plan"], setup["games"], setup["mods"],
                                setup["program"], weidu=setup["program"], ask=ask,
                                on_event=events.append, quiet_s=0.3, **extra)
    return install, events


def read(*path):
    from pathlib import Path
    file = Path(*path)
    return file.read_text(encoding="utf-8") if file.exists() else ""


def answers(setup):
    return setup["transcript"].read_text(encoding="utf-8").splitlines() if setup["transcript"].exists() else []


def test_eet_is_installed_answering_each_question_from_where_it_should(setup, monkeypatch):
    asked = []
    install, events = run(setup, monkeypatch, {
        "vienxay.tp2#0": ["Choose one", "Press Enter"],
        "eet.tp2#0": [EET_QUESTION],
        "setup-ub.tp2#0": ["Restore the tavern? [y]es or [n]o"]},
        ask=lambda question, batch: asked.append((question, batch)) or "y")
    outcome = install.run()
    assert outcome.ok, [e.text for e in events]
    assert answers(setup) == ["1", "", setup["games"]["BGEE"], "y"]
    assert [a.source for a in outcome.answered] == ["recorded", "recorded", "EET", "player"]
    # the player was asked only what nothing recorded, with its component
    # the question comes with WeiDU's lines before it, as mod_installer sends it
    assert [(question_line(q), b) for q, b in asked] == \
        [("Restore the tavern? [y]es or [n]o", (("setup-ub.tp2", 0),))]
    assert "Installing [SETUP-UB.TP2 component 0]" in asked[0][0]
    # each game's WeiDU.log now names what went in, the recorded answers not copied
    eet_log = read(setup["games"]["EET"], "WeiDU.log")
    assert "EET core" in eet_log and "SETUP-UB.TP2" in eet_log
    assert "@wlb-inputs" not in read(setup["games"]["BGEE"], "WeiDU.log")
    assert [e.batch for e in events if e.kind == "batch"] == [
        (("vienxay.tp2", 0),), (("eet.tp2", 0),), (("setup-ub.tp2", 0),)]


def test_a_question_the_player_cancels_stops_the_install(setup, monkeypatch):
    install, _events = run(setup, monkeypatch, {"eet.tp2#0": ["Something unknown?"]})
    outcome = install.run()
    assert outcome.cancelled and not outcome.ok
    assert "SETUP-UB" not in read(setup["games"]["EET"], "WeiDU.log")       # never reached


def test_cancel_from_another_thread_stops_it(setup, monkeypatch):
    monkeypatch.setenv("FAKE_SLOW", "30")
    install, events = run(setup, monkeypatch, {}, grace_s=2.0)
    timer = threading.Timer(0.5, install.cancel)
    timer.start()
    outcome = install.run()
    timer.cancel()
    assert outcome.cancelled and outcome.returncode is not None
    assert any(e.kind == "batch" for e in events)


def test_a_failed_component_is_a_failed_install(setup, monkeypatch):
    monkeypatch.setenv("FAKE_FAIL", "eet.tp2#0")
    install, events = run(setup, monkeypatch, {})
    outcome = install.run()
    assert outcome.returncode == 1 and not outcome.ok and not outcome.cancelled
    assert any("not installed due to errors" in e.text for e in events if e.kind == "line")


# ------------------------------------------------------- before it starts
def test_what_stops_it_before_it_starts_is_named(setup, tmp_path):
    games, program = setup["games"], setup["program"]
    assert preflight(games, setup["mods"], program, program) == []
    os.remove(os.path.join(games["BGEE"], "chitin.key"))
    with open(os.path.join(games["EET"], "WeiDU.log"), "w") as fh:
        fh.write("~EET/EET.TP2~ #0 #0 // EET core\n")
    problems = preflight(games, str(tmp_path / "nowhere"), program, str(tmp_path / "weidu"))
    assert any("BGEE: no chitin.key" in p for p in problems)
    assert any("EET:" in p and "already has mods" in p for p in problems)
    assert any("does not exist - download first" in p for p in problems)
    assert any(p.startswith("WeiDU is not a program here") for p in problems)
    assert not any("already has mods" in p for p in preflight(
        games, setup["mods"], program, program, allow_existing=True))
    with pytest.raises(ConfigError, match="no chitin.key"):
        api.start_install(setup["plan"], games, setup["mods"], program, program,
                          ask=lambda *_a: None)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux's case rule")
def test_a_mixed_case_mod_folder_is_refused_on_linux(setup):
    os.rename(os.path.join(setup["mods"], "ub"), os.path.join(setup["mods"], "UB"))
    assert any("lower-case on Linux: UB" in p for p in preflight(
        setup["games"], setup["mods"], setup["program"], setup["program"]))


def test_the_command_is_the_one_the_scripts_run(setup):
    argv = command(setup["plan"], setup["games"], "/mods", "/mi", "/weidu", "it_IT")
    assert argv[:2] == ["/mi", "eet"]
    assert argv[argv.index("--bg1-log-file") + 1].endswith("WeiDU-BGEE.log")
    assert argv[argv.index("--bg2-game-directory") + 1] == setup["games"]["EET"]
    assert argv[-8:] == ["--mod-directories", "/mods", "--weidu-binary", "/weidu",
                         "--language", "it_IT", "--download=false",
                         "--skip-installed=false"]
    one = command(setup["plan"], {"BG2EE": "/g"}, "/mods", "/mi", "/weidu")
    assert one[:6] == ["/mi", "normal", "--game-directory", "/g", "--log-file",
                       os.path.join(setup["plan"], "WeiDU.log")]


# ------------------------------------------------ reviews of the design
def alive(pid):
    """Whether process `pid` is still running (a zombie counts as gone)."""
    if os.name == "nt":
        import subprocess
        listed = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                capture_output=True, text=True, check=False).stdout
        return str(pid) in listed
    # gone between the open and the read (ESRCH), or its pid taken by another
    # program on a busy runner: not the child (both seen on CI, PR #115)
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            if fh.read().split(")")[-1].split()[0] == "Z":
                return False
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return b"SIG_IGN" in fh.read()           # the IGNORING child's own code
    except OSError:
        return False


def test_cancel_stops_what_mod_installer_started_too(setup, monkeypatch, tmp_path):
    """WeiDU, mod_installer's child, must not go on writing into the game."""
    import time
    pidfile = tmp_path / "weidu.pid"
    monkeypatch.setenv("FAKE_SLOW", "30")
    monkeypatch.setenv("FAKE_GRANDCHILD", str(pidfile))
    install, _events = run(setup, monkeypatch, {}, grace_s=1.0)
    timer = threading.Timer(1.0, install.cancel)
    timer.start()
    outcome = install.run()
    timer.cancel()
    assert outcome.cancelled
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 5
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not alive(pid)


def test_an_ended_install_does_not_wait_on_what_it_left_running(setup, monkeypatch, tmp_path):
    """
    mod_installer exits, something it started still holds its output (review
    of #83): the run ends soon after - not when that lets go - and stops it.
    """
    import time
    pidfile = tmp_path / "weidu.pid"
    monkeypatch.setenv("FAKE_GRANDCHILD", str(pidfile))
    monkeypatch.setenv("FAKE_EXIT_EARLY", "1")
    install, events = run(setup, monkeypatch, {}, grace_s=1.0, drain_s=0.5)
    started = time.monotonic()
    outcome = install.run()
    assert time.monotonic() - started < 15
    assert outcome.returncode == 0 and not outcome.cancelled
    assert any("still running: stopped" in e.text for e in events)
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 5
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not alive(pid)


def test_mod_installer_gets_the_child_environment(setup, monkeypatch):
    """A frozen bundle's library path is not handed down (childenv, #70)."""
    from iemod_fetch import install_run
    seen = []

    def marked(extra=None):
        seen.append(dict(extra or {}))
        return dict(os.environ, IEMOD_CHILD_ENV="cleaned", **(extra or {}))
    monkeypatch.setattr(install_run, "child_env", marked)
    monkeypatch.setenv("FAKE_ECHO_ENV", "IEMOD_CHILD_ENV")
    install, events = run(setup, monkeypatch, {})
    assert install.run().ok
    assert seen[0] == {"RUST_LOG": "info"}
    assert any(e.text.endswith("IEMOD_CHILD_ENV=cleaned") for e in events)


def test_mod_installers_options_never_come_from_the_players_environment(setup, monkeypatch):
    """clap reads NEW_EET_DIR, OVERWRITE, DOWNLOAD... from the environment as
    options (review of #86): none reaches mod_installer; the rest does."""
    monkeypatch.setenv("NEW_EET_DIR", "/somewhere/else")
    monkeypatch.setenv("overwrite", "true")              # Windows names are not case-sensitive
    monkeypatch.setenv("IEMOD_KEEP_ME", "kept")
    for name, expected in (("NEW_EET_DIR", ""), ("IEMOD_KEEP_ME", "kept")):
        monkeypatch.setenv("FAKE_ECHO_ENV", name)
        install, events = run(setup, monkeypatch, {}, allow_existing=True)
        assert install.run().ok
        assert any(e.text.endswith(f"{name}={expected}") for e in events), name
    from iemod_fetch import install_run
    env = install_run.mod_installer_env()
    assert "overwrite" not in env and "OVERWRITE" not in env and env["RUST_LOG"] == "info"


def test_answers_that_run_out_are_asked_never_left_blank(setup, monkeypatch):
    from pathlib import Path
    Path(setup["plan"], "WeiDU-BGEE.log").write_text(
        "~VIENXAY/VIENXAY.TP2~ #0 #0 // Vienxay NPC: 1.67 // @wlb-inputs: 1\n")
    asked = []
    install, _events = run(setup, monkeypatch, {
        "vienxay.tp2#0": ["Choose one", "And another"],
        "eet.tp2#0": [EET_QUESTION]},
        ask=lambda question, batch: asked.append(question) or "2")
    outcome = install.run()
    assert outcome.ok
    assert [question_line(q) for q in asked] == ["And another"]
    assert answers(setup)[:2] == ["1", "2"]
    assert [a.source for a in outcome.answered][:2] == ["recorded", "player"]


def test_folders_with_spaces_and_accents_reach_it_whole(setup, monkeypatch, tmp_path):
    """The command is a list, never a shell line; an answer goes as UTF-8."""
    for name in ("BGEE", "EET"):
        folder = tmp_path / f"Baldur's Gate {name} – città"
        os.rename(setup["games"][name], folder)
        setup["games"][name] = str(folder)
    install, _events = run(setup, monkeypatch, {"eet.tp2#0": [EET_QUESTION]})
    outcome = install.run()
    assert outcome.ok
    assert answers(setup) == [setup["games"]["BGEE"]]
    assert "SETUP-UB.TP2" in read(setup["games"]["EET"], "WeiDU.log")


def test_an_accented_bgee_folder_is_not_refused(setup, tmp_path):
    """
    #83 refused one on Windows until it was measured; item 22b measured it
    (tests/test_real_mod_installer.py, on CI's Windows runner): the real
    WeiDU v251 opens a folder with accents given as UTF-8 through
    mod_installer. ADR-0046.
    """
    from iemod_fetch import install_run
    folder = tmp_path / "Baldur's Gate – città"
    os.rename(setup["games"]["BGEE"], folder)
    setup["games"]["BGEE"] = str(folder)
    args = (setup["games"], setup["mods"], setup["program"], setup["program"])
    assert install_run.preflight(*args) == []


# ------------------------------------------------------------ resuming (item 23)
def lines(path):
    from pathlib import Path
    return [line for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.startswith("~")]


def test_a_stopped_eet_install_resumes_with_only_what_is_left(setup, monkeypatch):
    """The fake fails at UB: BG:EE's part and EET's core are in. Resuming
    runs the EET game alone, with UB only - nothing installed twice."""
    monkeypatch.setenv("FAKE_FAIL", "setup-ub.tp2#0")
    install, _events = run(setup, monkeypatch, {"eet.tp2#0": [EET_QUESTION]})
    assert not install.run().ok
    progress = api.install_progress(setup["plan"], setup["games"])
    assert progress["state"] == "partial" and (progress["done"], progress["total"]) == (2, 3)
    assert [p["next"] for p in progress["phases"]] == [None, "ub/setup-ub.tp2 #0"]

    monkeypatch.delenv("FAKE_FAIL")
    install, events = run(setup, monkeypatch, {}, resume=True)
    assert install.argv[1] == "normal" and setup["games"]["EET"] in install.argv
    assert setup["games"]["BGEE"] not in install.argv
    assert install.run().ok
    assert [line.split("~")[1] for line in lines(os.path.join(setup["games"]["EET"],
                                                               "WeiDU.log"))] == \
        ["EET/EET.TP2", "UB/SETUP-UB.TP2"]
    assert len(lines(os.path.join(setup["games"]["BGEE"], "WeiDU.log"))) == 1
    assert api.install_progress(setup["plan"], setup["games"])["state"] == "finished"


def test_resuming_bgee_unfinished_runs_eet_mode_with_bgees_rest(setup, monkeypatch):
    from pathlib import Path
    Path(setup["plan"], "WeiDU-BGEE.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "~VIENXAY/VIENXAY.TP2~ #0 #0 // Vienxay NPC: 1.67\n"
        "~VIENXAY/VIENXAY.TP2~ #0 #1 // Vienxay banter\n")
    Path(setup["games"]["BGEE"], "WeiDU.log").write_text(
        "~VIENXAY/VIENXAY.TP2~ #0 #0 // Vienxay NPC: 1.67\n")
    install, _events = run(setup, monkeypatch, {"eet.tp2#0": [EET_QUESTION]}, resume=True)
    assert install.argv[1] == "eet"
    rest = install.argv[install.argv.index("--bg1-log-file") + 1]
    assert [line.split("#")[-1].split()[0] for line in lines(rest)] == ["1"]
    assert install.run().ok
    assert len(lines(os.path.join(setup["games"]["BGEE"], "WeiDU.log"))) == 2


def test_a_game_that_is_not_the_plans_beginning_is_not_resumed(setup, monkeypatch):
    from pathlib import Path
    Path(setup["games"]["BGEE"], "WeiDU.log").write_text("~OTHER/OTHER.TP2~ #0 #0 // x\n")
    progress = api.install_progress(setup["plan"], setup["games"])
    assert progress["state"] == "mismatch" and "not this plan's install" in progress["problem"]
    with pytest.raises(ConfigError, match="cannot resume: .*restore the backup"):
        run(setup, monkeypatch, {}, resume=True)


def test_a_finished_install_has_nothing_to_resume(setup, monkeypatch):
    install, _events = run(setup, monkeypatch, {"eet.tp2#0": [EET_QUESTION]})
    assert install.run().ok
    with pytest.raises(ConfigError, match="nothing to resume"):
        run(setup, monkeypatch, {}, resume=True)


def test_a_fresh_game_resumes_as_a_plain_install(setup, monkeypatch):
    assert api.install_progress(setup["plan"], setup["games"])["state"] == "fresh"
    install, _events = run(setup, monkeypatch, {"eet.tp2#0": [EET_QUESTION]}, resume=True)
    assert install.argv[1] == "eet" and install.run().ok


def test_an_eet_game_with_components_while_bgees_part_is_unfinished_is_not_resumed(
        setup, monkeypatch):
    """EET's log is only begun once BG:EE's part is whole (review of item 23)."""
    from pathlib import Path
    Path(setup["plan"], "WeiDU-BGEE.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "~VIENXAY/VIENXAY.TP2~ #0 #0 // Vienxay NPC: 1.67\n"
        "~VIENXAY/VIENXAY.TP2~ #0 #1 // Vienxay banter\n")
    Path(setup["games"]["BGEE"], "WeiDU.log").write_text(
        "~VIENXAY/VIENXAY.TP2~ #0 #0 // Vienxay NPC: 1.67\n")
    Path(setup["games"]["EET"], "WeiDU.log").write_text("~EET/EET.TP2~ #0 #0 // EET core\n")
    progress = api.install_progress(setup["plan"], setup["games"])
    assert progress["state"] == "mismatch"
    assert progress["problem"] == ("WeiDU.log: the game has 1 component(s) while "
                                   "WeiDU-BGEE.log is not finished (1 of 2 in): the game "
                                   "is not this plan's install")
    with pytest.raises(ConfigError, match="cannot resume: WeiDU.log: the game has 1"):
        run(setup, monkeypatch, {}, resume=True)


def test_mod_installer_is_told_not_to_skip(setup, monkeypatch):
    """Its skip reads `weidu.log` in lower case (16.0.0): what is left is ours."""
    install, _events = run(setup, monkeypatch, {"eet.tp2#0": [EET_QUESTION]})
    assert "--skip-installed=false" in install.argv


def test_a_component_stopped_half_way_is_not_resumed(setup, monkeypatch):
    """WeiDU's uninstall record of the next component is in the game while its
    log line is not: a Cancel inside it (measured with WeiDU 251). Installing
    it again would back up its own leftovers as the game's originals."""
    from pathlib import Path
    Path(setup["plan"], "WeiDU-BGEE.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "~SLOW/SLOW.TP2~ #0 #0 // Quick\n~SLOW/SLOW.TP2~ #0 #1 // Slow\n")
    game = Path(setup["games"]["BGEE"])
    (game / "WeiDU.log").write_text("~SLOW/SLOW.TP2~ #0 #0 // Quick\n")
    (game / "SLOW").mkdir()
    (game / "SLOW" / "slow.tp2").write_text("BACKUP ~slow/Backup~\nAUTHOR ~t~\n")
    progress = api.install_progress(setup["plan"], setup["games"])
    assert progress["state"] == "partial"                 # no record: resumable
    (game / "SLOW" / "Backup" / "1").mkdir(parents=True)
    (game / "SLOW" / "Backup" / "1" / "UNINSTALL.1").write_text("override/first.txt\n")
    progress = api.install_progress(setup["plan"], setup["games"])
    assert progress["state"] == "mismatch"
    assert "slow/slow.tp2 #1 stopped half-way" in progress["problem"]
    assert "UNINSTALL.1" in progress["problem"]
    with pytest.raises(ConfigError, match="stopped half-way.*restore the backup"):
        run(setup, monkeypatch, {}, resume=True)


def test_resuming_the_eet_game_alone_still_answers_eets_bgee_question(setup, monkeypatch):
    """BG:EE's part is in, EET's core failed (WeiDU undid it): the resume runs
    the EET game alone, and EET's question still gets BG:EE's folder, not the
    player (review of #89)."""
    monkeypatch.setenv("FAKE_FAIL", "eet.tp2#0")
    install, _events = run(setup, monkeypatch, {"eet.tp2#0": [EET_QUESTION]})
    assert not install.run().ok
    progress = api.install_progress(setup["plan"], setup["games"])
    assert [p["next"] for p in progress["phases"]] == [None, "eet/eet.tp2 #0"]

    monkeypatch.delenv("FAKE_FAIL")
    asked = []
    install, events = run(setup, monkeypatch, {"eet.tp2#0": [EET_QUESTION]},
                          ask=lambda question, batch: asked.append(question), resume=True)
    assert install.argv[1] == "normal" and install.bgee_dir == setup["games"]["BGEE"]
    outcome = install.run()
    assert outcome.ok, [e.text for e in events]
    assert asked == [] and [a.source for a in outcome.answered] == ["EET"]


def test_a_backup_folder_named_with_mod_folder_is_found(setup, monkeypatch):
    from pathlib import Path
    Path(setup["plan"], "WeiDU-BGEE.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #0 // a\n~MYMOD/SETUP-MYMOD.TP2~ #0 #1 // b\n")
    game = Path(setup["games"]["BGEE"])
    (game / "WeiDU.log").write_text("~MYMOD/SETUP-MYMOD.TP2~ #0 #0 // a\n")
    (game / "MyMod").mkdir()
    (game / "MyMod" / "setup-mymod.tp2").write_text("BACKUP ~%MOD_FOLDER%/saved~\n")
    (game / "MyMod" / "saved" / "1").mkdir(parents=True)
    (game / "MyMod" / "saved" / "1" / "UNINSTALL.1").write_text("override/x\n")
    progress = api.install_progress(setup["plan"], setup["games"])
    assert progress["state"] == "mismatch" and "stopped half-way" in progress["problem"]


# ------------------------------------- what was answered (item 63)
# The fake sends a question as mod_installer does: WeiDU's last 10 lines -
# its version, "Installing [x] [vN]", earlier questions - then the question.
def with_answers(setup, answers_text):
    from pathlib import Path
    log = Path(setup["plan"], "WeiDU.log")
    log.write_text(log.read_text().replace(
        "Restorations: v30", f"Restorations: v30 // @wlb-inputs: {answers_text}"))


def test_recorded_answers_go_in_order_whatever_the_question_says(setup, monkeypatch):
    """Fourth review of #98: Tweaks Anthology #3210 asks "between 6 and 15,
    or 0 for no minimum" and takes 0 - its tp2 decides, not its text. The
    recorded answers go in as recorded; nobody is asked."""
    with_answers(setup, "0,y")
    asked = []
    install, _events = run(setup, monkeypatch, {
        "eet.tp2#0": [EET_QUESTION],
        "setup-ub.tp2#0": [
            "Select a minimum STRENGTH value, between 6 and 15, or 0 for no minimum:",
            "Restore the tavern? [y]es or [n]o"]},
        ask=lambda question, batch: asked.append(question) or "x")
    outcome = install.run()
    assert outcome.ok and asked == []
    assert answers(setup)[-2:] == ["0", "y"]


def test_what_was_answered_is_recorded_and_never_read_back(setup, monkeypatch):
    """answers.json says what each question got and from where - for the
    player and a bug report; a later install decides as if it were not
    there."""
    import json
    from pathlib import Path
    with_answers(setup, "y")
    questions = {"eet.tp2#0": [EET_QUESTION],
                 "setup-ub.tp2#0": ["Restore the tavern? [y]es or [n]o"]}
    install, _events = run(setup, monkeypatch, questions)
    assert install.run().ok
    kept = json.loads(Path(setup["plan"], "answers.json").read_text())
    assert kept["v"] == 1
    assert kept["answered"][-1] == {"question": "Restore the tavern? [y]es or [n]o",
                                    "answer": "y", "source": "recorded"}
    assert kept["answered"][0]["source"] == "EET"
    Path(setup["plan"], "answers.json").write_text(json.dumps(
        {"v": 1, "answered": [{"question": "Restore the tavern? [y]es or [n]o",
                               "answer": "n", "source": "player"}]}))
    for game in setup["games"].values():
        for name in os.listdir(game):
            if name != "chitin.key":
                os.remove(os.path.join(game, name))
    install, _events = run(setup, monkeypatch, questions)
    assert install.run().ok and answers(setup)[-1] == "y"       # the log's, as before


def test_a_run_that_answers_nothing_leaves_no_earlier_record(setup, monkeypatch):
    import json
    from pathlib import Path
    Path(setup["plan"], "answers.json").write_text('{"v": 1, "answered": [{"answer": "old"}]}')
    install, _events = run(setup, monkeypatch, {})          # no question asked
    assert install.run().ok
    assert json.loads(Path(setup["plan"], "answers.json").read_text()) == \
        {"v": 1, "answered": []}


def test_a_run_that_cannot_start_leaves_no_earlier_record(setup, monkeypatch):
    """Review of #98: mod_installer that will not start (gone, not a
    program) still replaces the record of the run before."""
    import json
    from pathlib import Path
    Path(setup["plan"], "answers.json").write_text('{"v": 1, "answered": [{"answer": "old"}]}')
    install, _events = run(setup, monkeypatch, {})
    install.argv = [str(Path(setup["plan"], "no-such-program")), *install.argv[1:]]
    with pytest.raises(OSError):
        install.run()
    assert json.loads(Path(setup["plan"], "answers.json").read_text()) == \
        {"v": 1, "answered": []}


def test_batch_mode_from_the_environment_does_not_reach_mod_installer(monkeypatch):
    """One batch is one mod's consecutive components only while
    mod_installer's BATCH_MODE (clap reads it from the environment) is off;
    it is never passed on."""
    from iemod_fetch import install_run
    monkeypatch.setenv("BATCH_MODE", "true")
    monkeypatch.setenv("BATCH_SIZE", "50")
    env = install_run.mod_installer_env()
    assert not {"BATCH_MODE", "BATCH_SIZE"} & {key.upper() for key in env}


# ------------------------------------------- the game not running (item 67)
def test_a_game_in_use_stops_the_install_before_it_starts(setup):
    games, program = setup["games"], setup["program"]
    seen = []

    def in_use(folders):
        seen.append(folders)
        return ["EET: Baldur.exe is running from the game folder - close it first"]
    problems = preflight(games, setup["mods"], program, program, in_use=in_use)
    assert problems == ["EET: Baldur.exe is running from the game folder - close it first"]
    assert seen == [games]
    os.rename(games["BGEE"], games["BGEE"] + "-gone")              # only folders that exist
    preflight(games, setup["mods"], program, program, in_use=in_use)
    assert seen[-1] == {"EET": games["EET"]}


def test_a_game_started_during_the_install_is_said_once_not_stopped(setup, monkeypatch):
    import json

    from iemod_fetch import install_run
    monkeypatch.setenv("FAKE_QUESTIONS", json.dumps({}))
    monkeypatch.setenv("FAKE_TRANSCRIPT", str(setup["transcript"]))
    exe = os.path.join(setup["games"]["EET"], "Baldur.exe")
    tool = os.path.join(setup["games"]["EET"], "weidu.exe")        # this install's own WeiDU
    events = []
    install = install_run.start(setup["plan"], setup["games"], setup["mods"],
                                setup["program"], setup["program"], ask=lambda *_a: None,
                                on_event=events.append, quiet_s=0.3,
                                running=lambda: [(1, exe), (2, tool), (3, setup["program"])])
    install.tools = (*install.tools, tool)
    outcome = install.run()
    assert outcome.ok
    warnings = [e.text for e in events if e.kind == "line" and e.text.startswith("warning:")]
    assert warnings == [(f"warning: EET: {exe} (pid 1) is running from the game folder while it is "
                         "installed into - WeiDU fails if it cannot write dialog.tlk; close it")]
    assert len([e for e in events if e.kind == "batch"]) == 3      # every batch looked


# --------------------------------------- what each component came to (item 69)
def test_each_component_gets_a_result_and_results_json_is_written(setup, monkeypatch):
    """The fake writes no debug file: WeiDU.log alone says what went in."""
    import json
    from pathlib import Path
    install, _events = run(setup, monkeypatch, {"setup-ub.tp2#0": ["Restore? [y]es"]},
                           ask=lambda *_a: "y")
    outcome = install.run()
    assert outcome.ok
    got = [(x.key, x.status) for x in outcome.results]
    assert got == [(("vienxay.tp2", 0), "installed"), (("eet.tp2", 0), "installed"),
                   (("setup-ub.tp2", 0), "installed")]
    written = json.loads(Path(setup["plan"], "results.json").read_text())
    assert [c["status"] for c in written["components"]] == ["installed"] * 3
    assert all("no word" in c["note"] for c in written["components"])


def test_a_failed_component_and_what_follows_it(setup, monkeypatch):
    monkeypatch.setenv("FAKE_FAIL", "eet.tp2#0")
    install, _events = run(setup, monkeypatch, {})
    outcome = install.run()
    got = {x.key: x.status for x in outcome.results}
    assert got[("vienxay.tp2", 0)] == "installed"
    assert got[("eet.tp2", 0)] == "not reached"       # no debug file: the log is all
    assert got[("setup-ub.tp2", 0)] == "not reached"


def test_a_run_that_cannot_start_leaves_no_earlier_results(setup, monkeypatch):
    import json
    from pathlib import Path
    Path(setup["plan"], "results.json").write_text('{"v": 1, "components": [1]}')
    install, _events = run(setup, monkeypatch, {})
    install.argv = [str(Path(setup["plan"], "no-such-program")), *install.argv[1:]]
    with pytest.raises(OSError):
        install.run()
    assert json.loads(Path(setup["plan"], "results.json").read_text()) == \
        {"v": 1, "components": []}


def test_the_phases_are_the_games_command_gives_mod_installer(setup):
    from iemod_fetch import install_run
    games, plan = setup["games"], setup["plan"]
    assert install_run.phases(plan, games) == [
        (os.path.join(plan, "WeiDU-BGEE.log"), games["BGEE"]),
        (os.path.join(plan, "WeiDU.log"), games["EET"])]
    assert install_run.phases(plan, {"BG2EE": games["EET"]}) == [
        (os.path.join(plan, "WeiDU.log"), games["EET"])]
    with pytest.raises(ConfigError, match="not BG2EE, IWDEE"):        # review of #109
        install_run.phases(plan, {"BG2EE": games["EET"], "IWDEE": games["BGEE"]})


def test_a_question_asked_again_gets_its_stored_answer_once(tmp_path):
    """Review of #111: a loop refusing the stored answer would get it again
    forever; the second time in a batch, the player answers."""
    from iemod_fetch.install_run import InstallRun
    asked = []
    run = InstallRun(["x"], [], cwd=str(tmp_path), ask=lambda q, b: asked.append(q) or "4",
                     expected={("a.tp2", 0): [("@1", "Please enter a number between 1 and 5:")]},
                     by_key={("a.tp2", 0): {"@1": "9"}})
    run.answers.start((("a.tp2", 0),))
    window = "Installing [A]\nPlease enter a number between 1 and 5:"
    assert run._by_question(window, (("a.tp2", 0),)) == ("9", "by question")
    assert run._by_question(window, (("a.tp2", 0),)) is None        # -> the player
    run.answers.start((("a.tp2", 0),))
    run._given = set()                     # a new batch: given again
    assert run._by_question(window, (("a.tp2", 0),)) == ("9", "by question")


def test_recorded_answers_of_another_tool_are_handed_out_in_order(tmp_path):
    """Review of #111: without this program's row keys an Orchestrator-style
    log (answers as asked, skipped ones left out) still goes in order."""
    from iemod_fetch.install_run import InstallRun
    log = tmp_path / "WeiDU.log"
    log.write_text("~A/A.TP2~ #0 #0 // a // @wlb-inputs: a1,a3\n")
    run = InstallRun(["x"], [str(log)], cwd=str(tmp_path), ask=lambda q, b: None,
                     expected={("a.tp2", 0): [("@1", "Please enter the first value:"),
                                              ("@2", "Do you want the optional part?"),
                                              ("@3", "Please enter the third value:")]})
    run.answers.start((("a.tp2", 0),))
    # @2 skipped this run: @3 comes second and gets a3, not "nothing"
    assert run._by_question("Please enter the first value:", (("a.tp2", 0),)) == ("a1", "recorded")
    assert run._by_question("Please enter the third value:", (("a.tp2", 0),)) == ("a3", "recorded")


def test_a_long_silence_is_said_never_acted_on_and_measured(setup, monkeypatch):
    """ADR-0049 point 4: no output for longer than the threshold is said once,
    with the last lines; the install goes on to its end; each batch's longest
    silence is recorded."""
    import json
    monkeypatch.setenv("FAKE_SLOW", "1.5")
    install, events = run(setup, monkeypatch, {}, silent_s=0.7)
    outcome = install.run()
    assert outcome.ok                                           # never stopped
    said = [e.text for e in events if e.kind == "watchdog"]
    assert said and all(text.startswith("No output for") for text in said)
    assert "Nothing is stopped" in said[0] and "The last lines:" in said[0]
    assert len(said) == len(outcome.silences)                   # once per silence
    assert all(seconds >= 1.4 for _batch, seconds in outcome.silences)
    with open(os.path.join(setup["plan"], "results.json"), encoding="utf-8") as fh:
        kept = json.load(fh)
    assert len(kept["silences"]) == 3 and kept["silences"][0]["seconds"] >= 1.4


def test_a_silence_after_a_question_mod_installer_does_not_ask_says_so(tmp_path):
    from iemod_fetch.install_run import InstallRun
    run_ = InstallRun(["x"], [], cwd=str(tmp_path), ask=lambda q, b: None,
                      expected={("a.tp2", 0): [("@1", "How many extra kits should be installed?")]})
    text = run_._silence_text(700, ["Installing [A]", "How many extra kits should be installed?"],
                              (("a.tp2", 0),))
    assert text.startswith("No output for 12 minute(s)")
    assert "does not put to anyone" in text and "mod_installer's timeout" in text


TICKS_12 = r"""
import sys, time
def log(text):
    print(f"[2026-10-24T00:00:00Z INFO  mod_installer::installers] {text}", flush=True)
log('Installing mod Component { tp_file: "A.TP2", name: "A", lang: "0", component: "0" }')
print("How many extra kits should be installed?", flush=True)
for i in range(40):                       # 12.1.1's row of dots while WeiDU is silent,
    log("." * (i + 1)); time.sleep(0.04)   # faster than the queue's 0.1 s wait
"""


def test_mod_installer_12s_dots_are_not_output(tmp_path):
    """Review of #115: 12.1.1 prints dots exactly while WeiDU is silent - they
    neither keep the watchdog quiet nor push the question out of the last
    lines, nor spoil the measured silence."""
    import sys
    from iemod_fetch.install_run import InstallRun
    events = []
    run_ = InstallRun([sys.executable, "-c", TICKS_12], [], cwd=str(tmp_path),
                      ask=lambda q, b: None, on_event=events.append, quiet_s=0.2,
                      silent_s=0.6,
                      expected={("a.tp2", 0): [("@1", "How many extra kits should be installed?")]})
    outcome = run_.run()
    said = [e.text for e in events if e.kind == "watchdog"]
    assert len(said) == 1 and "does not put to anyone" in said[0], [e.text for e in events]
    assert "...." not in said[0].split("The last lines:")[1]
    assert outcome.silences and outcome.silences[0][1] >= 1.4


ANSWERED_THEN_SILENT = r"""
import sys, time
def log(text):
    print(f"[2026-10-24T00:00:00Z INFO  mod_installer::runner] {text}", flush=True)
log('Installing mod WeiduBatchedComponents([WeiduComponent { tp_file: "A.TP2", name: "A", lang: "0", component: "0" }])')
log("User Input required"); log("Question is")
log("Please enter the number of extra kits to install:")
sys.stdin.readline()
time.sleep(1.5)                            # works silently after the answer
"""


KITS_QUESTION = "Please enter the number of extra kits to install:"


def test_a_silence_after_an_answered_question_is_not_that_question_waiting(tmp_path):
    """Review of #115: the answered question's window is not the last output;
    a silence after it says nothing of a question nobody is asked."""
    import sys
    from iemod_fetch.install_run import InstallRun
    events = []
    run_ = InstallRun([sys.executable, "-c", ANSWERED_THEN_SILENT], [], cwd=str(tmp_path),
                      ask=lambda q, b: "3", on_event=events.append, quiet_s=0.2, silent_s=0.6,
                      expected={("a.tp2", 0): [("@1", KITS_QUESTION)]})
    run_.run()
    said = [e.text for e in events if e.kind == "watchdog"]
    assert len(said) == 1 and "does not put to anyone" not in said[0]
    assert "Nothing is stopped" in said[0]


ASKED_THEN_CANCELLED = r"""
import sys
def log(text):
    print(f"[2026-10-24T00:00:00Z INFO  mod_installer::runner] {text}", flush=True)
log('Installing mod WeiduBatchedComponents([WeiduComponent { tp_file: "A.TP2", name: "A", lang: "0", component: "0" }])')
log("User Input required"); log("Question is"); log("Please choose one:")
sys.stdin.readline()
"""


def test_the_players_time_at_a_cancelled_question_is_not_silence(tmp_path):
    """Third review of #115: the time a question waits on the player is not
    counted, also when the player cancels it."""
    import sys
    import time
    from iemod_fetch.install_run import InstallRun
    run_ = InstallRun([sys.executable, "-c", ASKED_THEN_CANCELLED], [], cwd=str(tmp_path),
                      ask=lambda q, b: time.sleep(1.5) or None, quiet_s=0.2, grace_s=1.0)
    outcome = run_.run()
    assert outcome.cancelled
    assert outcome.silences and outcome.silences[0][1] < 1.0
