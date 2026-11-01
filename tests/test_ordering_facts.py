"""
Ordering facts as planner regression tests (GUI-AUDIT M8 item 70), checked
against the community data the planner reads - BWS-NG's rules and krion64's
ordering index - not written into it. Each fact comes from Chriz Easy BG's
curation notes (`docs/curation/components/*.md`, MIT, at 508256a) and is a
test only where our data says it too; what our data does not say is listed
in GUI-AUDIT item 70 and not made up here.

Each test gives the planner a log in the wrong order and checks the order it
plans, and that the data still holds the rule or the place it rests on: when
upstream drops it, the test says so instead of passing by luck.

Opt-in, like the real binaries: IEMOD_FACTS_DATA=<a data cache, as
`iemod-fetch --update-data` fills it>. The community-data workflow runs it on
the data it has just fetched.
"""
import os

import pytest

from iemod_fetch.datasync import data_paths
from iemod_fetch.ordering import EET_LOG, OrderIndex, plan_order, tp2_key
from iemod_fetch.rules import RuleSet

DATA = os.environ.get("IEMOD_FACTS_DATA", "")
pytestmark = pytest.mark.skipif(not os.path.isdir(DATA),
                                reason="no community data (IEMOD_FACTS_DATA)")
HEADER = "// Log of Currently Installed WeiDU Mods\n"


@pytest.fixture(scope="module")
def data():
    paths = data_paths(DATA)
    return OrderIndex.load(paths.order_catalogue), RuleSet.load(paths.rules)


def planned(tmp_path, data, tp2s):
    """The planner's order for one component of each tp2, given in this order."""
    index, ruleset = data
    log = tmp_path / "WeiDU.log"
    log.write_text(HEADER + "".join(f"~{tp2}~ #0 #0 // {tp2}\n" for tp2 in tp2s),
                   encoding="utf-8")
    plan = plan_order([(str(log), EET_LOG)], index, ruleset)
    return [tp2_key(entry.split("~")[1]) for unit in plan.logs[EET_LOG]
            for entry in unit.render()]


def rule(data, left, right, direction):
    """An order rule of the data: `left` `direction` `right`."""
    _index, ruleset = data
    return any(r.kind == "order" and r.direction == direction and r.left.mod == left
               and right in {s.mod for s in r.right} for r in ruleset.rules)


def test_bg1npc_goes_before_eet_end(tmp_path, data):
    """CEBG BG1NPC.md: BG1NPC refuses to install after EET_end."""
    assert rule(data, "bg1npc", "eetend", "before"), "BWS-NG no longer orders it"
    order = planned(tmp_path, data, ["EET/EET_end/EET_end.tp2", "bg1npc/bg1npc.tp2"])
    assert order.index("bg1npc") < order.index("eetend")


def test_ascension_goes_before_spell_revisions_and_scs(tmp_path, data):
    """CEBG ASCENSION.md: Ascension before Spell Revisions and SCS."""
    assert rule(data, "ascension", "spellrev", "before")
    assert rule(data, "ascension", "stratagems", "before")
    order = planned(tmp_path, data, ["stratagems/setup-stratagems.tp2",
                                     "spell_rev/setup-spell_rev.tp2",
                                     "ascension/ascension.tp2"])
    assert order.index("ascension") < order.index("spellrev")
    assert order.index("ascension") < order.index("stratagems")


def test_bubbs_spell_menu_goes_after_a_ui_replacement(tmp_path, data):
    """CEBG BUBB_SPELL_MENU_EXTENDED.md: after any UI replacement."""
    for ui in ("leui", "dragonspearui", "eetgui"):
        assert rule(data, "bubbspellmenuextended", ui, "after"), ui
    order = planned(tmp_path, data, ["bubb_spell_menu_extended/bubb_spell_menu_extended.tp2",
                                     "LeUI/LeUI.tp2"])
    assert order.index("leui") < order.index("bubbspellmenuextended")


def test_crossmod_goes_after_yeslick_by_their_places(tmp_path, data):
    """CEBG CROSSMODBG2.md: Crossmod v30's own After= leaves out Yeslick. No
    rule of ours names the pair either; krion64's places put an NPC mod
    (NEW NPC MODS) before the crossmod (NPC CROSSMOD), and that is what
    holds it."""
    index, _ruleset = data
    yeslick, crossmod = index.get("yeslicknpc"), index.get("crossmodbg2")
    assert yeslick and crossmod and yeslick.rank < crossmod.rank
    order = planned(tmp_path, data, ["crossmodbg2/setup-crossmodbg2.tp2",
                                     "yeslicknpc/setup-yeslicknpc.tp2"])
    assert order.index("yeslicknpc") < order.index("crossmodbg2")


def test_artisans_kitpack_goes_after_item_mods_by_its_place(tmp_path, data):
    """CEBG ARTISANSKITPACK.md: its kits after item mods (20101/12012). Our
    data has it at mod level only - krion64's KIT & CLASS MODS after ITEM
    ADDITION MODS; the component-level facts are not in it (item 70)."""
    index, _ruleset = data
    kits, items = index.get("artisanskitpack"), index.get("itemrev")
    assert kits and items and items.rank < kits.rank
    order = planned(tmp_path, data, ["artisanskitpack/artisanskitpack.tp2",
                                     "item_rev/item_rev.tp2"])
    assert order.index("itemrev") < order.index("artisanskitpack")
