"""
A mod's own metadata ini, read before the mod is downloaded (ADR-0037).

Project Infinity's metadata file (`<tp2 name>.ini`, `[Metadata]`, beside the
tp2; modmeta.py reads it) carries the author's own install order: `Before`
and `After`, lists of other mods' tp2 names. The tool already reads it from a
staged mod. But the order is planned, and conflicts are judged, before
anything is downloaded - and then only the community rule sets speak.

Measured on 85 real metadata inis (tools/pi_metadata_benchmark.py): they
state 314 order pairs; krion64's install order agrees with 239, a rule already
covers 34 more, and 19 are known only to the author's ini - 7 of them
contradicting krion64's order (Region of Terror after IWD1_EET and IWD2_EET,
Kivan before Adrian, ...). So the ini is worth reading early.

It is one small text file, fetched from the repository the catalogue names,
at its default branch, from raw.githubusercontent.com: never executed, capped
at 1 MiB, parsed by the same tolerant reader as a staged one. What was found -
and what was not, so a missing file is not asked for again on every run - is
kept in one JSON file in the community-data cache, with the date. A staged
mod's own ini always wins over a fetched one.
"""
import json
import os
import time
import urllib.parse
from dataclasses import dataclass
from collections.abc import Iterable

from .atomic import write_text
from .errors import HttpStatusError, ModFetchError, NetworkError
from .modmeta import ModMetadata, parse_metadata_ini
from .naming import normalize_key

RAW = "https://raw.githubusercontent.com"
API = "https://api.github.com/repos"
CACHE_FILE = "mod-metadata.json"
MAX_INI_BYTES = 1024 * 1024
MAX_AGE_DAYS = 7          # a found or missing ini is asked for again after this
RETRY_AFTER_SECONDS = 3600   # after a network error: not before this


@dataclass(frozen=True)
class Wanted:
    """
    A tp2 whose ini is wanted: its mod folder, the tp2's path as the log gives
    it (`eet/EET_end/EET_end.tp2` - one folder can hold several tp2s, each with
    its own ini), and the repository.
    """
    folder: str
    tp2_file: str
    repo: str                 # owner/name on GitHub

    @property
    def parts(self) -> list[str]:
        """The tp2's path, split: no empty or `.` parts (`./x//y.tp2` is x/y.tp2)."""
        return [p for p in self.tp2_file.replace("\\", "/").split("/") if p not in ("", ".")]

    @property
    def directory(self) -> str:
        """The tp2's folder in the repository, as the log spells it."""
        parts = self.parts
        return "/".join(parts[:-1]) if len(parts) > 1 else self.folder


def tp2_name(tp2_file: str) -> str:
    """The tp2's name as rules give it: no folder, no extension, no `setup-`."""
    stem = os.path.splitext(os.path.basename(tp2_file.replace("\\", "/")))[0]
    return stem[6:] if stem.lower().startswith("setup-") else stem


def candidates(folder: str, tp2_file: str) -> list[str]:
    """Where the ini may be in the repository: beside the tp2, named after it."""
    parts = [p for p in tp2_file.replace("\\", "/").split("/") if p not in ("", ".")]
    if len(parts) > 1:
        folder = "/".join(parts[:-1])
    stem = os.path.splitext(os.path.basename(tp2_file.replace("\\", "/")))[0]
    names = [stem]
    if stem.lower().startswith("setup-"):
        names.append(stem[6:])
    # Project Infinity runs on Windows, where `rot.ini` is `RoT.ini`; GitHub is
    # case-sensitive, and Region of Terror ships `RoT/rot.ini` beside
    # `setup-RoT.tp2`. The lower-case spelling is tried too.
    names += [name.lower() for name in names if name.lower() != name]
    out = []
    for name in names:
        for where in (f"{folder}/{name}.ini", f"{name}.ini"):
            if where not in out:
                out.append(where)
    return out


def cache_key(mod: Wanted) -> str:
    return f"{normalize_key(mod.folder)}:{normalize_key(tp2_name(mod.tp2_file))}"


class MetadataCache:
    """
    The fetched inis, by mod folder key: {"repo", "path", "text", "checked"},
    plus "failed" (when the network last failed) while it is backing off.
    """

    def __init__(self, data_dir: str) -> None:
        self.path = os.path.join(data_dir, CACHE_FILE)
        self.entries: dict[str, dict] = {}
        try:
            with open(self.path, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                self.entries = {k: v for k, v in loaded.items() if isinstance(v, dict)}
        except (OSError, ValueError):
            pass                  # no cache yet, or a broken one: start again

    def get(self, mod: Wanted) -> ModMetadata | None:
        """The cached ini of `mod`, if it came from its repository and gives an order."""
        entry = self.entries.get(cache_key(mod)) or {}
        text = entry.get("text")
        if not isinstance(text, str) or entry.get("repo") != mod.repo.lower():
            return None
        meta = parse_metadata_ini(text, source=f"{entry.get('repo')}:{entry.get('path')}")
        return meta if meta.has_order_hints else None

    def fresh(self, mod: Wanted, now: float) -> bool:
        entry = self.entries.get(cache_key(mod))
        if not entry or entry.get("repo") != mod.repo.lower():
            return False
        if now - float(entry.get("failed") or 0) < RETRY_AFTER_SECONDS:
            return True           # backing off after a network error
        if not entry.get("checked"):
            return False          # never checked: only ever failed
        return now - float(entry["checked"]) < MAX_AGE_DAYS * 86400

    def back_off(self, mod: Wanted, now: float) -> None:
        """Remember a network failure; what was found before is kept."""
        key = cache_key(mod)
        entry = dict(self.entries.get(key) or {})
        if entry.get("repo") != mod.repo.lower():
            entry = {"repo": mod.repo.lower(), "path": None, "text": None, "checked": 0}
        entry["failed"] = now
        self.entries[key] = entry

    def save(self) -> None:
        write_text(self.path, json.dumps(self.entries, indent=1, sort_keys=True))


def _names(tp2_file: str) -> list[str]:
    stem = os.path.splitext(os.path.basename(tp2_file.replace("\\", "/")))[0]
    names = [stem]
    if stem.lower().startswith("setup-"):
        names.append(stem[6:])
    return [name.lower() + ".ini" for name in names]


def _raw(client, repo: str, where: str) -> str | None:
    """The file's text, or None when it is not there (404). Other errors raise."""
    url = f"{RAW}/{repo}/HEAD/{urllib.parse.quote(where, safe='/')}"
    try:
        data = client.read_bytes(url, limit=MAX_INI_BYTES)
    except ModFetchError as exc:
        if getattr(exc, "status", None) == 404:
            return None
        raise
    return bytes(data).decode("utf-8-sig", errors="replace")


def _listed(client, repo: str, path: str) -> list[dict] | None:
    """A repository folder's entries (GitHub's contents API); None if it is not there."""
    url = f"{API}/{repo}/contents" + (f"/{urllib.parse.quote(path, safe='/')}" if path else "")
    try:
        listed = client.get_json(url)
    except ModFetchError as exc:
        if getattr(exc, "status", None) == 404:
            return None
        raise
    return [e for e in listed if isinstance(e, dict)] if isinstance(listed, list) else None


def _find(client, repo: str, mod: Wanted) -> tuple[str | None, str | None]:
    """
    (text, path) of the mod's ini, or (None, None) when the repository has none.

    The likely spellings are tried first, on raw.githubusercontent.com (no API
    quota). On a miss the repository's root and each level of the tp2's folder
    are listed (GitHub's contents API) and matched ignoring case: a
    WeiDU log may spell `ASCENSION/ASCENSION.TP2`, and a mod may ship
    `DeitiesOfFaerun/Deitiesoffaerun.ini` beside `DeitiesOffaerun.tp2` - PI runs
    where case does not matter, GitHub does not. Only a listing proves a miss.
    """
    for where in candidates(mod.folder, mod.tp2_file):
        text = _raw(client, repo, where)
        if text is not None and "[metadata]" in text.lower():
            return text, where
    wanted = set(_names(mod.tp2_file))
    root = _listed(client, repo, "") or []
    places = [("", root)]
    prefix, entries = "", root
    for part in mod.directory.split("/"):              # each level, ignoring case
        match = next((e["name"] for e in entries if e.get("type") == "dir"
                      and str(e.get("name", "")).lower() == part.lower()), None)
        if match is None:
            break
        prefix = f"{prefix}/{match}" if prefix else match
        entries = _listed(client, repo, prefix) or []
        places.append((prefix, entries))
    for prefix, entries in reversed(places):           # the tp2's own folder first
        for entry in entries:
            name = str(entry.get("name", ""))
            if entry.get("type") == "file" and name.lower() in wanted:
                where = f"{prefix}/{name}" if prefix else name
                text = _raw(client, repo, where)
                if text is not None and "[metadata]" in text.lower():
                    return text, where
    return None, None


def _network_down(exc: ModFetchError) -> bool:
    """
    A failure of the run, not of one repository: no connection, a timeout, a
    credential GitHub refuses (401 - it would refuse every repository), or a
    403/429, which on GitHub is almost always a quota, primary or secondary
    (the secondary one carries no "rate limit" words). A 404, a 451, a file
    over the cap belong to one repository and must not stop the others.
    """
    if isinstance(exc, HttpStatusError):
        return exc.status in (401, 403, 429)
    return isinstance(exc, NetworkError)


def fetch(client, cache: MetadataCache, wanted: Iterable[Wanted],
          now: float | None = None) -> tuple[int, int, list[str]]:
    """
    Fetch the ini of every `wanted` tp2 whose cache entry is missing or old.
    Returns (found, missing, problems). When the network is down (or the quota
    spent), nothing more is asked this time, every tp2 still to ask backs off
    for an hour, and what was found before is kept. An error of one repository
    is recorded for that tp2 alone, as checked, and the others go on.
    """
    now = time.time() if now is None else now
    found = missing = 0
    problems: list[str] = []
    todo = [mod for mod in wanted if not cache.fresh(mod, now)]
    for n, mod in enumerate(todo):
        repo = mod.repo.lower()
        try:
            text, path = _find(client, repo, mod)
        except ModFetchError as exc:
            problems.append(f"{mod.folder}: {exc}")
            if _network_down(exc):
                for rest in todo[n:]:
                    cache.back_off(rest, now)
                break
            # This repository's own failure: it backs off for an hour like a
            # network error, and an ini found before is kept.
            cache.back_off(mod, now)
            cache.entries[cache_key(mod)]["problem"] = str(exc)
            continue
        cache.entries[cache_key(mod)] = {"repo": repo, "path": path, "text": text,
                                         "checked": now}
        if text is None:
            missing += 1
        else:
            found += 1
    return found, missing, problems
