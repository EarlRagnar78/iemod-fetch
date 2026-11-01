"""
Staged, atomic, non-destructive installation.

Invariants (ADR-0007):
  * everything is extracted into a staging directory first;
  * the destination is only touched once the staged tree has been verified to
    contain the .tp2 that identifies this mod;
  * an existing destination is never deleted - it is moved aside to a backup
    directory, and only when --force is given;
  * a failure at any point leaves the destination exactly as it was.
"""
import contextlib
import json
import os
import shutil
import stat
import time
import uuid
from dataclasses import dataclass, field

from . import atomic
from .atomic import write_text
from .archives import safe_extract
from .errors import InstallConflict, NotThisMod, VerificationFailed
from .naming import matches_tp2, safe_component
from .tp2 import Tp2Info, read_mod_tp2

STATE_FILENAME = ".iemod-fetch-state.json"
STAGING_DIR = ".staging"
BACKUP_DIR = ".backup"


@dataclass
class InstallOutcome:
    folder: str                       # the directory actually created
    dest: str
    tp2_file: str
    backup: str | None = None
    file_count: int = 0
    renamed_from: str | None = None   # WeiDU folder, when it differed
    tp2_info: Tp2Info | None = None   # what the mod says about itself

    @property
    def version(self) -> str | None:
        return self.tp2_info.version if self.tp2_info else None


def find_tp2_files(root: str) -> list[str]:
    found = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.lower().endswith(".tp2"):
                found.append(os.path.join(dirpath, name))
    return sorted(found, key=lambda p: (p.count(os.sep), p))


def verify_mod_dir(mod_dir: str, folder: str,
                   expect_tp2: str | None = None) -> str | None:
    """
    Return the .tp2 filename proving `mod_dir` really contains this mod, or None.

    Strict: an unrelated .tp2 does not count (legacy defect L1). `expect_tp2`
    widens the accepted set by exactly one known-good name - the tp2 the mod
    genuinely ships when it differs from the WeiDU folder, taken either from the
    manifest or from a curated catalogue. It is still an exact match, never a
    substring.
    """
    if not os.path.isdir(mod_dir):
        return None
    wanted = [n for n in (folder, expect_tp2) if n]
    for path in find_tp2_files(mod_dir):
        name = os.path.basename(path)
        if any(matches_tp2(name, candidate) for candidate in wanted):
            return name
    return None


def locate_mod_root(staging: str, folder: str,
                    expect_tp2: str | None = None) -> tuple:
    """
    Find the mod root inside `staging`.

    Returns (root, tp2_filename, matched_name) where matched_name is whichever
    of `folder`/`expect_tp2` the archive actually satisfied.
    """
    candidates = find_tp2_files(staging)
    if not candidates:
        raise NotThisMod(
            f"{folder}: the archive contains no .tp2 file at all - it is not a "
            f"WeiDU mod package")
    for wanted in [n for n in (folder, expect_tp2) if n]:
        for path in candidates:
            if matches_tp2(os.path.basename(path), wanted):
                return os.path.dirname(path), os.path.basename(path), wanted
    present = sorted({os.path.basename(p) for p in candidates})[:8]
    stem = os.path.splitext(present[0])[0] if present else folder
    raise NotThisMod(
        f"{folder}: archive contains .tp2 files {present} but none of them is "
        f"'{folder}.tp2' or 'setup-{folder}.tp2' - this is not the mod that was "
        f"asked for. If this archive is right and the mod simply renamed itself, "
        f"add \"expect_tp2\": \"{stem}\" to its manifest entry.")


def fold_root_tp2(root: str, tp2_file: str, name: str) -> str:
    """
    Handle the older packaging: `setup-<mod>.tp2` beside a `<mod>/` folder.

    A tp2's paths are relative to the game directory, not to the tp2, so
    `<mod>/setup-<mod>.tp2` installs identically - and it is the only layout a
    one-folder-per-mod staging area can hold. Returns the directory to install.

    Strict: only a folder whose name IS the matched mod name (case-insensitive,
    as on Windows) qualifies. With no such folder the archive is used as it is,
    and the root-level `setup-<mod>.exe` is left behind with it - a WeiDU
    binary for one platform, not mod data.
    """
    if os.path.basename(os.path.normpath(root)).lower() == name.lower():
        return root                                  # already the mod folder
    children = [entry for entry in os.listdir(root)
                if entry.lower() == name.lower()
                and os.path.isdir(os.path.join(root, entry))]
    if len(children) != 1:
        return root
    mod_dir = os.path.join(root, children[0])
    inner = os.path.join(mod_dir, tp2_file)
    if not os.path.exists(inner):
        atomic.move(os.path.join(root, tp2_file), inner)
    return mod_dir


def install_from_archive(archive_path: str, target_root: str, folder: str,
                         force: bool = False, allow_exe: bool = False,
                         expect_tp2: str | None = None) -> InstallOutcome:
    folder = safe_component(folder)
    target_root = os.path.abspath(target_root)
    dest = os.path.join(target_root, folder)
    if os.path.commonpath([target_root, os.path.abspath(dest)]) != target_root:
        raise VerificationFailed(f"{folder}: destination escapes the target directory")

    staging = os.path.join(target_root, STAGING_DIR, f"{folder}-{uuid.uuid4().hex[:12]}")
    os.makedirs(staging, exist_ok=True)
    backup = None
    try:
        safe_extract(archive_path, staging, allow_exe=allow_exe)
        root, tp2_file, matched = locate_mod_root(staging, folder, expect_tp2)
        root = fold_root_tp2(root, tp2_file, matched)

        # When the archive satisfied `expect_tp2` rather than the WeiDU folder,
        # the mod has renamed itself. WeiDU needs the directory to match the tp2
        # it ships, so follow the archive rather than the stale log entry.
        renamed_from = None
        if matched != folder:
            archive_folder = os.path.basename(root.rstrip(os.sep))
            if archive_folder and archive_folder != folder:
                renamed_from, folder = folder, safe_component(archive_folder)
                dest = os.path.join(target_root, folder)

        if os.path.exists(dest):
            if not force:
                raise InstallConflict(
                    f"{folder}: {dest} already exists; re-run with --force to replace "
                    f"it (the old directory is moved to {BACKUP_DIR}/, never deleted)")
            backup_root = os.path.join(target_root, BACKUP_DIR)
            os.makedirs(backup_root, exist_ok=True)
            backup = os.path.join(backup_root, f"{folder}.{time.strftime('%Y%m%dT%H%M%S')}")
            atomic.move(dest, backup)

        # The mod's folder moves in one rename, from the staging folder under
        # target_root (one file system): never entry by entry, which a file
        # held at the third left half in place (review of #102). If it fails,
        # the copy it replaces comes back.
        count = len(os.listdir(root))
        # The folder comes as the archive made it: one read-only there (some
        # unpackers restore 0555) cannot be renamed into another folder on
        # POSIX (the rename rewrites its "..") and would stop WeiDU writing
        # its backup folder inside it. Its owner may write it, set while it
        # is still in staging (reviews of #102). If that fails, the move says
        # why.
        with contextlib.suppress(OSError):
            mode = stat.S_IMODE(os.stat(root).st_mode)
            if mode & stat.S_IRWXU != stat.S_IRWXU:
                os.chmod(root, mode | stat.S_IRWXU)
        try:
            atomic.move(root, dest)
        except OSError as exc:
            if backup is None or os.path.exists(dest):
                raise
            try:
                atomic.move(backup, dest)
            except OSError as again:
                # one message: what failed, and where the old copy is safe
                raise OSError(exc.errno, f"{folder}: not installed ({exc}); the copy it was "
                                         f"to replace is kept in {backup} - putting it back "
                                         f"failed too ({again})") from exc
            raise

        verified = verify_mod_dir(dest, folder, expect_tp2)
        if not verified:
            raise VerificationFailed(f"{folder}: post-install verification failed")
        # The mod's own .tp2 is the authority on its version and the games it
        # supports - neither the WeiDU log nor the manifest records them.
        info = read_mod_tp2(dest, verified)
        return InstallOutcome(folder, dest, verified, backup, count, renamed_from, info)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        parent = os.path.join(target_root, STAGING_DIR)
        if os.path.isdir(parent) and not os.listdir(parent):
            os.rmdir(parent)


# ------------------------------------------------------------------- state
@dataclass
class State:
    path: str
    mods: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, target_root: str) -> State:
        path = os.path.join(target_root, STATE_FILENAME)
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
            mods = raw.get("mods", {}) if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError, ValueError):
            mods = {}
        return cls(path=path, mods=mods if isinstance(mods, dict) else {})

    def record(self, folder: str, **fields) -> None:
        entry = {"installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        entry.update({k: v for k, v in fields.items() if v is not None})
        self.mods[folder.lower()] = entry

    def get(self, folder: str) -> dict | None:
        return self.mods.get(folder.lower())

    def save(self) -> None:
        write_text(self.path, json.dumps({"version": 1, "mods": self.mods}, indent=2,
                                         sort_keys=True), durable=True)
