"""
Tests for the component-level conflict report.

The claims under test:

* a rule that names components fires only on the components you installed - the
  60 mod pairs on the real install that carry a conflict rule and are clear
  must stay clear;
* the report names the exact components on both sides, with the labels from the
  operator's own log;
* provenance survives: a speculative claim is marked speculative;
* the remedy is the narrowest one available, and prefers the cheaper side;
* an order finding the plan already fixes is marked fixed, not repeated;
* per-mod known issues are narrowed to the components you have.
"""
import io
import json
import os


from iemod_fetch.conflicts import (KNOWN_ISSUE, ConflictReport,
                                   build_conflict_report,
                                   render_conflict_report)
from iemod_fetch.ordering import EET_LOG, PRE_EET_LOG, OrderIndex, plan_order
from iemod_fetch.rules import (DEPENDS, INCOMPATIBLE, ORDER, Context, Install,
                               RuleSet)
from iemod_fetch.weidu import parse_weidu_files

HERE = os.path.dirname(__file__)
KRION = os.path.join(HERE, "data", "krion")
REAL_EET = os.path.join(HERE, "data", "WeiDU.log")
REAL_BGEE = os.path.join(HERE, "data", "WeiDUBGEE.log")

HEADER = "// Log of Currently Installed WeiDU Mods\n"


def write_log(tmp_path, name, lines):
    path = tmp_path / name
    path.write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def install_of(path, label="WeiDU.log"):
    return Install.from_log(parse_weidu_files([(path, None)]), label=label)


def rules_file(tmp_path, name, entries):
    path = tmp_path / name
    path.write_text(json.dumps(entries), encoding="utf-8")
    return RuleSet.load([str(path)])


# ------------------------------------------------------- component precision
def test_a_component_rule_does_not_fire_on_the_wrong_component(tmp_path):
    """
    The whole point. `stratagems(7000)` conflicting with `JA#BGT_AdvPack(35)` is
    not a conflict if you did not install #35, and reporting it as one would
    make 60 false findings on the real install.
    """
    ruleset = rules_file(tmp_path, "incompatibilities.json",
                         [{"rule": "stratagems(7000):cdtweaks(1150)",
                           "severity": "error"}])
    log = write_log(tmp_path, "WeiDU.log", [
        r"~stratagems\setup-stratagems.tp2~ #0 #7000 // Smarter mages",
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #2100 // Thieving in heavy armor",
    ])
    report = build_conflict_report([install_of(log)], ruleset)
    assert report.of(INCOMPATIBLE) == []
    assert report.pairs_with_both_mods == 1
    assert report.pairs_cleared_by_components == 1


def test_it_does_fire_when_both_components_are_installed(tmp_path):
    ruleset = rules_file(tmp_path, "incompatibilities.json",
                         [{"rule": "stratagems(7000):cdtweaks(1150)",
                           "severity": "error"}])
    log = write_log(tmp_path, "WeiDU.log", [
        r"~stratagems\setup-stratagems.tp2~ #0 #7000 // Smarter mages",
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #1150 // Shapeshifter rebalancing",
    ])
    finding = build_conflict_report([install_of(log)], ruleset).of(INCOMPATIBLE)[0]
    assert finding.left.numbers == (7000,)
    assert finding.right.numbers == (1150,)
    assert finding.scope == "cross-mod"


def test_component_labels_come_from_the_operators_own_log(tmp_path):
    ruleset = rules_file(tmp_path, "incompatibilities.json",
                         [{"rule": "stratagems(7000):cdtweaks(1150)"}])
    log = write_log(tmp_path, "WeiDU.log", [
        r"~stratagems\setup-stratagems.tp2~ #0 #7000 // Smarter mages",
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #1150 // Shapeshifter rebalancing",
    ])
    finding = build_conflict_report([install_of(log)], ruleset).of(INCOMPATIBLE)[0]
    assert finding.left.components == ((7000, "Smarter mages"),)
    assert "#7000 Smarter mages" in finding.left.describe()


def test_a_version_suffix_is_not_mistaken_for_the_component_name(tmp_path):
    ruleset = rules_file(tmp_path, "incompatibilities.json",
                         [{"rule": "stratagems(7000):cdtweaks(1150)"}])
    log = write_log(tmp_path, "WeiDU.log", [
        r"~stratagems\setup-stratagems.tp2~ #0 #7000 // Smarter mages : v35",
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #1150 // Shapeshifter",
    ])
    finding = build_conflict_report([install_of(log)], ruleset).of(INCOMPATIBLE)[0]
    assert finding.left.components == ((7000, "Smarter mages"),)


def test_a_rule_naming_no_components_is_reported_as_the_whole_mod(tmp_path):
    ruleset = rules_file(tmp_path, "incompatibilities.json",
                         [{"rule": "stratagems:cdtweaks"}])
    log = write_log(tmp_path, "WeiDU.log", [
        r"~stratagems\setup-stratagems.tp2~ #0 #7000 // Smarter mages",
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #1150 // Shapeshifter",
    ])
    finding = build_conflict_report([install_of(log)], ruleset).of(INCOMPATIBLE)[0]
    assert finding.left.whole_mod and finding.right.whole_mod
    assert "whole mod" in finding.left.describe()


def test_two_components_of_the_same_mod_are_scoped_as_such(tmp_path):
    ruleset = rules_file(tmp_path, "incompatibilities.json",
                         [{"rule": "cdtweaks(1251,1252):cdtweaks(1257)",
                           "severity": "error"}])
    log = write_log(tmp_path, "WeiDU.log", [
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #1251 // Move Alora",
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #1252 // Move Eldoth",
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #1257 // Move all six",
    ])
    finding = build_conflict_report([install_of(log)], ruleset).of(INCOMPATIBLE)[0]
    assert finding.scope == "same-mod"
    assert finding.left.numbers == (1251, 1252)
    assert finding.right.numbers == (1257,)
    assert "deselect one of the two groups" in finding.remedy


# ------------------------------------------------------------------ remedies
def test_the_remedy_prefers_the_side_with_fewer_components(tmp_path):
    ruleset = rules_file(tmp_path, "incompatibilities.json",
                         [{"rule": "cdtweaks(1251,1252,1253):stratagems(7000)"}])
    log = write_log(tmp_path, "WeiDU.log", [
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #1251 // Move Alora",
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #1252 // Move Eldoth",
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #1253 // Move Quayle",
        r"~stratagems\setup-stratagems.tp2~ #0 #7000 // Smarter mages",
    ])
    finding = build_conflict_report([install_of(log)], ruleset).of(INCOMPATIBLE)[0]
    assert finding.remedy.startswith("deselect stratagems: #7000")
    assert "alternative" in finding.remedy


def test_a_component_fix_beats_dropping_a_whole_mod(tmp_path):
    """
    "drop infinity_ui" and "deselect stratagems #4115" are not equal advice.
    The rule pinned one side and not the other; the pinned side is the fix.
    """
    ruleset = rules_file(tmp_path, "incompatibilities.json",
                         [{"rule": "infinity_ui:stratagems(4115)"}])
    log = write_log(tmp_path, "WeiDU.log", [
        r"~infinity_ui\infinity_ui.tp2~ #0 #0 // Infinity UI++",
        r"~stratagems\setup-stratagems.tp2~ #0 #4115 // Skill points in fives",
    ])
    finding = build_conflict_report([install_of(log)], ruleset).of(INCOMPATIBLE)[0]
    assert finding.remedy.startswith("deselect stratagems: #4115")
    assert "drop infinity_ui" in finding.remedy


def test_when_neither_side_is_pinned_the_report_says_so(tmp_path):
    ruleset = rules_file(tmp_path, "incompatibilities.json",
                         [{"rule": "stratagems:cdtweaks"}])
    log = write_log(tmp_path, "WeiDU.log", [
        r"~stratagems\setup-stratagems.tp2~ #0 #7000 // Smarter mages",
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #1150 // Shapeshifter",
    ])
    finding = build_conflict_report([install_of(log)], ruleset).of(INCOMPATIBLE)[0]
    assert "the rules do not narrow it to components" in finding.remedy


def test_a_missing_prerequisite_names_the_components_it_wants(tmp_path):
    ruleset = rules_file(tmp_path, "dependencies.json",
                         [{"rule": "TDDz:TDD(0)", "severity": "error"}])
    log = write_log(tmp_path, "WeiDU.log",
                    [r"~TDDz\setup-tddz.tp2~ #0 #0 // TDD for EE"])
    finding = build_conflict_report([install_of(log)], ruleset).of(DEPENDS)[0]
    assert finding.scope == "missing"
    assert finding.right.numbers == (0,)
    assert finding.remedy.startswith("install TDD")


# ---------------------------------------------------------------- provenance
def test_a_speculative_claim_is_marked_as_speculative(tmp_path):
    record = tmp_path / "cdtweaks.json"
    record.write_text(json.dumps({
        "t": "cdtweaks", "ord": 20,
        "conflicts": [{"with": "stratagems", "severity": "partial",
                       "myComps": "#1150", "theirComps": "#7000",
                       "reason": "both touch shapeshifting",
                       "source": "tp2 analysis, 2026-04",
                       "evidenceLevel": "speculative"}],
    }), encoding="utf-8")
    log = write_log(tmp_path, "WeiDU.log", [
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #1150 // Shapeshifter",
        r"~stratagems\setup-stratagems.tp2~ #0 #7000 // Smarter mages",
    ])
    finding = build_conflict_report(
        [install_of(log)], RuleSet.load([str(record)])).of(INCOMPATIBLE)[0]
    assert finding.evidence == "speculative"
    assert finding.source == "tp2 analysis, 2026-04"
    assert finding.raw_severity == "partial"

    text = io.StringIO()
    render_conflict_report(build_conflict_report(
        [install_of(log)], RuleSet.load([str(record)])), text)
    assert "SPECULATIVE" in text.getvalue()


def test_advisories_are_loaded_but_withheld_by_default(tmp_path):
    """
    krion64's `advisories` are observations nobody traced. Loading them at the
    same weight as verified conflicts would bury the real findings; not loading
    them at all throws away thousands of component-level observations.
    """
    record = tmp_path / "cdtweaks.json"
    record.write_text(json.dumps({
        "t": "cdtweaks", "ord": 20,
        "advisories": [{"with": "stratagems", "severity": "soft",
                        "myComps": "#1150", "theirComps": "#7000",
                        "reason": "may interact",
                        "evidenceLevel": "speculative"}],
    }), encoding="utf-8")
    log = write_log(tmp_path, "WeiDU.log", [
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #1150 // Shapeshifter",
        r"~stratagems\setup-stratagems.tp2~ #0 #7000 // Smarter mages",
    ])
    report = build_conflict_report([install_of(log)], RuleSet.load([str(record)]))
    assert [f.severity for f in report.of(INCOMPATIBLE)] == ["note"]

    quiet, loud = io.StringIO(), io.StringIO()
    render_conflict_report(report, quiet)
    render_conflict_report(report, loud, show_notes=True)
    assert "advisory finding(s) withheld" in quiet.getvalue()
    assert "may interact" not in quiet.getvalue()
    assert "may interact" in loud.getvalue()


def test_english_rule_text_is_preferred_over_the_french_description(tmp_path):
    ruleset = rules_file(tmp_path, "incompatibilities.json", [
        {"rule": "stratagems(7000):cdtweaks(1150)",
         "description": "Conflit interne",
         "translations": {"en_US": "Internal conflict", "fr_FR": "Conflit interne"}},
    ])
    log = write_log(tmp_path, "WeiDU.log", [
        r"~stratagems\setup-stratagems.tp2~ #0 #7000 // Smarter mages",
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #1150 // Shapeshifter",
    ])
    finding = build_conflict_report([install_of(log)], ruleset).of(INCOMPATIBLE)[0]
    assert finding.reason == "Internal conflict"


# --------------------------------------------------------------- known issues
def test_a_known_issue_fires_only_for_components_you_installed(tmp_path):
    record = tmp_path / "cdtweaks.json"
    record.write_text(json.dumps({
        "t": "cdtweaks", "ord": 20,
        "ki": [{"pattern": "slowdown", "severity": "warning",
                "description": "these two components cost frame rate",
                "components": [260, 2680],
                "workaround": "skip them if performance matters",
                "evidenceLevel": "mechanism-verified"}],
    }), encoding="utf-8")
    ruleset = RuleSet.load([str(record)])
    assert len(ruleset.notes) == 1

    clear = write_log(tmp_path, "a.log",
                      [r"~cdtweaks\setup-cdtweaks.tp2~ #0 #1150 // Shapeshifter"])
    assert build_conflict_report([install_of(clear)], ruleset).of(KNOWN_ISSUE) == []

    hit = write_log(tmp_path, "b.log",
                    [r"~cdtweaks\setup-cdtweaks.tp2~ #0 #260 // Hide effects"])
    finding = build_conflict_report([install_of(hit)], ruleset).of(KNOWN_ISSUE)[0]
    assert finding.left.numbers == (260,)
    assert finding.workaround == "skip them if performance matters"


def test_a_known_issue_with_no_component_list_applies_to_the_whole_mod(tmp_path):
    record = tmp_path / "eeex.json"
    record.write_text(json.dumps({
        "t": "EEex", "ord": 10,
        "ki": [{"severity": "critical", "description": "engine version tied",
                "forum": "https://example.invalid/thread"}],
    }), encoding="utf-8")
    log = write_log(tmp_path, "WeiDU.log", [r"~EEex\EEex.tp2~ #0 #0 // EEex"])
    finding = build_conflict_report(
        [install_of(log)], RuleSet.load([str(record)])).of(KNOWN_ISSUE)[0]
    assert finding.severity == "error"
    assert finding.left.whole_mod
    assert finding.source == "https://example.invalid/thread"


# ------------------------------------------------------ interaction with plan
def test_an_order_finding_the_plan_fixes_is_marked_fixed(tmp_path):
    rules = tmp_path / "order.json"
    rules.write_text(json.dumps(
        [{"rule": "cdtweaks:stratagems", "direction": "after"}]), encoding="utf-8")
    ruleset = RuleSet.load([str(rules)])
    log = write_log(tmp_path, "WeiDU.log", [
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #10 // Tweak",
        r"~stratagems\setup-stratagems.tp2~ #0 #10 // SCS",
    ])
    plan = plan_order([(log, EET_LOG)], OrderIndex.load(KRION), ruleset)
    report = build_conflict_report([install_of(log)], ruleset, Context(), plan)
    finding = report.of(ORDER)[0]
    assert finding.order_fixable and finding.fixed_by_plan is True
    assert not finding.actionable
    assert report.actionable == []


def test_without_a_plan_an_order_finding_stays_outstanding(tmp_path):
    rules = tmp_path / "order.json"
    rules.write_text(json.dumps(
        [{"rule": "cdtweaks:stratagems", "direction": "after"}]), encoding="utf-8")
    ruleset = RuleSet.load([str(rules)])
    log = write_log(tmp_path, "WeiDU.log", [
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #10 // Tweak",
        r"~stratagems\setup-stratagems.tp2~ #0 #10 // SCS",
    ])
    finding = build_conflict_report([install_of(log)], ruleset).of(ORDER)[0]
    assert finding.fixed_by_plan is None
    assert finding.actionable


# ---------------------------------------------------------- real install data
def test_the_real_install_is_reported_honestly():
    ruleset = RuleSet()          # no rules loaded at all
    installs = [install_of(REAL_EET, EET_LOG), install_of(REAL_BGEE, PRE_EET_LOG)]
    report = build_conflict_report(installs, ruleset)
    assert len(report) == 0
    text = io.StringIO()
    render_conflict_report(report, text)
    assert "nothing fired" in text.getvalue()


def test_the_report_states_how_much_was_actually_examined(tmp_path):
    """
    "No conflicts found" is unfalsifiable without this. It must be possible to
    tell an install that is clean from a rule set that matched nothing.
    """
    ruleset = rules_file(tmp_path, "incompatibilities.json",
                         [{"rule": "stratagems(7000):cdtweaks(1150)"}])
    log = write_log(tmp_path, "WeiDU.log", [
        r"~stratagems\setup-stratagems.tp2~ #0 #7000 // Smarter mages",
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #2100 // Something else",
    ])
    text = io.StringIO()
    render_conflict_report(build_conflict_report([install_of(log)], ruleset), text)
    out = text.getvalue()
    assert "1 rule(s)" in out
    assert "1 pair(s) where both mods are installed" in out
    assert "1 cleared because the named components are not installed" in out


def test_json_round_trips(tmp_path):
    ruleset = rules_file(tmp_path, "incompatibilities.json",
                         [{"rule": "stratagems(7000):cdtweaks(1150)",
                           "severity": "error"}])
    log = write_log(tmp_path, "WeiDU.log", [
        r"~stratagems\setup-stratagems.tp2~ #0 #7000 // Smarter mages",
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #1150 // Shapeshifter",
    ])
    out = tmp_path / "nested" / "conflicts.json"
    build_conflict_report([install_of(log)], ruleset).write_json(str(out))
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["rules_checked"] == 1
    assert payload["findings"][0]["left"]["components"] == [7000]
    assert payload["findings"][0]["right"]["mod"] == "cdtweaks"


def test_empty_report_renders(tmp_path):
    text = io.StringIO()
    render_conflict_report(ConflictReport(), text)
    assert "COMPONENT CONFLICT REPORT" in text.getvalue()


# ------------------------------------------------------------------- the CLI
def test_cli_emits_the_conflict_report(tmp_path):
    from iemod_fetch import cli
    rules = tmp_path / "incompatibilities.json"
    rules.write_text(json.dumps(
        [{"rule": "stratagems(3183):cdtweaks(1150)", "severity": "error"}]),
        encoding="utf-8")
    stream = io.StringIO()
    out = tmp_path / "conflicts.json"
    code = cli.main(["--check-only",
                     "-m", os.path.join(HERE, "data", "mod_downloads.json"),
                     "-w", f"{REAL_EET}:EET",
                     "--rules", str(rules),
                     "--conflict-report", str(out)], stream=stream)
    text = stream.getvalue()
    assert "COMPONENT CONFLICT REPORT" in text
    assert out.exists()
    assert code in (0, 1)
