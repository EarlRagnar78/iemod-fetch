"""
Phase 2, mod selection, driven like a player drives it (M3, GUI-AUDIT item 16).
The catalogue comes from a fixed loader - the page's loader is injected - so
the tests need no network and no community data.
"""
import json
import os

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402

from iemod_fetch import api  # noqa: E402
from iemod_fetch_gui import text as qtext  # noqa: E402
from iemod_fetch_gui.pages.mods import ROLE, ModsPage  # noqa: E402
from iemod_fetch_gui.window import MainWindow  # noqa: E402
from test_project import bg2ee, bgee  # noqa: E402

TP2 = "bg1ub/setup-bg1ub.tp2"


def no_plan(*_args):
    return {"phases": [], "cycles": [], "violations": [], "planned": False, "custom": False}


def no_check(*_args):
    """No rules: these tests are about choosing (test_conflicts.py checks)."""
    return {"findings": [], "stale": [], "rules_checked": 0, "planned": False,
            "problem": None}


def component(number, name, exclusive="", subgroup="", requires=()):
    return {"number": number, "name": name, "subgroup": subgroup, "exclusive": exclusive,
            "groups": [], "requires": list(requires), "forced": False}


MODS = [
    {"key": "bg1ub", "name": "BG1 Unfinished Business", "games": ["BGEE", "EET"],
     "categories": ["Quests"], "status": [], "advisories": [], "version": "v17",
     "installed": "v16", "update_available": True, "latest": {"version": "v17"},
     "tp2s": [{"tp2": TP2, "origin": "krion64", "components": [
         component(0, "Restoration"),
         component(10, "classic", "g:7", "Portraits"),
         component(11, "new", "g:7", "Portraits"),
         component(20, "Needs the first", requires=[0])]}]},
    {"key": "unknown", "name": "A mod nobody describes", "games": ["EET"],
     "categories": ["Tweaks"], "status": [], "advisories": [], "tp2s": []},
]


def page(qtbot, folder, mods=MODS):
    widget = ModsPage(str(folder), load=lambda game, project: json.loads(json.dumps(mods)),
                      check=no_check)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.loaded, timeout=5000):
        widget.start("EET")
    return widget


def check(widget, key, on=True):
    widget.items[key].setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)


def test_the_catalogue_loads_off_the_window_thread_with_its_categories(qtbot, tmp_path):
    widget = page(qtbot, tmp_path)
    assert widget.tree.topLevelItemCount() == 2
    # A list from before item 26 has no kinds: its categories stand in.
    assert [widget.categories.item(i).text() for i in range(widget.categories.count())] == [
        "All kinds (2)", "Quests (1)", "Tweaks (1)"]
    assert not widget.is_complete()


def test_choosing_one_of_a_subcomponent_clears_the_others(qtbot, tmp_path):
    widget = page(qtbot, tmp_path)
    check(widget, (TP2, 10))
    check(widget, (TP2, 11))
    assert widget.chosen() == [(TP2, 11)]


def test_a_component_brings_the_one_it_needs(qtbot, tmp_path):
    widget = page(qtbot, tmp_path)
    check(widget, (TP2, 20))
    assert widget.chosen() == [(TP2, 0), (TP2, 20)] and widget.is_complete()


def test_a_mod_whose_components_are_unknown_cannot_be_chosen(qtbot, tmp_path):
    widget = page(qtbot, tmp_path)
    unknown = widget.tree.topLevelItem(1)
    assert unknown.isDisabled() and "not known until it is downloaded" in unknown.toolTip(0)


def test_search_category_and_filters_hide_what_does_not_match(qtbot, tmp_path):
    widget = page(qtbot, tmp_path)
    visible = lambda: [widget.tree.topLevelItem(i).text(0)  # noqa: E731
                       for i in range(widget.tree.topLevelItemCount())
                       if not widget.tree.topLevelItem(i).isHidden()]
    widget.search.setText("portraits")                 # a component's name finds its mod
    assert visible() == ["BG1 Unfinished Business"]
    widget.search.setText("")
    widget.categories.setCurrentRow(2)
    assert visible() == ["A mod nobody describes"]
    widget.categories.setCurrentRow(0)
    widget.filter.setCurrentText("Updates available")
    assert visible() == ["BG1 Unfinished Business"]
    widget.filter.setCurrentText("Chosen only")
    assert visible() == []
    check(widget, (TP2, 0))
    widget.apply_filter()
    assert visible() == ["BG1 Unfinished Business"]


def test_the_choice_is_saved_as_the_selection_the_cli_reads_and_comes_back(qtbot, tmp_path):
    widget = page(qtbot, tmp_path)
    check(widget, (TP2, 10))
    path = widget.save()
    (install,) = api.load_selection(path).installs
    assert install.game == "EET"
    assert [(c.tp2, c.component, c.label) for c in install.components] == [(TP2, 10, "classic")]
    again = page(qtbot, tmp_path)
    assert again.chosen() == [(TP2, 10)]


def test_a_loader_that_fails_is_shown_not_raised(qtbot, tmp_path):
    def broken(game, project):
        raise OSError("no network")
    widget = ModsPage(str(tmp_path), load=broken, check=no_check)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.loaded, timeout=5000):
        widget.start("EET")
    assert "could not be loaded: no network" in widget.status.text()


def test_a_list_that_failed_loads_when_the_game_is_chosen_again(qtbot, tmp_path):
    # Review of #41: after a failed switch the old game's tree stayed, so
    # choosing the game again found "a list" and loaded nothing, presets off
    offline = [True]

    def flaky(game, project):
        if game == "BGEE" and offline[0]:
            raise OSError("offline")
        return json.loads(json.dumps(MODS))
    widget = ModsPage(str(tmp_path), load=flaky, check=no_check)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.loaded, timeout=5000):
        widget.start("EET")
    with qtbot.waitSignal(widget.loaded, timeout=5000):
        widget.start("BGEE")
    assert "could not be loaded: offline" in widget.status.text()
    assert widget.tree.topLevelItemCount() == 0        # not EET's list
    offline[0] = False
    with qtbot.waitSignal(widget.loaded, timeout=5000):
        widget.start("BGEE")
    assert widget.tree.topLevelItemCount() == 2
    assert widget.load_preset.isEnabled() and widget.save_preset.isEnabled()


def test_the_wizard_goes_from_folders_to_mods_and_saves_both(qtbot, tmp_path):
    project = tmp_path / "project"
    planned = {"phases": [{"role": "WeiDU.log", "title": "EET", "units": [{
        "node": "n", "name": "bg1ub", "tp2": "setup-bg1ub.tp2", "key": "bg1ub", "part": 0,
        "split": False, "category": "", "components": [[TP2, 0, ""]],
        "constrained": False, "moved": False, "flagged": False}]}],
        "cycles": [], "violations": [], "planned": True, "custom": False}
    main = MainWindow(str(project), load=lambda game, proj: json.loads(json.dumps(MODS)),
                      check=no_check, plan=lambda *a: planned)
    qtbot.addWidget(main)
    main.game.bgee.edit.setText(bgee(tmp_path))
    main.game.bg2ee.edit.setText(bg2ee(tmp_path))
    main.game.check()
    with qtbot.waitSignal(main.mods.loaded, timeout=5000):
        qtbot.mouseClick(main.next, Qt.MouseButton.LeftButton)
    assert main.current == 1 and not main.next.isEnabled()
    check(main.mods, (TP2, 0))
    assert main.next.isEnabled()
    with qtbot.waitSignal(main.order.planned, timeout=5000):
        qtbot.mouseClick(main.next, Qt.MouseButton.LeftButton)
    assert main.current == 2 and (project / api.SELECTION_FILE).is_file()
    # once the order is planned, Next goes on (it stayed disabled: the page
    # said it was complete before its thread had ended)
    assert main.order.is_complete() and main.next.isEnabled()


def test_closing_the_page_while_the_list_loads_does_not_crash(qtbot, tmp_path):
    """A loader still on the network when the window closes: Qt aborts if a
    running QThread is destroyed, so the thread outlives the page."""
    import threading

    from iemod_fetch_gui.pages.mods import wait_for_loaders
    release = threading.Event()

    def slow(game, project):
        release.wait(5)
        return []
    widget = ModsPage(str(tmp_path), load=slow, check=no_check)
    widget.start("EET")
    widget.close()
    widget.deleteLater()
    qtbot.wait(50)                     # the page is gone; its thread is not
    release.set()
    wait_for_loaders(5000)


# ------------------------------------------- selection by kind (item 26)
KINDS = [
    dict(MODS[1], key="turnabout", name="Turnabout", kinds=["gameplay", "quest"],
         kinds_by_source={"lcc-docs": ["quest"], "BWS-NG": ["gameplay"]},
         kind_disagreement=True),
    dict(MODS[1], key="ascension", name="Ascension", kinds=["quest"],
         kinds_by_source={"lcc-docs": ["quest"], "BWS-NG": ["quest"]},
         kind_disagreement=False, install_category="QUEST MODS BG2", tags=["tob"]),
]


def test_the_list_is_chosen_by_kind_and_a_disagreement_is_shown(qtbot, tmp_path):
    widget = page(qtbot, tmp_path, KINDS)
    visible = lambda: [widget.tree.topLevelItem(i).text(0)  # noqa: E731
                       for i in range(widget.tree.topLevelItemCount())
                       if not widget.tree.topLevelItem(i).isHidden()]
    assert [widget.categories.item(i).text() for i in range(widget.categories.count())] == [
        "All kinds (2)", "gameplay (1)", "quest (2)"]
    turnabout, ascension = (widget.tree.topLevelItem(i) for i in range(2))
    assert ascension.text(3) == "quest"
    assert turnabout.text(3).startswith("\u26a0") and "gameplay, quest" in turnabout.text(3)
    assert turnabout.toolTip(3) == qtext.plain_tip("lcc-docs: quest; BWS-NG: gameplay")
    widget.categories.setCurrentRow(1)
    assert visible() == ["Turnabout"]
    widget.categories.setCurrentRow(0)
    widget.filter.setCurrentText("Kinds disagree")
    assert visible() == ["Turnabout"]

    widget._show(turnabout)               # disabled rows: nothing to choose yet
    text = widget.details.toPlainText()
    assert "lcc-docs: quest; BWS-NG: gameplay" in text
    assert "disagree" in text
    widget._show(ascension)
    assert "krion64 install category: QUEST MODS BG2 (tags: tob)" in widget.details.toPlainText()


def test_a_chosen_mod_the_kind_filter_hides_stays_chosen(qtbot, tmp_path):
    mods = [dict(MODS[0], kinds=["quest"]), dict(KINDS[0])]
    widget = page(qtbot, tmp_path, mods)
    check(widget, (TP2, 0))
    widget.categories.setCurrentRow(1)                   # gameplay: Turnabout only
    assert widget.tree.topLevelItem(0).isHidden()
    assert widget.chosen() == [(TP2, 0)]


# --------------------------------------------- review follow-ups (#32)
EXCLUSIVE_NEEDED = [{
    "key": "fp", "name": "Faiths and Powers", "games": ["EET"], "categories": ["Kits"],
    "status": [], "advisories": [], "tp2s": [{"tp2": "fp/fp.tp2", "origin": "krion64",
                                              "refused": None, "components": [
        component(10, "kit a", "g:paladin"), component(11, "kit b", "g:paladin"),
        component(30, "needs kit a", requires=[10]),
        component(30, "listed twice")]}]}]


def test_a_needed_component_clears_the_rest_of_its_subcomponent(qtbot, tmp_path):
    widget = page(qtbot, tmp_path, EXCLUSIVE_NEEDED)
    check(widget, ("fp/fp.tp2", 11))
    check(widget, ("fp/fp.tp2", 30))
    assert widget.chosen() == [("fp/fp.tp2", 10), ("fp/fp.tp2", 30)]


def test_a_component_listed_twice_has_one_box_that_works(qtbot, tmp_path):
    widget = page(qtbot, tmp_path, EXCLUSIVE_NEEDED)
    rows = [widget.tree.topLevelItem(0).child(i).text(0)
            for i in range(widget.tree.topLevelItem(0).childCount())]
    assert sum(row.startswith("#30") for row in rows) == 1


def test_a_refused_tp2_cannot_be_chosen_and_says_why(qtbot, tmp_path):
    refused = [dict(EXCLUSIVE_NEEDED[0], tp2s=[dict(EXCLUSIVE_NEEDED[0]["tp2s"][0],
                                                    refused="tp2 path is unsafe")])]
    widget = page(qtbot, tmp_path, refused)
    assert widget.tree.topLevelItem(0).isDisabled()


def test_changing_the_game_while_the_list_loads_loads_the_new_game(qtbot, tmp_path):
    import threading
    gate = threading.Event()
    asked = []

    def load(game, project):
        asked.append(game)
        if game == "EET":
            gate.wait(5)
        return [dict(MODS[0], name=f"for {game}")]
    widget = ModsPage(str(tmp_path), load=load, check=no_check)
    qtbot.addWidget(widget)
    widget.start("EET")
    widget.start("BGEE")                       # Back, another game, Next
    with qtbot.waitSignal(widget.loaded, timeout=5000):
        gate.set()
    assert asked == ["EET", "BGEE"] and widget.game == "BGEE"
    assert widget.tree.topLevelItem(0).text(0) == "for BGEE"


def test_catalogue_text_is_shown_as_text_not_html(qtbot, tmp_path):
    hostile = [dict(MODS[0], name="<a href='file:///etc/passwd'>click</a>",
                    advisories=["<img src='file:///x'>"])]
    widget = page(qtbot, tmp_path, hostile)
    widget._show(widget.tree.topLevelItem(0))
    assert "&lt;a href" in widget.details.toHtml() and "<img" not in widget.details.toHtml()


def test_a_selection_for_another_game_is_not_carried_over(qtbot, tmp_path):
    api.save_selection(str(tmp_path), "BGEE", [(TP2, 0)])
    widget = page(qtbot, tmp_path)                     # loads for EET
    assert widget.chosen() == []


def test_an_eet_build_saved_in_two_phases_is_chosen_again(qtbot, tmp_path):
    # bg1ub belongs to the BG:EE phase (krion64): selection.json holds it in a
    # BGEE install beside the EET one, and the EET page must find it there.
    krion = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "krion")
    api.save_selection(str(tmp_path), "EET", [(TP2, 0), ("eet/EET.tp2", 0)],
                       order_catalogue=krion)
    saved = api.load_selection(str(tmp_path / api.SELECTION_FILE))
    assert [i.game for i in saved.installs] == ["BGEE", "EET"]
    widget = page(qtbot, tmp_path)
    assert widget.chosen() == [(TP2, 0)]


# ----------------------------------- who needs it (GUI-AUDIT M5b item 34)
ADDON, OTHER = "addon/addon.tp2", "other/other.tp2"
WITH_ADDONS = MODS + [
    {"key": "addon", "name": "An addon", "games": ["EET"], "categories": ["Quests"],
     "status": [], "advisories": [],
     "tp2s": [{"tp2": ADDON, "origin": "krion64", "components": [component(0, "Addon")]}]},
    {"key": "other", "name": "Another mod", "games": ["EET"], "categories": ["Tweaks"],
     "status": [], "advisories": [],
     "tp2s": [{"tp2": OTHER, "origin": "krion64", "components": [component(0, "Other")]}]}]


def needing(*needs):
    """A check that finds no conflict and the dependencies `needs` satisfied."""
    def check(game, chosen, labels, folder):
        return dict(no_check(), needs=[
            {"chosen": [list(who)], "on": [[list(p) for p in alt] for alt in on], "rule": ""}
            for who, on in needs if who in chosen])
    return check


def guarded(qtbot, folder, check, chosen, answer, mods=WITH_ADDONS):
    widget = ModsPage(str(folder), load=lambda game, project: json.loads(json.dumps(
        mods)), check=check)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.loaded, timeout=5000):
        widget.start("EET")
    for key in chosen:
        check_(widget, key)
    with qtbot.waitSignal(widget.checked, timeout=5000):    # checked as it now is
        widget.timer.stop()
        widget.check_conflicts()
    asked = []
    widget.ask_dependents = lambda removed, needs: asked.append((removed, needs)) or answer
    return widget, asked


check_ = check


def test_unticking_what_its_own_mod_needs_asks_and_can_untick_those_too(qtbot, tmp_path):
    widget, asked = guarded(qtbot, tmp_path, no_check, [(TP2, 20)], "all")
    assert widget.chosen() == [(TP2, 0), (TP2, 20)]           # #20 brought #0
    check_(widget, (TP2, 0), on=False)
    qtbot.waitUntil(lambda: bool(asked), timeout=2000)
    assert len(asked) == 1 and "#20" in asked[0][1][0]
    assert widget.chosen() == []


def test_keep_ticks_it_again_and_alone_leaves_the_others(qtbot, tmp_path):
    widget, asked = guarded(qtbot, tmp_path, no_check, [(TP2, 20)], "keep")
    check_(widget, (TP2, 0), on=False)
    qtbot.waitUntil(lambda: bool(asked), timeout=2000)
    assert widget.chosen() == [(TP2, 0), (TP2, 20)]
    widget.ask_dependents = lambda *_args: "only"
    check_(widget, (TP2, 0), on=False)
    qtbot.wait(50)
    assert widget.chosen() == [(TP2, 20)]


def test_a_rule_another_mod_needs_it_by_is_asked_about_and_followed(qtbot, tmp_path):
    # the other mod needs it, and the addon (listed first) needs the other mod
    check = needing(((OTHER, 0), [[(TP2, 0)]]), ((ADDON, 0), [[(OTHER, 0)]]))
    widget, asked = guarded(qtbot, tmp_path, check, [(TP2, 0), (ADDON, 0), (OTHER, 0)],
                            "all")
    check_(widget, (TP2, 0), on=False)
    qtbot.waitUntil(lambda: bool(asked), timeout=2000)
    assert [name.split(" #")[0] for name in asked[0][1]] == ["Another mod", "An addon"]
    assert widget.chosen() == []


def test_another_alternative_still_chosen_asks_nothing(qtbot, tmp_path):
    check = needing(((ADDON, 0), [[(TP2, 0)], [(TP2, 10)]]))     # any one of the two
    widget, asked = guarded(qtbot, tmp_path, check, [(TP2, 0), (TP2, 10), (ADDON, 0)],
                            "all")
    check_(widget, (TP2, 0), on=False)
    qtbot.wait(50)
    assert asked == [] and (ADDON, 0) in widget.chosen()


def test_a_mod_unticked_whole_asks_once(qtbot, tmp_path):
    check = needing(((ADDON, 0), [[(TP2, 0)]]))
    widget, asked = guarded(qtbot, tmp_path, check, [(TP2, 0), (TP2, 10), (ADDON, 0)],
                            "keep")
    mod = next(widget.tree.topLevelItem(r) for r in range(widget.tree.topLevelItemCount())
               if widget.tree.topLevelItem(r).data(0, ROLE)[1] == "bg1ub")
    mod.setCheckState(0, Qt.CheckState.Unchecked)
    qtbot.waitUntil(lambda: bool(asked), timeout=2000)
    qtbot.wait(50)
    assert len(asked) == 1 and len(asked[0][0]) == 2              # #0 and #10, once
    assert set(widget.chosen()) == {(TP2, 0), (TP2, 10), (ADDON, 0)}


def resolving(severity):
    """The addon needs bg1ub #0 (or #20) and clashes with the other mod."""
    def side(key, path, number):
        return {"mod": key, "components": [number], "whole_mod": False, "key": key,
                "chosen": [[path, number]]}

    def check(game, chosen, labels, folder):
        findings = []
        if (ADDON, 0) in chosen and (TP2, 0) not in chosen:
            findings.append({
                "id": "conflict-dep", "kind": "depends", "severity": "error",
                "left": side("addon", ADDON, 0),
                "right": {"mod": "bg1ub", "components": [0], "whole_mod": False,
                          "key": "bg1ub", "chosen": []},
                "fixed_by_plan": None, "decision": None, "reason": "", "remedy": "",
                "options": [{"id": "option-i", "action": "install", "key": "bg1ub",
                             "mod": "bg1ub", "components": [0], "whole_mod": False,
                             "applicable": True, "recommended": False, "cost": 0,
                             "description": "install bg1ub", "chosen": []}]})
        if (ADDON, 0) in chosen and (OTHER, 0) in chosen:
            findings.append({
                "id": "conflict-inc", "kind": "incompatible", "severity": severity,
                "left": side("addon", ADDON, 0), "right": side("other", OTHER, 0),
                "fixed_by_plan": None, "decision": None, "reason": "", "remedy": "",
                "options": []})
        return dict(no_check(), findings=findings, rules_checked=2)
    return check


def test_resolve_chooses_what_it_needs_then_keeps_it_against_an_error(qtbot, tmp_path):
    widget, _asked = guarded(qtbot, tmp_path, resolving("error"), [(ADDON, 0), (OTHER, 0)],
                             "only")
    widget.tree.setCurrentItem(widget.items[(ADDON, 0)])
    assert widget.resolve.isEnabled()
    shown = []
    widget.confirm_resolve = lambda text: shown.append(text) or True
    with qtbot.waitSignal(widget.checked, timeout=5000):
        widget.resolve.click()
    assert shown == ["Choose bg1ub #0\nDeselect Another mod #0  Other"]
    # one alternative chosen, not every target; the other side deselected
    assert widget.chosen() == [(TP2, 0), (ADDON, 0)]


def test_resolve_leaves_a_warning_to_the_player_and_does_nothing_unconfirmed(
        qtbot, tmp_path):
    widget, _asked = guarded(qtbot, tmp_path, resolving("warning"),
                             [(ADDON, 0), (OTHER, 0)], "only")
    widget.tree.setCurrentItem(widget.items[(ADDON, 0)])
    shown = []
    widget.confirm_resolve = lambda text: shown.append(text) or False
    widget.resolve.click()
    assert shown[0].splitlines() == [
        "Choose bg1ub #0", "Left to you: warning: other - a warning is yours to decide"]
    assert widget.chosen() == [(ADDON, 0), (OTHER, 0)]           # not confirmed


def test_resolve_is_off_where_there_is_nothing_to_resolve(qtbot, tmp_path):
    widget, _asked = guarded(qtbot, tmp_path, resolving("error"), [(TP2, 10)], "only")
    widget.tree.setCurrentItem(widget.items[(TP2, 10)])
    assert not widget.resolve.isEnabled()


def test_a_cycle_of_requires_ends_and_unticks_both(qtbot, tmp_path):
    """Review of #81: two components that require each other, and a third
    that needs one of them - the walk ends, every one is named once."""
    cyclic = [dict(MODS[0], tp2s=[{"tp2": TP2, "origin": "krion64", "components": [
        component(0, "Restoration"), component(30, "One", requires=[31]),
        component(31, "Two", requires=[30]), component(32, "Three", requires=[31])]}])]
    widget, asked = guarded(qtbot, tmp_path, no_check, [(TP2, 30), (TP2, 32)], "all",
                            mods=cyclic)
    assert widget.chosen() == [(TP2, 30), (TP2, 31), (TP2, 32)]
    check_(widget, (TP2, 31), on=False)
    qtbot.waitUntil(lambda: bool(asked), timeout=2000)
    assert sorted(name.split("#")[1].split()[0] for name in asked[0][1]) == ["30", "32"]
    assert widget.chosen() == []


def test_the_real_check_names_what_a_mods_own_tp2_needs(qtbot, tmp_path):
    """Review of #81 (the real path): api.selection_conflicts on the mock EET
    install - EET_end's own tp2 requires the EET core - and the page asks
    before the core is unticked."""
    here = os.path.join(os.path.dirname(__file__), os.pardir)
    mock = os.path.join(here, "data", "eetmock")
    core, end = "eet/EET.tp2", "EET_end/EET_end.tp2"
    mods = [{"key": key, "name": name, "games": ["EET"], "categories": ["Core"],
             "status": [], "advisories": [],
             "tp2s": [{"tp2": tp2, "origin": "tp2", "components": [component(0, name)]}]}
            for key, name, tp2 in (("eet", "EET", core), ("eet_end", "EET end", end))]

    def real(game, chosen, labels, folder):
        return api.selection_conflicts(game, chosen, labels, folder=folder,
                                       rules=[os.path.join(mock, "rules")],
                                       target=os.path.join(mock, "Mods"),
                                       order_catalogue=os.path.join(here, "data", "krion"),
                                       data_dir=os.path.join(folder, "no-cache"))
    widget, asked = guarded(qtbot, tmp_path, real, [(core, 0), (end, 0)], "keep", mods=mods)
    assert {"chosen": [[end, 0]], "on": [[[core, 0]]],
            "rule": "eetend(0) needs eet(0)"} in widget.conflicts["needs"]
    check_(widget, (core, 0), on=False)
    qtbot.waitUntil(lambda: bool(asked), timeout=2000)
    assert asked[0][1] == ["EET end #0  EET end"]
    assert widget.chosen() == [(core, 0), (end, 0)]                  # kept


def test_a_deselect_the_player_chose_elsewhere_is_not_asked_about_again(qtbot, tmp_path):
    """Review of #81: the conflicts panel's Deselect, or the order page's
    "turn it off", is the player's answer already - no second question."""
    check = needing(((ADDON, 0), [[(TP2, 0)]]))
    widget, asked = guarded(qtbot, tmp_path, check, [(TP2, 0), (ADDON, 0)], "keep")
    widget.deselect([(TP2, 0)])
    qtbot.wait(50)
    assert asked == [] and widget.chosen() == [(ADDON, 0)]


# ------------------------- groups, forced options, no re-check (item 35)
def test_a_mod_ticked_whole_takes_each_groups_first_option(qtbot, tmp_path):
    widget = page(qtbot, tmp_path)
    mod = widget.tree.topLevelItem(0)
    mod.setCheckState(0, Qt.CheckState.Checked)
    # #10 "classic", the first of the Portraits group - not Qt's last, #11
    assert widget.chosen() == [(TP2, 0), (TP2, 10), (TP2, 20)]


def test_a_mod_ticked_whole_keeps_the_option_already_chosen(qtbot, tmp_path):
    widget = page(qtbot, tmp_path)
    check(widget, (TP2, 11))
    qtbot.wait(1)                                # two clicks: the event loop runs between
    widget.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
    assert widget.chosen() == [(TP2, 0), (TP2, 11), (TP2, 20)]


FORCED = [dict(MODS[0], tp2s=[{"tp2": TP2, "origin": "tp2", "components": [
    component(0, "Restoration"),
    dict(component(10, "classic", "sub:Portraits", "Portraits"), forced=True),
    dict(component(11, "new", "sub:Portraits", "Portraits"), forced=True)]}])]


def test_the_only_option_of_a_forced_group_is_put_back(qtbot, tmp_path):
    widget = page(qtbot, tmp_path, FORCED)
    check(widget, (TP2, 0))
    check(widget, (TP2, 10))
    check(widget, (TP2, 10), on=False)
    qtbot.waitUntil(lambda: (TP2, 10) in widget.chosen(), timeout=2000)
    assert "needs one option of this group" in widget.status.text()
    check(widget, (TP2, 11))                     # another option: allowed
    assert widget.chosen() == [(TP2, 0), (TP2, 11)]


def test_a_forced_group_goes_with_its_mod(qtbot, tmp_path):
    widget = page(qtbot, tmp_path, FORCED)
    check(widget, (TP2, 0))
    check(widget, (TP2, 10))
    widget.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
    qtbot.wait(50)
    assert widget.chosen() == []


def test_a_check_is_not_run_again_when_nothing_it_reads_changed(qtbot, tmp_path):
    calls = []

    def counting(*args):
        calls.append(args[1])
        return dict(no_check(), rules_checked=1)
    widget = ModsPage(str(tmp_path), load=lambda game, project: json.loads(json.dumps(MODS)),
                      check=counting)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.loaded, timeout=5000):
        widget.start("EET")
    check(widget, (TP2, 0))
    with qtbot.waitSignal(widget.checked, timeout=5000):
        widget.check_conflicts()
    ran = widget.checks
    check(widget, (TP2, 0), on=False)            # undone before the check
    check(widget, (TP2, 0))
    with qtbot.waitSignal(widget.checked, timeout=5000):
        widget.check_conflicts()
    assert widget.checks == ran                  # the same selection: not checked again
    api.save_decisions(str(tmp_path), {}, {"conflict-1": "fine"})   # a decision changed
    with qtbot.waitSignal(widget.checked, timeout=5000):
        widget.check_conflicts()
    assert widget.checks == ran + 1


MAYBE_MODS = [
    {"key": "tweaks", "name": "Tweak Anthology", "games": ["EET"], "categories": [],
     "status": ["stable"], "advisories": [], "version": "v16", "installed": None,
     "update_available": None, "latest": None, "last_update": "2025-08-25",
     "fetched": "2025-08-01", "maybe_updated": True, "page": "https://example.org/tweaks",
     "tp2s": [{"tp2": "tweaks/setup-tweaks.tp2", "origin": "tp2",
               "components": [component(0, "One")]}]},
    {"key": "other", "name": "Other", "games": ["EET"], "categories": [], "status": [],
     "advisories": [], "version": "1", "last_update": "2025-08-25", "fetched": None,
     "maybe_updated": False, "tp2s": [{"tp2": "other/setup-other.tp2", "origin": "tp2",
                                       "components": [component(0, "One")]}]},
]


def test_maybe_updated_is_shown_as_a_date_and_filtered(qtbot, tmp_path):
    widget = page(qtbot, tmp_path, MAYBE_MODS)
    tweaks, other = widget.tree.topLevelItem(0), widget.tree.topLevelItem(1)
    assert tweaks.text(0) == "Tweak Anthology" and tweaks.text(1) == "v16 (maybe updated)"
    assert other.text(1) == "1"
    widget.filter.setCurrentText("Maybe updated")
    assert [widget.tree.topLevelItem(i).text(0) for i in range(2)
            if not widget.tree.topLevelItem(i).isHidden()] == ["Tweak Anthology"]
    widget.filter.setCurrentText("Updates available")   # a date is not an update
    assert all(widget.tree.topLevelItem(i).isHidden() for i in range(2))
    widget._show(tweaks)
    text = widget.details.toPlainText()
    assert "lcc-docs last update: 2025-08-25" in text
    assert "after your copy was fetched on 2025-08-01" in text and "not a version" in text


def test_a_release_update_and_a_date_both_show_and_a_plain_address_is_text(qtbot, tmp_path):
    """Review of #122: the column agrees with both filters; an http page is
    shown, never dropped and never a link."""
    both = dict(MAYBE_MODS[0], update_available=True, installed="v15",
                latest={"version": "v16"}, page="http://example.org/tweaks")
    widget = page(qtbot, tmp_path, [both])
    row = widget.tree.topLevelItem(0)
    assert row.text(1) == "v15 -> v16 (maybe updated)"
    widget._show(row)
    assert "http://example.org/tweaks" in widget.details.toPlainText()
    assert 'href="http://' not in widget.details.toHtml()


HOSTILE = ('<a href="https://evil.example">click</a> <img src="https://evil.example/x.png"> '
           'javascript:alert(1)')


def test_release_notes_and_krion64_notes_are_literal_text_with_source_and_day(qtbot, tmp_path):
    """Item 51: third-party text, escaped whole - no link, no image - and
    what krion64 saw is said with the day of its data."""
    mod = dict(MAYBE_MODS[1], krion_date="2026-10-22",
               krion_notes=[["Notes", HOSTILE]],
               release={"repo": "a/b", "tag": "v2", "date": "2026-07-03", "notes": HOSTILE,
                        "pushed": "2026-09-06", "archived": True, "checked": "2026-03-14"})
    widget = page(qtbot, tmp_path, [mod])
    widget._show(widget.tree.topLevelItem(0))
    text, markup = widget.details.toPlainText(), widget.details.toHtml()
    assert text.count(HOSTILE) == 2                       # shown as written, twice
    assert 'href="https://evil.example"' not in markup and "<img" not in markup
    # what the scan saw carries the day of its look, older than the data's
    assert "Archived on GitHub, according to krion64's scan of 2026-03-14 (a/b)" in text
    assert "Last push to a/b (krion64's scan of 2026-03-14): 2026-09-06" in text
    assert "Notes (krion64, data of 2026-10-22):" in text      # notes: the data's day


def test_without_the_day_of_krion64s_data_it_says_so(qtbot, tmp_path):
    mod = dict(MAYBE_MODS[1], krion_date=None, krion_notes=[["Notes", "x"]])
    widget = page(qtbot, tmp_path, [mod])
    widget._show(widget.tree.topLevelItem(0))
    assert "Notes (krion64, date of its data not known): x" in widget.details.toPlainText()


def test_a_scan_with_no_day_of_its_own_says_so(qtbot, tmp_path):
    mod = dict(MAYBE_MODS[1], krion_date="2026-10-22",
               release={"repo": "a/b", "tag": "v2", "pushed": "2026-09-06"})
    widget = page(qtbot, tmp_path, [mod])
    widget._show(widget.tree.topLevelItem(0))
    assert ("Last push to a/b (krion64, data of 2026-10-22, day of its scan not known)"
            in widget.details.toPlainText())
