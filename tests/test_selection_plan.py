"""
The wizard's install order without a window (M3 phase 3, ADR-0038): the plan
of a selection, split by EET phase, and the order the player sets by hand -
kept as a Project Infinity Sorting Order file the command line reads too.
"""
import json
import os

import pytest

from iemod_fetch import api
from iemod_fetch.errors import ConfigError
from iemod_fetch.weidu import parse_weidu_files

HERE = os.path.dirname(__file__)
MOCK = os.path.join(HERE, "data", "eetmock")
KRION = os.path.join(HERE, "data", "krion")


def chosen_of(*logs):
    parsed = parse_weidu_files([(log, None) for log in logs])
    components = sorted((c for mod in parsed.mods.values() for c in mod.components),
                        key=lambda c: c.line)
    return [((c.path or f"{c.folder}/{c.tp2_file}").replace("\\", "/"), c.index)
            for c in components]


# the BG:EE phase's mod first, as a player might tick it
CHOSEN = chosen_of(os.path.join(MOCK, "WeiDU-BGEE.log"), os.path.join(MOCK, "WeiDU.log"))


def plan(folder, chosen=CHOSEN, **extra):
    extra.setdefault("order_catalogue", KRION)
    return api.selection_plan("EET", chosen, folder=str(folder),
                              rules=extra.pop("rules", [os.path.join(MOCK, "rules")]),
                              target=os.path.join(MOCK, "Mods"),
                              data_dir=str(folder / "no-cache"), **extra)


def names(result, title):
    phase = next(p for p in result["phases"] if p["title"] == title)
    return [u["name"].lower() for u in phase["units"]]


# ------------------------------------------------------------- the plan
def test_an_eet_build_is_planned_in_its_two_phases(tmp_path):
    result = plan(tmp_path)
    assert result["planned"] and not result["custom"]
    assert [p["title"] for p in result["phases"]] == ["BG:EE before the conversion", "EET"]
    assert names(result, "BG:EE before the conversion") == ["bg1ub"]
    eet = names(result, "EET")
    # the test catalogue places EET, then cdtweaks (pre-tactical), then
    # stratagems (tactical); components it files apart are units of their own
    first = {name.split(" #")[0]: n for n, name in reversed(list(enumerate(eet)))}
    assert first["eet"] < first["cdtweaks"] < first["stratagems"] < first["eet_end"]
    assert "stratagems #4100" in eet


def test_the_selection_is_saved_in_the_same_two_phases(tmp_path):
    api.save_selection(str(tmp_path), "EET", CHOSEN, order_catalogue=KRION)
    selection = api.load_selection(str(tmp_path / api.SELECTION_FILE))
    assert [i.game for i in selection.installs] == ["BGEE", "EET"]
    assert [c.tp2.lower() for c in selection.installs[0].components] == ["bg1ub/bg1ub.tp2"]


def test_without_krion64s_data_there_is_no_plan_and_one_install(tmp_path):
    result = plan(tmp_path, order_catalogue=None)
    assert result == {"phases": [], "cycles": [], "violations": [], "planned": False,
                      "custom": False}
    api.save_selection(str(tmp_path), "EET", CHOSEN)          # no data cache here
    selection = api.load_selection(str(tmp_path / api.SELECTION_FILE))
    assert [i.game for i in selection.installs] == ["EET"]


def test_a_rule_placed_mod_is_marked(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "order.json").write_text(json.dumps({"rules": [
        {"rule": "ub(-):ascension(-)", "direction": "before", "severity": "warning"}]}))
    result = plan(tmp_path, rules=[str(rules)])
    eet = next(p for p in result["phases"] if p["title"] == "EET")["units"]
    marked = {u["name"].lower() for u in eet if u["constrained"]}
    assert {"ub", "ascension"} <= marked
    order = names(result, "EET")
    assert order.index("ub") < order.index("ascension")


# --------------------------------------------------- the order by hand
def test_an_order_set_by_hand_is_kept_and_applied(tmp_path):
    first = plan(tmp_path)
    phases = [p["units"] for p in first["phases"]]
    eet = phases[1]
    ub = next(u for u in eet if u["name"].lower() == "ub")
    eet.remove(ub)
    eet.insert(eet.index(next(u for u in eet if u["name"].lower() == "ascension")), ub)
    path = api.save_install_order(str(tmp_path), phases)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    assert "ub *" in text and text.index("ub *") < text.index("Ascension *")
    # the command line run in the project reads it as --sorting-order
    assert "sorting_order = install-order.txt" in (tmp_path / api.PROJECT_FILE).read_text()
    again = plan(tmp_path)
    assert again["custom"]
    order = names(again, "EET")
    assert order.index("ub") < order.index("ascension")


def test_an_order_that_breaks_a_rule_is_reported_not_silently_won(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "order.json").write_text(json.dumps({"rules": [
        {"rule": "ascension(-):ub(-)", "direction": "before", "severity": "warning"}]}))
    phases = [p["units"] for p in plan(tmp_path, rules=[str(rules)])["phases"]]
    eet = phases[1]
    ub = next(u for u in eet if u["name"].lower() == "ub")
    eet.remove(ub)
    eet.insert(0, ub)
    api.save_install_order(str(tmp_path), phases)
    result = plan(tmp_path, rules=[str(rules)])
    assert result["cycles"] or result["violations"]


def test_the_plan_hands_the_order_page_its_rule_edges(tmp_path):
    """M5b item 31 (review of #75): the check after a drop uses each unit's
    `after` - the real planner's, not a test's - and on the plan's own order
    finds what the plan reports: nothing, then what a hand order breaks."""
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "order.json").write_text(json.dumps({"rules": [
        {"rule": "ub(-):ascension(-)", "direction": "before", "severity": "warning"}]}))

    def eet_of(result):
        return next(p for p in result["phases"] if p["title"] == "EET")["units"]
    units = eet_of(plan(tmp_path, rules=[str(rules)]))
    node = {u["name"].lower(): u["node"] for u in units}
    after = {u["node"]: u["after"] for u in units}
    assert node["ub"] in after[node["ascension"]]
    assert api.order_breaks([u["node"] for u in units], after) == set()

    ub = next(u for u in units if u["node"] == node["ub"])
    units.remove(ub)
    units.append(ub)                                         # ub after ascension
    phases = [p["units"] for p in plan(tmp_path, rules=[str(rules)])["phases"]]
    phases[1] = units
    api.save_install_order(str(tmp_path), phases)
    result = plan(tmp_path, rules=[str(rules)])
    assert result["violations"]
    again = eet_of(result)
    breaks = api.order_breaks([u["node"] for u in again],
                              {u["node"]: u["after"] for u in again})
    # the hand order meets the rules in a cycle; what the plan then flags is
    # what the check finds broken, pair for pair
    assert breaks and len(breaks) == len(result["violations"])
    assert {n for pair in breaks for n in pair} == {u["node"] for u in again if u["flagged"]}


def test_using_the_computed_order_again_forgets_the_file(tmp_path):
    phases = [p["units"] for p in plan(tmp_path)["phases"]]
    api.save_install_order(str(tmp_path), phases)
    api.reset_install_order(str(tmp_path))
    assert not (tmp_path / api.INSTALL_ORDER_FILE).exists()
    assert "sorting_order" not in (tmp_path / api.PROJECT_FILE).read_text()
    assert not plan(tmp_path)["custom"]


def test_a_split_mod_names_its_components(tmp_path):
    unit = {"tp2": "stratagems/setup-stratagems.tp2", "split": True,
            "components": [["stratagems/setup-stratagems.tp2", 4100, ""]]}
    whole = {"tp2": "ub/setup-ub.tp2", "split": False, "components": []}
    with open(api.save_install_order(str(tmp_path), [[whole, unit]]), encoding="utf-8") as fh:
        text = fh.read()
    assert "ub *\nstratagems 4100\n" in text


def test_a_tp2_name_with_spaces_is_written_as_its_key_reads_it(tmp_path):
    # krion64 lists `Setup-Unofficial Item Pack.tp2`; one such mod must not
    # stop every drag.
    unit = {"tp2": "Setup-Unofficial Item Pack.tp2", "split": False, "components": []}
    with open(api.save_install_order(str(tmp_path), [[unit]]), encoding="utf-8") as fh:
        assert "UnofficialItemPack *" in fh.read()


def test_a_name_that_cannot_be_a_sorting_line_is_refused(tmp_path):
    with pytest.raises(ConfigError):
        api.save_install_order(str(tmp_path), [[{"tp2": "--.tp2", "split": False,
                                                 "components": []}]])
    assert not (tmp_path / api.INSTALL_ORDER_FILE).exists()


def test_an_unwritable_project_ini_leaves_no_order_file(tmp_path):
    (tmp_path / api.PROJECT_FILE).write_text("not an ini [[[\n")
    phases = [p["units"] for p in plan(tmp_path)["phases"]]
    with pytest.raises(ConfigError):
        api.save_install_order(str(tmp_path), phases)
    assert not (tmp_path / api.INSTALL_ORDER_FILE).exists()


def test_your_own_order_does_not_mark_every_mod_as_placed_by_a_rule(tmp_path):
    def constrained(result):
        return sorted(u["name"] for p in result["phases"] for u in p["units"]
                      if u["constrained"])
    before = constrained(plan(tmp_path))
    api.save_install_order(str(tmp_path), [p["units"] for p in plan(tmp_path)["phases"]])
    assert constrained(plan(tmp_path)) == before


def test_the_cli_finds_the_order_file_beside_the_ini_from_anywhere(tmp_path, monkeypatch):
    from iemod_fetch.config import load_config
    api.save_install_order(str(tmp_path), [p["units"] for p in plan(tmp_path)["phases"]])
    monkeypatch.chdir(tmp_path.parent)
    config = load_config(str(tmp_path / api.PROJECT_FILE))
    assert config.values["sorting_order"] == str(tmp_path / api.INSTALL_ORDER_FILE)


def collapsed(folders):
    out = []
    for folder in folders:
        if not out or out[-1] != folder:
            out.append(folder)
    return out


def test_the_wizards_order_is_the_order_the_command_line_writes(tmp_path):
    # The acceptance test: the same selection.json and install-order.txt give
    # the same order on the page and in the run's plan.
    phases = [p["units"] for p in plan(tmp_path)["phases"]]
    eet = phases[1]
    ub = next(u for u in eet if u["name"].lower() == "ub")
    eet.remove(ub)
    eet.insert(1, ub)
    api.save_install_order(str(tmp_path), phases)
    shown = plan(tmp_path)
    api.save_selection(str(tmp_path), "EET", CHOSEN, order_catalogue=KRION)
    api.run(api.Settings(
        selection=str(tmp_path / api.SELECTION_FILE),
        sorting_order=str(tmp_path / api.INSTALL_ORDER_FILE),
        check_only=True, quiet=True, manifest=os.path.join(HERE, "data", "mod_downloads.json"),
        target=os.path.join(MOCK, "Mods"), rules=[os.path.join(MOCK, "rules")],
        order_catalogue=KRION, plan_order=str(tmp_path / "plan"),
        data_dir=str(tmp_path / "no-cache"), no_update_data=True, no_default_data=True))
    for title, log in (("BG:EE before the conversion", "WeiDU-BGEE.log"), ("EET", "WeiDU.log")):
        lines = (tmp_path / "plan" / log).read_text().splitlines()
        written = collapsed([line[1:].split("\\")[0].lower() for line in lines
                             if line.startswith("~")])
        page = collapsed([u["components"][0][0].split("/")[0].lower()
                          for u in next(p for p in shown["phases"]
                                        if p["title"] == title)["units"]])
        assert written == page, title


def test_a_failed_second_save_keeps_the_ini_naming_the_file_still_there(tmp_path, monkeypatch):
    phases = [p["units"] for p in plan(tmp_path)["phases"]]
    api.save_install_order(str(tmp_path), phases)

    def full(*_args):
        raise OSError("disk full")
    monkeypatch.setattr(api, "_write_whole", full)
    with pytest.raises(OSError):
        api.save_install_order(str(tmp_path), phases)
    assert (tmp_path / api.INSTALL_ORDER_FILE).exists()
    assert "sorting_order = install-order.txt" in (tmp_path / api.PROJECT_FILE).read_text()


def test_a_path_the_player_wrote_is_put_back_and_never_reset(tmp_path, monkeypatch):
    (tmp_path / api.PROJECT_FILE).write_text("[iemod-fetch]\nsorting_order = my-order.txt\n")
    api.reset_install_order(str(tmp_path))
    assert "my-order.txt" in (tmp_path / api.PROJECT_FILE).read_text()

    def full(*_args):
        raise OSError("disk full")
    monkeypatch.setattr(api, "_write_whole", full)
    with pytest.raises(OSError):
        api.save_install_order(str(tmp_path), [p["units"] for p in plan(tmp_path)["phases"]])
    assert "sorting_order = my-order.txt" in (tmp_path / api.PROJECT_FILE).read_text()


# ---------------------------------------------- the place by kind (item 27)
def test_what_krion64_does_not_place_takes_the_place_its_kind_decides(tmp_path):
    """ub and ascension are not in the test catalogue: lcc-docs, in the data
    cache, says ub is a BG1 quest and ascension gameplay."""
    import shutil
    krion = tmp_path / "krion"
    shutil.copytree(KRION, krion)
    categories = json.loads((krion / "categories.json").read_text(encoding="utf-8"))
    names_ = list(categories["categories"])
    names_.insert(names_.index("ENGINE") + 1, "QUEST MODS BG1")
    categories["categories"] = {name: categories["categories"].get(name, {})
                                for name in names_}
    (krion / "categories.json").write_text(json.dumps(categories), encoding="utf-8")
    lcc = tmp_path / "no-cache" / "lcc-docs" / "db"
    lcc.mkdir(parents=True)
    (lcc / "mods.json").write_text(json.dumps([
        {"tp2": "ub", "name": "Unfinished Business", "categories": ["Quête"],
         "games": ["BGEE"], "urls": []},
        {"tp2": "ascension", "name": "Ascension", "categories": ["Gameplay"],
         "games": ["BG2EE"], "urls": []}]), encoding="utf-8")

    result = plan(tmp_path, order_catalogue=str(krion))

    eet = {u["name"].lower(): u for u in
           next(p for p in result["phases"] if p["title"] == "EET")["units"]}
    assert eet["ub"]["category"] == "QUEST MODS BG1"
    assert eet["ub"]["placed_by"] == "placed by kind: quest, 73% (lcc-docs)"
    assert eet["ascension"]["placed_by"] == ""
    assert eet["ascension"]["no_place"] == "no place: its kind does not decide one (gameplay)"
    order = names(result, "EET")
    first_tweak = next(n for n, name in enumerate(order) if name.startswith("cdtweaks"))
    assert order.index("ub") < first_tweak          # QUEST MODS BG1 before PRE-TACTICAL


def test_bws_ngs_sequence_in_the_data_cache_places_first(tmp_path):
    """Decision 2a: games/eet.json, cached, places ascension after EEex, its
    neighbour after it agreeing (ENGINE), before any kind would."""
    import shutil
    krion = tmp_path / "krion"
    shutil.copytree(KRION, krion)
    (krion / "mods" / "engine2.json").write_text(json.dumps(
        {"t": "engine2", "c": "ENGINE", "ord": 20}), encoding="utf-8")
    games = tmp_path / "no-cache" / "bws-ng" / "data" / "games"
    games.mkdir(parents=True)
    (games / "eet.json").write_text(json.dumps({"sequences": [
        {"game": "bg2ee", "order": ["eet:0", "eeex:0", "ascension:0", "engine2:0"]}]}),
        encoding="utf-8")

    result = plan(tmp_path, order_catalogue=str(krion))

    eet = {u["name"].lower(): u for u in
           next(p for p in result["phases"] if p["title"] == "EET")["units"]}
    assert eet["ascension"]["placed_by"] == "placed by BWS-NG's EET sequence: after eeex #0"
    assert eet["ascension"]["placed_from"] == "BWS-NG"
    assert eet["ub"]["placed_by"] == ""


def test_a_broken_cached_sequence_does_not_block_the_plan(tmp_path):
    """Review of #71 (F2): the data cache's eet.json is warned about; one
    given by hand still stops the run."""
    games = tmp_path / "no-cache" / "bws-ng" / "data" / "games"
    games.mkdir(parents=True)
    (games / "eet.json").write_text('{"sequences": [', encoding="utf-8")

    result = plan(tmp_path)

    assert result["planned"]
    by_hand = api.Settings(eet_sequence=str(games / "eet.json"),
                           data_dir=str(tmp_path / "elsewhere"))
    with pytest.raises(ConfigError, match="cannot read --eet-sequence"):
        api._eet_sequences(by_hand)
    cached = api.Settings(eet_sequence=str(games / "eet.json"),
                          data_dir=str(tmp_path / "no-cache"))
    warned: list = []
    assert api._eet_sequences(cached, warned) is None and "cannot be read" in warned[0]


def test_after_a_split_and_a_move_the_wizard_and_the_command_line_agree(tmp_path):
    """M5b item 30, its acceptance test: eefixpack split into its components
    and #1 moved just after the EET core - the page and --plan-order give the
    same order, component for component."""
    phases = [p["units"] for p in plan(tmp_path)["phases"]]
    eet = phases[1]
    fix = next(u for u in eet if u["key"] == "eefixpack")
    at = eet.index(fix)
    parts = [dict(fix, components=[c], split=True) for c in fix["components"]]
    eet[at:at + 1] = parts
    eet.remove(parts[1])
    eet.insert(eet.index(next(u for u in eet if u["key"] == "eet")) + 1, parts[1])
    wanted = [(c[0].split("/")[0].lower(), c[1]) for u in eet for c in u["components"]]
    api.save_install_order(str(tmp_path), phases)

    shown = plan(tmp_path)
    page = [(c[0].split("/")[0].lower(), c[1])
            for u in next(p for p in shown["phases"] if p["title"] == "EET")["units"]
            for c in u["components"]]
    assert page == wanted and not shown["violations"]
    api.save_selection(str(tmp_path), "EET", CHOSEN, order_catalogue=KRION)
    api.run(api.Settings(
        selection=str(tmp_path / api.SELECTION_FILE),
        sorting_order=str(tmp_path / api.INSTALL_ORDER_FILE),
        check_only=True, quiet=True, manifest=os.path.join(HERE, "data", "mod_downloads.json"),
        target=os.path.join(MOCK, "Mods"), rules=[os.path.join(MOCK, "rules")],
        order_catalogue=KRION, plan_order=str(tmp_path / "plan"),
        data_dir=str(tmp_path / "no-cache"), no_update_data=True, no_default_data=True))
    written = [(line[1:].split("\\")[0].lower(), int(line.split("#")[2].split()[0]))
               for line in (tmp_path / "plan" / "WeiDU.log").read_text().splitlines()
               if line.startswith("~")]
    assert written == page


def test_a_rule_broken_by_one_part_marks_that_part_not_the_mod():
    """Review of #74: after a split, one part's violation marked every part."""
    from types import SimpleNamespace
    from iemod_fetch.rules import Violation
    part = lambda n: SimpleNamespace(key="eefixpack", lines=[("p", 0, n, "")])  # noqa: E731
    wrong = Violation("order", "error", "eefixpack #1 must go after eet",
                      mods=("eefixpack", "eet"), left_components=(1,))
    assert api._broken(part(1), [wrong]) == [wrong.summary]
    assert not api._broken(part(0), [wrong])
    whole = Violation("order", "error", "eefixpack after eet", mods=("eet", "eefixpack"))
    assert api._broken(part(0), [whole])


def test_a_tp2_in_both_installs_is_written_with_its_numbers(tmp_path):
    """Review of #74: `*` would name it whole in both."""
    unit = lambda tp2, numbers, split=False: {  # noqa: E731
        "tp2": tp2, "split": split, "components": [[tp2, n, ""] for n in numbers]}
    api.save_install_order(str(tmp_path), [
        [unit("eefixpack/setup-eefixpack.tp2", [0]), unit("bg1ub/bg1ub.tp2", [0])],
        [unit("EET/EET.tp2", [0]), unit("eefixpack/setup-eefixpack.tp2", [1, 2])]])
    lines = [line for line in (tmp_path / api.INSTALL_ORDER_FILE).read_text().splitlines()
             if not line.startswith("//")]
    assert lines == ["eefixpack 0", "bg1ub *", "EET *", "eefixpack 1 2"]


def test_a_keep_both_decision_in_the_project_orders_the_wizards_plan(tmp_path):
    """Item 28: the project's decisions.json "keep both, X last" is an order
    rule of the wizard's plan - here on ub and cdtweaks #2370, which nothing
    else orders, so the decision alone moves them (review of #72, H3)."""
    overlap = tmp_path / "overlap"
    overlap.mkdir()
    (overlap / "incompatibilities.json").write_text(json.dumps({"rules": [
        {"rule": "ub(0):cdtweaks(2370)", "severity": "warning", "description": "same file"}]}))
    rules = [os.path.join(MOCK, "rules"), str(overlap)]

    def order():
        units = next(p for p in plan(tmp_path, rules=rules)["phases"]
                     if p["title"] == "EET")["units"]
        return [(c[0].split("/")[0].lower(), c[1]) for u in units for c in u["components"]]
    before = order()
    ub_first = before.index(("ub", 0)) < before.index(("cdtweaks", 2370))
    found = api.selection_conflicts("EET", CHOSEN, folder=str(tmp_path),
                                    order_catalogue=KRION, rules=rules,
                                    target=os.path.join(MOCK, "Mods"),
                                    data_dir=str(tmp_path / "no-cache"))
    pair = next(f for f in found["findings"] if f["kind"] == "incompatible"
                and {f["left"]["mod"], f["right"]["mod"]} == {"ub", "cdtweaks"})
    last = next(o for o in pair["options"] if o["action"] == "keep-both"
                and o["mod"] == ("ub" if ub_first else "cdtweaks"))
    api.save_decisions(str(tmp_path), choose={pair["id"]: last["id"]})

    after = order()

    assert (after.index(("ub", 0)) < after.index(("cdtweaks", 2370))) is not ub_first


def test_moved_and_flagged_are_marked_per_part_through_the_real_plan(tmp_path):
    """Review of #74: with marks per mod, every part of a split mod was moved
    or red when one was. cdtweaks is split by the catalogue: only its #4010
    is moved. eefixpack split by hand, #1 put before the EET core against a
    rule that wants it after: only #1 is flagged."""
    rows = {u["name"]: u for u in next(p for p in plan(tmp_path)["phases"]
                                       if p["title"] == "EET")["units"]}
    assert rows["cdtweaks #4010"]["moved"] and not rows["cdtweaks #2370"]["moved"]

    after = tmp_path / "after"
    after.mkdir()
    (after / "order.json").write_text(json.dumps(
        [{"rule": "eefixpack(1):eet", "direction": "after", "severity": "error"}]))
    rules = [os.path.join(MOCK, "rules"), str(after)]
    phases = [p["units"] for p in plan(tmp_path, rules=rules)["phases"]]
    eet = phases[1]
    pieces = [u for u in eet if u["key"] == "eefixpack"]    # the rule may split it already
    at = eet.index(pieces[0])
    for piece in pieces:
        eet.remove(piece)
    parts = {c[1]: dict(pieces[0], components=[c], split=True)
             for piece in pieces for c in piece["components"]}
    eet[at:at] = [parts[0], parts[2]]
    eet.insert(0, parts[1])                    # #1 first: before the EET core
    api.save_install_order(str(tmp_path), phases)

    shown = plan(tmp_path, rules=rules)
    flagged = {u["name"]: u["flagged"] for u in next(
        p for p in shown["phases"] if p["title"] == "EET")["units"] if u["key"] == "eefixpack"}
    assert shown["violations"]
    assert flagged == {"eefixpack #1": True, "eefixpack #0": False, "eefixpack #2": False}


# ------------------------------------------ the row's panel (M5b item 33)
def test_each_row_carries_the_order_rules_on_it_for_the_panel(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "order.json").write_text(json.dumps({"rules": [
        {"rule": "ub(-):ascension(-)", "direction": "before", "severity": "warning"}]}))
    eet = plan(tmp_path, rules=[os.path.join(MOCK, "rules"), str(rules)])["phases"][1]["units"]
    by_name = {u["name"]: u for u in eet}
    on = {(r["must"], r["name"], r["whole"]) for r in by_name["ascension"]["rules"]}
    # a rule naming whole mods (shown dimmed) and one naming components
    assert on == {("after", "ub", True), ("before", "stratagems #5900", False)}
    rule = next(r for r in by_name["ub"]["rules"])
    assert (rule["must"], rule["name"], rule["severity"]) == ("before", "ascension", "warning")
    assert rule["rule"] == "ub before ascension" and rule["source"]
    assert by_name["DlcMerger"]["rules"] == [] and by_name["DlcMerger"]["broken"] == []


def broken_by_hand(folder, rules=None):
    """stratagems #5900 dragged above the EET core: a rule the plan reports."""
    extra = {"rules": rules} if rules else {}
    phases = [p["units"] for p in plan(folder, **extra)["phases"]]
    eet = phases[1]
    moved = next(u for u in eet if u["name"] == "stratagems #5900")
    eet.remove(moved)
    eet.insert(1, moved)
    api.save_install_order(str(folder), phases)
    return plan(folder, **extra)


def row(result, node):
    units = result["phases"][1]["units"]
    at = next(n for n, u in enumerate(units) if u["node"] == node)
    return units[at], (units[at - 1]["node"] if at else "")


def test_an_ignored_row_stays_ignored_in_its_place_and_for_its_rules(tmp_path):
    node = "WeiDU.log|stratagems|0"
    unit, above = row(broken_by_hand(tmp_path), node)
    assert unit["flagged"] and unit["broken"] and unit["ignored"] is None
    api.ignore_order(str(tmp_path), node, above, unit["broken"], "tested, works for me")
    unit, _above = row(plan(tmp_path), node)
    assert unit["ignored"] == {"why": "tested, works for me", "after": above}
    assert unit["flagged"]                       # still broken; the page shows it ignored
    # an ignore made in another place does not hold here
    api.ignore_order(str(tmp_path), node, "WeiDU.log|ub|0", unit["broken"], "elsewhere")
    assert row(plan(tmp_path), node)[0]["ignored"] is None


def test_a_new_rule_the_row_breaks_shows_it_again(tmp_path):
    node = "WeiDU.log|stratagems|0"
    unit, above = row(broken_by_hand(tmp_path), node)
    api.ignore_order(str(tmp_path), node, above, unit["broken"], "fine")
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "order.json").write_text(json.dumps({"rules": [
        {"rule": "stratagems(5900):dlcmerger(-)", "direction": "before",
         "severity": "warning"}]}))           # DlcMerger stays first: a new break
    again, _above = row(plan(tmp_path, rules=[os.path.join(MOCK, "rules"), str(rules)]), node)
    assert len(again["broken"]) > len(unit["broken"]) and again["ignored"] is None


# ------------------------------------- nothing to check again (item 35)
def test_the_digest_changes_with_what_a_check_reads_and_only_then(tmp_path):
    data = tmp_path / "data"
    data.mkdir()

    def digest(chosen=CHOSEN, labels=None):
        return api.selection_digest("EET", chosen, labels, folder=str(tmp_path),
                                    data_dir=str(data))
    first = digest()
    assert digest() == first and api.selection_digest(
        "eet", CHOSEN, None, folder=str(tmp_path), data_dir=str(data)) == first
    assert digest(CHOSEN[:-1]) != first                       # a component fewer
    assert digest(labels={CHOSEN[0]: "renamed"}) != first      # a label
    api.save_install_order(str(tmp_path), [p["units"] for p in plan(tmp_path)["phases"]])
    second = digest()
    assert second != first                                     # the order set by hand
    (data / "sources.json").write_text("{}")                    # the data refreshed
    assert digest() != second


def test_the_digest_follows_the_staged_mods_and_their_inis(tmp_path):
    """Review of #82: the planner reads each staged mod's own ini and tp2,
    and the data cache's copy of the inis - each changes the digest."""
    data, target = tmp_path / "data", tmp_path / "Mods"
    data.mkdir()
    target.mkdir()

    def digest():
        return api.selection_digest("EET", CHOSEN, None, folder=str(tmp_path),
                                    data_dir=str(data), target=str(target))
    first = digest()
    (target / "mymod").mkdir()                                  # a mod staged
    staged = digest()
    assert staged != first
    ini = target / "mymod" / "mymod.ini"
    ini.write_text("[Metadata]\nBefore = eet\n")                # its own ini
    with_ini = digest()
    assert with_ini != staged
    os.utime(ini, ns=(1, 1))                                    # extracted again
    again = digest()
    assert again != with_ini
    (data / "mod-metadata.json").write_text("{}")               # the inis' cache
    assert digest() != again
