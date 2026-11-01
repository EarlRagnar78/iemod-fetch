"""
tools/order_sources_benchmark.py (GUI-AUDIT M5 item 25): each source's kind of
mod and install place, measured. Fixtures in the shape of the real files -
krion64's (the Infinity Mod Forge's) data/, BWS-NG's data/ (written by hand to
its schema: its data is GPL and not bundled), lcc-docs' db/mods.json.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "tools"))

import order_sources_benchmark as bench  # noqa: E402


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def sources(tmp_path):
    krion = tmp_path / "krion"
    write(krion / "categories.json", {"categories": {
        "INTERFACE": {}, "QUEST MODS BG2": {}, "KIT & CLASS MODS": {}, "PORTRAITS": {}}})
    write(krion / "mods" / "ui.json", {"t": "ui", "c": "INTERFACE", "ord": 1, "tags": ["ui"],
                                      "co": [{"cn": 0, "wp": "ui/setup-ui.tp2"}]})
    write(krion / "mods" / "quest.json", {"t": "quest", "c": "QUEST MODS BG2", "ord": 1,
                                         "co": [{"cn": 0, "wp": "quest/quest.tp2"},
                                                {"cn": 9, "wp": "quest/quest.tp2",
                                                 "cat": "PORTRAITS"}]})
    write(krion / "mods" / "kits.json", {"t": "kits", "c": "KIT & CLASS MODS", "ord": 1,
                                        "co": [{"cn": 0, "wp": "kits/setup-kits.tp2"}]})
    bws = tmp_path / "bws"
    write(bws / "mods" / "ui.json", {"tp2": "ui", "categories": ["ui"]})
    write(bws / "mods" / "kits.json", {"tp2": "kits", "categories": ["kit"]})
    write(bws / "mods" / "lonely.json", {"tp2": "lonely", "categories": ["npc"]})
    write(bws / "mods" / "weidu.json", {"tp2": "", "categories": []})        # a tool
    # BWS-NG puts kits before the quest, krion64 the other way round
    write(bws / "games" / "eet.json", {"sequences": [
        {"game": "sod", "order": ["eefixpack:0"]},
        {"game": "bg2ee", "order": ["weidu:0", "ui:0", "kits:0", "quest:0", "lonely:0",
                                    "kits:0"]}]})          # listed twice: first place kept
    lcc = tmp_path / "lcc.json"
    write(lcc, {"mods": [
        {"tp2": "ui", "games": ["EET"], "categories": ["Interface"]},
        {"tp2": "only-lcc;other", "games": ["BG2EE"], "categories": ["Quête"]},
        {"tp2": "classic", "games": ["BG2"], "categories": ["Kit"]},      # not EE
        {"tp2": "non-weidu", "games": ["EET"], "categories": ["Utilitaire"]}]})
    return str(krion), str(bws), str(lcc)


def test_each_source_is_read_by_tp2_with_its_categories(tmp_path):
    krion, bws, lcc = sources(tmp_path)
    k, b, l_ = bench.krion(krion), bench.bws(bws), bench.lcc(lcc)
    assert k["mods"] == {"ui": "INTERFACE", "quest": "QUEST MODS BG2",
                         "kits": "KIT & CLASS MODS"}
    assert k["apart"] == 1 and k["tags"]["ui"] == 1
    assert b["mods"]["kits"] == ("kit",) and "weidu" not in b["mods"] and b["skipped"] == 1
    # BG2 phase only (eefixpack is SoD's), kits once at its first place
    assert b["sequence"] == {("weidu", 0): 0, ("ui", 0): 1, ("kits", 0): 2,
                             ("quest", 0): 3, ("lonely", 0): 4}
    assert set(l_["mods"]) == {"ui", "onlylcc", "other"}   # EE only; non-weidu dropped


def test_the_measures_say_what_differs(tmp_path):
    krion, bws, lcc = sources(tmp_path)
    log = tmp_path / "WeiDU.log"
    log.write_text("// Log of Currently Installed WeiDU Mods\n// made by hand\n"
                   "~UI\\SETUP-UI.TP2~ #0 #0 // UI\n"
                   "~QUEST\\QUEST.TP2~ #0 #0 // Quest\n"
                   "~KITS\\SETUP-KITS.TP2~ #0 #0 // Kits\n"
                   "~NOBODY\\NOBODY.TP2~ #0 #0 // Nobody\n", encoding="utf-8")
    result = bench.measure(bench.krion(krion), bench.bws(bws), bench.lcc(lcc), str(log))
    assert result["overlap"]["bws_not_krion64"] == 1                    # lonely
    assert result["bws_sequence_mods"] == {"mods": 5, "not_placed_by_krion64": ["lonely"],
                                           "tools_left_out": ["weidu"]}
    assert result["mapping_to_krion64"]["bws_ng"]["kit"] == {"KIT & CLASS MODS": 1}
    assert result["mapping_to_krion64"]["lcc_docs"]["Interface"] == {"INTERFACE": 1}
    # ui, kits, quest by BWS-NG; ui, quest, kits by krion64: one pair of three
    assert result["bws_vs_krion64"] == {"components_both_place": 3, "pairs": 3,
                                        "reversed": 1, "share": 0.3333,
                                        "tied_in_krion64": 0, "share_without_ties": 0.3333}
    log_result = result["log"]
    assert log_result["head"][1] == "// made by hand"
    assert log_result["krion64"]["reversed_vs_log"] == 0
    assert log_result["bws_ng"]["reversed_vs_log"] == 1
    assert log_result["mods_placed_by_neither"] == ["nobody"]


def test_disagreement_counts_reversed_pairs():
    assert bench.disagreement([0, 1, 2, 3], [0, 1, 2, 3]) == (0, 6)
    assert bench.disagreement([0, 1, 2, 3], [3, 2, 1, 0]) == (6, 6)
    assert bench.disagreement([0, 1, 2], [0, 2, 1]) == (1, 3)
    assert bench.disagreement([0, 1], [5, 5]) == (0, 1)     # a tie is not reversed
    assert bench.ties([5, 5, 5, 7]) == 3


def test_the_report_prints_and_writes_json(tmp_path, capsys):
    krion, bws, lcc = sources(tmp_path)
    out = tmp_path / "out.json"
    assert bench.main([krion, bws, lcc, "--json", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "BWS-NG sequence vs krion64 order" in printed
    assert json.loads(out.read_text())["krion64"]["mods"] == 3


def test_a_tp2_name_with_dots_is_one_mod(tmp_path):
    # Review of #47: "www.urstuff2athkatla" was keyed "www"
    krion = tmp_path / "krion"
    write(krion / "categories.json", {"categories": {"QUEST MODS BG2": {}}})
    write(krion / "mods" / "www.json", {"t": "www.urstuff2athkatla", "c": "QUEST MODS BG2",
                                       "ord": 1, "co": [{"cn": 0, "wp":
                                       "www.urstuff2athkatla/www.urstuff2athkatla.tp2"}]})
    assert list(bench.krion(str(krion))["mods"]) == ["wwwurstuff2athkatla"]
