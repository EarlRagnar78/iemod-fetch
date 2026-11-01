"""tools/download_measure.py: the summary of a download-sources run (ADR-0039)."""
import json

import pytest

from tools import download_measure


def report(path, records, unresolved=()):
    path.write_text(json.dumps({"records": records, "unresolved": list(unresolved)}))
    return str(path)


def test_the_summary_counts_each_status_and_lists_the_misses(tmp_path, capsys):
    dry = report(tmp_path / "dry.json", [
        {"folder": "ub", "status": "planned", "origin": "release-asset", "detail": ""},
        {"folder": "eet", "status": "planned", "origin": "release-asset", "detail": ""},
        {"folder": "ghost", "status": "manual", "detail": "no manifest entry | none"}],
        unresolved=[{"folder": "x", "detail": "no entry"}])
    real = report(tmp_path / "real.json", [
        {"folder": "ub", "status": "ok", "origin": "release-asset", "detail": "installed"},
        {"folder": "eet", "status": "failed", "detail": "archive does not contain eet.tp2"},
        {"folder": "bggo", "status": "failed",
         "detail": "Content-Length 1457111463 exceeds 314572800 byte ceiling"}])
    assert download_measure.main([dry, "--real", real]) == 0
    out = capsys.readouterr().out
    assert "4 mods: 2 manual, 2 planned" in out
    assert "| release-asset | 2 |" in out
    assert "| ghost | manual | no manifest entry / none |" in out
    assert "| eet | failed | archive does not contain eet.tp2 |" in out
    assert "3 mods: 1 failed, 1 ok, 1 over the size cap" in out


def test_pick_names_planned_mods_in_a_stable_order(tmp_path, capsys):
    dry = report(tmp_path / "dry.json", [
        {"folder": f, "status": s, "detail": ""} for f, s in
        (("zz", "planned"), ("aa", "planned"), ("mm", "manual"), ("bb", "planned"))])
    download_measure.main([dry, "--pick", "2"])
    assert capsys.readouterr().out.split() == ["aa", "bb"]


def test_pick_all_names_every_planned_mod(tmp_path, capsys):
    dry = report(tmp_path / "dry.json", [
        {"folder": f, "status": s, "detail": ""} for f, s in
        (("zz", "planned"), ("aa", "planned"), ("mm", "manual"))])
    download_measure.main([dry, "--pick", "all"])
    assert capsys.readouterr().out.split() == ["aa", "zz"]


def test_the_real_run_says_what_the_player_was_told(tmp_path, capsys):
    """Items 55, 58, 59: a forum post's copy, a newer release, a GitHub redirect."""
    dry = report(tmp_path / "dry.json", [])
    real = tmp_path / "real.json"
    real.write_text(json.dumps({
        "records": [
            {"folder": "ascension", "status": "ok", "origin": "page-link", "detail": "",
             "advisories": [("installed from a forum post (https://forums.beamdog.com/"
                            "uploads/x.7z), which may be older ...")],
             "newer": {"version": "2.1.0", "installed": "v1.5 BETA",
                       "repo": "Gibberlings3/Ascension"}},
            {"folder": "AC_QUEST", "status": "ok", "origin": "release-asset",
             "detail": ""}],
        "unresolved": [],
        "warnings": [("AC_QUEST: https://baldurs-gate.de/... leads to "
                     "Gitjas/Ascalons_Questpack on GitHub; its release is used")]}))
    assert download_measure.main([dry, "--real", str(real)]) == 0
    out = capsys.readouterr().out
    assert "installed from a forum post: 1 (ascension)" in out
    assert "a newer GitHub release offered: 1" in out
    assert "ascension: v1.5 BETA -> 2.1.0 (Gibberlings3/Ascension)" in out
    assert "a link that led to a GitHub repository: 1" in out


def test_pick_is_a_number_or_all(tmp_path, capsys):
    """Review of #60: `--pick x` was a traceback; `--pick 0` picks none."""
    dry = report(tmp_path / "dry.json", [{"folder": "aa", "status": "planned",
                                          "detail": ""}])
    with pytest.raises(SystemExit):
        download_measure.main([dry, "--pick", "x"])
    download_measure.main([dry, "--pick", "0"])
    assert capsys.readouterr().out == ""              # not even an empty line
