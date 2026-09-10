"""End-to-end runs against a stubbed transport - no network, no real GitHub."""
import io
import json
import zipfile

import pytest

from iemod_fetch import cli
from iemod_fetch.errors import NetworkError
from iemod_fetch.net import DownloadResult
from iemod_fetch.archives import Kind


def zip_bytes(folder, tp2=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(tp2 or f"{folder}/{folder}.tp2", "BACKUP ~x~")
        zf.writestr(f"{folder}/readme.txt", "hello")
    return buf.getvalue()


class StubClient:
    """Serves canned releases and archives; records what was asked for."""

    def __init__(self, releases, blobs, **_kw):
        self.releases, self.blobs = releases, blobs
        self.downloaded = []

    def get_json(self, url):
        for repo, payload in self.releases.items():
            if f"/repos/{repo}/" in url:
                return payload
        raise NetworkError(f"404 {url}")

    def download(self, url, dest_path, expected_sha256=None, require_archive=True):
        import hashlib
        if url not in self.blobs:
            raise NetworkError(f"404 {url}")
        data = self.blobs[url]
        with open(dest_path, "wb") as fh:
            fh.write(data)
        self.downloaded.append(url)
        return DownloadResult(dest_path, hashlib.sha256(data).hexdigest(),
                              len(data), Kind.ZIP, url)

    def open(self, url):
        raise NetworkError(f"no landing pages in this stub: {url}")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    (tmp_path / "WeiDU.log").write_text(
        "// Log of Currently Installed WeiDU Mods\n"
        "~DlcMerger\\DlcMerger.tp2~ #0 #3 // Merge DLC\n"
        "~eefixpack\\SETUP-EEFIXPACK.TP2~ #0 #0 // Core Fixes\n")
    (tmp_path / "mod_downloads.json").write_text(json.dumps({"mods": [
        {"name": "DLC Merger", "tp2": "DlcMerger", "github": "Argent77/A7-DlcMerger",
         "url": "https://github.com/Argent77/A7-DlcMerger/releases"},
        {"name": "EE Fixpack", "tp2": "eefixpack", "github": "o/eefixpack",
         "url": "https://github.com/o/eefixpack/releases"},
    ]}))

    url_a = "https://github.com/o/r/releases/download/v1/DlcMerger.iemod"
    url_b = "https://github.com/o/r/releases/download/v2/eefixpack.zip"
    stub = StubClient(
        releases={
            "Argent77/A7-DlcMerger": {"tag_name": "v1", "assets": [
                {"name": "DlcMerger.iemod", "browser_download_url": url_a}]},
            "o/eefixpack": {"tag_name": "v2", "assets": [
                {"name": "eefixpack.zip", "browser_download_url": url_b}]}},
        blobs={url_a: zip_bytes("DlcMerger"),
               url_b: zip_bytes("eefixpack", "eefixpack/SETUP-EEFIXPACK.TP2")})

    monkeypatch.setattr(cli, "HttpClient", lambda **kw: stub)
    monkeypatch.setattr(cli, "resolve_credential",
                        lambda **kw: type("C", (), {"token": None, "describe":
                                                    lambda self: "anonymous"})())
    monkeypatch.chdir(tmp_path)
    return tmp_path, stub


def run(args, tmp_path):
    out = io.StringIO()
    code = cli.main(args, stream=out)
    return code, out.getvalue()


def test_full_run_installs_and_verifies_both_mods(workspace):
    tmp_path, stub = workspace
    code, out = run(["-w", "WeiDU.log", "-m", "mod_downloads.json",
                     "-t", "Mods", "--json-report", "report.json"], tmp_path)

    assert code == 0, out
    assert (tmp_path / "Mods" / "DlcMerger" / "DlcMerger.tp2").exists()
    assert (tmp_path / "Mods" / "eefixpack" / "SETUP-EEFIXPACK.TP2").exists()
    assert len(stub.downloaded) == 2

    report = json.loads((tmp_path / "report.json").read_text())
    assert report["counts"]["ok"] == 2
    assert all(r["sha256"] for r in report["records"])


def test_a_second_run_is_idempotent_and_downloads_nothing(workspace):
    tmp_path, stub = workspace
    run(["-w", "WeiDU.log", "-t", "Mods"], tmp_path)
    stub.downloaded.clear()
    code, out = run(["-w", "WeiDU.log", "-t", "Mods"], tmp_path)
    assert code == 0
    assert stub.downloaded == []
    assert "already installed and verified" in out


def test_dry_run_writes_nothing(workspace):
    tmp_path, stub = workspace
    code, out = run(["-w", "WeiDU.log", "-t", "Mods", "--dry-run"], tmp_path)
    assert code == 0
    assert stub.downloaded == []
    assert not (tmp_path / "Mods" / "DlcMerger").exists()
    assert "would download" in out


def test_unresolved_mods_make_the_run_fail_for_ci(workspace):
    tmp_path, stub = workspace
    (tmp_path / "WeiDU.log").write_text(
        "~DlcMerger\\DlcMerger.tp2~ #0 #0 // Merge DLC\n"
        "~HPS_PORTRAITS_PROJECT\\HPS_PORTRAITS_PROJECT.tp2~ #0 #0 // Portraits\n")
    code, out = run(["-w", "WeiDU.log", "-t", "Mods"], tmp_path)
    assert code == 1                                   # legacy always exited 0
    assert "MANUAL ACTION REQUIRED" in out
    assert "HPS_PORTRAITS_PROJECT" in out


def test_allow_manual_lets_a_partial_run_succeed(workspace):
    tmp_path, stub = workspace
    (tmp_path / "WeiDU.log").write_text(
        "~DlcMerger\\DlcMerger.tp2~ #0 #0 // Merge DLC\n"
        "~HPS_PORTRAITS_PROJECT\\HPS.tp2~ #0 #0 // Portraits\n")
    code, _ = run(["-w", "WeiDU.log", "-t", "Mods", "--allow-manual"], tmp_path)
    assert code == 0


def test_a_wrong_archive_fails_the_mod_without_touching_the_target(workspace):
    tmp_path, stub = workspace
    url = "https://github.com/o/r/releases/download/v1/DlcMerger.iemod"
    stub.blobs[url] = zip_bytes("SomethingElse")       # server served the wrong mod
    code, out = run(["-w", "WeiDU.log", "-t", "Mods"], tmp_path)
    assert code == 1
    assert not (tmp_path / "Mods" / "DlcMerger").exists()
    assert "none of them is 'DlcMerger.tp2'" in out


def test_running_without_a_weidu_log_is_a_configuration_error(workspace):
    tmp_path, _ = workspace
    code, _ = run(["-m", "mod_downloads.json", "-t", "Mods"], tmp_path)
    assert code == 2


def test_existing_directory_is_protected_until_force(workspace):
    tmp_path, stub = workspace
    dest = tmp_path / "Mods" / "DlcMerger"
    dest.mkdir(parents=True)
    (dest / "hand-edited.txt").write_text("mine")

    code, out = run(["-w", "WeiDU.log", "-t", "Mods"], tmp_path)
    assert code == 1 and "--force" in out
    assert (dest / "hand-edited.txt").read_text() == "mine"

    code, out = run(["-w", "WeiDU.log", "-t", "Mods", "--force"], tmp_path)
    assert code == 0
    backups = list((tmp_path / "Mods" / ".backup").iterdir())
    assert any((b / "hand-edited.txt").exists() for b in backups)


def test_emit_pinned_manifest_produces_a_reusable_lockfile(workspace):
    tmp_path, stub = workspace
    code, out = run(["-w", "WeiDU.log", "-t", "Mods",
                     "--emit-pinned-manifest", "pinned.json"], tmp_path)
    assert code == 0

    pinned = json.loads((tmp_path / "pinned.json").read_text())
    assert pinned["pinned_entries"] == 2
    by_key = {m["tp2"]: m for m in pinned["mods"]}
    assert by_key["DlcMerger"]["release_tag"] == "v1"
    assert by_key["DlcMerger"]["asset"] == "DlcMerger.iemod"
    assert len(by_key["DlcMerger"]["sha256"]) == 64

    # and the lockfile is itself a usable manifest
    code, _ = run(["-w", "WeiDU.log", "-m", "pinned.json", "-t", "Mods2"], tmp_path)
    assert code == 0
    assert (tmp_path / "Mods2" / "DlcMerger" / "DlcMerger.tp2").exists()


def test_a_pinned_digest_that_no_longer_matches_fails_the_run(workspace):
    """The point of pinning: a changed artefact is refused, not installed."""
    tmp_path, stub = workspace
    run(["-w", "WeiDU.log", "-t", "Mods", "--emit-pinned-manifest", "pinned.json"],
        tmp_path)

    url = "https://github.com/o/r/releases/download/v1/DlcMerger.iemod"
    stub.blobs[url] = zip_bytes("DlcMerger") + b"tampered"

    class Strict(type(stub)):
        def download(self, url, dest_path, expected_sha256=None, require_archive=True):
            import hashlib
            from iemod_fetch.errors import ChecksumMismatch
            data = self.blobs[url]
            actual = hashlib.sha256(data).hexdigest()
            if expected_sha256 and actual != expected_sha256:
                raise ChecksumMismatch(url, expected_sha256, actual)
            return super().download(url, dest_path, expected_sha256, require_archive)

    stub.__class__ = Strict
    code, out = run(["-w", "WeiDU.log", "-m", "pinned.json", "-t", "Mods3"], tmp_path)
    assert code == 1
    assert "sha256 expected" in out
    assert not (tmp_path / "Mods3" / "DlcMerger").exists()
