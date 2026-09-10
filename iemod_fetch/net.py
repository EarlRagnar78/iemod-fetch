"""
HTTP layer with an explicit security policy.

Policy (ADR-0003):
  * https only, unless --allow-http is given for a specific run;
  * the GitHub credential is attached ONLY to api.github.com / github.com and is
    dropped on every cross-host redirect, including GitHub's own CDN;
  * responses are size-capped and streamed to a temporary file, then verified by
    content sniffing and (when known) sha256 before anything is extracted;
  * retries honour Retry-After and never retry a deterministic 4xx.
"""
import hashlib
import os
import random
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional, TypeVar

from .archives import Kind, detect_kind
from .errors import (ChecksumMismatch, HttpStatusError, InsecureURL,
                     NetworkError, NotAnArchive, TooLarge)

# `_with_retries` returns exactly what the action it wraps returns. Saying so
# keeps `read_bytes -> bytes` and `download -> DownloadResult` honest instead of
# widening both to Any at the retry boundary.
_T = TypeVar("_T")

USER_AGENT = "iemod-fetch/2.0 (+https://github.com/; Infinity Engine mod fetcher)"

# Several mod hosts sit behind bot protection that rejects unknown agents
# outright - Gibberlings3 answers 403 and SHS 401. Identifying honestly to the
# GitHub API and as a browser to the forums is the pragmatic split: we are
# fetching a file a human could fetch by clicking, and no scraping-hostile
# behaviour (rate, concurrency, robots-ignoring) comes with it.
BROWSER_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36")

# Hosts allowed to receive the GitHub bearer token. Exact matches only: a
# suffix/substring test would accept `github.com.attacker.example`.
GITHUB_AUTH_HOSTS = frozenset({"api.github.com", "github.com"})

DEFAULT_MAX_BYTES = 2 * 1024 ** 3          # 2 GiB; real mods reach 1.5 GB
DEFAULT_TIMEOUT = 45
_CHUNK = 64 * 1024
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def host_of(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").lower().rstrip(".")


def is_github_auth_host(url_or_host: str) -> bool:
    host = url_or_host if "/" not in url_or_host else host_of(url_or_host)
    return host.lower().rstrip(".") in GITHUB_AUTH_HOSTS


def registrable_suffix(host: str) -> str:
    """Crude eTLD+1 for same-site link checks (adequate for the known mod hosts)."""
    parts = host.lower().rstrip(".").split(".")
    if len(parts) <= 2:
        return ".".join(parts)
    if parts[-2] in {"co", "com", "net", "org", "ac", "gov"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def same_site(a: str, b: str) -> bool:
    return registrable_suffix(host_of(a)) == registrable_suffix(host_of(b))


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Drops credentials on host change and refuses scheme downgrades."""

    def __init__(self, allow_http: bool = False):
        self.allow_http = allow_http

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        scheme = urllib.parse.urlparse(newurl).scheme.lower()
        if scheme != "https" and not (self.allow_http and scheme == "http"):  # noqa: FURB171
            raise InsecureURL(f"refusing redirect to non-https URL: {newurl}")

        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is None:
            return None
        if not is_github_auth_host(newurl):
            for store in (new_req.headers, new_req.unredirected_hdrs):
                for key in [k for k in list(store) if k.lower() == "authorization"]:
                    del store[key]
        return new_req


@dataclass
class DownloadResult:
    path: str
    sha256: str
    size: int
    kind: Kind
    final_url: str


class HttpClient:
    def __init__(self, token: Optional[str] = None, allow_http: bool = False,
                 timeout: int = DEFAULT_TIMEOUT, max_bytes: int = DEFAULT_MAX_BYTES,
                 retries: int = 3, sleep=time.sleep):
        self.token = token
        self.allow_http = allow_http
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.retries = max(1, retries)
        self._sleep = sleep
        self._opener = urllib.request.build_opener(SafeRedirectHandler(allow_http))

    # -- policy ------------------------------------------------------------
    def check_url(self, url: str) -> str:
        scheme = urllib.parse.urlparse(url).scheme.lower()
        if scheme == "https":
            return url
        if scheme == "http" and self.allow_http:
            return url
        raise InsecureURL(f"refusing {scheme or 'scheme-less'} URL (https required): {url}")

    def headers_for(self, url: str) -> dict:
        github = is_github_auth_host(url)
        headers = {"User-Agent": USER_AGENT if github else BROWSER_USER_AGENT,
                   "Accept-Encoding": "identity"}
        if not github:
            headers["Accept"] = ("text/html,application/xhtml+xml,application/xml;"
                                 "q=0.9,*/*;q=0.8")
            headers["Accept-Language"] = "en-US,en;q=0.9"
        if self.token and is_github_auth_host(url):
            headers["Authorization"] = f"Bearer {self.token}"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
            headers["Accept"] = "application/vnd.github+json"
        return headers

    # -- transport ---------------------------------------------------------
    def open(self, url: str, method: str = "GET", extra_headers: Optional[dict] = None):
        self.check_url(url)
        headers = self.headers_for(url)
        headers.update(extra_headers or {})
        req = urllib.request.Request(url, headers=headers, method=method)
        return self._opener.open(req, timeout=self.timeout)

    def _with_retries(self, url: str, action: Callable[[], _T]) -> _T:
        last: Optional[BaseException] = None
        for attempt in range(1, self.retries + 1):
            try:
                return action()
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code not in _RETRYABLE_STATUS:
                    raise HttpStatusError(url, exc.code, exc.reason or "") from exc
                delay = self._retry_after(exc) or self._backoff(attempt)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last = exc
                delay = self._backoff(attempt)
            if attempt == self.retries:
                break
            self._sleep(delay)
        raise NetworkError(f"{url}: giving up after {self.retries} attempts: {last}") from last

    @staticmethod
    def _retry_after(exc) -> Optional[float]:
        value = exc.headers.get("Retry-After") if getattr(exc, "headers", None) else None
        if not value:
            return None
        try:
            return min(float(value), 300.0)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _backoff(attempt: int) -> float:
        return float(min(2 ** attempt, 30) + random.uniform(0, 0.5))

    def read_bytes(self, url: str, limit: Optional[int] = None) -> bytes:
        cap = limit or self.max_bytes

        def action() -> bytes:
            with self.open(url) as resp:
                data: bytes = resp.read(cap + 1)
            if len(data) > cap:
                raise TooLarge(f"{url}: response exceeded {cap} bytes")
            return data

        return self._with_retries(url, action)

    def get_json(self, url: str):
        import json as _json
        raw = self.read_bytes(url, limit=8 * 1024 * 1024)
        try:
            return _json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise NetworkError(f"{url}: expected JSON, got {raw[:120]!r}") from exc

    def post_form(self, url: str, fields: dict) -> dict:
        """POST an application/x-www-form-urlencoded body and parse a JSON reply."""
        import json as _json
        body = urllib.parse.urlencode(fields).encode("utf-8")
        self.check_url(url)
        headers = self.headers_for(url)
        headers["Accept"] = "application/json"
        headers["Content-Type"] = "application/x-www-form-urlencoded"

        def action() -> dict:
            req = urllib.request.Request(url, data=body, headers=headers,
                                         method="POST")
            with self._opener.open(req, timeout=self.timeout) as resp:
                parsed = _json.loads(resp.read(1024 * 1024).decode("utf-8"))
            if not isinstance(parsed, dict):
                raise NetworkError(f"{url}: expected a JSON object, got "
                                   f"{type(parsed).__name__}")
            return parsed

        return self._with_retries(url, action)

    # -- download ----------------------------------------------------------
    def download(self, url: str, dest_path: str, expected_sha256: Optional[str] = None,
                 require_archive: bool = True) -> DownloadResult:
        """
        Stream `url` to `dest_path` atomically.

        The file is written to `<dest>.part`, hashed while streaming, checked
        against the byte ceiling, sniffed for an archive magic number and
        compared to `expected_sha256` when the manifest pins one. Only then is
        it renamed into place, so a partial or bogus download is never visible
        to the extractor.
        """
        def action() -> DownloadResult:
            part = dest_path + ".part"
            digest = hashlib.sha256()
            total = 0
            head = b""
            os.makedirs(os.path.dirname(os.path.abspath(part)) or ".", exist_ok=True)
            try:
                with self.open(url) as resp, open(part, "wb") as out:
                    final_url = resp.geturl()
                    declared = resp.headers.get("Content-Length")
                    if declared and declared.isdigit() and int(declared) > self.max_bytes:
                        raise TooLarge(f"{url}: Content-Length {declared} exceeds "
                                       f"{self.max_bytes} byte ceiling")
                    while True:
                        chunk = resp.read(_CHUNK)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > self.max_bytes:
                            raise TooLarge(f"{url}: exceeded {self.max_bytes} byte ceiling")
                        if len(head) < 512:
                            head += chunk[:512 - len(head)]
                        digest.update(chunk)
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())

                actual = digest.hexdigest()
                kind = detect_kind(head)
                if require_archive and kind is Kind.UNKNOWN:
                    raise NotAnArchive(url, head[:160])
                if expected_sha256 and actual.lower() != expected_sha256.lower():
                    raise ChecksumMismatch(url, expected_sha256, actual)

                os.replace(part, dest_path)
                return DownloadResult(dest_path, actual, total, kind, final_url)
            finally:
                if os.path.exists(part):
                    os.remove(part)

        return self._with_retries(url, action)


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["HttpClient", "DownloadResult", "SafeRedirectHandler", "host_of",
           "is_github_auth_host", "same_site", "registrable_suffix", "sha256_file",
           "shutil"]
