"""
The fixes the order page offers a red row (GUI-AUDIT M5b item 32): a move of
that row alone that mends its rule and breaks no other, and the planner's
preview of a hand order or selection, written nowhere - what turning a row
off or planning it again would give, with the errors it adds.
"""
import json
import os

from iemod_fetch import api
from iemod_fetch.ordering import broken_pairs, order_fixes

from test_selection_plan import CHOSEN, plan

MOCK_RULES = os.path.join(os.path.dirname(__file__), "data", "eetmock", "rules")


def test_a_row_above_what_must_come_first_goes_just_after_it():
    before = {"c": {"a"}}
    fixes = order_fixes(["c", "a", "b"], before, "c")
    assert [(f.kind, f.anchor, f.order) for f in fixes] == [("after", "a", ("a", "c", "b"))]
    assert fixes[0].fixed == {("c", "a")} and not fixes[0].breaks


def test_a_row_below_what_must_follow_it_goes_just_before_it():
    before = {"b": {"c"}}
    fixes = order_fixes(["a", "b", "c"], before, "c")
    assert [(f.kind, f.anchor, f.order) for f in fixes] == [("before", "b", ("a", "c", "b"))]


def test_both_ends_of_a_broken_pair_are_offered_their_own_move():
    before = {"b": {"a"}}
    assert [f.order for f in order_fixes(["b", "a"], before, "b")] == [("a", "b")]
    assert [f.order for f in order_fixes(["b", "a"], before, "a")] == [("a", "b")]


def test_a_move_that_would_break_another_rule_is_not_offered():
    # c must follow a, and b must follow c: c just after a lands it below b
    before = {"c": {"a"}, "b": {"c"}}
    order = ["c", "b", "a"]
    assert broken_pairs(order, before) == {("c", "a")}
    assert order_fixes(order, before, "c") == []


def test_a_row_breaking_nothing_has_no_fix():
    assert order_fixes(["a", "b"], {"b": {"a"}}, "b") == []
    assert order_fixes(["a", "b"], {"b": {"a"}}, "x") == []


def test_the_api_gives_each_fix_as_plain_data():
    fixes = api.order_fixes(["c", "a", "b"], {"c": ["a"]}, "c")
    assert fixes == [{"kind": "after", "anchor": "a", "order": ["a", "c", "b"],
                      "fixed": [("c", "a")], "left": []}]


# ------------------------------------------------- the planner's preview
def preview(folder, chosen=CHOSEN, phases=None, rules=None):
    return api.preview_install_order(
        "EET", chosen, folder=str(folder), phases=phases,
        rules=rules or [MOCK_RULES],
        target=os.path.join(os.path.dirname(__file__), "data", "eetmock", "Mods"),
        order_catalogue=os.path.join(os.path.dirname(__file__), "data", "krion"),
        data_dir=str(folder / "no-cache"))


def test_a_preview_of_the_computed_order_is_the_plan_and_writes_nothing(tmp_path):
    shown = preview(tmp_path)
    planned = plan(tmp_path)
    assert {k: v for k, v in shown.items() if k != "errors"} == planned
    assert not os.listdir(tmp_path) or os.listdir(tmp_path) == ["no-cache"]


def test_a_preview_of_a_hand_order_applies_it_without_saving_it(tmp_path):
    phases = [p["units"] for p in plan(tmp_path)["phases"]]
    eet = phases[1]
    last = eet.pop()
    eet.insert(1, last)
    shown = preview(tmp_path, phases=phases)
    assert shown["custom"]
    assert not (tmp_path / api.INSTALL_ORDER_FILE).exists()
    assert not plan(tmp_path)["custom"]


def test_a_preview_names_the_errors_dropping_a_component_adds(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "dependencies.json").write_text(json.dumps({"rules": [
        {"rule": "ascension(-):ub(-)", "severity": "error"}]}))
    rule_dirs = [MOCK_RULES, str(rules)]
    base = preview(tmp_path, rules=rule_dirs)
    without = [key for key in CHOSEN if not key[0].lower().startswith("ub/")]
    dropped = preview(tmp_path, chosen=without, rules=rule_dirs)
    new = set(dropped["errors"]) - set(base["errors"])
    assert len(new) == 1 and "ub" in next(iter(new)).lower()
    # the community incompatibility of the mock is there either way
    assert set(base["errors"]) <= set(dropped["errors"])
