"""
Installer scripts (ADR-0022): the plan, handed to mod_installer, never run by us.

The load-bearing claims:

* an EET plan becomes ONE `mod_installer eet` call with the pre-EET log on the
  BGEE game and the EET log on the BG2EE game; anything else becomes one
  `mod_installer normal` call;
* the EET core line must keep the comment mod_installer recognises it by, or the
  BGEE path never reaches EET - refused at generation time, not at minute 40;
* the scripts refuse a game directory that is not a game, or that already has
  mods in it, before anything runs;
* the shell script, executed for real against a stand-in mod_installer, passes
  exactly the arguments the documentation promises.
"""
import os
import stat
import subprocess
import sys

import pytest

from iemod_fetch.installer import build_installer
from iemod_fetch.ordering import EET_LOG, PRE_EET_LOG, OrderIndex, plan_order

HERE = os.path.dirname(__file__)
KRION = os.path.join(HERE, "data", "krion")
REAL_EET = os.path.join(HERE, "data", "WeiDU.log")
REAL_BGEE = os.path.join(HERE, "data", "WeiDUBGEE.log")
HEADER = "// Log of Currently Installed WeiDU Mods\n"

EET_LINES = [
    r"~eet\EET.TP2~ #0 #0 // EET core (resource importation)",
    r"~cdtweaks\setup-cdtweaks.tp2~ #0 #10 // Tweak",
    r"~eet\EET_end\EET_end.tp2~ #0 #0 // Standard installation",
]
BGEE_LINES = [r"~bg1ub\setup-bg1ub.tp2~ #0 #0 // Ice Island"]


@pytest.fixture
def index():
    return OrderIndex.load(KRION)


def write_log(tmp_path, name, lines):
    path = tmp_path / name
    path.write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def eet_plan(tmp_path, index, eet_lines=EET_LINES, bgee_lines=BGEE_LINES):
    specs = [(write_log(tmp_path, "in-eet.log", eet_lines), EET_LOG)]
    if bgee_lines:
        specs.append((write_log(tmp_path, "in-bgee.log", bgee_lines), PRE_EET_LOG))
    return plan_order(specs, index)


def make_game(path):
    path.mkdir(parents=True)
    (path / "chitin.key").write_bytes(b"KEY V1  ")
    return path


# ------------------------------------------------------------------ the plan
def test_an_eet_plan_is_one_eet_call_over_both_games(tmp_path, index):
    installer = build_installer(eet_plan(tmp_path, index), mods_relpath="../Mods")
    assert installer.mode == "eet" and installer.problems == []
    sh = installer.scripts["install-eet.sh"]
    assert "set -- eet " in sh
    assert '--bg1-game-directory "$BGEE_DIR"' in sh
    assert '--bg1-log-file "$HERE/WeiDU-BGEE.log"' in sh
    assert '--bg2-game-directory "$BG2EE_DIR"' in sh
    assert '--bg2-log-file "$HERE/WeiDU.log"' in sh
    assert "install-eet.cmd" in installer.scripts


def test_an_eet_plan_with_no_bgee_mods_still_gets_a_bgee_log(tmp_path, index):
    """mod_installer's eet mode requires both logs; EET itself needs the BGEE game."""
    installer = build_installer(eet_plan(tmp_path, index, bgee_lines=None),
                                mods_relpath="../Mods")
    assert installer.mode == "eet"
    assert installer.extra_files["WeiDU-BGEE.log"].startswith("// Log of")


def test_a_single_game_plan_is_a_normal_install(tmp_path, index):
    log = write_log(tmp_path, "in.log", BGEE_LINES)
    installer = build_installer(plan_order([(log, PRE_EET_LOG)], index),
                                mods_relpath="../Mods")
    assert installer.mode == "normal"
    sh = installer.scripts["install.sh"]
    assert "set -- normal " in sh
    assert '--game-directory "$GAME_DIR"' in sh
    assert '--log-file "$HERE/WeiDU-BGEE.log"' in sh


def test_an_eet_core_without_its_comment_is_refused(tmp_path, index):
    """mod_installer finds the EET core by its log comment, to hand it the BGEE
    path. Without it the merge would stop at a prompt nobody answers."""
    lines = [r"~eet\EET.TP2~ #0 #0", *EET_LINES[1:]]
    installer = build_installer(eet_plan(tmp_path, index, eet_lines=lines),
                                mods_relpath="../Mods")
    assert any("EET core (resource importation)" in p for p in installer.problems)


def test_two_logs_without_an_eet_core_are_refused(tmp_path, index):
    specs = [(write_log(tmp_path, "a.log", EET_LINES[1:2]), EET_LOG),
             (write_log(tmp_path, "b.log", BGEE_LINES), PRE_EET_LOG)]
    installer = build_installer(plan_order(specs, index), mods_relpath="../Mods")
    assert any("no EET core" in p for p in installer.problems)


def test_eet_end_not_last_is_a_problem(tmp_path, index):
    lines = [EET_LINES[0], EET_LINES[2], EET_LINES[1]]
    plan = eet_plan(tmp_path, index, eet_lines=lines)
    by_key = {u.key: u for u in plan.logs[EET_LOG]}         # force EET_end mid-list
    plan.logs[EET_LOG] = [by_key["eet"], by_key["eetend"], by_key["cdtweaks"]]
    installer = build_installer(plan, mods_relpath="../Mods")
    assert any("EET_end" in p for p in installer.problems)


def test_mods_missing_from_the_staging_area_are_named(tmp_path, index):
    mods = tmp_path / "Mods"
    (mods / "eet").mkdir(parents=True)
    installer = build_installer(eet_plan(tmp_path, index), mods_relpath="../Mods",
                                mods_dir=str(mods))
    assert any("cdtweaks" in w and "bg1ub" in w for w in installer.warnings)


def test_an_unverified_plan_carries_its_warning_into_the_script(tmp_path, index):
    plan = eet_plan(tmp_path, index)
    plan.blockers = ["x"]
    installer = build_installer(plan, mods_relpath="../Mods")
    assert "UNRESOLVED" in installer.scripts["install-eet.sh"]


def test_the_windows_script_quotes_paths_and_trims_a_trailing_backslash(tmp_path,
                                                                       index):
    cmd = build_installer(eet_plan(tmp_path, index),
                          mods_relpath="../Mods").scripts["install-eet.cmd"]
    assert '--bg1-game-directory "%BGEE_DIR%"' in cmd
    assert 'if "%BGEE_DIR:~-1%"=="\\" set "BGEE_DIR=%BGEE_DIR:~0,-1%"' in cmd
    assert 'set "MODS_DIR=%HERE%..\\Mods"' in cmd
    assert "\r\n" in cmd                                    # cmd.exe wants CRLF


def test_the_real_logs_produce_a_clean_eet_installer(index):
    plan = plan_order([(REAL_EET, EET_LOG), (REAL_BGEE, PRE_EET_LOG)], index)
    installer = build_installer(plan, mods_relpath="../Mods")
    assert installer.mode == "eet" and installer.problems == []


# --------------------------------------------- the shell script, executed
@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX shell script")
class TestShellScriptRuns:
    def _setup(self, tmp_path, index, installed_mods=False):
        plan_dir = tmp_path / "plan"
        installer = build_installer(eet_plan(tmp_path, index), mods_relpath="../Mods")
        installer.write(str(plan_dir))
        (tmp_path / "Mods").mkdir()
        bgee, bg2ee = make_game(tmp_path / "BGEE"), make_game(tmp_path / "BG2 EE")
        if installed_mods:
            (bgee / "WeiDU.log").write_text(HEADER + BGEE_LINES[0] + "\n")
        fake = tmp_path / "fake_mod_installer"
        fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGS_OUT"\n')
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        weidu = tmp_path / "weidu"
        weidu.write_text("#!/bin/sh\n")
        weidu.chmod(weidu.stat().st_mode | stat.S_IEXEC)
        env = dict(os.environ, BGEE_DIR=str(bgee), BG2EE_DIR=str(bg2ee),
                   MOD_INSTALLER=str(fake), WEIDU=str(weidu),
                   ARGS_OUT=str(tmp_path / "args.txt"))
        return plan_dir, env

    def _run(self, plan_dir, env):
        return subprocess.run(["sh", str(plan_dir / "install-eet.sh")], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=60, check=False)

    def test_it_hands_mod_installer_both_games_and_both_logs(self, tmp_path, index):
        plan_dir, env = self._setup(tmp_path, index)
        proc = self._run(plan_dir, env)
        assert proc.returncode == 0, proc.stdout.decode()
        args = (tmp_path / "args.txt").read_text().splitlines()
        assert args[0] == "eet"
        pairs = dict(zip(args[1::2], args[2::2], strict=False))
        assert pairs["--bg1-game-directory"] == str(tmp_path / "BGEE")
        assert pairs["--bg2-game-directory"] == str(tmp_path / "BG2 EE")
        assert pairs["--bg1-log-file"] == str(plan_dir / "WeiDU-BGEE.log")
        assert pairs["--bg2-log-file"] == str(plan_dir / "WeiDU.log")
        assert pairs["--mod-directories"] == str(tmp_path / "Mods")
        assert pairs["--language"] == "en_US"

    def test_it_refuses_a_directory_that_is_not_a_game(self, tmp_path, index):
        plan_dir, env = self._setup(tmp_path, index)
        env["BGEE_DIR"] = str(tmp_path)
        proc = self._run(plan_dir, env)
        assert proc.returncode == 2 and b"chitin.key" in proc.stdout
        assert not (tmp_path / "args.txt").exists()

    def test_it_refuses_a_game_that_already_has_mods(self, tmp_path, index):
        plan_dir, env = self._setup(tmp_path, index, installed_mods=True)
        proc = self._run(plan_dir, env)
        assert proc.returncode == 2 and b"fresh" in proc.stdout
        env["ALLOW_EXISTING"] = "1"
        assert self._run(plan_dir, env).returncode == 0

    @pytest.mark.skipif(not sys.platform.startswith("linux"),
                        reason="case-sensitive file systems")
    def test_on_linux_mixed_case_mods_are_refused_before_an_hour_of_install(
            self, tmp_path, index):
        """mod_installer hands WeiDU lower-cased paths (eet/eet.tp2); on a
        case-sensitive file system EET.TP2 is then 'not found' mid-install."""
        plan_dir, env = self._setup(tmp_path, index)
        (tmp_path / "Mods" / "eet").mkdir()
        (tmp_path / "Mods" / "eet" / "EET.TP2").write_text("x")
        proc = self._run(plan_dir, env)
        assert proc.returncode == 2 and b"lower-case" in proc.stdout
        assert not (tmp_path / "args.txt").exists()

        env["MOD_INSTALLER_ARGS"] = "--casefold"          # mod_installer's answer
        assert self._run(plan_dir, env).returncode == 0

    def test_dry_run_prints_and_runs_nothing(self, tmp_path, index):
        plan_dir, env = self._setup(tmp_path, index)
        env["DRY_RUN"] = "1"
        proc = self._run(plan_dir, env)
        assert proc.returncode == 0 and b"eet" in proc.stdout
        assert not (tmp_path / "args.txt").exists()


# ------------------------------------------- the cmd script, on Windows CI
@pytest.mark.skipif(not sys.platform.startswith("win"), reason="cmd.exe script")
def test_the_windows_script_runs_under_cmd(tmp_path, index):
    plan_dir = tmp_path / "plan"
    build_installer(eet_plan(tmp_path, index), mods_relpath="../Mods").write(
        str(plan_dir))
    (tmp_path / "Mods").mkdir()
    bgee, bg2ee = make_game(tmp_path / "BGEE"), make_game(tmp_path / "BG2 EE")
    fake = tmp_path / "fake_mod_installer.cmd"
    fake.write_text('@echo off\r\n(for %%a in (%*) do @echo %%~a) > "%ARGS_OUT%"\r\n')
    weidu = tmp_path / "weidu.exe"
    weidu.write_bytes(b"MZ")
    env = dict(os.environ, BGEE_DIR=str(bgee) + "\\", BG2EE_DIR=str(bg2ee),
               MOD_INSTALLER=str(fake), WEIDU=str(weidu),
               ARGS_OUT=str(tmp_path / "args.txt"))
    proc = subprocess.run(["cmd", "/c", str(plan_dir / "install-eet.cmd")], env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=60, check=False)
    assert proc.returncode == 0, proc.stdout.decode(errors="replace")
    args = (tmp_path / "args.txt").read_text().splitlines()
    assert args[0] == "eet"
    assert str(bgee) in args                      # trailing backslash trimmed
    assert str(bg2ee) in args


# ----------------------------------------------------------------- the CLI
def _cli(argv):
    import io

    from iemod_fetch import cli
    stream = io.StringIO()
    code = cli.main(argv, stream=stream)
    return code, stream.getvalue()


def test_cli_writes_the_plan_and_both_installer_scripts(tmp_path):
    out = tmp_path / "plan"
    code, text = _cli(["--check-only",
                       "-m", os.path.join(HERE, "data", "mod_downloads.json"),
                       "-w", f"{REAL_EET}:EET", "-w", f"{REAL_BGEE}:BGEE",
                       "--order-catalogue", KRION, "-t", str(tmp_path / "Mods"),
                       "--plan-order", str(out), "--emit-installer"])
    assert code == 0, text
    for name in ("WeiDU.log", "WeiDU-BGEE.log", "install-eet.sh", "install-eet.cmd"):
        assert (out / name).is_file(), name
    assert "INSTALLER" in text and "install-eet.sh" in text
    script = (out / "install-eet.sh").read_text()
    assert 'MODS_DIR="${MODS_DIR:-$HERE/../Mods}"' in script


def test_cli_refuses_an_installer_without_a_plan(tmp_path, capsys):
    code, _text = _cli(["--check-only", "-w", f"{REAL_EET}:EET",
                        "--emit-installer"])
    assert code == 2
    assert "--plan-order" in capsys.readouterr().err


def test_cli_game_language_reaches_the_script(tmp_path):
    out = tmp_path / "plan"
    code, _text = _cli(["--check-only", "-q",
                        "-m", os.path.join(HERE, "data", "mod_downloads.json"),
                        "-w", f"{REAL_EET}:EET", "-w", f"{REAL_BGEE}:BGEE",
                        "--order-catalogue", KRION, "--plan-order", str(out),
                        "--emit-installer", "--game-language", "it_IT"])
    assert code == 0
    assert 'LANGUAGE="${LANGUAGE:-it_IT}"' in (out / "install-eet.sh").read_text()


# Mods on D:, plan on C: - os.path.relpath raises, and the plan must still be
# installable. Found by the Windows CI runner, whose checkout is on D:.
def test_an_absolute_mods_location_is_used_as_is(tmp_path, index):
    installer = build_installer(eet_plan(tmp_path, index), mods_relpath="D:/Games/Mods")
    assert 'MODS_DIR="${MODS_DIR:-D:/Games/Mods}"' in installer.scripts["install-eet.sh"]
    assert 'set "MODS_DIR=D:\\Games\\Mods"' in installer.scripts["install-eet.cmd"]


def test_cli_falls_back_to_an_absolute_path_across_drives(tmp_path, monkeypatch):
    from iemod_fetch import api

    def other_drive(*_args):
        raise ValueError("path is on mount 'D:', start on mount 'C:'")

    monkeypatch.setattr(api.os.path, "relpath", other_drive)
    out = tmp_path / "plan"
    code, _text = _cli(["--check-only", "-q",
                        "-m", os.path.join(HERE, "data", "mod_downloads.json"),
                        "-w", f"{REAL_EET}:EET", "-w", f"{REAL_BGEE}:BGEE",
                        "--order-catalogue", KRION, "-t", str(tmp_path / "Mods"),
                        "--plan-order", str(out), "--emit-installer"])
    assert code == 0
    mods = str(tmp_path / "Mods").replace(os.sep, "/")
    assert f'MODS_DIR="${{MODS_DIR:-{mods}}}"' in (out / "install-eet.sh").read_text()
