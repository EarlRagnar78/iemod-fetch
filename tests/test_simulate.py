"""
Simulating the install the way WeiDU will run it (ADR-0025).

No game data is needed: each component's own tp2 constraints are checked in
plan order against what is installed by then, on the game it lands on. The
claims:

* the pre-EET log installs on BGEE; the EET log on BG2EE, which becomes EET once
  the EET core is in - so a BG2EE-only component after the core is refused;
* REQUIRE_COMPONENT / MOD_IS_INSTALLED must already be satisfied, FORBID /
  NOT MOD_IS_INSTALLED must not be, and a refusal cascades to what needs it;
* the result says, per refused component, exactly which constraint refused it.
"""
from iemod_fetch.ordering import EET_LOG, PRE_EET_LOG
from iemod_fetch.simulate import simulate_install
from iemod_fetch.tp2 import Tp2Component


def comp(number, requires=(), forbids=(), games=(), not_games=()):
    return Tp2Component(number=number, requires=list(requires), forbids=list(forbids),
                        games=list(games), not_games=list(not_games))


# the constraint table: mod -> component -> its own tp2 flags
CONSTRAINTS = {
    "dlcmerger": {1: comp(1, games=["BGEE"])},
    "eefixpack": {0: comp(0)},
    "bg1ub": {0: comp(0, games=["BGEE", "EET"])},
    "eet": {0: comp(0, games=["BG2EE"])},
    "cdtweaks": {2100: comp(2100), 4000: comp(4000, games=["BG2EE"])},
    "stratagems": {4115: comp(4115, forbids=[("cdtweaks", 2100)]),
                   5000: comp(5000, requires=[("eet", 0)])},
    "ascension": {0: comp(0, requires=[("stratagems", 5000)])},
    "eetend": {0: comp(0, requires=[("eet", 0)], games=["EET"])},
}

PRE = [("dlcmerger", 1), ("eefixpack", 0), ("bg1ub", 0)]


def run(eet_order, pre=PRE, constraints=CONSTRAINTS):
    return simulate_install({PRE_EET_LOG: pre, EET_LOG: eet_order}, constraints)


def refused(result):
    return {(r.mod, r.component): r.reason for r in result.refused}


def test_a_clean_eet_install_installs_everything():
    result = run([("eet", 0), ("cdtweaks", 2100), ("stratagems", 5000),
                  ("ascension", 0), ("eetend", 0)])
    assert result.refused == []
    assert result.installed[EET_LOG][-1] == ("eetend", 0)


def test_the_bgee_phase_runs_on_bgee():
    result = run([("eet", 0)], pre=[("dlcmerger", 1), ("eet", 0)])
    assert "game is BGEE" in refused(result)[("eet", 0)]


def test_a_bg2ee_only_component_after_the_eet_core_is_refused():
    result = run([("eet", 0), ("cdtweaks", 4000)])
    assert "game is EET" in refused(result)[("cdtweaks", 4000)]


def test_a_missing_requirement_refuses_and_cascades():
    result = run([("stratagems", 5000), ("eet", 0), ("ascension", 0)])
    got = refused(result)
    assert "needs eet #0" in got[("stratagems", 5000)]          # not installed yet
    assert "needs stratagems #5000" in got[("ascension", 0)]    # cascaded


def test_a_forbidden_component_already_installed_refuses():
    result = run([("eet", 0), ("cdtweaks", 2100), ("stratagems", 4115)])
    assert "cdtweaks #2100 is installed" in refused(result)[("stratagems", 4115)]


def test_forbid_only_looks_backwards_as_weidu_does():
    result = run([("eet", 0), ("stratagems", 4115), ("cdtweaks", 2100)])
    assert ("stratagems", 4115) not in refused(result)


def test_a_mod_without_a_readable_tp2_is_assumed_to_install_and_counted():
    result = run([("eet", 0), ("unknownmod", 3)])
    assert result.refused == [] and result.unchecked == [(EET_LOG, "unknownmod", 3)]


def test_the_bgee_mods_count_as_installed_on_eet_when_eet_imports_them():
    """EET merges the BGEE game; a BG2-phase check for a BGEE mod then holds."""
    constraints = dict(CONSTRAINTS, needsub={0: comp(0, requires=[("bg1ub", 0)])})
    eet = [("eet", 0), ("needsub", 0)]
    imported = simulate_install({PRE_EET_LOG: PRE, EET_LOG: eet}, constraints,
                                eet_imports_bgee=True)
    assert imported.refused == []
    separate = simulate_install({PRE_EET_LOG: PRE, EET_LOG: eet}, constraints,
                                eet_imports_bgee=False)
    assert ("needsub", 0) in refused(separate)


def test_the_report_names_each_refusal_and_the_constraint():
    text = run([("eet", 0), ("cdtweaks", 2100), ("stratagems", 4115)]).render()
    assert "WOULD REFUSE" in text and "stratagems #4115" in text
    assert "FORBID" in text


# ------------------------------------------------------- EET's merge check
# EET.tp2 reads the BG:EE WeiDU.log at merge time and FAILs on any mod missing
# from its tbl/compatibility.tbl, and on two wrong options. A BG:EE mod can
# therefore make the EET core - and everything that needs EET - impossible.
from iemod_fetch.constraints import EetMergeRules  # noqa: E402

MERGE = EetMergeRules(allowed={"dlcmerger", "eefixpack", "bg1ub", "soa"},
                      wrong_components={("soa", 1)})
EET_TAIL = [("eet", 0), ("stratagems", 5000), ("eetend", 0)]


def test_a_bgee_mod_eet_cannot_import_refuses_the_merge_and_what_needs_it():
    pre = PRE + [("bg1aerie", 0)]
    result = simulate_install({PRE_EET_LOG: pre, EET_LOG: EET_TAIL}, CONSTRAINTS,
                              eet_rules=MERGE)
    got = refused(result)
    assert "bg1aerie" in got[("eet", 0)] and "compatibility.tbl" in got[("eet", 0)]
    assert ("stratagems", 5000) in got and ("eetend", 0) in got


def test_a_wrong_option_on_bgee_refuses_the_merge():
    pre = PRE + [("soa", 1)]
    result = simulate_install({PRE_EET_LOG: pre, EET_LOG: EET_TAIL}, CONSTRAINTS,
                              eet_rules=MERGE)
    assert "soa #1" in refused(result)[("eet", 0)]


def test_a_bgee_install_eet_accepts_merges():
    result = simulate_install({PRE_EET_LOG: PRE, EET_LOG: EET_TAIL}, CONSTRAINTS,
                              eet_rules=MERGE)
    assert result.refused == []


def test_eet_does_not_carry_bgee_mods_into_its_own_log_by_default():
    """EET.tp2 copies the BG:EE log to WeiDU-BGEE.log, not into WeiDU.log, and
    MOD_IS_INSTALLED reads WeiDU.log - so a BGEE-phase mod does not count."""
    constraints = dict(CONSTRAINTS, needsub={0: comp(0, requires=[("bg1ub", 0)])})
    result = simulate_install({PRE_EET_LOG: PRE, EET_LOG: [("eet", 0), ("needsub", 0)]},
                              constraints)
    assert ("needsub", 0) in refused(result)
