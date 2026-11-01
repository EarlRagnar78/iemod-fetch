"""
HTTP layer with an explicit security policy.

Policy (ADR-0003):
  * https only, unless --allow-http is given for a specific run;
  * the GitHub credential is attached ONLY to api.github.com / github.com and is
    dropped on every cross-host redirect, including GitHub's own CDN;
  * responses are size-capped and streamed to a temporary file, then verified by
    content sniffing and (when known) sha256 before anything is extracted;
  * retries honour Retry-After (seconds or an HTTP date) and never retry a
    deterministic 4xx - but for GitHub's secondary rate limit, a 403 or 429
    that GitHub's docs say to wait out and retry (GUI-AUDIT item 45).
"""
import contextlib
import email.utils
import errno
import functools
import hashlib
import http.client
import importlib.resources
import ipaddress
import math
import os
import random
import shutil
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from publicsuffixlist import PublicSuffixList
from typing import TYPE_CHECKING, TypeVar
from collections.abc import Callable

from . import atomic
from .archives import Kind, detect_kind
from .errors import (Cancelled, ChecksumMismatch, HttpStatusError, InsecureURL,
                     NetworkError, NotAnArchive, TooLarge)

if TYPE_CHECKING:
    from .etagcache import ETagCache

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
_PROGRESS_STEP = 256 * 1024     # a progress bar needs a few updates, not thousands
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_MAX_WAIT = 300.0               # seconds; a longer Retry-After is not waited out
# Errors from the local filesystem, which no amount of retrying will fix.
_LOCAL_ERRNOS = {errno.ENOSPC, errno.EACCES, errno.EPERM, errno.EROFS,
                 errno.ENAMETOOLONG, getattr(errno, "EDQUOT", errno.ENOSPC)}


def host_of(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").lower().rstrip(".")


def is_github_auth_host(url_or_host: str) -> bool:
    host = url_or_host if "/" not in url_or_host else host_of(url_or_host)
    return host.lower().rstrip(".") in GITHUB_AUTH_HOSTS


@functools.cache
def _suffixes() -> PublicSuffixList:
    """The Public Suffix List the library carries, read through
    importlib.resources so it loads from inside the .pyz too (the library's
    own default opens a path beside its file, which a zip has not)."""
    data = importlib.resources.files("publicsuffixlist").joinpath("public_suffix_list.dat")
    with data.open("rb") as fh:
        return PublicSuffixList(source=fh)


def registrable_suffix(host: str) -> str:
    """A host's site: its registrable domain by the Public Suffix List, private
    suffixes included - `a.github.io` and `b.github.io` are two sites, as two
    users' pages are (ADR-0043; the hand-written rule took both for
    `github.io`). An address, a suffix itself or a single label is its own
    site."""
    host = host.lower().rstrip(".")
    try:
        ipaddress.ip_address(host.strip("[]"))
        return host
    except ValueError:
        pass
    return _suffixes().privatesuffix(host) or host


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


def _release(exc: urllib.error.HTTPError) -> None:
    # Python 3.9: an HTTPError built with fp=None never initialised its file
    # wrapper, so close() raises. There is nothing to release in that case.
    with contextlib.suppress(KeyError, AttributeError):
        exc.close()


def ascii_url(url: str) -> str:
    """
    `url` as http.client can send it. A catalogue may hold a link as a person
    typed it (`.../BG2_Mes_créations`); http.client refuses non-ASCII and the
    mod failed with an internal error before its other sources were tried. The
    host is IDNA-encoded, the rest percent-encoded; what is already encoded
    stays as it is.
    """
    if url.isascii():
        return url
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        host = urllib.parse.quote(host, safe="")
    netloc = host + (f":{parts.port}" if parts.port else "")
    if parts.username:
        user = urllib.parse.quote(parts.username, safe="")
        if parts.password:
            user += ":" + urllib.parse.quote(parts.password, safe="")
        netloc = f"{user}@{netloc}"
    keep = "/%:@!$&'()*+,;=~-._"
    return urllib.parse.urlunsplit((
        parts.scheme, netloc, urllib.parse.quote(parts.path, safe=keep),
        urllib.parse.quote(parts.query, safe=keep + "?"),
        urllib.parse.quote(parts.fragment, safe=keep + "?")))


_HTTPS_CONTEXT: ssl.SSLContext | None = None
_HTTPS_LOCK = threading.Lock()


def https_context() -> ssl.SSLContext:
    """
    The process's one verifying TLS context (ADR-0048), built on first use.

    urllib builds a new one for every opener, and building one loads the
    system's trust store: on Windows `ssl` reads every certificate of the
    certificate store and parses them while it holds the GIL - 50-60 ms on a
    GitHub runner, 240 ms once - so a download started from the wizard froze
    its window that long. Built once and shared (an SSLContext may serve
    connections from several threads), the cost is paid once per process,
    and the wizard pays it before its window is drawn (`prepare_https`).
    Built as http.client builds its own: through
    ssl._create_default_https_context (so the PEP 476 hook a site may set is
    still honoured), ALPN http/1.1, post-handshake auth on.
    """
    global _HTTPS_CONTEXT  # noqa: PLW0603 (one per process, set once under the lock)
    with _HTTPS_LOCK:
        if _HTTPS_CONTEXT is None:
            context = ssl._create_default_https_context()  # noqa: SLF001 (PEP 476 hook)
            context.set_alpn_protocols(["http/1.1"])
            if context.post_handshake_auth is not None:
                context.post_handshake_auth = True
            _HTTPS_CONTEXT = context
        return _HTTPS_CONTEXT


class HttpClient:
    def __init__(self, token: str | None = None, allow_http: bool = False,
                 timeout: int = DEFAULT_TIMEOUT, max_bytes: int = DEFAULT_MAX_BYTES,
                 retries: int = 3, sleep=time.sleep):
        self.token = token
        self.allow_http = allow_http
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.retries = max(1, retries)
        self._sleep = sleep
        # The run's cancel event (Runner sets it): a wait between retries ends
        # when it is set, so Cancel never waits out a rate limit (review of #61).
        self.cancel = None
        # GitHub API answers kept by ETag (etagcache.ETagCache; api wires it):
        # an unchanged answer is a 304 with no body, free with a token
        self.etags: ETagCache | None = None
        self.not_modified = 0
        self._opener = urllib.request.build_opener(
            SafeRedirectHandler(allow_http), urllib.request.HTTPSHandler(context=https_context()))

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
    def open(self, url: str, method: str = "GET", extra_headers: dict | None = None):
        self.check_url(url)
        url = ascii_url(url)
        headers = self.headers_for(url)
        headers.update(extra_headers or {})
        req = urllib.request.Request(url, headers=headers, method=method)
        return self._opener.open(req, timeout=self.timeout)

    def _with_retries(self, url: str, action: Callable[[], _T], cancel=None) -> _T:
        stop = cancel if cancel is not None else self.cancel
        last: BaseException | None = None
        for attempt in range(1, self.retries + 1):
            if stop is not None and stop.is_set():
                raise Cancelled(f"{url}: cancelled")
            try:
                return action()
            except urllib.error.HTTPError as exc:
                last = exc
                secondary = self._secondary_limit(url, exc)
                # The error owns the response socket. Only its status, headers
                # and the start of its body are used, so release the connection
                # now rather than whenever the exception is garbage-collected.
                _release(exc)
                spent = self._rate_limit_reason(exc)
                # A spent hourly quota resets up to an hour away, a 429 as much
                # as a 403: GitHub's docs say wait for the reset, not retry
                if (exc.code not in _RETRYABLE_STATUS and not secondary) or spent:
                    raise HttpStatusError(url, exc.code,
                                          spent or exc.reason or "") from exc
                asked = self._retry_after(exc, cap=math.inf)
                if secondary and asked is not None and asked > _MAX_WAIT:
                    # retrying sooner than GitHub asks prolongs the limit
                    raise HttpStatusError(url, exc.code,
                                          f"GitHub's secondary rate limit: it asks to wait "
                                          f"{asked:.0f} s; run again later") from exc
                delay = self._retry_after(exc) or (
                    self._secondary_backoff(attempt) if secondary else self._backoff(attempt))
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError,
                    http.client.HTTPException) as exc:
                # IncompleteRead - a transfer cut short - is an HTTPException,
                # not an OSError, and is the commonest failure on forum hosts.
                # A local disk or permission error is not transient: retrying
                # it only downloads the whole file again to fail the same way.
                if isinstance(exc, OSError) and exc.errno in _LOCAL_ERRNOS:
                    raise
                last = exc
                delay = self._backoff(attempt)
            if attempt == self.retries:
                break
            self._wait(url, delay, stop)
        raise NetworkError(f"{url}: giving up after {self.retries} attempts: {last}") from last

    def _wait(self, url: str, delay: float, stop) -> None:
        """Sleep `delay`, or less if the run is cancelled meanwhile."""
        if stop is not None and self._sleep is time.sleep and hasattr(stop, "wait"):
            if stop.wait(delay):
                raise Cancelled(f"{url}: cancelled")
            return
        self._sleep(delay)
        if stop is not None and stop.is_set():
            raise Cancelled(f"{url}: cancelled")

    @staticmethod
    def _retry_after(exc, cap: float = 300.0) -> float | None:
        value = exc.headers.get("Retry-After") if getattr(exc, "headers", None) else None
        if not value:
            return None
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            # RFC 9110 allows an HTTP date too: wait until then
            try:
                when = email.utils.parsedate_to_datetime(value)
            except (TypeError, ValueError, IndexError, OverflowError):
                return None      # junk: fall back to backoff
            if when.tzinfo is None:
                return None
            seconds = when.timestamp() - time.time()
        # Server input: NaN or a negative value would make time.sleep raise.
        if math.isnan(seconds):
            return None
        return min(max(seconds, 0.0), cap)

    @staticmethod
    def _secondary_limit(url: str, exc) -> bool:
        """
        GitHub's secondary rate limit: a 403 or 429 from GitHub while the
        hourly quota is not spent, with a Retry-After or GitHub's own words in
        the body. GitHub's docs say to wait and retry it; a 403 that is a real
        refusal has neither, and an exhausted quota (X-RateLimit-Remaining 0,
        reset up to an hour away) still stops at once with its own message.
        """
        if exc.code not in (403, 429) or host_of(url) not in GITHUB_AUTH_HOSTS:
            return False
        headers = getattr(exc, "headers", None) or {}
        if headers.get("X-RateLimit-Remaining") == "0":
            return False
        if headers.get("Retry-After"):
            return True
        body = b""
        with contextlib.suppress(OSError, AttributeError, KeyError, ValueError,
                                 http.client.HTTPException):
            body = exc.read(4096) or b""
        return b"secondary rate limit" in body.lower()

    @staticmethod
    def _secondary_backoff(attempt: int) -> float:
        """GitHub: at least one minute, then longer each time."""
        return float(min(60 * 2 ** (attempt - 1), _MAX_WAIT))

    @staticmethod
    def _rate_limit_reason(exc) -> str | None:
        """GitHub's quota, named as such: a bare 403 reads as a permission error."""
        headers = getattr(exc, "headers", None)
        if not headers or headers.get("X-RateLimit-Remaining") != "0":
            return None
        reset = headers.get("X-RateLimit-Reset") or ""
        when = "unknown"
        if reset.isdigit() and len(reset) <= 11:     # epoch seconds; gmtime overflows
            when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(reset)))
        return (f"GitHub API rate limit exhausted (resets {when}); "
                f"a token raises the limit from 60 to 5000 requests an hour")

    @staticmethod
    def _backoff(attempt: int) -> float:
        return float(min(2 ** attempt, 30) + random.uniform(0, 0.5))

    def read_bytes(self, url: str, limit: int | None = None) -> bytes:
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
        raw, etag = self._read_json(url, 8 * 1024 * 1024)
        try:
            value = _json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise NetworkError(f"{url}: expected JSON, got {raw[:120]!r}") from exc
        if etag and self.etags is not None:
            self.etags.put(url, etag, raw)
        return value

    def _read_json(self, url: str, cap: int) -> tuple[bytes, str | None]:
        """
        The body, and the ETag to keep it under when it is new. A GitHub API
        answer kept from an earlier run is asked for with If-None-Match; a 304
        means it is unchanged, and the kept body is used (GUI-AUDIT item 45).

        A git object named by its hash (`/git/trees/<sha>`) is not kept: its
        answer never changes, so it is never asked twice, and each new commit
        of the community data would add a file of its whole tree that nothing
        removes.
        """
        if (self.etags is None or host_of(url) != "api.github.com"
                or "/git/" in urllib.parse.urlsplit(url).path):
            return self.read_bytes(url, limit=cap), None
        kept = self.etags.get(url)

        def action() -> tuple[bytes, str | None]:
            headers = {"If-None-Match": kept[0]} if kept else None
            try:
                with self.open(url, extra_headers=headers) as resp:
                    data: bytes = resp.read(cap + 1)
                    etag = resp.headers.get("ETag")
            except urllib.error.HTTPError as exc:
                if exc.code == 304 and kept:
                    _release(exc)
                    self.not_modified += 1
                    return kept[1], None
                raise
            if len(data) > cap:
                raise TooLarge(f"{url}: response exceeded {cap} bytes")
            return data, etag

        return self._with_retries(url, action)

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
    def download(self, url: str, dest_path: str, expected_sha256: str | None = None,
                 require_archive: bool = True,
                 progress: Callable[[int, int | None], None] | None = None,
                 cancel=None) -> DownloadResult:
        """
        Stream `url` to `dest_path` atomically.

        The file is written to `<dest>.part`, hashed while streaming, checked
        against the byte ceiling, sniffed for an archive magic number and
        compared to `expected_sha256` when the manifest pins one. Only then is
        it renamed into place, so a partial or bogus download is never visible
        to the extractor.

        `progress(done, total)` is called as bytes arrive (total is None when
        the server does not say), at most every _PROGRESS_STEP bytes and once
        at the end. `cancel` is anything with `is_set()`, a threading.Event:
        once set, the download stops at the next chunk, raises Cancelled and
        leaves no file behind. A cancelled download is never retried.
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
                    expected = int(declared) if declared and declared.isdigit() else None
                    reported = 0
                    while True:
                        if cancel is not None and cancel.is_set():
                            raise Cancelled(f"{url}: cancelled")
                        chunk = resp.read(_CHUNK)
                        if not chunk:
                            break
                        total += len(chunk)
                        if progress is not None and total - reported >= _PROGRESS_STEP:
                            progress(total, expected)
                            reported = total
                        if total > self.max_bytes:
                            raise TooLarge(f"{url}: exceeded {self.max_bytes} byte ceiling")
                        if len(head) < 512:
                            head += chunk[:512 - len(head)]
                        digest.update(chunk)
                        out.write(chunk)
                    # http.client's read(n) does not raise on a short body: it
                    # returns what arrived, then b"". A cut connection would
                    # pass as a complete download whose first bytes look right.
                    if declared and declared.isdigit() and total != int(declared):
                        raise http.client.IncompleteRead(b"", int(declared) - total)
                    out.flush()
                    os.fsync(out.fileno())
                    if progress is not None and reported != total:
                        progress(total, expected)

                actual = digest.hexdigest()
                kind = detect_kind(head)
                if require_archive and kind is Kind.UNKNOWN:
                    raise NotAnArchive(url, head[:160], final_url=final_url)
                if expected_sha256 and actual.lower() != expected_sha256.lower():
                    raise ChecksumMismatch(url, expected_sha256, actual)

                atomic.replace(part, dest_path)
                return DownloadResult(dest_path, actual, total, kind, final_url)
            finally:
                if os.path.exists(part):
                    os.remove(part)

        return self._with_retries(url, action, cancel)


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["HttpClient", "DownloadResult", "SafeRedirectHandler", "host_of",
           "is_github_auth_host", "same_site", "registrable_suffix", "sha256_file",
           "shutil"]
