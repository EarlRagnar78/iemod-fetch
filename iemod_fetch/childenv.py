"""
The environment a program started by this one gets (review of #70).

Inside a PyInstaller bundle on Linux, the bootloader puts the bundle's own
library folder first on LD_LIBRARY_PATH (macOS: DYLD_LIBRARY_PATH), and a
child inherits it: `git`, `gh`, 7-Zip or unrar would load the bundle's
OpenSSL, zlib or liblzma instead of the system's, and fail on a system whose
tools want newer ones - `git credential fill` failing that way leaves the run
anonymous without a word. PyInstaller keeps the value from before it started
in `<NAME>_ORIG`; a child gets that back, or nothing. Outside a bundle the
environment is inherited unchanged.

On Windows the bootloader instead calls SetDllDirectoryW with the bundle's
`_internal`, and a process it creates inherits that DLL directory (GUI-AUDIT
item 61, ADR-0058). It is not in the environment, so `popen` and `run` clear
it only while the child is created - under one lock, since it belongs to the
whole process - and put it back at once: the wizard's own loading (Qt's
plugins, Python's extension modules) sees it as before.
"""
import contextlib
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator, Mapping

_PATHS = ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH")


def child_env(extra: Mapping[str, str] | None = None) -> dict[str, str] | None:
    """The `env=` for subprocess.run: None (inherit) unless frozen or `extra`."""
    if not getattr(sys, "frozen", False):
        return dict(os.environ, **extra) if extra else None
    env = dict(os.environ)
    for name in _PATHS:
        original = env.pop(name + "_ORIG", None)
        if original is not None:
            env[name] = original
        else:
            env.pop(name, None)
    env.update(extra or {})
    return env


_SPAWN = threading.RLock()          # the DLL directory is the process's, not a thread's


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.GetDllDirectoryW.argtypes = (wintypes.DWORD, wintypes.LPWSTR)
    _kernel32.GetDllDirectoryW.restype = wintypes.DWORD
    _kernel32.SetDllDirectoryW.argtypes = (wintypes.LPCWSTR,)
    _kernel32.SetDllDirectoryW.restype = wintypes.BOOL

    def _get_dll_directory() -> str | None:
        buffer = ctypes.create_unicode_buffer(32768)
        return buffer.value if _kernel32.GetDllDirectoryW(len(buffer), buffer) else None

    def _set_dll_directory(path: str | None) -> None:
        _kernel32.SetDllDirectoryW(path)

    _API: tuple[Callable[[], str | None], Callable[[str | None], None]] | None = (
        _get_dll_directory, _set_dll_directory)
else:
    _API = None


def _dll_directory_api() -> tuple[Callable[[], str | None],
                                  Callable[[str | None], None]] | None:
    """(get, set) of kernel32's DLL directory, or None where there is none
    to clear: off Windows, or outside a bundle."""
    return _API if getattr(sys, "frozen", False) else None


@contextlib.contextmanager
def spawning() -> Iterator[None]:
    """Around the creation of a child (not its whole run): on Windows, in a
    bundle, the DLL directory is cleared for it and put back after."""
    api = _dll_directory_api()
    if api is None:
        yield
        return
    get, set_ = api
    with _SPAWN:
        before = get()
        try:
            set_(None)
            yield
        finally:
            set_(before or None)


def popen(args, **kwargs) -> subprocess.Popen:
    """subprocess.Popen, created under `spawning`."""
    with spawning():
        return subprocess.Popen(args, **kwargs)  # noqa: S603 (the caller's program)


def run(args, *, input=None, timeout=None, check=False,  # noqa: A002 (subprocess.run's name)
        capture_output=False, **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run whose child is created under `spawning`; outside a
    Windows bundle it is subprocess.run itself."""
    if _dll_directory_api() is None:
        return subprocess.run(args, input=input, timeout=timeout, check=check,  # noqa: S603
                              capture_output=capture_output, **kwargs)
    # subprocess.run's own refusals, not a silent override (review of #121)
    if capture_output:
        if kwargs.get("stdout") is not None or kwargs.get("stderr") is not None:
            raise ValueError("stdout and stderr arguments may not be used with capture_output.")
        kwargs["stdout"] = kwargs["stderr"] = subprocess.PIPE
    if input is not None:
        if kwargs.get("stdin") is not None:
            raise ValueError("stdin and input arguments may not both be used.")
        kwargs["stdin"] = subprocess.PIPE
    with popen(args, **kwargs) as process:
        try:
            out, err = process.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            exc.stdout, exc.stderr = process.communicate()
            raise
        except BaseException:
            process.kill()
            raise
        code = process.wait()
    if check and code:
        raise subprocess.CalledProcessError(code, process.args, out, err)
    return subprocess.CompletedProcess(process.args, code, out, err)
