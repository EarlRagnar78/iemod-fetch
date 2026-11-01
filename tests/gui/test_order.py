"""
Phase 3, install order, driven like a player drives it (M3, GUI-AUDIT item
17, ADR-0038). The planner is injected: it answers as api.selection_plan does,
and reads the order the page saved (test_selection_plan.py checks the real
one against the run's planner).
"""
import json
import os

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QModelIndex, Qt  # noqa: E402

from iemod_fetch import api  # noqa: E402
from iemod_fetch_gui import text as qtext  # noqa: E402
from iemod_fetch_gui.pages.order import GREY, RED, ROLE, OrderPage  # noqa: E402

PHASES = {"BG:EE before the conversion": ["bg1ub"],
          "EET": ["eet", "ub", "ascension", "EET_end"]}


def unit(name, constrained=False, flagged=False):
    return {"node": f"x|{name}|0", "name": name, "tp2": f"{name}/{name}.tp2",
            "key": name.lower(), "part": 0, "split": False, "category": "SOMEWHERE",
            "components": [[f"{name}/{name}.tp2", 0, ""]],
            "constrained": constrained, "moved": False, "flagged": flagged}


class Planner:
    """Plans by the saved order when there is one, else by PHASES; EET_end
    must stay last (a rule), so moving it away is a violation."""

    def __init__(self):
        self.calls = 0

    def __call__(self, game, chosen, labels, folder):
        self.calls += 1
        order = dict(PHASES)
        path = os.path.join(folder, api.INSTALL_ORDER_FILE)
        custom = os.path.isfile(path)
        if custom:
            with open(path, encoding="utf-8") as fh:
                names = [line.split()[0] for line in fh if line.strip()
                         and not line.startswith("//")]
            order = {"BG:EE before the conversion": [n for n in names if n == "bg1ub"],
                     "EET": [n for n in names if n != "bg1ub"]}
        broken = order["EET"][-1] != "EET_end"
        return {"phases": [{"role": title, "title": title, "units": [
                    unit(n, constrained=n == "EET_end", flagged=broken and n == "EET_end")
                    for n in names]} for title, names in order.items()],
                "cycles": [], "violations": ["EET_end should be installed last"] if broken
                else [], "planned": True, "custom": custom}


def page(qtbot, folder, planner=None):
    planner = planner or Planner()
    widget = OrderPage(str(folder), plan=planner)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.planned, timeout=5000):
        widget.start("EET", [("ub/ub.tp2", 0)], {})
    return widget, planner


def texts(widget, tab):
    view = widget.tabs.widget(tab)
    return [view.item(row).text().split("  -  ")[0] for row in range(view.count())]


def drag(qtbot, widget, tab, row, to):
    view = widget.tabs.widget(tab)
    with qtbot.waitSignal(widget.planned, timeout=5000):
        view.model().moveRow(QModelIndex(), row, QModelIndex(), to)


def test_each_eet_phase_is_a_tab_in_the_planned_order(qtbot, tmp_path):
    widget, _planner = page(qtbot, tmp_path)
    assert [widget.tabs.tabText(i) for i in range(widget.tabs.count())] == [
        "BG:EE before the conversion (1)", "EET (4)"]
    assert texts(widget, 1) == ["eet", "ub", "ascension", "EET_end"]
    assert widget.is_complete() and not widget.reset.isEnabled()


def test_a_rule_placed_mod_is_bold(qtbot, tmp_path):
    widget, _planner = page(qtbot, tmp_path)
    view = widget.tabs.widget(1)
    assert view.item(3).font().bold() and not view.item(1).font().bold()


def test_a_mod_its_kind_placed_says_so_and_one_it_could_not_says_why(qtbot, tmp_path):
    """Item 27: krion64 does not place newui or tweak; newui's kind decides."""
    def planner(game, chosen, labels, folder):
        units = [unit("eet"),
                 dict(unit("newui"), category="INTERFACE",
                      placed_by="placed by kind: interface, 92% / 100% (lcc-docs)"),
                 dict(unit("tweak"), category="",
                      no_place="no place: its kind does not decide one (gameplay)")]
        return {"phases": [{"role": "EET", "title": "EET", "units": units}],
                "cycles": [], "violations": [], "planned": True, "custom": False}
    widget, _planner = page(qtbot, tmp_path, planner)
    view = widget.tabs.widget(0)
    assert view.item(1).text() == "newui  -  INTERFACE  (by kind)"
    assert "placed by kind: interface, 92% / 100% (lcc-docs)" in view.item(1).toolTip()
    assert "does not decide one (gameplay)" in view.item(2).toolTip()
    assert "1 placed by kind" in widget.summary.text()


def test_a_mod_bws_ngs_sequence_placed_says_so(qtbot, tmp_path):
    """Decision 2a: BWS-NG's EET sequence placed it, before any kind."""
    def planner(game, chosen, labels, folder):
        units = [unit("eet"), dict(unit("allison"), category="NEW NPC MODS",
                                   placed_by="placed by BWS-NG's EET sequence: after alassa #0",
                                   placed_from="BWS-NG")]
        return {"phases": [{"role": "EET", "title": "EET", "units": units}],
                "cycles": [], "violations": [], "planned": True, "custom": False}
    widget, _planner = page(qtbot, tmp_path, planner)
    assert widget.tabs.widget(0).item(1).text() == "allison  -  NEW NPC MODS  (by BWS-NG)"
    assert "1 placed by BWS-NG's sequence" in widget.summary.text()
    assert "placed by kind" not in widget.summary.text()


def test_the_players_own_order_supersedes_a_place_by_kind(qtbot, tmp_path):
    """Review of #67 (L1): with install-order.txt the kind places nothing."""
    def planner(game, chosen, labels, folder):
        units = [unit("eet"), dict(unit("newui"), category="INTERFACE",
                                   placed_by="placed by kind: interface, 92% / 100%")]
        return {"phases": [{"role": "EET", "title": "EET", "units": units}],
                "cycles": [], "violations": [], "planned": True, "custom": True}
    widget, _planner = page(qtbot, tmp_path, planner)
    item = widget.tabs.widget(0).item(1)
    assert "(by kind)" not in item.text()
    assert "your own order applies" in item.toolTip()
    assert "placed by kind" not in widget.summary.text()


def test_a_mod_split_into_components_is_saved_one_line_each(qtbot, tmp_path):
    """M5b item 30: split a mod, then each component is a row of its own."""
    calls = []

    def planner(game, chosen, labels, folder):
        calls.append(1)
        tweaks = dict(unit("cdtweaks"), components=[["cdtweaks/cdtweaks.tp2", n, ""]
                                                     for n in (10, 20, 30)])
        return {"phases": [{"role": "EET", "title": "EET",
                            "units": [unit("eet"), tweaks, unit("stratagems")]}],
                "cycles": [], "violations": [], "planned": True, "custom": False}
    widget, _planner = page(qtbot, tmp_path, planner)
    view = widget.tabs.widget(0)
    view.setCurrentRow(0)
    assert not widget.split.isEnabled()              # one component: nothing to split
    view.setCurrentRow(1)
    assert widget.split.isEnabled()
    with qtbot.waitSignal(widget.planned, timeout=5000):
        widget.split.click()
    lines = (tmp_path / api.INSTALL_ORDER_FILE).read_text().splitlines()
    assert [line for line in lines if not line.startswith("//")] == [
        "eet *", "cdtweaks 10", "cdtweaks 20", "cdtweaks 30", "stratagems *"]
    assert len(calls) == 2                           # planned again


def test_dragging_saves_the_order_the_cli_reads_and_plans_again(qtbot, tmp_path):
    widget, planner = page(qtbot, tmp_path)
    calls = planner.calls
    drag(qtbot, widget, 1, 2, 1)                 # ascension above ub
    assert planner.calls == calls + 1
    saved = (tmp_path / api.INSTALL_ORDER_FILE).read_text()
    assert saved.index("\nascension *") < saved.index("\nub *")
    assert "sorting_order" in (tmp_path / api.PROJECT_FILE).read_text()
    assert texts(widget, 1) == ["eet", "ascension", "ub", "EET_end"]
    assert widget.reset.isEnabled() and "your own order applies" in widget.summary.text()


def test_an_order_that_breaks_a_rule_is_marked_red_with_the_rule(qtbot, tmp_path):
    widget, _planner = page(qtbot, tmp_path)
    drag(qtbot, widget, 1, 3, 0)                 # EET_end first
    view = widget.tabs.widget(1)
    flagged = next(view.item(r) for r in range(view.count()) if "EET_end" in view.item(r).text())
    assert flagged.foreground().color() == RED
    assert "EET_end should be installed last" in widget.problems.text()


def test_the_computed_order_can_be_used_again(qtbot, tmp_path):
    widget, _planner = page(qtbot, tmp_path)
    drag(qtbot, widget, 1, 2, 1)
    with qtbot.waitSignal(widget.planned, timeout=5000):
        widget.reset.click()
    assert not (tmp_path / api.INSTALL_ORDER_FILE).exists()
    assert texts(widget, 1) == ["eet", "ub", "ascension", "EET_end"]


def test_without_krion64s_data_the_phase_says_so_and_lets_you_go_on(qtbot, tmp_path):
    def unplanned(*_args):
        return {"phases": [], "cycles": [], "violations": [], "planned": False,
                "custom": False}
    widget, _planner = page(qtbot, tmp_path, planner=unplanned)
    assert "krion64's data is not here yet" in widget.summary.text()
    assert widget.is_complete() and widget.tabs.count() == 0


def test_a_failing_plan_is_said_and_blocks_next(qtbot, tmp_path):
    def broken(*_args):
        raise RuntimeError("no rules")
    widget, _planner = page(qtbot, tmp_path, planner=broken)
    assert "no rules" in widget.summary.text() and not widget.is_complete()


def test_an_order_that_cannot_be_saved_is_said(qtbot, tmp_path, monkeypatch):
    widget, planner = page(qtbot, tmp_path)
    shown = []
    monkeypatch.setattr(qtext, "critical", lambda *a: shown.append(a[1]))
    monkeypatch.setattr(api, "save_install_order",
                        lambda *a: (_ for _ in ()).throw(OSError("read-only")))
    calls = planner.calls
    widget.tabs.widget(1).model().moveRow(QModelIndex(), 2, QModelIndex(), 1)
    assert shown == ["Cannot save the install order"] and planner.calls == calls


def test_a_plan_for_a_previous_selection_never_lands(qtbot, tmp_path):
    widget, _planner = page(qtbot, tmp_path)
    old = widget._generation
    widget.start("EET", [("ub/ub.tp2", 0), ("ascension/ascension.tp2", 0)], {})
    widget._done((old, {"phases": [], "planned": True, "cycles": [], "violations": [],
                        "custom": False}, ""))
    qtbot.waitUntil(lambda: widget._planning is None, timeout=5000)
    assert widget.tabs.count() == 2


# --------------------------------------------- review follow-ups (#74)
def lines_of(folder):
    return [line for line in (folder / api.INSTALL_ORDER_FILE).read_text().splitlines()
            if not line.startswith("//")]


class Slow:
    """A planner that answers from the saved order, and waits for `gate`
    once it is set - as a plan fetching metadata may, for seconds."""

    def __init__(self):
        import threading
        self.gate = None
        self.event = threading.Event

    def __call__(self, game, chosen, labels, folder):
        if self.gate is not None:
            self.gate.wait(5)
        units = [unit("eet"),
                 dict(unit("cdtweaks"), components=[["cdtweaks/cdtweaks.tp2", n, ""]
                                                    for n in (10, 20, 30)]),
                 unit("stratagems")]
        return {"phases": [{"role": "EET", "title": "EET", "units": units}],
                "cycles": [], "violations": [], "planned": True, "custom": False}


def test_a_drag_while_the_plan_is_made_keeps_the_split(qtbot, tmp_path):
    """Review of #74 (blocking): the split is in the list at once, so a drag
    before the plan comes back saves it rather than the mod whole."""
    planner = Slow()
    widget, _planner = page(qtbot, tmp_path, planner)
    planner.gate = planner.event()
    view = widget.tabs.widget(0)
    view.setCurrentRow(1)
    widget.split.click()                             # the plan now waits on the gate
    assert [view.item(r).data(ROLE)["components"][0][1] for r in (1, 2, 3)] == [10, 20, 30]
    assert not widget.split.isEnabled() and not widget.join.isEnabled()
    view.model().moveRow(QModelIndex(), 4, QModelIndex(), 0)       # stratagems to the top
    assert lines_of(tmp_path) == ["stratagems *", "eet *", "cdtweaks 10", "cdtweaks 20",
                                  "cdtweaks 30"]
    with qtbot.waitSignal(widget.planned, timeout=5000):
        planner.gate.set()


def test_the_parts_of_a_split_mod_are_joined_again(qtbot, tmp_path):
    """Review of #74: one split undone, the other moves kept."""
    widget, _planner = page(qtbot, tmp_path, Slow())
    view = widget.tabs.widget(0)
    view.setCurrentRow(1)
    with qtbot.waitSignal(widget.planned, timeout=5000):
        widget.split.click()
    assert lines_of(tmp_path)[1:4] == ["cdtweaks 10", "cdtweaks 20", "cdtweaks 30"]
    # the Slow planner answers the mod whole again; put the parts back on screen
    view = widget.tabs.widget(0)                     # the plan rebuilt the tab
    view.takeItem(1)
    for offset, number in enumerate((10, 20, 30)):
        view.insertItem(1 + offset, widget._item(dict(
            unit("cdtweaks"), split=True, components=[["cdtweaks/cdtweaks.tp2", number, ""]])))
    view.setCurrentRow(0)
    view.setCurrentRow(2)
    assert widget.join.isEnabled()
    with qtbot.waitSignal(widget.planned, timeout=5000):
        widget.join.click()
    assert lines_of(tmp_path) == ["eet *", "cdtweaks *", "stratagems *"]


def test_split_and_drag_on_the_real_planner_agree_with_the_command_line(qtbot, tmp_path):
    """Review of #74 (acceptance on the real path): the run's own planner,
    Split on eefixpack, its #1 dragged just after the EET core, then
    --plan-order with the same selection and order - row for row."""
    here = os.path.join(os.path.dirname(__file__), os.pardir)
    mock = os.path.join(here, "data", "eetmock")
    krion = os.path.join(here, "data", "krion")
    from test_selection_plan import CHOSEN

    def real(game, chosen, labels, folder):
        return api.selection_plan(game, chosen, labels, folder=folder,
                                  order_catalogue=krion, rules=[os.path.join(mock, "rules")],
                                  target=os.path.join(mock, "Mods"),
                                  data_dir=os.path.join(folder, "no-cache"))
    widget = OrderPage(str(tmp_path), plan=real)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.planned, timeout=10000):
        widget.start("EET", CHOSEN, {})
    widget.tabs.setCurrentIndex(1)
    view = widget.tabs.widget(1)
    rows = lambda: [view.item(r).data(ROLE) for r in range(view.count())]  # noqa: E731
    view.setCurrentRow(next(r for r, u in enumerate(rows()) if u["key"] == "eefixpack"))
    with qtbot.waitSignal(widget.planned, timeout=10000):
        widget.split.click()
    view = widget.tabs.widget(1)
    source = next(r for r, u in enumerate(rows()) if u["key"] == "eefixpack"
                  and u["components"][0][1] == 1)
    core = next(r for r, u in enumerate(rows()) if u["key"] == "eet")
    with qtbot.waitSignal(widget.planned, timeout=10000):
        view.model().moveRow(QModelIndex(), source, QModelIndex(), core + 1)
    view = widget.tabs.widget(1)
    page_order = [(c[0].split("/")[0].lower(), c[1]) for u in rows() for c in u["components"]]
    assert page_order.index(("eefixpack", 1)) == page_order.index(("eet", 0)) + 1

    api.save_selection(str(tmp_path), "EET", CHOSEN, order_catalogue=krion)
    api.run(api.Settings(
        selection=str(tmp_path / api.SELECTION_FILE),
        sorting_order=str(tmp_path / api.INSTALL_ORDER_FILE),
        check_only=True, quiet=True, manifest=os.path.join(here, "data", "mod_downloads.json"),
        target=os.path.join(mock, "Mods"), rules=[os.path.join(mock, "rules")],
        order_catalogue=krion, plan_order=str(tmp_path / "plan"),
        data_dir=str(tmp_path / "no-cache"), no_update_data=True, no_default_data=True))
    written = [(line[1:].split("\\")[0].lower(), int(line.split("#")[2].split()[0]))
               for line in (tmp_path / "plan" / "WeiDU.log").read_text().splitlines()
               if line.startswith("~")]
    assert written == page_order


# ---------------------------------------- the check after a drop (item 31)
def test_a_drop_is_checked_at_once_before_the_plan_comes_back(qtbot, tmp_path):
    """M5b item 31: dragging stratagems above cdtweaks, which a rule puts
    first, marks both red at once - the plan is still being made."""
    import threading
    gate = threading.Event()
    calls = []

    def planner(game, chosen, labels, folder):
        if calls:
            gate.wait(5)
        calls.append(1)
        units = [unit("eet"), unit("cdtweaks"),
                 dict(unit("stratagems"), after=["x|cdtweaks|0"])]
        return {"phases": [{"role": "EET", "title": "EET", "units": units}],
                "cycles": [], "violations": [], "planned": True, "custom": False}
    widget, _planner = page(qtbot, tmp_path, planner)
    view = widget.tabs.widget(0)
    assert view.item(2).foreground().color() != RED
    view.model().moveRow(QModelIndex(), 2, QModelIndex(), 1)      # stratagems up one
    assert [view.item(r).data(ROLE)["name"] for r in range(3)] == [
        "eet", "stratagems", "cdtweaks"]
    assert view.item(1).foreground().color() == RED
    assert view.item(2).foreground().color() == RED
    assert view.item(0).foreground().color() != RED
    assert "1 rule(s) broken" in widget.problems.text()
    assert widget.last_check_ms < 100
    with qtbot.waitSignal(widget.planned, timeout=5000):
        gate.set()


def test_a_drop_downward_marks_the_row_it_moved(qtbot, tmp_path):
    """Review of #75: a row dropped lower lands one above the row Qt names,
    and that is the row checked - cdtweaks below stratagems breaks the rule."""
    import threading
    gate = threading.Event()
    calls = []

    def planner(game, chosen, labels, folder):
        if calls:
            gate.wait(5)
        calls.append(1)
        units = [unit("eet"), unit("cdtweaks"),
                 dict(unit("stratagems"), after=["x|cdtweaks|0"]), unit("eet_end")]
        return {"phases": [{"role": "EET", "title": "EET", "units": units}],
                "cycles": [], "violations": [], "planned": True, "custom": False}
    widget, _planner = page(qtbot, tmp_path, planner)
    view = widget.tabs.widget(0)
    view.model().moveRow(QModelIndex(), 1, QModelIndex(), 3)      # cdtweaks down one
    assert [view.item(r).data(ROLE)["name"] for r in range(4)] == [
        "eet", "stratagems", "cdtweaks", "eet_end"]
    assert [view.item(r).foreground().color() == RED for r in range(4)] == [
        False, True, True, False]
    assert "1 rule(s) broken" in widget.problems.text()
    with qtbot.waitSignal(widget.planned, timeout=5000):
        gate.set()


def test_a_drag_after_a_split_leaves_the_marks_to_the_plan(qtbot, tmp_path):
    """Review of #75: until the plan comes back, a split mod's parts share
    its node, so a drop is not checked at once - no row is marked by a
    guess, and the plan that follows marks them."""
    planner = Slow()
    widget, _planner = page(qtbot, tmp_path, planner)
    planner.gate = planner.event()
    view = widget.tabs.widget(0)
    view.setCurrentRow(1)
    widget.split.click()
    view.model().moveRow(QModelIndex(), 1, QModelIndex(), 5)       # a part to the end
    assert widget.problems.text() == "Checked when the plan comes back."
    assert not any(view.item(r).foreground().color() == RED for r in range(view.count()))
    with qtbot.waitSignal(widget.planned, timeout=5000):
        planner.gate.set()


# ------------------------------------------------------ fixes (item 32)
ALL = [(f"{n}/{n}.tp2", 0) for n in ("bg1ub", "eet", "ub", "ascension", "EET_end")]


class Ruled(Planner):
    """Planner, with the rule as edges: EET_end after every other EET mod; a
    hand order without EET_end leaves it to the rule, last."""

    def __call__(self, game, chosen, labels, folder):
        result = super().__call__(game, chosen, labels, folder)
        eet = result["phases"][-1]["units"]
        if not any(u["name"] == "EET_end" for u in eet):
            eet.append(unit("EET_end", constrained=True))
        present = {tp2 for tp2, _n in chosen}
        for phase in result["phases"]:
            phase["units"] = [u for u in phase["units"] if u["tp2"] in present]
        eet = result["phases"][-1]["units"]
        for u in eet:
            if u["name"] == "EET_end":
                u["after"] = [o["node"] for o in eet if o is not u]
        return result


class Preview:
    """api.preview_install_order's answer, from Ruled; turning EET_end off
    adds `error` when there is one."""

    def __init__(self, error=""):
        self.error, self.calls = error, []

    def __call__(self, game, chosen, labels, folder, phases):
        import tempfile
        self.calls.append((list(chosen), phases))
        with tempfile.TemporaryDirectory() as scratch:
            if phases is not None:
                api.save_install_order(scratch, phases)
            result = Ruled()(game, chosen, labels, scratch)
        gone = ("EET_end/EET_end.tp2", 0) not in chosen
        result["errors"] = [self.error] if self.error and gone else []
        return result


def fixing(qtbot, folder, preview):
    widget = OrderPage(str(folder), plan=Ruled(), preview=preview)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.planned, timeout=5000):
        widget.start("EET", ALL, {})
    widget.tabs.setCurrentIndex(1)
    view = widget.tabs.widget(1)
    with qtbot.waitSignal(widget.planned, timeout=5000):
        view.model().moveRow(QModelIndex(), 3, QModelIndex(), 1)    # EET_end up
    assert texts(widget, 1) == ["eet", "EET_end", "ub", "ascension"]
    view = widget.tabs.widget(1)                    # the plan's list, made again
    view.setCurrentRow(1)
    assert widget.fix.isEnabled()
    return widget, view


def opened(qtbot, widget):
    widget.fix.click()
    dialog = widget.fixing
    planner_fixes = [f for f in dialog.fixes if f["kind"] in ("replan", "off")]
    qtbot.waitUntil(lambda: not any(f["preview"].startswith("Previewing")
                                    for f in planner_fixes), timeout=5000)
    return dialog


def test_fix_is_offered_only_on_a_red_row(qtbot, tmp_path):
    widget, view = fixing(qtbot, tmp_path, Preview())
    view.setCurrentRow(0)
    assert not widget.fix.isEnabled()


def test_a_move_fix_puts_the_row_just_after_what_must_come_first(qtbot, tmp_path):
    widget, _view = fixing(qtbot, tmp_path, Preview())
    dialog = opened(qtbot, widget)
    assert [f["kind"] for f in dialog.fixes] == ["after", "replan", "off"]
    assert dialog.options.item(0).text() == "Move it just after ascension"
    assert "2 rule(s) mended, none broken" in dialog.preview.text()   # ub, ascension
    assert dialog.apply.isEnabled()
    with qtbot.waitSignal(widget.planned, timeout=5000):
        dialog.apply.click()
    assert texts(widget, 1) == ["eet", "ub", "ascension", "EET_end"]
    assert lines_of(tmp_path)[-1] == "EET_end *"
    assert widget.problems.text() == ""


def test_planning_the_row_again_keeps_the_other_moves(qtbot, tmp_path):
    widget, view = fixing(qtbot, tmp_path, Preview())
    with qtbot.waitSignal(widget.planned, timeout=5000):
        view.model().moveRow(QModelIndex(), 3, QModelIndex(), 2)    # ascension above ub
    widget.tabs.widget(1).setCurrentRow(1)
    dialog = opened(qtbot, widget)
    dialog.options.setCurrentRow(1)
    assert "EET_end would go after ub (EET, row 4 of 4)" in dialog.preview.text()
    assert "breaks nothing else" in dialog.preview.text()
    with qtbot.waitSignal(widget.planned, timeout=5000):
        dialog.apply.click()
    assert lines_of(tmp_path) == ["bg1ub *", "eet *", "ascension *", "ub *"]
    assert texts(widget, 1) == ["eet", "ascension", "ub", "EET_end"]


def test_turning_off_what_another_needs_is_previewed_and_not_applied(qtbot, tmp_path):
    preview = Preview(error="ascension needs EET_end, which is not installed")
    widget, _view = fixing(qtbot, tmp_path, preview)
    emitted = []
    widget.turn_off.connect(emitted.append)
    dialog = opened(qtbot, widget)
    dialog.options.setCurrentRow(2)
    assert "New error: ascension needs EET_end" in dialog.preview.text()
    assert not dialog.apply.isEnabled()
    off = [chosen for chosen, _phases in preview.calls
           if ("EET_end/EET_end.tp2", 0) not in chosen]
    assert off == [ALL[:-1]]
    dialog.accept()                                 # what is not ok is never applied
    assert emitted == []


class Worse(Preview):
    """Preview, but a plan without EET_end's line - planned again or turned
    off - leaves it red (`still`) or breaks another rule (`broken`)."""

    def __init__(self, still=False, broken=""):
        super().__init__()
        self.still, self.broken = still, broken

    def __call__(self, game, chosen, labels, folder, phases):
        result = super().__call__(game, chosen, labels, folder, phases)
        names = [u["name"] for phase in phases or () for u in phase]
        if phases is not None and "EET_end" not in names:
            for u in result["phases"][-1]["units"]:
                u["flagged"] = u["flagged"] or (self.still and u["name"] == "EET_end")
            result["violations"] = result["violations"] + ([self.broken] if self.broken
                                                           else [])
        return result


def test_planning_again_that_leaves_the_row_red_is_not_applied(qtbot, tmp_path):
    """Review of #77: a re-plan the planner still finds wrong is refused."""
    widget, _view = fixing(qtbot, tmp_path, Worse(still=True))
    dialog = opened(qtbot, widget)
    dialog.options.setCurrentRow(1)
    assert "A rule still finds it in the wrong place." in dialog.preview.text()
    assert not dialog.apply.isEnabled()


def test_a_fix_that_breaks_another_rule_is_not_applied(qtbot, tmp_path):
    """Review of #77: planning again or turning off that breaks a rule the
    plan keeps now is refused, the rule named."""
    widget, _view = fixing(qtbot, tmp_path, Worse(broken="ub should be installed before eet"))
    dialog = opened(qtbot, widget)
    for row in (1, 2):                                  # replan, off
        dialog.options.setCurrentRow(row)
        assert "Newly broken: ub should be installed before eet" in dialog.preview.text()
        assert not dialog.apply.isEnabled()


def test_turning_a_row_off_hands_its_components_to_the_window(qtbot, tmp_path):
    widget, _view = fixing(qtbot, tmp_path, Preview())
    emitted = []
    widget.turn_off.connect(emitted.append)
    dialog = opened(qtbot, widget)
    dialog.options.setCurrentRow(2)
    assert dialog.options.currentItem().text() == "Turn it off (1 component(s))"
    assert dialog.apply.isEnabled()
    dialog.apply.click()
    assert emitted == [[("EET_end/EET_end.tp2", 0)]]
    assert "EET_end" not in " ".join(lines_of(tmp_path))


def test_the_window_unticks_what_a_fix_turns_off_and_plans_again(qtbot, tmp_path):
    """Item 32's "turn it off" through the window: the mods page unticks the
    components, the selection is saved and the order planned again."""
    from gui.test_m3_end_to_end import EET, TW, UB, check, load, plan
    from iemod_fetch_gui.window import MainWindow
    api.save_project(str(tmp_path), "EET")
    main = MainWindow(str(tmp_path), load=load, check=check, plan=plan)
    qtbot.addWidget(main)
    with qtbot.waitSignal(main.mods.loaded, timeout=5000):
        main.mods.start("EET")
    for key in [(UB, 0), (EET, 0), (TW, 100)]:
        main.mods.items[key].setCheckState(0, Qt.CheckState.Checked)
    with qtbot.waitSignal(main.order.planned, timeout=5000):
        main.order.turn_off.emit([(TW, 100)])
    assert main.mods.chosen() == [(UB, 0), (EET, 0)]
    assert TW not in (tmp_path / api.SELECTION_FILE).read_text()
    shown = [u["tp2"] for p in main.order.result["phases"] for u in p["units"]]
    assert TW not in shown and EET in shown


def test_a_fix_on_the_real_planner_mends_what_a_hand_order_broke(qtbot, tmp_path):
    """Item 32 on the real path: stratagems #5900 dragged above the EET core
    breaks a rule the plan reports; "plan it again" is previewed by the real
    planner - nothing left broken, no new error - and applied."""
    here = os.path.join(os.path.dirname(__file__), os.pardir)
    mock = os.path.join(here, "data", "eetmock")
    common = {"order_catalogue": os.path.join(here, "data", "krion"),
              "rules": [os.path.join(mock, "rules")], "target": os.path.join(mock, "Mods")}
    from test_selection_plan import CHOSEN

    def real(game, chosen, labels, folder):
        return api.selection_plan(game, chosen, labels, folder=folder,
                                  data_dir=os.path.join(folder, "no-cache"), **common)

    def preview(game, chosen, labels, folder, phases):
        return api.preview_install_order(game, chosen, labels, folder=folder, phases=phases,
                                         data_dir=os.path.join(folder, "no-cache"), **common)
    widget = OrderPage(str(tmp_path), plan=real, preview=preview)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.planned, timeout=10000):
        widget.start("EET", CHOSEN, {})
    widget.tabs.setCurrentIndex(1)
    rows = lambda: [widget.tabs.widget(1).item(r).data(ROLE)  # noqa: E731
                    for r in range(widget.tabs.widget(1).count())]
    source = next(r for r, u in enumerate(rows()) if u["name"] == "stratagems #5900")
    with qtbot.waitSignal(widget.planned, timeout=10000):
        widget.tabs.widget(1).model().moveRow(QModelIndex(), source, QModelIndex(), 1)
    assert widget.result["violations"]
    flagged = next(r for r, u in enumerate(rows()) if u["name"] == "stratagems #5900")
    assert rows()[flagged]["flagged"]
    widget.tabs.widget(1).setCurrentRow(flagged)
    dialog = opened(qtbot, widget)
    kinds = [f["kind"] for f in dialog.fixes]
    assert "replan" in kinds
    dialog.options.setCurrentRow(kinds.index("replan"))
    assert "breaks nothing else" in dialog.preview.text(), dialog.preview.text()
    with qtbot.waitSignal(widget.planned, timeout=10000):
        dialog.apply.click()
    assert widget.result["violations"] == [] and widget.result["cycles"] == []
    assert not any(u["flagged"] for u in rows())
    # its line is gone, every other row keeps the order the player set
    assert "stratagems 5900" not in lines_of(tmp_path)
    assert "stratagems 4100" in lines_of(tmp_path)


# --------------------------------------------- the row's panel (item 33)
def real_page(qtbot, folder, extra_rules=()):
    """The order page on the run's own planner and the mock EET install."""
    here = os.path.join(os.path.dirname(__file__), os.pardir)
    mock = os.path.join(here, "data", "eetmock")
    common = {"order_catalogue": os.path.join(here, "data", "krion"),
              "rules": [os.path.join(mock, "rules"), *extra_rules],
              "target": os.path.join(mock, "Mods")}
    from test_selection_plan import CHOSEN

    def real(game, chosen, labels, project):
        return api.selection_plan(game, chosen, labels, folder=project,
                                  data_dir=os.path.join(project, "no-cache"), **common)
    widget = OrderPage(str(folder), plan=real)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.planned, timeout=10000):
        widget.start("EET", CHOSEN, {})
    widget.tabs.setCurrentIndex(1)
    return widget


def at(widget, name):
    view = widget.tabs.widget(1)
    return next(r for r in range(view.count()) if view.item(r).data(ROLE)["name"] == name)


def test_the_panel_shows_each_rule_on_the_row_and_dims_a_whole_mod_one(qtbot, tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "order.json").write_text(json.dumps({"rules": [
        {"rule": "ub(-):ascension(-)", "direction": "before", "severity": "warning"}]}))
    widget = real_page(qtbot, tmp_path / "project", [str(rules)])
    widget.tabs.widget(1).setCurrentRow(at(widget, "ascension"))
    text = widget.panel.text()
    assert "Must come after ub: ub before ascension" in text
    assert f'color: {GREY.name()}">Must come after ub' in text and "whole mod" in text
    assert "Must come before stratagems #5900: ascension(0) before stratagems(5900)" in text
    assert "broken" not in text
    widget.tabs.widget(1).setCurrentRow(at(widget, "DlcMerger"))
    assert "No order rule names it." in widget.panel.text()
    assert not widget.ignore.isEnabled()


def broken_page(qtbot, folder):
    """stratagems #5900 dragged above the EET core: the plan reports it."""
    folder.mkdir()
    widget = real_page(qtbot, folder)
    with qtbot.waitSignal(widget.planned, timeout=10000):
        widget.tabs.widget(1).model().moveRow(QModelIndex(), at(widget, "stratagems #5900"),
                                              QModelIndex(), 1)
    return widget


def test_an_ignored_row_is_grey_kept_in_decisions_and_red_again_once_dragged(
        qtbot, tmp_path, monkeypatch):
    widget = broken_page(qtbot, tmp_path / "project")
    view = widget.tabs.widget(1)
    row = at(widget, "stratagems #5900")
    assert view.item(row).foreground().color() == RED
    view.setCurrentRow(row)
    assert "Broken: [WeiDU.log] stratagems should be installed before eet" in widget.panel.text()
    assert widget.ignore.text() == "Ignore..." and widget.ignore.isEnabled()
    monkeypatch.setattr("iemod_fetch_gui.pages.order.QInputDialog.getText",
                        lambda *_args: ("tested, works for me", True))
    with qtbot.waitSignal(widget.planned, timeout=10000):
        widget.ignore.click()
    view = widget.tabs.widget(1)
    row = at(widget, "stratagems #5900")
    item = view.item(row)
    assert item.foreground().color() == GREY and item.text().endswith("(ignored)")
    saved = api.load_decisions(str(tmp_path / "project"))["ignored_order"]
    assert saved["WeiDU.log|stratagems|0"]["why"] == "tested, works for me"
    view.setCurrentRow(row)
    assert widget.ignore.text() == "Stop ignoring"
    assert "Ignored, while it stays where it is: tested, works for me" in widget.panel.text()
    # eet, the rule's other row, is not ignored: the list below still says it plainly
    assert "(ignored:" not in widget.problems.text()

    with qtbot.waitSignal(widget.planned, timeout=10000):     # dragged: shown again
        view.model().moveRow(QModelIndex(), row, QModelIndex(), 0)
    assert api.load_decisions(str(tmp_path / "project"))["ignored_order"] == {}
    view = widget.tabs.widget(1)
    assert view.item(at(widget, "stratagems #5900")).foreground().color() == RED


def test_stop_ignoring_shows_the_row_red_again(qtbot, tmp_path, monkeypatch):
    widget = broken_page(qtbot, tmp_path / "project")
    monkeypatch.setattr("iemod_fetch_gui.pages.order.QInputDialog.getText",
                        lambda *_args: ("fine", True))
    widget.tabs.widget(1).setCurrentRow(at(widget, "stratagems #5900"))
    with qtbot.waitSignal(widget.planned, timeout=10000):
        widget.ignore.click()
    widget.tabs.widget(1).setCurrentRow(at(widget, "stratagems #5900"))
    with qtbot.waitSignal(widget.planned, timeout=10000):
        widget.ignore.click()                                    # Stop ignoring
    view = widget.tabs.widget(1)
    assert view.item(at(widget, "stratagems #5900")).foreground().color() == RED
    assert api.load_decisions(str(tmp_path / "project"))["ignored_order"] == {}


def test_ignoring_without_a_reason_saves_nothing(qtbot, tmp_path, monkeypatch):
    widget = broken_page(qtbot, tmp_path / "project")
    monkeypatch.setattr("iemod_fetch_gui.pages.order.QInputDialog.getText",
                        lambda *_args: ("  ", True))
    widget.tabs.widget(1).setCurrentRow(at(widget, "stratagems #5900"))
    widget.ignore.click()
    assert not (tmp_path / "project" / api.DECISIONS_FILE).exists()


def test_a_rule_every_row_ignores_says_so_below_the_list(qtbot, tmp_path, monkeypatch):
    widget = broken_page(qtbot, tmp_path / "project")
    monkeypatch.setattr("iemod_fetch_gui.pages.order.QInputDialog.getText",
                        lambda *_args: ("tested", True))
    for name in ("stratagems #5900", "eet"):                 # both rows the rule names
        widget.tabs.widget(1).setCurrentRow(at(widget, name))
        with qtbot.waitSignal(widget.planned, timeout=10000):
            widget.ignore.click()
    assert widget.problems.text().splitlines()[0] == (
        "[WeiDU.log] stratagems should be installed before eet (ignored: tested)")


# ----------------------------- several rows, keys, find (item 35)
def ruled_page(qtbot, folder):
    widget = OrderPage(str(folder), plan=Ruled(), preview=Preview())
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.planned, timeout=5000):
        widget.start("EET", ALL, {})
    widget.tabs.setCurrentIndex(1)
    return widget


def select(view, *rows):
    view.clearSelection()
    for row in rows:
        view.item(row).setSelected(True)


def test_a_block_of_rows_dropped_together_is_checked_at_once(qtbot, tmp_path):
    widget = ruled_page(qtbot, tmp_path)
    view = widget.tabs.widget(1)
    with qtbot.waitSignal(widget.planned, timeout=5000):
        # ub and ascension, rows 1-2, below EET_end: three rows now wrong
        view.model().moveRows(QModelIndex(), 1, 2, QModelIndex(), 4)
        assert texts(widget, 1) == ["eet", "EET_end", "ub", "ascension"]
        assert [view.item(r).foreground().color() == RED for r in range(4)] == [
            False, True, True, True]
        assert "2 rule(s) broken" in widget.problems.text()


def test_ctrl_down_moves_the_selected_rows_together_saved_and_planned_once(
        qtbot, tmp_path, monkeypatch):
    widget = ruled_page(qtbot, tmp_path)
    view = widget.tabs.widget(1)
    saves = []
    real = api.save_install_order
    monkeypatch.setattr(api, "save_install_order",
                        lambda *args: saves.append(1) or real(*args))
    calls = widget.plan.calls
    select(view, 1, 2)                                     # ub, ascension
    with qtbot.waitSignal(widget.planned, timeout=5000):
        widget.nudge(1)
        assert texts(widget, 1) == ["eet", "EET_end", "ub", "ascension"]
        assert sorted(i.row() for i in view.selectedIndexes()) == [2, 3]   # still selected
    assert saves == [1] and widget.plan.calls == calls + 1
    assert lines_of(tmp_path)[2:] == ["EET_end *", "ub *", "ascension *"]


def test_nothing_moves_past_either_end(qtbot, tmp_path):
    widget = ruled_page(qtbot, tmp_path)
    view = widget.tabs.widget(1)
    select(view, 0, 1)
    widget.nudge(-1)
    select(view, 3)
    widget.nudge(1)
    assert texts(widget, 1) == ["eet", "ub", "ascension", "EET_end"]
    assert not (tmp_path / api.INSTALL_ORDER_FILE).exists()


def test_the_keys_move_the_rows(qtbot, tmp_path):
    from PySide6.QtTest import QTest
    widget = ruled_page(qtbot, tmp_path)
    widget.show()
    with qtbot.waitActive(widget):
        widget.activateWindow()
    view = widget.tabs.widget(1)
    view.setFocus()
    view.setCurrentRow(2)                                  # ascension
    with qtbot.waitSignal(widget.planned, timeout=5000):
        QTest.keyClick(view, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    assert texts(widget, 1) == ["eet", "ascension", "ub", "EET_end"]


def test_find_selects_the_matching_rows_of_the_tab_shown(qtbot, tmp_path):
    widget = ruled_page(qtbot, tmp_path)
    view = widget.tabs.widget(1)
    widget.find.setText("eet")
    assert sorted(i.row() for i in view.selectedIndexes()) == [0, 3]   # eet, EET_end
    assert view.currentRow() == 0
    widget.find.setText("ASC")
    assert [i.row() for i in view.selectedIndexes()] == [2]
    widget.find.setText("")
    assert view.selectedIndexes() == []


def test_coming_back_with_nothing_changed_keeps_the_plan(qtbot, tmp_path):
    widget = ruled_page(qtbot, tmp_path)
    calls = widget.plan.calls
    with qtbot.waitSignal(widget.planned, timeout=5000):
        widget.start("EET", ALL, {})
    assert widget.plan.calls == calls and widget.is_complete()
    with qtbot.waitSignal(widget.planned, timeout=5000):  # another selection
        widget.start("EET", ALL[:-1], {})
    assert widget.plan.calls == calls + 1
    api.save_decisions(str(tmp_path), {}, {"conflict-1": "fine"})     # a project file
    with qtbot.waitSignal(widget.planned, timeout=5000):
        widget.start("EET", ALL[:-1], {})
    assert widget.plan.calls == calls + 2


def test_a_mod_staged_since_the_plan_is_planned_again(qtbot, tmp_path):
    """Review of #82: back from the download page, a staged mod's own ini can
    order it differently - the plan shown is not kept."""
    widget = ruled_page(qtbot, tmp_path)
    calls = widget.plan.calls
    ini = tmp_path / "Mods" / "ub" / "ub.ini"                  # the project's target
    ini.parent.mkdir(parents=True)
    ini.write_text("[Metadata]\nAfter = ascension\n")
    with qtbot.waitSignal(widget.planned, timeout=5000):
        widget.start("EET", ALL, {})
    assert widget.plan.calls == calls + 1
