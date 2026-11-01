"""
Progress events and cancellation (ADR-0030, milestone M1).

A UI cannot read a progress bar out of printed text, and must be able to stop a
run without killing the process. The runner reports what it does as events -
the same dicts `--events` writes one per line - and stops at the next chunk
when asked to.
"""
import hashlib
import json
import threading

from iemod_fetch.errors import Cancelled
from iemod_fetch.manifest import parse_manifest
from iemod_fetch.net import DownloadResult
from iemod_fetch.archives import Kind
from iemod_fetch.plan import build_plan
from iemod_fetch.report import Status
from iemod_fetch.runner import Options, Runner
from iemod_fetch.weidu import parse_weidu_log

from test_cli_end_to_end import zip_bytes

URL = "https://github.com/o/eefixpack/releases/download/v2/eefixpack.zip"


class Client:
    """One release, one archive; reports progress and honours a cancel."""

    def __init__(self, cancel_midway=None):
        self.data = zip_bytes("eefixpack", "eefixpack/SETUP-EEFIXPACK.TP2")
        self.cancel_midway = cancel_midway
        self.downloaded = []

    def get_json(self, url):
        return {"tag_name": "v2", "assets": [{"name": "eefixpack.zip",
                                              "browser_download_url": URL}]}

    def open(self, url):
        raise AssertionError(url)

    def download(self, url, dest_path, expected_sha256=None, require_archive=True,
                 progress=None, cancel=None):
        half = len(self.data) // 2
        if progress:
            progress(half, len(self.data))
        if self.cancel_midway is not None:
            self.cancel_midway.set()
        if cancel is not None and cancel.is_set():
            raise Cancelled(f"{url}: cancelled")
        if progress:
            progress(len(self.data), len(self.data))
        with open(dest_path, "wb") as fh:
            fh.write(self.data)
        self.downloaded.append(url)
        return DownloadResult(dest_path, hashlib.sha256(self.data).hexdigest(),
                              len(self.data), Kind.ZIP, url)


def _plan():
    manifest = parse_manifest({"mods": [{"name": "EE Fixpack", "tp2": "eefixpack",
                                         "github": "o/eefixpack"}]})
    log = parse_weidu_log("~eefixpack\\SETUP-EEFIXPACK.TP2~ #0 #0 // Core\n")
    return build_plan(log, manifest)


def _runner(tmp_path, client, events=None, cancel=None):
    return Runner(client, Options(target_dir=str(tmp_path / "Mods"), workers=1),
                  on_event=events.append if events is not None else None,
                  cancel=cancel)


def test_a_run_reports_what_it_does_as_events(tmp_path):
    events = []
    report = _runner(tmp_path, Client(), events).run(_plan())
    assert [r.status for r in report.records] == [Status.OK]
    kinds = [e["event"] for e in events]
    assert kinds[0] == "run_started" and kinds[-1] == "run_finished"
    assert kinds.index("mod_started") < kinds.index("download_progress") \
        < kinds.index("mod_finished")
    progress = [e for e in events if e["event"] == "download_progress"]
    assert progress[-1]["bytes"] == progress[-1]["total"]
    assert all(e["schema_version"] == 1 for e in events)
    finished = [e for e in events if e["event"] == "mod_finished"][0]
    assert (finished["folder"], finished["status"]) == ("eefixpack", "ok")
    json.dumps(events)                                   # every event is JSON


def test_a_run_cancelled_before_it_starts_downloads_nothing(tmp_path):
    cancel = threading.Event()
    cancel.set()
    client = Client()
    report = _runner(tmp_path, client, cancel=cancel).run(_plan())
    assert client.downloaded == []
    assert [r.status for r in report.records] == [Status.CANCELLED]
    assert report.cancelled and report.exit_code() == 130


def test_a_download_cancelled_midway_is_recorded_as_cancelled(tmp_path):
    cancel = threading.Event()
    events = []
    report = _runner(tmp_path, Client(cancel_midway=cancel), events, cancel).run(_plan())
    assert [r.status for r in report.records] == [Status.CANCELLED]
    assert not (tmp_path / "Mods" / "eefixpack").exists()
    assert events[-1]["event"] == "run_finished" and events[-1]["cancelled"] is True


def test_every_event_matches_the_published_schema(tmp_path):
    import os

    import pytest
    jsonschema = pytest.importorskip("jsonschema")
    events = []
    _runner(tmp_path, Client(), events).run(_plan())
    path = os.path.join(os.path.dirname(__file__), os.pardir, "schemas",
                        "events-v1.schema.json")
    with open(path, encoding="utf-8") as fh:
        schema = json.load(fh)
    for event in events:
        jsonschema.validate(event, schema)
