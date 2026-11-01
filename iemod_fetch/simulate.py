"""
Walk an install plan the way WeiDU will run it (ADR-0025).

No game data is needed. Each component's own tp2 constraints - the flags WeiDU
enforces at install time - are checked in plan order against what is installed
by then, on the game the component lands on:

* the pre-EET log installs on BGEE; the EET log on BG2EE, which BECOMES EET the
  moment the EET core (`eet #0`) is in, so `GAME_IS ~bg2ee~` stops holding;
* `REQUIRE_COMPONENT` / `MOD_IS_INSTALLED` must already be satisfied;
* `FORBID_COMPONENT` / `NOT MOD_IS_INSTALLED` must not be - WeiDU checks only
  what is already installed, so a forbidden component installed LATER does not
  refuse this one (the later one's own flags decide whether it installs);
* a refused component is not installed, so whatever requires it is refused too.

A refusal is what makes mod_installer stop partway through a long install. The
point is to find it before the first file is copied.
"""
from dataclasses import dataclass, field
from collections.abc import Iterable, Mapping, Sequence

from .naming import normalize_key
from .tp2 import Tp2Component

EET_LOG = "WeiDU.log"            # mirrors ordering.EET_LOG without importing it
PRE_EET_LOG = "WeiDU-BGEE.log"
EET_CORE = ("eet", 0)

Constraints = dict[str, dict[int, Tp2Component]]
Step = tuple[str, int]


@dataclass
class Refusal:
    log: str
    mod: str
    component: int
    reason: str


@dataclass
class SimulationResult:
    installed: dict[str, list[Step]] = field(default_factory=dict)
    refused: list[Refusal] = field(default_factory=list)
    unchecked: list[tuple[str, str, int]] = field(default_factory=list)

    def render(self) -> str:
        total = sum(len(v) for v in self.installed.values())
        lines = [("INSTALL SIMULATION (each component's own tp2 constraints, "
                 "in plan order)"),
                 (f"  {total} component(s) would install, {len(self.refused)} "
                  f"would be refused, {len(self.unchecked)} unchecked (no tp2 read)")]
        if self.refused:
            lines.append("  WOULD REFUSE - mod_installer stops at the first of these:")
            for item in self.refused:
                lines.append(f"    [{item.log}] {item.mod} #{item.component}: "
                             f"{item.reason}")
        return "\n".join(lines)


def _games_of(game: str) -> set[str]:
    """What GAME_IS answers on this game, as far as the constraints use it."""
    if game == "BGEE":
        return {"BGEE", "SoD"}      # SoD content is merged into BGEE (DlcMerger)
    return {game}


def _check(component: Tp2Component, game: str,
           installed: set[Step]) -> str | None:
    answers = _games_of(game)
    if component.games and not answers & set(component.games):
        return (f"needs game {'/'.join(component.games)}, but the game is "
                f"{game} (REQUIRE_PREDICATE GAME_IS)")
    if answers & set(component.not_games):
        return f"refuses game {game} (REQUIRE_PREDICATE NOT GAME_IS)"
    for mod, number in component.requires:
        if (mod, number) not in installed:
            return (f"needs {mod} #{number}, which is not installed by then "
                    f"(REQUIRE_COMPONENT)")
    for mod, number in component.forbids:
        if (mod, number) in installed:
            return f"{mod} #{number} is installed and this component FORBIDs it"
    return None


def _merge_refusal(eet_rules, bgee: Sequence[Step]) -> str | None:
    """EET.tp2's own check of the BG:EE install it is about to import."""
    unknown = sorted({mod for mod, _n in bgee
                      if normalize_key(mod) not in eet_rules.allowed})
    wrong = sorted(step for step in bgee if step in eet_rules.wrong_components)
    if not unknown and not wrong:
        return None
    parts = []
    if unknown:
        parts.append(f"BG:EE mod(s) {', '.join(unknown)} not in EET's "
                     f"compatibility.tbl")
    if wrong:
        parts.append("wrong option(s) " + ", ".join(f"{m} #{n}" for m, n in wrong))
    return ("EET refuses the merge: " + "; ".join(parts)
            + " (EET's M flag overrides this, at your own risk)")


def simulate_install(logs: Mapping[str, Sequence[Step]], constraints: Constraints,
                     games: dict[str, str] | None = None,
                     eet_imports_bgee: bool = False,
                     eet_rules=None) -> SimulationResult:
    """
    `logs` maps a plan role to its ordered (mod, component) steps.

    `games` overrides which game a role installs on; by default the pre-EET log
    is BGEE and the EET log starts as BG2EE.

    `eet_imports_bgee` is False because that is what EET does: EET.tp2 copies
    the BG:EE log to `WeiDU-BGEE.log`, not into `WeiDU.log`, and
    MOD_IS_INSTALLED reads `WeiDU.log`. `eet_rules` (constraints.EetMergeRules)
    is EET's own merge check, applied when the EET core installs.
    """
    games = dict({PRE_EET_LOG: "BGEE", EET_LOG: "BG2EE"}, **(games or {}))
    result = SimulationResult()
    installed_on: dict[str, set[Step]] = {}
    for role in (PRE_EET_LOG, EET_LOG):
        if role not in logs:
            continue
        game = games[role]
        installed: set[Step] = installed_on.setdefault(role, set())
        done: list[Step] = result.installed.setdefault(role, [])
        for mod, number in logs[role]:
            component = constraints.get(mod, {}).get(number)
            if component is None:
                result.unchecked.append((role, mod, number))
                reason = None
            else:
                reason = _check(component, game, installed)
            if (reason is None and (mod, number) == EET_CORE and role == EET_LOG
                    and eet_rules is not None):
                reason = _merge_refusal(eet_rules,
                                        result.installed.get(PRE_EET_LOG, []))
            if reason:
                result.refused.append(Refusal(role, mod, number, reason))
                continue
            installed.add((mod, number))
            done.append((mod, number))
            if (mod, number) == EET_CORE and role == EET_LOG:
                game = "EET"
                if eet_imports_bgee:
                    installed |= installed_on.get(PRE_EET_LOG, set())
    return result


def steps_of(units: Iterable) -> list[Step]:
    """(mod, component) in plan order, from ordering.Unit-like objects."""
    return [(unit.key, comp) for unit in units
            for _path, _lang, comp, _comment in unit.lines]
