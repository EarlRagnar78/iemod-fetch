"""
A mod krion64 does not place takes the place its kind decides (GUI-AUDIT M5
item 27, ADR-0041 decision 2): only where the kind decides one, after
krion64's own mods in that category, never over a rule, and marked with its
source. Where the kind decides nothing the mod stays where the player put it,
and says why.
"""
import io
import json

from iemod_fetch.kinds import KindHint, place
from iemod_fetch.ordering import (EET_LOG, PRE_EET_LOG, OrderIndex, plan_order,
                                  render_plan_summary)
from iemod_fetch.rules import RuleSet

CATEGORIES = ["PRE EET BGEE MODS", "EET STARTS HERE", "INTERFACE", "QUEST MODS BG1",
              "QUEST MODS BG2", "NEW NPC MODS", "KIT & CLASS MODS", "TACTICAL MODS"]
HEADER = "// Log of Currently Installed WeiDU Mods\n"


def krion(tmp_path):
    root = tmp_path / "krion"
    (root / "mods").mkdir(parents=True)
    (root / "categories.json").write_text(json.dumps(
        {"categories": {name: {} for name in CATEGORIES}}), encoding="utf-8")
    for t, c, order in (("EET", "EET STARTS HERE", 10), ("LeUI", "INTERFACE", 10),
                        ("bg1ub", "PRE EET BGEE MODS", 10),
                        ("ascension", "QUEST MODS BG2", 10),
                        ("stratagems", "TACTICAL MODS", 10),
                        ("newhud", "INTERFACE", 20), ("tactix", "TACTICAL MODS", 20)):
        (root / "mods" / f"{t}.json").write_text(json.dumps(
            {"t": t, "c": c, "ord": order}), encoding="utf-8")
    return OrderIndex.load(str(root))


def log(tmp_path, *tp2s, name="WeiDU.log"):
    path = tmp_path / name
    path.write_text(HEADER + "\n".join(f"~{t}\\{t}.tp2~ #0 #0 // {t}" for t in tp2s)
                    + "\n", encoding="utf-8")
    return str(path)


def order(plan, role=EET_LOG):
    return [u.key for u in plan.logs[role]]


UI = KindHint(("interface",), ("BG2EE",), ("lcc-docs", "BWS-NG"))


def test_a_kind_that_decides_places_the_mod_after_krion64s_own(tmp_path):
    index = krion(tmp_path)
    eet = log(tmp_path, "EET", "stratagems", "newui", "LeUI")

    plan = plan_order([(eet, EET_LOG)], index, kinds={"newui": UI})

    assert order(plan) == ["eet", "leui", "newui", "stratagems"]
    assert plan.by_kind == [("newui", "INTERFACE",
                             "placed by kind: interface, 92% / 100% (lcc-docs, BWS-NG)")]
    assert plan.unranked == []
    newui = next(u for u in plan.logs[EET_LOG] if u.key == "newui")
    assert newui.placed_by.startswith("placed by kind")


def test_without_the_kinds_the_mod_stays_where_it_was(tmp_path):
    index = krion(tmp_path)
    plan = plan_order([(log(tmp_path, "EET", "stratagems", "newui"), EET_LOG)], index)
    assert order(plan) == ["eet", "stratagems", "newui"]
    assert plan.unranked == ["newui"] and plan.by_kind == []


def test_a_kind_that_decides_nothing_leaves_it_and_says_why(tmp_path):
    index = krion(tmp_path)
    tweak = KindHint(("gameplay",), (), ("lcc-docs",))
    plan = plan_order([(log(tmp_path, "EET", "stratagems", "tweak"), EET_LOG)], index,
                      kinds={"tweak": tweak})
    assert order(plan) == ["eet", "stratagems", "tweak"]
    assert plan.no_place == [(EET_LOG, "tweak",
                              "no place: its kind does not decide one (gameplay)")]
    out = io.StringIO()
    render_plan_summary(plan, str(tmp_path), out)
    assert "does not decide one (gameplay)" in out.getvalue()


def test_a_rule_still_decides_over_the_kind(tmp_path):
    index = krion(tmp_path)
    rules = tmp_path / "order.json"
    rules.write_text(json.dumps([{"rule": "newui:stratagems", "direction": "after"}]),
                     encoding="utf-8")
    plan = plan_order([(log(tmp_path, "EET", "stratagems", "newui"), EET_LOG)], index,
                      RuleSet.load([str(rules)]), kinds={"newui": UI})
    assert order(plan) == ["eet", "stratagems", "newui"]
    assert plan.verified


def test_a_quest_for_bg1_alone_goes_with_bg1s_quests(tmp_path):
    index = krion(tmp_path)
    bg1 = KindHint(("quest",), ("BGEE", "EET"), ("lcc-docs",))
    bg2 = KindHint(("quest",), ("BG2EE", "EET"), ("lcc-docs",))
    plan = plan_order([(log(tmp_path, "EET", "ascension", "q2", "q1"), EET_LOG)], index,
                      kinds={"q1": bg1, "q2": bg2})
    assert order(plan) == ["eet", "q1", "ascension", "q2"]
    assert {name: category for name, category, _why in plan.by_kind} == {
        "q2": "QUEST MODS BG2", "q1": "QUEST MODS BG1"}


def test_the_install_before_the_eet_core_is_not_placed_by_kind(tmp_path):
    index = krion(tmp_path)
    plan = plan_order([(log(tmp_path, "bg1ub", "newui", name="WeiDU-BGEE.log"),
                        PRE_EET_LOG), (log(tmp_path, "EET"), EET_LOG)], index,
                      kinds={"newui": UI})
    assert order(plan, PRE_EET_LOG) == ["bg1ub", "newui"]
    assert plan.by_kind == [] and plan.phase_notes == []


def test_the_summary_names_what_its_kind_placed(tmp_path):
    index = krion(tmp_path)
    plan = plan_order([(log(tmp_path, "EET", "newui"), EET_LOG)], index,
                      kinds={"newui": UI})
    out = io.StringIO()
    render_plan_summary(plan, str(tmp_path), out)
    assert "placed by kind (1)" in out.getvalue()
    assert "INTERFACE" in out.getvalue()


def test_every_kind_must_decide_the_same_place():
    assert place(KindHint(("kit", "recruitable NPC")))[0] is None
    assert place(KindHint(("quest", "gameplay")))[0] is None
    assert place(KindHint(("recruitable NPC", "one-day NPC")))[0] == "NEW NPC MODS"
    assert place(KindHint(()))[0] is None
    # a label no table knows decides nothing
    assert place(KindHint(("Catégorie nouvelle",)))[0] is None


TWEAK = KindHint(("gameplay",), (), ("lcc-docs",))


def test_a_mod_with_no_place_is_not_dragged_behind_one_its_kind_moved(tmp_path):
    """Review of #67 (B1): tweak inherited newui's place by kind and moved
    with it, while the plan said it stayed where it was chosen."""
    index = krion(tmp_path)
    eet = log(tmp_path, "EET", "stratagems", "newui", "tweak")
    plan = plan_order([(eet, EET_LOG)], index, kinds={"newui": UI, "tweak": TWEAK})
    assert order(plan) == ["eet", "newui", "stratagems", "tweak"]
    assert "tweak" not in {move.key for move in plan.moved}


def test_a_single_games_log_is_placed_by_kind_too(tmp_path):
    """Review of #67 (H1): a BG2:EE log has the pre-EET role, but is not the
    phase before an EET conversion."""
    index = krion(tmp_path)
    alone = log(tmp_path, "stratagems", "newui", name="WeiDU-BG2.log")
    plan = plan_order([(alone, PRE_EET_LOG)], index, kinds={"newui": UI})
    assert order(plan, PRE_EET_LOG) == ["newui", "stratagems"]
    assert [name for name, _category, _why in plan.by_kind] == ["newui"]


def test_a_split_mod_keeps_its_reason_in_every_part(tmp_path):
    """Review of #67 (M1): parts of a split mod lost the reason."""
    index = krion(tmp_path)
    rules = tmp_path / "order.json"
    rules.write_text(json.dumps([{"rule": "tweak(1):stratagems", "direction": "after"}]),
                     encoding="utf-8")
    eet = tmp_path / "WeiDU.log"
    eet.write_text(HEADER + "~EET\\EET.tp2~ #0 #0 // EET\n"
                   "~tweak\\tweak.tp2~ #0 #0 // a\n~tweak\\tweak.tp2~ #0 #1 // b\n"
                   "~stratagems\\stratagems.tp2~ #0 #0 // s\n", encoding="utf-8")
    plan = plan_order([(str(eet), EET_LOG)], index, RuleSet.load([str(rules)]),
                      kinds={"tweak": TWEAK})
    parts = [u for u in plan.logs[EET_LOG] if u.key == "tweak"]
    assert len(parts) == 2
    assert all(u.no_place.startswith("no place: its kind does not decide") for u in parts)


def test_a_mod_in_both_installs_has_the_reason_only_where_it_was_asked(tmp_path):
    """Review of #67 (M2): one display name, two logs."""
    index = krion(tmp_path)
    plan = plan_order([(log(tmp_path, "bg1ub", "tweak", name="WeiDU-BGEE.log"), PRE_EET_LOG),
                       (log(tmp_path, "EET", "tweak"), EET_LOG)], index,
                      kinds={"tweak": TWEAK})
    before = next(u for u in plan.logs[PRE_EET_LOG] if u.key == "tweak")
    after = next(u for u in plan.logs[EET_LOG] if u.key == "tweak")
    assert before.no_place == "" and after.no_place
    assert [entry[0] for entry in plan.no_place] == [EET_LOG]


def test_a_folders_kind_is_not_given_to_a_second_tp2_in_it(tmp_path):
    """Review of #67 (L2): EET_end lives in EET's folder."""
    index = krion(tmp_path)
    eet = tmp_path / "WeiDU.log"
    eet.write_text(HEADER + "~pack\\one.tp2~ #0 #0 // one\n~pack\\two.tp2~ #0 #0 // two\n",
                   encoding="utf-8")
    plan = plan_order([(str(eet), EET_LOG)], index, kinds={"pack": UI})
    assert plan.by_kind == []
    alone = tmp_path / "solo.log"
    alone.write_text(HEADER + "~pack\\setup-other.tp2~ #0 #0 // one\n", encoding="utf-8")
    plan = plan_order([(str(alone), EET_LOG)], index, kinds={"pack": UI})
    assert [name for name, _c, _w in plan.by_kind] == ["pack/other"]


# ------------------------------------- BWS-NG's sequence first (decision 2a)
from iemod_fetch.ordering import bws_sequence  # noqa: E402

SEQUENCE = [("eet", 0), ("leui", 10), ("seqone", 0), ("seqtwo", 5), ("newhud", 0),
            ("stratagems", 10), ("newui", 0), ("tactix", 0)]


def test_bws_ngs_sequence_places_a_mod_right_after_the_one_before_it(tmp_path):
    index = krion(tmp_path)
    eet = log(tmp_path, "EET", "stratagems", "seqtwo", "LeUI", "seqone")
    plan = plan_order([(eet, EET_LOG)], index, sequence=SEQUENCE)
    # after LeUI, in BWS-NG's order between themselves, before stratagems
    assert order(plan) == ["eet", "leui", "seqone", "seqtwo", "stratagems"]
    assert [entry[0] for entry in plan.by_sequence] == ["seqtwo", "seqone"]
    assert plan.by_sequence[0][2] == "placed by BWS-NG's EET sequence: after leui #10"


def test_the_sequence_comes_before_the_kind(tmp_path):
    index = krion(tmp_path)
    eet = log(tmp_path, "EET", "LeUI", "stratagems", "newui")
    plan = plan_order([(eet, EET_LOG)], index, kinds={"newui": UI}, sequence=SEQUENCE)
    assert order(plan) == ["eet", "leui", "stratagems", "newui"]   # not INTERFACE
    assert plan.by_kind == [] and [e[0] for e in plan.by_sequence] == ["newui"]


def test_the_sequence_places_nothing_before_the_eet_core(tmp_path):
    index = krion(tmp_path)
    plan = plan_order([(log(tmp_path, "bg1ub", "seqone", name="WeiDU-BGEE.log"), PRE_EET_LOG),
                       (log(tmp_path, "EET"), EET_LOG)], index, sequence=SEQUENCE)
    assert order(plan, PRE_EET_LOG) == ["bg1ub", "seqone"] and plan.by_sequence == []


def test_a_mod_with_no_place_stays_behind_one_the_sequence_moved(tmp_path):
    index = krion(tmp_path)
    eet = log(tmp_path, "EET", "stratagems", "seqone", "tweak")
    plan = plan_order([(eet, EET_LOG)], index, kinds={"tweak": TWEAK}, sequence=SEQUENCE)
    assert order(plan) == ["eet", "seqone", "stratagems", "tweak"]


def test_the_summary_names_what_the_sequence_placed(tmp_path):
    index = krion(tmp_path)
    plan = plan_order([(log(tmp_path, "EET", "seqone"), EET_LOG)], index, sequence=SEQUENCE)
    out = io.StringIO()
    render_plan_summary(plan, str(tmp_path), out)
    assert "placed by BWS-NG's EET sequence (1)" in out.getvalue()


def test_bws_ngs_eet_json_is_read_as_its_bg2ee_order():
    eet = {"sequences": [{"game": "sod", "order": ["bg1ub:0"]},
                         {"game": "bg2ee", "order": ["weidu:0", "EET:0", "A7-Recolor:10",
                                                     "broken", "x:y"]}]}
    assert bws_sequence(eet) == [("weidu", 0), ("eet", 0), ("a7recolor", 10)]
    assert bws_sequence(None) == [] and bws_sequence({"sequences": "no"}) == []


def test_where_bws_ngs_neighbours_disagree_the_sequence_decides_nothing(tmp_path):
    """Review of #71 (F1): krion64 places whole mods, so the component before
    and the one after can sit in different categories - then the kind, or
    no place, and the reason says why."""
    index = krion(tmp_path)
    mixed = [("eet", 0), ("leui", 10), ("newui", 0), ("stratagems", 10)]
    eet = log(tmp_path, "EET", "stratagems", "newui")
    placed = plan_order([(eet, EET_LOG)], index, kinds={"newui": UI}, sequence=mixed)
    assert placed.by_sequence == []
    newui = next(u for u in placed.logs[EET_LOG] if u.key == "newui")
    assert newui.placed_from == "kind"
    assert "BWS-NG's neighbours disagree (leui in INTERFACE, stratagems in TACTICAL MODS)" \
        in newui.placed_by
    unplaced = plan_order([(eet, EET_LOG)], index, sequence=mixed)
    assert unplaced.no_place == [(EET_LOG, "newui", ("BWS-NG's neighbours disagree "
                                  "(leui in INTERFACE, stratagems in TACTICAL MODS)"))]


def test_what_bws_ng_installs_before_the_eet_core_is_not_moved_after_it(tmp_path):
    """Review of #71 (F3): bws-fr-fixpack and the like come before eet:0."""
    index = krion(tmp_path)
    precore = [("leui", 10), ("precore", 0), ("eet", 0), ("stratagems", 10)]
    plan = plan_order([(log(tmp_path, "precore", "EET", "stratagems"), EET_LOG)], index,
                      sequence=precore)
    assert order(plan) == ["precore", "eet", "stratagems"]
    assert plan.by_sequence == []


def test_a_neighbour_counts_only_where_krion64_puts_its_mod(tmp_path):
    """Review of #71 (F1): bws-fr-fixpack's #1 is at the end of BWS-NG's
    order, krion64 places the mod where its #0 is; and with nothing after
    it the sequence cannot check the neighbour before."""
    index = krion(tmp_path)
    late = [("eet", 0), ("leui", 10), ("stratagems", 10), ("leui", 30), ("late", 0),
            ("tactix", 0)]
    plan = plan_order([(log(tmp_path, "EET", "stratagems", "late"), EET_LOG)], index,
                      sequence=late)
    assert [entry[2] for entry in plan.by_sequence] == [
        "placed by BWS-NG's EET sequence: after stratagems #10"]
    last = [("eet", 0), ("stratagems", 10), ("last", 0)]
    plan = plan_order([(log(tmp_path, "EET", "last", "stratagems"), EET_LOG)], index,
                      sequence=last)
    assert plan.by_sequence == [] and order(plan) == ["eet", "last", "stratagems"]
    assert plan.no_place[0][2] == "BWS-NG places nothing krion64 knows after it"
