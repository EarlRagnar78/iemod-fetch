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
import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .archives import safe_extract
from .errors import InstallConflict, VerificationFailed
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
    backup: Optional[str] = None
    file_count: int = 0
    renamed_from: Optional[str] = None   # WeiDU folder, when it differed
    tp2_info: Optional[Tp2Info] = None   # what the mod says about itself

    @property
    def version(self) -> Optional[str]:
        return self.tp2_info.version if self.tp2_info else None


def find_tp2_files(root: str) -> List[str]:
    found = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.lower().endswith(".tp2"):
                found.append(os.path.join(dirpath, name))
    return sorted(found, key=lambda p: (p.count(os.sep), p))


def verify_mod_dir(mod_dir: str, folder: str,
                   expect_tp2: Optional[str] = None) -> Optional[str]:
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
                    expect_tp2: Optional[str] = None) -> tuple:
    """
    Find the mod root inside `staging`.

    Returns (root, tp2_filename, matched_name) where matched_name is whichever
    of `folder`/`expect_tp2` the archive actually satisfied.
    """
    candidates = find_tp2_files(staging)
    if not candidates:
        raise VerificationFailed(
            f"{folder}: the archive contains no .tp2 file at all - it is not a "
            f"WeiDU mod package")
    for wanted in [n for n in (folder, expect_tp2) if n]:
        for path in candidates:
            if matches_tp2(os.path.basename(path), wanted):
                return os.path.dirname(path), os.path.basename(path), wanted
    present = sorted({os.path.basename(p) for p in candidates})[:8]
    stem = os.path.splitext(present[0])[0] if present else folder
    raise VerificationFailed(
        f"{folder}: archive contains .tp2 files {present} but none of them is "
        f"'{folder}.tp2' or 'setup-{folder}.tp2' - this is not the mod that was "
        f"asked for. If this archive is right and the mod simply renamed itself, "
        f"add \"expect_tp2\": \"{stem}\" to its manifest entry.")


def install_from_archive(archive_path: str, target_root: str, folder: str,
                         force: bool = False, allow_exe: bool = False,
                         expect_tp2: Optional[str] = None) -> InstallOutcome:
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
            shutil.move(dest, backup)

        os.makedirs(dest, exist_ok=False)
        count = 0
        for entry in os.listdir(root):
            shutil.move(os.path.join(root, entry), os.path.join(dest, entry))
            count += 1

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
    mods: Dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, target_root: str) -> "State":
        path = os.path.join(target_root, STATE_FILENAME)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            mods = raw.get("mods", {}) if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError, ValueError):
            mods = {}
        return cls(path=path, mods=mods if isinstance(mods, dict) else {})

    def record(self, folder: str, **fields) -> None:
        entry = {"installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        entry.update({k: v for k, v in fields.items() if v is not None})
        self.mods[folder.lower()] = entry

    def get(self, folder: str) -> Optional[dict]:
        return self.mods.get(folder.lower())

    def save(self) -> None:
        tmp = self.path + ".tmp"
        os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "mods": self.mods}, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
