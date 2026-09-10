"""Transport policy - the fix for legacy defects L5, L6, L8."""
import io
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
