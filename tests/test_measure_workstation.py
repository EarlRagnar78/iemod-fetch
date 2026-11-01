"""tools/measure_workstation.py: the item-57 measurement from a player's computer.

The steps are faked (no network); what is tested is that the script reads the
paths given where they were given, and never ends "done" with nothing measured.
"""
import json
import os
import subprocess

import pytest

from tools import download_measure, measure_workstation


class Steps:
    """Stands in for subprocess.run: each step writes what the real one would."""

    def __init__(self, dry=True):
        self.dry, self.calls = dry, []

    def __call__(self, argv, cwd=None, stdout=None, stderr=None, env=None, check=False,
                 capture_output=False, text=False):
        self.calls.append((list(argv), env))
        report = argv[argv.index("--json-report") + 1] if "--json-report" in argv else None
        if report and (self.dry or "--dry-run" not in argv):
            with open(report, "w", encoding="utf-8") as fh:
                json.dump({"records": [{"folder": "ub", "status": "planned",
                                        "origin": "release-asset", "detail": ""}],
                           "unresolved": []}, fh)
        if capture_output:                  # download_measure.py
            out, err = _measure(argv[2:])
            return subprocess.CompletedProcess(argv, 0, out, err)
        return subprocess.CompletedProcess(argv, 1 if report else 0)


def _measure(args):
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        download_measure.main(args)
    return buf.getvalue(), ""


@pytest.fixture
def steps(monkeypatch):
    fake = Steps()
    monkeypatch.setattr(measure_workstation.subprocess, "run", fake)
    return fake


def test_a_relative_log_is_read_from_where_it_was_given(tmp_path, monkeypatch, steps):
    """Review of #60: every step runs in the repository, so `--log WeiDU.log`
    named the repository's file, or none, silently."""
    (tmp_path / "WeiDU.log").write_text("~ub\\setup-ub.tp2~ #0 #0 // UB\n")
    monkeypatch.chdir(tmp_path)

    assert measure_workstation.main(["--log", "WeiDU.log", "--out", "m"]) == 0

    logs = {argv[argv.index("-w") + 1] for argv, _ in steps.calls if "-w" in argv}
    assert logs == {str(tmp_path / "WeiDU.log")}
    assert (tmp_path / "m" / "summary.md").read_text().strip()


def test_a_log_that_is_not_there_stops_before_anything_runs(tmp_path, monkeypatch, steps):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        measure_workstation.main(["--log", "nope.log", "--out", "m"])
    assert steps.calls == []


def test_a_dry_run_that_left_no_report_fails_the_run(tmp_path, monkeypatch, capsys):
    """Review of #60: no dry-catalogue.json ended in an empty summary and exit 0."""
    fake = Steps(dry=False)
    monkeypatch.setattr(measure_workstation.subprocess, "run", fake)
    monkeypatch.chdir(tmp_path)

    assert measure_workstation.main(["--out", "m"]) == 1

    assert "wrote no dry-catalogue.json" in capsys.readouterr().err
    assert not (tmp_path / "m" / "summary.md").exists()


def test_an_earlier_runs_folder_is_refused(tmp_path, monkeypatch, steps):
    """Review of #60: the same day's folder kept a stale real.json."""
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "real.json").write_text("{}")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        measure_workstation.main(["--out", "m"])
    assert steps.calls == []


def test_the_players_own_data_cache_is_left_alone(tmp_path, monkeypatch, steps):
    """Review of #60: the community data step refreshed ~/.cache/iemod-fetch."""
    monkeypatch.chdir(tmp_path)
    assert measure_workstation.main(["--out", "m"]) == 0
    assert {env["IEMOD_DATA_DIR"] for _, env in steps.calls} == {
        os.path.join(str(tmp_path), "m", "data")}
