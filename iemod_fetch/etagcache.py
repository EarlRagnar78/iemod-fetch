"""
GitHub API answers kept with their ETag, for conditional requests (GUI-AUDIT
M7 item 45).

A run asks GitHub the same questions as the run before it: each mod's latest
release, the community data's HEAD. Sent with `If-None-Match: <etag>`, an
unchanged answer comes back `304 Not Modified` with no body, and the body kept
here is used. GitHub's docs: a 304 does not count against the primary rate
limit *when the request is authorized* - measured on 2026-10-23, a 200 took
one from X-RateLimit-Remaining and a 304 none. Without a token a 304 still
counts, so then it saves bandwidth, not quota.

One file per URL, named by its sha256, written whole (`atomic.write_text`)
and readable by its owner only. A file that does not read back as an entry
for that URL is ignored, as if it were not there.
"""
import contextlib
import hashlib
import json
import os

from .atomic import write_text


class ETagCache:
    def __init__(self, folder: str):
        self.folder = folder

    def _path(self, url: str) -> str:
        return os.path.join(self.folder,
                            hashlib.sha256(url.encode("utf-8")).hexdigest() + ".json")

    def get(self, url: str) -> tuple[str, bytes] | None:
        """(etag, body) kept for `url`, or None."""
        try:
            with open(self._path(url), encoding="utf-8") as fh:
                entry = json.load(fh)
        except (OSError, ValueError):
            return None
        if (not isinstance(entry, dict) or entry.get("url") != url
                or not isinstance(entry.get("etag"), str) or not entry["etag"]
                or not isinstance(entry.get("body"), str)):
            return None
        return entry["etag"], entry["body"].encode("utf-8")

    def put(self, url: str, etag: str, body: bytes) -> None:
        """Keep `body` under `etag`; a cache that cannot be written is only slower."""
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return
        with contextlib.suppress(OSError):
            write_text(self._path(url), json.dumps({"url": url, "etag": etag, "body": text}))
