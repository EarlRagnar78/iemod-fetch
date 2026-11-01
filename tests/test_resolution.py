"""
Automatic conflict resolution (ADR-0021) - opt-in, narrow, and re-verified.

The load-bearing claims:

* only an `error`-graded incompatibility whose rule names components is
  resolved, by removing the cheaper component-pinned side - exactly the remedy
  the conflict report already prints;
* a rule that condemns both mods wholesale, a same-mod conflict, a missing
  dependency, a speculative or a warning-level claim is NEVER resolved: those
  stay the operator's decision and are listed as such;
* nothing is removed that the rule did not name, and the plan is re-checked
  after the removal rather than trusted.
"""
import json
import os
import pathlib

import pytest

from iemod_fetch.conflicts import build_conflict_report
from iemod_fetch.ordering import EET_LOG, PRE_EET_LOG, OrderIndex, plan_order
from iemod_fetch.resolution import resolve_conflicts
from iemod_fetch.rules import RuleSet

HERE = os.path.dirname(__file__)
KRION = os.path.join(HERE, "data", "krion")
MANIFEST = os.path.join(HERE, "data", "mod_downloads.json")
HEADER = "// Log of Currently Installed WeiDU Mods\n"


@pytest.fixture
def index():
    return OrderIndex.load(KRION)


def write_log(tmp_path, name, lines):
    path = tmp_path / name
    path.write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def ruleset(tmp_path, entries, name="incompatibilities.json"):
    path = tmp_path / name
    path.write_text(json.dumps(entries), encoding="utf-8")
    return RuleSet.load([str(path)])


def planned(tmp_path, index, rules, lines, role=EET_LOG):
    log = write_log(tmp_path, "WeiDU.log", lines)
    plan = plan_order([(log, role)], index, rules)
    report = build_conflict_report(plan.installs(), rules, plan=plan)
    return plan, report


def components(plan, role=EET_LOG):
    return [(unit.display, comp) for unit in plan.logs.get(role, ())
            for _path, _lang, comp, _comment in unit.lines]


SCS_VS_TWEAKS = [
    r"~stratagems\setup-stratagems.tp2~ #0 #4115 // Smarter mages",
    r"~stratagems\setup-stratagems.tp2~ #0 #5000 // Smarter priests",
    r"~cdtweaks\setup-cdtweaks.tp2~ #0 #1150 // Shapeshifter",
    r"~cdtweaks\setup-cdtweaks.tp2~ #0 #1151 // Shapeshifter 2",
    r"~cdtweaks\setup-cdtweaks.tp2~ #0 #2100 // Heavy armour thieving",
]


# ------------------------------------------------------------------- resolved
def test_the_cheaper_component_side_is_removed_and_nothing_else(tmp_path, index):
    rules = ruleset(tmp_path, [{"rule": "stratagems(4115):cdtweaks(1150,1151)",
                                "severity": "error"}])
    plan, report = planned(tmp_path, index, rules, SCS_VS_TWEAKS)

    result = resolve_conflicts(plan, report, rules)

    assert [(r.mod, r.components) for r in result.removed] == [("stratagems", (4115,))]
    kept = components(plan)
    assert ("stratagems", 4115) not in kept
    assert ("stratagems", 5000) in kept                 # not named by the rule
    assert ("cdtweaks", 1150) in kept and ("cdtweaks", 2100) in kept
    assert result.left_for_operator == []
    assert not plan.blockers                            # re-verified, now clean


def test_a_component_side_beats_a_whole_mod_side(tmp_path, index):
    rules = ruleset(tmp_path, [{"rule": "stratagems:cdtweaks(2100)",
                                "severity": "error"}])
    plan, report = planned(tmp_path, index, rules, SCS_VS_TWEAKS)
    result = resolve_conflicts(plan, report, rules)
    assert [(r.mod, r.components) for r in result.removed] == [("cdtweaks", (2100,))]
    assert ("stratagems", 4115) in components(plan)


def test_a_mod_left_with_no_components_leaves_the_plan(tmp_path, index):
    rules = ruleset(tmp_path, [{"rule": "stratagems:cdtweaks(1150,1151,2100)",
                                "severity": "error"}])
    plan, report = planned(tmp_path, index, rules, SCS_VS_TWEAKS)
    resolve_conflicts(plan, report, rules)
    assert [u.display for u in plan.logs[EET_LOG]] == ["stratagems"]


def test_two_findings_on_one_side_do_not_remove_twice(tmp_path, index):
    rules = ruleset(tmp_path, [
        {"rule": "stratagems(4115):cdtweaks(1150,1151)", "severity": "error"},
        {"rule": "stratagems(4115):cdtweaks(2100,1150,1151)", "severity": "error"},
    ])
    plan, report = planned(tmp_path, index, rules, SCS_VS_TWEAKS)
    result = resolve_conflicts(plan, report, rules)
    assert sum(len(r.components) for r in result.removed) == 1


# ----------------------------------------------------- left for the operator
@pytest.mark.parametrize("entry,why", [
    ({"rule": "stratagems:cdtweaks", "severity": "error"}, "whole mod"),
    ({"rule": "stratagems(4115):cdtweaks(1150)", "severity": "warning"}, "warning"),
    ({"rule": "stratagems(4115):cdtweaks(1150)", "severity": "error",
      "evidenceLevel": "speculative"}, "speculative"),
    ({"rule": "cdtweaks(1150):cdtweaks(2100)", "severity": "error"}, "equal"),
    ({"rule": "stratagems(4115):cdtweaks(2100)", "severity": "error"}, "equal"),
])
def test_what_the_rules_do_not_decide_is_left_to_the_operator(tmp_path, index,
                                                              entry, why):
    rules = ruleset(tmp_path, [entry])
    plan, report = planned(tmp_path, index, rules, SCS_VS_TWEAKS)
    before = components(plan)

    result = resolve_conflicts(plan, report, rules)

    assert result.removed == []
    assert components(plan) == before
    if entry["severity"] == "error":
        assert len(result.left_for_operator) == 1
        assert why in result.left_for_operator[0].why


def test_a_same_mod_conflict_drops_the_smaller_group(tmp_path, index):
    """cdtweaks #1150+#1151 vs cdtweaks #2100: the pinned group of one goes."""
    rules = ruleset(tmp_path, [{"rule": "cdtweaks(1150,1151):cdtweaks(2100)",
                                "severity": "error"}])
    plan, report = planned(tmp_path, index, rules, SCS_VS_TWEAKS)
    result = resolve_conflicts(plan, report, rules)
    assert [(r.mod, r.components) for r in result.removed] == [("cdtweaks", (2100,))]
    assert ("cdtweaks", 1150) in components(plan)


# WeiDU logs a SUBCOMPONENT choice as "Group -> Option". Two options of one
# group are mutually exclusive by the mod's own design: installing the second
# makes WeiDU uninstall the first. The plan keeps the one WeiDU would end with.
SUBCOMPONENTS = [
    r"~cdtweaks\setup-cdtweaks.tp2~ #0 #100 // Stack sizes -> 40",
    r"~cdtweaks\setup-cdtweaks.tp2~ #0 #2100 // Thieving in heavy armour",
    r"~cdtweaks\setup-cdtweaks.tp2~ #0 #101 // Stack sizes -> 80",
]


def test_two_options_of_one_subcomponent_group_are_a_conflict(tmp_path, index):
    plan, report = planned(tmp_path, index, RuleSet(), SUBCOMPONENTS)
    found = [f for f in report.findings if f.origin == "WeiDU SUBCOMPONENT"]
    assert len(found) == 1
    assert found[0].left.numbers == (100,) and found[0].right.numbers == (101,)


def test_the_last_option_of_a_subcomponent_group_is_kept(tmp_path, index):
    plan, report = planned(tmp_path, index, RuleSet(), SUBCOMPONENTS)
    result = resolve_conflicts(plan, report, RuleSet())
    assert [(r.mod, r.components) for r in result.removed] == [("cdtweaks", (100,))]
    assert ("cdtweaks", 101) in components(plan) and ("cdtweaks", 2100) in components(plan)


def test_one_option_per_group_is_not_a_conflict(tmp_path, index):
    lines = [SUBCOMPONENTS[0], SUBCOMPONENTS[1]]
    _plan, report = planned(tmp_path, index, RuleSet(), lines)
    assert not [f for f in report.findings if f.origin == "WeiDU SUBCOMPONENT"]


def test_a_missing_dependency_is_never_resolved_by_removal(tmp_path, index):
    rules = ruleset(tmp_path, [{"rule": "cdtweaks(2100):eefixpack",
                                "severity": "error"}], name="dependencies.json")
    plan, report = planned(tmp_path, index, rules, SCS_VS_TWEAKS)
    before = components(plan)
    result = resolve_conflicts(plan, report, rules)
    assert result.removed == [] and components(plan) == before


def test_the_pre_eet_log_is_resolved_in_its_own_right(tmp_path, index):
    rules = ruleset(tmp_path, [{"rule": "stratagems(4115):cdtweaks(1150,1151)",
                                "severity": "error"}])
    plan, report = planned(tmp_path, index, rules, SCS_VS_TWEAKS, role=PRE_EET_LOG)
    result = resolve_conflicts(plan, report, rules)
    assert result.removed[0].log == PRE_EET_LOG
    assert ("stratagems", 4115) not in components(plan, PRE_EET_LOG)


def test_resolution_is_described_for_a_human(tmp_path, index):
    rules = ruleset(tmp_path, [{"rule": "stratagems(4115):cdtweaks(1150,1151)",
                                "severity": "error", "description": "SCS vs Tweaks"}])
    plan, report = planned(tmp_path, index, rules, SCS_VS_TWEAKS)
    text = resolve_conflicts(plan, report, rules).render()
    assert "removed" in text and "stratagems" in text and "#4115" in text
    assert "cdtweaks" in text                       # what it conflicted with


# ----------------------------------------------------------------- the CLI
def _cli(argv):
    import io

    from iemod_fetch import cli
    stream = io.StringIO()
    code = cli.main(argv, stream=stream)
    return code, stream.getvalue()


def test_cli_resolves_into_the_plan_and_leaves_the_input_alone(tmp_path):
    rules = tmp_path / "incompatibilities.json"
    rules.write_text(json.dumps([{"rule": "stratagems(4115):cdtweaks(1150,1151)",
                                  "severity": "error"}]), encoding="utf-8")
    log = write_log(tmp_path, "WeiDU.log", SCS_VS_TWEAKS)
    original = pathlib.Path(log).read_text(encoding="utf-8")
    out = tmp_path / "plan"
    code, text = _cli(["--check-only", "-m", MANIFEST,
                       "-w", f"{log}:EET", "--rules", str(rules),
                       "--order-catalogue", KRION, "--plan-order", str(out),
                       "--resolve-conflicts"])
    planned_log = (out / "WeiDU.log").read_text()
    assert "#4115" not in planned_log and "#5000" in planned_log
    assert pathlib.Path(log).read_text(encoding="utf-8") == original   # untouched
    assert "CONFLICT RESOLUTION" in text and "removed" in text
    assert (out / "RESOLUTION.json").is_file()
    assert code == 1          # the INPUT still has the conflict; the check says so


def test_cli_refuses_to_resolve_without_a_plan(tmp_path, capsys):
    log = write_log(tmp_path, "WeiDU.log", SCS_VS_TWEAKS)
    code, _text = _cli(["--check-only", "-w", f"{log}:EET", "--resolve-conflicts"])
    assert code == 2
    assert "--plan-order" in capsys.readouterr().err


# --------------------------------------------- what WeiDU would refuse (ADR-0025)
from iemod_fetch.constraints import EetMergeRules, ModConstraints  # noqa: E402
from iemod_fetch.resolution import resolve_refusals  # noqa: E402
from iemod_fetch.tp2 import Tp2Component  # noqa: E402


def two_phase_plan(tmp_path, index, bgee_lines, eet_lines):
    pre = tmp_path / "bgee.log"
    pre.write_text(HEADER + "\n".join(bgee_lines) + "\n", encoding="utf-8")
    eet = tmp_path / "eet.log"
    eet.write_text(HEADER + "\n".join(eet_lines) + "\n", encoding="utf-8")
    return plan_order([(str(eet), EET_LOG), (str(pre), PRE_EET_LOG)], index)


BGEE = [r"~DlcMerger\DlcMerger.tp2~ #0 #1 // Merge SoD",
        r"~bg1aerie\setup-bg1aerie.tp2~ #0 #0 // Aerie for BG:EE (not in this table)"]
EET = [r"~eet\EET.tp2~ #0 #0 // EET core (resource importation)",
       r"~cdtweaks\setup-cdtweaks.tp2~ #0 #4000 // BG2EE-only tweak",
       r"~eet\EET_end\EET_end.tp2~ #0 #0 // Standard installation"]
CONSTRAINTS = ModConstraints(by_mod={
    "dlcmerger": {1: Tp2Component(1, games=["BGEE"])},
    "bg1aerie": {0: Tp2Component(0)},
    "eet": {0: Tp2Component(0)},
    "cdtweaks": {4000: Tp2Component(4000, games=["BG2EE"])},
    "eetend": {0: Tp2Component(0, requires=[("eet", 0)])},
}, eet=EetMergeRules(allowed={"dlcmerger"}))


def test_bgee_mods_eet_cannot_import_are_dropped_and_the_merge_proceeds(tmp_path, index):
    plan = two_phase_plan(tmp_path, index, BGEE, EET)
    result = resolve_refusals(plan, CONSTRAINTS)
    removed = {(r.log, r.mod): r.because for r in result.removed}
    assert "compatibility.tbl" in removed[(PRE_EET_LOG, "bg1aerie")]
    assert ("eet", 0) in components(plan) and ("eet/EET_end", 0) in components(plan)


def test_a_component_weidu_would_refuse_is_dropped_with_its_reason(tmp_path, index):
    plan = two_phase_plan(tmp_path, index, BGEE[:1], EET)
    result = resolve_refusals(plan, CONSTRAINTS)
    assert [(r.mod, r.components) for r in result.removed] == [("cdtweaks", (4000,))]
    assert "game is EET" in result.removed[0].because


def test_the_eet_core_is_never_dropped(tmp_path, index):
    """Refused for a reason other than its merge table: that is yours to fix."""
    constraints = ModConstraints(by_mod=dict(
        CONSTRAINTS.by_mod, eet={0: Tp2Component(0, requires=[("ghostmod", 9)])}))
    plan = two_phase_plan(tmp_path, index, BGEE[:1], EET)
    result = resolve_refusals(plan, constraints)
    assert ("eet", 0) in components(plan)
    assert any("EET core" in item.why for item in result.left_for_operator)


def test_what_is_left_for_the_operator_points_at_its_finding(tmp_path, index):
    """A UI shows the choice next to the conflict it belongs to (ADR-0030)."""
    rules = ruleset(tmp_path, [{"rule": "stratagems(4115):cdtweaks(1150)",
                                "severity": "warning"}])
    plan, report = planned(tmp_path, index, rules, SCS_VS_TWEAKS)
    result = resolve_conflicts(plan, report, rules)
    ids = {f.id for f in report.findings}
    assert result.left_for_operator
    assert all(u.finding_id in ids for u in result.left_for_operator)
    data = result.as_dict()
    assert data["schema_version"] == 1
    assert data["left_for_operator"][0]["finding_id"] in ids


# What may go on BG2:EE before the EET core: BWS-NG's games/eet.json, which is
# maintained (2026) and contains what EET's readme allows (the Fixpack), is the
# list when it is available; the readme's rule is the floor.
BWS_EET = {"sequences": [
    {"game": "sod", "order": ["dlcmerger:1", "eefixpack:0"]},
    {"game": "bg2ee", "order": ["weidu:0", "eefixpack:0", "eefixpack:1",
                                "correctfrbg2ee:10", "eet:0", "cdtweaks:4000"]}]}


def test_the_bws_ng_sequence_says_what_goes_before_the_eet_core():
    from iemod_fetch.resolution import before_eet_core
    allowed = before_eet_core(BWS_EET)
    assert {"eefixpack", "correctfrbg2ee"} <= set(allowed)
    assert "cdtweaks" not in allowed and "dlcmerger" not in allowed
    assert "games/eet.json" in allowed["correctfrbg2ee"]


def test_without_the_bws_ng_sequence_the_readme_rule_stands():
    from iemod_fetch.resolution import BEFORE_EET_CORE, before_eet_core
    assert before_eet_core(None) == BEFORE_EET_CORE
    assert before_eet_core({"sequences": "nonsense"}) == BEFORE_EET_CORE


def test_a_mod_bws_ng_orders_before_the_core_is_moved_there(tmp_path, index):
    eet = [r"~eet\EET.tp2~ #0 #0 // EET core (resource importation)",
           r"~correctfrbg2ee\correctfrbg2ee.tp2~ #0 #10 // Corrections"]
    constraints = ModConstraints(by_mod={
        "eet": {0: Tp2Component(0)},
        "correctfrbg2ee": {10: Tp2Component(10, not_games=["EET"])}})
    from iemod_fetch.resolution import before_eet_core
    plan = two_phase_plan(tmp_path, index, BGEE[:1], eet)
    result = resolve_refusals(plan, constraints, before_core=before_eet_core(BWS_EET))
    assert [(m.mod, m.components) for m in result.moved] == [("correctfrbg2ee", (10,))]
    order = [(display.split(" ")[0], number) for display, number in components(plan)]
    assert order.index(("correctfrbg2ee", 10)) < order.index(("eet", 0))
