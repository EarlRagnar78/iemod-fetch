"""
A program the bundle starts gets the system's libraries, not the bundle's
(review of #70): PyInstaller's bootloader puts `_internal` first on
LD_LIBRARY_PATH, and git, gh, 7-Zip and unrar would inherit it.
"""
import subprocess
import sys

import pytest

from iemod_fetch import archives, auth, childenv
from iemod_fetch.childenv import child_env


def test_outside_a_bundle_the_environment_is_inherited(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert child_env() is None
    monkeypatch.setenv("KEEP", "1")
    assert child_env({"X": "y"})["KEEP"] == "1"


def test_in_a_bundle_a_child_gets_the_library_path_from_before(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/iemod-fetch/_internal")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/local/lib")
    env = child_env({"GIT_TERMINAL_PROMPT": "0"})
    assert env["LD_LIBRARY_PATH"] == "/usr/local/lib"
    assert "LD_LIBRARY_PATH_ORIG" not in env and env["GIT_TERMINAL_PROMPT"] == "0"


def test_in_a_bundle_with_no_path_before_the_child_gets_none(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/iemod-fetch/_internal")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/Applications/x/_internal")
    env = child_env()
    assert "LD_LIBRARY_PATH" not in env and "DYLD_LIBRARY_PATH" not in env


@pytest.mark.parametrize("call", ["gh", "git", "7z-list", "extract"])
def test_every_program_started_gets_that_environment(monkeypatch, tmp_path, call):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/iemod-fetch/_internal")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    seen = []

    def fake_run(cmd, **kw):
        seen.append(kw.get("env"))
        return subprocess.CompletedProcess(cmd, 1, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    # the environment only: on Windows a frozen run creates its child with
    # Popen under the DLL-directory lock, tested below
    monkeypatch.setattr(childenv, "_dll_directory_api", lambda: None)
    monkeypatch.setattr(archives, "find_tool", lambda name: "/usr/bin/" + name)
    archive = tmp_path / "a.7z"
    archive.write_bytes(b"7z\xbc\xaf\x27\x1c" + b"\0" * 32)
    if call == "gh":
        auth._from_gh_cli()
    elif call == "git":
        auth._from_git_credential()
    elif call == "7z-list":
        archives._seven_zip_listing(str(archive))
    else:
        with pytest.raises(archives.ExtractionError):
            archives._extract_external(str(archive), str(tmp_path / "out"), archives.Kind.SEVENZIP)
    assert seen, "no program was started"
    assert all(env is not None and "LD_LIBRARY_PATH" not in env for env in seen)


# --- the DLL directory on Windows (GUI-AUDIT item 61, ADR-0058) -------------

_PRINT_DLL_DIRECTORY = (
    "import ctypes\n"
    "b = ctypes.create_unicode_buffer(32768)\n"
    "ctypes.windll.kernel32.GetDllDirectoryW(32768, b)\n"
    "print(b.value)\n")


class _FakeDllDirectory:
    """kernel32's DLL directory, as a value the test can watch."""

    def __init__(self, value):
        self.value, self.calls = value, []

    def get(self):
        return self.value

    def set(self, value):
        self.calls.append(value)
        self.value = value


def _fake_bundle(monkeypatch, value="C:\\iemod-fetch\\_internal"):
    fake = _FakeDllDirectory(value)
    monkeypatch.setattr(childenv, "_dll_directory_api", lambda: (fake.get, fake.set))
    return fake


def test_a_child_is_created_with_no_dll_directory_and_it_is_put_back(monkeypatch):
    fake = _fake_bundle(monkeypatch)
    seen = []
    real_popen = subprocess.Popen

    def popen(args, **kw):
        seen.append(fake.value)
        return real_popen(args, **kw)

    monkeypatch.setattr(subprocess, "Popen", popen)
    done = childenv.run([sys.executable, "-c", "print('hi')"], capture_output=True)
    assert seen == [None] and done.returncode == 0 and done.stdout.strip() == b"hi"
    assert fake.calls == [None, "C:\\iemod-fetch\\_internal"]
    assert fake.value == "C:\\iemod-fetch\\_internal"


def test_none_before_is_left_none(monkeypatch):
    fake = _fake_bundle(monkeypatch, value=None)
    childenv.popen([sys.executable, "-c", "pass"]).wait()
    assert fake.calls == [None, None]


def test_the_directory_is_put_back_when_the_program_cannot_start(monkeypatch, tmp_path):
    fake = _fake_bundle(monkeypatch)
    with pytest.raises(OSError):
        childenv.run([str(tmp_path / "no-such-program")])
    assert fake.value == "C:\\iemod-fetch\\_internal"


def test_run_in_a_bundle_answers_as_subprocess_run(monkeypatch):
    _fake_bundle(monkeypatch)
    echo = [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())"]
    done = childenv.run(echo, input=b"abc", stdout=subprocess.PIPE, check=True)
    assert done.stdout == b"ABC" and done.args == echo
    with pytest.raises(subprocess.CalledProcessError) as failed:
        childenv.run([sys.executable, "-c", "raise SystemExit(3)"], check=True)
    assert failed.value.returncode == 3
    with pytest.raises(subprocess.TimeoutExpired):
        childenv.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)


def test_creations_from_two_threads_do_not_interleave(monkeypatch):
    """The DLL directory is the process's: one thread's put-back must not
    land while another thread's child is being created."""
    import threading
    fake = _fake_bundle(monkeypatch)
    real_popen = subprocess.Popen
    seen = []

    def popen(args, **kw):
        seen.append(fake.value)
        return real_popen(args, **kw)

    monkeypatch.setattr(subprocess, "Popen", popen)
    threads = [threading.Thread(target=lambda: childenv.run([sys.executable, "-c", "pass"]))
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert seen == [None] * 8
    assert fake.calls == [None, "C:\\iemod-fetch\\_internal"] * 8


def test_outside_a_bundle_nothing_is_touched(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert childenv._dll_directory_api() is None
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: seen.append(args) or
                        subprocess.CompletedProcess(args, 0, b"", b""))
    childenv.run(["x"], check=False)
    assert seen == [["x"]]


@pytest.mark.skipif(sys.platform != "win32", reason="kernel32's DLL directory")
def test_on_windows_a_child_inherits_the_dll_directory_unless_cleared(monkeypatch, tmp_path):
    """Measured, not assumed: what PyInstaller's bootloader does
    (SetDllDirectoryW with `_internal`), then a child started both ways."""
    import ctypes
    kernel32 = ctypes.windll.kernel32
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert kernel32.SetDllDirectoryW(str(tmp_path))
    try:
        command = [sys.executable, "-c", _PRINT_DLL_DIRECTORY]
        plain = subprocess.run(command, capture_output=True, text=True, check=True)
        cleared = childenv.run(command, capture_output=True, text=True, check=True)
        buffer = ctypes.create_unicode_buffer(32768)
        kernel32.GetDllDirectoryW(32768, buffer)
    finally:
        kernel32.SetDllDirectoryW(None)
    assert plain.stdout.strip() == str(tmp_path)        # inherited
    assert cleared.stdout.strip() == ""                 # not, through childenv
    assert buffer.value == str(tmp_path)                # this process keeps its own


def test_run_in_a_bundle_refuses_what_subprocess_run_refuses(monkeypatch):
    _fake_bundle(monkeypatch)
    with pytest.raises(ValueError):
        childenv.run([sys.executable, "-c", "pass"], capture_output=True,
                     stdout=subprocess.DEVNULL)
    with pytest.raises(ValueError):
        childenv.run([sys.executable, "-c", "pass"], input=b"x", stdin=subprocess.DEVNULL)


def test_spawning_nests_without_a_deadlock(monkeypatch):
    fake = _fake_bundle(monkeypatch)
    with childenv.spawning(), childenv.spawning():
        assert fake.value is None
    assert fake.value == "C:\\iemod-fetch\\_internal"
