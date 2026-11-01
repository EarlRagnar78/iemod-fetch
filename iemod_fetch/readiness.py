"""
Is there room, and the right WeiDU, before an install starts (GUI-AUDIT M8
item 49, ADR-0055)? Each finding is a warning in words, never a refusal:
the player decides.

- **A backup's room**: the exact bytes a backup of each game copies
  (backup.size, what create() copies) against the free space where backups
  go.
- **The install's room**: on each game's drive, an upper estimate - the
  staged mods' bytes (what WeiDU may copy into the game) plus what a backup
  copies (what WeiDU may back up before it overwrites, into each mod's
  backup folder in the game). An estimate, said as one.
- **WeiDU**: its `--version` against the one this program is tested with
  (toolchain.VERIFIED), and against the highest `WEIDU_VER >= N` a staged
  mod's tp2, tpa or tph requires.
"""
import os
import re
import shutil
from collections.abc import Callable

from . import backup, toolchain

_NEEDS = re.compile(r"\bWEIDU_VER\s*(?P<op>>=|>)\s*(?P<version>\d{5})", re.IGNORECASE)
_SOURCES = (".tp2", ".tpa", ".tph")


def _free(path: str) -> int | None:
    """Free bytes on the drive `path` is on (its nearest existing folder)."""
    while path and not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent
    try:
        return shutil.disk_usage(path or ".").free
    except OSError:
        return None


def _tree_size(folder: str) -> int:
    total = 0
    for here, _dirs, names in os.walk(folder):
        for name in names:
            full = os.path.join(here, name)
            if not os.path.islink(full):
                try:
                    total += os.path.getsize(full)
                except OSError:
                    continue
    return total


def _gib(count: int) -> str:
    return f"{count / 2**30:,.1f} GiB" if count >= 2**30 else f"{count / 2**20:,.0f} MiB"


def weidu_needed(mods_dir: str) -> tuple[int, str] | None:
    """The highest WeiDU a staged mod requires (`WEIDU_VER >= N`, or `> N`
    as N + 1), with the file that says so; None when none says."""
    best: tuple[int, str] | None = None
    for here, _dirs, names in os.walk(mods_dir):
        for name in names:
            if not name.lower().endswith(_SOURCES):
                continue
            path = os.path.join(here, name)
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            for match in _NEEDS.finditer(text):
                needed = int(match["version"]) + (1 if match["op"] == ">" else 0)
                if best is None or needed > best[0]:
                    best = (needed, os.path.relpath(path, mods_dir))
    return best


def _nearest(path: str) -> str:
    while path and not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path or "."


def _device(path: str) -> object:
    """Which drive `path` is on: its nearest existing folder's device; the
    path itself when that cannot be read (measured on its own)."""
    try:
        return os.stat(_nearest(path)).st_dev
    except OSError:
        return path


def findings(games: dict[str, str], mods_dir: str, weidu: str | None,
             backups_dir: str | None = None,
             free: Callable[[str], int | None] = _free,
             version: Callable[[str, str], str | None] = toolchain.version_of,
             device: Callable[[str], object] = _device) -> list[str]:
    """What may stop the install or its backup, in words; [] when nothing.

    What lands on one drive is added up: in EET, BG:EE, EET and the backups
    folder are often on the same one (review of #114)."""
    out: list[str] = []
    staged = _tree_size(mods_dir) if os.path.isdir(mods_dir) else 0
    sizes = {name: backup.size(folder) for name, folder in games.items()
             if os.path.isfile(os.path.join(folder, "chitin.key"))}
    # drive -> (a path on it, [(what, bytes)])
    drives: dict[object, tuple[str, list[tuple[str, int]]]] = {}

    def need(path: str, what: str, count: int) -> None:
        drives.setdefault(device(path), (path, []))[1].append((what, count))

    if backups_dir is not None and sizes:
        need(backups_dir, f"the backup in {backups_dir}", sum(sizes.values()))
    staged_on: set[object] = set()
    for name, folder in games.items():
        if name not in sizes:
            continue
        # the staged mods once a drive (each goes into one game); what WeiDU
        # may back up, at most what a backup copies, for each game
        mods_here = staged if device(folder) not in staged_on else 0
        staged_on.add(device(folder))
        need(folder, f"the install into {name}", mods_here + sizes[name])
    for path, needs in drives.values():
        total = sum(count for _what, count in needs)
        room = free(path)
        if room is None or room >= total:
            continue
        parts = "; ".join(f"{what}: {_gib(count)}" for what, count in needs)
        estimate = (" (an estimate for an install: the staged mods and what WeiDU may "
                    "back up)" if any(w.startswith("the install") for w, _c in needs) else "")
        out.append(f"{_gib(total)} may be needed on the drive of {path}{estimate} - "
                   f"{parts}; {_gib(room)} is free there")
    if weidu:
        have = version(toolchain.WEIDU, weidu)
        tested = max(int(v) for v in toolchain.VERIFIED[toolchain.WEIDU])
        if have is not None and have.isdigit():
            if int(have) < tested:
                out.append(f"WeiDU {have} is older than {tested}, the one this program is "
                           f"tested with")
            required = weidu_needed(mods_dir) if os.path.isdir(mods_dir) else None
            if required and int(have) < required[0]:
                out.append(f"WeiDU {have} is older than {required[0]}, which {required[1]} "
                           f"requires (WEIDU_VER)")
    return out
