"""
The wizard's conflicts panel without a window (M3 phase 2, ADR-0033): the
findings a selection has before anything is downloaded, and the decisions.json
the panel writes - which the command line must read as the same thing.

The acceptance test: for the same selection, api.selection_conflicts gives the
ids the run's --conflict-report gives, and a decision saved from it is applied
by --decisions, never reported stale.
"""
import json
import os

import pytest

from iemod_fetch import api
from iemod_fetch.conflicts import DESELECT
from iemod_fetch.errors import ConfigError
from iemod_fetch.weidu import parse_weidu_files

HERE = os.path.dirname(__file__)
MOCK = os.path.join(HERE, "data", "eetmock")
KRION = os.path.join(HERE, "data", "krion")
RULES = [os.path.join(MOCK, "rules")]


def chosen_of(log, game="EET"):
    parsed = parse_weidu_files([(log, game)])
    components = sorted((c for mod in parsed.mods.values() for c in mod.components),
                        key=lambda c: c.line)
    return [((c.path or f"{c.folder}/{c.tp2_file}").replace("\\", "/"), c.index)
            for c in components]


CHOSEN = chosen_of(os.path.join(MOCK, "WeiDU.log"))


def conflicts(folder, chosen=CHOSEN, **extra):
    extra.setdefault("order_catalogue", KRION)
    return api.selection_conflicts("EET", chosen, folder=str(folder), rules=RULES,
                                   target=os.path.join(MOCK, "Mods"),
                                   data_dir=str(folder / "no-cache"), **extra)


def cli_report(folder, decisions=False):
    path = api.save_selection(str(folder), "EET", CHOSEN)
    settings = api.Settings(
        selection=path, check_only=True, quiet=True,
        manifest=os.path.join(HERE, "data", "mod_downloads.json"),
        target=os.path.join(MOCK, "Mods"), rules=RULES, order_catalogue=KRION,
        plan_order=str(folder / "plan"), conflict_report=str(folder / "conflicts.json"),
        decisions=str(folder / api.DECISIONS_FILE) if decisions else None,
        no_update_data=True, no_default_data=True)
    outcome = api.run(settings)
    with open(folder / "conflicts.json", encoding="utf-8") as fh:
        return outcome, json.load(fh)["findings"]


def actionable(result):
    return [f for f in result["findings"] if not f["fixed_by_plan"]]


# ----------------------------------------------------- the acceptance test
def test_the_panel_sees_the_ids_the_command_line_reports(tmp_path):
    result = conflicts(tmp_path)
    assert result["planned"] and actionable(result)
    _outcome, findings = cli_report(tmp_path)
    assert {f["id"] for f in result["findings"]} == {f["id"] for f in findings}


def test_a_decision_saved_by_the_panel_is_applied_by_the_command_line(tmp_path):
    findings = actionable(conflicts(tmp_path))
    chosen = next(f for f in findings
                  if any(o["applicable"] and o["action"] == DESELECT for o in f["options"]))
    option = next(o for o in chosen["options"]
                  if o["applicable"] and o["action"] == DESELECT)
    accepted = next(f for f in findings if f["id"] != chosen["id"])
    api.save_decisions(str(tmp_path), {chosen["id"]: option["id"]},
                       {accepted["id"]: "tested, works for me"})
    outcome, report = cli_report(tmp_path, decisions=True)
    resolution = outcome.order_plan.resolution
    assert not resolution.stale_decisions
    assert [r.finding_id for r in resolution.removed if r.by == "decision"] == [chosen["id"]]
    assert [a.finding_id for a in resolution.accepted] == [accepted["id"]]
    # and the run's own conflict report says so - it could not when the
    # selection's log name differed from the plan's role
    by_id = {f["id"]: f for f in report}
    assert by_id[accepted["id"]]["suppressed"].endswith("tested, works for me")
    # the id keeps the plan's name for the install; the reader sees the file's
    assert {f["log"] for f in report} == {"WeiDU-EET.log"}


def test_the_panel_shows_each_decision_and_the_stale_ones(tmp_path):
    finding = actionable(conflicts(tmp_path))[0]
    api.save_decisions(str(tmp_path), {}, {finding["id"]: "known",
                                           "conflict-0000000000000000": "gone"})
    result = conflicts(tmp_path)
    decided = {f["id"]: f["decision"] for f in result["findings"] if f["decision"]}
    assert decided == {finding["id"]: {"accept": "known"}}
    assert result["stale"] == ["conflict-0000000000000000"]


def test_each_side_names_the_chosen_components_it_covers(tmp_path):
    for finding in conflicts(tmp_path)["findings"]:
        for name in ("left", "right"):
            side = finding[name]
            if side is None or not side["chosen"]:
                continue
            assert all(pair in [list(c) for c in CHOSEN] for pair in side["chosen"])
            if not side["whole_mod"]:
                assert {n for _tp2, n in side["chosen"]} <= set(side["components"])


def test_deselecting_a_side_clears_its_finding(tmp_path):
    result = conflicts(tmp_path)
    finding = next(f for f in actionable(result)
                   if f["right"] and f["right"]["chosen"] and f["kind"] == "incompatible")
    dropped = {tuple(pair) for pair in finding["right"]["chosen"]}
    after = conflicts(tmp_path, chosen=[c for c in CHOSEN if c not in dropped])
    assert finding["id"] not in {f["id"] for f in after["findings"]}


def test_without_an_order_catalogue_the_selection_is_judged_as_it_is(tmp_path):
    result = conflicts(tmp_path, order_catalogue=None)
    assert not result["planned"]
    assert not any(f["fixed_by_plan"] for f in result["findings"])


def test_a_decision_saved_with_no_order_data_still_matches_a_planned_run(tmp_path):
    # First run, offline: no krion64 yet. The ids must be the planned run's.
    unplanned = {f["id"] for f in conflicts(tmp_path, order_catalogue=None)["findings"]
                 if f["kind"] != "order"}
    planned = {f["id"] for f in conflicts(tmp_path)["findings"] if f["kind"] != "order"}
    assert unplanned and unplanned == planned


def test_a_key_names_its_own_tp2_not_every_tp2_in_the_folder():
    from iemod_fetch.api import _covered
    chosen = [("eet/EET.tp2", 0), ("eet/EET_end/EET_end.tp2", 0), ("ub/setup-ub.tp2", 3)]
    assert _covered("eet", (0,), False, chosen) == [["eet/EET.tp2", 0]]
    assert _covered("eetend", (), True, chosen) == [["eet/EET_end/EET_end.tp2", 0]]
    # a rule naming the folder when no tp2 has that key: the folder's
    assert _covered("ub", (3,), False, chosen) == [["ub/setup-ub.tp2", 3]]


def test_no_rules_no_findings(tmp_path):
    result = api.selection_conflicts("EET", CHOSEN, folder=str(tmp_path),
                                     data_dir=str(tmp_path / "no-cache"))
    assert result["findings"] == [] and result["rules_checked"] == 0


def test_with_nothing_judged_no_decision_is_called_stale(tmp_path):
    # no community data yet: every decision would look stale, and a click on
    # "Forget them" would wipe the player's answers
    api.save_decisions(str(tmp_path), accept={"conflict-0000000000000000": "known"})
    result = api.selection_conflicts("EET", CHOSEN, folder=str(tmp_path),
                                     data_dir=str(tmp_path / "no-cache"))
    assert result["rules_checked"] == 0 and result["stale"] == []


# ------------------------------------------------------- decisions.json
@pytest.mark.parametrize("text", ["{", '{"schema_version": 9, "decisions": []}',
                                  '{"schema_version": 1, "decisions": [{"finding": "x"}]}'])
def test_an_unreadable_decisions_file_is_a_problem_not_a_crash(tmp_path, text):
    (tmp_path / api.DECISIONS_FILE).write_text(text)
    loaded = api.load_decisions(str(tmp_path))
    assert loaded["problem"] and loaded["choose"] == {} and loaded["accept"] == {}
    assert conflicts(tmp_path)["problem"] == loaded["problem"]


def test_no_decisions_file_is_no_decisions(tmp_path):
    assert api.load_decisions(str(tmp_path)) == {"choose": {}, "accept": {},
                                                  "ignored_order": {}, "problem": None}


def test_decisions_are_saved_whole_and_read_back(tmp_path):
    api.save_decisions(str(tmp_path), {"conflict-a": "option-b"}, {"conflict-c": " why "})
    assert api.load_decisions(str(tmp_path)) == {
        "choose": {"conflict-a": "option-b"}, "accept": {"conflict-c": "why"},
        "ignored_order": {}, "problem": None}
    assert not [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


@pytest.mark.parametrize("choose, accept", [({"x": "option-b"}, {}),
                                            ({"conflict-a": "b"}, {}),
                                            ({}, {"conflict-a": "  "})])
def test_a_decision_the_cli_would_refuse_is_not_written(tmp_path, choose, accept):
    with pytest.raises(ConfigError):
        api.save_decisions(str(tmp_path), choose, accept)
    assert not (tmp_path / api.DECISIONS_FILE).exists()


def test_two_pre_eet_logs_are_refused_not_merged(tmp_path):
    # The plan has one BG:EE phase; two logs would share its name, and their
    # findings their ids.
    import shutil
    second = tmp_path / "other-BGEE.log"
    shutil.copy(os.path.join(MOCK, "WeiDU-BGEE.log"), second)
    with pytest.raises(ConfigError, match="more than one log is not the EET install"):
        api._log_roles([os.path.join(MOCK, "WeiDU.log") + ":EET",
                        os.path.join(MOCK, "WeiDU-BGEE.log") + ":BGEE", f"{second}:BGEE"])


# ------------------------------- who needs what (GUI-AUDIT M5b item 34)
def test_the_check_lists_the_dependencies_the_selection_satisfies(tmp_path):
    needs = conflicts(tmp_path)["needs"]
    # EET_end's own tp2 requires the EET core, which is chosen
    assert {"chosen": [["EET_end/EET_end.tp2", 0]], "on": [[["eet/EET.tp2", 0]]],
            "rule": "eetend(0) needs eet(0)"} in needs


def test_any_one_of_lists_each_alternative_the_selection_has(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "dependencies.json").write_text(json.dumps({"rules": [
        {"rule": "ascension(-):ub(-)|stratagems(-)|notchosen(-)", "severity": "error"}]}))
    result = api.selection_conflicts("EET", CHOSEN, folder=str(tmp_path),
                                     rules=RULES + [str(rules)], order_catalogue=KRION,
                                     target=os.path.join(MOCK, "Mods"),
                                     data_dir=str(tmp_path / "no-cache"))
    need = next(n for n in result["needs"] if n["rule"].startswith("ascension"))
    assert need["chosen"] == [["ascension/Ascension.tp2", 0]]
    # an alternative not chosen is not listed; each chosen one is, whole
    assert [sorted({tuple(p)[0] for p in alt}) for alt in need["on"]] == [
        ["ub/setup-ub.tp2"], ["stratagems/setup-stratagems.tp2"]]


def test_a_dependency_already_broken_is_a_finding_not_a_need(tmp_path):
    without = [key for key in CHOSEN if not key[0].lower().startswith("eet/")]
    result = conflicts(tmp_path, chosen=without)
    assert not any(n["rule"] == "eetend(0) needs eet(0)" for n in result["needs"])
    assert any(f["kind"] == "depends" for f in result["findings"])


def test_an_optional_dependency_is_a_need_only_when_optional_ones_count():
    """Review of #81: a soft dependency ("can also integrate with") is no
    reason to ask before unticking - unless optional ones are reported."""
    from iemod_fetch.rules import DEPENDS, Context, Install, ModSpec, Rule, RuleSet
    install = Install(components={"addon": {0}, "base": {0}})
    rule = Rule(DEPENDS, ModSpec("addon", "addon", frozenset({0})),
                (ModSpec("base", "base", None),), optional=True)
    hard = Rule(DEPENDS, ModSpec("addon", "addon", frozenset({0})),
                (ModSpec("base", "base", frozenset({0})),))
    chosen = [("addon/addon.tp2", 0), ("base/base.tp2", 0)]
    assert api._needs([install], RuleSet(rules=[rule]), Context(), chosen) == []
    with_optional = api._needs([install], RuleSet(rules=[rule]),
                               Context(include_optional=True), chosen)
    assert [n["chosen"] for n in with_optional] == [[["addon/addon.tp2", 0]]]
    assert api._needs([install], RuleSet(rules=[hard]), Context(), chosen)[0]["on"] == [
        [["base/base.tp2", 0]]]
