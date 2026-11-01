"""Transport policy - the fix for legacy defects L5, L6, L8."""
import email.utils
import io
import time
import urllib.error
import urllib.request
import zipfile

import pytest

from conftest import FakeResponse
from iemod_fetch.errors import (ChecksumMismatch, HttpStatusError, InsecureURL,
                                NetworkError, NotAnArchive, TooLarge)
from iemod_fetch.net import HttpClient, SafeRedirectHandler, is_github_auth_host

ZIP_BYTES = None


def _zip_bytes():
    global ZIP_BYTES
    if ZIP_BYTES is None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("mod/mod.tp2", "BACKUP ~mod/backup~")
        ZIP_BYTES = buf.getvalue()
    return ZIP_BYTES


# --------------------------------------------------------- credential scope
@pytest.mark.parametrize("url,expected", [
    ("https://api.github.com/repos/a/b/releases/latest", True),
    ("https://github.com/a/b/archive/refs/tags/v1.zip", True),
    # GitHub's own asset CDN must NOT receive the token (it 400s, and it is a
    # different trust domain):
    ("https://objects.githubusercontent.com/x", False),
    ("https://codeload.github.com/a/b/zip/main", False),
    # every third-party mod host in the real manifest:
    ("https://downloads.weaselmods.net/download/x/", False),
    ("https://www.gibberlings3.net/files/file/1/", False),
    ("https://www.shsforums.net/files/file/1/", False),
    ("http://www.pocketplane.net/index.php", False),
    # lookalike hosts (legacy defect L6):
    ("https://github.com.attacker.example/steal", False),
    ("https://evilgithub.com/steal", False),
    ("https://api.github.com.evil.net/steal", False),
])
def test_token_is_attached_only_to_real_github_hosts(url, expected):
    client = HttpClient(token="ghp_SECRET", allow_http=True)
    assert ("Authorization" in client.headers_for(url)) is expected
    assert is_github_auth_host(url) is expected


def test_redirect_to_a_lookalike_host_drops_the_credential():
    handler = SafeRedirectHandler()
    req = urllib.request.Request("https://api.github.com/x",
                                 headers={"Authorization": "Bearer SECRET"})
    new = handler.redirect_request(req, None, 302, "Found", {},
                                   "https://github.com.attacker.example/steal")
    assert new.get_header("Authorization") is None


def test_redirect_to_the_github_cdn_drops_the_credential():
    handler = SafeRedirectHandler()
    req = urllib.request.Request("https://api.github.com/x",
                                 headers={"Authorization": "Bearer SECRET"})
    new = handler.redirect_request(req, None, 302, "Found", {},
                                   "https://objects.githubusercontent.com/asset")
    assert new.get_header("Authorization") is None


def test_redirect_between_github_hosts_keeps_the_credential():
    handler = SafeRedirectHandler()
    req = urllib.request.Request("https://api.github.com/x",
                                 headers={"Authorization": "Bearer SECRET"})
    new = handler.redirect_request(req, None, 302, "Found", {},
                                   "https://github.com/a/b/releases/download/v1/m.zip")
    assert new.get_header("Authorization") == "Bearer SECRET"


def test_redirect_cannot_downgrade_to_cleartext():
    handler = SafeRedirectHandler(allow_http=False)
    req = urllib.request.Request("https://x.example/a")
    with pytest.raises(InsecureURL):
        handler.redirect_request(req, None, 302, "Found", {}, "http://x.example/b")


@pytest.mark.parametrize("url", ["http://x.example/m.zip", "file:///etc/passwd",
                                 "ftp://x.example/m.zip", "/etc/passwd"])
def test_non_https_urls_are_refused_by_default(url):
    with pytest.raises(InsecureURL):
        HttpClient().check_url(url)


def test_http_is_permitted_only_when_explicitly_enabled():
    assert HttpClient(allow_http=True).check_url("http://x.example/m.zip")


# ------------------------------------------------------------- download gate
def test_html_error_page_is_rejected_instead_of_stored(fake_opener, tmp_path):
    """Legacy defect L8: a 3 KB captcha page was accepted as an archive."""
    body = b"<html><body>403 - solve this captcha</body></html>" + b" " * 3000
    fake_opener(default=lambda r: FakeResponse(body))
    client = HttpClient()
    dest = tmp_path / "mod.zip"

    with pytest.raises(NotAnArchive):
        client.download("https://x.example/m.zip", str(dest))
    assert not dest.exists()
    assert not (tmp_path / "mod.zip.part").exists()


def test_download_is_capped(fake_opener, tmp_path):
    fake_opener(default=lambda r: FakeResponse(_zip_bytes() + b"\x00" * 100_000))
    client = HttpClient(max_bytes=1024)
    with pytest.raises(TooLarge):
        client.download("https://x.example/m.zip", str(tmp_path / "m.zip"))
    assert not (tmp_path / "m.zip").exists()


def test_content_length_over_the_ceiling_is_refused_before_reading(fake_opener, tmp_path):
    fake_opener(default=lambda r: FakeResponse(
        _zip_bytes(), headers={"Content-Length": "999999999999"}))
    with pytest.raises(TooLarge):
        HttpClient(max_bytes=1024).download("https://x.example/m.zip",
                                            str(tmp_path / "m.zip"))


def test_checksum_mismatch_rejects_the_artefact(fake_opener, tmp_path):
    fake_opener(default=lambda r: FakeResponse(_zip_bytes()))
    dest = tmp_path / "m.zip"
    with pytest.raises(ChecksumMismatch):
        HttpClient().download("https://x.example/m.zip", str(dest),
                              expected_sha256="00" * 32)
    assert not dest.exists()


def test_matching_checksum_is_accepted(fake_opener, tmp_path):
    import hashlib
    digest = hashlib.sha256(_zip_bytes()).hexdigest()
    fake_opener(default=lambda r: FakeResponse(_zip_bytes()))
    result = HttpClient().download("https://x.example/m.zip", str(tmp_path / "m.zip"),
                                   expected_sha256=digest)
    assert result.sha256 == digest
    assert (tmp_path / "m.zip").read_bytes() == _zip_bytes()


# ----------------------------------------------------------------- retrying
def test_transient_5xx_is_retried_then_succeeds(fake_opener, tmp_path):
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)
        return FakeResponse(_zip_bytes())

    fake_opener(default=flaky)
    client = HttpClient(retries=3, sleep=lambda *_: None)
    assert client.download("https://x.example/m.zip", str(tmp_path / "m.zip")).size > 0
    assert calls["n"] == 3


class _TruncatedResponse(FakeResponse):
    """The connection closes before Content-Length bytes arrived."""

    def read(self, *_a):
        import http.client
        raise http.client.IncompleteRead(b"PK\x03\x04partial", 4096)


def test_a_truncated_transfer_is_retried_not_an_internal_error(fake_opener, tmp_path):
    """IncompleteRead is an HTTPException, not an OSError: it escaped the retry
    loop and reached the runner as an 'internal error' on the first flaky host."""
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        return _TruncatedResponse(b"") if calls["n"] == 1 else FakeResponse(_zip_bytes())

    fake_opener(default=flaky)
    client = HttpClient(retries=3, sleep=lambda *_: None)
    assert client.download("https://x.example/m.zip", str(tmp_path / "m.zip")).size > 0
    assert calls["n"] == 2


def test_a_full_disk_is_not_retried(fake_opener, tmp_path, monkeypatch):
    """Retrying a local ENOSPC re-downloads the whole file to fail the same way."""
    import errno
    calls = {"n": 0}

    def ok(req):
        calls["n"] += 1
        return FakeResponse(_zip_bytes())

    def full(_fd):
        raise OSError(errno.ENOSPC, "No space left on device")

    fake_opener(default=ok)
    monkeypatch.setattr("iemod_fetch.net.os.fsync", full)
    with pytest.raises(OSError) as caught:
        HttpClient(retries=3, sleep=lambda *_: None).download(
            "https://x.example/m.zip", str(tmp_path / "m.zip"))
    assert caught.value.errno == errno.ENOSPC
    assert calls["n"] == 1
    assert not (tmp_path / "m.zip.part").exists()


def test_an_exhausted_github_rate_limit_says_so_and_when_it_resets(fake_opener):
    """A bare 'HTTP 403' reads as a permission problem. GitHub's own headers say
    it is the hourly quota, and when it comes back - and that a token raises it."""
    calls = {"n": 0}

    def limited(req):
        calls["n"] += 1
        raise urllib.error.HTTPError(
            req.full_url, 403, "rate limit exceeded",
            {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"}, None)

    fake_opener(default=limited)
    with pytest.raises(HttpStatusError) as caught:
        HttpClient(retries=3, sleep=lambda *_: None).get_json("https://api.github.com/x")
    message = str(caught.value)
    assert caught.value.status == 403
    assert "rate limit" in message and "2023-11-14T22:13:20Z" in message
    assert "token" in message
    assert calls["n"] == 1               # waiting up to an hour is the user's call


def test_an_absurd_rate_limit_reset_does_not_crash(fake_opener):
    def limited(req):
        raise urllib.error.HTTPError(
            req.full_url, 403, "rate limit exceeded",
            {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9" * 40}, None)

    fake_opener(default=limited)
    with pytest.raises(HttpStatusError, match="resets unknown"):
        HttpClient(retries=1, sleep=lambda *_: None).get_json("https://api.github.com/x")


def test_deterministic_404_is_not_retried(fake_opener):
    calls = {"n": 0}

    def gone(req):
        calls["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    fake_opener(default=gone)
    with pytest.raises(HttpStatusError) as caught:
        HttpClient(retries=4, sleep=lambda *_: None).read_bytes("https://x.example/m")
    assert caught.value.status == 404
    assert calls["n"] == 1


class _TrackedBody(io.BytesIO):
    """An HTTPError body that records whether anyone closed it."""


@pytest.mark.parametrize("status", [503, 404])
def test_an_http_error_response_is_closed_not_leaked(fake_opener, status):
    """An HTTPError owns the response socket. Retried or raised, it is closed -
    otherwise every 5xx retry leaks a connection until garbage collection, and
    Python 3.14 reports it as a ResourceWarning."""
    bodies = []

    def failing(req):
        body = _TrackedBody(b"error page")
        bodies.append(body)
        raise urllib.error.HTTPError(req.full_url, status, "x", {}, body)

    fake_opener(default=failing)
    with pytest.raises((HttpStatusError, NetworkError)):
        HttpClient(retries=2, sleep=lambda *_: None).read_bytes("https://x.example/m")
    assert bodies and all(b.closed for b in bodies)


@pytest.mark.parametrize("header", ["-1", "nan", "-inf", "inf", "1e999", "soon"])
def test_a_hostile_retry_after_becomes_a_sane_delay(fake_opener, header):
    """Retry-After is server input. A negative or NaN value reached time.sleep,
    which raises ValueError - escaping the retry loop as an internal error."""
    slept = []
    calls = {"n": 0}

    def limited(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 503, "busy",
                                         {"Retry-After": header}, None)
        return FakeResponse(b'{"ok":true}')

    fake_opener(default=limited)
    client = HttpClient(retries=3, sleep=slept.append)
    assert client.get_json("https://api.github.com/x") == {"ok": True}
    assert len(slept) == 1 and 0.0 <= slept[0] <= 300.0


def test_retry_after_is_honoured(fake_opener):
    slept = []
    calls = {"n": 0}

    def limited(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "rate limited",
                                         {"Retry-After": "7"}, None)
        return FakeResponse(b'{"ok":true}')

    fake_opener(default=limited)
    client = HttpClient(retries=3, sleep=slept.append)
    assert client.get_json("https://api.github.com/x") == {"ok": True}
    assert slept == [7.0]


def test_exhausted_retries_raise_a_typed_error(fake_opener):
    fake_opener(default=lambda r: (_ for _ in ()).throw(
        urllib.error.URLError("no route to host")))
    with pytest.raises(NetworkError):
        HttpClient(retries=2, sleep=lambda *_: None).read_bytes("https://x.example/m")


# ------------------------------------------- user agent (regression: G3 403/SHS 401)
def test_forum_hosts_get_a_browser_user_agent():
    """
    Gibberlings3 answered 403 and SHS 401 to the tool's own agent string. These
    are files a human can fetch by clicking; nothing else about the request
    changes.
    """
    from iemod_fetch.net import BROWSER_USER_AGENT
    client = HttpClient()
    for url in ("https://www.gibberlings3.net/mods/quests/cliffette/",
                "https://www.shsforums.net/files/file/984-x/",
                "https://downloads.weaselmods.net/download/x/"):
        assert client.headers_for(url)["User-Agent"] == BROWSER_USER_AGENT


def test_the_github_api_gets_the_honest_tool_agent():
    from iemod_fetch.net import USER_AGENT
    headers = HttpClient(token="ghp_x").headers_for("https://api.github.com/repos/o/r")
    assert headers["User-Agent"] == USER_AGENT
    assert headers["Authorization"] == "Bearer ghp_x"


def test_the_browser_agent_never_carries_the_credential():
    """The UA split must not widen where the token goes."""
    client = HttpClient(token="ghp_secret")
    for url in ("https://www.gibberlings3.net/x", "https://downloads.weaselmods.net/x"):
        assert "Authorization" not in client.headers_for(url)


def test_the_default_ceiling_admits_a_real_mod():
    """BGGO is 1.4 GB; the old 512 MiB default rejected six real downloads."""
    from iemod_fetch.net import DEFAULT_MAX_BYTES
    assert DEFAULT_MAX_BYTES >= 1_457_111_463


# ------------------------------------------------- same site (ADR-0043)
@pytest.mark.parametrize("page, link, same", [
    # two users' GitHub Pages are two sites: the hand-written rule took both
    # for github.io, so a link to another user's page escaped the offsite gate
    ("https://modder.github.io/mod/", "https://attacker.github.io/x.zip", False),
    ("https://a.gitlab.io/m/", "https://b.gitlab.io/x.zip", False),
    # not a public suffix (the list is the authority, not a guess): one site
    ("https://a.sourceforge.io/", "https://b.sourceforge.io/x.zip", True),
    ("https://modder.github.io/mod/", "https://modder.github.io/files/x.zip", True),
    # the ordinary mod hosts are unchanged
    ("https://www.gibberlings3.net/mods/", "https://gibberlings3.net/files/x.zip", True),
    ("https://www.weaselmods.net/p", "https://weaselmods.net/d.zip", True),
    ("https://forums.beamdog.com/t", "https://www.gibberlings3.net/x", False),
    ("https://shop.example.co.uk/", "https://www.example.co.uk/x", True),
    ("https://a.co.uk/", "https://b.co.uk/", False),
    # an address is its own site; so is a bare suffix
    ("http://127.0.0.1:8000/page", "http://127.0.0.1:8000/x.zip", True),
    ("http://127.0.0.1/page", "http://127.0.0.2/x.zip", False),
    ("http://[::1]:8000/page", "http://[::1]:8000/x.zip", True),
])
def test_same_site_follows_the_public_suffix_list(page, link, same):
    from iemod_fetch.net import same_site
    assert same_site(page, link) is same


# ------------------------------- GitHub's secondary rate limit (GUI-AUDIT item 45)
def _limited_once(fake_opener, url_status_headers, body=b""):
    """The first request answers as given, the second with JSON."""
    calls = {"n": 0}
    status, headers = url_status_headers

    def answer(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, status, "x", headers, io.BytesIO(body))
        return FakeResponse(b'{"ok":true}')

    fake_opener(default=answer)
    return calls


def test_a_secondary_limit_with_retry_after_is_waited_out(fake_opener):
    """GitHub's docs: a 403 or 429 for a secondary limit, wait retry-after
    seconds and retry. A 403 used to stop the run at once."""
    _limited_once(fake_opener, (403, {"Retry-After": "30", "X-RateLimit-Remaining": "4000"}))
    slept = []
    assert HttpClient(sleep=slept.append).get_json("https://api.github.com/x") == {"ok": True}
    assert slept == [30.0]


def test_a_secondary_limit_without_retry_after_waits_a_minute(fake_opener):
    """GitHub's docs: with neither header, wait at least one minute."""
    _limited_once(fake_opener, (403, {}), b'{"message": "You have exceeded a secondary rate limit."}')
    slept = []
    assert HttpClient(sleep=slept.append).get_json("https://api.github.com/x") == {"ok": True}
    assert slept == [60.0]


@pytest.mark.parametrize("url,headers,body", [
    ("https://api.github.com/x", {}, b'{"message": "Resource not accessible"}'),   # a refusal
    ("https://api.github.com/x", {"X-RateLimit-Remaining": "0", "Retry-After": "30"}, b""),
    ("https://forums.example.org/x", {"Retry-After": "30"}, b"secondary rate limit"),
])
def test_other_403s_still_stop_at_once(fake_opener, url, headers, body):
    calls = _limited_once(fake_opener, (403, headers), body)
    with pytest.raises(HttpStatusError) as caught:
        HttpClient(sleep=lambda *_: None).get_json(url)
    assert caught.value.status == 403 and calls["n"] == 1


def test_a_retry_after_date_is_waited_until(fake_opener):
    """RFC 9110 lets Retry-After be an HTTP date; it was ignored for backoff."""
    when = email.utils.formatdate(time.time() + 20, usegmt=True)
    _limited_once(fake_opener, (503, {"Retry-After": when}))
    slept = []
    assert HttpClient(sleep=slept.append).get_json("https://x.example/j") == {"ok": True}
    assert len(slept) == 1 and 15.0 <= slept[0] <= 21.0


# ------------------------------------ the waits and Cancel (review of #61)
def test_cancel_set_before_a_retry_stops_at_once(fake_opener, tmp_path):
    import threading
    from iemod_fetch.errors import Cancelled
    _limited_once(fake_opener, (403, {"Retry-After": "30"}))
    ev = threading.Event()
    ev.set()
    slept = []
    with pytest.raises(Cancelled):
        HttpClient(sleep=slept.append).download(
            "https://github.com/o/r/releases/download/v1/a.zip", str(tmp_path / "a.zip"),
            cancel=ev)
    assert slept == []


def test_cancel_ends_a_wait_for_a_rate_limit(fake_opener):
    """A secondary limit's wait was a time.sleep the GUI's Cancel could not end:
    'Stopping...' for minutes, and a quit that outlived Qt's thread wait."""
    import threading
    from iemod_fetch.errors import Cancelled
    calls = {"n": 0}

    def limited(req):
        calls["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 403, "x", {"Retry-After": "60"},
                                     io.BytesIO())
    fake_opener(default=limited)
    client = HttpClient()                  # the real time.sleep
    client.cancel = threading.Event()
    threading.Timer(0.2, client.cancel.set).start()
    started = time.monotonic()
    with pytest.raises(Cancelled):
        client.get_json("https://api.github.com/x")
    assert time.monotonic() - started < 5 and calls["n"] == 1


def test_the_runner_hands_its_cancel_to_the_client(tmp_path):
    from iemod_fetch.runner import Options, Runner
    client = HttpClient()
    runner = Runner(client, Options(target_dir=str(tmp_path / "Mods"), workers=1))
    assert client.cancel is runner.cancel


def test_a_secondary_limit_asking_more_than_five_minutes_stops(fake_opener):
    """Retrying sooner than GitHub asks prolongs the limit (its docs warn of a ban)."""
    calls = _limited_once(fake_opener, (403, {"Retry-After": "600"}))
    with pytest.raises(HttpStatusError, match="600 s"):
        HttpClient(sleep=lambda *_: None).get_json("https://api.github.com/x")
    assert calls["n"] == 1


def test_a_429_with_the_quota_spent_is_not_retried(fake_opener):
    """It resets up to an hour away; retrying after 2 and 4 s only spent requests."""
    calls = _limited_once(fake_opener, (429, {"X-RateLimit-Remaining": "0",
                                              "X-RateLimit-Reset": "1900000000"}))
    with pytest.raises(HttpStatusError, match="rate limit exhausted"):
        HttpClient(sleep=lambda *_: None).get_json("https://api.github.com/x")
    assert calls["n"] == 1


def test_a_secondary_limit_that_outlasts_the_retries(fake_opener):
    def limited(req):
        raise urllib.error.HTTPError(req.full_url, 403, "x", {},
                                     io.BytesIO(b"You have exceeded a secondary rate limit"))
    fake_opener(default=limited)
    slept = []
    with pytest.raises(NetworkError):
        HttpClient(sleep=slept.append).get_json("https://api.github.com/x")
    assert slept == [60.0, 120.0]
