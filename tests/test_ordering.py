"""
Tests for the whole-install order planner.

The load-bearing claims, each with a test that fails without the code that
makes it true:

* the plan contains exactly the components the input contained - no invention,
  no loss, no rewriting of a line;
* the EET core installs first and EET_end last, even though both live in the
  `eet` folder;
* a dependency is never read as an ordering constraint;
* the emitted plan is checked against the same rules that judged the input, and
  reports honestly when it cannot satisfy them.
"""
import json
import os

import pytest

from iemod_fetch.errors import ConfigError
from iemod_fetch.ordering import (EET_LOG, PRE_EET_LOG, OrderIndex, OrderPlan,
                                  _minimum_moves, collect_units, plan_order,
                                  render_plan_summary, tp2_key)
from iemod_fetch.rules import RuleSet

HERE = os.path.dirname(__file__)
KRION = os.path.join(HERE, "data", "krion")
REAL_EET = os.path.join(HERE, "data", "WeiDU.log")
REAL_BGEE = os.path.join(HERE, "data", "WeiDUBGEE.log")

HEADER = ("// Log of Currently Installed WeiDU Mods\n"
          "// Format: ~TP2_Path~ #lang #comp // Name : Version\n")


def write_log(tmp_path, name, lines):
    path = tmp_path / name
    path.write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


@pytest.fixture
def index():
    return OrderIndex.load(KRION)


# ------------------------------------------------------------------- tp2 keys
@pytest.mark.parametrize("filename,expected", [
    ("SETUP-EEFIXPACK.TP2", "eefixpack"),
    ("eefixpack.tp2", "eefixpack"),
    ("EET.TP2", "eet"),
    ("EET_end.tp2", "eetend"),
    ("eet\\EET_end\\EET_end.tp2", "eetend"),
    ("setup-bp-bgt-worldmap.tp2", "bpbgtworldmap"),
])
def test_tp2_key_identifies_the_mod_not_the_folder(filename, expected):
    assert tp2_key(filename) == expected


# ------------------------------------------------------------------ catalogue
def test_index_loads_categories_in_their_declared_order(index):
    assert index.categories[0] == "PRE EET BGEE MODS"
    assert index.categories[-1] == "EET FINALIZATION"
    assert index.get("eeex").rank == index.categories.index("ENGINE")


def test_a_mods_own_identity_beats_a_folder_another_mod_claims(index):
    """
    EET_END.json sorts before eet.json and lists `wf: eet`. Letting that folder
    claim win put the EET core in EET FINALIZATION and sent it to the end of the
    install - the whole plan inverted by one filename's capitalisation.
    """
    assert index.get("eet").category == "EET STARTS HERE"
    assert index.get("eetend").category == "EET FINALIZATION"
    assert index.get("eet").rank < index.get("eetend").rank


def test_unknown_category_is_reported_not_silently_dropped(index):
    assert index.get("bogus") is None
    assert any("bogus" in w for w in index.warnings)


def test_index_accepts_a_repository_root_not_only_its_data_dir(tmp_path):
    data = tmp_path / "data"
    os.makedirs(data / "mods")
    (data / "categories.json").write_text(
        json.dumps({"categories": {"ENGINE": {}}}), encoding="utf-8")
    (data / "mods" / "x.json").write_text(
        json.dumps({"t": "x", "c": "ENGINE", "ord": 1}), encoding="utf-8")
    assert len(OrderIndex.load(str(tmp_path))) == 1


def test_index_refuses_a_directory_that_is_not_a_catalogue(tmp_path):
    with pytest.raises(ConfigError) as excinfo:
        OrderIndex.load(str(tmp_path))
    assert "categories.json" in str(excinfo.value)


# ---------------------------------------------------------------- unit reading
def test_units_are_ordered_by_log_line_not_by_folder_grouping(tmp_path):
    """
    EET_end sits on the last line but inside the FIRST folder. Ordering units by
    the parser's folder grouping reported it as install #2 and then claimed the
    plan had moved it 140 places.
    """
    log = write_log(tmp_path, "WeiDU.log", [
        r"~eet\EET.TP2~ #0 #0 // EET core",
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #10 // Tweak",
        r"~eet\EET_end\EET_end.tp2~ #0 #0 // Standard installation",
    ])
    units, warnings = collect_units([(log, EET_LOG)])
    assert warnings == []
    assert [u.key for u in units] == ["eet", "cdtweaks", "eetend"]


def test_display_distinguishes_two_tp2s_in_one_folder(tmp_path):
    log = write_log(tmp_path, "WeiDU.log", [
        r"~eet\EET.TP2~ #0 #0 // EET core",
        r"~eet\EET_end\EET_end.tp2~ #0 #0 // Standard installation",
    ])
    units, _ = collect_units([(log, EET_LOG)])
    assert [u.display for u in units] == ["eet", "eet/EET_end"]


# ---------------------------------------------------------------- the ordering
def test_eet_core_first_and_eet_end_last(tmp_path, index):
    log = write_log(tmp_path, "WeiDU.log", [
        r"~eet\EET_end\EET_end.tp2~ #0 #0 // Standard installation",
        r"~stratagems\setup-stratagems.tp2~ #0 #10 // SCS",
        r"~eet\EET.TP2~ #0 #0 // EET core",
        r"~EEex\EEex.tp2~ #0 #0 // EEex",
    ])
    plan = plan_order([(log, EET_LOG)], index)
    assert [u.key for u in plan.logs[EET_LOG]] == [
        "eet", "eeex", "stratagems", "eetend"]


def test_a_dependency_is_not_an_ordering_constraint(tmp_path, index):
    """
    BWS-NG records both `EET: EET_end` and `EET_end: EET` as dependencies -
    each needs the other present. Read as ordering they are a cycle, and the
    solver pushed the EET core to the very end of the install to satisfy it.
    """
    rules = tmp_path / "dependencies.json"
    rules.write_text(json.dumps([{"rule": "EET:EET_end"},
                                 {"rule": "EET_end:EET"}]), encoding="utf-8")
    log = write_log(tmp_path, "WeiDU.log", [
        r"~eet\EET.TP2~ #0 #0 // EET core",
        r"~eet\EET_end\EET_end.tp2~ #0 #0 // Standard installation",
    ])
    plan = plan_order([(log, EET_LOG)], index, RuleSet.load([str(rules)]))
    assert plan.cycles == []
    assert [u.key for u in plan.logs[EET_LOG]] == ["eet", "eetend"]


def test_an_order_rule_overrides_the_catalogue_preference(tmp_path, index):
    """The catalogue is a preference; a rule is a constraint."""
    rules = tmp_path / "order.json"
    rules.write_text(json.dumps(
        [{"rule": "cdtweaks:stratagems", "direction": "after"}]), encoding="utf-8")
    log = write_log(tmp_path, "WeiDU.log", [
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #10 // Tweak",
        r"~stratagems\setup-stratagems.tp2~ #0 #10 // SCS",
    ])
    plain = plan_order([(log, EET_LOG)], index)
    assert [u.key for u in plain.logs[EET_LOG]] == ["cdtweaks", "stratagems"]

    constrained = plan_order([(log, EET_LOG)], index, RuleSet.load([str(rules)]))
    assert [u.key for u in constrained.logs[EET_LOG]] == ["stratagems", "cdtweaks"]
    assert constrained.edges == 1


def test_contradictory_rules_are_reported_and_still_produce_a_plan(tmp_path, index):
    rules = tmp_path / "order.json"
    rules.write_text(json.dumps([
        {"rule": "cdtweaks:stratagems", "direction": "after"},
        {"rule": "cdtweaks:stratagems", "direction": "before"},
    ]), encoding="utf-8")
    log = write_log(tmp_path, "WeiDU.log", [
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #10 // Tweak",
        r"~stratagems\setup-stratagems.tp2~ #0 #10 // SCS",
    ])
    plan = plan_order([(log, EET_LOG)], index, RuleSet.load([str(rules)]))
    assert plan.cycles and set(plan.cycles[0]) == {"cdtweaks", "stratagems"}
    assert len(plan.logs[EET_LOG]) == 2          # a complete plan regardless
    assert not plan.verified                     # and it does not claim success
    assert plan.residual


def test_a_mod_the_catalogue_does_not_know_stays_where_it_was(tmp_path, index):
    log = write_log(tmp_path, "WeiDU.log", [
        r"~eet\EET.TP2~ #0 #0 // EET core",
        r"~NeverHeardOfIt\setup-neverheardofit.tp2~ #0 #0 // Mystery",
        r"~EEex\EEex.tp2~ #0 #0 // EEex",
    ])
    plan = plan_order([(log, EET_LOG)], index)
    assert [u.key for u in plan.logs[EET_LOG]] == ["eet", "neverheardofit", "eeex"]
    assert plan.unranked == ["NeverHeardOfIt"]


def test_the_two_installs_never_order_against_each_other(tmp_path, index):
    """A pre-EET mod and an EET mod are two different games, not one order."""
    rules = tmp_path / "order.json"
    rules.write_text(json.dumps(
        [{"rule": "bg1ub:cdtweaks", "direction": "after"}]), encoding="utf-8")
    eet = write_log(tmp_path, "WeiDU.log",
                    [r"~cdtweaks\setup-cdtweaks.tp2~ #0 #10 // Tweak"])
    bgee = write_log(tmp_path, "WeiDUBGEE.log",
                     [r"~bg1ub\BG1UB.TP2~ #0 #11 // Scar"])
    plan = plan_order([(eet, EET_LOG), (bgee, PRE_EET_LOG)], index,
                      RuleSet.load([str(rules)]))
    assert plan.edges == 0
    assert [u.key for u in plan.logs[PRE_EET_LOG]] == ["bg1ub"]
    assert [u.key for u in plan.logs[EET_LOG]] == ["cdtweaks"]


# --------------------------------------------------------------- phase changes
def test_a_wrong_phase_is_reported_but_not_acted_on(tmp_path, index):
    log = write_log(tmp_path, "WeiDU.log", [
        r"~eet\EET.TP2~ #0 #0 // EET core",
        r"~bg1ub\BG1UB.TP2~ #0 #11 // Scar",
    ])
    plan = plan_order([(log, EET_LOG)], index)
    assert [(m.display, m.frm, m.to) for m in plan.phase_notes] == [
        ("bg1ub", EET_LOG, PRE_EET_LOG)]
    # It stays in the log the operator put it in, sorted by its own pre-EET
    # priority - which lands it before the EET core, and is exactly why the
    # phase note exists: a position inside the wrong install is meaningless.
    assert [u.key for u in plan.logs[EET_LOG]] == ["bg1ub", "eet"]
    assert PRE_EET_LOG not in plan.logs


def test_reassign_phase_moves_it_when_asked(tmp_path, index):
    log = write_log(tmp_path, "WeiDU.log", [
        r"~eet\EET.TP2~ #0 #0 // EET core",
        r"~bg1ub\BG1UB.TP2~ #0 #11 // Scar",
    ])
    plan = plan_order([(log, EET_LOG)], index, reassign_phase=True)
    assert [u.key for u in plan.logs[PRE_EET_LOG]] == ["bg1ub"]
    assert [u.key for u in plan.logs[EET_LOG]] == ["eet"]


def test_a_mod_installed_on_both_games_is_not_reported_as_misplaced(tmp_path, index):
    """eefixpack legitimately installs on BG1:EE and again on the merged game."""
    eet = write_log(tmp_path, "WeiDU.log", [
        r"~eet\EET.TP2~ #0 #0 // EET core",
        r"~bg1ub\BG1UB.TP2~ #0 #11 // Scar",
    ])
    bgee = write_log(tmp_path, "WeiDUBGEE.log",
                     [r"~bg1ub\BG1UB.TP2~ #0 #11 // Scar"])
    plan = plan_order([(eet, EET_LOG), (bgee, PRE_EET_LOG)], index)
    assert plan.phase_notes == []


# ------------------------------------------------------------- lossless output
def test_the_plan_contains_exactly_the_input_components(index):
    plan = plan_order([(REAL_EET, EET_LOG), (REAL_BGEE, PRE_EET_LOG)], index)
    emitted = sorted(line for role in plan.logs
                     for line in plan.render(role).splitlines()
                     if line.startswith("~"))
    original = []
    for path in (REAL_EET, REAL_BGEE):
        with open(path, encoding="utf-8") as fh:
            original.extend(line.strip() for line in fh
                            if line.strip().startswith("~"))
    original.sort()
    assert emitted == original
    assert len(emitted) == 796


def test_written_files_are_named_what_weidu_expects(tmp_path, index):
    plan = plan_order([(REAL_EET, EET_LOG), (REAL_BGEE, PRE_EET_LOG)], index)
    written = plan.write(str(tmp_path / "plan"))
    assert sorted(os.path.basename(p) for p in written) == [
        "WeiDU-BGEE.log", "WeiDU.log"]
    text = (tmp_path / "plan" / "WeiDU.log").read_text(encoding="utf-8")
    assert text.startswith("// Log of Currently Installed WeiDU Mods")
    assert text.splitlines()[-1].startswith(r"~eet\EET_end")


def test_a_component_with_no_comment_round_trips(tmp_path, index):
    log = write_log(tmp_path, "WeiDU.log", [r"~eet\EET.TP2~ #0 #0"])
    plan = plan_order([(log, EET_LOG)], index)
    assert r"~eet\EET.TP2~ #0 #0" in plan.render(EET_LOG).splitlines()


# ----------------------------------------------------------------- the metrics
def test_minimum_moves_reports_one_move_not_the_whole_list():
    """
    Comparing indexes said 146 mods moved when one did. Only what falls off a
    longest common subsequence genuinely has to move.
    """
    before = ["a", "b", "c", "d", "e"]
    after = ["e", "a", "b", "c", "d"]
    assert [key for key, _o, _n in _minimum_moves(before, after)] == ["e"]


def test_minimum_moves_is_empty_for_an_unchanged_order():
    assert _minimum_moves(list("abcd"), list("abcd")) == []


def test_real_logs_need_only_a_handful_of_moves(index):
    """
    Regression guard on the real 796-component install: a plan that reorders
    almost everything means a bug in the priorities, not a bad install.
    """
    plan = plan_order([(REAL_EET, EET_LOG), (REAL_BGEE, PRE_EET_LOG)], index)
    assert len(plan.moved) < 20
    # The fixture catalogue knows 6 mods, so most of the install is unranked and
    # holds its place. What it must get right is the pair it does know about.
    order = [u.key for u in plan.logs[EET_LOG]]
    assert order.index("eet") < order.index("eetend")
    assert order[-1] == "eetend"


# ------------------------------------------------------------- self-validation
def test_the_plan_is_checked_against_the_rules_it_claims_to_satisfy(tmp_path, index):
    rules = tmp_path / "order.json"
    rules.write_text(json.dumps(
        [{"rule": "cdtweaks:stratagems", "direction": "after"}]), encoding="utf-8")
    log = write_log(tmp_path, "WeiDU.log", [
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #10 // Tweak",
        r"~stratagems\setup-stratagems.tp2~ #0 #10 // SCS",
    ])
    plan = plan_order([(log, EET_LOG)], index, RuleSet.load([str(rules)]))
    assert plan.verified and plan.residual == []
    assert not plan.compliant          # the INPUT was wrong; the OUTPUT is not


def test_an_incompatibility_survives_the_plan_and_is_named_as_unfixable(tmp_path, index):
    rules = tmp_path / "incompatibilities.json"
    rules.write_text(json.dumps(
        [{"rule": "cdtweaks:stratagems", "severity": "error"}]), encoding="utf-8")
    log = write_log(tmp_path, "WeiDU.log", [
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #10 // Tweak",
        r"~stratagems\setup-stratagems.tp2~ #0 #10 // SCS",
    ])
    plan = plan_order([(log, EET_LOG)], index, RuleSet.load([str(rules)]))
    assert len(plan.blockers) == 1
    assert len(plan.logs[EET_LOG]) == 2      # nothing was dropped on the user
    assert plan.verified                     # no ORDER rule is unsatisfied


def test_summary_states_the_plan_is_for_a_fresh_install(tmp_path, index, capsys):
    plan = plan_order([(REAL_EET, EET_LOG), (REAL_BGEE, PRE_EET_LOG)], index)
    render_plan_summary(plan, str(tmp_path), __import__("sys").stdout)
    out = capsys.readouterr().out
    assert "FRESH install" in out
    assert "reinstalling" in out


def test_an_empty_plan_renders_without_crashing(tmp_path, capsys):
    render_plan_summary(OrderPlan(), str(tmp_path), __import__("sys").stdout)
    assert "INSTALL ORDER PLAN" in capsys.readouterr().out


# ------------------------------------------------------------------- the CLI
def _cli(argv):
    import io
    from iemod_fetch import cli
    stream = io.StringIO()
    code = cli.main(argv, stream=stream)
    return code, stream.getvalue()


def test_cli_writes_both_logs_and_reports(tmp_path):
    out = tmp_path / "plan"
    code, text = _cli(["--check-only",
                       "-m", os.path.join(HERE, "data", "mod_downloads.json"),
                       "-w", f"{REAL_EET}:EET", "-w", f"{REAL_BGEE}:BGEE",
                       "--order-catalogue", KRION,
                       "--plan-order", str(out)])
    assert code == 0
    assert (out / "WeiDU.log").exists() and (out / "WeiDU-BGEE.log").exists()
    assert "INSTALL ORDER PLAN" in text
    assert "FRESH install" in text


def test_cli_refuses_to_plan_without_a_catalogue(tmp_path, capsys):
    """Rather than inventing a reference order of its own."""
    code, _text = _cli(["--check-only",
                       "-m", os.path.join(HERE, "data", "mod_downloads.json"),
                       "-w", f"{REAL_EET}:EET",
                       "--plan-order", str(tmp_path / "plan")])
    assert code != 0
    assert "--order-catalogue" in capsys.readouterr().err


def test_cli_refuses_two_logs_that_both_look_like_eet(tmp_path, capsys):
    code, _text = _cli(["--check-only",
                       "-m", os.path.join(HERE, "data", "mod_downloads.json"),
                       "-w", f"{REAL_EET}:EET", "-w", f"{REAL_EET}:EET",
                       "--order-catalogue", KRION,
                       "--plan-order", str(tmp_path / "plan")])
    assert code != 0
    assert "both look like the EET install" in capsys.readouterr().err


def test_cli_infers_the_roles_without_explicit_game_suffixes(tmp_path):
    """The EET log is the one that installs EET, not the one named WeiDU.log."""
    out = tmp_path / "plan"
    code, _text = _cli(["--check-only",
                        "-m", os.path.join(HERE, "data", "mod_downloads.json"),
                        "-w", REAL_BGEE, "-w", REAL_EET,
                        "--order-catalogue", KRION,
                        "--plan-order", str(out)])
    assert code == 0
    assert r"~eet\EET.TP2~" in (out / "WeiDU.log").read_text(encoding="utf-8")
    assert "eet" not in (out / "WeiDU-BGEE.log").read_text(encoding="utf-8").lower().split("\n")[4]
