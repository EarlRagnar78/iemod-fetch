"""
Release discovery scoped to owners you already trust.

ADR-0008. The legacy script's fatal move was a GLOBAL GitHub search
(`?q=<name>+in:name`) whose top hit it installed - a namespace anyone can
register in. This is a different mechanism with a different trust boundary:

  * the search space is an explicit allowlist of owners (defaulting to the
    owners your own manifest already depends on, plus a shipped list of the
    Infinity Engine modding houses) - not all of GitHub;
  * a hit is a CANDIDATE, never a decision. The artefact still has to survive
    the same strict `<folder>.tp2` / `setup-<folder>.tp2` check at install time,
    so a wrong repository inside a right owner fails verification instead of
    being installed;
  * whatever it resolves is reported and written back as a suggested `github`
    value, so the guess becomes a reviewed manifest entry and stops being a
    guess on the next run.

Name similarity narrows the field. Owner allowlist plus tp2 verification is
what makes it safe.
"""
import json
import os
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence

from .errors import ModFetchError
from .naming import normalize_key
from .plan import _strip_prefix

# The modding houses that publish these mods. Extend with --trusted-owner.
SHIPPED_TRUSTED_OWNERS = (
    "Spellhold-Studios",      # current SHS org
    "SpellholdStudios",       # legacy SHS org (abandoned 2022, still hosts some mods)
    "Gibberlings3",
    "Pocket-Plane-Group",
    "The-Gate-Project",
    "Black-Wyrm-Lair",
    "Bubb13",
    "Argent77",
    "TheArtisanBG",
    "InfinityMods",
    "UnearthedArcana",
    "morpheus562",
)

CACHE_TTL_SECONDS = 24 * 3600
_PER_PAGE = 100
_MAX_PAGES = 10           # 1000 repos per owner is far beyond any of these orgs


class JsonClient(Protocol):
    """
    All the owner index needs of an HTTP client: fetch a URL and decode JSON.

    Stated as a Protocol rather than importing HttpClient, so this module keeps
    no dependency on `net` and the test doubles are checked against the same
    shape the real client has to satisfy.
    """

    def get_json(self, url: str) -> Any: ...


@dataclass(frozen=True)
class RepoRef:
    owner: str
    name: str
    archived: bool = False
    fork: bool = False

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass
class OwnerCandidate:
    repo: RepoRef
    score: float
    rationale: str


@dataclass
class OwnerIndex:
    """Lazily-built, disk-cached map of trusted owner -> repositories."""
    client: "JsonClient"
    owners: Sequence[str] = SHIPPED_TRUSTED_OWNERS
    cache_path: Optional[str] = None
    ttl: int = CACHE_TTL_SECONDS
    _repos: Dict[str, List[RepoRef]] = field(default_factory=dict)
    _failed: Dict[str, str] = field(default_factory=dict)
    _loaded: bool = False

    # ------------------------------------------------------------- caching
    def _load_cache(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.cache_path or not os.path.exists(self.cache_path):
            return
        try:
            with open(self.cache_path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict) or time.time() - raw.get("fetched_at", 0) > self.ttl:
            return
        for owner, names in (raw.get("owners") or {}).items():
            # names are stored as {owner: [repo, ...]}; keep the owner's real
            # spelling so suggested "github" values are pasteable verbatim
            self._repos[owner.lower()] = [RepoRef(owner, n) for n in names]

    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        payload = {"fetched_at": time.time(),
                   "owners": {(repos[0].owner if repos else owner):
                              [r.name for r in repos]
                              for owner, repos in self._repos.items()}}
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.cache_path)) or ".",
                        exist_ok=True)
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            os.replace(tmp, self.cache_path)
        except OSError:
            pass                       # a cold cache is slow, not wrong

    # ------------------------------------------------------------ fetching
    def repos_for(self, owner: str) -> List[RepoRef]:
        self._load_cache()
        key = owner.lower()
        if key in self._repos:
            return self._repos[key]
        if key in self._failed:
            return []

        collected: List[RepoRef] = []
        for page in range(1, _MAX_PAGES + 1):
            url = (f"https://api.github.com/users/{urllib.parse.quote(owner)}/repos"
                   f"?per_page={_PER_PAGE}&page={page}&type=owner&sort=full_name")
            try:
                batch = self.client.get_json(url)
            except ModFetchError as exc:
                if not collected:
                    self._failed[key] = str(exc)
                break
            if not isinstance(batch, list) or not batch:
                break
            for entry in batch:
                name = entry.get("name")
                if name:
                    collected.append(RepoRef(entry.get("owner", {}).get("login", owner),
                                             name, bool(entry.get("archived")),
                                             bool(entry.get("fork"))))
            if len(batch) < _PER_PAGE:
                break

        self._repos[key] = collected
        if collected:
            self._save_cache()
        return collected

    @property
    def failures(self) -> Dict[str, str]:
        return dict(self._failed)

    # ------------------------------------------------------------ matching
    def candidates(self, folder: str, display_name: str = "",
                   limit: int = 3) -> List[OwnerCandidate]:
        """Score every repo in the trusted owners against this mod's identity."""
        import difflib

        folder_key = normalize_key(folder)
        folder_core = _strip_prefix(folder_key)
        name_key = normalize_key(display_name)
        out: List[OwnerCandidate] = []

        for owner in self.owners:
            for repo in self.repos_for(owner):
                repo_key = normalize_key(repo.name)
                repo_core = _strip_prefix(repo_key)
                score, why = 0.0, ""

                if repo_key == folder_key:
                    score, why = 1.0, "repository name equals the mod folder"
                elif repo_core and repo_core == folder_core:
                    score, why = 0.92, "equal after stripping author prefixes"
                elif len(folder_core) >= 5 and folder_core in repo_key:
                    score, why = 0.80, "repository name contains the mod folder"
                elif name_key and normalize_key(repo.name.replace("_", "")) == name_key:
                    score, why = 0.78, "repository name equals the mod's display name"
                else:
                    ratio = difflib.SequenceMatcher(None, folder_core, repo_core).ratio()
                    if ratio >= 0.72:
                        score, why = round(ratio * 0.75, 3), f"name similarity {ratio:.0%}"

                if score > 0:
                    if repo.archived:
                        score -= 0.05
                        why += " (archived)"
                    if repo.fork:
                        score -= 0.10
                        why += " (fork)"
                    out.append(OwnerCandidate(repo, score, why))

        out.sort(key=lambda c: (-c.score, c.repo.full_name))
        return out[:limit]


def load_trusted_owners(path: Optional[str], manifest=None,
                        extra: Sequence[str] = ()) -> List[str]:
    """
    Build the allowlist: shipped houses + every owner the manifest already
    trusts + anything passed explicitly. An owner your catalogue already
    depends on is, by definition, one you have already accepted.
    """
    owners: List[str] = []
    seen = set()

    def add(value):
        if value and value.lower() not in seen:
            seen.add(value.lower())
            owners.append(value)

    if path:
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError) as exc:
            raise ModFetchError(f"cannot read trusted-owner file {path}: {exc}") from exc
        entries = raw.get("owners", raw) if isinstance(raw, dict) else raw
        if not isinstance(entries, list):
            raise ModFetchError(f"{path}: expected a list of owner names")
        for owner in entries:
            add(str(owner))
    else:
        for owner in SHIPPED_TRUSTED_OWNERS:
            add(owner)

    if manifest is not None:
        for source in manifest.sources.values():
            if source.github and "/" in source.github:
                add(source.github.split("/", 1)[0])
    for owner in extra:
        add(owner)
    return owners
