"""
Phase 2's conflicts panel, driven like a player drives it (M3, GUI-AUDIT
item 16, ADR-0033). The checker is injected: it answers the way
api.selection_conflicts answers, from the selection it is given, so the tests
need no rules and no community data (test_selection_conflicts.py checks the
real one against the command line).
"""
import json

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QInputDialog, QLabel, QMessageBox  # noqa: E402

from iemod_fetch import api  # noqa: E402
from iemod_fetch_gui import text as qtext  # noqa: E402
from iemod_fetch_gui.pages.mods import CHECK_DELAY_MS, ModsPage  # noqa: E402

CHECK_WAIT_MS = CHECK_DELAY_MS + 300

UB = "bg1ub/setup-bg1ub.tp2"
TW = "cdtweaks/setup-cdtweaks.tp2"
NEED = "needed/setup-needed.tp2"


def component(number, name):
    return {"number": number, "name": name, "subgroup": "", "exclusive": "",
            "groups": [], "requires": [], "forced": False}


def tp2(path, numbers, name):
    key = path.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower().replace("setup-", "")
    return {"tp2": path, "origin": "krion64", "key": key.replace("_", ""),
            "components": [component(n, f"{name} {n}") for n in numbers]}


def mod(key, path, numbers, category="Tweaks"):
    return {"key": key, "name": key, "games": ["EET"], "categories": [category],
            "status": [], "advisories": [], "tp2s": [tp2(path, numbers, key)]}


EET, EET_END = "eet/EET.tp2", "eet/EET_end/EET_end.tp2"
MODS = [mod("bg1ub", UB, [0, 10]), mod("cdtweaks", TW, [100, 200]),
        mod("needed", NEED, [0]), mod("bystander", "bystander/b.tp2", [1]),
        {**mod("eet", EET, [0]), "tp2s": [tp2(EET, [0], "EET"), tp2(EET_END, [0], "EET_end")]}]


def option(oid, action, key, components, chosen=(), text=""):
    return {"id": oid, "action": action, "mod": key, "key": key,
            "components": list(components), "whole_mod": False, "cost": len(components),
            "applicable": action != "install", "recommended": False,
            "description": text or f"{action} {key}", "chosen": [list(c) for c in chosen]}


def side(key, numbers, chosen):
    return {"mod": key, "components": list(numbers), "whole_mod": False, "key": key,
            "chosen": [list(c) for c in chosen]}


class Checker:
    """api.selection_conflicts' answers for this little catalogue."""

    def __init__(self):
        self.calls = 0

    def __call__(self, game, chosen, labels, project_dir):
        self.calls += 1
        decided = api.load_decisions(project_dir)
        findings = []
        if (UB, 10) in chosen and (TW, 200) in chosen:
            findings.append({
                "id": "conflict-0000000000000001", "kind": "incompatible",
                "severity": "error", "fixed_by_plan": None, "evidence": "",
                "reason": "<b>both</b> patch the same file", "workaround": "",
                "left": side("bg1ub", [10], [(UB, 10)]),
                "right": side("cdtweaks", [200], [(TW, 200)]),
                "options": [option("option-000000000000000a", "deselect", "cdtweaks",
                                   [200], [(TW, 200)]),
                            option("option-000000000000000b", "deselect", "bg1ub",
                                   [10], [(UB, 10)])]})
        if (TW, 100) in chosen:
            findings.append({
                "id": "conflict-0000000000000002", "kind": "depends",
                "severity": "error", "fixed_by_plan": None, "evidence": "",
                "reason": "needs it", "workaround": "",
                "left": side("cdtweaks", [100], [(TW, 100)]),
                "right": side("needed", [0], []),
                "options": [option("option-000000000000000c", "install", "needed", [0]),
                            option("option-000000000000000d", "install", "absent", [5]),
                            option("option-000000000000000e", "reorder", "cdtweaks", [],
                                   text="install needed before cdtweaks")]})
        for finding in findings:
            fid = finding["id"]
            finding["decision"] = ({"choose": decided["choose"][fid]}
                                   if fid in decided["choose"] else
                                   {"accept": decided["accept"][fid]}
                                   if fid in decided["accept"] else None)
        known = {f["id"] for f in findings}
        stale = sorted((set(decided["choose"]) | set(decided["accept"])) - known)
        return {"findings": findings, "stale": stale, "rules_checked": 2, "planned": True,
                "problem": decided["problem"]}


def page(qtbot, folder, checker=None):
    checker = checker or Checker()
    widget = ModsPage(str(folder), load=lambda game, project: json.loads(json.dumps(MODS)),
                      check=checker)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.checked, timeout=5000):
        widget.start("EET")
    return widget, checker


def choose(qtbot, widget, *keys, on=True):
    with qtbot.waitSignal(widget.checked, timeout=5000):
        for key in keys:
            widget.items[key].setCheckState(
                0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)


def click(qtbot, widget, button_id):
    button = widget.panel.buttons[button_id]
    assert button.isEnabled()
    with qtbot.waitSignal(widget.checked, timeout=5000):
        button.click()


def open_ids(widget):
    return [f["id"] for f in widget.conflicts["findings"] if not f["decision"]]


def test_a_burst_of_choices_is_checked_once_after_it_ends(qtbot, tmp_path):
    widget, checker = page(qtbot, tmp_path)
    before = checker.calls
    choose(qtbot, widget, (UB, 10), (TW, 200))
    assert checker.calls == before + 1
    assert open_ids(widget) == ["conflict-0000000000000001"]
    assert widget.tabs.tabText(1) == "Conflicts (1)"


def test_deselecting_a_side_unchooses_it_and_clears_the_conflict(qtbot, tmp_path):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (UB, 10), (TW, 200))
    click(qtbot, widget, "option-000000000000000a")
    assert widget.chosen() == [(UB, 10)] and open_ids(widget) == []
    assert widget.tabs.tabText(1) == "Conflicts"


def test_a_missing_prerequisite_is_chosen_when_the_list_knows_it(qtbot, tmp_path):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (TW, 100))
    assert not widget.panel.buttons["option-000000000000000d"].isEnabled()   # not listed
    click(qtbot, widget, "option-000000000000000c")
    assert (NEED, 0) in widget.chosen()


def test_an_order_the_plan_could_not_settle_is_not_offered_as_a_choice(qtbot, tmp_path):
    # --decisions applies a reorder by sorting the plan, which already failed
    # for this finding: recording it would mark it settled and change nothing.
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (TW, 100))
    button = widget.panel.buttons["option-000000000000000e"]
    assert not button.isEnabled() and "could not" in button.toolTip()


class Overlap(Checker):
    """Finding 1 as a warning - two components touching one thing - with
    the "keep both" options a run gives such a finding (item 28)."""

    def __call__(self, *args):
        result = super().__call__(*args)
        for finding in result["findings"]:
            if finding["id"] == "conflict-0000000000000001":
                finding["severity"] = "warning"
                finding["options"].append(
                    option("option-00000000000000f1", "keep-both", "cdtweaks", [200],
                           text="keep both, cdtweaks installed last (its changes win)"))
        return result


def test_keeping_both_records_which_is_installed_last(qtbot, tmp_path):
    widget, _checker = page(qtbot, tmp_path, Overlap())
    choose(qtbot, widget, (UB, 10), (TW, 200))
    button = widget.panel.buttons["option-00000000000000f1"]
    assert "installed after the other" in button.toolTip()
    click(qtbot, widget, "option-00000000000000f1")
    assert api.load_decisions(str(tmp_path))["choose"] == {
        "conflict-0000000000000001": "option-00000000000000f1"}
    assert open_ids(widget) == []
    assert all(widget.items[key].checkState(0) == Qt.CheckState.Checked
               for key in ((UB, 10), (TW, 200)))          # both kept


def test_an_acceptance_is_shown_as_decided_and_can_be_undone(qtbot, tmp_path, monkeypatch):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (TW, 100))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("known", True))
    click(qtbot, widget, "accept:conflict-0000000000000002")
    assert open_ids(widget) == []
    assert "1 decided" in widget.panel.summary.text()
    undo = next(b for b in widget.panel.findChildren(type(widget.panel.again))
                if b.text() == "Undo")
    with qtbot.waitSignal(widget.checked, timeout=5000):
        undo.click()
    assert api.load_decisions(str(tmp_path))["accept"] == {}
    assert open_ids(widget) == ["conflict-0000000000000002"]


def test_accepting_asks_why_and_keeps_the_reason(qtbot, tmp_path, monkeypatch):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (TW, 100))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("tested it", True))
    click(qtbot, widget, "accept:conflict-0000000000000002")
    assert api.load_decisions(str(tmp_path))["accept"] == {
        "conflict-0000000000000002": "tested it"}


def test_an_unreadable_decisions_file_is_never_overwritten(qtbot, tmp_path, monkeypatch):
    (tmp_path / api.DECISIONS_FILE).write_text("{ hand-edited")
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (TW, 100))
    assert "could not be read" in " ".join(
        label.text() for label in widget.panel.findChildren(QLabel))
    shown = []
    monkeypatch.setattr(qtext, "critical", lambda *a: shown.append(a[1]))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("known", True))
    widget.panel.buttons["accept:conflict-0000000000000002"].click()
    assert shown == ["decisions.json cannot be read"]
    assert (tmp_path / api.DECISIONS_FILE).read_text() == "{ hand-edited"


def test_conflicts_only_shows_the_mods_still_to_decide(qtbot, tmp_path):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (UB, 10), (TW, 200))
    widget.filter.setCurrentText("Conflicts only")
    shown = [widget.tree.topLevelItem(i).text(0) for i in range(widget.tree.topLevelItemCount())
             if not widget.tree.topLevelItem(i).isHidden()]
    assert shown == ["bg1ub", "cdtweaks"]


def test_rule_text_is_shown_as_text_never_as_markup(qtbot, tmp_path):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (UB, 10), (TW, 200))
    labels = [label for label in widget.panel.findChildren(QLabel)
              if "patch the same file" in label.text()]
    assert labels and labels[0].textFormat() == Qt.TextFormat.PlainText
    assert labels[0].text() == "<b>both</b> patch the same file"


def test_a_failing_check_is_said_on_the_panel(qtbot, tmp_path):
    def broken(*_args):
        raise RuntimeError("rules unreadable")
    widget, _checker = page(qtbot, tmp_path, checker=broken)
    assert "rules unreadable" in widget.panel.summary.text()


def test_an_option_naming_eet_acts_on_eet_tp2_not_on_eet_end(qtbot, tmp_path):
    # Two tp2s in one folder, both with #0: the plan keys them `eet` and `eetend`.
    widget, _checker = page(qtbot, tmp_path)
    assert widget._can_choose("eet", [0]) and not widget._can_choose("eet", [0, 5])
    widget._choose_in("eet", [0])
    assert (EET, 0) in widget.chosen() and (EET_END, 0) not in widget.chosen()
    assert widget._can_choose("eetend", [0])


def test_a_check_of_the_previous_game_never_lands_on_the_next(qtbot, tmp_path):
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (UB, 10), (TW, 200))
    old = widget.conflicts
    widget.start("BG2EE")                     # the list for another game is loading
    assert widget.conflicts == {} and widget.panel.buttons == {}
    widget._check_done((widget._generation - 1, old, "", ""))
    assert widget.conflicts == {} and widget.panel.buttons == {}
    qtbot.waitUntil(lambda: widget._thread is None and widget._checking is None,
                    timeout=5000)


def test_a_failed_check_leaves_no_button_to_press(qtbot, tmp_path):
    calls = {"n": 0}
    good = Checker()

    def flaky(*args):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("rules unreadable")
        return good(*args)
    widget, _checker = page(qtbot, tmp_path, checker=flaky)
    choose(qtbot, widget, (UB, 10), (TW, 200))
    assert widget.panel.buttons == {} and "rules unreadable" in widget.panel.summary.text()


def test_the_result_is_shown_on_the_window_thread(qtbot, tmp_path):
    # A widget made on the worker's thread is the classic Qt crash; slots that
    # are not the page's own methods would run there.
    from PySide6.QtWidgets import QGroupBox
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (UB, 10), (TW, 200))
    rows = widget.panel.findChildren(QGroupBox)
    assert rows and all(row.thread() is widget.thread() for row in rows)


def test_no_check_runs_while_the_next_games_list_loads(qtbot, tmp_path):
    # The old list is still shown while the new one loads: checking it as the
    # new game would put the old list's buttons under the new game's name.
    import threading
    gate = threading.Event()
    checker = Checker()

    def load(game, project):
        if game == "BG2EE":
            gate.wait(5)
        return json.loads(json.dumps(MODS))
    widget = ModsPage(str(tmp_path), load=load, check=checker)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.checked, timeout=5000):
        widget.start("EET")
    choose(qtbot, widget, (UB, 10), (TW, 200))
    calls = checker.calls
    widget.start("BG2EE")
    widget.panel.again.click()
    widget.items[(UB, 0)].setCheckState(0, Qt.CheckState.Checked)
    qtbot.wait(CHECK_WAIT_MS)
    assert checker.calls == calls and widget.panel.buttons == {}
    assert widget.tabs.tabText(1) == "Conflicts"
    with qtbot.waitSignal(widget.checked, timeout=5000):
        gate.set()
    assert checker.calls == calls + 1       # the new list, once it is shown


def test_a_failed_check_resets_the_count_and_the_filter(qtbot, tmp_path):
    calls = {"n": 0}
    good = Checker()

    def flaky(*args):
        calls["n"] += 1
        if calls["n"] > 2:
            raise RuntimeError("rules unreadable")
        return good(*args)
    widget, _checker = page(qtbot, tmp_path, checker=flaky)
    choose(qtbot, widget, (UB, 10), (TW, 200))
    widget.filter.setCurrentText("Conflicts only")
    assert widget.tabs.tabText(1) == "Conflicts (1)"
    choose(qtbot, widget, (TW, 100))
    assert widget.tabs.tabText(1) == "Conflicts"
    assert all(widget.tree.topLevelItem(i).isHidden()
               for i in range(widget.tree.topLevelItemCount()))


def test_decisions_no_conflict_has_any_more_can_be_forgotten(qtbot, tmp_path, monkeypatch):
    # e.g. ids saved by an earlier build, or a conflict whose mod is gone
    api.save_decisions(str(tmp_path), {"conflict-00000000000000ff": "option-0000000000000001"},
                       {"conflict-0000000000000002": "known", "conflict-00000000000000fe": "old"})
    widget, _checker = page(qtbot, tmp_path)
    choose(qtbot, widget, (TW, 100))
    assert widget.conflicts["stale"] == ["conflict-00000000000000fe",
                                         "conflict-00000000000000ff"]
    asked = []
    monkeypatch.setattr(qtext, "question",
                        lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.No)
    widget.panel.buttons["forget:"].click()
    assert asked and "conflict-00000000000000ff" in asked[0]
    assert len(api.load_decisions(str(tmp_path))["accept"]) == 2     # No keeps them
    monkeypatch.setattr(qtext, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    click(qtbot, widget, "forget:")
    decided = api.load_decisions(str(tmp_path))
    assert decided["choose"] == {}
    assert decided["accept"] == {"conflict-0000000000000002": "known"}    # live one kept
    assert widget.conflicts["stale"] == [] and "forget:" not in widget.panel.buttons


def test_no_forget_button_while_decisions_json_cannot_be_read(qtbot, tmp_path):
    (tmp_path / api.DECISIONS_FILE).write_text("{ hand-edited")
    widget, _checker = page(qtbot, tmp_path)
    assert "forget:" not in widget.panel.buttons


def yes(monkeypatch):
    monkeypatch.setattr(qtext, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)


def test_a_decision_live_again_is_not_forgotten_by_the_old_button(qtbot, tmp_path,
                                                                  monkeypatch):
    api.save_decisions(str(tmp_path), accept={"conflict-0000000000000002": "known"})
    widget, _checker = page(qtbot, tmp_path)
    assert widget.conflicts["stale"] == ["conflict-0000000000000002"]   # cdtweaks unticked
    forget = widget.panel.buttons["forget:"]
    yes(monkeypatch)
    with qtbot.waitSignal(widget.checked, timeout=5000):
        widget.items[(TW, 100)].setCheckState(0, Qt.CheckState.Checked)  # live again
        forget.click()                  # the old result's button, before the check
    assert widget.conflicts["stale"] == []
    assert api.load_decisions(str(tmp_path))["accept"] == {"conflict-0000000000000002": "known"}


def test_a_check_ending_while_the_question_is_open_is_obeyed(qtbot, tmp_path, monkeypatch):
    api.save_decisions(str(tmp_path), accept={"conflict-0000000000000002": "known"})
    widget, _checker = page(qtbot, tmp_path)

    def question(*_args, **_kwargs):
        with qtbot.waitSignal(widget.checked, timeout=5000):
            widget.items[(TW, 100)].setCheckState(0, Qt.CheckState.Checked)
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(qtext, "question", question)
    widget.panel.buttons["forget:"].click()
    assert api.load_decisions(str(tmp_path))["accept"] == {"conflict-0000000000000002": "known"}


def test_with_no_rules_nothing_is_offered_to_forget(qtbot, tmp_path):
    api.save_decisions(str(tmp_path), accept={"conflict-0000000000000002": "known"})

    def no_rules(game, chosen, labels, project_dir):
        decided = api.load_decisions(project_dir)     # as an older api might answer
        return {"findings": [], "stale": sorted(decided["accept"]), "rules_checked": 0,
                "planned": False, "problem": None}
    widget, _checker = page(qtbot, tmp_path, checker=no_rules)
    assert "forget:" not in widget.panel.buttons
