"""
RED PHASE - characterization tests for legacy/fetch_mods_original.py.

These tests PASS, and that is the problem: each one asserts the *defective*
behaviour of the original script, executing the real code to prove the defect
is real rather than a reading of the source. They are the executable audit.

Every test is confined to tmp_path. No test touches the network.
"""
import gzip
import io
import tarfile
import urllib.error
import urllib.request

import pytest

from conftest import FakeResponse, json_response


@pytest.fixture
def legacy(monkeypatch):
    from legacy import fetch_mods_original as mod
    monkeypatch.setattr(mod, "RUNTIME_GH_TOKEN", None)
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)  # keep retries instant
    return mod


# ---------------------------------------------------------------- verification
def test_L1_verification_accepts_a_completely_unrelated_tp2(legacy, tmp_path):
    """find_tp2_in_dir ends in `return True`, so ANY .tp2 satisfies ANY mod."""
    d = tmp_path / "eefixpack"
    d.mkdir()
    (d / "some-other-mod.tp2").write_text("BACKUP ~x~")

    assert legacy.find_tp2_in_dir(str(d), "eefixpack") is True  # DEFECT


def test_L2_process_mod_reports_SKIPPED_for_a_wrong_directory(legacy, tmp_path):
    target = tmp_path / "Mods"
    (target / "EET").mkdir(parents=True)
    (target / "EET" / "unrelated.tp2").write_text("x")
    legacy.TARGET_DIR = str(target)

    name, status, _ = legacy.process_mod({"name": "EET", "tp2": "EET",
                                          "url": "https://example.invalid/"})
    assert status == "SKIPPED"  # DEFECT: never downloads, never verifies


def test_L3_scan_archive_for_strict_tp2_is_not_strict(legacy, tmp_path):
    """A 'bg1ub' archive is claimed as a match for the mod key 'ub'."""
    import zipfile
    arc = tmp_path / "a.zip"
    with zipfile.ZipFile(arc, "w") as z:
        z.writestr("bg1ub/bg1ub.tp2", "BACKUP ~x~")

    assert legacy.scan_archive_for_strict_tp2(str(arc), "ub") is True  # DEFECT


# ------------------------------------------------------------- path traversal
def test_L4_manifest_tp2_key_escapes_target_dir_and_destroys_user_data(
        legacy, tmp_path, fake_opener):
    """
    A manifest entry whose `tp2` contains `..` makes the script delete a
    directory OUTSIDE the target dir on the error path.
    """
    target = tmp_path / "Mods"
    target.mkdir()
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "precious.txt").write_text("irreplaceable user data")
    legacy.TARGET_DIR = str(target)

    def boom(req):
        raise urllib.error.URLError("network down")

    fake_opener(routes={
        "api.github.com/repos": lambda r: json_response(
            {"assets": [{"name": "m.zip",
                         "browser_download_url": "https://example.invalid/m.zip"}]}),
        "example.invalid/m.zip": boom,
    })

    assert (victim / "precious.txt").exists()
    legacy.process_mod({"name": "evil", "tp2": "../victim",
                        "github": "someone/somerepo"})

    assert not victim.exists()  # DEFECT: arbitrary directory deletion


# ---------------------------------------------------------------- token leak
def test_L5_github_token_is_sent_to_third_party_mod_hosts(legacy, fake_opener):
    """
    get_headers() attaches the OAuth bearer to EVERY request. With the real
    manifest that means the token is sent to 9 non-GitHub hosts.
    """
    legacy.RUNTIME_GH_TOKEN = "ghp_SUPERSECRET"
    opener = fake_opener(default=lambda r: FakeResponse(
        b"<html><a href='/f.zip'>download</a></html>",
        headers={"Content-Type": "text/html"}))

    legacy.resolve_html_download_link("https://downloads.weaselmods.net/download/x/")

    assert opener.header_sent_to("weaselmods", "Authorization") == "Bearer ghp_SUPERSECRET"


def test_L6_token_survives_redirect_to_a_lookalike_host(legacy):
    """`"github.com" not in netloc` is a substring test, not a host test."""
    handler = legacy.AuthRedirectHandler()
    handler.parent = None
    req = urllib.request.Request("https://api.github.com/x",
                                 headers={"Authorization": "Bearer SECRET"})

    new = handler.redirect_request(req, None, 302, "Found", {},
                                   "https://github.com.attacker.example/steal")

    assert new.get_header("Authorization") == "Bearer SECRET"  # DEFECT


# ------------------------------------------------------- supply chain / trust
def test_L7_unknown_repo_falls_back_to_arbitrary_github_search_result(
        legacy, fake_opener):
    """
    When resolution fails the script installs whatever repo GitHub's search
    ranks first - a name anybody can register.
    """
    def notfound(req):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", None, None)

    fake_opener(routes={
        "api.github.com/search/repositories": lambda r: json_response(
            {"items": [{"full_name": "attacker/typosquat-mod"}]}),
    }, default=notfound)

    url = legacy.resolve_github_asset("Argent77/A7-Missing", tp2="eefixpack")

    assert "attacker/typosquat-mod" in url  # DEFECT


def test_L8_html_error_page_is_accepted_as_a_valid_archive(legacy, tmp_path,
                                                           fake_opener):
    """The only integrity check is `size < 500`, so a 2 KB error page passes."""
    body = b"<html><body>403 Forbidden - please solve this captcha</body></html>"
    body += b" " * 3000
    fake_opener(default=lambda r: FakeResponse(body))

    dest = tmp_path / "mod_temp.bin"
    assert legacy.download_with_retry("https://example.invalid/m.zip", str(dest)) is True
    assert dest.read_bytes().startswith(b"<html")  # DEFECT: HTML stored as an archive


# ------------------------------------------------------------ archive safety
def test_L9_tar_extraction_escapes_the_destination_directory(legacy, tmp_path):
    """extract_archive calls tarfile.extractall() with no member validation."""
    outside = tmp_path / "outside.txt"
    arc = tmp_path / "evil.tar.gz"

    payload = io.BytesIO(b"pwned")
    with tarfile.open(arc, "w:gz") as tf:
        info = tarfile.TarInfo("../outside.txt")
        info.size = len(payload.getvalue())
        tf.addfile(info, payload)

    dest = tmp_path / "extract_here"
    dest.mkdir()
    assert legacy.extract_archive(str(arc), str(dest)) is True
    assert outside.read_bytes() == b"pwned"  # DEFECT: zip-slip / tar traversal


def test_L10_plain_gzip_is_misidentified_as_a_tar_archive(legacy, tmp_path):
    p = tmp_path / "blob.gz"
    p.write_bytes(gzip.compress(b"not a tarball"))
    assert legacy.detect_archive_type(str(p)) == "tar"  # DEFECT


# ------------------------------------------------------------- URL handling
def test_L11_trailing_slash_is_appended_to_query_strings(legacy):
    """`https://host/f/?do=download&csrf=a` becomes `...csrf=a/` - a broken URL."""
    url = "https://www.gibberlings3.net/files/file/1-x/?do=download&csrf=abc"
    assert legacy.resolve_html_download_link(url).endswith("csrf=abc/")  # DEFECT


def test_L12_first_matching_link_on_the_page_wins_regardless_of_host(
        legacy, fake_opener):
    """An advert or tracker link is downloaded in place of the mod."""
    html = (b"<html>"
            b"<a href='https://ads.example.net/sponsored-download.exe'>download</a>"
            b"<a href='https://downloads.weaselmods.net/real-mod.zip'>the mod</a>"
            b"</html>")
    fake_opener(default=lambda r: FakeResponse(html, headers={"Content-Type": "text/html"}))

    link = legacy.resolve_html_download_link("https://downloads.weaselmods.net/p/")
    assert link == "https://ads.example.net/sponsored-download.exe"  # DEFECT


# --------------------------------------------------------------- exit status
def test_L13_main_exits_zero_even_when_every_mod_fails(legacy, tmp_path,
                                                       monkeypatch, fake_opener):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mod_downloads.json").write_text(
        '{"mods":[{"name":"X","tp2":"xmod","url":"https://example.invalid/x"}]}')
    legacy.TARGET_DIR = str(tmp_path / "Mods")
    monkeypatch.setattr(legacy, "get_github_token", lambda: "")
    fake_opener(default=lambda r: (_ for _ in ()).throw(
        urllib.error.URLError("no network")))

    assert legacy.main() is None  # DEFECT: CI cannot detect the failure
