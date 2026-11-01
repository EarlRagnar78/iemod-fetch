"""
Known upstream faults said before installing (GUI-AUDIT M8 item 65): EET's
core and a Documents folder registered with a space, on Windows. EET's
GET_USER_DIRECTORY (lib/macros.tph, still so at c26a11a, 2026-10-29) keeps
the third `reg query` token only. The batch lines below are written here in
other words to the same effect (other variables, spacing, quoting), not
EET's line.
"""
import sys
import types

import pytest

from iemod_fetch import api, install_run

QUERY = ("'reg query \"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\"
         "User Shell Folders\" /v Personal'")
CUT = f'for /F  "tokens=3,*" %%i in ({QUERY}) do set DOC_DIR=%%i\n'
CUT_VARIANTS = [
    f'FOR /f "tokens=3*" %%k IN ({QUERY}) DO (set "DOC_DIR=%%k")\n',
    f'  for  /F "tokens=3,*" %%a in ({QUERY})  do  set DOC_DIR=%%a\n',
]
WHOLE = f'for /f "tokens=3,*" %%i in ({QUERY}) do set "DOC_DIR=%%i %%j"\n'
SPACE = r"C:\Users\ann\OneDrive - Acme\Documents"
GAMES = {"BGEE": "/g/bgee", "EET": "/g/eet"}


def eet_mods(tmp_path, batch=CUT, folder="EET"):
    lib = tmp_path / "mods" / folder / "lib"
    lib.mkdir(parents=True)
    (lib / "macros.tph").write_text("DEFINE_ACTION_FUNCTION GET_USER_DIRECTORY\nBEGIN\n"
                                    + batch + "END\n")
    return str(tmp_path / "mods")


def test_a_documents_folder_with_a_space_meets_eets_cut(tmp_path):
    issues = install_run.known_issues(GAMES, eet_mods(tmp_path), documents=lambda: SPACE)
    assert len(issues) == 1
    issue = issues[0]
    # where EET writes its settings: the path up to the space, single backslashes
    assert "'C:\\Users\\ann\\OneDrive\\Baldur's Gate - Enhanced Edition Trilogy'" in issue
    assert f"registered as '{SPACE}'" in issue
    assert "game's settings (Baldur.lua" in issue and "will not see them" in issue
    assert "saves are not affected" in issue and "may fail" in issue


def test_a_variable_in_the_value_is_shown_expanded(tmp_path, monkeypatch):
    """Second review of #100: %USERPROFILE%\\OneDrive - Acme reads as the player's path."""
    monkeypatch.setenv("USERPROFILE", r"C:\Users\ann")
    issue = install_run.known_issues(GAMES, eet_mods(tmp_path),
                                     documents=lambda: r"%USERPROFILE%\OneDrive - Acme\Docs")[0]
    assert "'C:\\Users\\ann\\OneDrive\\Baldur's Gate - Enhanced Edition Trilogy'" in issue
    assert "registered as '%USERPROFILE%\\OneDrive - Acme\\Docs'" in issue


@pytest.mark.parametrize("batch", [
    f'REM for /f "tokens=3,*" %%i in ({QUERY}) do set DOC_DIR=%%i\n',          # commented out
    (f'for /f "tokens=3,*" %%i in ({QUERY}) do (set DOC_DIR=%%i\n'              # fixed in its block
     '  set "DOC_DIR=%%i %%j"\n)\n'),
])
def test_a_cut_commented_out_or_fixed_after_meets_nothing(tmp_path, batch):
    assert install_run.known_issues(GAMES, eet_mods(tmp_path, batch), documents=lambda: SPACE) == []


@pytest.mark.parametrize("batch", CUT_VARIANTS)
def test_the_same_cut_written_otherwise_is_found(tmp_path, batch):
    assert install_run.known_issues(GAMES, eet_mods(tmp_path, batch), documents=lambda: SPACE)


@pytest.mark.parametrize("value", [
    r"%USERPROFILE%\Documents",          # a user name with a space is expanded after the cut
    r"D:\Documents", None, "", "   ",
])
def test_no_space_in_the_registered_value_meets_nothing(tmp_path, value):
    assert install_run.known_issues(GAMES, eet_mods(tmp_path), documents=lambda: value) == []


def test_an_eet_that_keeps_the_whole_path_meets_nothing(tmp_path):
    mods = eet_mods(tmp_path, batch=WHOLE)
    assert install_run.known_issues(GAMES, mods, documents=lambda: r"D:\My Documents") == []


def test_no_eet_in_the_plan_or_none_downloaded_meets_nothing(tmp_path):
    mods = eet_mods(tmp_path)
    assert install_run.known_issues({"BG2EE": "/g"}, mods, documents=lambda: SPACE) == []
    assert install_run.known_issues(GAMES, str(tmp_path / "none"), documents=lambda: SPACE) == []


def test_a_resume_past_eets_core_meets_nothing(tmp_path):
    """Review of #100: EET's core already in the EET game - no warning."""
    eet = tmp_path / "eet"
    eet.mkdir()
    games = {"BGEE": str(tmp_path / "bgee"), "EET": str(eet)}
    mods = eet_mods(tmp_path)
    assert install_run.known_issues(games, mods, documents=lambda: SPACE)
    (eet / "WeiDU.log").write_text("~EET\\EET.TP2~ #0 #0 // EET core (resource importation)\n")
    assert install_run.known_issues(games, mods, documents=lambda: SPACE) == []


def test_the_eet_folder_is_found_whatever_its_case(tmp_path):
    mods = eet_mods(tmp_path, folder="eet")
    assert install_run.known_issues(GAMES, mods, documents=lambda: r"D:\My Documents")


class FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_winreg(value=None, fails=False):
    calls = []

    def open_key(root, path):
        calls.append((root, path))
        if fails:
            raise FileNotFoundError(2, "no such key")
        return FakeKey()
    module = types.SimpleNamespace(
        HKEY_CURRENT_USER="HKCU", OpenKey=open_key,
        QueryValueEx=lambda key, name: (calls.append(name) or value, 2))
    return module, calls


def test_the_registry_is_read_unexpanded_where_windows_is(monkeypatch):
    module, calls = fake_winreg(r"%USERPROFILE%\Documents")
    monkeypatch.setitem(sys.modules, "winreg", module)
    monkeypatch.setattr(sys, "platform", "win32")
    assert install_run._documents_value() == r"%USERPROFILE%\Documents"
    assert calls == [("HKCU", install_run._SHELL_FOLDERS), "Personal"]


def test_an_unreadable_registry_is_none(monkeypatch):
    module, _calls = fake_winreg(fails=True)
    monkeypatch.setitem(sys.modules, "winreg", module)
    monkeypatch.setattr(sys, "platform", "win32")
    assert install_run._documents_value() is None


def test_off_windows_the_registry_is_not_read(monkeypatch):
    monkeypatch.setitem(sys.modules, "winreg", None)       # importing it would fail
    monkeypatch.setattr(sys, "platform", "linux")
    assert install_run._documents_value() is None


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows registry")
def test_on_windows_the_registered_value_is_read():
    value = install_run._documents_value()
    # a runner's own value: unexpanded (%USERPROFILE%) or a drive or UNC path
    assert value is None or (isinstance(value, str) and value.strip() and (
        "%" in value or value[1:3] == ":\\" or value.startswith("\\\\")))


def test_the_api_says_the_same(tmp_path, monkeypatch):
    monkeypatch.setattr(install_run, "_documents_value", lambda: r"D:\My Documents")
    assert api.install_known_issues(GAMES, eet_mods(tmp_path))


@pytest.mark.parametrize("after", [
    'set "DOC_DIR=%%i %%j"\n',                     # after a one-line for: %%i is not its variable
    'REM set "DOC_DIR=%%i %%j"\n',
    '// was: set "DOC_DIR=%%i %%j"\n',
    "echo x\n" * 50 + 'set "DOC_DIR=%%i %%j"\n',   # far away, another function
])
def test_a_line_that_does_not_fix_the_cut_does_not_hide_it(tmp_path, after):
    """Review of #100: only a whole-path set inside the cut's own block fixes it."""
    mods = eet_mods(tmp_path, CUT + after)
    assert install_run.known_issues(GAMES, mods, documents=lambda: SPACE)


def test_a_block_that_closes_before_a_fix_is_still_cut(tmp_path):
    batch = (f'for /f "tokens=3,*" %%i in ({QUERY}) do (set DOC_DIR=%%i\n'
             '  REM set "DOC_DIR=%%i %%j"\n)\nset "DOC_DIR=%%i %%j"\n')
    assert install_run.known_issues(GAMES, eet_mods(tmp_path, batch), documents=lambda: SPACE)


@pytest.mark.parametrize("batch", [
    f'@for /f "tokens=3,*" %%i in ({QUERY}) do set DOC_DIR=%%i\n',
    f'for /f "tokens=3,*" %%i in ({QUERY}) do(set DOC_DIR=%%i)\n',
])
def test_an_at_sign_or_a_tight_parenthesis_is_the_same_cut(tmp_path, batch):
    assert install_run.known_issues(GAMES, eet_mods(tmp_path, batch), documents=lambda: SPACE)


@pytest.mark.parametrize("batch", [
    (f'for /f "tokens=3,*" %%i in ({QUERY}) do (set DOC_DIR=%%i\n'
     '  if not "%%j"=="" (\n    echo "a ) in quotes"\n  ) else (\n    echo none\n  )\n'
     '  set "DOC_DIR=%%i %%j"\n)\n'),
    (f'for /f "tokens=3,*" %%i in ({QUERY}) do (set DOC_DIR=%%i\n'
     '  echo one ^) escaped\n  set "DOC_DIR=%%i %%j"\n)\n'),
])
def test_a_block_nested_before_the_fix_does_not_close_the_cuts_block(tmp_path, batch):
    """Review of #100's merge: `if (` over lines and `) else (` before the
    fix, a `)` in quotes or escaped with ^, leave the cut's block open."""
    assert install_run.known_issues(GAMES, eet_mods(tmp_path, batch), documents=lambda: SPACE) == []


def test_a_fix_inside_a_nested_block_depends_on_its_condition_and_does_not_count(tmp_path):
    batch = (f'for /f "tokens=3,*" %%i in ({QUERY}) do (set DOC_DIR=%%i\n'
             '  if defined X (\n    set "DOC_DIR=%%i %%j"\n  )\n)\n')
    assert install_run.known_issues(GAMES, eet_mods(tmp_path, batch), documents=lambda: SPACE)
