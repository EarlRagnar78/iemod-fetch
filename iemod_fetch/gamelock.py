"""
The game not running while it is installed into (GUI-AUDIT M8 item 67,
ADR-0051).

Two checks, before an install or a resume starts:

- no running program whose executable is in a game folder: the game itself,
  a launcher (InfinityLoader, EEex), a mod's own setup-*.exe or another
  WeiDU working on it;
- on Windows, every `dialog*.tlk` of the game opens with no sharing at all:
  a program holding one (the game, an editor such as Near Infinity) makes
  WeiDU fail when it writes it, at the end of a component.

mod_installer starts WeiDU for each batch itself, right after it logs the
batch (16.0.0: installers.rs L144, runner.rs L198), so nothing lets this
program check *before* a batch. During the run only the processes are looked
at again, at each batch, and a game started meanwhile is said, not stopped:
the dialog.tlk check cannot run then, WeiDU itself holds the file.

The idea, and the two checks, are Chriz Easy BG's (`engine/src/preflight.rs`
L399 and L735, MIT); the code is written here.

Under Wine or Proton (Linux) /proc's executable is Wine's loader: the game's
path is read from the command line too, Z: as / and another drive through
the prefix's dosdevices.

What is not seen: a process this user may not inspect (another account's,
which /proc refuses with EACCES and which is skipped; an elevated one on
Windows), and on macOS a game whose executable is outside
the folder given (an .app's Contents/MacOS when the folder is its
Contents/Resources). A listing that fails says nothing rather than refusing.
"""
import contextlib
import os
import posixpath
import subprocess
import sys
import time
from collections.abc import Callable, Iterable

SHARING_VIOLATION, LOCK_VIOLATION = 32, 33
HELD_TRIES, HELD_WAIT_S = 5, 0.03     # a scanner's moment on dialog.tlk: about 0.12 s

# One running program, seen at one path: its executable, or under Wine
# (Linux) the game's own path from its command line.
Running = tuple[int, str]             # (pid, path)
_WINE = ("wine", "wine64", "wine-preloader", "wine64-preloader")


def _read(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _wine_path(arg: str, prefix: str | None) -> str | None:
    """A path as a Windows program under Wine sees it, on this system:
    Z: is /, another drive is the prefix's dosdevices link."""
    if arg.startswith("/"):
        return arg
    if len(arg) > 2 and arg[1] == ":" and arg[2] in "\\/":
        rest = arg[3:].replace("\\", "/")
        if arg[0].lower() == "z":
            return "/" + rest
        if prefix:
            # a Linux path: posixpath, not os.path (C: would reset it on Windows)
            return posixpath.join(prefix, "dosdevices", arg[0].lower() + ":", rest)
    return None


def _wine_paths(pid: str, exe: str) -> list[str]:
    """Where a Wine (or Proton) process's game is: its command line's first
    two words (`wine64-preloader C:\\...\\Baldur.exe`, or the .exe as
    argv[0]) - for a Windows program /proc's exe is Wine's loader, not the
    game (review of #105)."""
    argv = [a.decode("utf-8", "replace") for a in _read(f"/proc/{pid}/cmdline").split(b"\0")
            if a]
    if not (os.path.basename(exe) in _WINE
            or any(a.lower().endswith(".exe") for a in argv[:2])):
        return []
    env = dict(item.split("=", 1) for item in
               _read(f"/proc/{pid}/environ").decode("utf-8", "replace").split("\0")
               if "=" in item) if os.access(f"/proc/{pid}/environ", os.R_OK) else {}
    prefix = env.get("WINEPREFIX") or (os.path.join(env["HOME"], ".wine")
                                       if "HOME" in env else None)
    # not its working folder: Wine's own helpers (services.exe,
    # explorer.exe) may inherit the game's and stay after it closes
    return [path for arg in argv[:2] if (path := _wine_path(arg, prefix))]


def _linux() -> list[Running]:
    """The processes /proc lets this user read; another user's are refused
    (EACCES) and skipped, not an error."""
    found: list[Running] = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            exe = os.readlink(f"/proc/{pid}/exe")
        except OSError:
            continue
        found.append((int(pid), exe))
        with contextlib.suppress(OSError):
            found += [(int(pid), path) for path in _wine_paths(pid, exe)]
    return found


def _macos() -> list[Running]:
    """ps's pids and command paths (comm, full path on macOS)."""
    out = subprocess.run(["/bin/ps", "-axww", "-o", "pid=,comm="],  # noqa: S603 (fixed)
                         capture_output=True, text=True, timeout=10, check=True).stdout
    found: list[Running] = []
    for line in out.splitlines():
        pid, _, path = line.strip().partition(" ")
        if pid.isdigit() and path.strip().startswith("/"):
            found.append((int(pid), path.strip()))
    return found


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _QUERY_LIMITED = 0x1000           # PROCESS_QUERY_LIMITED_INFORMATION
    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
        wintypes.DWORD, wintypes.HANDLE)
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _INVALID = wintypes.HANDLE(-1).value

    def _windows() -> list[Running]:
        """Every process's image path that OpenProcess lets this user query."""
        pids = (wintypes.DWORD * 8192)()
        got = wintypes.DWORD()
        if not _kernel32.K32EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(got)):
            raise ctypes.WinError(ctypes.get_last_error())
        found: list[Running] = []
        for pid in pids[:got.value // ctypes.sizeof(wintypes.DWORD)]:
            handle = _kernel32.OpenProcess(_QUERY_LIMITED, False, pid)
            if not handle:
                continue
            try:
                size = wintypes.DWORD(32768)
                buffer = ctypes.create_unicode_buffer(size.value)
                if _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                    found.append((int(pid), buffer.value))
            finally:
                _kernel32.CloseHandle(handle)
        return found

    def _open_alone(path: str) -> int:
        """0 when `path` opens for reading and writing with no sharing, else
        the Windows error (32: another program has it open)."""
        handle = _kernel32.CreateFileW(path, 0xC0000000, 0, None, 3, 0x80, None)
        if handle == _INVALID or handle is None:
            return ctypes.get_last_error()
        _kernel32.CloseHandle(handle)
        return 0

# How this system lists its processes, and opens a file alone (Windows only:
# elsewhere nothing locks a file against WeiDU)
_LIST: Callable[[], list[Running]]
_OPEN_ALONE: Callable[[str], int] | None = None
if sys.platform == "win32":
    _LIST, _OPEN_ALONE = _windows, _open_alone
elif sys.platform == "darwin":
    _LIST = _macos
else:
    _LIST = _linux                    # no /proc: an OSError, so None


def running_executables() -> list[Running] | None:
    """(pid, path) for the running processes this user can see; None when
    they could not be listed."""
    try:
        return _LIST()
    except (OSError, subprocess.SubprocessError):
        return None


def _under(path: str, folder: str) -> bool:
    try:
        path = os.path.normcase(os.path.realpath(path))
        folder = os.path.normcase(os.path.realpath(folder))
        return os.path.commonpath([path, folder]) == folder
    except (OSError, ValueError):     # another drive
        return False


def running_in(folders: dict[str, str], running: Iterable[Running] | None,
               ignore: Iterable[str] = ()) -> list[str]:
    """`name: path (pid N)` for each process seen under one of the folders
    ({name: folder}), once per process, but this install's own tools
    (`ignore`) and this program's own process and executable."""
    if running is None:
        return []
    # this program itself is never the game, even unpacked into its folder
    # (the Windows zip or the GUI beside Baldur.exe): it cannot be closed by
    # the player it is asking (review of #105)
    skip = {os.path.normcase(os.path.realpath(path))
            for path in (*ignore, sys.executable) if path}
    found, seen = [], {os.getpid()}
    for pid, path in dict.fromkeys(running):          # the executable first
        if pid in seen or os.path.normcase(os.path.realpath(path)) in skip:
            continue
        for name, folder in folders.items():
            if _under(path, folder):
                found.append(f"{name}: {path} (pid {pid})")
                seen.add(pid)
                break
    return found


def _entries(folder: str) -> list[os.DirEntry]:
    try:
        with os.scandir(folder) as it:
            return list(it)
    except OSError:
        return []


def _tlks(folder: str) -> list[str]:
    return [entry.path for entry in _entries(folder)
            if entry.name.lower().startswith("dialog") and entry.name.lower().endswith(".tlk")
            and entry.is_file()]


def talk_tables(folder: str) -> list[str]:
    """The game's dialog*.tlk: in lang/*/ (the Enhanced Editions) and at its
    root, whatever the case of the names (Linux)."""
    found = _tlks(folder)
    for lang in _entries(folder):
        if lang.name.lower() == "lang" and lang.is_dir():
            for language in _entries(lang.path):
                if language.is_dir():
                    found += _tlks(language.path)
    return sorted(found)


def held_talk_tables(folders: dict[str, str],
                     open_alone: Callable[[str], int] | None = None,
                     sleep: Callable[[float], None] = time.sleep) -> list[str]:
    """`name: path (why)` for each dialog*.tlk another program holds open.
    A file held is tried again for a moment first: an antivirus or the
    indexer opens it briefly (review of #105). Windows only (elsewhere
    nothing locks a file against WeiDU), unless `open_alone` is given."""
    open_alone = open_alone or _OPEN_ALONE
    if open_alone is None:
        return []
    held = []
    for name, folder in folders.items():
        for path in talk_tables(folder):
            error = open_alone(path)
            for _ in range(HELD_TRIES - 1):
                if error not in (SHARING_VIOLATION, LOCK_VIOLATION):
                    break
                sleep(HELD_WAIT_S)
                error = open_alone(path)
            if error in (SHARING_VIOLATION, LOCK_VIOLATION):
                held.append(f"{name}: {path} is open in another program (the game, "
                            "Near Infinity, an editor)")
            elif error:
                held.append(f"{name}: {path} cannot be opened for writing "
                            f"(Windows error {error})")
    return held


def problems(folders: dict[str, str],
             running: Callable[[], list[Running] | None] = running_executables,
             open_alone: Callable[[str], int] | None = None,
             sleep: Callable[[float], None] = time.sleep) -> list[str]:
    """What says the game is in use, in words, each with what to do; []
    when nothing. There is no "install anyway": what stops the install is
    closed by the player (review of #105)."""
    found = [f"the game is running: {line} - close it and try again"
             for line in running_in(folders, running())]
    found += [f"{line} - close it and try again"
              for line in held_talk_tables(folders, open_alone, sleep)]
    return found
