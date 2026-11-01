"""
A game folder's backup before mods are installed, and its restore (GUI-AUDIT
M4 item 21, ADR-0042).

What WeiDU changes is copied: `override/`, every `lang/*/dialog*.tlk`, and the
files at the folder's root (chitin.key, dialog.tlk on older games, WeiDU.log,
weidu.conf...). Everything else is only listed - path and size - in the
backup's inventory, so a restore can tell what an install ADDED anywhere (a mod
folder, a new BIFF in data/, a side folder) and what it CHANGED that was not
copied.

    backup = create(game_dir, backups_dir)     # <backups_dir>/<name>/
    verify(backup)                              # every copy against its sha256
    plan = plan_restore(backup, game_dir)       # what a restore would do
    restore(backup, game_dir)                   # do it

A restore deletes nothing (ADR-0007): what is in the way - a file or link
added since, or the current version of a file the backup has - is MOVED into
`<backup>/displaced-<time>/` under its own path (a folder no other restore
uses; nothing in it is ever replaced), then the copy is put back and checked
against its sha256. A file that changed but was not copied cannot be restored;
it is named, never passed over. A restore that stops half-way is finished by
running it again: the plan is made from what is on disk.

A restore only writes into a game folder (one with chitin.key), and only at
paths the manifest may name: relative, no `..`, no drive, no backslash -
a manifest is a file anyone could have edited (review of #48).

Standard library only; nothing here runs WeiDU or anything downloaded.
"""
import contextlib
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import threading
import time
from collections.abc import Callable

from . import atomic
from .errors import ConfigError, ModFetchError, VerificationFailed

SCHEMA_VERSION = 1
MANIFEST = "iemod-backup.json"
FILES = "files"
PARTIAL = ".partial"
DISPLACED = "displaced-"
JOURNAL_PREFIX = "restore-in-progress-"
_NAME_SURROGATE = 0x20000000          # IO_REPARSE_TAG bit: "points to another name"
COPIED_DIRS = ("override",)

Progress = Callable[[dict], None] | None


# ------------------------------------------------------------------ helpers

def _rel(path: str, root: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def _is_copied(rel: str) -> bool:
    """Whether a path (relative, '/') is in what a backup copies."""
    parts = rel.split("/")
    if len(parts) == 1:
        return True                                   # a file at the root
    if parts[0].lower() in COPIED_DIRS:
        return True
    return (len(parts) == 3 and parts[0].lower() == "lang"
            and parts[2].lower().startswith("dialog") and parts[2].lower().endswith(".tlk"))


def _scan(root: str):
    """(files, folders, links, mounts) under root, relative with '/': regular
    files {rel: full path}, every folder (empty ones too), every link - to a
    file or a folder, dangling or not - and every folder that leads elsewhere
    without being a link (a Windows junction, a mount point: review of #48).
    Neither links nor mounts are ever entered."""
    files: dict[str, str] = {}
    folders: list[str] = []
    links: list[str] = []
    mounts: list[str] = []
    device = os.stat(root).st_dev
    mount_points = _mount_points()
    for here, dirs, names in os.walk(root):
        enter = []
        for name in sorted(dirs):
            full = os.path.join(here, name)
            rel = _rel(full, root)
            if os.path.islink(full):
                links.append(rel)
            elif _leads_elsewhere(full, device, mount_points):
                mounts.append(rel)
            else:
                folders.append(rel)
                enter.append(name)
        dirs[:] = enter
        for name in sorted(names):
            full = os.path.join(here, name)
            if os.path.islink(full):
                links.append(_rel(full, root))
            elif os.path.isfile(full):
                # a file mounted over another one lives elsewhere too (#48)
                if _leads_elsewhere(full, device, mount_points):
                    mounts.append(_rel(full, root))
                else:
                    files[_rel(full, root)] = full
    return files, sorted(folders), sorted(links), sorted(mounts)


def size(game_dir: str) -> int:
    """The bytes a backup of `game_dir` copies: what create() would copy
    (item 49). Nothing is written. It walks the whole game folder - 0.9 s
    for 40,000 files on Linux with the folder cached, more on a cold disk
    or on Windows - so a window calls it off its own thread (ADR-0048)."""
    present, _folders, _links, _mounts = _scan(os.path.abspath(game_dir))
    total = 0
    for rel, full in present.items():
        if _is_copied(rel):
            # a file gone since the scan (the game, a scanner) counts nothing
            with contextlib.suppress(OSError):
                total += os.path.getsize(full)
    return total


def _mount_points() -> dict[str, int]:
    """Linux's mount table, {mount point: device}: a bind mount of the same
    disk has the same st_dev as its parent and is not os.path.ismount, but it
    is listed here. Read as bytes - a mount point need not be UTF-8 (#48)."""
    try:
        with open("/proc/self/mountinfo", "rb") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return {}
    points: dict[str, int] = {}
    for line in lines:
        fields = line.split(b" ")
        if len(fields) <= 4:
            continue
        point = re.sub(rb"\\([0-7]{3})", lambda m: bytes([int(m.group(1), 8)]), fields[4])
        try:
            major, minor = (int(x) for x in fields[2].split(b":"))
        except ValueError:
            continue
        points[os.fsdecode(point)] = os.makedev(major, minor)
    return points


def _leads_elsewhere(full: str, device: int, mount_points: dict[str, int]) -> bool:
    """A file or folder that is not a link but whose content lives
    elsewhere: a Windows junction or mount (a reparse point), a mount point,
    another drive. A mount-table entry counts only when its device is the
    one the path has now: one shadowed by a later mount over a parent is not
    there any more (#48)."""
    st = os.lstat(full)
    if getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT",
                                                      0x400) \
            and getattr(st, "st_reparse_tag", 0) & _NAME_SURROGATE:
        # a junction, mount or link points elsewhere; a OneDrive placeholder
        # or a deduplicated file is a reparse point too, but holds its own
        # content (fourth review of #48)
        return True
    if st.st_dev != device or (stat.S_ISDIR(st.st_mode) and os.path.ismount(full)):
        return True
    return mount_points.get(os.path.realpath(full)) == st.st_dev


def _is_game(folder: str) -> bool:
    return any(os.path.isfile(os.path.join(folder, key)) and
               not os.path.islink(os.path.join(folder, key))
               for key in ("chitin.key", "CHITIN.KEY", "Chitin.key"))


def _safe_rel(rel) -> bool:
    """A path a manifest may name: relative, '/'-separated, nothing that
    leaves the folder it is joined to on this system. On Windows `\\` and
    `:` are separators or drives; elsewhere they are ordinary letters a
    file may carry (a mod unpacked from a Windows-made zip, a save named
    "Chapter 2: ..."), and refusing them made such a folder's backup
    unreadable (review of #48)."""
    if not isinstance(rel, str) or not rel or "\0" in rel or rel.startswith("/"):
        return False
    if os.name == "nt" and ("\\" in rel or ":" in rel):
        return False
    return all(part not in ("", ".", "..") for part in rel.split("/"))


def _join(root: str, rel: str) -> str:
    """root/rel, refused unless it stays inside root (links resolved)."""
    path = os.path.join(root, *rel.split("/"))
    if not _safe_rel(rel) or not _inside(os.path.dirname(path), root):
        raise VerificationFailed(f"{rel}: a path outside {root}, refused")
    return path


def _sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def _identity(path: str):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino)


def _inside(path: str, folder: str) -> bool:
    """Whether path is folder or under it, by the file system's identity of
    each existing parent, not by spelling: on macOS ~/games/bg2ee and
    ~/Games/BG2EE are one folder, and so are a mount and its alias (review of
    #48: a backup written inside the game it was of)."""
    target = _identity(folder)
    if target is None:
        return False
    here = os.path.realpath(path)
    while True:
        if _identity(here) == target:
            return True
        parent = os.path.dirname(here)
        if parent == here:
            return False
        here = parent


def _check_cancel(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise InterruptedError("cancelled")


def _emit(on_progress: Progress, **event) -> None:
    if on_progress is not None:
        on_progress(event)


def read_manifest(backup: str) -> dict:
    path = os.path.join(backup, MANIFEST)
    try:
        with open(path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError) as exc:
        raise VerificationFailed(f"{backup}: not a readable backup ({exc})") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise VerificationFailed(f"{backup}: not a backup this version can read")
    _check_shape(backup, manifest)
    return manifest


def _check_shape(backup: str, manifest: dict) -> None:
    """Every field a restore reads, of the type it reads it as; every path
    one it may join (review of #48: a hand-edited manifest wrote outside the
    game folder)."""
    def bad(why: str):
        return VerificationFailed(f"{backup}: the backup's manifest is damaged ({why})")
    for key in ("name", "game_dir", "created"):
        if not isinstance(manifest.get(key), str):
            raise bad(f"no {key}")
    copied, inventory = manifest.get("copied"), manifest.get("inventory")
    folders, links = manifest.get("folders"), manifest.get("links")
    if not isinstance(copied, dict) or not isinstance(inventory, dict) or \
            not isinstance(folders, list) or not isinstance(links, list):
        raise bad("copied, inventory, folders or links missing")
    for rel, size in inventory.items():
        if not _safe_rel(rel) or not isinstance(size, int) or isinstance(size, bool):
            raise bad(f"inventory entry {rel!r}")
    for rel, meta in copied.items():
        if rel not in inventory or not isinstance(meta, dict) or \
                meta.get("size") != inventory[rel] or not isinstance(meta.get("sha256"), str) \
                or len(meta["sha256"]) != 64:
            raise bad(f"copied entry {rel!r}")
    if not isinstance(manifest.get("mounts", []), list):
        raise bad("mounts")
    for rel in folders + links + manifest.get("mounts", []):
        if not _safe_rel(rel):
            raise bad(f"folder or link {rel!r}")


# ------------------------------------------------------------------- create

def create(game_dir: str, backups_dir: str, name: str | None = None,
           on_progress: Progress = None, cancel: threading.Event | None = None) -> str:
    """Back game_dir up into backups_dir/<name>; returns the backup's path.

    It is written as `<name>.partial` and renamed only once every copy is
    made and its manifest written: a backup that exists is complete."""
    game_dir = os.path.abspath(game_dir)
    if not _is_game(game_dir):
        raise ConfigError(f"{game_dir}: no chitin.key - not a game folder")
    backups_dir = os.path.abspath(backups_dir)
    if _inside(backups_dir, game_dir):
        raise ConfigError(f"{backups_dir} is inside the game folder: a backup there would "
                          f"back itself up and be displaced by its own restore")
    name = name or f"{os.path.basename(game_dir) or 'game'}-{time.strftime('%Y%m%dT%H%M%S')}"
    final = os.path.join(backups_dir, name)
    if os.path.exists(final):
        raise ConfigError(f"{final} exists already")
    present, folders, links, mounts = _scan(game_dir)
    if _overlaps(backups_dir, game_dir, folders):
        raise ConfigError(f"{backups_dir} is inside the game folder (one of its folders under "
                          f"another name): a backup there would be displaced by its own restore")
    for rel in links + mounts:
        root_file = "/" not in rel and not os.path.isdir(os.path.join(game_dir, rel))
        if root_file or any(rel.lower() == d or rel.lower().startswith(d + "/")
                            for d in ("lang",) + COPIED_DIRS):
            # what a backup must copy would be left out without a word
            raise ConfigError(f"{game_dir}/{rel} is a link or leads to another drive: a "
                              f"backup would not hold what it points at; make it a real file "
                              f"or folder first")
    work = final + PARTIAL
    if os.path.exists(work):
        shutil.rmtree(work)                         # our own unfinished attempt
    os.makedirs(os.path.join(work, FILES))

    entries = sorted(present.items())
    copied = [(rel, full) for rel, full in entries if _is_copied(rel)]
    total = sum(os.path.getsize(full) for _, full in copied)
    _emit(on_progress, event="backup_started", files=len(copied), bytes=total)
    inventory: dict[str, int] = {}
    hashes: dict[str, dict] = {}
    done = 0
    for rel, full in entries:
        _check_cancel(cancel)
        size = os.path.getsize(full)
        inventory[rel] = size
        if not _is_copied(rel):
            continue
        target = os.path.join(work, FILES, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(full, target)
        hashes[rel] = {"size": size, "sha256": _sha256(target)}
        done += size
        _emit(on_progress, event="backup_progress", file=rel, bytes=done, total=total)
    manifest = {"schema_version": SCHEMA_VERSION, "name": name, "game_dir": game_dir,
                "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "folders": folders, "links": links, "mounts": mounts,
                "copied": hashes, "inventory": inventory}
    with open(os.path.join(work, MANIFEST), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    # before it is a backup: readable as one, and every copy its own file - on
    # a case-insensitive backups drive, X.ITM and x.itm would be one (#48)
    read_manifest(work)
    if len(_scan(os.path.join(work, FILES))[0]) != len(hashes):
        raise ConfigError(f"{backups_dir}: two files of the game are one file there (names "
                          f"that differ only in case?); back up to another drive")
    atomic.replace(work, final)
    _emit(on_progress, event="backup_finished", path=final, files=len(hashes), bytes=total)
    return final


# ------------------------------------------------------------------- verify

def verify(backup: str) -> dict:
    """Every copied file against its size and sha256."""
    manifest = read_manifest(backup)
    problems = []
    for rel, meta in sorted(manifest["copied"].items()):
        path = _join(os.path.join(backup, FILES), rel)
        if not os.path.isfile(path) or os.path.islink(path):
            problems.append(f"{rel}: missing")
        elif os.path.getsize(path) != meta["size"] or _sha256(path) != meta["sha256"]:
            problems.append(f"{rel}: changed since the backup was made")
    return {"ok": not problems, "files": len(manifest["copied"]), "problems": problems}


# ------------------------------------------------------------------ restore

def plan_restore(backup: str, game_dir: str) -> dict:
    """What restore() would do, from what is on disk now; changes nothing.

    - put_back: copied files missing or different now (they will be copied
      back; a current version is displaced first);
    - displace: files and links the backup does not know (added since),
      anywhere - matched by exact name: on a case-sensitive system a mod's
      `x.itm` beside a backed-up `X.ITM` is a file of its own (review of #48);
    - cannot_restore: files listed but not copied that are now missing or of
      another size - only their absence or change can be reported. A listed
      file whose name only changed case counts as present, so it is never
      moved away for want of a copy;
    - links: links the backup listed; left alone, never backed up."""
    manifest = read_manifest(backup)
    game_dir = os.path.abspath(game_dir)
    if not _is_game(game_dir):
        raise ConfigError(f"{game_dir}: no chitin.key - not a game folder, nothing to restore "
                          f"into")
    copied, inventory = manifest["copied"], manifest["inventory"]
    present, folders_now, links_now, mounts_now = _scan(game_dir)
    # said by the plan, not only by --apply (fourth review of #48)
    if _inside(game_dir, backup) or _overlaps(backup, game_dir, folders_now):
        raise ConfigError(f"{backup} and {game_dir} overlap: a backup cannot be restored into "
                          f"a folder that holds it")
    # a listed, uncopied file found only under another case is that file
    uncopied_missing = {rel.lower(): rel for rel in inventory
                        if rel not in copied and rel not in present}
    renamed: dict[str, str] = {}                       # listed rel -> its name now
    put_back, displace, cannot = [], [], []
    for rel, meta in sorted(copied.items()):
        now = present.get(rel)
        if now is None or os.path.getsize(now) != meta["size"] or _sha256(now) != meta["sha256"]:
            put_back.append(rel)
    # under a path that becomes a file again nothing can stay, not even a
    # listed file under another case (fifth review of #48)
    inside_put_back = tuple(rel + "/" for rel in put_back)
    for rel in sorted(present):
        if rel in inventory:
            continue
        listed = None if rel.startswith(inside_put_back) else \
            uncopied_missing.pop(rel.lower(), None)
        if listed is not None:
            renamed[listed] = rel
        else:
            displace.append(rel)
    known_links = set(manifest["links"])
    displace = sorted(displace + [rel for rel in links_now if rel not in known_links])
    for rel, size in sorted(inventory.items()):
        if rel in copied:
            continue
        now = present.get(renamed.get(rel, rel))
        if now is None:
            cannot.append(f"{rel}: missing, and not in the backup")
        elif os.path.getsize(now) != size:
            cannot.append(f"{rel}: changed, and not in the backup")
    # a mount on, above or below a path to put back: a restore would have to
    # move or write through it (#48: shutil.move emptied a mounted folder)
    blocked = sorted({rel for rel in put_back for mount in mounts_now
                      if rel == mount or rel.startswith(mount + "/")
                      or mount.startswith(rel + "/")})
    return {"backup": os.path.abspath(backup), "game_dir": game_dir,
            "backed_up_from": manifest["game_dir"], "put_back": put_back,
            "displace": displace, "cannot_restore": cannot,
            "links": sorted(known_links & set(links_now)), "mounts": mounts_now,
            "blocked": blocked}


def _overlaps(path: str, game_dir: str, folders: list[str]) -> bool:
    """Whether path, or a parent of it, IS the game folder or one of its
    folders - by identity: a mount of a game folder elsewhere is that folder
    (review of #48: a backups folder mounted from the game's)."""
    ids = {_identity(game_dir)} | {_identity(os.path.join(game_dir, *rel.split("/")))
                                    for rel in folders}
    ids.discard(None)
    here = os.path.realpath(path)
    while True:
        if _identity(here) in ids:
            return True
        parent = os.path.dirname(here)
        if parent == here:
            return False
        here = parent


def _same_folder(a: str, b: str) -> bool:
    ida = _identity(a)
    return ida is not None and ida == _identity(b)


def _new_aside(backup: str) -> str:
    """A displaced-<time> folder made now, by this restore alone: two restores
    in one second once shared one, and the second's moves replaced the
    first's files (review of #48)."""
    base = os.path.join(backup, DISPLACED + time.strftime("%Y%m%dT%H%M%S"))
    for n in range(1, 10000):
        path = base if n == 1 else f"{base}-{n}"
        try:
            os.makedirs(path)
            return path
        except FileExistsError:
            continue
    raise OSError(f"{backup}: no free displaced- folder name")


def restore(backup: str, game_dir: str, on_progress: Progress = None,
            cancel: threading.Event | None = None, other_folder: bool = False) -> dict:
    """Bring game_dir back to the backup, deleting nothing (module doc).

    A folder other than the one backed up is restored only with other_folder
    (the caller named it): a moved or edited manifest must not point a restore
    at a folder the player did not choose."""
    check = verify(backup)
    if not check["ok"]:
        raise VerificationFailed(f"{backup}: the backup itself is damaged, nothing restored: "
                                 + "; ".join(check["problems"][:5]))
    plan = plan_restore(backup, game_dir)
    game_dir = plan["game_dir"]
    if not other_folder and not _same_folder(game_dir, plan["backed_up_from"]):
        raise ConfigError(f"{game_dir} is not the folder this backup was made of "
                          f"({plan['backed_up_from']}); name it as the target to restore there")
    if plan["blocked"]:
        raise ModFetchError(f"{plan['blocked'][0]}: a junction, mount or another drive is on "
                            f"or inside this path; remove it first - nothing restored")
    manifest = read_manifest(backup)
    files_now, _folders, links_now, _mounts = _scan(game_dir)
    # what is on disk is moved by the name the disk gave it, whatever letters
    # it holds; only the manifest's names go through _join
    on_disk = {**files_now, **{rel: os.path.join(game_dir, *rel.split("/"))
                               for rel in links_now}}
    journal = _journal_path(backup, game_dir)
    earlier = _read_journal(journal, game_dir, backup)   # what a cut restore moved
    asides: list[str] = []
    moved: list[str] = []

    def move_aside(rel: str, source: str) -> None:
        target = None
        for aside in asides:
            candidate = os.path.join(aside, *rel.split("/"))
            if not os.path.lexists(candidate) and not _blocked(aside, rel):
                target = candidate
                break
        if target is None:                 # first move, or a name that clashes
            asides.append(_new_aside(backup))
            target = os.path.join(asides[-1], *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.lexists(target):        # never replace what was moved aside
            raise OSError(f"{target} exists: nothing moved over it")
        _journal_add(journal, rel, game_dir)   # before the move: a cut run is known
        _move(source, target)
        moved.append(rel)
        _emit(on_progress, event="restore_displaced", file=rel)

    _emit(on_progress, event="restore_started", displace=len(plan["displace"]),
          put_back=len(plan["put_back"]))
    # what was added first - a link where a folder was included - so every
    # path put back below is a real folder of the game again
    for rel in plan["displace"]:
        _check_cancel(cancel)
        move_aside(rel, on_disk[rel])
    for rel in plan["put_back"]:
        _check_cancel(cancel)
        target = _join(game_dir, rel)
        if os.path.isdir(target) and not os.path.islink(target):
            # a folder where the backup has a file: its files and links were
            # moved aside above; its folders, empty now, are moved aside too -
            # as empty folders - so it can go (fourth review of #48)
            for here, _dirs, _files in os.walk(target, topdown=False):
                sub = _rel(here, game_dir)
                if not asides:
                    asides.append(_new_aside(backup))
                os.makedirs(os.path.join(asides[0], *sub.split("/")), exist_ok=True)
                os.rmdir(here)
        elif os.path.lexists(target):
            move_aside(rel, target)
        source = _join(os.path.join(backup, FILES), rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.lexists(target):
            raise OSError(f"{target} is still there: not written over")
        shutil.copy2(source, target, follow_symlinks=False)
        if _sha256(target) != manifest["copied"][rel]["sha256"]:
            raise VerificationFailed(f"{target}: the copy put back does not match the backup")
        _emit(on_progress, event="restore_put_back", file=rel)
    # the folders the moves left empty - this run's, and a cut run's
    moved.extend(earlier)
    removed = _remove_emptied(game_dir, moved, keep={rel.lower() for rel in manifest["folders"]})
    with contextlib.suppress(FileNotFoundError):
        os.remove(journal)                         # the restore is finished
    result = {**plan, "displaced_to": asides[0] if asides else None, "displaced": asides,
              "removed_folders": removed}
    _emit(on_progress, event="restore_finished", **{k: result[k] for k in
                                                  ("displaced_to", "cannot_restore")})
    return result


def _blocked(aside: str, rel: str) -> bool:
    """Whether a parent of rel in aside is a file (a moved file where a
    folder is wanted now)."""
    parts = rel.split("/")[:-1]
    return any(os.path.lexists(p) and not os.path.isdir(p) or os.path.islink(p)
               for p in (os.path.join(aside, *parts[:i]) for i in range(1, len(parts) + 1)))


def _remove_emptied(game_dir: str, moved: list[str], keep: set) -> list[str]:
    """The folders the moves emptied, deepest first, when the backup did not
    have them: never a folder the backup had, never one holding anything,
    and never one the moves did not touch - an empty folder made since, or
    the target's own (review of #48)."""
    folders: set = set()
    for rel in moved:
        parts = rel.split("/")[:-1]
        folders.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
    removed = []
    for rel in sorted(folders, key=lambda f: (f.count("/"), f), reverse=True):
        if rel.lower() in keep:
            continue
        path = os.path.join(game_dir, *rel.split("/"))
        if os.path.islink(path) or not os.path.isdir(path) or not _inside(path, game_dir):
            continue
        with contextlib.suppress(OSError):                      # only when empty
            os.rmdir(path)
            removed.append(rel)
    return sorted(removed)


def _move(source: str, target: str) -> None:
    """A file or a link, never a folder, from source to target. Not
    shutil.move: across drives, or onto a mount, it copies a folder and then
    rmtree()s the source - which emptied a mounted folder outside the game
    (review of #48). Here a file is copied, checked and only then removed; a
    copy whose source cannot be removed is taken back, so a rerun finds the
    state it started from."""
    st = os.lstat(source)
    if not (stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode)):
        raise OSError(f"{source}: not a file or a link, not moved")
    try:
        atomic.rename(source, target)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    if stat.S_ISLNK(st.st_mode):
        os.symlink(os.readlink(source), target)
    else:
        try:
            shutil.copy2(source, target, follow_symlinks=False)
            if os.path.getsize(target) != st.st_size:
                raise OSError(f"{source}: the copy moved aside is incomplete, nothing moved")
        except BaseException:
            with contextlib.suppress(OSError):
                os.remove(target)              # a part copy is never left behind
            raise
    try:
        os.remove(source)
    except OSError:
        os.remove(target)                      # ours, a copy: the source stays
        raise


def _journal_path(backup: str, game_dir: str) -> str:
    """One journal per game folder, named from its path: a drive plugged in
    again keeps its path but may change its device number, and two folders
    restored from one backup never share - or overwrite - a journal (fifth
    review of #48)."""
    key = os.path.normcase(os.path.realpath(game_dir))
    digest = hashlib.sha256(os.fsencode(key)).hexdigest()[:16]
    return os.path.join(backup, f"{JOURNAL_PREFIX}{digest}.jsonl")


def _journal_add(path: str, rel: str, game_dir: str) -> None:
    """One moved path per line, appended before it is moved; the first line
    names the game folder."""
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as fh:
        if new:
            fh.write(json.dumps({"game": os.path.realpath(game_dir)}) + "\n")
        fh.write(json.dumps(rel) + "\n")


def _read_journal(path: str, game_dir: str, backup: str) -> list[str]:
    """The paths a restore cut short moved out of THIS game folder and that
    are in one of this backup's displaced- folders now: a path that was
    never moved removes nothing (fourth review of #48)."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except (OSError, ValueError):
        return []
    try:
        header = json.loads(lines[0]) if lines else None
    except ValueError:
        header = None
    if not isinstance(header, dict) or not isinstance(header.get("game"), str) or \
            os.path.normcase(header["game"]) != os.path.normcase(os.path.realpath(game_dir)):
        return []                          # not this folder's: left as it is
    asides = [os.path.join(backup, name) for name in os.listdir(backup)
              if name.startswith(DISPLACED) and os.path.isdir(os.path.join(backup, name))
              and not os.path.islink(os.path.join(backup, name))]
    found = []
    for line in lines[1:]:
        try:
            rel = json.loads(line)
        except ValueError:
            continue
        if _safe_rel(rel) and any(os.path.lexists(os.path.join(a, *rel.split("/")))
                                  for a in asides):
            found.append(rel)
    return found


def list_backups(backups_dir: str) -> list[dict]:
    """The finished backups in a folder, newest first."""
    found: list[dict] = []
    if not os.path.isdir(backups_dir):
        return found
    for name in os.listdir(backups_dir):
        path = os.path.join(backups_dir, name)
        if name.endswith(PARTIAL) or not os.path.isfile(os.path.join(path, MANIFEST)):
            continue
        try:
            manifest = read_manifest(path)
        except ModFetchError:
            continue
        found.append({"path": path, "name": manifest["name"], "created": manifest["created"],
                      "game_dir": manifest["game_dir"], "files": len(manifest["copied"]),
                      "bytes": sum(m["size"] for m in manifest["copied"].values())})
    return sorted(found, key=lambda b: b["created"], reverse=True)
