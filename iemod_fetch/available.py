"""
The mods a player can choose from, merged from every source given (M1).

The selection screen of a UI starts here, before any WeiDU.log exists. Each
source knows something different about a mod:

* the download manifest (`mod_downloads.json`): where to fetch it;
* the lcc-docs catalogue: games, categories, quality rating, status, last
  update, and its own advisories;
* the BWS-NG / krion64 mod database: the version and, often, a sha256;
* krion64's release cache: each GitHub repository's latest release (M2d).

Each source's kind is kept apart (M5 item 26, kinds.py): lcc-docs' categories
and BWS-NG's as kinds, krion64's install category and tags beside them. The
selection filters on any kind a source gives; where two sources both classify
a mod with no kind in common, `kind_disagreement` says so - never settled.

With versions known and a WeiDU.log given, each mod also says what is
installed, the newest version any source names, and whether that is an update
(freshness.py has the rule and how it was measured).

They are joined on the folder name folded to its comparison key - the same key
every other part of the tool joins on - so one mod is one entry, carrying each
source's facts and where they came from. Nothing is fetched: this reads only
what was given.
"""
import json
import re
from dataclasses import dataclass, field
from collections.abc import Mapping, Sequence

from .catalogues import CatalogueSet
from .freshness import RELEASE, Candidate, Release, github_repo, latest, update_available
from .kinds import BWS_NG, LCC_DOCS, disagree, kinds as to_kinds, source_name
from .manifest import Manifest
from .moddb import ModDatabase
from .naming import normalize_key
from .weidu import KNOWN_GAMES

SCHEMA_VERSION = 1
_GAMES = {game.upper(): game for game in KNOWN_GAMES}


@dataclass
class AvailableMod:
    key: str                          # comparison key: lowercase alphanumerics
    tp2: str                          # the folder name, as the first source spells it
    name: str
    in_manifest: bool = False
    games: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    status: tuple[str, ...] = ()
    safe: int | None = None
    last_update: str | None = None
    version: str | None = None
    blocking: bool = False
    advisories: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    kinds_by_source: dict[str, tuple[str, ...]] = field(default_factory=dict)
    install_category: str | None = None   # krion64's, beside the kinds
    tags: tuple[str, ...] = ()
    repos: list[str] = field(default_factory=list)       # GitHub owner/repo, lowercased
    candidates: list[Candidate] = field(default_factory=list)
    installed: str | None = None
    latest: Candidate | None = None
    update_available: bool | None = None
    page: str | None = None               # lcc-docs' first link for it
    release: dict | None = None           # what krion64's scan saw of its repository
    notes: list[tuple[str, str]] = field(default_factory=list)   # krion64's
    fetched: str | None = None            # the day this tool fetched the player's copy

    def _repo(self, url: str | None) -> None:
        repo = github_repo(url)
        if repo and repo not in self.repos:
            self.repos.append(repo)

    def _kinds(self, origin: str, found: tuple[str, ...]) -> None:
        if found:
            origin = source_name(origin)
            self.kinds_by_source[origin] = to_kinds(
                self.kinds_by_source.get(origin, ()) + found, {})

    @property
    def maybe_updated(self) -> bool:
        """lcc-docs' date is after the day the player's copy was fetched
        (ADR-0044): a page edited or a release made since. A date, never a
        version - and unknown is silence, not a guess."""
        return newer_by_day(self.last_update, self.fetched)

    @property
    def kinds(self) -> tuple[str, ...]:
        """Every kind any source gives, in KINDS' order."""
        return to_kinds((k for found in self.kinds_by_source.values() for k in found), {})

    @property
    def kind_disagreement(self) -> bool:
        said = list(self.kinds_by_source.values())
        return any(disagree(a, b) for i, a in enumerate(said) for b in said[i + 1:])

    def as_dict(self) -> dict:
        freshness = {"installed": self.installed,
                     "latest": self.latest.as_dict() if self.latest else None,
                     "update_available": self.update_available}
        return {**self._facts(), **freshness}

    def _facts(self) -> dict:
        return {"key": self.key, "tp2": self.tp2, "name": self.name,
                "in_manifest": self.in_manifest, "games": list(self.games),
                "categories": list(self.categories), "status": list(self.status),
                "safe": self.safe, "last_update": self.last_update,
                "version": self.version, "blocking": self.blocking,
                "advisories": list(self.advisories), "sources": list(self.sources),
                "kinds": list(self.kinds),
                "kinds_by_source": {o: list(k) for o, k in self.kinds_by_source.items()},
                "kind_disagreement": self.kind_disagreement,
                "install_category": self.install_category, "tags": list(self.tags)}


_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def newer_by_day(date: str | None, since: str | None) -> bool:
    """`date` is a later day than `since`. lcc-docs' dates are days with no
    time or zone, so both are cut to the day: the same day is not newer,
    and any doubt (no date, not a date) says nothing (ADR-0044)."""
    a, b = _DAY.match(date or ""), _DAY.match(since or "")
    return a is not None and b is not None and a.groups() > b.groups()


def mark_fetched(mods: Sequence[AvailableMod], fetched: Mapping[str, str]) -> None:
    """Give each mod the day its copy was fetched ({mod key: ISO time}, from
    install.State's `installed_at`, UTC)."""
    for mod in mods:
        when = fetched.get(mod.key)
        if when and _DAY.match(when):
            mod.fetched = when[:10]


def _games(values) -> tuple[str, ...]:
    return tuple(_GAMES[v.upper()] for v in values if isinstance(v, str)
                 and v.upper() in _GAMES)


def _merge(found: dict[str, AvailableMod], key: str, tp2: str, name: str) -> AvailableMod:
    if key not in found:
        found[key] = AvailableMod(key=key, tp2=tp2, name=name or tp2)
    return found[key]


def available_mods(manifest: Manifest | None = None,
                   catalogues: CatalogueSet | None = None,
                   database: ModDatabase | None = None,
                   releases: Mapping[str, Release] | None = None,
                   versions: Sequence[ModDatabase] = (),
                   installed: Mapping[str, str] | None = None) -> list[AvailableMod]:
    """
    One entry per mod any source knows, sorted by name.

    `releases` is the release cache (owner/repo -> latest release), `versions`
    more databases read only for the version they record (krion64's), and
    `installed` the installed version by mod key, from a WeiDU.log.
    """
    found: dict[str, AvailableMod] = {}
    for source in (manifest.sources.values() if manifest else ()):
        tp2 = source.folder or source.key
        mod = _merge(found, normalize_key(tp2), tp2, source.name)
        mod.in_manifest = True
        mod.sources.append({k: v for k, v in (
            ("origin", "manifest"), ("url", source.url), ("github", source.github),
            ("sha256", source.sha256), ("release_tag", source.release_tag)) if v})
        mod._repo(source.github and f"https://github.com/{source.github}")
        mod._repo(source.url)

    for catalogue in (catalogues.catalogues if catalogues else ()):
        for key, entries in catalogue.by_key.items():
            for entry in entries:
                mod = _merge(found, key, entry.tp2, entry.name)
                mod.games = tuple(sorted(set(mod.games) | set(_games(entry.games))))
                mod.categories = tuple(dict.fromkeys(mod.categories + entry.categories))
                mod.status = tuple(dict.fromkeys(mod.status + entry.status))
                mod._kinds(entry.origin, to_kinds(entry.categories, LCC_DOCS))
                mod.safe = mod.safe if mod.safe is not None else entry.safe
                mod.last_update = mod.last_update or entry.last_update
                # a page, not an archive lcc-docs links directly (review of #122:
                # 114 of 2,134 entries list an archive first)
                mod.page = mod.page or next((url for url in entry.http_urls
                                             if url not in entry.direct_urls), None)
                mod.blocking = mod.blocking or entry.blocking
                mod.advisories.extend(a for a in entry.advisories()
                                      if a not in mod.advisories)
                mod.sources.append({k: v for k, v in (
                    ("origin", entry.origin), ("github", entry.github),
                    ("urls", list(entry.http_urls))) if v} or {"origin": entry.origin})
                mod._repo(entry.github and f"https://github.com/{entry.github}")
                for url in entry.http_urls:
                    mod._repo(url)

    origin = database.origin if database else ""
    for record in (database.records.values() if database else ()):
        mod = _merge(found, record.key, record.key, record.name or record.key)
        mod.version = mod.version or record.version
        mod.games = tuple(sorted(set(mod.games) | set(_games(record.games))))
        best = record.best_file
        mod.sources.append({k: v for k, v in (
            ("origin", origin), ("url", best.download if best else None),
            ("sha256", best.sha256 if best else None),
            ("version", record.version)) if v})
        _record_versions(mod, record, origin)
        _record_kinds(mod, record, origin)

    for extra in versions:
        for record in extra.records.values():
            if record.key in found:
                _record_versions(found[record.key], record, extra.origin)
                _record_kinds(found[record.key], record, extra.origin)

    for mod in found.values():
        for repo in _by_likeness(mod.repos, mod.key):
            release = (releases or {}).get(repo)
            if release:
                mod.candidates.insert(0, Candidate(release.tag, RELEASE, release.date,
                                                   release.url))
                mod.release = {k: v for k, v in (
                    ("repo", repo), ("tag", release.tag), ("name", release.name),
                    ("date", release.date), ("notes", release.notes),
                    ("pushed", release.pushed), ("archived", release.archived),
                    ("checked", (release.checked or "")[:10])) if v}
                break
        mod.latest = latest(mod.candidates)
        mod.installed = (installed or {}).get(mod.key)
        mod.update_available = update_available(mod.installed, mod.latest)

    return sorted(found.values(), key=lambda m: (m.name.lower(), m.key))


def _by_likeness(repos: list[str], key: str) -> list[str]:
    """The repository named like the mod first: CTB's sub-mods link both
    their own repository and Check the Bodies'."""
    def rank(repo: str) -> int:
        name = normalize_key(repo.split("/", 1)[1])
        return 0 if name == key else 1 if key and key in name else 2
    return sorted(repos, key=rank)


def _record_versions(mod: AvailableMod, record, origin: str) -> None:
    for url in [record.homepage] + [f.download for f in record.files]:
        mod._repo(url)
    if record.version:
        mod.candidates.append(Candidate(record.version, origin))
    for note in getattr(record, "notes", ()):
        if note not in mod.notes:
            mod.notes.append(note)


def _record_kinds(mod: AvailableMod, record, origin: str) -> None:
    mod._kinds(origin, to_kinds(record.categories, BWS_NG))
    mod.install_category = mod.install_category or record.install_category
    mod.tags = tuple(dict.fromkeys(mod.tags + tuple(record.tags)))


def mods_document(mods: list[AvailableMod]) -> str:
    """The versioned JSON a UI reads (ADR-0030)."""
    return json.dumps({"schema_version": SCHEMA_VERSION,
                       "mods": [m.as_dict() for m in mods]}, indent=2) + "\n"
