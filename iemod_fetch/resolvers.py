"""
Turning a manifest entry into exactly one download URL - or into an honest
"I don't know, here is what I found".

ADR-0006: resolution never guesses. The legacy script mutated repository names
and, failing that, installed the first hit of a GitHub code search - a name
anyone can register. Both are removed. An unresolvable entry is reported for a
human to decide, which is slower and correct.
"""
import fnmatch
import posixpath
import re
import urllib.parse
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import List, Optional

from .errors import InsecureURL, ModFetchError, NetworkError  # noqa: F401
from .manifest import ModSource
from .net import same_site
# Re-exported: these are URL facts, not networking, and live in `urls` so the
# catalogue layer can use them without importing anything that opens a socket.
from .urls import (ARCHIVE_EXT, has_archive_ext as _has_archive_ext,  # noqa: F401
                   normalize_dropbox, repo_from_url, unwrap_redirect)
_ASSET_TIERS = ((".iemod",), (".zip",), (".tar.gz", ".tgz", ".tar.bz2", ".tar.xz"),
                (".7z", ".rar"))
_ARCHIVE_CT = ("application/zip", "application/x-zip", "application/octet-stream",
               "application/x-7z", "application/x-rar", "application/gzip",
               "application/x-tar", "application/x-msdownload")

# A link must clear this to be downloaded unattended. A bare "/download/<slug>/"
# nav entry scores 20, which is deliberately below the bar: on a site that lists
# every mod in its sidebar, the alphabetically first one would otherwise win for
# every mod on the site.
_MIN_LINK_SCORE = 40



def _page_slug(url: str) -> str:
    path = urllib.parse.urlsplit(url).path.rstrip("/")
    return posixpath.basename(path).lower()


def _is_sibling_page(link: str, page_url: str) -> bool:
    """
    True when `link` is another entry in the same listing as `page_url`.

    `/download/alabaster-sands/` reached from `/download/shades-of-the-sword-coast/`
    is a different mod's page, not this mod's download.
    """
    link_path = urllib.parse.urlsplit(link).path.rstrip("/")
    page_path = urllib.parse.urlsplit(page_url).path.rstrip("/")
    if not link_path or link_path == page_path:
        return False
    return (posixpath.dirname(link_path) == posixpath.dirname(page_path)
            and posixpath.basename(link_path) != posixpath.basename(page_path))


@dataclass
class Candidate:
    url: str
    filename: str
    origin: str                       # release-asset | source-snapshot | direct | page-link
    version: Optional[str] = None
    sha256: Optional[str] = None
    offsite: bool = False


@dataclass
class Resolution:
    candidate: Optional[Candidate] = None
    reason: str = ""
    alternatives: List[Candidate] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.candidate is not None




class GitHubResolver:
    """Resolves a release asset via the REST API. No name guessing, no search."""

    def __init__(self, client, allow_exe: bool = False):
        self.client = client
        self.allow_exe = allow_exe

    def resolve(self, source: ModSource) -> Resolution:
        repo = source.github or repo_from_url(source.url or "")
        if not repo:
            return Resolution(reason=(
                f"no GitHub repository could be determined "
                f"({'url is a profile/organisation page' if source.url else 'no url'}: "
                f"{source.url!r})"))

        if source.release_tag:
            api = f"https://api.github.com/repos/{repo}/releases/tags/{urllib.parse.quote(source.release_tag)}"
        else:
            api = f"https://api.github.com/repos/{repo}/releases/latest"

        try:
            data = self.client.get_json(api)
        except ModFetchError as exc:
            if getattr(exc, "status", None) == 404 and not source.release_tag:
                # Plenty of Infinity Engine mods never cut a GitHub release; the
                # repository IS the mod. Falling back to its default branch is
                # deterministic - it is the repo the manifest already names, not
                # a guess - so try it before giving up.
                snapshot = self._default_branch_snapshot(repo, source)
                if snapshot:
                    return snapshot
            hint = ""
            status = getattr(exc, "status", None)
            if status == 404:
                hint = (f" - {repo} has no published release"
                        f"{' tagged ' + source.release_tag if source.release_tag else 's'}"
                        f" (or the repository was renamed)")
            elif status in (401, 403):
                hint = " - rate limited or credential rejected; set GH_TOKEN"
            return Resolution(reason=f"GitHub API: {exc}{hint}")

        version = data.get("tag_name")
        assets = [a for a in data.get("assets", []) if a.get("browser_download_url")]
        res = self._pick_asset(source, assets, version)
        if res.ok:
            return res

        for key, origin in (("zipball_url", "source-snapshot"),
                            ("tarball_url", "source-snapshot")):
            if data.get(key):
                res.candidate = Candidate(
                    url=data[key], filename=f"{repo.replace('/', '-')}-{version or 'src'}.zip",
                    origin=origin, version=version, sha256=source.sha256)
                res.warnings.append(
                    f"{source.key}: release {version or '?'} publishes no archive asset; "
                    f"falling back to a source snapshot, which for many mods is NOT a "
                    f"ready-to-install package")
                return res
        res.reason = res.reason or f"release {version or '?'} of {repo} has no usable asset"
        return res

    def _default_branch_snapshot(self, repo: str,
                                source: ModSource) -> Optional[Resolution]:
        """Archive of the repository's default branch, for repos with no releases."""
        try:
            meta = self.client.get_json(f"https://api.github.com/repos/{repo}")
        except ModFetchError:
            return None
        branch = meta.get("default_branch")
        if not branch:
            return None
        url = f"https://api.github.com/repos/{repo}/zipball/{urllib.parse.quote(branch)}"
        res = Resolution(candidate=Candidate(
            url=url, filename=f"{repo.replace('/', '-')}-{branch}.zip",
            origin="source-snapshot", version=branch, sha256=source.sha256))
        res.warnings.append(
            f"{source.key}: {repo} publishes no releases; using a snapshot of its "
            f"'{branch}' branch. That is whatever is committed today, so pin it with "
            f"\"release_tag\" once you have a working copy.")
        return res

    def _pick_asset(self, source: ModSource, assets, version) -> Resolution:
        res = Resolution()
        if not assets:
            return Resolution(reason="release has no assets")

        names = [a["name"] for a in assets]
        if source.asset:
            matched = [a for a in assets
                       if fnmatch.fnmatch(a["name"].lower(), source.asset.lower())]
            if not matched:
                return Resolution(reason=f"pinned asset {source.asset!r} not in release "
                                         f"(available: {names})")
            if len(matched) > 1:
                return Resolution(
                    reason=f"pinned asset pattern {source.asset!r} is ambiguous: "
                           f"{[a['name'] for a in matched]}")
            chosen = matched[0]
            return Resolution(candidate=self._to_candidate(chosen, version, source))

        tiers = list(_ASSET_TIERS) + ([(".exe",)] if self.allow_exe else [])
        for tier in tiers:
            tier_hits = sorted((a for a in assets
                                if a["name"].lower().endswith(tuple(tier))),
                               key=lambda a: (len(a["name"]), a["name"]))
            if not tier_hits:
                continue
            if len(tier_hits) > 1:
                res.warnings.append(
                    f"{source.key}: release has {len(tier_hits)} {tier[0]} assets "
                    f"{[a['name'] for a in tier_hits]}; picked {tier_hits[0]['name']!r}. "
                    f"Pin it with \"asset\" in the manifest to make this deterministic.")
                res.alternatives = [self._to_candidate(a, version, source)
                                    for a in tier_hits[1:]]
            res.candidate = self._to_candidate(tier_hits[0], version, source)
            return res
        return Resolution(reason=f"no installable asset among {names}"
                                 + ("" if self.allow_exe else " (.exe ignored; --allow-exe)"))

    @staticmethod
    def _to_candidate(asset, version, source) -> Candidate:
        return Candidate(url=asset["browser_download_url"], filename=asset["name"],
                         origin="release-asset", version=version, sha256=source.sha256)


class _LinkExtractor(HTMLParser):
    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links = []
        self._current = None

    def handle_starttag(self, tag, attrs):
        attrs = {k.lower(): (v or "") for k, v in attrs}
        if tag == "a":
            href = attrs.get("href") or attrs.get("data-downloadurl") or attrs.get("data-url")
            if href and not href.lower().startswith(("javascript:", "mailto:", "#")):
                self._current = urllib.parse.urljoin(self.base_url, href)
                self.links.append([self._current, ""])
        elif tag == "meta" and attrs.get("http-equiv", "").lower() == "refresh":
            match = re.search(r"url=([^;]+)$", attrs.get("content", ""), re.IGNORECASE)
            if match:
                self.links.append(
                    [urllib.parse.urljoin(self.base_url, match.group(1).strip("'\" ")), "refresh"])

    def handle_data(self, data):
        if self._current and self.links and data.strip():
            self.links[-1][1] = (self.links[-1][1] + " " + data.strip())[:120]

    def handle_endtag(self, tag):
        if tag == "a":
            self._current = None




class LandingPageResolver:
    """
    Scrapes a mod's landing page for its download link.

    Two rules make this safe enough to automate:
      * the credential is never sent here (enforced in net.HttpClient), and
      * a link is only auto-selected if it is on the same site as the page, so
        an advert or a hijacked CDN link is surfaced for review, not fetched.
    """

    def __init__(self, client, accept_offsite: bool = False, allow_exe: bool = False):
        self.client = client
        self.accept_offsite = accept_offsite
        self.allow_exe = allow_exe

    def resolve(self, source: ModSource) -> Resolution:
        url = source.url
        if not url:
            return Resolution(reason="entry has no url")

        if "dropbox.com" in (urllib.parse.urlparse(url).hostname or ""):
            direct = normalize_dropbox(url)
            return Resolution(candidate=Candidate(direct, posixpath.basename(
                urllib.parse.urlparse(direct).path) or f"{source.key}.zip",
                origin="direct", sha256=source.sha256))

        if _has_archive_ext(urllib.parse.urlparse(url).path):
            return Resolution(candidate=Candidate(
                url, posixpath.basename(urllib.parse.urlparse(url).path),
                origin="direct", sha256=source.sha256))

        try:
            with self.client.open(url) as resp:
                content_type = (resp.headers.get("Content-Type") or "").lower()
                final_url = resp.geturl()
                if any(ct in content_type for ct in _ARCHIVE_CT):
                    name = self._filename(resp, final_url, source)
                    return Resolution(candidate=Candidate(final_url, name, "direct",
                                                          sha256=source.sha256))
                if "text/html" not in content_type and content_type:
                    return Resolution(reason=f"unexpected Content-Type {content_type!r}")
                body = resp.read(4 * 1024 * 1024).decode("utf-8", errors="replace")
        except (InsecureURL, NetworkError, ModFetchError) as exc:
            return Resolution(reason=str(exc))
        except OSError as exc:
            return Resolution(reason=f"cannot fetch landing page: {exc}")

        return self._from_html(source, final_url, body)

    @staticmethod
    def _filename(resp, url, source) -> str:
        disp = resp.headers.get("Content-Disposition") or ""
        match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', disp, re.IGNORECASE)
        if match:
            return posixpath.basename(match.group(1).strip())
        return posixpath.basename(urllib.parse.urlparse(url).path) or f"{source.key}.zip"

    def _from_html(self, source, page_url, body) -> Resolution:
        parser = _LinkExtractor(page_url)
        try:
            parser.feed(body)
        except Exception as exc:                     # HTMLParser on malformed input
            return Resolution(reason=f"could not parse landing page: {exc}")

        slug = _page_slug(page_url)
        scored = []
        for raw_link, text in parser.links:
            link = unwrap_redirect(raw_link)
            score = self._score(link, text)
            if score <= 0:
                continue
            if same_site(link, page_url) and _is_sibling_page(link, page_url):
                continue          # another mod's page in the same listing
            if slug and slug in link.lower():
                score += 30       # this page's own slug appears in the link
            if score < _MIN_LINK_SCORE:
                continue
            scored.append((score, Candidate(
                link, posixpath.basename(urllib.parse.urlparse(link).path) or source.key,
                origin="page-link", sha256=source.sha256,
                offsite=not same_site(link, page_url))))
        if not scored:
            return Resolution(
                reason="no download link on the landing page scored high enough to "
                       "use unattended (navigation links to other mods are ignored); "
                       "open the page and pin the real URL in the manifest")

        scored.sort(key=lambda pair: -pair[0])
        onsite = [c for _, c in scored if not c.offsite]
        offsite = [c for _, c in scored if c.offsite]

        if onsite:
            res = Resolution(candidate=onsite[0], alternatives=onsite[1:] + offsite)
            if offsite:
                res.warnings.append(
                    f"{source.key}: ignored {len(offsite)} off-site link(s) on the page")
            return res
        if self.accept_offsite:
            res = Resolution(candidate=offsite[0], alternatives=offsite[1:])
            res.warnings.append(
                f"{source.key}: using OFF-SITE link {offsite[0].url} (--accept-offsite)")
            return res
        return Resolution(
            reason="only off-site links found; review and pin one in the manifest",
            alternatives=offsite)

    def _score(self, link: str, text: str) -> int:
        parsed = urllib.parse.urlparse(link)
        path, query, blob = parsed.path.lower(), parsed.query.lower(), link.lower()
        if path.endswith(".exe") and not self.allow_exe:
            return 0
        score = 0
        if _has_archive_ext(path):
            score += 100
        if "wpdmdl=" in query:                     # WeaselMods / WP Download Manager
            score += 90
        if "do=download" in query:                 # Invision (Gibberlings3, SHS)
            score += 80
        if re.search(r"/(download|files?|attachment)s?/", path):
            score += 20
        if "download" in (text or "").lower():
            score += 10
        if any(bad in blob for bad in ("/login", "/register", "signin", "captcha",
                                       "advert", "sponsor", "doubleclick")):
            score -= 200
        return score
