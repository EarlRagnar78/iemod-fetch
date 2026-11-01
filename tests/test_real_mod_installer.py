"""
The install the wizard runs, with the REAL mod_installer driving the REAL
WeiDU (ADR-0045): a synthetic BG2:EE folder (test_real_weidu.make_game), a
test mod whose tp2 asks two questions, and the planned log recording their
answers as `// @wlb-inputs:`. The claim: mod_installer's question reaches
this program, the recorded answers go back in order, and WeiDU installs the
component with them.

Opt-in: IEMOD_MOD_INSTALLER=/path/to/mod_installer (16.0.0, built from
source) and IEMOD_WEIDU=/path/to/weidu.
"""
import os

import pytest

from iemod_fetch import api

MOD_INSTALLER = os.environ.get("IEMOD_MOD_INSTALLER", "")
WEIDU = os.environ.get("IEMOD_WEIDU", "")
if os.environ.get("IEMOD_REQUIRE_REAL") and not (os.path.isfile(MOD_INSTALLER)
                                                  and os.path.isfile(WEIDU)):
    raise RuntimeError("IEMOD_REQUIRE_REAL is set but IEMOD_MOD_INSTALLER or IEMOD_WEIDU "
                       "is not a file")
pytestmark = pytest.mark.skipif(
    not (os.path.isfile(MOD_INSTALLER) and os.path.isfile(WEIDU)),
    reason="real mod_installer and WeiDU not given (IEMOD_MOD_INSTALLER, IEMOD_WEIDU)")

ASKER = """BACKUP ~asker/backup~
AUTHOR ~iemod-fetch test~
VERSION ~1~

BEGIN ~Asks two things~
PRINT ~Please enter the first answer:~
ACTION_READLN first
PRINT ~Please enter the second answer:~
ACTION_READLN second
APPEND_OUTER ~asker-answers.txt~ ~%first% %second%~
"""


def test_the_real_mod_installer_asks_and_gets_the_recorded_answers(tmp_path):
    from test_real_weidu import make_game
    game = tmp_path / "bg2ee"
    make_game(str(game), "BG2EE")
    mods = tmp_path / "mods"
    (mods / "asker").mkdir(parents=True)
    (mods / "asker" / "asker.tp2").write_text(ASKER)
    (game / "asker-answers.txt").write_text("")              # APPEND_OUTER needs it there
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "// The top of the file is the 'oldest' mod\n"
        "// ~TP2_File~ #language_number #component_number // [Subcomponent Name -> ] "
        "Component Name [ : Version]\n"
        "~ASKER/ASKER.TP2~ #0 #0 // Asks two things: 1 // @wlb-inputs: hello,world\n")
    lines, asked = [], []
    install = api.start_install(str(plan), {"BG2EE": str(game)}, str(mods), MOD_INSTALLER,
                                WEIDU, ask=lambda q, b: asked.append(q) or None,
                                on_event=lambda e: lines.append(e.text))
    outcome = install.run()
    transcript = "\n".join(lines)
    assert outcome.ok, transcript
    assert asked == [], transcript
    assert [a.source for a in outcome.answered] == ["recorded", "recorded"], transcript
    assert (game / "asker-answers.txt").read_text().split() == ["hello", "world"]
    installed = (game / "WeiDU.log").read_text()
    assert "ASKER" in installed.upper()


ASKPATH = """BACKUP ~askpath/backup~
AUTHOR ~iemod-fetch test~
VERSION ~1~

BEGIN ~Asks a folder~
PRINT ~Please enter the full path to the folder:~
ACTION_READLN folder
ACTION_IF FILE_EXISTS ~%folder%/marker.txt~ THEN BEGIN
  APPEND_OUTER ~askpath-result.txt~ ~found~
END ELSE BEGIN
  APPEND_OUTER ~askpath-result.txt~ ~missing~
END
"""


# "città – über" fits Windows' ANSI code page (cp1252); "Игры ゲーム" does
# not: a program opening paths with the ANSI API would fail only that one
# (review of #86). Both tell WeiDU's wide-API use apart from cp1252 luck.
@pytest.mark.parametrize("name", ["plain folder", "città – über", "Игры ゲーム"],
                         ids=["ascii", "cp1252", "beyond-cp1252"])
def test_a_folder_answered_through_mod_installer_reaches_weidu(tmp_path, name):
    """
    The measurement ADR-0046 records (review of #83): a folder given as an
    answer travels as UTF-8 through mod_installer (its read_line takes
    nothing else) to WeiDU, which opens it. EET's BG:EE folder travels so
    on Windows and macOS. ASCII is the control: when it fails, the setup
    does, not the encoding.
    """
    from test_real_weidu import make_game
    game = tmp_path / "bg2ee"
    make_game(str(game), "BG2EE")
    mods = tmp_path / "mods"
    (mods / "askpath").mkdir(parents=True)
    (mods / "askpath" / "askpath.tp2").write_text(ASKPATH)
    (game / "askpath-result.txt").write_text("")
    folder = tmp_path / name
    folder.mkdir()
    (folder / "marker.txt").write_text("here")
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        f"~ASKPATH/ASKPATH.TP2~ #0 #0 // Asks a folder: 1 // @wlb-inputs: {folder}\n",
        encoding="utf-8")
    lines = []
    install = api.start_install(str(plan), {"BG2EE": str(game)}, str(mods), MOD_INSTALLER,
                                WEIDU, ask=lambda q, b: None,
                                on_event=lambda e: lines.append(e.text))
    outcome = install.run()
    transcript = "\n".join(lines)
    assert outcome.ok, transcript
    assert [a.source for a in outcome.answered] == ["recorded"], transcript
    assert (game / "askpath-result.txt").read_text().split() == ["found"], transcript


TWO = """BACKUP ~two/backup~
AUTHOR ~iemod-fetch test~
VERSION ~1~

BEGIN ~First~
PRINT ~first~

BEGIN ~Second~
PRINT ~second~
"""


def test_a_resumed_install_installs_only_what_is_left(tmp_path):
    """Item 23, against the real programs: mod_installer's own skip reads
    `weidu.log` and, on Linux, would install the first component again
    (measured), so it is turned off; the resume hands it only the second."""
    from test_real_weidu import make_game
    game = tmp_path / "bg2ee"
    make_game(str(game), "BG2EE")
    mods = tmp_path / "mods"
    (mods / "two").mkdir(parents=True)
    (mods / "two" / "two.tp2").write_text(TWO)
    plan = tmp_path / "plan"
    plan.mkdir()

    def install(components, **extra):
        (plan / "WeiDU.log").write_text(
            "// Log of Currently Installed WeiDU Mods\n"
            + "".join(f"~TWO/TWO.TP2~ #0 #{n} // x\n" for n in components))
        lines = []
        outcome = api.start_install(str(plan), {"BG2EE": str(game)}, str(mods), MOD_INSTALLER,
                                    WEIDU, ask=lambda q, b: None,
                                    on_event=lambda e: lines.append(e.text), **extra).run()
        return outcome, "\n".join(lines)

    outcome, transcript = install([0])                       # stopped after the first
    assert outcome.ok, transcript
    (plan / "WeiDU.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "~TWO/TWO.TP2~ #0 #0 // x\n~TWO/TWO.TP2~ #0 #1 // x\n")
    assert api.install_progress(str(plan), {"BG2EE": str(game)})["done"] == 1
    outcome, transcript = install([0, 1], resume=True)
    assert outcome.ok, transcript
    assert "Installing [Second]" in transcript, transcript
    assert "Installing [First]" not in transcript, transcript       # not again
    installed = [line for line in (game / "WeiDU.log").read_text().splitlines()
                 if line.startswith("~")]
    assert [line.split("#")[-1].split()[0] for line in installed] == ["0", "1"]


SLOW = """BACKUP ~slow/backup~
AUTHOR ~iemod-fetch test~
VERSION ~1~

BEGIN ~Quick~
COPY ~slow/a.txt~ ~override/quick.txt~

BEGIN ~Slow~
COPY ~slow/a.txt~ ~override/marker.txt~
OUTER_SET n = 0
OUTER_WHILE n < 300000000 BEGIN OUTER_SET n = n + 1 END
"""


def test_a_component_cancelled_inside_is_not_resumed(tmp_path):
    """Item 23, review: a Cancel inside a component leaves its files in the
    game (marker.txt is the mod's now) and its uninstall record, not its
    WeiDU.log line. The resume refuses it rather than let WeiDU back up the
    mod's marker.txt as the game's."""
    import threading
    import time

    from test_real_weidu import make_game
    game = tmp_path / "bg2ee"
    make_game(str(game), "BG2EE")
    (game / "override" / "marker.txt").write_text("original\n")
    mods = tmp_path / "mods"
    (mods / "slow").mkdir(parents=True)
    (mods / "slow" / "slow.tp2").write_text(SLOW)
    (mods / "slow" / "a.txt").write_text("mod\n")
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text("// Log of Currently Installed WeiDU Mods\n"
                                    "~SLOW/SLOW.TP2~ #0 #0 // Quick\n"
                                    "~SLOW/SLOW.TP2~ #0 #1 // Slow\n")
    lines: list[str] = []
    install = api.start_install(str(plan), {"BG2EE": str(game)}, str(mods), MOD_INSTALLER,
                                WEIDU, ask=lambda q, b: None,
                                on_event=lambda e: lines.append(e.text))

    def cancel_inside():
        deadline = time.monotonic() + 60
        while not any("marker.txt" in line for line in lines) and time.monotonic() < deadline:
            time.sleep(0.05)
        install.cancel()
    threading.Thread(target=cancel_inside, daemon=True).start()
    assert not install.run().ok
    assert (game / "override" / "marker.txt").read_text() == "mod\n"     # left there
    progress = api.install_progress(str(plan), {"BG2EE": str(game)})
    assert progress["state"] == "mismatch", "\n".join(lines)
    assert "slow/slow.tp2 #1 stopped half-way" in progress["problem"]


BAD = """BACKUP ~bad/backup~
AUTHOR ~iemod-fetch test~

BEGIN ~Fine~
COPY ~bad/a.txt~ ~override/fine.txt~

BEGIN ~Broken~
COPY ~bad/a.txt~ ~override/marker.txt~
COPY ~bad/a.txt~ ~override/new.txt~
FAIL ~broken~
"""


def test_a_component_that_fails_is_undone_by_weidu_and_resumes(tmp_path):
    """The other way an install stops: WeiDU's own error. It undoes the
    component it was in - the game's file back, the new one gone, no
    uninstall record left - so the resume goes on from it."""
    from test_real_weidu import make_game
    game = tmp_path / "bg2ee"
    make_game(str(game), "BG2EE")
    (game / "override" / "marker.txt").write_text("original\n")
    mods = tmp_path / "mods"
    (mods / "bad").mkdir(parents=True)
    (mods / "bad" / "bad.tp2").write_text(BAD)
    (mods / "bad" / "a.txt").write_text("mod\n")
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text("// Log of Currently Installed WeiDU Mods\n"
                                    "~BAD/BAD.TP2~ #0 #0 // Fine\n"
                                    "~BAD/BAD.TP2~ #0 #1 // Broken\n")
    outcome = api.start_install(str(plan), {"BG2EE": str(game)}, str(mods), MOD_INSTALLER,
                                WEIDU, ask=lambda q, b: None).run()
    assert not outcome.ok
    assert (game / "override" / "marker.txt").read_text() == "original\n"
    assert not (game / "override" / "new.txt").exists()
    progress = api.install_progress(str(plan), {"BG2EE": str(game)})
    assert progress["state"] == "partial" and progress["phases"][0]["next"] == "bad/bad.tp2 #1"


TWO_QUESTIONS = """BACKUP ~twoq/backup~
AUTHOR ~iemod-fetch test~
VERSION ~v30~

BEGIN ~Asks a yes or no, then a number~
PRINT ~Restore the tavern? [y]es or [n]o~
ACTION_READLN first
PRINT ~Please select 1 or 2 and press Enter.~
ACTION_READLN second
APPEND_OUTER ~twoq-answers.txt~ ~%first% %second%~
"""


def test_recorded_answers_fit_the_real_window(tmp_path):
    """Item 63, review of #98: mod_installer sends each question with WeiDU's
    lines before it - here the yes/no before "select 1 or 2". The recorded
    answers both go in, nobody is asked, and what was answered is recorded."""
    import json

    from test_real_weidu import make_game
    game = tmp_path / "bg2ee"
    make_game(str(game), "BG2EE")
    (game / "twoq-answers.txt").write_text("")
    mods = tmp_path / "mods"
    (mods / "twoq").mkdir(parents=True)
    (mods / "twoq" / "twoq.tp2").write_text(TWO_QUESTIONS)
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "~TWOQ/TWOQ.TP2~ #0 #0 // Asks a yes or no, then a number // @wlb-inputs: y,2\n")
    lines, asked = [], []
    outcome = api.start_install(str(plan), {"BG2EE": str(game)}, str(mods), MOD_INSTALLER,
                                WEIDU, ask=lambda q, b: asked.append(q) or None,
                                on_event=lambda e: lines.append(e.text)).run()
    transcript = "\n".join(lines)
    assert outcome.ok and asked == [], transcript
    assert [a.source for a in outcome.answered] == ["recorded", "recorded"], transcript
    assert (game / "twoq-answers.txt").read_text().split() == ["y", "2"]
    assert any("Installing [" in a.question for a in outcome.answered), transcript
    kept = json.loads((plan / "answers.json").read_text())["answered"]
    assert [(k["question"], k["answer"]) for k in kept] == [
        ("Restore the tavern? [y]es or [n]o", "y"),
        ("Please select 1 or 2 and press Enter.", "2")]


MENU_AFTER = """BACKUP ~menu/backup~
AUTHOR ~iemod-fetch test~
VERSION ~v30~

BEGIN ~Asks with its menu after the question~
PRINT ~Which portraits?~
PRINT ~1] Original~
PRINT ~2] Select 5 or 10 random ones~
ACTION_READLN choice
APPEND_OUTER ~menu-answer.txt~ ~%choice%~
"""


def test_a_menu_after_the_question_does_not_limit_its_answer(tmp_path):
    """Second review of #98: mod_installer fires on "2] Select 5 or 10 random
    ones" (its choice words); the recorded "1" still goes in."""
    import json

    from test_real_weidu import make_game
    game = tmp_path / "bg2ee"
    make_game(str(game), "BG2EE")
    (game / "menu-answer.txt").write_text("")
    mods = tmp_path / "mods"
    (mods / "menu").mkdir(parents=True)
    (mods / "menu" / "menu.tp2").write_text(MENU_AFTER)
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "~MENU/MENU.TP2~ #0 #0 // Asks with its menu after the question // @wlb-inputs: 1\n")
    lines, asked = [], []
    outcome = api.start_install(str(plan), {"BG2EE": str(game)}, str(mods), MOD_INSTALLER,
                                WEIDU, ask=lambda q, b: asked.append(q) or None,
                                on_event=lambda e: lines.append(e.text)).run()
    transcript = "\n".join(lines)
    assert outcome.ok and asked == [], transcript
    assert (game / "menu-answer.txt").read_text().split() == ["1"]
    kept = json.loads((plan / "answers.json").read_text())["answered"]
    assert [(k["answer"], k["source"]) for k in kept] == [("1", "recorded")], kept


WARNS = """BACKUP ~warns/backup~
AUTHOR ~iemod-fetch test~
VERSION ~2~

BEGIN ~One~
COPY ~warns/f.txt~ ~override/one.txt~

BEGIN ~Careful~
COPY ~warns/f.txt~ ~override/careful.txt~
WARN ~careful~
"""


def test_each_component_gets_weidus_own_verdict(tmp_path):
    """Item 69 (ADR-0053): mod_installer starts WeiDU with --logapp --autolog,
    so every run appends to the game's WSETUP.DEBUG; each component's
    verdict is read from what this install appended, and held to WeiDU.log."""
    import json

    from test_real_weidu import make_game
    game = tmp_path / "bg2ee"
    make_game(str(game), "BG2EE")
    # an earlier install's debug file, with a verdict on a component this
    # install never reaches: not read, only what this install appends is
    (game / "WSETUP.DEBUG").write_text(
        f"WeiDU v 25100 Log\n\n {WEIDU} bad/bad.tp2 --force-install-list 2 --logapp\n"
        "Installing [Later]\nSUCCESSFULLY INSTALLED      Later\n")
    mods = tmp_path / "mods"
    for name, tp2 in (("warns", WARNS), ("bad", BAD)):
        (mods / name).mkdir(parents=True)
        (mods / name / f"{name}.tp2").write_text(tp2)
    (mods / "warns" / "f.txt").write_text("f\n")
    (mods / "bad" / "a.txt").write_text("mod\n")
    with open(mods / "bad" / "bad.tp2", "a") as fh:
        fh.write("\nBEGIN ~Later~\nCOPY ~bad/a.txt~ ~override/later.txt~\n")
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text("// Log of Currently Installed WeiDU Mods\n"
                                    "~WARNS/WARNS.TP2~ #0 #0 // One\n"
                                    "~WARNS/WARNS.TP2~ #0 #1 // Careful\n"
                                    "~BAD/BAD.TP2~ #0 #0 // Fine\n"
                                    "~BAD/BAD.TP2~ #0 #1 // Broken\n"
                                    "~BAD/BAD.TP2~ #0 #2 // Later\n")
    outcome = api.start_install(str(plan), {"BG2EE": str(game)}, str(mods), MOD_INSTALLER,
                                WEIDU, ask=lambda q, b: None).run()
    assert not outcome.ok                                   # the exit code: something failed
    got = [(x.key, x.status, x.name) for x in outcome.results]
    assert got[:4] == [(("warns.tp2", 0), "installed", "One"),
                       (("warns.tp2", 1), "installed with warnings", "Careful"),
                       (("bad.tp2", 0), "installed", "Fine"),
                       (("bad.tp2", 1), "not installed (errors)", "Broken")], got
    assert all(not x.note for x in outcome.results[:4])
    assert (got[4][0], got[4][1]) == (("bad.tp2", 2), "not reached")     # stopped before
    written = json.loads((plan / "results.json").read_text())["components"]
    assert [c["status"] for c in written[:4]] == [x[1] for x in got[:4]]


SKIPS = """BACKUP ~skips/backup~
AUTHOR ~iemod-fetch test~
VERSION ~1~

BEGIN ~First~
COPY ~skips/f.txt~ ~override/first.txt~

BEGIN ~Middle~
REQUIRE_PREDICATE (0 == 1) ~not for this game~
COPY ~skips/f.txt~ ~override/middle.txt~

BEGIN ~Last~
COPY ~skips/f.txt~ ~override/last.txt~
"""


def test_weidus_debug_file_for_a_skipped_component_in_a_batch(tmp_path):
    """Review of #109: WeiDU itself, given three components with the middle
    one's REQUIRE_PREDICATE false, as a batch would give them - measured,
    not assumed: `SKIPPING: [Middle]`, no verdict, the others where they are."""
    import subprocess

    from test_real_weidu import make_game

    from iemod_fetch import results
    game = tmp_path / "bg2ee"
    make_game(str(game), "BG2EE")
    (game / "skips").mkdir()
    (game / "skips" / "skips.tp2").write_text(SKIPS)
    (game / "skips" / "f.txt").write_text("f\n")
    subprocess.run([WEIDU, "skips/skips.tp2", "--force-install-list", "0", "1", "2",  # noqa: S603
                    "--use-lang", "en_US", "--language", "0", "--no-exit-pause",
                    "--logapp", "--autolog", "--log-extern"], cwd=game,
                   stdin=subprocess.DEVNULL, capture_output=True, timeout=120, check=False)
    debug = (game / "WSETUP.DEBUG").read_text(errors="replace")
    assert "SKIPPING: [Middle]" in debug
    assert results.debug_verdicts(debug) == {("skips.tp2", 0): (results.OK, "First"),
                                             ("skips.tp2", 2): (results.OK, "Last")}
    found = results.results([("skips.tp2", n) for n in (0, 1, 2)], "",
                            (game / "WeiDU.log").read_text(), debug)
    assert [x.status for x in found] == [results.OK, results.NOT_REACHED, results.OK]


UNDER_A_CONDITION = """BACKUP ~cond/backup~
AUTHOR ~iemod-fetch test~
VERSION ~v30~

BEGIN ~Asks under a condition, then always~
ACTION_IF NOT FILE_EXISTS ~cond/prefs.txt~ BEGIN
  PRINT ~Which portraits do you want, old or new?~
  ACTION_READLN portraits
END ELSE BEGIN
  OUTER_SPRINT portraits ~preset~
END
PRINT ~Please enter how many extra kits should be installed:~
ACTION_READLN kits
APPEND_OUTER ~cond-answers.txt~ ~%portraits% %kits%~
"""


@pytest.mark.parametrize("asked_first", [True, False])
def test_the_real_window_is_recognised_and_answered_by_question(tmp_path, asked_first):
    """ADR-0049: a question under a condition, which the log's order cannot
    answer, is recognised by its text in the real mod_installer's window and
    answered by its key - and when the condition skips it (prefs.txt there),
    the next question still gets its own answer. Measured: mod_installer
    16.0.0 flags a question only when its window holds one of its choice
    words or phrases (parser_config.rs: "enter", "please enter", "do you
    want"...); a question with none ("How many kits?" alone) is never put
    to anyone and WeiDU waits until mod_installer's timeout, 3 hours - so
    the second question says "Please enter"."""
    from test_real_weidu import make_game
    game = tmp_path / "bg2ee"
    make_game(str(game), "BG2EE")
    (game / "cond-answers.txt").write_text("")
    mods = tmp_path / "mods"
    (mods / "cond").mkdir(parents=True)
    (mods / "cond" / "cond.tp2").write_text(UNDER_A_CONDITION)
    if not asked_first:
        (mods / "cond" / "prefs.txt").write_text("")      # copied into the game with the mod
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "~COND/COND.TP2~ #0 #0 // Asks under a condition, then always\n")
    answers = {"cond.tp2#0": {"Which portraits do you want, old or new?": "new",
                              "Please enter how many extra kits should be installed:": "3"}}
    lines, asked = [], []
    outcome = api.start_install(str(plan), {"BG2EE": str(game)}, str(mods), MOD_INSTALLER,
                                WEIDU, ask=lambda q, b: asked.append(q) or None,
                                on_event=lambda e: lines.append(e.text),
                                answers=answers).run()
    transcript = "\n".join(lines)
    assert outcome.ok and asked == [], transcript
    expected = ["new", "3"] if asked_first else ["preset", "3"]
    assert (game / "cond-answers.txt").read_text().split() == expected, transcript
    assert {a.source for a in outcome.answered} == {"by question"}, transcript


ASKED_UNTIL_VALID = """BACKUP ~rep/backup~
AUTHOR ~iemod-fetch test~
VERSION ~v30~

BEGIN ~Asks until the answer is valid~
OUTER_SET n = 0
OUTER_WHILE (n < 1 OR n > 5) BEGIN
  PRINT ~Please enter a number between 1 and 5:~
  ACTION_READLN n
END
APPEND_OUTER ~rep-answer.txt~ ~%n%~
"""


def test_a_stored_answer_the_mod_refuses_is_given_once_then_the_player_answers(tmp_path):
    """Review of #111, reproduced with the real binaries: a loop asking until
    valid got the same refused stored answer forever (16 in 40 s). Given
    once; asked again, the player answers."""
    from test_real_weidu import make_game
    game = tmp_path / "bg2ee"
    make_game(str(game), "BG2EE")
    (game / "rep-answer.txt").write_text("")
    mods = tmp_path / "mods"
    (mods / "rep").mkdir(parents=True)
    (mods / "rep" / "rep.tp2").write_text(ASKED_UNTIL_VALID)
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text("// Log of Currently Installed WeiDU Mods\n"
                                    "~REP/REP.TP2~ #0 #0 // Asks until the answer is valid\n")
    asked, lines = [], []
    outcome = api.start_install(
        str(plan), {"BG2EE": str(game)}, str(mods), MOD_INSTALLER, WEIDU,
        ask=lambda q, b: asked.append(q) or "3", on_event=lambda e: lines.append(e.text),
        answers={"rep.tp2#0": {"Please enter a number between 1 and 5:": "9"}}).run()
    transcript = "\n".join(lines)
    assert outcome.ok and len(asked) == 1, transcript
    assert [a.source for a in outcome.answered] == ["by question", "player"], transcript
    assert (game / "rep-answer.txt").read_text().split() == ["3"]


NO_CHOICE_WORD = """BACKUP ~plain/backup~
AUTHOR ~iemod-fetch test~
VERSION ~v30~

BEGIN ~Asks with no choice word~
PRINT ~{PRINTED}~
ACTION_READLN kits
APPEND_OUTER ~plain-answer.txt~ ~%kits%~
"""


@pytest.mark.parametrize(("printed", "phrase"), [
    ("How many extra kits should be installed?", "how many extra kits should be installed?"),
    # review of #120: the question's text read with its spaces collapsed
    # gave a phrase no line WeiDU prints holds - two lines, two spaces
    ("Kits menu\nHow many extra kits should be installed?",
     "how many extra kits should be installed?"),
    ("How many extra  kits should be installed?", "how many extra  kits should be installed?"),
])
def test_a_question_without_choice_words_is_asked_through_the_parser_config(tmp_path, printed,
                                                                            phrase):
    """ADR-0057: mod_installer 16.0.0 never puts "How many extra kits should
    be installed?" to anyone (no choice word or phrase): WeiDU would wait for
    its 3-hour timeout. Its expected text, added to mod_installer's parser
    config for this install, makes it a question, answered by its key. The
    run is cancelled after 120 s, so a regression fails instead of hanging."""
    import threading
    from test_real_weidu import make_game
    game = tmp_path / "bg2ee"
    make_game(str(game), "BG2EE")
    (game / "plain-answer.txt").write_text("")
    mods = tmp_path / "mods"
    (mods / "plain").mkdir(parents=True)
    (mods / "plain" / "plain.tp2").write_text(NO_CHOICE_WORD.replace("{PRINTED}", printed))
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text("// Log of Currently Installed WeiDU Mods\n"
                                    "~PLAIN/PLAIN.TP2~ #0 #0 // Asks with no choice word\n")
    lines: list[str] = []
    install = api.start_install(
        str(plan), {"BG2EE": str(game)}, str(mods), MOD_INSTALLER, WEIDU,
        ask=lambda q, b: None, on_event=lambda e: lines.append(e.text),
        answers={"plain.tp2#0": {" ".join(printed.split()): "4"}})
    timer = threading.Timer(120, install.cancel)
    timer.start()
    try:
        outcome = install.run()
    finally:
        timer.cancel()
    transcript = "\n".join(lines)
    assert outcome.ok, transcript
    assert install.parser_phrases == [phrase], transcript
    assert (plan / "mod_installer-config").is_dir()
    assert (game / "plain-answer.txt").read_text().split() == ["4"], transcript
    assert [a.source for a in outcome.answered] == ["by question"], transcript
