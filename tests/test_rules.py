"""
Install-order, incompatibility and dependency checking against a WeiDU log.

Fixtures use the real rule shapes from BigWorldSetup-Next-Generation.
"""
import json

import pytest

from iemod_fetch.errors import ConfigError
from iemod_fetch.rules import (DEPENDS, INCOMPATIBLE, ORDER, Install, RuleSet,
                               check, check_all, parse_spec)
from iemod_fetch.weidu import parse_weidu_log


def log(*lines):
    return parse_weidu_log("".join(lines))


def line(folder, comp, tp2=None):
    return f"~{folder}\\{tp2 or folder}.tp2~ #0 #{comp} // c{comp}\n"


def rules(kind, *entries):
    return RuleSet.from_mapping({"rules": list(entries)}, kind, "test")


# ------------------------------------------------------------------ parsing
@pytest.mark.parametrize("text,mod,components", [
    ("stratagems(-)", "stratagems", None),
    ("5E_spellcasting(100)", "5espellcasting", {100}),
    ("A7-ConvenientEENPCs(1,101)", "a7convenienteenpcs", {1, 101}),
    ("cdtweaks(  1 , 2 )", "cdtweaks", {1, 2}),
])
def test_spec_parsing(text, mod, components):
    spec = parse_spec(text)
    assert spec.mod == mod
    assert spec.components == (frozenset(components) if components else None)


def test_an_unparseable_component_list_widens_rather_than_drops():
    """`(3183.4.1)` appears once in the real data; never silently skip a rule."""
    assert parse_spec("mod(3183.4.1)").components == frozenset({3183, 4, 1})
    assert parse_spec("mod(nonsense)").components is None      # widened to "any"


def test_a_rule_without_a_colon_is_skipped_with_a_warning():
    ruleset = rules(ORDER, {"rule": "nonsense", "severity": "warning"})
    assert len(ruleset) == 0 and ruleset.warnings


def test_the_english_translation_becomes_the_message():
    ruleset = rules(ORDER, {"rule": "a(-):b(-)", "direction": "before",
                            "translations": {"en_US": "because reasons",
                                             "fr_FR": "raisons"}})
    assert ruleset.rules[0].message == "because reasons"


# -------------------------------------------------------------------- order
def test_an_order_violation_is_reported():
    install = Install.from_log(log(line("cdtweaks", 1), line("stratagems", 0)))
    found = check(install, rules(ORDER, {"rule": "stratagems(-):cdtweaks(-)",
                                         "direction": "before",
                                         "severity": "warning"}))
    assert len(found) == 1
    assert found[0].kind == ORDER
    assert "stratagems should be installed before cdtweaks" in found[0].summary


def test_the_right_order_reports_nothing():
    install = Install.from_log(log(line("stratagems", 0), line("cdtweaks", 1)))
    assert check(install, rules(ORDER, {"rule": "stratagems(-):cdtweaks(-)",
                                        "direction": "before"})) == []


def test_after_is_the_mirror_of_before():
    install = Install.from_log(log(line("a", 0), line("b", 0)))
    found = check(install, rules(ORDER, {"rule": "a(-):b(-)", "direction": "after"}))
    assert found and "b should be installed before a" in found[0].summary


def test_a_rule_about_a_mod_you_do_not_have_is_silent():
    install = Install.from_log(log(line("a", 0)))
    assert check(install, rules(ORDER, {"rule": "a(-):notinstalled(-)",
                                        "direction": "before"})) == []


# ----------------------------------------------------------- incompatibility
def test_two_incompatible_mods_are_reported():
    install = Install.from_log(log(line("ascension", 40), line("ub", 19)))
    found = check(install, rules(INCOMPATIBLE, {"rule": "ascension(40):ub(19)",
                                                "severity": "error"}))
    assert found and found[0].blocking
    assert "ascension and ub are incompatible" in found[0].summary


def test_components_that_do_not_overlap_are_not_a_conflict():
    install = Install.from_log(log(line("ascension", 10), line("ub", 19)))
    assert check(install, rules(INCOMPATIBLE,
                                {"rule": "ascension(40):ub(19)"})) == []


def test_an_internal_conflict_reads_as_one():
    install = Install.from_log(log(line("cdtweaks", 1251), line("cdtweaks", 1257)))
    found = check(install, rules(INCOMPATIBLE,
                                 {"rule": "cdtweaks(1251):cdtweaks(1257)",
                                  "severity": "error"}))
    assert "conflict with each other" in found[0].summary


# ------------------------------------------------------------- dependencies
def test_a_missing_prerequisite_is_reported():
    install = Install.from_log(log(line("TDDz", 0)))
    found = check(install, rules(DEPENDS, {"rule": "TDDz(-):TDD(0)",
                                           "severity": "error",
                                           "description": "TDD is required"}))
    assert found and found[0].kind == DEPENDS and found[0].blocking
    assert "needs TDD(0)" in found[0].summary


def test_a_satisfied_prerequisite_is_silent():
    install = Install.from_log(log(line("TDD", 0), line("TDDz", 0)))
    assert check(install, rules(DEPENDS, {"rule": "TDDz(-):TDD(0)"})) == []


def test_any_one_alternative_satisfies_a_dependency():
    install = Install.from_log(log(line("a", 0), line("c", 5)))
    assert check(install, rules(DEPENDS, {"rule": "a(-):b(1)|c(5)"})) == []


# ------------------------------------------------- one log is one game install
def test_two_logs_are_never_ordered_against_each_other():
    """
    Regression: merging an EET log and a BGEE log compared positions across two
    separate installs and invented order violations that cannot exist.
    """
    eet = Install.from_log(log(line("eefixpack", 0)), label="WeiDU.log")
    bgee = Install.from_log(log(line("DlcMerger", 3)), label="WeiDUBGEE.log")
    ruleset = rules(ORDER, {"rule": "DlcMerger(-):eefixpack(-)",
                            "direction": "before"})
    assert check_all([eet, bgee], ruleset) == []


def test_findings_are_labelled_when_several_logs_are_checked():
    a = Install.from_log(log(line("x", 1), line("y", 0)), label="A.log")
    b = Install.from_log(log(line("p", 0)), label="B.log")
    found = check_all([a, b], rules(ORDER, {"rule": "y(-):x(-)",
                                            "direction": "before"}))
    assert found and found[0].summary.startswith("[A.log]")


# ------------------------------------------------------- the mod's own ini
def test_a_mods_own_before_list_becomes_a_rule():
    ruleset = RuleSet()
    ruleset.add_metadata_order("stratagems", before=["cdtweaks"], after=[])
    install = Install.from_log(log(line("cdtweaks", 1), line("stratagems", 0)))
    found = check(install, ruleset)
    assert found and "own metadata" in found[0].detail


# ------------------------------------------------------------------- loading
def test_loading_a_directory_of_rule_files(tmp_path):
    (tmp_path / "order.json").write_text(json.dumps(
        {"rules": [{"rule": "a(-):b(-)", "direction": "before"}]}))
    (tmp_path / "incompatibilities.json").write_text(json.dumps(
        {"rules": [{"rule": "c(-):d(-)", "severity": "error"}]}))
    ruleset = RuleSet.load([str(tmp_path)])
    assert len(ruleset) == 2
    assert {r.kind for r in ruleset.rules} == {ORDER, INCOMPATIBLE}


def test_the_kind_is_taken_from_the_filename(tmp_path):
    path = tmp_path / "dependencies.json"
    path.write_text(json.dumps({"rules": [{"rule": "a(-):b(-)"}]}))
    assert RuleSet.load_file(str(path)).rules[0].kind == DEPENDS


def test_invalid_json_is_a_configuration_error(tmp_path):
    path = tmp_path / "order.json"
    path.write_text("{oops")
    with pytest.raises(ConfigError, match="not valid JSON"):
        RuleSet.load_file(str(path))


def test_a_missing_rules_file_is_a_configuration_error(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        RuleSet.load_file(str(tmp_path / "nope.json"))


def test_findings_are_deduplicated_and_errors_come_first():
    install = Install.from_log(log(line("a", 0), line("b", 0)))
    ruleset = rules(ORDER, {"rule": "b(-):a(-)", "direction": "before",
                            "severity": "warning"})
    ruleset.rules.extend(rules(INCOMPATIBLE, {"rule": "a(-):b(-)",
                                              "severity": "error"}).rules)
    found = check(install, ruleset)
    assert [f.severity for f in found] == ["error", "warning"]


# =========================== rule staleness ===========================
from iemod_fetch.rules import Context, load_suppressions        # noqa: E402


class FakeDB:
    def __init__(self, versions):
        self.versions = {k.lower(): v for k, v in versions.items()}

    def get(self, key):
        value = self.versions.get(key.lower())
        return type("R", (), {"version": value}) if value else None


def install_ab():
    return Install.from_log(log(line("infinity_ui", 0), line("hgo", 17)))


def incompat_rule():
    return rules(INCOMPATIBLE, {"rule": "infinity_ui(-):hgo(-)", "severity": "error"})


def test_a_rule_older_than_the_installed_mod_is_flagged_and_not_counted():
    """
    A rule carries no version qualifier. The only way to notice it predates a
    fix is to compare the installed version against the one the rules were
    built from.
    """
    context = Context(installed_versions={"hgo": "v5.2"},
                      baseline=FakeDB({"hgo": "5.0"}))
    found = check(install_ab(), incompat_rule(), context)
    assert len(found) == 1
    assert found[0].stale_risk
    assert "v5.2 installed, rules written against 5.0" in found[0].stale_risk
    assert found[0].blocking is False           # reported, but does not gate


def test_the_same_version_is_not_stale():
    context = Context(installed_versions={"hgo": "v5.0"},
                      baseline=FakeDB({"hgo": "5.0"}))
    assert check(install_ab(), incompat_rule(), context)[0].stale_risk == ""


def test_an_older_installed_version_is_not_stale():
    context = Context(installed_versions={"hgo": "v4.9"},
                      baseline=FakeDB({"hgo": "5.0"}))
    found = check(install_ab(), incompat_rule(), context)
    assert found[0].stale_risk == "" and found[0].blocking


def test_unrankable_versions_do_not_claim_staleness():
    context = Context(installed_versions={"hgo": "vEAOB.9"},
                      baseline=FakeDB({"hgo": "Alpha 3"}))
    assert check(install_ab(), incompat_rule(), context)[0].stale_risk == ""


def test_without_a_baseline_nothing_is_claimed():
    context = Context(installed_versions={"hgo": "v5.2"})
    assert check(install_ab(), incompat_rule(), context)[0].stale_risk == ""


# ------------------------------------------------------------- suppressions
def test_a_verified_suppression_withholds_the_finding():
    context = Context(suppressions=[{
        "mods": ["infinity_ui", "hgo"], "kind": INCOMPATIBLE,
        "reason": "fixed upstream", "verified_on": "2026-09-09"}])
    found = check(install_ab(), incompat_rule(), context)
    assert found[0].suppressed.startswith("fixed upstream")
    assert found[0].blocking is False


def test_a_suppression_for_other_mods_does_not_apply():
    context = Context(suppressions=[{"mods": ["a", "b"], "reason": "x"}])
    assert check(install_ab(), incompat_rule(), context)[0].suppressed == ""


def test_a_version_gated_suppression_waits_for_that_version():
    entry = {"mods": ["infinity_ui", "hgo"], "reason": "fixed in 6.0",
             "verified_version": {"hgo": "6.0"}}
    old = Context(installed_versions={"hgo": "v5.2"}, suppressions=[entry])
    assert check(install_ab(), incompat_rule(), old)[0].suppressed == ""

    new = Context(installed_versions={"hgo": "v6.1"}, suppressions=[entry])
    assert check(install_ab(), incompat_rule(), new)[0].suppressed


def test_loading_suppressions(tmp_path):
    path = tmp_path / "suppress.json"
    path.write_text(json.dumps({"suppressions": [{"mods": ["a"], "reason": "r"}]}))
    assert load_suppressions(str(path))[0]["reason"] == "r"


def test_a_malformed_suppression_file_is_a_configuration_error(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{nope")
    with pytest.raises(ConfigError):
        load_suppressions(str(path))


# ------------------------------------------- the mod's own ini wins on ordering
def test_a_mod_shipping_its_own_ini_overrides_community_ordering():
    """
    The ini travels with the version you downloaded, so it cannot be stale about
    itself. This is the only channel that updates when a developer fixes things.
    """
    install = Install.from_log(log(line("cdtweaks", 1), line("stratagems", 0)))
    ruleset = rules(ORDER, {"rule": "stratagems(-):cdtweaks(-)",
                            "direction": "before", "severity": "warning"})
    assert check(install, ruleset) != []          # community rule fires

    context = Context(mods_with_own_ini={"stratagems"})
    assert check(install, ruleset, context) == []  # the mod's own ini governs


def test_ini_precedence_does_not_touch_incompatibility_rules():
    """Mod inis only express ordering, so they cannot retire a conflict rule."""
    context = Context(mods_with_own_ini={"infinity_ui"})
    assert check(install_ab(), incompat_rule(), context) != []


# ======================= the krion64 per-mod rule format =======================
def krion(**overrides):
    record = {"t": "stratagems", "n": "Sword Coast Stratagems", "v": "35.21",
              "ord": 10, "conflicts": [], "dependencies": []}
    record.update(overrides)
    return record


def krion_ruleset(tmp_path, record, name="stratagems.json"):
    (tmp_path / name).write_text(json.dumps(record))
    return RuleSet.load([str(tmp_path)])


def test_the_krion_format_is_detected_and_loaded(tmp_path):
    ruleset = krion_ruleset(tmp_path, krion(conflicts=[
        {"with": "d5_refinements", "severity": "hard", "reason": "clash",
         "myComps": "#1500 #1510 spells", "theirComps": "#10 revised HLAs"}]))
    assert len(ruleset) == 1
    rule = ruleset.rules[0]
    assert rule.kind == INCOMPATIBLE and rule.severity == "error"
    assert rule.left.components == frozenset({1500, 1510})
    assert rule.right[0].components == frozenset({10})


def test_component_numbers_are_read_out_of_the_free_text(tmp_path):
    ruleset = krion_ruleset(tmp_path, krion(conflicts=[
        {"with": "bg1re", "severity": "soft", "reason": "overlap",
         "myComps": "#2 Ramazith, #48 Ender Sai, #51 Mini-Quest",
         "theirComps": "#2 Ramazith"}]))
    assert ruleset.rules[0].left.components == frozenset({2, 48, 51})


def test_a_conflict_with_no_component_text_applies_to_any_component(tmp_path):
    ruleset = krion_ruleset(tmp_path, krion(conflicts=[
        {"with": "cdtweaks", "severity": "hard", "reason": "whole mod"}]))
    assert ruleset.rules[0].left.components is None


@pytest.mark.parametrize("severity,expected", [
    ("hard", "error"), ("partial", "warning"), ("soft", "warning"), (None, "warning"),
])
def test_krion_conflict_severity_mapping(tmp_path, severity, expected):
    ruleset = krion_ruleset(tmp_path, krion(conflicts=[
        {"with": "x", "severity": severity, "reason": "r"}]))
    assert ruleset.rules[0].severity == expected


def test_the_evidence_level_is_carried_into_the_message(tmp_path):
    ruleset = krion_ruleset(tmp_path, krion(conflicts=[
        {"with": "x", "severity": "hard", "reason": "they clash",
         "evidenceLevel": "mechanism-verified"}]))
    assert "mechanism-verified" in ruleset.rules[0].message


def test_an_order_sensitive_pair_with_no_direction_is_counted_not_invented(tmp_path):
    """
    375 real entries say "these two are order-sensitive" without saying which
    way round. Inventing a direction would manufacture violations.
    """
    ruleset = krion_ruleset(tmp_path, krion(conflicts=[
        {"with": "x", "severity": "soft", "reason": "r", "orderOnly": True}]))
    assert len(ruleset) == 0 and ruleset.undirected == 1


def test_an_order_sensitive_pair_with_a_direction_becomes_an_order_rule(tmp_path):
    ruleset = krion_ruleset(tmp_path, krion(conflicts=[
        {"with": "x", "severity": "soft", "reason": "r",
         "orderOnly": True, "before": True}]))
    assert ruleset.rules[0].kind == ORDER and ruleset.rules[0].direction == "before"


# ------------------------------------------------- hard vs optional dependencies
def test_a_hard_dependency_is_a_requirement(tmp_path):
    ruleset = krion_ruleset(tmp_path, krion(dependencies=[
        {"requires": "ascension", "type": "hard", "reason": "needed"}]))
    install = Install.from_log(log(line("stratagems", 0)))
    found = check(install, ruleset)
    assert found and found[0].blocking and "needs" in found[0].summary


def test_optional_integrations_are_not_reported_by_default(tmp_path):
    """
    "Alternate portraits for X" is an enhancement. Eleven of those buried the
    one real missing prerequisite in the first run against real data.
    """
    ruleset = krion_ruleset(tmp_path, krion(dependencies=[
        {"requires": "BG1NPC", "type": "soft", "reason": "Alternate Portraits"}]))
    install = Install.from_log(log(line("stratagems", 0)))
    assert check(install, ruleset) == []


def test_optional_integrations_can_be_asked_for(tmp_path):
    ruleset = krion_ruleset(tmp_path, krion(dependencies=[
        {"requires": "BG1NPC", "type": "soft", "reason": "Alternate Portraits"}]))
    install = Install.from_log(log(line("stratagems", 0)))
    found = check(install, ruleset, Context(include_optional=True))
    assert found and "can also integrate with" in found[0].summary
    assert not found[0].blocking or found[0].severity == "warning"


def test_both_rule_formats_can_be_loaded_together(tmp_path):
    bws = tmp_path / "bws"
    bws.mkdir()
    (bws / "order.json").write_text(json.dumps(
        {"rules": [{"rule": "a(-):b(-)", "direction": "before"}]}))
    krion_dir = tmp_path / "krion"
    krion_dir.mkdir()
    (krion_dir / "stratagems.json").write_text(json.dumps(krion(conflicts=[
        {"with": "x", "severity": "hard", "reason": "r"}])))
    ruleset = RuleSet.load([str(bws), str(krion_dir)])
    assert len(ruleset) == 2


def test_catalog_and_index_files_are_not_read_as_mods(tmp_path):
    (tmp_path / "_catalog.json").write_text(json.dumps({"3": "DlcMerger.json"}))
    (tmp_path / "stratagems.json").write_text(json.dumps(krion()))
    assert len(RuleSet.load([str(tmp_path)])) == 0      # neither yields a rule
