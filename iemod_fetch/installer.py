"""
Installer scripts for a planned install (ADR-0022).

The plan says WHAT to install and in what order. Running WeiDU against two game
directories in that order - batching consecutive components, answering prompts,
handing EET the BGEE path - is a solved problem: dark0dave's mod_installer
(GPL-3.0, https://github.com/dark0dave/mod_installer) does exactly that from a
pair of weidu.log files, and Born2BSalty's Infinity Orchestrator delegates to it
for the same reason. Re-implementing it here would be a second, less tested
copy of somebody else's work.

So this module writes two small scripts - POSIX `sh` and Windows `cmd` - that
hand the plan to mod_installer, after the checks that are cheap to make and
expensive to skip:

* each game directory is a game (`chitin.key` is there);
* it is fresh: a game that already has mods installed is refused unless
  ALLOW_EXISTING=1, because a plan is an order for a FRESH install (ADR-0017);
* mod_installer and WeiDU are where the script was told they are.

The tool itself never executes WeiDU, mod_installer or the scripts: they are
written for the operator to read and run (ADR-0006 - nothing downloaded is
executed - stays true).

What an EET plan must satisfy, checked here at generation time rather than
forty minutes into an install:

* the EET core line keeps the comment `EET core (resource importation)` -
  mod_installer recognises the core by it, and only then passes the BGEE path;
* EET_end, when present, is the last thing installed on the EET game.
"""
import os
import re
import stat
from dataclasses import dataclass, field

from . import __version__
from .ordering import EET_LOG, HEADER, PRE_EET_LOG

EET_CORE_COMMENT = "eet core (resource importation)"


@dataclass
class Installer:
    mode: str                                  # "eet" | "normal"
    scripts: dict[str, str] = field(default_factory=dict)
    extra_files: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)   # the plan cannot work
    warnings: list[str] = field(default_factory=list)   # it can, but look first

    def write(self, directory: str) -> list[str]:
        os.makedirs(directory, exist_ok=True)
        written = []
        for name, text in {**self.extra_files, **self.scripts}.items():
            path = os.path.join(directory, name)
            newline = "\r\n" if name.endswith(".cmd") else "\n"
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(text.replace("\r\n", "\n").replace("\n", newline))
            if name.endswith(".sh"):
                # Executable by its owner only; `sh install.sh` needs no bit at all.
                os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
            written.append(path)
        return written


def _component_name(comment: str) -> str:
    return comment.rsplit(" : ", 1)[0].strip().lower()


def _check_eet(plan, problems: list[str]) -> bool:
    """True when the EET log installs the EET core; records what is wrong."""
    units = plan.logs.get(EET_LOG, [])
    core = next((u for u in units if u.key == "eet"), None)
    if core is None:
        return False
    first = next((line for line in core.lines if line[2] == 0), None)
    if first is None or _component_name(first[3]) != EET_CORE_COMMENT:
        problems.append(
            "the EET core line (~EET/EET.TP2~ #0 #0) must keep its comment "
            "'// EET core (resource importation)': mod_installer finds the core "
            "by it, and only then gives EET the BGEE path")
    end = [i for i, u in enumerate(units) if u.key == "eetend"]
    if end and end[-1] != len(units) - 1:
        problems.append("EET_end is not the last mod in the EET log; it must be")
    return True


def _missing_mods(plan, mods_dir: str) -> list[str]:
    try:
        present = {entry.lower() for entry in os.listdir(mods_dir)}
    except OSError:
        return []
    missing = []
    for units in plan.logs.values():
        for unit in units:
            path = unit.lines[0][0] if unit.lines else unit.folder
            folder = path.replace("\\", "/").split("/")[0]
            if folder.lower() not in present and folder not in missing:
                missing.append(folder)
    return missing


def build_installer(plan, mods_relpath: str, mods_dir: str | None = None,
                    language: str = "en_US") -> Installer:
    """
    Turn an ordering.OrderPlan into installer scripts.

    `mods_relpath` is where the staged mods are, relative to the directory the
    scripts are written to - or absolute, when no relative path exists (a
    different Windows drive); `mods_dir`, when given, is checked for every mod
    the plan installs.
    """
    problems: list[str] = []
    is_eet = _check_eet(plan, problems)
    roles = [role for role in (PRE_EET_LOG, EET_LOG) if plan.logs.get(role)]

    if is_eet:
        installer = Installer(mode="eet", problems=problems)
        if PRE_EET_LOG not in plan.logs:
            installer.extra_files[PRE_EET_LOG] = HEADER
    elif len(roles) > 1:
        installer = Installer(mode="normal", problems=problems + [
            ("two logs but no EET core in either: that is not an EET install. "
             "Plan each game separately")])
        roles = roles[:1]
    else:
        installer = Installer(mode="normal", problems=problems)

    if mods_dir:
        missing = _missing_mods(plan, mods_dir)
        if missing:
            installer.warnings.append(
                f"{len(missing)} mod folder(s) the plan installs are not in "
                f"{mods_dir} yet - fetch them first: {', '.join(missing[:12])}"
                + (" ..." if len(missing) > 12 else ""))

    unresolved = bool(plan.blockers or plan.residual)
    if installer.mode == "eet":
        installer.scripts["install-eet.sh"] = _sh_eet(mods_relpath, language,
                                                      unresolved)
        installer.scripts["install-eet.cmd"] = _crlf(_cmd_eet(mods_relpath, language,
                                                              unresolved))
    else:
        log = roles[0] if roles else EET_LOG
        installer.scripts["install.sh"] = _sh_normal(log, mods_relpath, language,
                                                     unresolved)
        installer.scripts["install.cmd"] = _crlf(_cmd_normal(log, mods_relpath,
                                                             language, unresolved))
    return installer


# ---------------------------------------------------------------- POSIX sh
def _sh_banner(unresolved: bool) -> str:
    text = (f"#!/bin/sh\n"
            f"# Generated by iemod-fetch {__version__} next to the plan it installs.\n"
            f"# Review it, then run it. iemod-fetch itself never executes it.\n"
            f"#\n"
            f"# Needs: mod_installer (https://github.com/dark0dave/mod_installer)\n"
            f"#        and WeiDU (https://github.com/WeiDUorg/weidu/releases).\n"
            f"# Optional: MODS_DIR, MOD_INSTALLER, WEIDU, LANGUAGE, DRY_RUN=1,\n"
            f"#           ALLOW_EXISTING=1, ALLOW_MIXED_CASE=1,\n"
            f"#           MOD_INSTALLER_ARGS (passed through, e.g. --casefold).\n")
    if unresolved:
        text += ("#\n# WARNING: this plan has UNRESOLVED conflicts or order findings.\n"
                 "# Read the iemod-fetch report before installing it.\n")
    return text


def _is_absolute(path: str) -> bool:
    """POSIX or Windows absolute, whatever OS generates the script."""
    return path.startswith("/") or bool(re.match(r"^[A-Za-z]:[\\/]", path))


def _sh_common(mods_relpath: str, language: str) -> str:
    mods = mods_relpath if _is_absolute(mods_relpath) else f"$HERE/{mods_relpath}"
    return f"""set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
MODS_DIR="${{MODS_DIR:-{mods}}}"
MOD_INSTALLER="${{MOD_INSTALLER:-mod_installer}}"
WEIDU="${{WEIDU:-$(command -v weidu || true)}}"
LANGUAGE="${{LANGUAGE:-{language}}}"

die() {{ echo "install: $*"; exit 2; }}

game_dir() {{  # $1 = variable name, $2 = its value
    [ -n "$2" ] || die "set $1 to the game directory"
    [ -d "$2" ] || die "$1: $2 is not a directory"
    [ -f "$2/chitin.key" ] || die "$1: no chitin.key in $2 - not a game directory"
    for log in "$2/WeiDU.log" "$2/weidu.log"; do
        if [ -f "$log" ] && grep -q '^~' "$log" && [ "${{ALLOW_EXISTING:-0}}" != 1 ]; then
            die "$1 already has mods installed ($log). The plan is for a fresh game: use a clean copy, or ALLOW_EXISTING=1"
        fi
    done
}}

[ -d "$MODS_DIR" ] || die "MODS_DIR: $MODS_DIR does not exist - fetch the mods first"
MODS_DIR=$(CDPATH= cd -- "$MODS_DIR" && pwd)
command -v "$MOD_INSTALLER" >/dev/null 2>&1 || die "mod_installer not found: set MOD_INSTALLER"

# mod_installer hands WeiDU lower-cased paths (eet/eet.tp2). On a case-sensitive
# file system a mixed-case mod is then "not found" partway through the install.
if [ "$(uname -s)" = Linux ] && [ "${{ALLOW_MIXED_CASE:-0}}" != 1 ]; then
    case " ${{MOD_INSTALLER_ARGS:-}} " in
        *" --casefold "*) ;;
        *) mixed=$(find "$MODS_DIR" -mindepth 1 -name '*[[:upper:]]*' -print 2>/dev/null | head -n 1)
           [ -z "$mixed" ] || die "mods must be lower-case on Linux (found: $mixed). Lower-case the mod folders, or on an ext4 file system with case-folding pass MOD_INSTALLER_ARGS=--casefold. ALLOW_MIXED_CASE=1 skips this check" ;;
    esac
fi
[ -n "$WEIDU" ] && [ -x "$WEIDU" ] || die "WeiDU not found: set WEIDU to the weidu binary"
"""


def _sh_run() -> str:
    return """
if [ "${DRY_RUN:-0}" = 1 ]; then
    printf '%s\\n' "would run: $MOD_INSTALLER $*"
    exit 0
fi
# shellcheck disable=SC2086 - MOD_INSTALLER_ARGS is deliberately word-split
"$MOD_INSTALLER" "$@" ${MOD_INSTALLER_ARGS:-}
"""


def _sh_eet(mods_relpath: str, language: str, unresolved: bool) -> str:
    return (_sh_banner(unresolved) + "#\n# EET: BGEE_DIR (pre-EET game) and "
            "BG2EE_DIR (becomes the EET game).\n\n" + _sh_common(mods_relpath, language)
            + """game_dir BGEE_DIR "${BGEE_DIR:-}"
game_dir BG2EE_DIR "${BG2EE_DIR:-}"
BGEE_DIR=$(CDPATH= cd -- "$BGEE_DIR" && pwd)
BG2EE_DIR=$(CDPATH= cd -- "$BG2EE_DIR" && pwd)

set -- eet --bg1-game-directory "$BGEE_DIR" --bg1-log-file "$HERE/WeiDU-BGEE.log" \\
    --bg2-game-directory "$BG2EE_DIR" --bg2-log-file "$HERE/WeiDU.log" \\
    --mod-directories "$MODS_DIR" --weidu-binary "$WEIDU" --language "$LANGUAGE"
""" + _sh_run())


def _sh_normal(log: str, mods_relpath: str, language: str, unresolved: bool) -> str:
    return (_sh_banner(unresolved) + "#\n# One game: GAME_DIR.\n\n"
            + _sh_common(mods_relpath, language)
            + f"""game_dir GAME_DIR "${{GAME_DIR:-}}"
GAME_DIR=$(CDPATH= cd -- "$GAME_DIR" && pwd)

set -- normal --game-directory "$GAME_DIR" --log-file "$HERE/{log}" \\
    --mod-directories "$MODS_DIR" --weidu-binary "$WEIDU" --language "$LANGUAGE"
""" + _sh_run())


# ------------------------------------------------------------- Windows cmd
def _crlf(text: str) -> str:
    """cmd.exe misparses labels and long lines in LF-only batch files."""
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


def _cmd_banner(unresolved: bool) -> str:
    text = (f"@echo off\n"
            f"rem Generated by iemod-fetch {__version__} next to the plan it installs.\n"
            f"rem Review it, then run it. iemod-fetch itself never executes it.\n"
            f"rem Needs: mod_installer.exe (https://github.com/dark0dave/mod_installer)\n"
            f"rem        and weidu.exe (https://github.com/WeiDUorg/weidu/releases).\n"
            f"rem Optional: MODS_DIR MOD_INSTALLER WEIDU LANGUAGE DRY_RUN=1\n"
            f"rem           ALLOW_EXISTING=1 MOD_INSTALLER_ARGS\n")
    if unresolved:
        text += ("rem WARNING: this plan has UNRESOLVED conflicts or order findings.\n"
                 "rem Read the iemod-fetch report before installing it.\n")
    return text + "setlocal EnableExtensions\n"


def _cmd_common(mods_relpath: str, language: str) -> str:
    rel = mods_relpath.replace("/", "\\")
    mods = rel if _is_absolute(mods_relpath) else f"%HERE%{rel}"
    return f"""set "HERE=%~dp0"
if not defined MODS_DIR set "MODS_DIR={mods}"
if not defined MOD_INSTALLER set "MOD_INSTALLER=mod_installer.exe"
if not defined WEIDU for /f "delims=" %%W in ('where weidu.exe 2^>nul') do if not defined WEIDU set "WEIDU=%%W"
if not defined LANGUAGE set "LANGUAGE={language}"
if not exist "%MODS_DIR%\\" (echo install: MODS_DIR %MODS_DIR% does not exist - fetch the mods first& exit /b 2)
if not defined WEIDU (echo install: weidu.exe not found - set WEIDU& exit /b 2)
if not exist "%WEIDU%" (echo install: WEIDU %WEIDU% does not exist& exit /b 2)
"""


def _cmd_game(var: str) -> str:
    return f"""if not defined {var} (echo install: set {var} to the game directory& exit /b 2)
if "%{var}:~-1%"=="\\" set "{var}=%{var}:~0,-1%"
if not exist "%{var}%\\chitin.key" (echo install: {var}: no chitin.key in %{var}% - not a game directory& exit /b 2)
if exist "%{var}%\\WeiDU.log" if not "%ALLOW_EXISTING%"=="1" findstr /b /c:"~" "%{var}%\\WeiDU.log" >nul && (echo install: {var} already has mods installed. The plan is for a fresh game: use a clean copy, or set ALLOW_EXISTING=1& exit /b 2)
"""


def _cmd_run(args: str) -> str:
    return f"""set "ARGS={args}"
if "%DRY_RUN%"=="1" (echo would run: "%MOD_INSTALLER%" %ARGS% %MOD_INSTALLER_ARGS%& exit /b 0)
call "%MOD_INSTALLER%" %ARGS% %MOD_INSTALLER_ARGS%
exit /b %ERRORLEVEL%
"""


def _cmd_eet(mods_relpath: str, language: str, unresolved: bool) -> str:
    args = ('eet --bg1-game-directory "%BGEE_DIR%" --bg1-log-file "%HERE%WeiDU-BGEE.log" '
            '--bg2-game-directory "%BG2EE_DIR%" --bg2-log-file "%HERE%WeiDU.log" '
            '--mod-directories "%MODS_DIR%" --weidu-binary "%WEIDU%" '
            '--language "%LANGUAGE%"')
    return (_cmd_banner(unresolved)
            + "rem EET: BGEE_DIR (pre-EET game) and BG2EE_DIR (becomes the EET game).\n"
            + _cmd_common(mods_relpath, language)
            + _cmd_game("BGEE_DIR") + _cmd_game("BG2EE_DIR") + _cmd_run(args))


def _cmd_normal(log: str, mods_relpath: str, language: str, unresolved: bool) -> str:
    args = (f'normal --game-directory "%GAME_DIR%" --log-file "%HERE%{log}" '
            f'--mod-directories "%MODS_DIR%" --weidu-binary "%WEIDU%" '
            f'--language "%LANGUAGE%"')
    return (_cmd_banner(unresolved) + "rem One game: GAME_DIR.\n"
            + _cmd_common(mods_relpath, language) + _cmd_game("GAME_DIR")
            + _cmd_run(args))
