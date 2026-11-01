"""
Component-level install order (ADR-0023).

A mod is not one thing: `stratagems #4000` and `stratagems #5900` can belong at
opposite ends of an install. The load-bearing claims:

* "A before B" means EVERY installed component of A precedes EVERY installed
  component of B - the checker used to compare only the first component of
  each, so a split mod could pass while half of it sat on the wrong side;
* the planner splits a mod's components across the order only where a
  component-level rule requires it, keeps each part's components in their
  original order, and leaves a mod with no such rule exactly as it was;
* a rule between two components of the SAME mod is satisfied by reordering them;
* the plan still contains exactly the input lines, and is re-verified.
"""
import json
import os

import pytest

from iemod_fetch.ordering import EET_LOG, OrderIndex, plan_order
from iemod_fetch.rules import ORDER, Install, RuleSet, check
from iemod_fetch.weidu import parse_weidu_log

HERE = os.path.dirname(__file__)
KRION = os.path.join(HERE, "data", "krion")
HEADER = "// Log of Currently Installed WeiDU Mods\n"


def line(folder, comp, tp2=None):
    return f"~{folder}\\{tp2 or folder}.tp2~ #0 #{comp} // c{comp}"


def install(*lines):
    return Install.from_log(parse_weidu_log("\n".join(lines) + "\n"))


def order_rules(*entries):
    return RuleSet.from_mapping({"rules": list(entries)}, ORDER, "test")


@pytest.fixture
def index():
    return OrderIndex.load(KRION)


def planned(tmp_path, index, lines, rules):
    path = tmp_path / "WeiDU.log"
    path.write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    ruleset = RuleSet.load([str(rules)]) if not isinstance(rules, RuleSet) else rules
    plan = plan_order([(str(path), EET_LOG)], index, ruleset)
    return plan, [(entry.split("~")[1].split("\\")[0], int(entry.split("#")[2].split()[0]))
                  for u in plan.logs[EET_LOG] for entry in u.render()]


def write_rules(tmp_path, entries):
    path = tmp_path / "order.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


# ----------------------------------------------------------------- checking
def test_a_split_mod_with_a_component_on_the_wrong_side_is_reported():
    """A#1 before B, A#2 after B: 'A before B' is violated by A#2."""
    found = check(install(line("a", 1), line("b", 0), line("a", 2)),
                  order_rules({"rule": "a(-):b(-)", "direction": "before"}))
    assert len(found) == 1 and found[0].kind == ORDER


def test_a_component_rule_judges_only_the_components_it_names():
    """'a(1) before b' holds even though a#2 comes after b."""
    found = check(install(line("a", 1), line("b", 0), line("a", 2)),
                  order_rules({"rule": "a(1):b(-)", "direction": "before"}))
    assert found == []


def test_after_is_judged_on_every_component_too():
    found = check(install(line("b", 0), line("a", 1), line("b", 5)),
                  order_rules({"rule": "a(-):b(-)", "direction": "after"}))
    assert len(found) == 1


# ----------------------------------------------------------------- planning
def test_a_mod_is_split_only_where_a_component_rule_requires_it(tmp_path, index):
    """stratagems #4000 must precede cdtweaks; stratagems #5900 must follow it."""
    rules = write_rules(tmp_path, [
        {"rule": "stratagems(4000):cdtweaks(-)", "direction": "before"},
        {"rule": "stratagems(5900):cdtweaks(-)", "direction": "after"},
    ])
    plan, order = planned(tmp_path, index, [
        line("cdtweaks", 10), line("stratagems", 4000), line("stratagems", 5900),
    ], rules)
    assert order == [("stratagems", 4000), ("cdtweaks", 10), ("stratagems", 5900)]
    assert plan.verified and not plan.cycles


def test_a_mod_without_component_rules_stays_in_one_piece(tmp_path, index):
    rules = write_rules(tmp_path, [{"rule": "stratagems(-):cdtweaks(-)",
                                    "direction": "before"}])
    plan, order = planned(tmp_path, index, [
        line("cdtweaks", 10), line("stratagems", 4000), line("stratagems", 5900),
    ], rules)
    assert order == [("stratagems", 4000), ("stratagems", 5900), ("cdtweaks", 10)]
    assert len(plan.logs[EET_LOG]) == 2                      # two units, not three


def test_the_parts_of_a_split_mod_keep_their_own_order(tmp_path, index):
    rules = write_rules(tmp_path, [{"rule": "stratagems(5900):cdtweaks(-)",
                                    "direction": "after"}])
    _plan, order = planned(tmp_path, index, [
        line("stratagems", 1000), line("stratagems", 2000),
        line("stratagems", 5900), line("cdtweaks", 10),
    ], rules)
    at = {entry: i for i, entry in enumerate(order)}
    assert at[("stratagems", 1000)] < at[("stratagems", 2000)] < at[("stratagems", 5900)]
    assert at[("cdtweaks", 10)] < at[("stratagems", 5900)]


def test_a_same_mod_component_rule_is_satisfied_by_reordering(tmp_path, index):
    rules = write_rules(tmp_path, [{"rule": "cdtweaks(200):cdtweaks(100)",
                                    "direction": "before"}])
    plan, order = planned(tmp_path, index, [
        line("cdtweaks", 100), line("cdtweaks", 200), line("cdtweaks", 300),
    ], rules)
    assert order.index(("cdtweaks", 200)) < order.index(("cdtweaks", 100))
    assert plan.verified


def test_splitting_never_invents_or_drops_a_line(tmp_path, index):
    lines = [line("cdtweaks", 10), line("stratagems", 4000),
             line("cdtweaks", 20), line("stratagems", 5900), line("eefixpack", 0)]
    rules = write_rules(tmp_path, [
        {"rule": "stratagems(4000):cdtweaks(-)", "direction": "before"},
        {"rule": "stratagems(5900):cdtweaks(20)", "direction": "after"},
    ])
    plan, _order = planned(tmp_path, index, lines, rules)
    rendered = [entry for u in plan.logs[EET_LOG] for entry in u.render()]
    assert sorted(rendered) == sorted(lines)


def test_a_split_mod_is_named_by_its_parts_in_reports(tmp_path, index):
    rules = write_rules(tmp_path, [
        {"rule": "stratagems(4000):cdtweaks(-)", "direction": "before"},
        {"rule": "stratagems(5900):cdtweaks(-)", "direction": "after"},
    ])
    plan, _order = planned(tmp_path, index, [
        line("cdtweaks", 10), line("stratagems", 4000), line("stratagems", 5900),
    ], rules)
    names = [u.display for u in plan.logs[EET_LOG]]
    assert "stratagems #4000" in names and "stratagems #5900" in names


def test_the_catalogue_can_place_one_component_apart_from_its_mod(tmp_path):
    """krion64 files stratagems #4100 under POST EET while the mod sits in
    TACTICAL MODS; the component follows its own category, the rest stays."""
    data = tmp_path / "krion"
    (data / "mods").mkdir(parents=True)
    (data / "categories.json").write_text(json.dumps({"categories": {
        "TACTICAL MODS": {}, "TWEAKS": {}, "POST EET": {}}}))
    (data / "mods" / "stratagems.json").write_text(json.dumps({
        "t": "stratagems", "c": "TACTICAL MODS", "ord": 10,
        "co": [{"wf": "stratagems", "wp": "stratagems\\setup-stratagems.tp2"},
               {"cn": 4100, "cat": "POST EET"}]}))
    (data / "mods" / "cdtweaks.json").write_text(json.dumps({
        "t": "cdtweaks", "c": "TWEAKS", "ord": 5,
        "co": [{"wf": "cdtweaks", "wp": "cdtweaks\\setup-cdtweaks.tp2"}]}))
    index = OrderIndex.load(str(data))
    plan, order = planned(tmp_path, index, [
        line("stratagems", 4000, "setup-stratagems"), line("cdtweaks", 10, "setup-cdtweaks"),
        line("stratagems", 4100, "setup-stratagems"),
    ], RuleSet())
    assert order == [("stratagems", 4000), ("cdtweaks", 10), ("stratagems", 4100)]
    assert plan.moved == [] or all(m.display for m in plan.moved)
