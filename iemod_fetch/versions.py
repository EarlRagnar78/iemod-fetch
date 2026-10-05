"""
Comparing mod version strings, honestly.

Mod versions in this ecosystem are not semver: `v14.1`, `Alpha 3`,
`v0.11.0-alpha`, `vEAOB.9`, `2.8`, `v.4.6.4`, `20.2`. Any comparator will meet
pairs it cannot rank, and guessing there would be worse than admitting it — so
`compare` returns None for those, and every caller must handle None as
"unknown", never as "equal".
"""
import re
from typing import Optional, Tuple

# Stability ordering, least stable first:
#     branch snapshot  <  alpha  <  beta  <  rc  <  a numbered release
# A snapshot of master is what you get when a repository publishes no release at
# all, so it ranks lowest. Note this is a *stability* order, not a chronological
# one - master is often newer code than the last tag. Ranking it lowest is the
# conservative choice: it never lets a snapshot suppress a rule as "stale".
_PRERELEASE = {
    "master": -6, "main": -6, "head": -6, "trunk": -6, "default": -6,
    "snapshot": -5, "nightly": -5, "git": -5, "dev": -4, "devel": -4,
    "alpha": -3, "a": -3,
    "beta": -2, "b": -2,
    "rc": -1, "pre": -1, "prerelease": -1,
}
_TRIM = re.compile(r"^[vV]\.?\s*")
_SPLIT = re.compile(r"[^0-9A-Za-z]+")


def parse_version(text: Optional[str]) -> Optional[Tuple]:
    """Split a version into comparable parts, or None if there is nothing to compare."""
    if not text:
        return None
    cleaned = _TRIM.sub("", str(text).strip())
    parts = []
    for chunk in _SPLIT.split(cleaned):
        if not chunk:
            continue
        for piece in re.findall(r"\d+|[A-Za-z]+", chunk):
            parts.append(int(piece) if piece.isdigit() else piece.lower())
    return tuple(parts) or None


def compare(left: Optional[str], right: Optional[str]) -> Optional[int]:
    """
    -1 / 0 / 1 if `left` is older / same / newer than `right`; None if unknown.
    """
    a, b = parse_version(left), parse_version(right)
    if not a or not b:
        return None
    for x, y in zip(a, b):
        if x == y:
            continue
        if isinstance(x, int) and isinstance(y, int):
            return -1 if x < y else 1
        # a pre-release marker sorts before the release it qualifies
        if isinstance(x, str) and isinstance(y, int):
            return -1 if x in _PRERELEASE else None
        if isinstance(x, int) and isinstance(y, str):
            return 1 if y in _PRERELEASE else None
        if x in _PRERELEASE and y in _PRERELEASE:
            if _PRERELEASE[x] == _PRERELEASE[y]:
                # Two spellings of the same stability level - `master`/`main`,
                # `alpha`/`a`, `rc`/`pre`. Returning 1 here (as this did) made
                # the comparator claim BOTH that master is newer than main and
                # that main is newer than master, so `is_newer` was true in both
                # directions and a synonym rename upstream could mark a rule
                # stale. They are equal at this position; the next one decides.
                continue
            return -1 if _PRERELEASE[x] < _PRERELEASE[y] else 1
        # One pre-release marker against an arbitrary word ("EAOB" vs "Alpha")
        # is not rankable either. Saying so is the point.
        return None
    if len(a) == len(b):
        return 0
    longer, sign = (a, 1) if len(a) > len(b) else (b, -1)
    tail = longer[min(len(a), len(b))]
    if isinstance(tail, str) and tail in _PRERELEASE:
        return -sign                     # 1.0-alpha is older than 1.0
    return sign


def is_newer(candidate: Optional[str], baseline: Optional[str]) -> Optional[bool]:
    result = compare(candidate, baseline)
    return None if result is None else result > 0
