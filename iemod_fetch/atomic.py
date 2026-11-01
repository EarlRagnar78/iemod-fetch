"""
Write a file whole or not at all (GUI-AUDIT M7 item 46).

Eight places wrote `path + ".tmp"` and renamed it over `path`. That fixed temp
name was shared: two runs saving the same file wrote into one temp, and a
crash left it behind. Here each write gets its own temp beside the target
(the rename stays on one file system), removed if anything fails, and the
target keeps the permissions it had.
"""
import contextlib
import errno
import os
import secrets
import shutil
import time
from collections.abc import Callable
from typing import Any

# Windows: a file another program holds open for a moment - an antivirus
# scanning what was just written, the search indexer - cannot be renamed until
# it lets go (GUI-AUDIT M8 item 66). ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION,
# ERROR_LOCK_VIOLATION. Retried 12 times, waiting 10 ms doubling to 1 s, about
# 5.3 s in all - Chriz Easy BG's measure (engine/src/fs_retry.rs, MIT, read at
# 508256a; the idea, not its code).
_HELD = frozenset({5, 32, 33})
ATTEMPTS, FIRST_WAIT_S, LONGEST_WAIT_S = 12, 0.01, 1.0
PATIENT_S = 5.3          # a download, an extraction, a backup: off the GUI's thread
BRIEF_S = 0.15           # a small file written while the window waits (review of #102)


def _for_good(target: str) -> bool:
    """ERROR_ACCESS_DENIED that no wait ends: the target is a folder that is
    already there, or a read-only file (review of #102)."""
    return os.path.isdir(target) or (os.path.isfile(target) and not os.access(target, os.W_OK))


def retried(operation: Callable[..., Any], *args: Any, windows: bool | None = None,
            sleep: Callable[[float], Any] = time.sleep, budget_s: float = PATIENT_S,
            for_good: Callable[[], bool] = lambda: False) -> Any:
    """`operation(*args)`, tried again while Windows says another program holds
    the file, waiting at most `budget_s` in all; any other error, an access
    denial `for_good` says no wait ends, and every error elsewhere, at once."""
    windows = os.name == "nt" if windows is None else windows
    wait, waited = FIRST_WAIT_S, 0.0
    for attempt in range(ATTEMPTS):
        try:
            return operation(*args)
        except PermissionError as exc:
            code = getattr(exc, "winerror", None)
            if (not windows or code not in _HELD or attempt == ATTEMPTS - 1
                    or waited + wait > budget_s + 1e-9 or (code == 5 and for_good())):
                raise
        sleep(wait)
        waited += wait
        wait = min(wait * 2, LONGEST_WAIT_S)
    raise AssertionError("unreachable")           # the last attempt returns or raises


def replace(source: str, target: str, budget_s: float = PATIENT_S) -> None:
    """os.replace, waiting out a file held for a moment on Windows."""
    retried(os.replace, source, target, budget_s=budget_s, for_good=lambda: _for_good(target))


def rename(source: str, target: str, budget_s: float = PATIENT_S) -> None:
    """os.rename, waiting out a file held for a moment on Windows."""
    retried(os.rename, source, target, budget_s=budget_s, for_good=lambda: _for_good(target))


def move(source: str, target: str) -> None:
    """A rename on one file system, waiting out a held file; shutil.move only
    across file systems. Not shutil.move alone: when Windows refuses the
    rename of a held file it copies and then deletes, and a held file left
    behind splits the move in two."""
    try:
        replace(source, target)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.move(source, target)


def write_text(path: str, text: str, *, durable: bool = False) -> None:
    """
    Replace `path` with `text` (UTF-8) in one rename: a reader sees the old
    file or the new one, never half of it.

    A new file is readable by its owner only - the config may hold a token,
    the state and reports name the player's folders; an existing file keeps
    the mode its owner gave it.

    durable: flush to disk before the rename, and the folder after it on
        POSIX, for state that must survive a power cut (what was installed).
    """
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    try:
        mode = os.stat(path).st_mode & 0o7777
    except OSError:
        mode = None
    temp = os.path.join(folder, f".{os.path.basename(path)}.{secrets.token_hex(6)}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            if durable:
                fh.flush()
                os.fsync(fh.fileno())
        if mode is not None:
            os.chmod(temp, mode)
        replace(temp, path, budget_s=BRIEF_S)    # the GUI's thread may wait on it
    except BaseException:
        with contextlib.suppress(OSError):
            os.chmod(temp, 0o600)       # Windows refuses to delete a read-only file
            os.unlink(temp)
        raise
    if durable and os.name == "posix":
        # The file is in place: a folder that cannot be flushed (some network
        # and FUSE file systems answer EINVAL) does not make the write fail.
        with contextlib.suppress(OSError):
            dir_fd = os.open(folder, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
