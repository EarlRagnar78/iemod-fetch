"""
tools/places_check.py, the live check of the kinds and the places (GUI-AUDIT
M5 item 29): a data cache written by hand in the sources' own shapes - BWS-NG's
is GPL and is never bundled, so its files here are made up to its schema.
"""
import json

from iemod_fetch.kinds import BG1_QUESTS, PLACES
from tools import places_check

# every category a kind places into, as krion64 has them
CATEGORIES = ["EET STARTS HERE", BG1_QUESTS, *dict.fromkeys(c for c, _s in PLACES.values())]


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def cache(root, lcc_label="Interface", bws_code="ui", order=("eet:0", "leui:0", "newui:0",
                                                               "otherui:0"),
          categories=tuple(CATEGORIES)):
    write(root / "lcc-docs" / "db" / "mods.json", [
        {"tp2": "newui", "name": "New UI", "categories": [lcc_label], "games": ["BG2EE"],
         "urls": []},
        {"tp2": "tweak", "name": "A tweak", "categories": ["Gameplay"], "games": ["BG2EE"],
         "urls": []}])
    write(root / "bws-ng" / "data" / "mods" / "newui.json",
          {"name": "New UI", "categories": [bws_code]})
    write(root / "bws-ng" / "data" / "games" / "eet.json",
          {"sequences": [{"game": "bg2ee", "order": list(order)}]})
    write(root / "krion64" / "data" / "categories.json",
          {"categories": {name: {} for name in categories}})
    for key, category in (("EET", "EET STARTS HERE"), ("LeUI", "INTERFACE"),
                          ("otherui", "INTERFACE")):
        write(root / "krion64" / "data" / "mods" / f"{key}.json",
              {"t": key, "c": category, "ord": 10})
    return str(root)


def test_the_live_data_as_expected_passes_and_counts_the_places(tmp_path, capsys):
    out = tmp_path / "out.json"
    assert places_check.main([cache(tmp_path), "--json", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["unknown labels"] == {"lcc-docs": [], "BWS-NG": []}
    assert result["places"] == {"with a kind, krion64 does not place": 2,
                                "by BWS-NG's sequence": 1, "by kind": 0, "no place": 1}


def test_a_category_the_tables_do_not_map_fails_and_is_named(tmp_path, capsys):
    root = cache(tmp_path, lcc_label="Nouvelle catégorie", bws_code="newcode")
    assert places_check.main([root]) == 1
    err = capsys.readouterr().err
    assert "lcc-docs uses categories kinds.py does not map: Nouvelle catégorie" in err
    assert "BWS-NG uses categories kinds.py does not map: newcode" in err


def test_a_sequence_without_the_eet_core_fails(tmp_path, capsys):
    assert places_check.main([cache(tmp_path, order=("leui:0", "newui:0"))]) == 1
    assert "no bg2ee sequence with eet:0" in capsys.readouterr().err


def test_a_cache_missing_a_source_fails(tmp_path, capsys):
    assert places_check.main([str(tmp_path)]) == 1


def test_inversions_count_the_pairs_ordered_the_other_way_round():
    sequence = [("a", 0), ("b", 0), ("c", 0)]
    assert places_check.inversions([("a", 0), ("b", 0), ("c", 0)], sequence) == (0, 3)
    assert places_check.inversions([("c", 0), ("a", 0), ("b", 0)], sequence) == (2, 3)
    assert places_check.inversions([("x", 1), ("b", 0)], sequence) == (0, 0)


def test_krion64_losing_a_category_a_kind_places_into_fails(tmp_path, capsys):
    """Review of #73: krion64 renaming QUEST MODS BG2 exited 0 while every BG2
    quest lost its place."""
    kept = [c for c in CATEGORIES if c != "QUEST MODS BG2"]
    assert places_check.main([cache(tmp_path, categories=kept)]) == 1
    assert "krion64 no longer has the categories kinds.py places into: QUEST MODS BG2" \
        in capsys.readouterr().err


def test_a_count_under_its_floor_fails(tmp_path, capsys):
    """Review of #73: lcc-docs renaming its `categories` key left 97 mods with
    a kind and exit 0; the workflow gives floors."""
    assert places_check.main([cache(tmp_path), "--min-kinds", "2"]) == 0
    assert places_check.main([cache(tmp_path), "--min-kinds", "3"]) == 1
    assert "a count collapsed (2, floor 3)" in capsys.readouterr().err
    assert places_check.main([cache(tmp_path), "--min-by-sequence", "2"]) == 1


def test_upstream_text_cannot_start_a_workflow_command_or_break_the_summary(tmp_path, capsys):
    """Review of #73: a label is the upstream's text."""
    label = "x\n::stop-commands::evil\n```<b>"
    summary = tmp_path / "summary.md"
    assert places_check.main([cache(tmp_path, lcc_label=label),
                              "--summary", str(summary)]) == 1
    err = capsys.readouterr().err
    assert not any(line.startswith("::stop-commands") for line in err.splitlines())
    assert "x%0A::stop-commands::evil%0A```<b>" in err
    text = summary.read_text(encoding="utf-8")
    assert "<b>" not in text and "&lt;b&gt;" in text and text.count("<pre>") == 1


def test_a_log_is_planned_without_and_with_the_places(tmp_path):
    root = cache(tmp_path)
    log = tmp_path / "WeiDU.log"
    log.write_text("~EET\\EET.tp2~ #0 #0 // EET\n~otherui\\otherui.tp2~ #0 #0 // o\n"
                   "~newui\\newui.tp2~ #0 #0 // n\n~leui\\leui.tp2~ #0 #0 // l\n",
                   encoding="utf-8")
    out = tmp_path / "out.json"
    assert places_check.main([root, "--log", str(log), "--json", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))["log"]
    assert result["without"]["placed"] == 0 and result["with"]["placed"] == 1
    assert result["with"]["components"] == 4
    assert result["with"]["the other way round"] < result["without"]["the other way round"]


def test_a_repeated_entry_counts_at_its_first_place_and_a_tie_is_no_inversion():
    """Review of #73: two mutations of inversions survived."""
    assert places_check.inversions([("b", 0), ("a", 0)],
                                   [("a", 0), ("b", 0), ("a", 0)]) == (1, 1)
    assert places_check.inversions([("a", 0), ("a", 0)], [("a", 0)]) == (0, 1)
