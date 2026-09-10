"""
The BigWorldSetup-Next-Generation per-mod database (`data/mods/*.json`).

Alongside its rule files that project keeps one JSON per mod:

    {"name": "...", "version": "1.03a",
     "files": [{"filename": "...", "sha256": "...", "download": "https://..."}],
     "games": [...], "components": {...}}

Two things make this worth reading:

* **Integrity data the download manifest does not have** — a direct URL *and* a
  sha256, for 391 of its 430 mods.
* **The version each rule was written against.** The rule files carry no version
  qualifier, so a rule cannot say "fixed in v5.1". But this database records the
  version the rule set was built against, and the installed mod declares its own
  version in its .tp2 — so when the installed one is newer, a rule about that
  mod is provably written against an older release and may no longer hold.
"""
import glob
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .errors import ConfigError
from .naming import normalize_key

_MAX_BYTES = 4 * 1024 * 1024


@dataclass
class ModFile:
    filename: Optional[str] = None
    download: Optional[str] = None
    sha256: Optional[str] = None
    size: Optional[int] = None


@dataclass
class ModRecord:
    key: str
    name: Optional[str] = None
    version: Optional[str] = None
    files: List[ModFile] = field(default_factory=list)
    games: List[str] = field(default_factory=list)
    homepage: Optional[str] = None
    origin: str = "mod database"

    @property
    def best_file(self) -> Optional[ModFile]:
        """A file with both a URL and a digest beats one with only a URL."""
        for candidates in (
                [f for f in self.files if f.download and f.sha256],
                [f for f in self.files if f.download]):
            if candidates:
                return candidates[0]
        return None


@dataclass
class ModDatabase:
    records: Dict[str, ModRecord] = field(default_factory=dict)
    origin: str = "mod database"
    skipped: int = 0

    def __len__(self) -> int:
        return len(self.records)

    def get(self, *names) -> Optional[ModRecord]:
        for name in names:
            if name:
                found = self.records.get(normalize_key(name))
                if found:
                    return found
        return None

    @classmethod
    def load(cls, path: str) -> "ModDatabase":
        """Load a directory of per-mod JSON files (or a single one)."""
        if os.path.isdir(path):
            paths = sorted(glob.glob(os.path.join(path, "*.json")))
        elif os.path.isfile(path):
            paths = [path]
        else:
            raise ConfigError(f"mod database not found: {path}")

        db = cls(origin=os.path.basename(path.rstrip(os.sep)) or "mod database")
        for item in paths:
            record = _read(item, db.origin)
            if record:
                db.records[record.key] = record
            else:
                db.skipped += 1
        return db


def _read(path: str, origin: str) -> Optional[ModRecord]:
    try:
        if os.path.getsize(path) > _MAX_BYTES:
            return None
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None

    stem = os.path.splitext(os.path.basename(path))[0]

    # krion64 per-mod records use short field names and carry no checksums, but
    # they do carry the version - which is what staleness detection needs.
    if "t" in raw and ("conflicts" in raw or "dependencies" in raw or "ord" in raw):
        download = raw.get("dl") or raw.get("u")
        return ModRecord(
            key=normalize_key(raw.get("t") or stem),
            name=raw.get("n") or raw.get("t") or stem,
            version=raw.get("v") or None,
            files=[ModFile(download=download)] if download else [],
            games=[g for g in (raw.get("ph") or []) if isinstance(g, str)],
            homepage=raw.get("u"), origin=origin)

    files = []
    for entry in raw.get("files") or []:
        if isinstance(entry, dict):
            files.append(ModFile(
                filename=entry.get("filename"),
                download=entry.get("download"),
                sha256=(entry.get("sha256") or "").lower() or None,
                size=entry.get("size") if isinstance(entry.get("size"), int) else None))
    links = raw.get("links") or {}
    return ModRecord(
        key=normalize_key(stem),
        name=raw.get("name") or stem,
        version=raw.get("version") or None,
        files=files,
        games=[g for g in (raw.get("games") or []) if isinstance(g, str)],
        homepage=links.get("homepage") if isinstance(links, dict) else None,
        origin=origin)
