"""
Component-level conflict reporting.

The order checker answers "are these two mods in the wrong order?". This answers
the question that follows: *which component of which mod fights which component
of which other mod - or of itself - and what is the smallest thing I can change?*

Three things make the difference between a list of complaints and a usable
report:

* **The component intersection, not the rule.** A rule says
  `JA#BGT_AdvPack(2,48,51) : bg1re(6,27,30,41)`. Reporting that as "these two
  mods conflict" is wrong: what matters is which of those components you
  actually installed. On the real 796-component install, 60 mod pairs have a
  known conflict rule and every one of them is clear once the component sets are
  intersected. A report that cried wolf on all 60 would be worse than none.
* **Provenance.** krion64 grades its claims `mechanism-verified` or
  `speculative` and records what was read. A speculative observation must not be
  presented in the same voice as a verified one.
* **The narrowest remedy.** "infinity_ui and stratagems are incompatible" is not
  actionable. "deselect stratagems #3183" is. Where a rule names components, the
  fix is at component granularity, and the smaller side is the cheaper fix.
"""
import json
from dataclasses import dataclass, field
from collections.abc import Sequence

from .atomic import write_text
from .contract import SCHEMA_VERSION, stable_id
from .rules import (DEPENDS, INCOMPATIBLE, ORDER, Context, Install, RuleSet,
                    check_all)

# Not a rule kind - a per-mod known issue, reported alongside the pairwise ones.
KNOWN_ISSUE = "known-issue"

# Not from any rule set: WeiDU's own SUBCOMPONENT semantics, read off the log.
SUBCOMPONENT_ORIGIN = "WeiDU SUBCOMPONENT"

# Worst first. `note` is krion64's `advisories` channel: real observations that
# nobody has verified, useful to read and wrong to act on blindly.
SEVERITY_ORDER = {"error": 0, "warning": 1, "note": 2}

EVIDENCE_NOTE = {
    "mechanism-verified": "verified: someone traced the mechanism",
    "speculative": "SPECULATIVE: not verified, judge it yourself",
}


@dataclass(frozen=True)
class Side:
    """One end of a conflict, narrowed to what is actually installed."""
    key: str
    mod: str
    components: tuple[tuple[int, str], ...] = ()
    whole_mod: bool = False       # the rule named no components: any will do

    def describe(self, limit: int = 6) -> str:
        if self.whole_mod or not self.components:
            return f"{self.mod} (whole mod)"
        shown = self.components[:limit]
        rest = len(self.components) - len(shown)
        parts = ", ".join(f"#{n}" + (f" {label}" if label else "")
                          for n, label in shown)
        return f"{self.mod}: {parts}" + (f", +{rest} more" if rest else "")

    @property
    def numbers(self) -> tuple[int, ...]:
        return tuple(n for n, _label in self.components)


@dataclass
class Finding:
    kind: str
    severity: str
    log: str
    left: Side
    right: Side | None = None
    scope: str = "cross-mod"          # cross-mod | same-mod | missing
    reason: str = ""
    evidence: str = ""
    source: str = ""
    workaround: str = ""
    origin: str = ""
    raw_severity: str = ""
    remedy: str = ""
    order_fixable: bool = False
    fixed_by_plan: bool | None = None
    stale_risk: str = ""
    suppressed: str = ""
    first: str = ""                   # ORDER: the key of the mod that goes first
    # The log's own file name, when `log` is the plan's role for it: the id
    # keeps the role (what --decisions matches), the reader sees the file.
    shown_log: str = ""
    # Sides that may not be installed last when both are kept (item 28): an
    # error order rule puts them first, or an error incompatibility covers
    # the same pair, so "keep both" that way is not offered.
    last_blocked: tuple[str, ...] = ()

    @property
    def rank(self) -> int:
        return SEVERITY_ORDER.get(self.severity, 3)

    @property
    def id(self) -> str:
        """The same conflict, the same id, run after run (ADR-0030)."""
        right = (None if self.right is None
                 else (self.right.key, self.right.numbers, self.right.whole_mod))
        return stable_id("conflict", self.kind, self.log, self.scope, self.origin,
                         (self.left.key, self.left.numbers, self.left.whole_mod),
                         right, self.source)

    @property
    def actionable(self) -> bool:
        """Neither withheld nor already dealt with by the ordering plan."""
        return not (self.suppressed or self.fixed_by_plan)

    @property
    def options(self) -> list[Option]:
        return finding_options(self)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind, "severity": self.severity,
            "raw_severity": self.raw_severity, "log": self.shown_log or self.log,
            "scope": self.scope,
            "left": {"mod": self.left.mod, "components": list(self.left.numbers),
                     "whole_mod": self.left.whole_mod},
            "right": (None if self.right is None else
                      {"mod": self.right.mod,
                       "components": list(self.right.numbers),
                       "whole_mod": self.right.whole_mod}),
            "reason": self.reason, "evidence": self.evidence,
            "source": self.source, "workaround": self.workaround,
            "origin": self.origin, "remedy": self.remedy,
            "order_fixable": self.order_fixable,
            "fixed_by_plan": self.fixed_by_plan,
            "stale_risk": self.stale_risk, "suppressed": self.suppressed,
            "options": [o.as_dict(self.id) for o in self.options],
        }


# ------------------------------------------------------------------- options
DESELECT = "deselect"       # remove these components from the plan
REORDER = "reorder"         # install one side before the other
INSTALL = "install"         # add what is missing - outside a plan's reach
KEEP_BOTH = "keep-both"     # keep both sides, one installed after the other (item 28)


@dataclass(frozen=True)
class Option:
    """
    One way to clear a finding, with its price (M2): how many of the chosen
    components the plan loses. `applicable` says whether `--decisions` can
    apply it to the plan; adding a missing mod needs a fetch, so it cannot.
    `recommended` is what `--resolve-conflicts` would do, and only where the
    rules decide - never on a tie.
    """
    action: str
    mod: str
    key: str
    components: tuple[int, ...]
    whole_mod: bool
    cost: int
    applicable: bool
    recommended: bool
    description: str
    before: str = ""            # REORDER, KEEP_BOTH: the mod that goes first

    def id(self, finding_id: str) -> str:
        return stable_id("option", finding_id, self.action, self.key,
                         self.components, self.whole_mod, self.before)

    def as_dict(self, finding_id: str) -> dict:
        return {"id": self.id(finding_id), "action": self.action, "mod": self.mod,
                "components": list(self.components), "whole_mod": self.whole_mod,
                "cost": self.cost, "applicable": self.applicable,
                "recommended": self.recommended, "description": self.description}


def _pinned_cost(side: Side) -> int:
    return 10 ** 6 if side.whole_mod else len(side.components)


def _deselect(side: Side, recommended: bool, verb: str = "deselect") -> Option:
    what = f"drop {side.mod} (whole mod)" if side.whole_mod else f"{verb} {side.describe(3)}"
    return Option(DESELECT, side.mod, side.key, side.numbers, side.whole_mod,
                  len(side.components), True, recommended, what)


def finding_options(finding: Finding) -> list[Option]:
    """Every way to clear `finding`, cheapest first."""
    left, right = finding.left, finding.right
    if finding.kind == ORDER and right is not None:
        first, second = (left, right) if finding.first == left.key else (right, left)
        return [Option(REORDER, second.mod, second.key, (), False, 0, True, True,
                       f"install {first.mod} before {second.mod}", before=first.key)]
    if finding.kind == DEPENDS:
        wanted = right.mod if right else "the prerequisite"
        options = [_deselect(left, False)]
        if right is not None:
            options.insert(0, Option(INSTALL, right.mod, right.key, right.numbers,
                                     right.whole_mod, 0, False, False,
                                     f"install {wanted}"))
        return options
    if right is None:
        return [_deselect(left, False)]
    if finding.origin == SUBCOMPONENT_ORIGIN:
        # WeiDU's own semantics: the option installed last is the one that stays.
        return [_deselect(left, True, "keep the last option, deselect"),
                _deselect(right, False, "keep the earlier option, deselect")]
    decides = (finding.kind == INCOMPATIBLE and finding.severity == "error"
               and finding.evidence != "speculative"
               and not (left.whole_mod and right.whole_mod)
               and _pinned_cost(left) != _pinned_cost(right))
    cheaper = left if _pinned_cost(left) < _pinned_cost(right) else right
    options = [_deselect(left, decides and cheaper is left),
               _deselect(right, decides and cheaper is right)]
    return (sorted(options, key=lambda o: (not o.recommended, o.whole_mod, o.cost))
            + _keep_both(finding))


def _keep_both(finding: Finding) -> list[Option]:
    """
    Two components that touch the same thing, where no rule says they must
    not coexist: keep both, the one installed last winning what they share
    (GUI-AUDIT item 28, ADR-0033 amendment). Never for an error - a "hard"
    incompatibility is not an overwrite to order - and never within one mod.
    """
    left, right = finding.left, finding.right
    if (finding.kind != INCOMPATIBLE or finding.severity == "error" or right is None
            or left.key == right.key):
        return []
    return [Option(KEEP_BOTH, last.mod, last.key, last.numbers, last.whole_mod, 0, True,
                   False, f"keep both, {last.mod} installed last (its changes win)",
                   before=first.key)
            for first, last in ((left, right), (right, left))
            if last.key not in finding.last_blocked]


def _overlap(side: Side, components) -> bool:
    """Whether a rule naming `components` (None: any) covers this side."""
    return components is None or side.whole_mod or bool(set(side.numbers) & set(components))


def _block_keep_both(findings: list[Finding], ruleset: RuleSet) -> None:
    """
    What "keep both" may not offer (review of #72). A tp2's one-sided
    FORBID_COMPONENT makes an error order rule and a warning incompatibility:
    keeping both with the forbidding side last is what WeiDU refuses. And a
    pair an error incompatibility also covers - BWS-NG hard, krion64 soft -
    is not an overwrite to order at all.
    """
    errors = [f for f in findings if f.kind == INCOMPATIBLE and f.severity == "error"
              and f.right is not None]
    orders = [r for r in ruleset.rules if r.kind == ORDER and r.severity == "error"
              and r.direction in ("before", "after")]
    for finding in findings:
        left, right = finding.left, finding.right
        if finding.kind != INCOMPATIBLE or finding.severity == "error" or right is None:
            continue
        sides = {left.key: left, right.key: right}
        blocked = set()
        for error in errors:
            pair = (error.left, error.right) if error.right is not None else ()
            if ({side.key for side in pair} == set(sides) and error.log == finding.log
                    and all(set(sides[s.key].numbers) & set(s.numbers) or s.whole_mod
                            or sides[s.key].whole_mod for s in pair)):
                blocked |= set(sides)
        for rule in orders:
            for spec in rule.right:
                first, last = (rule.left, spec) if rule.direction == "before" else (spec, rule.left)
                if ({first.mod, last.mod} == set(sides) and first.mod != last.mod
                        and _overlap(sides[first.mod], first.components)
                        and _overlap(sides[last.mod], last.components)):
                    blocked.add(first.mod)
        finding.last_blocked = tuple(sorted(blocked))


@dataclass
class ConflictReport:
    findings: list[Finding] = field(default_factory=list)
    rules_checked: int = 0
    notes_checked: int = 0
    pairs_with_both_mods: int = 0
    pairs_cleared_by_components: int = 0
    undirected: int = 0
    engine_limits: list = field(default_factory=list)    # limits.LimitsReport per install

    def __len__(self) -> int:
        return len(self.findings)

    @property
    def actionable(self) -> list[Finding]:
        return [f for f in self.findings if f.actionable]

    def of(self, *kinds: str) -> list[Finding]:
        return [f for f in self.findings if f.kind in kinds]

    def as_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "rules_checked": self.rules_checked,
            "known_issues_checked": self.notes_checked,
            "mod_pairs_with_a_conflict_rule": self.pairs_with_both_mods,
            "cleared_because_the_components_are_not_installed":
                self.pairs_cleared_by_components,
            "order_rules_with_no_direction": self.undirected,
            "findings": [f.as_dict() for f in self.findings],
            "engine_limits": [r.as_dict() for r in self.engine_limits],
        }

    def write_json(self, path: str) -> None:
        write_text(path, json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n")


# ------------------------------------------------------------------- building
def _side(install: Install, key: str, display: str,
          components: Sequence[int], spec_components) -> Side:
    labelled = tuple((n, install.component_label(key, n)) for n in sorted(components))
    return Side(key=key, mod=install.display.get(key, display),
                components=labelled, whole_mod=spec_components is None)


def _coverage(installs: Sequence[Install], ruleset: RuleSet) -> tuple[int, int]:
    """
    How much of the rule set was genuinely examined.

    Without this the report is unfalsifiable: "no conflicts found" reads the same
    whether 700 rules were evaluated or none matched anything at all.
    """
    both, cleared = 0, 0
    for rule in ruleset.rules:
        if rule.kind != INCOMPATIBLE:
            continue
        for install in installs:
            for right in rule.right:
                if (rule.left.mod not in install.components
                        or right.mod not in install.components):
                    continue
                both += 1
                if not (install.matched(rule.left) and install.matched(right)):
                    cleared += 1
    return both, cleared


def _remedy(kind: str, scope: str, left: Side, right: Side | None,
            direction: str | None) -> tuple[str, bool]:
    """The smallest change that clears this finding, and whether order does it."""
    if kind == ORDER and right is not None:
        first, second = (left, right) if direction == "before" else (right, left)
        return (f"install {first.mod} before {second.mod}", True)

    if kind == DEPENDS:
        wanted = right.mod if right else "the prerequisite"
        if left.whole_mod:
            return (f"install {wanted}, or remove {left.mod}", False)
        return (f"install {wanted}, or deselect {left.describe()}", False)

    if scope == "same-mod":
        return ((f"deselect one of the two groups of {left.mod} above - "
                f"{len(left.components)} vs "
                f"{len(right.components) if right else '?'} component(s)"), False)

    if right is None:
        return (f"review {left.describe()}", False)

    # Cross-mod: the cheaper side to give up is the one with fewer components,
    # and a side the rule pinned to specific components is always cheaper than
    # one it condemned wholesale.
    options = []
    for side in (left, right):
        cost = 10 ** 6 if side.whole_mod else len(side.components)
        options.append((cost, side))
    options.sort(key=lambda pair: pair[0])
    cheapest = options[0][1]
    other = options[1][1]
    if cheapest.whole_mod:
        return ((f"drop {cheapest.mod} or {other.mod} - the rules do not narrow "
                f"it to components"), False)
    short = cheapest.describe(limit=3)
    alternative = (f"drop {other.mod}" if other.whole_mod
                   else f"deselect {other.describe(limit=3)}")
    return (f"deselect {short}  (alternative: {alternative})", False)


def build_conflict_report(installs: Sequence[Install], ruleset: RuleSet,
                          context: Context | None = None,
                          plan=None) -> ConflictReport:
    """
    Turn rule violations into component-level findings.

    `plan`, when given, is an ordering.OrderPlan: an order finding it already
    resolves is marked `fixed_by_plan` rather than repeated as outstanding work.
    """
    context = context or Context()
    report = ConflictReport(rules_checked=len(ruleset),
                            notes_checked=len(ruleset.notes),
                            undirected=ruleset.undirected)
    report.pairs_with_both_mods, report.pairs_cleared_by_components = _coverage(
        installs, ruleset)

    by_label = {install.label: install for install in installs}
    unresolved_by_plan = set()
    if plan is not None:
        unresolved_by_plan = {(v.kind, tuple(sorted(v.mods))) for v in plan.residual}

    for violation in check_all(installs, ruleset, context):
        rule = violation.rule
        if rule is None:
            continue
        install = by_label.get(violation.log) or (installs[0] if installs else None)
        if install is None:
            continue

        left = _side(install, rule.left.mod, rule.left.display,
                     violation.left_components, rule.left.components)
        right = None
        if len(violation.mods) > 1:
            right_key = violation.mods[1]
            spec = next((s for s in rule.right if s.mod == right_key), None)
            right = _side(install, right_key,
                          spec.display if spec else right_key,
                          violation.right_components,
                          spec.components if spec else None)
        elif rule.kind == DEPENDS:
            spec = rule.right[0] if rule.right else None
            if spec:
                right = Side(key=spec.mod, mod=spec.display,
                             components=tuple((n, "") for n in
                                              sorted(spec.components or ())),
                             whole_mod=spec.components is None)

        if rule.kind == DEPENDS:
            scope = "missing"
        elif right is not None and right.key == left.key:
            scope = "same-mod"
        else:
            scope = "cross-mod"

        remedy, order_fixable = _remedy(rule.kind, scope, left, right,
                                        rule.direction)
        fixed = None
        if rule.kind == ORDER and plan is not None:
            fixed = (ORDER, tuple(sorted(violation.mods))) not in unresolved_by_plan

        report.findings.append(Finding(
            kind=rule.kind, severity=violation.severity, log=violation.log,
            left=left, right=right, scope=scope,
            reason=rule.message, evidence=rule.evidence, source=rule.source,
            workaround=rule.workaround, origin=violation.origin,
            raw_severity=rule.raw_severity, remedy=remedy,
            order_fixable=order_fixable, fixed_by_plan=fixed,
            stale_risk=violation.stale_risk, suppressed=violation.suppressed,
            first=(right.key if right is not None and rule.direction != "before"
                   else left.key) if rule.kind == ORDER else ""))

    _block_keep_both(report.findings, ruleset)
    report.findings.extend(_known_issues(installs, ruleset))
    report.findings.extend(_subcomponent_clashes(installs))
    report.findings.sort(key=lambda f: (f.rank, f.kind, f.left.mod))
    return report


def _subcomponent_clashes(installs: Sequence[Install]) -> list[Finding]:
    """
    Two options of one WeiDU SUBCOMPONENT group in the same install.

    WeiDU logs a SUBCOMPONENT choice as `// Group -> Option`. The options of one
    group are mutually exclusive by the mod's own design: when the second is
    installed, WeiDU uninstalls the first. No rule set is needed to know that,
    and the outcome is not a judgement call - the last one wins. The finding
    names it so the plan can skip the install-then-uninstall round trip.
    """
    findings: list[Finding] = []
    for install in installs:
        seen = set()
        for key, labels in install.labels.items():
            groups: dict = {}
            for number, label in labels.items():
                if " -> " not in label:
                    continue
                group = label.split(" -> ", 1)[0].strip()
                at = install.positions.get(key, {}).get(number, 0)
                groups.setdefault(group, []).append((at, number, label))
            for group, members in groups.items():
                if len(members) < 2:
                    continue
                members.sort()
                identity = (group, tuple(n for _at, n, _label in members))
                if identity in seen:           # a mod registered under two keys
                    continue
                seen.add(identity)
                mod = install.display.get(key, key)
                *earlier, (_at, last, last_label) = members
                left = Side(key=key, mod=mod, components=tuple(
                    (n, label) for _at, n, label in earlier))
                right = Side(key=key, mod=mod, components=((last, last_label),))
                findings.append(Finding(
                    kind=INCOMPATIBLE, severity="error", log=install.label,
                    left=left, right=right, scope="same-mod",
                    reason=(f"options of the SUBCOMPONENT group '{group}' are "
                            f"mutually exclusive; WeiDU uninstalls the earlier "
                            f"one when it installs #{last}"),
                    origin=SUBCOMPONENT_ORIGIN,
                    remedy=f"keep #{last} (the one WeiDU ends with), drop "
                           + ", ".join(f"#{n}" for _at, n, _label in earlier)))
    return findings


def _known_issues(installs: Sequence[Install], ruleset: RuleSet) -> list[Finding]:
    """
    Per-mod known issues, narrowed to the components actually installed.

    A note pinned to components (`cdtweaks` #260 and #2680 cost frame rate under
    EEex) is only worth printing if you installed one of them. A note with no
    component list applies to the mod as a whole.
    """
    out = []
    for note in ruleset.notes:
        for install in installs:
            installed = install.components.get(note.mod)
            if not installed:
                continue
            hit = installed if note.components is None else (
                installed & set(note.components))
            if not hit:
                continue
            side = _side(install, note.mod, note.display, sorted(hit),
                         note.components)
            out.append(Finding(
                kind=KNOWN_ISSUE, severity=note.severity, log=install.label,
                left=side, scope="known-issue", reason=note.summary,
                evidence=note.evidence, source=note.forum,
                workaround=note.workaround, origin=note.origin,
                remedy="" if note.workaround else "read it and decide"))
    return out


# ------------------------------------------------------------------ rendering
_KIND_TITLE = {
    INCOMPATIBLE: "INCOMPATIBLE COMPONENTS",
    ORDER: "ORDER-SENSITIVE COMPONENTS",
    DEPENDS: "MISSING PREREQUISITES",
    KNOWN_ISSUE: "KNOWN ISSUES FOR COMPONENTS YOU INSTALLED",
}


def render_conflict_report(report: ConflictReport, stream, limit: int = 40,
                           show_notes: bool = False) -> None:
    print(file=stream)
    print("COMPONENT CONFLICT REPORT", file=stream)
    print(f"  {report.rules_checked} rule(s) and {report.notes_checked} known "
          f"issue(s) evaluated; "
          f"{report.pairs_with_both_mods} pair(s) where both mods are "
          f"installed and a conflict rule exists, "
          f"{report.pairs_cleared_by_components} cleared because the named "
          f"components are not installed", file=stream)
    if report.undirected:
        print(f"  {report.undirected} order-sensitive pair(s) upstream never said "
              f"which way round - not checked", file=stream)

    shown_any = False
    for kind in (INCOMPATIBLE, DEPENDS, KNOWN_ISSUE, ORDER):
        group = [f for f in report.of(kind)
                 if show_notes or f.severity != "note"]
        if not group:
            continue
        shown_any = True
        outstanding = [f for f in group if f.actionable]
        print(f"\n  {_KIND_TITLE[kind]} ({len(outstanding)} outstanding "
              f"of {len(group)}):", file=stream)
        for finding in group[:limit]:
            _render_one(finding, stream)
        if len(group) > limit:
            print(f"    ... {len(group) - limit} more, see --conflict-report",
                  file=stream)

    hidden = [f for f in report.findings if f.severity == "note"]
    if hidden and not show_notes:
        print(f"\n  {len(hidden)} unverified advisory finding(s) withheld; "
              f"--show-advisories to see them", file=stream)
    if not shown_any:
        print("  nothing fired: no installed component pair matches a rule.",
              file=stream)
    if report.engine_limits:
        print("\n  ENGINE LIMITS (what the chosen components add to the game's tables):",
              file=stream)
        for limits in report.engine_limits:
            print(limits.render(), file=stream)


def _render_one(finding: Finding, stream) -> None:
    mark = {"error": "!!", "warning": " !", "note": " ~"}.get(finding.severity, "  ")
    shown = finding.shown_log or finding.log
    where = f"[{shown}] " if shown else ""
    print(f"    {mark} {where}{finding.left.describe()}", file=stream)
    if finding.right is not None:
        joiner = {"same-mod": "vs (same mod)", "missing": "needs"}.get(
            finding.scope, "vs")
        print(f"          {joiner} {finding.right.describe()}", file=stream)
    if finding.reason:
        print(f"          why: {finding.reason[:220]}", file=stream)
    if finding.evidence in EVIDENCE_NOTE:
        print(f"          {EVIDENCE_NOTE[finding.evidence]}", file=stream)
    if finding.source:
        print(f"          source: {finding.source[:140]}", file=stream)
    if finding.fixed_by_plan:
        print(f"          FIXED by --plan-order: {finding.remedy}", file=stream)
    elif finding.remedy:
        print(f"          fix: {finding.remedy}", file=stream)
    if finding.workaround:
        print(f"          workaround: {finding.workaround[:200]}", file=stream)
    if finding.stale_risk:
        print(f"          may be stale: {finding.stale_risk}", file=stream)
    if finding.suppressed:
        print(f"          suppressed: {finding.suppressed}", file=stream)
    if finding.actionable:
        # What decisions.json needs: the finding's id and one option's id.
        print(f"          id: {finding.id}; options:", file=stream)
        for option in finding.options:
            mark = "*" if option.recommended else " "
            note = "" if option.applicable else "  (not applicable to a plan)"
            print(f"           {mark} {option.id(finding.id)}  {option.description}"
                  f"  [cost {option.cost}]{note}", file=stream)
