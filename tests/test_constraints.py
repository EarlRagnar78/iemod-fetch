"""
A staged mod's own constraints, as rules and as EET's merge check (ADR-0025).

* a tp2 REQUIRE becomes "install the required component first" (the Infinity
  Orchestrator's reading) plus a dependency; a FORBID becomes an
  incompatibility - all graded error, origin "mod tp2";
* EET's merge check is read from the staged EET mod itself: its allow-list of
  BG:EE mods (tbl/compatibility.tbl) and the wrong options it fails on.
"""
import pytest

from iemod_fetch.constraints import (eet_merge_rules, load_constraints,
                                     tp2_rules)
from iemod_fetch.rules import DEPENDS, INCOMPATIBLE, ORDER


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def mods(tmp_path):
    root = tmp_path / "Mods"
    write(root / "stratagems" / "setup-stratagems.tp2", """
BEGIN @1 DESIGNATED 4100
FORBID_COMPONENT "setup-cdtweaks.tp2" 2370 @2
BEGIN @3 DESIGNATED 5000
REQUIRE_COMPONENT ~EET/EET.tp2~ ~0~ @4
""")
    write(root / "eet" / "EET.tp2", r"""
BEGIN @900000
REQUIRE_PREDICATE ENGINE_IS ~bg2ee~ @1
		COUNT_REGEXP_INSTANCES "^~EEFIXPACK[/\\]SETUP-EEFIXPACK\.TP2~ #[0-9]+ #0" cd_eefp_bgee
		REPLACE_TEXTUALLY ~^//.*~ ~~
		COUNT_REGEXP_INSTANCES "^~SOA[/\\]SETUP-SOA\.TP2~ #[0-9]+ #1 " num_matches
		PATCH_IF (num_matches > 0) BEGIN
			PATCH_FAIL @900006
		END
""")
    write(root / "eet" / "tbl" / "compatibility.tbl",
          "WEIDU 0 //dummy\nDLCMERGER 0 //DLC Merger\nEEFIXPACK 0\n\nBG1UB 1\nSOA 1\n")
    return root


def test_constraints_are_loaded_per_mod_and_component(mods):
    loaded = load_constraints(str(mods), [("stratagems", "stratagems",
                                           "setup-stratagems.tp2"),
                                          ("eet", "eet", "EET.tp2"),
                                          ("ghost", "ghost", "setup-ghost.tp2")])
    assert set(loaded.by_mod) == {"stratagems", "eet"}
    assert loaded.by_mod["stratagems"][5000].requires == [("eet", 0)]
    assert loaded.missing == ["ghost"]


def test_a_requirement_is_an_order_rule_and_a_dependency(mods):
    loaded = load_constraints(str(mods), [("stratagems", "stratagems",
                                           "setup-stratagems.tp2")])
    rules = tp2_rules(loaded)
    order = [r for r in rules if r.kind == ORDER and "requires" in r.message]
    assert [(r.left.mod, set(r.left.components), r.direction, r.right[0].mod)
            for r in order] == [("eet", {0}, "before", "stratagems")]
    assert any(r.kind == DEPENDS and r.left.mod == "stratagems" for r in rules)
    assert all(r.origin == "mod tp2" for r in rules)
    assert all(r.severity == "error" for r in rules if "requires" in r.message)


def test_a_one_sided_forbid_means_install_me_first(mods):
    """WeiDU checks a FORBID only against what is ALREADY installed, so a
    one-sided FORBID is satisfied by order - and that is what authors mean:
    EET's own comment on its FORBID reads 'EET should be installed BEFORE
    BP-BGT Worldmap'."""
    loaded = load_constraints(str(mods), [("stratagems", "stratagems",
                                           "setup-stratagems.tp2")])
    rules = tp2_rules(loaded)
    assert [(r.left.mod, set(r.left.components), r.direction, r.right[0].mod)
            for r in rules if r.kind == ORDER and r.left.mod == "stratagems"] == [
        ("stratagems", {4100}, "before", "cdtweaks")]
    # ...but whether they COEXIST the tp2 does not say (BWS-NG classes this very
    # pair incompatible), so it is also a warning - never auto-resolved.
    [warning] = [r for r in rules if r.kind == INCOMPATIBLE]
    assert warning.severity == "warning" and "did not say" in warning.message


def test_a_mutual_forbid_is_an_incompatibility(mods):
    """SCS #4100 and Tweaks #2370 forbid each other: no order works."""
    write(mods / "cdtweaks" / "setup-cdtweaks.tp2", """
BEGIN @1 DESIGNATED 2370
REQUIRE_PREDICATE !MOD_IS_INSTALLED ~stratagems.tp2~ 4100 @24
""")
    loaded = load_constraints(str(mods), [
        ("stratagems", "stratagems", "setup-stratagems.tp2"),
        ("cdtweaks", "cdtweaks", "setup-cdtweaks.tp2")])
    incompatible = [r for r in tp2_rules(loaded) if r.kind == INCOMPATIBLE]
    assert len(incompatible) == 1
    sides = {(incompatible[0].left.mod, *incompatible[0].left.components),
             (incompatible[0].right[0].mod, *incompatible[0].right[0].components)}
    assert sides == {("stratagems", 4100), ("cdtweaks", 2370)}


def test_eets_merge_check_is_read_from_the_staged_eet(mods):
    rules = eet_merge_rules(str(mods / "eet"))
    assert {"dlcmerger", "eefixpack", "bg1ub", "soa"} <= rules.allowed
    assert rules.wrong_components == {("soa", 1)}           # EEFixPack's is not a FAIL


def test_no_staged_eet_means_no_merge_check(tmp_path):
    assert eet_merge_rules(str(tmp_path / "nowhere")) is None


# ----------------------------------------------------------------- the CLI
def _cli(argv):
    import io

    from iemod_fetch import cli
    stream = io.StringIO()
    code = cli.main(argv, stream=stream)
    return code, stream.getvalue()


HEADER = "// Log of Currently Installed WeiDU Mods\n"
HERE = __import__("os").path.dirname(__file__)
KRION = __import__("os").path.join(HERE, "data", "krion")
MANIFEST = __import__("os").path.join(HERE, "data", "mod_downloads.json")


@pytest.fixture
def staged(tmp_path, mods):
    write(mods / "cdtweaks" / "setup-cdtweaks.tp2", """
BEGIN @1 DESIGNATED 2370
BEGIN @2 DESIGNATED 4000
REQUIRE_PREDICATE GAME_IS ~bg2ee~ @3
""")
    write(tmp_path / "bgee.log", HEADER + r"~eet\EET.tp2~ #0 #0 // never on BGEE" + "\n")
    write(tmp_path / "eet.log", HEADER + "\n".join([
        r"~stratagems\setup-stratagems.tp2~ #0 #5000 // needs EET first",
        r"~eet\EET.tp2~ #0 #0 // EET core (resource importation)",
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #2370 // forbidden by SCS 4100",
        r"~stratagems\setup-stratagems.tp2~ #0 #4100 // forbids cdtweaks 2370",
        r"~cdtweaks\setup-cdtweaks.tp2~ #0 #4000 // BG2EE only",
    ]) + "\n")
    return tmp_path


def run(staged, *extra):
    return _cli(["--check-only", "-m", MANIFEST,
                 "-w", f"{staged / 'eet.log'}:EET", "-w", f"{staged / 'bgee.log'}:BGEE",
                 "-t", str(staged / "Mods"), "--order-catalogue", KRION,
                 "--plan-order", str(staged / "plan"), "--simulate", *extra])


def test_cli_simulation_finds_what_weidu_would_refuse(staged):
    code, text = run(staged)
    assert code == 1
    assert "INSTALL SIMULATION" in text and "WOULD REFUSE" in text
    assert "game is BGEE" in text                     # EET core in the BGEE log
    assert "game is EET" in text                      # cdtweaks #4000 after the core


def test_cli_orders_by_the_mods_own_requirements(staged):
    _code, _text = run(staged)
    planned = (staged / "plan" / "WeiDU.log").read_text()
    assert planned.index("#0 #0 // EET core") < planned.index("#5000")


def test_cli_resolution_leaves_a_plan_weidu_can_finish(staged):
    code, text = run(staged, "--resolve-conflicts")
    assert "0 would be refused" in text, text
    planned = (staged / "plan" / "WeiDU.log").read_text()
    assert planned.index("#4100") < planned.index("#2370")   # FORBID honoured by order
    assert "#4000" not in planned          # BG2EE-only after the EET core
    assert code == 1          # the INPUT still has these problems; the plan does not
