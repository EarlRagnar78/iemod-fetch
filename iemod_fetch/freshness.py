"""
Is there a newer version of a mod than the one installed? (M2d)

Three sources say what the latest version of a mod is, and none is right
alone:

* krion64's `version_cache.json`: each GitHub repository's latest release tag,
  checked daily. Authoritative for what was released, blind to mods that ship
  from master without tagging (UB: tag v28, while 29 is out);
* the BWS-NG mod database: the version its installer downloads;
* krion64's per-mod records: the version its site lists.

Measured against the VERSION in the tp2 at HEAD of 95 mod repositories
(docs/TESTING.md), each source alone agrees for 43-68 mods; the newest of all
three, compared with `versions.compare_published`, for 81. That is the rule
here: the latest is the newest any source names, and which source named it is
kept, so a front end can say "v14.1, GitHub release of 2026-09-10".

Where two versions cannot be ranked (`EAOB.9` against `v1_Beta260923`) the
answer is "unknown", never a guess: `update_available` is then None.
"""
import re
from dataclasses import dataclass
from collections.abc import Iterable

from .naming import plain_text
from .versions import compare_published

_GITHUB = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.IGNORECASE)

# Source order: on a tie the first wins, so a GitHub release - with a date and
# a page - is what a tie is reported as.
RELEASE = "github release"


@dataclass(frozen=True)
class Release:
    tag: str
    date: str | None = None
    url: str | None = None
    archived: bool = False
    # what the scan saw of the repository (GUI-AUDIT item 51): third-party
    # text, kept as text - control characters out, cut at NOTES_MAX
    name: str | None = None
    notes: str | None = None
    pushed: str | None = None
    checked: str | None = None         # the day the scan last looked at it


NOTES_MAX = 1500                       # characters of a release's notes kept


@dataclass(frozen=True)
class Candidate:
    version: str
    origin: str
    date: str | None = None
    url: str | None = None

    def as_dict(self) -> dict:
        return {k: v for k, v in (("version", self.version), ("origin", self.origin),
                                  ("date", self.date), ("url", self.url)) if v}


def github_repo(url: str | None) -> str | None:
    """`owner/repo`, lowercased, of a GitHub URL; None for anything else."""
    match = _GITHUB.search(url or "")
    if not match:
        return None
    repo = match.group(2)
    repo = repo[:-4] if repo.lower().endswith(".git") else repo
    return f"{match.group(1)}/{repo}".lower()


def parse_release_cache(raw) -> dict[str, Release]:
    """krion64's version_cache.json: {"owner/repo": {"tag", "release_date", ...}}."""
    out: dict[str, Release] = {}
    if not isinstance(raw, dict):
        return out
    for repo, entry in raw.items():
        if not isinstance(repo, str) or not isinstance(entry, dict):
            continue
        tag = plain_text(entry.get("tag"), 100)
        if not tag:
            continue                 # a repository with no release says nothing
        out[repo.lower()] = Release(
            tag=tag,
            date=plain_text(entry.get("release_date"), 40),
            url=entry.get("release_url") or None,
            archived=entry.get("archived") is True,
            name=plain_text(entry.get("release_name"), 200),
            notes=plain_text(entry.get("body")),
            pushed=plain_text(entry.get("pushed"), 40),
            checked=plain_text(entry.get("checked"), 40))
    return out


def latest(candidates: Iterable[Candidate]) -> Candidate | None:
    """The newest candidate; on a tie or an unrankable pair, the earlier one."""
    best: Candidate | None = None
    for candidate in candidates:
        if not candidate.version:
            continue
        if best is None or compare_published(candidate.version, best.version) == 1:
            best = candidate
    return best


def update_available(installed: str | None, newest: Candidate | None) -> bool | None:
    """True / False when the versions rank; None when either is unknown."""
    if not installed or newest is None:
        return None
    result = compare_published(newest.version, installed)
    return None if result is None else result > 0
