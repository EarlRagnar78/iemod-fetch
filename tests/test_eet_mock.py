"""
A realistic mock EET installation (tests/data/eetmock, ADR-0025).

BG:EE first - DlcMerger merges SoD, EEFixPack, BG1 mods - then EET imports it
into BG2:EE and the BG2/EET mods follow, EET_end last. The mods' constraints are
their REAL ones (verbatim excerpts, see the fixture README); the logs carry the
mistakes operators actually make. Each test pins one of them: found, explained,
and resolved into a plan WeiDU would finish.
"""
import io
import os
import stat
import subprocess
import sys

import pytest

from iemod_fetch import cli

HERE = os.path.dirname(__file__)
MOCK = os.path.join(HERE, "data", "eetmock")
KRION = os.path.join(HERE, "data", "krion")
MANIFEST = os.path.join(HERE, "data", "mod_downloads.json")


def run(tmp_path, *extra):
    stream = io.StringIO()
    code = cli.main(["--check-only", "-m", MANIFEST,
                     "-w", os.path.join(MOCK, "WeiDU.log") + ":EET",
                     "-w", os.path.join(MOCK, "WeiDU-BGEE.log") + ":BGEE",
                     "-t", os.path.join(MOCK, "Mods"), "--order-catalogue", KRION,
                     "--plan-order", str(tmp_path / "plan"), "--simulate", *extra],
                    stream=stream)
    return code, stream.getvalue()


def planned(tmp_path, log):
    return [line for line in (tmp_path / "plan" / log).read_text().splitlines()
            if line.startswith("~")]


def position(lines, needle):
    return next(i for i, line in enumerate(lines) if needle in line)


# ------------------------------------------------- the input, as handed over
def test_a_tweak_installed_on_bgee_makes_eet_refuse_the_merge(tmp_path):
    code, text = run(tmp_path)
    assert code == 1
    assert "EET refuses the merge" in text and "cdtweaks" in text
    assert "compatibility.tbl" in text


# ------------------------------------------------------------ the resolution
RULES = os.path.join(MOCK, "rules")      # one BWS-NG rule, verbatim


@pytest.fixture
def resolved(tmp_path):
    code, text = run(tmp_path, "--rules", RULES, "--resolve-conflicts",
                     "--emit-installer")
    return code, text, tmp_path


def test_the_resolved_plan_installs_completely(resolved):
    _code, text, _tmp = resolved
    assert "0 would be refused" in text, text


def test_the_tweak_eet_cannot_import_leaves_the_bgee_phase(resolved):
    _code, text, tmp = resolved
    bgee = planned(tmp, "WeiDU-BGEE.log")
    assert not any("cdtweaks" in line for line in bgee)
    assert "EET cannot import it" in text
    # DlcMerger merges SoD first; EEFixPack and BG1UB stay on BG:EE
    assert "DlcMerger" in bgee[0]
    assert any("eefixpack" in line for line in bgee)
    assert any("bg1ub" in line for line in bgee)


def test_eet_core_first_after_the_fixpack_and_eet_end_last(resolved):
    _code, _text, tmp = resolved
    eet = [line for line in planned(tmp, "WeiDU.log") if "eefixpack" not in line]
    assert "EET core (resource importation)" in eet[0]
    assert "EET_end" in eet[-1]


def test_eefixpack_moves_before_the_eet_core_instead_of_being_dropped(resolved):
    """EEFixPack refuses EET, but the BG2:EE game is not EET until the core is
    in. EET's readme asks for 'a clean BG2:EE installation ... and (optionally)
    the Enhanced Edition Fixpack', and BWS-NG's games/eet.json orders
    eefixpack:0-2 before eet:0 - so the right order keeps it, before the core."""
    _code, text, tmp = resolved
    eet = planned(tmp, "WeiDU.log")
    core = position(eet, "EET core (resource importation)")
    fixpack = [i for i, line in enumerate(eet) if "eefixpack" in line]
    assert fixpack and max(fixpack) < core
    assert "moved before the EET core" in text


def test_a_bg2_only_tweak_does_not_go_onto_eet(resolved):
    _code, _text, tmp = resolved
    assert not any("#4010" in line for line in planned(tmp, "WeiDU.log"))


def test_ascension_goes_before_the_scs_component_it_forbids(resolved):
    _code, _text, tmp = resolved
    eet = planned(tmp, "WeiDU.log")
    assert position(eet, "Ascension.tp2") < position(eet, "#5900")


def test_scs_and_tweaks_from_the_tp2_alone_are_ordered_and_warned(tmp_path):
    """SCS #4100 FORBIDs Tweaks #2370 one-sidedly: WeiDU installs both with SCS
    first, so the plan does that - and warns, because coexistence is not
    something the tp2 states."""
    _code, text = run(tmp_path, "--resolve-conflicts")
    eet = planned(tmp_path, "WeiDU.log")
    assert position(eet, "#0 #4100") < position(eet, "#0 #2370")
    assert "did not say the two coexist" in text


def test_the_community_rule_says_they_do_not_coexist_and_you_choose(resolved):
    """BWS-NG grades stratagems(4100):cdtweaks(2370,2372,4020) error. Of Tweaks'
    three only #2370 is installed: one component against one, so the rules do
    not say which to keep - it is listed for the operator, never guessed."""
    _code, text, _tmp = resolved
    decide = text.split("left for you to decide", 1)[1]
    assert "stratagems" in decide and "cdtweaks" in decide
    assert "equal number of components" in decide


def test_the_installer_hands_both_planned_logs_to_mod_installer(resolved):
    _code, _text, tmp = resolved
    assert (tmp / "plan" / "install-eet.sh").is_file()
    assert (tmp / "plan" / "install-eet.cmd").is_file()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX shell script")
def test_the_installer_runs_the_resolved_plan(resolved, tmp_path):
    _code, _text, tmp = resolved
    games = {}
    for name in ("BGEE", "BG2EE"):
        game = tmp_path / "games" / name
        game.mkdir(parents=True)
        (game / "chitin.key").write_bytes(b"KEY V1  ")
        games[name] = game
    fake = tmp_path / "mod_installer"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGS_OUT"\n')
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    weidu = tmp_path / "weidu"
    weidu.write_text("#!/bin/sh\n")
    weidu.chmod(weidu.stat().st_mode | stat.S_IEXEC)
    env = dict(os.environ, BGEE_DIR=str(games["BGEE"]), BG2EE_DIR=str(games["BG2EE"]),
               MOD_INSTALLER=str(fake), WEIDU=str(weidu), ALLOW_MIXED_CASE="1",
               ARGS_OUT=str(tmp_path / "args.txt"))
    proc = subprocess.run(["sh", str(tmp / "plan" / "install-eet.sh")], env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=60, check=False)
    assert proc.returncode == 0, proc.stdout.decode()
    args = (tmp_path / "args.txt").read_text().splitlines()
    assert args[0] == "eet"


# ------------------------------------------------------ the real game folders
def _games(tmp_path, sod_file):
    import struct
    for name, marker in (("BGEE", b"OH1000"), ("BG2EE", b"OH6000")):
        root = tmp_path / "games" / name
        (root / "override").mkdir(parents=True)
        (root / "chitin.key").write_bytes(
            b"KEY V1  " + struct.pack("<IIII", 0, 1, 24, 24)
            + marker.ljust(8, b"\0") + struct.pack("<HI", 0x3F2, 0))
    sod = tmp_path / "games" / "BGEE" / sod_file
    sod.parent.mkdir(parents=True, exist_ok=True)
    sod.write_bytes(b"")
    return str(tmp_path / "games" / "BGEE"), str(tmp_path / "games" / "BG2EE")


def test_the_game_folders_are_verified_against_the_plan(tmp_path):
    bgee, bg2ee = _games(tmp_path, "dlc/sod-dlc.zip")
    code, text = run(tmp_path, "--rules", RULES, "--resolve-conflicts",
                     "--bgee-dir", bgee, "--bg2ee-dir", bg2ee)
    assert "GAME FOLDERS" in text and "Siege of Dragonspear dlc" in text
    assert "both folders are what an EET install needs" in text   # DlcMerger planned


def test_swapped_game_folders_fail_the_check(tmp_path):
    bgee, bg2ee = _games(tmp_path, "movies/sodcin05.wbm")
    code, text = run(tmp_path, "--rules", RULES, "--resolve-conflicts",
                     "--bgee-dir", bg2ee, "--bg2ee-dir", bgee)
    assert code == 1
    assert "is BG2EE, not BGEE" in text


def test_one_game_folder_without_the_other_is_refused(tmp_path, capsys):
    bgee, _bg2ee = _games(tmp_path, "movies/sodcin05.wbm")
    code, _text = run(tmp_path, "--bgee-dir", bgee)
    assert code == 2 and "--bg2ee-dir" in capsys.readouterr().err
