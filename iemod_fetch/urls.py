"""
URL facts, with no network attached.

These three functions answer questions about a URL string: which repository does
it name, what is really behind this forum interstitial, how do I ask Dropbox for
the file rather than the viewer page. None of them fetches anything.

They lived in `resolvers` — which does HTTP — until the architecture contract in
`.importlinter` refused the import that `catalogues` needed to reach them.
`catalogues` had been working around it with a function-local `from .resolvers
import repo_from_url` to dodge a cycle, which is the usual sign that a pure
thing is trapped inside an impure module. Extracting them makes the catalogue
layer honestly pure, and makes these testable without a client at all.
"""
import re
import urllib.parse
from typing import Optional

ARCHIVE_EXT = (".iemod", ".zip", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz",
               ".7z", ".rar")

# Forum software wraps outbound links in an interstitial; the real target is a
# query parameter on it.
_REDIRECT_PARAMS = ("target", "url", "u", "redirect", "link")
_INTERSTITIAL = re.compile(r"/(leaving|redirect|goto|out)(\.\w+)?/?$", re.IGNORECASE)
_REPO_PART = re.compile(r"[A-Za-z0-9._-]+")


def has_archive_ext(path: str) -> bool:
    lowered = (path or "").lower()
    return any(lowered.endswith(ext) for ext in ARCHIVE_EXT)


def unwrap_redirect(url: str) -> str:
    """Return the real destination behind a forum 'you are leaving' interstitial."""
    parsed = urllib.parse.urlsplit(url or "")
    if not _INTERSTITIAL.search(parsed.path):
        return url
    query = urllib.parse.parse_qs(parsed.query)
    for key in _REDIRECT_PARAMS:
        for value in query.get(key, ()):
            if value.startswith(("http://", "https://")):
                return value
    return url


def repo_from_url(url: str) -> Optional[str]:
    """Extract owner/repo from a github.com URL. Returns None for profile URLs."""
    parsed = urllib.parse.urlparse(url or "")
    if parsed.hostname not in ("github.com", "www.github.com"):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    repo = repo.removesuffix(".git")
    if not _REPO_PART.fullmatch(owner) or not _REPO_PART.fullmatch(repo):
        return None
    return f"{owner}/{repo}"


def normalize_dropbox(url: str) -> str:
    """Force dl=1 without destroying the rest of the query (rlkey, st, ...)."""
    parsed = urllib.parse.urlsplit(url)
    query = [(k, v) for k, v in
             urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
             if k != "dl"]
    query.append(("dl", "1"))
    return urllib.parse.urlunsplit(
        parsed._replace(query=urllib.parse.urlencode(query), fragment=""))
