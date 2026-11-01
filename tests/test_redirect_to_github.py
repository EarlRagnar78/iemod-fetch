"""
A download link that ends on a GitHub repository's page (GUI-AUDIT M7 item 55).

Measured on 2026-10-23: baldurs-gate.de's XenForo resource `/download` answers
301 to `github.com/<owner>/<repo>/releases` - an HTML page - for AC_QUEST,
bgqe, c#solaufein, JA#BGT_AdvPack and c#brage. The repository is then the
author's own, named by the redirect, not guessed: its release is taken, once,
and held to the same .tp2 check.
"""
import json

from conftest import FakeResponse
from iemod_fetch.errors import NotAnArchive
from test_discovery_end_to_end import WEIDU, DiscoveryStub, make, run, zip_bytes

PAGE = "https://baldurs-gate.de/index.php?resources/endless-bg1.4/"
DOWNLOAD = "https://baldurs-gate.de/index.php?resources/endless-bg1.4/download"
RELEASES = "https://github.com/Gitjas/EndlessBG1/releases"
ASSET = "https://github.com/Gitjas/EndlessBG1/releases/download/v3/EndlessBG1-v3.zip"


class RedirectingStub(DiscoveryStub):
    """baldurs-gate.de as measured: the download link lands on GitHub's page."""

    def open(self, url):
        html = {"Content-Type": "text/html; charset=utf-8"}
        if url == DOWNLOAD:           # opened as a landing page: the redirect shows
            return FakeResponse(b"<html>releases</html>", headers=html, url=RELEASES)
        if url == PAGE:               # the resource page links its download
            return FakeResponse(f'<a href="{DOWNLOAD}">Download</a>'.encode(),
                                headers=html, url=PAGE)
        return super().open(url)

    def download(self, url, dest_path, expected_sha256=None, require_archive=True,
                 progress=None, cancel=None):
        if url == DOWNLOAD:
            self.downloaded.append(url)
            raise NotAnArchive(url, b"<!DOCTYPE html>", final_url=RELEASES)
        return super().download(url, dest_path, expected_sha256, require_archive,
                                progress, cancel)


def setup(tmp_path, monkeypatch, stub, url=DOWNLOAD):
    make(tmp_path, monkeypatch, stub, WEIDU,
         {"mods": [{"name": "Endless BG1", "tp2": "EndlessBG1", "url": url}]})


def report(tmp_path):
    return json.loads((tmp_path / "r.json").read_text())


ARGS = ["-w", "WeiDU.log", "-t", "Mods", "--no-discovery", "--json-report", "r.json"]


def release_stub(blob):
    return RedirectingStub(
        owners={},
        releases={"Gitjas/EndlessBG1": {"tag_name": "v3", "assets": [
            {"name": "EndlessBG1-v3.zip", "browser_download_url": ASSET}]}},
        blobs={ASSET: blob})


def test_a_manifest_link_that_leads_to_a_github_page_takes_its_release(
        tmp_path, monkeypatch):
    """The manifest names `/download` itself (JA#BGT_AdvPack, c#brage)."""
    stub = release_stub(zip_bytes("EndlessBG1"))
    setup(tmp_path, monkeypatch, stub)

    code, out = run(ARGS)

    assert code == 0, out
    assert (tmp_path / "Mods" / "EndlessBG1" / "EndlessBG1.tp2").exists()
    assert stub.downloaded == [ASSET]
    assert any("leads to Gitjas/EndlessBG1 on GitHub" in w
               for w in report(tmp_path)["warnings"])


def test_a_download_that_lands_on_a_github_page_takes_its_release(tmp_path, monkeypatch):
    """The resource page is the source and its `/download` link the candidate
    (AC_QUEST, bgqe, c#solaufein): the redirect shows when downloading."""
    stub = release_stub(zip_bytes("EndlessBG1"))
    setup(tmp_path, monkeypatch, stub, url=PAGE)

    code, out = run(ARGS)

    assert code == 0, out
    assert (tmp_path / "Mods" / "EndlessBG1" / "EndlessBG1.tp2").exists()
    assert stub.downloaded == [DOWNLOAD, ASSET]
    assert any("leads to Gitjas/EndlessBG1 on GitHub" in w
               for w in report(tmp_path)["warnings"])


def test_the_release_it_leads_to_still_passes_the_tp2_check(tmp_path, monkeypatch):
    stub = release_stub(zip_bytes("SomeOtherMod"))
    setup(tmp_path, monkeypatch, stub, url=PAGE)

    code, out = run(ARGS)

    assert code == 1
    assert not (tmp_path / "Mods" / "EndlessBG1").exists()


def test_a_github_page_whose_release_cannot_be_had_says_so(tmp_path, monkeypatch):
    stub = RedirectingStub(owners={}, releases={}, blobs={})
    setup(tmp_path, monkeypatch, stub, url=PAGE)

    code, out = run(ARGS)

    assert code == 1
    detail = report(tmp_path)["records"][0]["detail"]
    assert "did not return an archive" in detail and "Gitjas/EndlessBG1" in detail


def test_html_that_does_not_lead_to_github_fails_as_before(tmp_path, monkeypatch):
    class Plain(RedirectingStub):
        def download(self, url, dest_path, **kw):
            self.downloaded.append(url)
            raise NotAnArchive(url, b"<!DOCTYPE html>", final_url=url)

    stub = Plain(owners={}, releases={}, blobs={})
    setup(tmp_path, monkeypatch, stub, url=PAGE)

    code, out = run(ARGS)

    assert code == 1
    assert stub.downloaded == [DOWNLOAD]
    assert "did not return an archive" in report(tmp_path)["records"][0]["detail"]


# ------------------------------------------------------ review of #59
def test_a_pinned_manifest_link_is_never_handed_over(tmp_path, monkeypatch):
    """A sha256 means that file or nothing: the repository's latest release is
    not taken instead, on the landing path."""
    stub = release_stub(zip_bytes("EndlessBG1"))
    make(tmp_path, monkeypatch, stub, WEIDU, {"mods": [
        {"name": "Endless BG1", "tp2": "EndlessBG1", "url": DOWNLOAD, "sha256": "a" * 64}]})

    code, out = run(ARGS)

    assert code == 1
    assert stub.downloaded == []
    assert not (tmp_path / "Mods" / "EndlessBG1").exists()
    assert "pinned to a file" in report(tmp_path)["records"][0]["detail"]


def test_a_pinned_page_link_is_never_handed_over_when_downloaded(tmp_path, monkeypatch):
    """The same on the download path: the page's link lands on GitHub."""
    stub = release_stub(zip_bytes("EndlessBG1"))
    make(tmp_path, monkeypatch, stub, WEIDU, {"mods": [
        {"name": "Endless BG1", "tp2": "EndlessBG1", "url": PAGE, "sha256": "a" * 64}]})

    code, out = run(ARGS)

    assert code == 1
    assert stub.downloaded == [DOWNLOAD]               # never the release's asset
    assert not (tmp_path / "Mods" / "EndlessBG1").exists()


def test_a_release_that_cannot_be_had_keeps_the_not_an_archive_code(tmp_path, monkeypatch):
    """The report's error codes are a contract (ADR-0030)."""
    stub = RedirectingStub(owners={}, releases={}, blobs={})
    setup(tmp_path, monkeypatch, stub, url=PAGE)

    assert run(ARGS)[0] == 1
    assert report(tmp_path)["records"][0]["error_code"] == "not_an_archive"


def test_a_catalogue_link_that_leads_to_a_github_page_takes_its_release(
        tmp_path, monkeypatch):
    """The catalogue's own landing path follows the redirect too."""
    stub = release_stub(zip_bytes("EndlessBG1"))
    make(tmp_path, monkeypatch, stub, WEIDU,
         {"mods": [{"name": "Endless BG1", "tp2": "EndlessBG1"}]})   # no url, no github
    (tmp_path / "lcc.json").write_text(json.dumps({"mods": [
        {"tp2": "EndlessBG1", "name": "Endless BG1", "urls": [DOWNLOAD]}]}))

    code, out = run([*ARGS, "-c", "lcc.json"])

    assert code == 0, out
    assert (tmp_path / "Mods" / "EndlessBG1" / "EndlessBG1.tp2").exists()
    assert stub.downloaded == [ASSET]
