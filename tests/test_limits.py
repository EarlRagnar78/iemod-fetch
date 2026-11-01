"""
Engine limits (ADR-0034): kits, spell states, spell slots per level.

The numbers are the primary sources' (WeiDU's ADD_KIT and ADD_SPELL, EEex,
IESDP), not Infinity Mod Forge's; what a component adds is krion64's count.
"""
import io
import json
import os

from iemod_fetch import api
from iemod_fetch.limits import KITS, SPELL_STATES, engine_limits
from iemod_fetch.ordering import tp2_key

HERE = os.path.dirname(__file__)


def record(t, components, **extra):
    return {"t": t, "co": components, **extra}


def kits_of(report):
    return report.tallies[0]


def test_kits_are_counted_against_weidus_256_not_forges_320():
    records = [record("dof", [{"cn": 0, "k": 15}, {"cn": 3, "k": 1}])]
    report = engine_limits("EET", [("dof", 0), ("dof", 3)], records)
    kits = kits_of(report)
    assert (kits.base, kits.added, kits.total, kits.cap) == (40, 16, 56, 256)
    assert kits.severity is None and "320" in kits.note
    assert KITS.forge_cap == 320 and KITS.cap == 256


def test_a_kit_table_near_or_past_its_end_warns_or_errs():
    near = engine_limits("EET", [("big", 0)], [record("big", [{"cn": 0, "k": 191}])])
    assert kits_of(near).total == 231 and kits_of(near).severity == "warning"
    past = engine_limits("EET", [("big", 0)], [record("big", [{"cn": 0, "k": 217}])])
    assert kits_of(past).total == 257 and kits_of(past).severity == "error"


def test_a_mod_krion64_does_not_know_is_named_never_counted_as_zero():
    report = engine_limits("EET", [("known", 0), ("mystery", 1)],
                           [record("known", [{"cn": 0}])])
    assert report.unknown_mods == ["mystery"]
    assert "at least" in report.render()


def test_spell_states_are_shown_but_never_warned_on():
    """krion64 counts EE Fixpack 19 - references it only looks up."""
    report = engine_limits("EET", [("eefixpack", 1)],
                           [record("eefixpack", [{"cn": 1, "ss": 200}])])
    states = report.tallies[1]
    assert states.total > states.cap and states.severity is None
    assert not states.checked and "references" in states.note
    assert SPELL_STATES.forge_base == 128


def test_eeex_lifts_the_spell_state_range():
    report = engine_limits("EET", [], [], eeex=True)
    assert report.tallies[1].cap > 10 ** 9 and "EEex" in report.tallies[1].note


def test_spells_are_counted_per_type_and_level():
    records = [record("ctb", [{"cn": 0, "spLv": {"w1": 1, "w6": 4}}]),
               record("x", [{"cn": 0, "spLv": {"w6": 30}}])]
    report = engine_limits("EET", [("ctb", 0), ("x", 0)], records)
    level6 = next(t for t in report.tallies if t.label.startswith("wizard level 6"))
    assert (level6.base, level6.added, level6.total, level6.cap) == (20, 34, 54, 50)
    assert level6.severity == "error"
    assert not any(t.label.startswith("priest") for t in report.tallies)   # nothing added


def test_spells_without_levels_are_reported_not_guessed():
    report = engine_limits("EET", [("m", 0)], [record("m", [{"cn": 0, "sp": 7}])])
    assert report.unlevelled_spells == 7
    assert "not counted against a level" in report.render()


def test_components_are_matched_by_weidu_number_and_tp2():
    records = [record("Sword Coast Stratagems", [
        {"cn": 5, "wc": 4100, "wf": "stratagems", "wp": "stratagems\\setup-stratagems.tp2",
         "k": 2}])]
    report = engine_limits("EET", [("stratagems", 4100)], records)
    assert kits_of(report).added == 2 and report.unknown_mods == []


def test_two_tp2s_in_one_folder_keep_their_own_counts():
    """krion64's EET_end shares EET's folder and component number 0."""
    records = [record("EET_end", [{"cn": 0, "wf": "eet", "wp": "eet\\EET_end\\EET_end.tp2",
                                   "k": 5}]),
               record("EET", [{"cn": 0, "wf": "eet", "wp": "eet\\EET.tp2", "k": 0}])]
    assert kits_of(engine_limits("EET", [("eet", 0)], records)).added == 0
    assert kits_of(engine_limits("EET", [(tp2_key("eet/EET_end/EET_end.tp2"), 0)], records)).added == 5


def test_malformed_records_are_skipped_never_stop_the_report():
    records = [None, "x", {"co": "abc"}, {"co": {"a": 1}}, {"t": ["list"], "co": [{"cn": 0}]},
               record("m", ["str", {"cn": True, "k": 4}, {"cn": 0, "k": 1}])]
    report = engine_limits("EET", [("m", 0), ("m", 1)], records)
    assert kits_of(report).added == 1


def test_a_component_listed_twice_is_counted_once():
    report = engine_limits("EET", [("m", 0), ("m", 0)], [record("m", [{"cn": 0, "k": 5}])])
    assert kits_of(report).added == 5 and report.components == 1


def test_a_mod_level_spell_state_count_belongs_to_its_first_component():
    records = [record("m", [{"cn": 0}, {"cn": 1}], ss=3)]
    assert engine_limits("EET", [("m", 0)], records).tallies[1].added == 3
    assert engine_limits("EET", [("m", 1)], records).tallies[1].added == 0


def test_the_conflict_report_carries_the_limits(tmp_path):
    log = tmp_path / "WeiDU.log"
    log.write_text("~stratagems/setup-stratagems.tp2~ #0 #4100 // x\n")
    krion = tmp_path / "krion"
    (krion / "mods").mkdir(parents=True)
    (krion / "categories.json").write_text(json.dumps({"categories": {"A": {}}}))
    (krion / "mods" / "stratagems.json").write_text(json.dumps(
        {"t": "stratagems", "ord": 1, "co": [{"cn": 4100, "k": 3}]}))
    (tmp_path / "rules").mkdir()
    out = io.StringIO()
    report_path = tmp_path / "conflicts.json"
    api.run(api.Settings(weidu_log=[f"{log}:EET"], check_only=True,
                         rules=[str(tmp_path / "rules")], order_catalogue=str(krion),
                         conflict_report=str(report_path), no_update_data=True,
                         no_default_data=True,
                         manifest=os.path.join(HERE, "data", "mod_downloads.json")),
            stream=out)
    (limits,) = json.loads(report_path.read_text())["engine_limits"]
    assert limits["install"] == "EET"
    assert limits["tables"][0]["total"] == 43
    assert "ENGINE LIMITS" in out.getvalue()


# ------------------------------------------------- measured in the game folder
import struct  # noqa: E402

from iemod_fetch import gamedir  # noqa: E402
from iemod_fetch.limits import (Measured, kits_in_use, spell_slots_taken,  # noqa: E402
                                spell_states_in_use)

KITLIST = ("2DA V1.0\n*\n     ROWNAME LOWER MIXED HELP ABILITIES PROFICIENCY UNUSABLE CLASS\n"
           "0  RESERVE 0 0 0 * 0 0x00000000 0\n1  BERSERKER 1 2 3 CLABFI02 1 0x4000 2\n"
           "40 DARK_MOON 1 2 3 CLABTH05 1 0x4000 4\n")
KITLIST_EX = KITLIST + "41 * *\n42 * *\n"
SPELL_IDS = "IDS V1.0\n3\n2101 WIZARD_ONE\n2102 WIZARD_TWO\n1101 CLERIC_ONE\n3101 PSIONIC\n"


def test_the_next_kit_number_is_found_as_weidu_finds_it():
    assert kits_in_use(KITLIST) == 40          # get_next_kit_number would give 41
    assert kits_in_use(KITLIST_EX) == 40       # the first `N * *` row is next


def test_a_spell_slot_is_taken_when_add_spell_would_skip_it():
    """TB#ADD_SPELL_FIND_SLOT: SPELL.IDS, ADD_SPELL.IDS, or an SPWI/SPPR file."""
    taken = spell_slots_taken(SPELL_IDS, "2103 WIZARD_THREE\n", ["SPWI104", "sppr101", "x"])
    assert taken == {"w1": 4, "p1": 1}         # 2101, 2102, 2103, spwi104; 1101 = sppr101


def test_spell_states_count_ids_0_to_255_once():
    assert spell_states_in_use("IDS V1.0\n0 NONE\n1 A\n1 A_AGAIN\n0x10 B\n300 HIGH\n") == 3


def bif(resources):
    """A real BIFF V1 file: (data) in order; locators 0..n-1."""
    table = 20
    data_at = table + 16 * len(resources)
    entries, blobs, offset = b"", b"", data_at
    for i, (kind, blob) in enumerate(resources):
        entries += struct.pack("<IIIHH", i, offset, len(blob), kind, 0)
        blobs += blob
        offset += len(blob)
    return b"BIFFV1  " + struct.pack("<III", len(resources), 0, table) + entries + blobs


def key(bif_name, resources):
    """KEY V1 with one BIF: (resref, type) at locator index i."""
    name = bif_name.encode() + b"\0"
    bif_at = 24
    name_at = bif_at + 12
    res_at = name_at + len(name)
    header = b"KEY V1  " + struct.pack("<IIII", 1, len(resources), bif_at, res_at)
    bifs = struct.pack("<IIHH", 0, name_at, len(name), 1)
    body = b"".join(r.encode().ljust(8, b"\0") + struct.pack("<HI", kind, i)
                    for i, (r, kind) in enumerate(resources))
    return header + bifs + name + body


def a_game(root, override=None, log=None):
    (root / "data").mkdir(parents=True)
    (root / "override").mkdir()
    (root / "data" / "Default.bif").write_bytes(bif([(0x3F4, KITLIST.encode()),
                                                     (0x3F0, SPELL_IDS.encode()),
                                                     (0x3EE, b"SPL V1  ")]))
    (root / "chitin.key").write_bytes(key("data\\Default.bif", [
        ("KITLIST", 0x3F4), ("SPELL", 0x3F0), ("SPWI105", 0x3EE)]))
    for name, text in (override or {}).items():
        (root / "override" / name).write_bytes(text.encode())   # exact bytes, on Windows too
    if log is not None:
        (root / "WeiDU.log").write_text(log)
    return str(root)


def test_resources_are_read_from_override_first_then_the_biff(tmp_path):
    game = a_game(tmp_path / "g", override={"SPLSTATE.IDS": "IDS V1.0\n0 A\n"})
    assert gamedir.read_resource(game, "kitlist.2da").decode() == KITLIST
    assert gamedir.read_resource(game, "SPELL.IDS").decode() == SPELL_IDS
    assert gamedir.read_resource(game, "splstate.ids") == b"IDS V1.0\n0 A\n"
    assert gamedir.read_resource(game, "missing.2da") is None
    assert "spwi105" in gamedir.spell_files(game)


def test_a_measured_table_replaces_the_estimate_and_skips_what_is_installed():
    measured = Measured(kits=250, spell_slots={"w1": 49}, spell_states=200)
    records = [record("old", [{"cn": 0, "wp": "old/old.tp2", "k": 30, "ss": 9,
                               "spLv": {"w1": 9}}]),
               record("new", [{"cn": 0, "wp": "new/new.tp2", "k": 7, "spLv": {"w1": 2}}])]
    report = engine_limits("BG2EE", [("old", 0), ("new", 0)], records,
                           measured=measured, installed=[("old", 0)], measured_from="/g")
    kits = kits_of(report)
    assert (kits.base, kits.added, kits.total, kits.measured) == (250, 7, 257, True)
    assert kits.severity == "error"
    states = report.tallies[1]
    assert (states.base, states.added, states.checked) == (200, 0, True)   # measured: warned on
    w1 = next(t for t in report.tallies if t.label.startswith("wizard level 1"))
    assert (w1.base, w1.added, w1.severity) == (49, 2, "error")
    assert "measured in /g" in report.render()


def test_a_game_folder_beside_the_log_is_measured(tmp_path):
    log = "~OLD/OLD.TP2~ #0 #0 // Old\n"
    game = a_game(tmp_path / "g", log=log,
                  override={"SPLSTATE.IDS": "IDS V1.0\n0 A\n1 B\n"})
    report_path = tmp_path / "conflicts.json"
    (tmp_path / "rules").mkdir()
    api.run(api.Settings(weidu_log=[os.path.join(game, "WeiDU.log") + ":BG2EE"],
                         check_only=True, quiet=True, conflict_report=str(report_path),
                         rules=[str(tmp_path / "rules")], no_update_data=True,
                         no_default_data=True,
                         manifest=os.path.join(HERE, "data", "mod_downloads.json")))
    (limits,) = json.loads(report_path.read_text())["engine_limits"]
    assert limits["measured_from"] == game
    tables = {t["label"]: t for t in limits["tables"]}
    assert tables["kits (KITLIST.2DA)"]["total"] == 40
    assert tables["spell states (SPLSTATE.IDS)"]["total"] == 2
    assert tables["wizard level 1 spells (SPELL.IDS)"]["total"] == 3     # 2101, 2102, spwi105


def test_a_biff_path_that_leaves_the_game_folder_is_not_followed(tmp_path):
    outside = tmp_path / "outside.bif"
    outside.write_bytes(bif([(0x3F4, KITLIST.encode())]))
    for name in ("..\\outside.bif", "C:\\outside.bif", "data\\..\\..\\outside.bif"):
        root = tmp_path / f"g{abs(hash(name))}"
        root.mkdir()
        (root / "chitin.key").write_bytes(key(name, [("KITLIST", 0x3F4)]))
        assert gamedir.read_resource(str(root), "kitlist.2da") is None


def test_a_damaged_key_or_biff_is_not_measured_and_does_not_stop_the_report(tmp_path):
    game = a_game(tmp_path / "g")
    with open(os.path.join(game, "data", "Default.bif"), "r+b") as fh:
        fh.truncate(30)
    measured, _installed = api._measure_game(game)
    assert measured.kits is None and measured.spell_slots is None


def test_ids_are_read_as_weidus_lexer_reads_them():
    from iemod_fetch.limits import ids_numbers
    assert ids_numbers("IDS V1.0\r2101 A\r2102 B\r") == [2101, 2102]          # CR only
    assert ids_numbers("IDS V1.0\n/* 2101 A */\n2102 B // 2103 C\n") == [2102]


def test_a_kitlist_ending_in_a_bare_row_number_is_read_as_weidu_reads_it():
    assert kits_in_use("2DA V1.0\n*\n  A\n1  A\n42") == 42
    assert kits_in_use(KITLIST.replace("\n", "\r\n") + "\r\n\r\n") == 40


def test_a_biff_whose_table_runs_past_its_end_is_not_read(tmp_path):
    game = a_game(tmp_path / "g")
    path = os.path.join(game, "data", "Default.bif")
    with open(path, "r+b") as fh:
        fh.seek(8)
        fh.write(struct.pack("<I", 0xFFFFFFFF))
    assert gamedir.read_resource(game, "kitlist.2da") is None
    assert api._measure_game(game)[0].kits is None


def test_an_encrypted_table_is_not_read_as_an_empty_one(tmp_path):
    game = a_game(tmp_path / "g")
    (tmp_path / "g" / "override" / "SPELL.IDS").write_bytes(b"\xff\xff" + b"\x10" * 40)
    assert gamedir.read_resource(game, "spell.ids") is None
    assert api._measure_game(game)[0].spell_slots is None
