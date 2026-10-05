"""
Install-order, incompatibility and dependency checking.

`WeiDU.log` records exactly what is installed and in what order, so the two
questions a 148-mod build actually needs answering can be answered offline:

  * is anything installed in an order the community says breaks it?
  * are two components installed that are known to conflict?
  * is a component installed whose prerequisite is missing?

Rules come from two places, both optional:

  * **The mods themselves.** A Project Infinity `[Metadata]` ini carries
    `Before=` / `After=` lists (see modmeta.py). A mod that ships one needs no
    external data.
  * **Community rule sets** in the BigWorldSetup-Next-Generation shape
    (`data/rules/order.json`, `incompatibilities.json`, `dependencies.json`),
    ~850 rules harvested from those same ini files and from BWS.

Rule syntax, as used by those files:

    "modA(-):modB(100)|modC(1,2)"      direction: before|after   severity: error|warning

`(-)` means any component of that mod; `(100)` one; `(1,2)` a list; `|`
separates alternatives on the right-hand side. Nothing here installs, uninstalls
or reorders anything: it reports.
"""
import json
import os
import re
from dataclasses import dataclass, field
from typing import (Any, Dict, FrozenSet, List, Optional, Protocol,
                    Sequence, Tuple)

from .errors import ConfigError
from .naming import normalize_key
from .versions import is_newer

ORDER, INCOMPATIBLE, DEPENDS = "order", "incompatible", "depends"


class ModDatabaseLike(Protocol):
    """
    The only thing `Context` needs of a mod database: look a key up.

    A Protocol rather than an import, so `rules` keeps no dependency on `moddb`
    and the layering contract in .importlinter stays true.
    """

    def get(self, *names: str) -> Any: ...
_SPEC = re.compile(r"^\s*(?P<mod>.+?)\s*\(\s*(?P<components>[^)]*)\s*\)\s*$")


@dataclass(frozen=True)
class ModSpec:
    mod: str                                   # normalised tp2 key
    display: str                               # as written in the rule
    components: Optional[FrozenSet] = None     # None = any component

    def __str__(self) -> str:
        if self.components is None:
            return self.display
        return f"{self.display}({','.join(str(c) for c in sorted(self.components))})"


@dataclass(frozen=True)
class Rule:
    kind: str
    left: ModSpec
    right: Tuple[ModSpec, ...]
    severity: str = "warning"
    direction: Optional[str] = None            # order only: before | after
    message: str = ""
    origin: str = "rules"
    optional: bool = False      # a soft/suggested dependency, not a requirement
    # Provenance, kept structured rather than flattened into `message`, because
    # a component-level report has to show WHY a claim is believed: krion64
    # records `source` (what was read) and `evidenceLevel` (mechanism-verified
    # vs speculative), and a speculative claim must not read like a verified one.
    evidence: str = ""
    source: str = ""
    workaround: str = ""
    raw_severity: str = ""      # the upstream's own word: hard / partial / soft


@dataclass
class Violation:
    kind: str
    severity: str
    summary: str
    detail: str = ""
    origin: str = ""
    mods: tuple = ()          # normalised keys the finding involves
    stale_risk: str = ""      # why this finding may no longer apply
    suppressed: str = ""      # why it was withheld
    rule: Optional["Rule"] = None      # the rule that fired, for drill-down
    left_components: tuple = ()        # installed components on the left side
    right_components: tuple = ()       # installed components on the right side
    log: str = ""                      # which install this was found in

    @property
    def blocking(self) -> bool:
        return self.severity == "error" and not (self.stale_risk or self.suppressed)


def parse_spec(text: str) -> Optional[ModSpec]:
    match = _SPEC.match(text)
    if not match:
        text = text.strip()
        return ModSpec(normalize_key(text), text) if text else None
    mod = match.group("mod").strip()
    raw = match.group("components").strip()
    if not mod:
        return None
    if raw in ("-", "*", ""):
        return ModSpec(normalize_key(mod), mod, None)
    numbers = {int(part) for part in re.findall(r"\d+", raw)}
    # An unparseable component list ("3183.4.1") is treated as "any", which can
    # only make the rule broader - never silently drop it.
    return ModSpec(normalize_key(mod), mod, frozenset(numbers) if numbers else None)


def parse_rule(entry: dict, kind: str, origin: str) -> Optional[Rule]:
    raw = (entry or {}).get("rule")
    if not isinstance(raw, str) or ":" not in raw:
        return None
    left_text, _, right_text = raw.partition(":")
    left = parse_spec(left_text)
    right = tuple(s for s in (parse_spec(p) for p in right_text.split("|")) if s)
    if not left or not right:
        return None
    # BWS-NG is a French project: `description` is usually French and an English
    # `translations.en_US` sits beside it. Preferring `description` produced a
    # report that explained conflicts in a language the operator may not read.
    translations = entry.get("translations") or {}
    message = (translations.get("en_US") or translations.get("en")
               or entry.get("description") or "")
    if not message and translations:
        message = next(iter(translations.values()), "")
    return Rule(kind=kind, left=left, right=right,
                severity=entry.get("severity") or "warning",
                direction=entry.get("direction"), message=message, origin=origin)


@dataclass(frozen=True)
class ComponentNote:
    """
    A known issue a catalogue records against a mod, not against a pair.

    krion64's `ki` entries hold things no pairwise rule can express: a global
    engine limit, a component that tanks performance, a namespace clash that
    only shows up in a log. 58 of them across 38 mods, 18 pinned to specific
    component numbers. They are advice, never a blocker.
    """
    mod: str
    display: str
    components: Optional[FrozenSet]
    severity: str
    summary: str
    workaround: str = ""
    evidence: str = ""
    forum: str = ""
    origin: str = ""


@dataclass
class RuleSet:
    rules: List[Rule] = field(default_factory=list)
    notes: List[ComponentNote] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    updated: Optional[str] = None          # newest mtime of the rule files
    age_days: Optional[int] = None
    undirected: int = 0                    # order-sensitive pairs with no direction
    _newest: Optional[float] = None

    def __len__(self) -> int:
        return len(self.rules)

    @classmethod
    def from_mapping(cls, payload, kind: str, origin: str) -> "RuleSet":
        entries = payload.get("rules", payload) if isinstance(payload, dict) else payload
        if not isinstance(entries, list):
            raise ConfigError(f"{origin}: expected a list of rules")
        out = cls()
        for entry in entries:
            rule = parse_rule(entry, kind, origin)
            if rule:
                out.rules.append(rule)
            else:
                out.warnings.append(f"{origin}: skipped unparseable rule {entry!r:.80}")
        return out

    @classmethod
    def load_file(cls, path: str, kind: Optional[str] = None) -> "RuleSet":
        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except OSError as exc:
            raise ConfigError(f"cannot read rules {path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path} is not valid JSON: {exc}") from exc

        origin = os.path.basename(path)
        if looks_like_krion(payload):
            rules, skipped, notes = _krion_rules(payload, origin)
            return cls(rules=rules, notes=notes, undirected=skipped)
        return cls.from_mapping(payload, kind or _kind_from_filename(path), origin)

    @classmethod
    def load(cls, paths: Sequence[str]) -> "RuleSet":
        """
        Load rule data, auto-detecting the shape.

        Two community formats are understood: rule-list files
        (BigWorldSetup-Next-Generation `data/rules/*.json`) and per-mod records
        with inline conflicts (krion64 `data/mods/*.json`).
        """
        combined = cls()
        for path in paths or ():
            targets = [path]
            if os.path.isdir(path):
                targets = [os.path.join(path, n) for n in sorted(os.listdir(path))
                           if n.lower().endswith(".json") and not n.startswith("_")]
            for target in targets:
                part = cls.load_file(target)
                combined.rules.extend(part.rules)
                combined.notes.extend(part.notes)
                combined.warnings.extend(part.warnings)
                combined.undirected += part.undirected
                try:
                    stamp = os.path.getmtime(target)
                except OSError:
                    continue
                if combined._newest is None or stamp > combined._newest:
                    combined._newest = stamp
        if combined._newest:
            import time
            combined.updated = time.strftime("%Y-%m-%d", time.gmtime(combined._newest))
            combined.age_days = int((time.time() - combined._newest) // 86400)
        return combined

    def add_metadata_order(self, folder: str, before, after,
                           origin: str = "mod ini") -> None:
        """Fold a mod's own Before/After lists into the rule set."""
        me = ModSpec(normalize_key(folder), folder, None)
        for other in before or ():
            self.rules.append(Rule(
                ORDER, me, (ModSpec(normalize_key(other), other, None),),
                severity="warning", direction="before",
                message=f"{folder}'s own metadata requires it before {other}",
                origin=origin))
        for other in after or ():
            self.rules.append(Rule(
                ORDER, me, (ModSpec(normalize_key(other), other, None),),
                severity="warning", direction="after",
                message=f"{folder}'s own metadata requires it after {other}",
                origin=origin))


# ---------------------------------------------------------------- krion64
# A second community data set (krion64.github.io) keeps one JSON per mod with
# `conflicts` and `dependencies` inline, using short field names: `t` is the tp2
# name, `n` the display name, `v` the version, `ord` the install-order category.
_KRION_CONFLICT_SEVERITY = {"hard": "error", "partial": "warning", "soft": "warning"}
_KRION_DEPENDENCY_SEVERITY = {"hard": "error", "soft": "warning"}
_COMPONENT_NUMBERS = re.compile(r"#(\d+)")


def _krion_spec(name, comps_text) -> Optional[ModSpec]:
    # Community JSON is not schema-checked upstream: a `with` field can be null,
    # a number, or a list. Anything that is not a usable name is not a rule.
    if not isinstance(name, str) or not name:
        return None
    numbers = {int(n) for n in _COMPONENT_NUMBERS.findall(comps_text or "")}
    return ModSpec(normalize_key(name), name, frozenset(numbers) if numbers else None)


# krion64 splits its pairwise claims in two. `conflicts` are things it stands
# behind; `advisories` are "these two touch the same thing, look at it". Reading
# only the first loses ~2,000 component-level observations; reading the second at
# the same weight would drown the real findings. They are loaded at note level.
_KRION_ADVISORY_SEVERITY = {"hard": "warning", "partial": "note", "soft": "note"}


def _krion_conflict_entries(record: dict):
    for entry in record.get("conflicts") or []:
        yield entry, _KRION_CONFLICT_SEVERITY, "warning"
    for entry in record.get("advisories") or []:
        yield entry, _KRION_ADVISORY_SEVERITY, "note"


_KRION_NOTE_SEVERITY = {"critical": "error", "error": "error",
                        "warning": "warning", "info": "note"}


def _krion_notes(record: dict, origin: str) -> List[ComponentNote]:
    me = record.get("t")
    if not isinstance(me, str) or not me:
        return []
    out = []
    for entry in record.get("ki") or []:
        if not isinstance(entry, dict):
            continue
        summary = entry.get("description") or ""
        if not summary:
            continue
        numbers = entry.get("components")
        components = (frozenset(int(n) for n in numbers)
                      if isinstance(numbers, list) and numbers else None)
        out.append(ComponentNote(
            mod=normalize_key(me), display=me, components=components,
            severity=_KRION_NOTE_SEVERITY.get(
                str(entry.get("severity") or ""), "warning"),
            summary=summary, workaround=entry.get("workaround") or "",
            evidence=entry.get("evidenceLevel") or "",
            forum=entry.get("forum") or "", origin=origin))
    return out


def _krion_rules(record: dict, origin: str) -> Tuple[List[Rule], int, List[ComponentNote]]:
    """Turn one krion64 mod record into rules. Returns (rules, skipped, notes)."""
    me = record.get("t")
    if not me:
        return [], 0, []
    out, skipped = [], 0

    for entry, severities, default_severity in _krion_conflict_entries(record):
        if not isinstance(entry, dict):
            continue
        left = _krion_spec(me, entry.get("myComps"))
        right = _krion_spec(entry.get("with"), entry.get("theirComps"))
        if not left or not right:
            continue
        severity = severities.get(str(entry.get("severity") or ""),
                                  default_severity)
        message = entry.get("reason") or ""
        evidence = entry.get("evidenceLevel") or ""
        provenance = {"evidence": str(evidence),
                      "source": str(entry.get("source") or ""),
                      "workaround": str(entry.get("workaround") or ""),
                      "raw_severity": str(entry.get("severity") or "")}
        if evidence:
            message = f"{message} [{evidence}]".strip()

        if entry.get("orderOnly"):
            direction = ("before" if entry.get("before") else
                         "after" if entry.get("after") else None)
            if not direction:
                # "these two are order-sensitive" without saying which way round
                # cannot be checked. Counting them beats inventing a direction.
                skipped += 1
                continue
            out.append(Rule(
                ORDER, left, (right,), severity="warning", direction=direction,
                message=message, origin=origin,
                evidence=provenance["evidence"], source=provenance["source"],
                workaround=provenance["workaround"],
                raw_severity=provenance["raw_severity"]))
        else:
            out.append(Rule(
                INCOMPATIBLE, left, (right,), severity=severity,
                message=message, origin=origin,
                evidence=provenance["evidence"], source=provenance["source"],
                workaround=provenance["workaround"],
                raw_severity=provenance["raw_severity"]))

    for entry in record.get("dependencies") or []:
        if not isinstance(entry, dict):
            continue
        left = _krion_spec(me, entry.get("myComps"))
        right = _krion_spec(entry.get("requires"), entry.get("requiresComps"))
        if not left or not right:
            continue
        soft = entry.get("type") != "hard"
        out.append(Rule(
            DEPENDS, left, (right,),
            severity=_KRION_DEPENDENCY_SEVERITY.get(
                str(entry.get("type") or ""), "warning"),
            message=entry.get("reason") or "", origin=origin, optional=soft))
    return out, skipped, _krion_notes(record, origin)


def looks_like_krion(payload) -> bool:
    return (isinstance(payload, dict) and "t" in payload
            and ("conflicts" in payload or "dependencies" in payload
                 or "ord" in payload))


def _kind_from_filename(path: str) -> str:
    name = os.path.basename(path).lower()
    if "incompat" in name:
        return INCOMPATIBLE
    if "depend" in name:
        return DEPENDS
    return ORDER


def _tp2_stem(tp2_file: str) -> str:
    """`SETUP-EEFIXPACK.TP2` -> `EEFIXPACK`; `EET_end.tp2` -> `EET_end`."""
    import os
    stem = os.path.splitext(os.path.basename(tp2_file.replace("\\", "/")))[0]
    return stem[6:] if stem.lower().startswith("setup-") else stem


# ----------------------------------------------------------------- the install
@dataclass
class Install:
    """
    What ONE WeiDU log says is installed, and in what order.

    One log is one game install. Two logs (an EET game and a BGEE game) are two
    separate installs: a mod in one neither conflicts with nor orders against a
    mod in the other, so they must never be merged before checking.
    """
    label: str = "WeiDU.log"
    components: Dict[str, set] = field(default_factory=dict)      # key -> {index}
    positions: Dict[str, Dict[int, int]] = field(default_factory=dict)  # key -> {comp: line}
    display: Dict[str, str] = field(default_factory=dict)         # key -> folder name
    labels: Dict[str, Dict[int, str]] = field(default_factory=dict)  # key -> {comp: name}

    @classmethod
    def from_log(cls, parsed, label: str = "WeiDU.log") -> "Install":
        install = cls(label=label)
        line = 0
        for key in parsed.order:
            mod = parsed.mods[key]
            folder_key = normalize_key(mod.folder)
            install.display.setdefault(folder_key, mod.folder)
            for component in mod.components:
                # Rules name a mod by its tp2, not by its folder, and the two
                # part company where one folder ships several tp2s: EET_end
                # lives in `eet\`, so keyed by folder alone every EET_end rule
                # silently matched nothing. Register both keys.
                keys = [folder_key]
                stem = normalize_key(_tp2_stem(component.tp2_file))
                if stem and stem != folder_key:
                    keys.append(stem)
                    install.display.setdefault(
                        stem, _tp2_stem(component.tp2_file))
                # The log already names every component the operator installed
                # ("// Allow Thieving in Heavy Armor"). That is a better source
                # than any catalogue: it is their install, not a description of
                # some version of the mod.
                label = (component.comment or "").split(" : ")[0].strip()
                for target in keys:
                    install.components.setdefault(target, set()).add(component.index)
                    install.positions.setdefault(target, {}).setdefault(
                        component.index, line)
                    if label:
                        install.labels.setdefault(target, {}).setdefault(
                            component.index, label)
                line += 1
        return install

    def matched(self, spec: ModSpec) -> Optional[set]:
        installed = self.components.get(spec.mod)
        if not installed:
            return None
        if spec.components is None:
            return set(installed)
        overlap = installed & set(spec.components)
        return overlap or None

    def position(self, spec: ModSpec, components: set) -> int:
        table = self.positions.get(spec.mod, {})
        return min((table[c] for c in components if c in table), default=0)

    def name(self, spec: ModSpec) -> str:
        return self.display.get(spec.mod, spec.display)

    def component_label(self, key: str, component: int) -> str:
        """What the log called this component, or '' if it did not say."""
        return self.labels.get(key, {}).get(component, "")


@dataclass
class Context:
    """
    What is known about the install beyond the log, used to judge whether a rule
    is still current.

    `installed_versions` comes from each mod's own .tp2; `baseline` is the mod
    database the rule set was built from. A rule carries no version qualifier,
    so this is the only way to notice that it predates what you have.
    """
    installed_versions: Dict[str, str] = field(default_factory=dict)
    baseline: Optional["ModDatabaseLike"] = None  # moddb.ModDatabase or None
    suppressions: List[dict] = field(default_factory=list)
    mods_with_own_ini: set = field(default_factory=set)
    include_optional: bool = False                # report soft dependencies too

    def baseline_version(self, key: str) -> Optional[str]:
        if self.baseline is None:
            return None
        record = self.baseline.get(key)
        return getattr(record, "version", None)

    def stale_note(self, keys) -> str:
        """A rule is suspect when a mod it names is newer than the rules' baseline."""
        notes = []
        for key in keys:
            installed = self.installed_versions.get(key)
            recorded = self.baseline_version(key)
            if installed and recorded and is_newer(installed, recorded):
                notes.append(f"{key} {installed} installed, rules written against "
                             f"{recorded}")
        if not notes:
            return ""
        return ("this rule may be out of date - " + "; ".join(notes)
                + ". Check the mod's changelog before acting on it.")

    def suppression(self, kind: str, keys) -> str:
        wanted = set(keys)
        for entry in self.suppressions:
            if entry.get("kind") and entry["kind"] != kind:
                continue
            mods = {normalize_key(m) for m in entry.get("mods", [])}
            if mods and mods != wanted:
                continue
            versions = entry.get("verified_version") or {}
            for mod, minimum in versions.items():
                have = self.installed_versions.get(normalize_key(mod))
                if not have or is_newer(have, minimum) is False:
                    break                        # not yet on the fixed version
            else:
                reason = entry.get("reason") or "suppressed by your overrides file"
                when = entry.get("verified_on")
                return f"{reason}" + (f" (verified {when})" if when else "")
        return ""


def load_suppressions(path: Optional[str]) -> List[dict]:
    """User-recorded 'this rule no longer applies' decisions."""
    if not path:
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except OSError as exc:
        raise ConfigError(f"cannot read suppressions {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    entries = raw.get("suppressions", raw) if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise ConfigError(f"{path}: expected a list of suppressions")
    return [e for e in entries if isinstance(e, dict)]


def check_all(installs: Sequence[Install], ruleset: RuleSet,
              context: Optional[Context] = None) -> List[Violation]:
    """Check each install separately and label findings by the log they came from."""
    out = []
    multiple = len(installs) > 1
    for install in installs:
        for violation in check(install, ruleset, context):
            if multiple:
                violation.origin = f"{install.label} / {violation.origin}"
                violation.summary = f"[{install.label}] {violation.summary}"
            out.append(violation)
    return _dedupe(out)


def check(install: Install, ruleset: RuleSet,
          context: Optional[Context] = None) -> List[Violation]:
    """Evaluate every rule against the install. Reports; never changes anything."""
    context = context or Context()
    violations: List[Violation] = []
    for rule in _applicable(ruleset, context):
        left_hit = install.matched(rule.left)
        if left_hit is None:
            continue
        for right in rule.right:
            right_hit = install.matched(right)

            if rule.kind == DEPENDS:
                continue                    # handled below, across alternatives
            if right_hit is None:
                continue

            if rule.kind == INCOMPATIBLE:
                if rule.left.mod == right.mod:
                    summary = (f"{install.name(rule.left)} has components that "
                               f"conflict with each other")
                else:
                    summary = (f"{install.name(rule.left)} and "
                               f"{install.name(right)} are incompatible")
                violations.append(Violation(
                    INCOMPATIBLE, rule.severity, summary,
                    _pair_detail(install, rule.left, left_hit, right, right_hit,
                                 rule.message),
                    rule.origin, mods=(rule.left.mod, right.mod), rule=rule,
                    left_components=tuple(sorted(left_hit)),
                    right_components=tuple(sorted(right_hit)),
                    log=install.label))
            elif rule.kind == ORDER and rule.direction:
                left_at = install.position(rule.left, left_hit)
                right_at = install.position(right, right_hit)
                wrong = (left_at > right_at if rule.direction == "before"
                         else left_at < right_at)
                if wrong:
                    first, second = ((rule.left, right) if rule.direction == "before"
                                     else (right, rule.left))
                    violations.append(Violation(
                        ORDER, rule.severity,
                        f"{install.name(first)} should be installed before "
                        f"{install.name(second)}",
                        _order_detail(install, rule, left_at, right_at, right),
                        rule.origin, mods=(rule.left.mod, right.mod), rule=rule,
                        left_components=tuple(sorted(left_hit)),
                        right_components=tuple(sorted(right_hit)),
                        log=install.label))

        if rule.kind == DEPENDS:
            if rule.optional and not context.include_optional:
                # "Alternate portraits for X" is an enhancement, not a
                # requirement. Reporting 11 of those buries the one real
                # missing prerequisite.
                continue
            if not any(install.matched(right) for right in rule.right):
                wanted = " or ".join(str(r) for r in rule.right)
                phrase = ("can also integrate with" if rule.optional else "needs")
                violations.append(Violation(
                    DEPENDS, rule.severity,
                    f"{install.name(rule.left)} {phrase} {wanted}, "
                    f"which is not installed",
                    rule.message, rule.origin, mods=(rule.left.mod,), rule=rule,
                    left_components=tuple(sorted(left_hit)),
                    log=install.label))
    for violation in violations:
        violation.stale_risk = context.stale_note(violation.mods)
        violation.suppressed = context.suppression(violation.kind, violation.mods)
    return _dedupe(violations)


def _applicable(ruleset: RuleSet, context: Context) -> List[Rule]:
    """
    Drop community ordering rules for mods that ship their own.

    A mod's `[Metadata]` ini travels with the version you downloaded, so it
    cannot be stale about itself. When a developer fixes an ordering problem and
    updates the ini, that correction arrives with the next download - which is
    the only self-updating channel available here.
    """
    if not context.mods_with_own_ini:
        return ruleset.rules
    return [rule for rule in ruleset.rules
            if not (rule.kind == ORDER
                    and rule.origin != "mod ini"
                    and rule.left.mod in context.mods_with_own_ini)]


def _pair_detail(install, left, left_hit, right, right_hit, message):
    parts = [f"installed: {install.name(left)} "
             f"#{sorted(left_hit)[:6]} and {install.name(right)} #{sorted(right_hit)[:6]}"]
    if message:
        parts.append(message)
    return " - ".join(parts)


def _order_detail(install, rule, left_at, right_at, right):
    order = (f"{install.name(rule.left)} is at position {left_at}, "
             f"{install.name(right)} at {right_at}")
    return f"{order} - {rule.message}" if rule.message else order


def _dedupe(violations: List[Violation]) -> List[Violation]:
    seen, out = set(), []
    rank = {"error": 0, "warning": 1}
    for violation in violations:
        key = (violation.kind, violation.summary)
        if key in seen:
            continue
        seen.add(key)
        out.append(violation)
    out.sort(key=lambda v: (rank.get(v.severity, 2), v.kind, v.summary))
    return out
