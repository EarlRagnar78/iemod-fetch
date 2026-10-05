"""Shared test doubles: an offline urllib opener so no test ever touches the network."""
import io
import json
import os
import sys
import urllib.error
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class FakeResponse(io.BytesIO):
    """Minimal stand-in for http.client.HTTPResponse."""

    def __init__(self, body=b"", status=200, headers=None, url="https://example.invalid/"):
        super().__init__(body if isinstance(body, bytes) else body.encode("utf-8"))
        self.status = status
        self.code = status
        self.url = url
        self.headers = _Headers(headers or {})

    def geturl(self):
        return self.url

    def info(self):
        return self.headers

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class _Headers(dict):
    def get(self, key, default=None):
        for k, v in self.items():
            if k.lower() == str(key).lower():
                return v
        return default


class RecordingOpener:
    """Records every Request it is asked to open and replays scripted responses."""

    def __init__(self, routes=None, default=None):
        self.routes = routes or {}          # substring -> callable(req) | FakeResponse factory
        self.default = default
        self.requests = []                  # list of urllib.request.Request

    def open(self, req, *args, **kwargs):
        if isinstance(req, str):
            req = urllib.request.Request(req)
        self.requests.append(req)
        for needle, handler in self.routes.items():
            if needle in req.full_url:
                return handler(req) if callable(handler) else handler
        if self.default is not None:
            return self.default(req) if callable(self.default) else self.default
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", None, None)

    # convenience assertions
    def header_sent_to(self, needle, header):
        for r in self.requests:
            if needle in r.full_url:
                return r.get_header(header.capitalize()) or r.headers.get(header)
        return None

    @property
    def urls(self):
        return [r.full_url for r in self.requests]


@pytest.fixture
def fake_opener(monkeypatch):
    """Install a RecordingOpener in place of urllib.request.build_opener."""
    holder = {}

    def install(routes=None, default=None):
        opener = RecordingOpener(routes, default)
        holder["opener"] = opener
        monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **k: opener)
        return opener

    install.get = lambda: holder.get("opener")
    return install


def json_response(payload, status=200):
    return FakeResponse(json.dumps(payload).encode("utf-8"), status=status,
                        headers={"Content-Type": "application/json"})


# ---------------------------------------------------------------- hypothesis
# Two profiles. The pull-request run stays fast enough that nobody skips it; the
# nightly job gets the budget where a rare counterexample actually lives.
try:
    from hypothesis import HealthCheck, settings

    settings.register_profile(
        "default", max_examples=300, deadline=None,
        suppress_health_check=[HealthCheck.too_slow])
    settings.register_profile(
        "nightly", max_examples=20000, deadline=None,
        suppress_health_check=[HealthCheck.too_slow])
    settings.load_profile(__import__("os").environ.get("HYPOTHESIS_PROFILE",
                                                       "default"))
except ImportError:                          # pragma: no cover - stdlib-only run
    pass
