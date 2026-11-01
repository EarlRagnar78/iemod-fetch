"""
Automatic conflict resolution - opt-in, narrow, and re-verified (ADR-0021).

The conflict report already names the narrowest remedy for every finding:
"deselect stratagems #4115 (alternative: drop infinity_ui)". This module applies
that remedy to an install PLAN, for the one class of finding where the rules
themselves decide what goes:

* an incompatibility,
* graded `error` by the rule set,
* not marked speculative,
* between two different mods,
* where the rule pins at least one side to specific components.

Then the side the rule pinned (the cheaper one, by the same cost the report
uses) loses exactly those components - nothing the rule did not name.

Everything else is left for the operator and listed as such: a rule that
condemns two mods wholesale says "not both", not which one; a same-mod conflict
is a choice between two option groups; a missing dependency is fixed by adding,
never by removing; a warning or a speculative claim is not enough to delete
someone's chosen component. Which mod to lose in those cases stays a human
decision, exactly as ADR-0017 said.

Only the plan is edited. The operator's WeiDU logs are never touched, and the
plan is re-checked against the same rules afterwards rather than trusted.
"""
from dataclasses import dataclass, field, replace
from collections.abc import Set

from .contract import SCHEMA_VERSION
from .conflicts import (DESELECT, INSTALL, KEEP_BOTH, SUBCOMPONENT_ORIGIN,
                        ConflictReport, Finding, Side, finding_options)
from .decisions import Decisions
from .errors import ConfigError
from .naming import normalize_key
from .rules import DECIDED_ORDER, INCOMPATIBLE, ORDER, ModSpec, Rule, RuleSet


@dataclass
class Removal:
    log: str
    mod: str
    components: tuple[int, ...]
    labels: tuple[str, ...]
    because: str            # the other side, as the report describes it
    reason: str = ""        # the rule's own explanation, if it gave one
    finding_id: str = ""    # the conflict-report finding this settles, if any
    by: str = "rules"       # "rules", or "decision": the player chose it


@dataclass
class Move:
    log: str
    mod: str
    components: tuple[int, ...]
    because: str


@dataclass
class Unresolved:
    log: str
    finding: str
    why: str
    finding_id: str = ""    # the conflict-report finding, so a UI can answer it


@dataclass
class Accepted:
    log: str
    finding: str
    why: str
    finding_id: str


@dataclass
class ResolutionResult:
    removed: list[Removal] = field(default_factory=list)
    left_for_operator: list[Unresolved] = field(default_factory=list)
    moved: list[Move] = field(default_factory=list)
    accepted: list[Accepted] = field(default_factory=list)
    stale_decisions: list[str] = field(default_factory=list)   # finding ids not found

    def extend(self, other: ResolutionResult) -> None:
        self.removed.extend(other.removed)
        self.left_for_operator.extend(other.left_for_operator)
        self.moved.extend(other.moved)
        self.accepted.extend(other.accepted)
        self.stale_decisions.extend(other.stale_decisions)

    def render(self) -> str:
        lines = ["CONFLICT RESOLUTION (--resolve-conflicts; the plan only, never your logs)"]
        for move in self.moved:
            shown = ", ".join(f"#{n}" for n in move.components)
            lines.append(f"  moved before the EET core  [{move.log}] {move.mod}: {shown}")
            lines.append(f"           because {move.because}")
        if not self.removed:
            lines.append("  nothing removed")
        for item in self.removed:
            shown = ", ".join(f"#{n}" + (f" {label}" if label else "")
                              for n, label in zip(item.components, item.labels, strict=False))
            chosen = " (your decision)" if item.by == "decision" else ""
            lines.append(f"  removed  [{item.log}] {item.mod}: {shown}{chosen}")
            lines.append(f"           conflicts with {item.because}")
            if item.reason:
                lines.append(f"           why: {item.reason[:200]}")
        for accepted in self.accepted:
            lines.append(f"  accepted [{accepted.log}] {accepted.finding} - {accepted.why}")
        for finding_id in self.stale_decisions:
            lines.append(f"  stale decision: {finding_id} is no longer in the report "
                         f"(the selection changed); not applied")
        if self.left_for_operator:
            lines.append(f"  left for you to decide ({len(self.left_for_operator)}):")
            for open_item in self.left_for_operator:
                lines.append(f"    [{open_item.log}] {open_item.finding} - "
                             f"{open_item.why}")
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "removed": [vars(r) for r in self.removed],
            "left_for_operator": [vars(u) for u in self.left_for_operator],
            "moved": [vars(m) for m in self.moved],
            "accepted": [vars(a) for a in self.accepted],
            "stale_decisions": list(self.stale_decisions),
        }


def _why_not(finding: Finding) -> str | None:
    """None when the rules decide this finding; otherwise the reason they do not."""
    if finding.severity != "error":
        return f"graded {finding.severity}, not error"
    if finding.evidence == "speculative":
        return "the claim is speculative (unverified upstream)"
    if finding.right is None:
        return "the rule names only one side"
    if finding.left.whole_mod and finding.right.whole_mod:
        return "whole mod vs whole mod: the rules say 'not both', not which one"
    return None


def _cheaper(left: Side, right: Side) -> tuple[Side, Side] | None:
    """
    (side to remove, side to keep) by the conflict report's own cost - pinned
    is cheaper than wholesale, fewer components cheaper than more. None on a
    tie: then the rules do not say which to keep, and picking one is a guess.
    """
    def cost(side: Side) -> int:
        return 10 ** 6 if side.whole_mod else len(side.components)
    if cost(left) == cost(right):
        return None
    return (left, right) if cost(left) < cost(right) else (right, left)


def _units_for(plan, log: str, key: str) -> list:
    """The plan units a rule's mod key names: the tp2 identity first, else the folder."""
    units = plan.logs.get(log, [])
    exact = [u for u in units if u.key == key]
    if exact:
        return exact
    by_folder = [u for u in units if normalize_key(u.folder) == key]
    # A folder holding two tp2s (eet: EET and EET_end) is ambiguous; refuse.
    return by_folder if len(by_folder) == 1 else []


def _present(plan, log: str, side: Side) -> set[int]:
    wanted = set(side.numbers)
    found: set[int] = set()
    for unit in _units_for(plan, log, side.key):
        for _path, _lang, comp, _comment in unit.lines:
            if side.whole_mod or comp in wanted:
                found.add(comp)
    return found


def apply_decisions(plan, report: ConflictReport, decisions: Decisions,
                    ruleset: RuleSet | None = None, context=None) -> ResolutionResult:
    """
    Apply the player's decisions.json to the plan, then re-check it.

    A chosen option removes exactly its components; a reorder is what the plan
    already does; adding a missing mod is outside a plan's reach and is listed,
    not faked. `report` must be built from `plan.installs()`.
    """
    result = ResolutionResult()
    by_id = {finding.id: finding for finding in report.findings}
    result.stale_decisions = sorted(decisions.findings - set(by_id))
    for finding_id, why in sorted(decisions.accept.items()):
        if finding_id in by_id:
            result.accepted.append(Accepted(by_id[finding_id].log,
                                            _describe(by_id[finding_id]), why, finding_id))
    for finding_id, option_id in sorted(decisions.choose.items()):
        if finding_id not in by_id:
            continue
        finding = by_id[finding_id]
        option = next((o for o in finding.options if o.id(finding_id) == option_id), None)
        if option is None and finding.last_blocked and any(
                o.id(finding_id) == option_id
                for o in finding_options(replace(finding, last_blocked=()))):
            # A "keep both" this way round is not offered: a rule says the
            # other side goes first, or must not coexist (review of #72).
            result.left_for_operator.append(Unresolved(
                finding.log, _describe(finding),
                "the \"keep both\" order you chose is not offered: a rule puts "
                + ", ".join(finding.last_blocked) + " first or forbids the pair",
                finding_id=finding_id))
            continue
        if option is None:
            raise ConfigError(f"decisions: {option_id} is not an option of {finding_id}; "
                              f"its options are "
                              f"{[o.id(finding_id) for o in finding.options]}")
        if option.action == KEEP_BOTH:
            # The order rule keep_both_rules made placed it - unless the plan
            # could not keep it (a cycle with other rules): then it is the
            # player's again, never recorded as settled (review of #72).
            pair = {finding.left.key, finding.right.key if finding.right else ""}
            broken = next((v for v in plan.residual if v.rule is not None
                           and v.rule.origin == DECIDED_ORDER and set(v.mods) == pair), None)
            if broken is not None:
                result.left_for_operator.append(Unresolved(
                    finding.log, _describe(finding),
                    f"you chose to {option.description}, but the plan could not keep "
                    f"that order: {broken.summary}", finding_id=finding_id))
            else:
                result.accepted.append(Accepted(finding.log, _describe(finding),
                                                option.description, finding_id))
            continue
        if option.action == INSTALL:
            result.left_for_operator.append(Unresolved(
                finding.log, _describe(finding),
                f"you chose to {option.description}: add it to the selection, "
                f"the plan cannot fetch it", finding_id=finding_id))
            continue
        if option.action != DESELECT:
            continue                  # REORDER: sorting the plan already does it
        side = Side(key=option.key, mod=option.mod,
                    components=tuple((n, "") for n in option.components),
                    whole_mod=option.whole_mod)
        targets = _present(plan, finding.log, side)
        units = _units_for(plan, finding.log, option.key)
        if not targets or not units:
            continue                  # an earlier decision already removed them
        labels = dict(finding.left.components
                      + (finding.right.components if finding.right else ()))
        for unit in units:
            unit.lines = [line for line in unit.lines if line[2] not in targets]
        numbers = tuple(sorted(targets))
        result.removed.append(Removal(
            log=finding.log, mod=option.mod, components=numbers,
            labels=tuple(labels.get(n, "") for n in numbers),
            because=option.description, reason=finding.reason,
            finding_id=finding_id, by="decision"))
    for log, units in list(plan.logs.items()):
        plan.logs[log] = [u for u in units if u.lines]
    if ruleset is not None:
        plan.reverify(ruleset, context)
    return result


def resolve_conflicts(plan, report: ConflictReport,
                      ruleset: RuleSet | None = None,
                      context=None, skip: Set[str] = frozenset()) -> ResolutionResult:
    """
    Apply the rules' own remedy to every incompatibility they decide.

    `plan` is an ordering.OrderPlan and is edited in place; `report` must have
    been built from `plan.installs()`, so its log labels are the plan's roles.
    """
    result = ResolutionResult()

    for finding in report.findings:
        if finding.kind != INCOMPATIBLE or finding.suppressed or finding.id in skip:
            continue
        why = _why_not(finding)
        if why is not None or finding.right is None:
            result.left_for_operator.append(Unresolved(
                finding.log, _describe(finding), why or "one-sided finding",
                finding_id=finding.id))
            continue
        if finding.origin == SUBCOMPONENT_ORIGIN:
            # WeiDU's own semantics, not a cost: the last option installed wins.
            loser, winner = finding.left, finding.right
        else:
            choice = _cheaper(finding.left, finding.right)
            if choice is None:
                result.left_for_operator.append(Unresolved(
                    finding.log, _describe(finding),
                    f"both sides pin an equal number of components "
                    f"({len(finding.left.components)}): the rules do not say "
                    f"which to keep", finding_id=finding.id))
                continue
            loser, winner = choice

        # An earlier removal may already have settled this pair.
        if not _present(plan, finding.log, winner) or not _present(
                plan, finding.log, loser):
            continue
        targets = _present(plan, finding.log, loser)
        units = _units_for(plan, finding.log, loser.key)
        if not units:
            result.left_for_operator.append(Unresolved(
                finding.log, _describe(finding),
                f"cannot tell which tp2 '{loser.mod}' means in this log",
                finding_id=finding.id))
            continue

        labels = dict(loser.components)
        for unit in units:
            unit.lines = [line for line in unit.lines if line[2] not in targets]
        numbers = tuple(sorted(targets))
        result.removed.append(Removal(
            log=finding.log, mod=loser.mod, components=numbers,
            labels=tuple(labels.get(n, "") for n in numbers),
            because=winner.describe(limit=3), reason=finding.reason,
            finding_id=finding.id))

    for log, units in list(plan.logs.items()):
        plan.logs[log] = [u for u in units if u.lines]
    if ruleset is not None:
        plan.reverify(ruleset, context)
    return result


def _describe(finding: Finding) -> str:
    right = f" vs {finding.right.describe(limit=3)}" if finding.right else ""
    return f"{finding.left.describe(limit=3)}{right}"


# ------------------------------------------------- what WeiDU would refuse
_EET_CORE = ("eet", 0)


def _drop(plan, log: str, mod: str, numbers) -> tuple[tuple[int, ...], tuple[str, ...]]:
    """Remove `numbers` of `mod` from one log of the plan; what was removed."""
    gone: list[tuple[int, str]] = []
    for unit in plan.logs.get(log, []):
        if unit.key != mod:
            continue
        keep = []
        for line in unit.lines:
            if line[2] in numbers:
                gone.append((line[2], line[3].rsplit(" : ", 1)[0].strip()))
            else:
                keep.append(line)
        unit.lines = keep
    plan.logs[log] = [u for u in plan.logs.get(log, []) if u.lines]
    gone.sort()
    return tuple(n for n, _l in gone), tuple(label for _n, label in gone)


# What may go on BG2:EE BEFORE the EET core, by EET's own readme ("Core EET
# component requires 'clean' BG2:EE installation with latest patch ... and
# (optionally) the Enhanced Edition Fixpack"), and BWS-NG's games/eet.json,
# whose bg2ee sequence orders eefixpack:0-2 before eet:0. Nothing else: EET
# warns that other mods before its core "may cause problems".
BEFORE_EET_CORE = {"eefixpack": "EET's readme allows the Enhanced Edition "
                                "Fixpack on BG2:EE before its core, and BWS-NG "
                                "orders it there (games/eet.json)"}
_FROM_BWS = ("BWS-NG's games/eet.json orders it on BG2:EE before the EET core "
             "(bg2ee sequence)")


def before_eet_core(eet_sequences: dict | None) -> dict[str, str]:
    """
    What may go on BG2:EE before the EET core, and why.

    BWS-NG's `games/eet.json` (`--eet-sequence`, cached by default) is the
    maintained list: its bg2ee sequence names everything installed before
    `eet:0`, and it contains what EET's readme allows. When it is not
    available, or not in the shape expected, the readme's rule stands alone.
    """
    allowed = dict(BEFORE_EET_CORE)
    sequences = eet_sequences.get("sequences") if isinstance(eet_sequences, dict) else None
    if not isinstance(sequences, list):
        return allowed
    for sequence in sequences:
        if not isinstance(sequence, dict) or str(sequence.get("game")).lower() != "bg2ee":
            continue
        for entry in sequence.get("order") or ():
            mod, _sep, number = str(entry).partition(":")
            key = normalize_key(mod)
            if key == "eet" and number.strip() == "0":
                break
            if key:
                allowed.setdefault(key, _FROM_BWS)
    return allowed


def _move_before_core(plan, log: str, mod: str, numbers) -> tuple[int, ...]:
    """Move `numbers` of `mod` to just before the EET core; what was moved."""
    units = plan.logs.get(log, [])
    core = next((i for i, unit in enumerate(units) if unit.key == _EET_CORE[0]
                 and any(line[2] == _EET_CORE[1] for line in unit.lines)), None)
    source = next((u for u in units if u.key == mod
                   and any(line[2] in numbers for line in u.lines)), None)
    if core is None or source is None or units.index(source) < core:
        return ()
    moved = [line for line in source.lines if line[2] in numbers]
    source.lines = [line for line in source.lines if line[2] not in numbers]
    part = max(u.part for u in units if u.key == mod) + 1
    units.insert(core, replace(source, lines=moved, part=part, split=True,
                               parts=part + 1))
    plan.logs[log] = [u for u in units if u.lines]
    return tuple(sorted(line[2] for line in moved))


def resolve_refusals(plan, constraints, games=None, ruleset=None,
                     context=None, before_core: dict[str, str] | None = None
                     ) -> ResolutionResult:
    """
    Make the plan one WeiDU can finish (ADR-0025).

    The plan is simulated with every staged mod's own tp2 constraints. A
    component WeiDU would refuse - wrong game, a requirement not installed by
    then, a FORBID tripped - is removed, with WeiDU's reason: that is the
    outcome WeiDU would produce anyway, minus the aborted run. When EET would
    refuse the merge, the BG:EE mods its compatibility.tbl cannot import (and
    the wrong options it names) are removed from the BG:EE plan instead - EET's
    own table decides that, not this tool. The EET core itself is never
    removed: refused for any other reason, it is left for the operator.
    A mod `before_core` names (default: EET's readme rule; see
    `before_eet_core`) that refuses EET is moved before the core instead.
    """
    before = before_core if before_core is not None else BEFORE_EET_CORE
    from .simulate import EET_LOG, PRE_EET_LOG, simulate_install, steps_of

    result = ResolutionResult()
    for _round in range(8):                       # each round can only shrink the plan
        logs = {role: steps_of(units) for role, units in plan.logs.items()}
        simulation = simulate_install(logs, constraints.by_mod, games=games,
                                      eet_rules=constraints.eet)
        if not simulation.refused:
            break
        changed = False
        for refusal in simulation.refused:
            step = (refusal.mod, refusal.component)
            if step == _EET_CORE and refusal.log == EET_LOG:
                if constraints.eet is not None and refusal.reason.startswith(
                        "EET refuses the merge"):
                    for mod, number in logs.get(PRE_EET_LOG, []):
                        unknown = normalize_key(mod) not in constraints.eet.allowed
                        if unknown or (mod, number) in constraints.eet.wrong_components:
                            numbers, labels = _drop(plan, PRE_EET_LOG, mod, {number})
                            if numbers:
                                changed = True
                                result.removed.append(Removal(
                                    PRE_EET_LOG, mod, numbers, labels,
                                    because=("EET cannot import it: not in EET's "
                                             "compatibility.tbl" if unknown else
                                             "EET fails the merge on this option")))
                    break                             # re-simulate before going on
                result.left_for_operator.append(Unresolved(
                    refusal.log, "eet #0",
                    f"the EET core would be refused: {refusal.reason}"))
                continue
            if (refusal.log == EET_LOG and refusal.mod in before
                    and ("refuses game EET" in refusal.reason
                         or "the game is EET" in refusal.reason)):
                moved = _move_before_core(plan, EET_LOG, refusal.mod,
                                          {refusal.component})
                if moved:
                    changed = True
                    result.moved.append(Move(EET_LOG, refusal.mod, moved,
                                             before[refusal.mod]))
                    continue
            numbers, labels = _drop(plan, refusal.log, refusal.mod,
                                    {refusal.component})
            if numbers:
                changed = True
                result.removed.append(Removal(refusal.log, refusal.mod, numbers,
                                              labels, because=refusal.reason))
        if not changed:
            break
    if ruleset is not None:
        plan.reverify(ruleset, context)
    return result


def keep_both_rules(report: ConflictReport, decisions: Decisions) -> list[Rule]:
    """
    The order rules the player's "keep both" choices make (GUI-AUDIT item 28,
    ADR-0033 amendment): the side chosen to win installs after the other,
    component for component as the finding names them. Plan with these on top
    of the rule set, then apply the decisions to the plan as before; a choice
    whose finding is gone makes no rule.
    """
    by_id = {finding.id: finding for finding in report.findings}
    rules = []
    for finding_id, option_id in sorted(decisions.choose.items()):
        finding = by_id.get(finding_id)
        if finding is None or finding.right is None:
            continue
        option = next((o for o in finding.options if o.id(finding_id) == option_id), None)
        if option is None or option.action != KEEP_BOTH:
            continue
        first, last = ((finding.left, finding.right) if finding.left.key == option.before
                       else (finding.right, finding.left))
        rules.append(Rule(kind=ORDER, left=_spec(last), right=(_spec(first),),
                          direction="after", origin=DECIDED_ORDER, severity="warning",
                          message=f"your decision: {option.description}"))
    return rules


def _spec(side: Side) -> ModSpec:
    numbers = frozenset(n for n, _label in side.components)
    return ModSpec(side.key, side.mod, None if side.whole_mod or not numbers else numbers)
