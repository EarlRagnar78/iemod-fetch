"""
The game not running while it is installed into (GUI-AUDIT M8 item 67,
ADR-0051): no program running from a game folder, and on Windows no
dialog*.tlk held open by another program - checked before the install and
again, for the programs, at each batch (mod_installer starts each batch's
WeiDU itself, so only a warning can come then).
"""
import os
import shutil
import subprocess
import sys
import time

import pytest

from iemod_fetch import gamelock


def test_a_program_in_a_game_folder_is_found_and_others_are_not(tmp_path):
    game = tmp_path / "Baldur's Gate EE"
    (game / "x64").mkdir(parents=True)
    exe = str(game / "x64" / "Baldur.exe")
    beside = str(tmp_path / "Baldur's Gate EE 2" / "Baldur.exe")     # a prefix, not under
    tools = str(game / "weidu.exe")
    found = gamelock.running_in({"BGEE": str(game)},
                                [(7, exe), (7, str(game)), (8, beside), (9, "/usr/bin/python3"),
                                 (10, tools)], ignore=[tools])
    assert found == [f"BGEE: {exe} (pid 7)"]                       # once per process
    assert gamelock.running_in({"BGEE": str(game)}, None) == []      # not listed: nothing said


@pytest.mark.skipif(os.name == "nt", reason="symbolic links need privileges on Windows")
def test_this_program_in_the_game_folder_is_never_the_game():
    """Review of #105: iemod-fetch unpacked beside Baldur.exe - its own
    process and executable are under the folder, and cannot be closed by
    the player they are asking."""
    folder = os.path.dirname(os.path.realpath(sys.executable))
    other = os.path.join(folder, "Baldur.exe")
    found = gamelock.running_in({"BGEE": folder}, [(os.getpid(), sys.executable),
                                                   (os.getpid() + 1, sys.executable),
                                                   (os.getpid() + 2, other)])
    assert found == [f"BGEE: {other} (pid {os.getpid() + 2})"]


def test_a_game_folder_reached_by_a_link_is_the_same_folder(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real)
    exe = str(real / "BaldursGate")
    assert gamelock.running_in({"EET": str(tmp_path / "link")}, [(3, exe)]) == \
        [f"EET: {exe} (pid 3)"]


def test_every_talk_table_is_found_whatever_the_case(tmp_path):
    (tmp_path / "lang" / "en_US").mkdir(parents=True)
    (tmp_path / "lang" / "de_DE").mkdir()
    for path in ("lang/en_US/dialog.tlk", "lang/de_DE/dialogF.tlk", "dialog.tlk",
                 "lang/en_US/dialog.txt", "chitin.key"):
        (tmp_path / path).write_text("")
    found = [os.path.relpath(p, tmp_path).replace(os.sep, "/")
             for p in gamelock.talk_tables(str(tmp_path))]
    assert found == ["dialog.tlk", "lang/de_DE/dialogF.tlk", "lang/en_US/dialog.tlk"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux keeps the case")
def test_talk_tables_in_upper_case_folders_are_found_on_linux(tmp_path):
    (tmp_path / "Lang" / "EN_US").mkdir(parents=True)
    (tmp_path / "Lang" / "EN_US" / "DIALOG.TLK").write_text("")
    assert [os.path.basename(p) for p in gamelock.talk_tables(str(tmp_path))] == ["DIALOG.TLK"]


def test_a_talk_table_held_by_another_program_is_named(tmp_path):
    (tmp_path / "lang" / "en_US").mkdir(parents=True)
    held, readonly = tmp_path / "lang" / "en_US" / "dialog.tlk", tmp_path / "dialog.tlk"
    held.write_text("")
    readonly.write_text("")
    errors = {str(held): gamelock.SHARING_VIOLATION, str(readonly): 5}
    waits = []
    found = gamelock.held_talk_tables({"EET": str(tmp_path)}, lambda p: errors.get(p, 0),
                                      sleep=waits.append)
    assert found == [f"EET: {readonly} cannot be opened for writing (Windows error 5)",
                     (f"EET: {held} is open in another program (the game, Near Infinity, "
                     "an editor)")]
    assert len(waits) == gamelock.HELD_TRIES - 1             # tried again, then said
    assert gamelock.held_talk_tables({"EET": str(tmp_path)}, lambda _p: 0) == []


def test_a_talk_table_held_for_a_moment_is_not_refused(tmp_path):
    """Review of #105: an antivirus or the indexer opens it briefly."""
    (tmp_path / "dialog.tlk").write_text("")
    answers = iter([gamelock.SHARING_VIOLATION, gamelock.SHARING_VIOLATION, 0])
    assert gamelock.held_talk_tables({"EET": str(tmp_path)}, lambda _p: next(answers),
                                     sleep=lambda _s: None) == []


def test_a_path_under_wine_is_this_systems_path():
    assert gamelock._wine_path(r"Z:\home\me\BG\Baldur.exe", None) == "/home/me/BG/Baldur.exe"
    assert gamelock._wine_path(r"C:\GOG\BG\Baldur.exe", "/home/me/.wine") == \
        "/home/me/.wine/dosdevices/c:/GOG/BG/Baldur.exe"
    assert gamelock._wine_path(r"C:\GOG\Baldur.exe", None) is None    # no prefix known
    assert gamelock._wine_path("/opt/bg/Baldur", None) == "/opt/bg/Baldur"
    assert gamelock._wine_path("--debug", None) is None


@pytest.mark.skipif(sys.platform == "win32", reason="Windows locks files")
def test_elsewhere_nothing_locks_a_talk_table_so_none_is_checked(tmp_path):
    (tmp_path / "dialog.tlk").write_text("")
    assert gamelock.held_talk_tables({"BG2EE": str(tmp_path)}) == []


def test_both_checks_say_close_it_first(tmp_path):
    (tmp_path / "dialog.tlk").write_text("")
    exe = str(tmp_path / "Baldur.exe")
    found = gamelock.problems({"BG2EE": str(tmp_path)}, lambda: [(42, exe)],
                              lambda _p: gamelock.SHARING_VIOLATION, sleep=lambda _s: None)
    assert found == [f"the game is running: BG2EE: {exe} (pid 42) - close it and try again",
                     (f"BG2EE: {tmp_path / 'dialog.tlk'} is open in another program (the "
                      "game, Near Infinity, an editor) - close it and try again")]


# --------------------------------------------------- against this system
def test_this_systems_processes_are_listed():
    running = gamelock.running_executables()
    assert running, "no process listed"
    if sys.platform != "darwin":         # ps names a framework's Python otherwise
        seen = {(pid, os.path.normcase(os.path.realpath(p))) for pid, p in running}
        assert (os.getpid(), os.path.normcase(os.path.realpath(sys.executable))) in seen


def _a_program_that_waits(folder):
    """A copy of a system program, in `folder`, that runs for a while."""
    if sys.platform == "win32":
        source = os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32",
                              "ping.exe")
        args = ["-n", "30", "127.0.0.1"]
    else:
        source, args = shutil.which("sleep") or "/bin/sleep", ["30"]
    target = os.path.join(folder, "Baldur" + (".exe" if sys.platform == "win32" else ""))
    shutil.copy(source, target)          # copy2 fails on macOS's system-file flags
    return [target, *args]


def test_a_game_really_running_from_the_folder_is_refused(tmp_path):
    argv = _a_program_that_waits(str(tmp_path))
    process = subprocess.Popen(argv, stdout=subprocess.DEVNULL)  # noqa: S603
    try:
        deadline = time.monotonic() + 10
        found = []
        while not found and time.monotonic() < deadline:
            found = gamelock.problems({"BGEE": str(tmp_path)})
            time.sleep(0.1)
        assert found == [(f"the game is running: BGEE: {argv[0]} (pid {process.pid}) - "
                         "close it and try again")]
    finally:
        process.kill()
        process.wait()
    assert gamelock.problems({"BGEE": str(tmp_path)}) == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows locks files")
def test_a_talk_table_really_held_open_is_refused_on_windows(tmp_path):
    tlk = tmp_path / "dialog.tlk"
    tlk.write_bytes(b"TLK V1  ")
    with open(tlk, "rb"):
        found = gamelock.problems({"BGEE": str(tmp_path)})
    assert found == [(f"BGEE: {tlk} is open in another program (the game, Near Infinity, an "
                     "editor) - close it and try again")]
    assert gamelock.problems({"BGEE": str(tmp_path)}) == []


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Wine runs on Linux")
def test_a_game_under_wine_is_found_by_its_command_line(tmp_path):
    """Review of #105: under Wine or Proton /proc's exe is Wine's loader,
    outside the game folder; the game's own path is in its command line."""
    game = os.path.realpath(tmp_path)
    as_wine = "Z:" + os.path.join(game, "Baldur.exe").replace("/", "\\")
    process = subprocess.Popen([as_wine, "30"], executable=shutil.which("sleep") or "/bin/sleep")
    try:
        deadline = time.monotonic() + 10
        found = []
        while not found and time.monotonic() < deadline:
            found = gamelock.problems({"BGEE": game})
            time.sleep(0.1)
        assert found == [(f"the game is running: BGEE: {os.path.join(game, 'Baldur.exe')} "
                         f"(pid {process.pid}) - close it and try again")]
    finally:
        process.kill()
        process.wait()
