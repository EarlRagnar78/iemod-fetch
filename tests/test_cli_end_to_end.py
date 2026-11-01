"""End-to-end runs against a stubbed transport - no network, no real GitHub."""
import io
import json
import zipfile

import pytest

from iemod_fetch import api, cli
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

    def download(self, url, dest_path, expected_sha256=None, require_archive=True,
                 progress=None, cancel=None):
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

    monkeypatch.setattr(api, "HttpClient", lambda **kw: stub)
    monkeypatch.setattr(api, "resolve_credential",
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
        def download(self, url, dest_path, expected_sha256=None, require_archive=True,
                 progress=None, cancel=None):
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


# selection.json (ADR-0030): a selection made without any WeiDU.log drives the
# same run, and a log converts to the selection a UI would save.
SELECTION = {"schema_version": 1, "installs": [{"game": "BG2EE", "components": [
    {"tp2": "DlcMerger/DlcMerger.tp2", "component": 3, "language": 0},
    {"tp2": "eefixpack/SETUP-EEFIXPACK.TP2", "component": 0, "language": 0}]}]}


def test_a_selection_without_any_weidu_log_fetches_the_same_mods(workspace):
    tmp_path, stub = workspace
    (tmp_path / "selection.json").write_text(json.dumps(SELECTION))
    code, out = run(["--selection", "selection.json", "-t", "Mods"], tmp_path)
    assert code == 0, out
    assert (tmp_path / "Mods" / "DlcMerger" / "DlcMerger.tp2").exists()
    assert (tmp_path / "Mods" / "eefixpack" / "SETUP-EEFIXPACK.TP2").exists()
    assert len(stub.downloaded) == 2


def test_a_weidu_log_is_converted_to_a_selection(workspace):
    tmp_path, stub = workspace
    code, out = run(["-w", "WeiDU.log:BG2EE", "--emit-selection", "sel.json",
                     "--check-only", "-t", "Mods"], tmp_path)
    assert code == 0, out
    written = json.loads((tmp_path / "sel.json").read_text())
    assert written["schema_version"] == 1
    assert [(c["tp2"], c["component"]) for c in written["installs"][0]["components"]] \
        == [("DlcMerger/DlcMerger.tp2", 3), ("eefixpack/SETUP-EEFIXPACK.TP2", 0)]
    assert stub.downloaded == []


def test_a_selection_and_a_weidu_log_together_are_refused(workspace):
    tmp_path, _stub = workspace
    (tmp_path / "selection.json").write_text(json.dumps(SELECTION))
    code, _out = run(["--selection", "selection.json", "-w", "WeiDU.log"], tmp_path)
    assert code == 2


def test_a_broken_selection_is_a_configuration_error(workspace):
    tmp_path, _stub = workspace
    (tmp_path / "selection.json").write_text('{"schema_version": 7}')
    code, _out = run(["--selection", "selection.json"], tmp_path)
    assert code == 2


# --list-mods: what a UI's selection screen shows, with no WeiDU.log at all.
def test_list_mods_needs_no_weidu_log_and_downloads_nothing(workspace):
    tmp_path, stub = workspace
    (tmp_path / "lcc.json").write_text(json.dumps([
        {"tp2": "eefixpack", "name": "EE Fixpack", "games": ["EET"], "safe": 2},
        {"tp2": "newmod", "name": "A New Mod", "games": ["BG2EE"]}]))
    code, out = run(["--list-mods", "mods.json", "-c", "lcc.json"], tmp_path)
    assert code == 0, out
    doc = json.loads((tmp_path / "mods.json").read_text())
    assert doc["schema_version"] == 1
    assert [m["key"] for m in doc["mods"]] == ["newmod", "dlcmerger", "eefixpack"]
    assert stub.downloaded == []


def test_list_mods_to_stdout_prints_only_the_json(workspace):
    tmp_path, _stub = workspace
    code, out = run(["--list-mods", "-"], tmp_path)
    assert code == 0
    assert json.loads(out)["mods"][0]["name"] == "DLC Merger"


def test_list_mods_works_without_a_manifest_when_a_catalogue_is_given(workspace):
    tmp_path, _stub = workspace
    (tmp_path / "lcc.json").write_text(json.dumps([{"tp2": "x", "name": "X"}]))
    code, out = run(["--list-mods", "-", "-m", "absent.json", "-c", "lcc.json"], tmp_path)
    assert code == 0, out
    assert [m["key"] for m in json.loads(out)["mods"]] == ["x"]


def test_the_run_report_names_its_schema_version(workspace):
    tmp_path, _stub = workspace
    code, out = run(["-w", "WeiDU.log", "-t", "Mods", "--json-report", "r.json"],
                    tmp_path)
    assert code == 0, out
    report = json.loads((tmp_path / "r.json").read_text())
    assert report["schema_version"] == 1
    jsonschema = pytest.importorskip("jsonschema")
    import os
    schema = os.path.join(os.path.dirname(__file__), os.pardir, "schemas",
                          "report-v1.schema.json")
    with open(schema, encoding="utf-8") as fh:
        jsonschema.validate(report, json.load(fh))


def test_events_are_written_one_json_object_per_line(workspace):
    tmp_path, _stub = workspace
    code, out = run(["-w", "WeiDU.log", "-t", "Mods", "--events", "events.jsonl"],
                    tmp_path)
    assert code == 0, out
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    events = [json.loads(line) for line in lines]
    assert events[0]["event"] == "run_started" and events[-1]["event"] == "run_finished"
    assert sum(e["event"] == "mod_finished" for e in events) == 2


def test_one_run_fetches_then_checks_what_it_just_staged(workspace):
    """
    The mods' own tp2 constraints are read from the staged folders. They used
    to be read before the downloads, so a fresh selection needed two runs: one
    to fetch, one to check. Now fetch comes first and the check sees the mods.
    """
    tmp_path, _stub = workspace
    code, out = run(["-w", "WeiDU.log", "-t", "Mods"], tmp_path)
    assert code == 0, out
    assert "own tp2s    : 2 mod(s)" in out
    assert "not staged" not in out
