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
import os
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from .rules import (DEPENDS, INCOMPATIBLE, ORDER, Context, Install, RuleSet,
                    check_all)

# Not a rule kind - a per-mod known issue, reported alongside the pairwise ones.
KNOWN_ISSUE = "known-issue"

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
    components: Tuple[Tuple[int, str], ...] = ()
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
    def numbers(self) -> Tuple[int, ...]:
        return tuple(n for n, _label in self.components)


@dataclass
class Finding:
    kind: str
    severity: str
    log: str
    left: Side
    right: Optional[Side] = None
    scope: str = "cross-mod"          # cross-mod | same-mod | missing
    reason: str = ""
    evidence: str = ""
    source: str = ""
    workaround: str = ""
    origin: str = ""
    raw_severity: str = ""
    remedy: str = ""
    order_fixable: bool = False
    fixed_by_plan: Optional[bool] = None
    stale_risk: str = ""
    suppressed: str = ""

    @property
    def rank(self) -> int:
        return SEVERITY_ORDER.get(self.severity, 3)

    @property
    def actionable(self) -> bool:
        """Neither withheld nor already dealt with by the ordering plan."""
        return not (self.suppressed or self.fixed_by_plan)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "severity": self.severity,
            "raw_severity": self.raw_severity, "log": self.log,
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
        }


@dataclass
class ConflictReport:
    findings: List[Finding] = field(default_factory=list)
    rules_checked: int = 0
    notes_checked: int = 0
    pairs_with_both_mods: int = 0
    pairs_cleared_by_components: int = 0
    undirected: int = 0

    def __len__(self) -> int:
        return len(self.findings)

    @property
    def actionable(self) -> List[Finding]:
        return [f for f in self.findings if f.actionable]

    def of(self, *kinds: str) -> List[Finding]:
        return [f for f in self.findings if f.kind in kinds]

    def as_dict(self) -> dict:
        return {
            "rules_checked": self.rules_checked,
            "known_issues_checked": self.notes_checked,
            "mod_pairs_with_a_conflict_rule": self.pairs_with_both_mods,
            "cleared_because_the_components_are_not_installed":
                self.pairs_cleared_by_components,
            "order_rules_with_no_direction": self.undirected,
            "findings": [f.as_dict() for f in self.findings],
        }

    def write_json(self, path: str) -> None:
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.as_dict(), fh, indent=2, sort_keys=True)
            fh.write("\n")


# ------------------------------------------------------------------- building
def _side(install: Install, key: str, display: str,
          components: Sequence[int], spec_components) -> Side:
    labelled = tuple((n, install.component_label(key, n)) for n in sorted(components))
    return Side(key=key, mod=install.display.get(key, display),
                components=labelled, whole_mod=spec_components is None)


def _coverage(installs: Sequence[Install], ruleset: RuleSet) -> Tuple[int, int]:
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


def _remedy(kind: str, scope: str, left: Side, right: Optional[Side],
            direction: Optional[str]) -> Tuple[str, bool]:
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
        return (f"deselect one of the two groups of {left.mod} above - "
                f"{len(left.components)} vs "
                f"{len(right.components) if right else '?'} component(s)", False)

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
        return (f"drop {cheapest.mod} or {other.mod} - the rules do not narrow "
                f"it to components", False)
    short = cheapest.describe(limit=3)
    alternative = (f"drop {other.mod}" if other.whole_mod
                   else f"deselect {other.describe(limit=3)}")
    return (f"deselect {short}  (alternative: {alternative})", False)


def build_conflict_report(installs: Sequence[Install], ruleset: RuleSet,
                          context: Optional[Context] = None,
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
            stale_risk=violation.stale_risk, suppressed=violation.suppressed))

    report.findings.extend(_known_issues(installs, ruleset))
    report.findings.sort(key=lambda f: (f.rank, f.kind, f.left.mod))
    return report


def _known_issues(installs: Sequence[Install], ruleset: RuleSet) -> List[Finding]:
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


def _render_one(finding: Finding, stream) -> None:
    mark = {"error": "!!", "warning": " !", "note": " ~"}.get(finding.severity, "  ")
    where = f"[{finding.log}] " if finding.log else ""
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
