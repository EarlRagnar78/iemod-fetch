"""
Whole-install order planning.

Answers the question "is my install in the right order, and if not, what order
*would* be right?" by re-sorting the components already named in the WeiDU logs
and writing a fresh, rule-compliant pair of logs.

Three things this deliberately does NOT do, because each would be a guess:

* It never invents, drops or edits a component. The plan contains exactly the
  components the input logs contain, spelled exactly as they were spelled.
* It never resolves a hard incompatibility. Reordering cannot fix "these two
  mods must not coexist"; only removing one can, and which one to lose is the
  operator's decision, not the tool's.
* It never moves a mod between the pre-EET and the EET log on its own. That
  changes which game the mod is installed onto - a different install, not a
  reordering. It is reported, and only acted on with `reassign_phase=True`.

A rewritten log is an INSTALL PLAN for a fresh install, consumable by
mod_installer / Project Infinity. It is not a repair applied to a game that is
already installed: WeiDU installs in file order, so changing the order after the
fact requires reinstalling.
"""
import glob
import heapq
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .errors import ConfigError
from .naming import normalize_key
from .rules import Install, RuleSet, check_all

# The two logs an EET install is described by.
EET_LOG = "WeiDU.log"
PRE_EET_LOG = "WeiDU-BGEE.log"

# The one category that means "this installs on BG1:EE, before the merge".
PRE_EET_CATEGORY = "PRE EET BGEE MODS"

HEADER = (
    "// Log of Currently Installed WeiDU Mods\n"
    "// The top of the file is the 'oldest' mod\n"
    "// Format: ~TP2_Path~ #lang #comp // Name : Version\n"
)


def tp2_key(tp2_file: str) -> str:
    """
    The orderable identity of a tp2.

    A mod folder is not enough: EET ships `eet\\EET.TP2` and `eet\\EET_end\\
    EET_end.tp2` in the same folder, and those two are the first and the last
    thing installed. The tp2 stem, with WeiDU's `setup-` prefix removed, is what
    catalogues and rules actually name.
    """
    stem = os.path.splitext(os.path.basename(tp2_file.replace("\\", "/")))[0]
    if stem.lower().startswith("setup-"):
        stem = stem[6:]
    return normalize_key(stem)


# --------------------------------------------------------------- the catalogue
@dataclass(frozen=True)
class Slot:
    """Where a catalogue says a mod belongs."""
    category: str
    rank: int          # index of the category in the catalogue's own order
    ord: int           # position within that category
    pre_eet: bool


@dataclass
class OrderIndex:
    """
    Install-order positions, read from a krion64-shaped data directory.

    `data/categories.json` gives the phase order (its key order IS the order);
    each `data/mods/*.json` gives one mod's category (`c`) and its position
    inside it (`ord`), plus the WeiDU folders (`co[].wf`) it installs as.
    """
    slots: Dict[str, Slot] = field(default_factory=dict)
    categories: List[str] = field(default_factory=list)
    origin: str = ""
    warnings: List[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.slots)

    def get(self, key: str) -> Optional[Slot]:
        return self.slots.get(key)

    @classmethod
    def load(cls, path: str) -> "OrderIndex":
        """Load from a krion64 `data/` directory (or its repository root)."""
        root = path
        if not os.path.isfile(os.path.join(root, "categories.json")):
            if os.path.isfile(os.path.join(root, "data", "categories.json")):
                root = os.path.join(root, "data")
            else:
                raise ConfigError(
                    f"{path}: no categories.json here or in a data/ subdirectory; "
                    "point --order-catalogue at a krion64 data directory")

        index = cls(origin=path)
        with open(os.path.join(root, "categories.json"), "r",
                  encoding="utf-8") as fh:
            payload = json.load(fh)
        categories = payload.get("categories")
        if not isinstance(categories, dict) or not categories:
            raise ConfigError(f"{path}: categories.json has no 'categories' map")
        index.categories = list(categories)
        rank_of = {name: i for i, name in enumerate(index.categories)}

        loaded = []
        for file in sorted(glob.glob(os.path.join(root, "mods", "*.json"))):
            try:
                with open(file, "r", encoding="utf-8") as fh:
                    record = json.load(fh)
            except (OSError, ValueError) as exc:
                index.warnings.append(f"{file}: unreadable ({exc})")
                continue
            parsed = index._slot_for(record, rank_of, file)
            if parsed:
                loaded.append(parsed)

        # Two passes, and the order matters. A tp2 name is a mod's own identity;
        # a folder is only where it happens to live, and mods DO share folders -
        # EET_end ships inside EET's `eet\` directory. Registering identities
        # first stops EET_end's "EET FINALIZATION" slot from claiming `eet` and
        # sending the EET core to the end of the install.
        for slot, identities, _folders in loaded:
            for name in identities:
                index.slots.setdefault(tp2_key(name), slot)
        for slot, _identities, folders in loaded:
            for name in folders:
                index.slots.setdefault(tp2_key(name), slot)
        return index

    def _slot_for(self, record, rank_of: Dict[str, int], file: str):
        """(slot, tp2 identities, folder names) for one catalogue record."""
        if not isinstance(record, dict):
            return None
        category = record.get("c")
        if category not in rank_of:
            if category:
                self.warnings.append(
                    f"{os.path.basename(file)}: unknown category {category!r}")
            return None
        slot = Slot(category=category, rank=rank_of[category],
                    ord=int(record.get("ord") or 0),
                    pre_eet=(category == PRE_EET_CATEGORY))

        identities, folders = set(), set()
        if isinstance(record.get("t"), str):
            identities.add(record["t"])
        for component in record.get("co") or ():
            if not isinstance(component, dict):
                continue
            if isinstance(component.get("wp"), str):
                identities.add(os.path.splitext(
                    os.path.basename(component["wp"].replace("\\", "/")))[0])
            if isinstance(component.get("wf"), str):
                folders.add(component["wf"])
        return slot, identities, folders - identities


# ------------------------------------------------------------------- the units
@dataclass
class Unit:
    """One tp2 from the logs, with every component of it that was installed."""
    key: str
    tp2_file: str
    folder: str
    source_log: str
    seq: int                                  # earliest log line, true input order
    lines: List[Tuple[str, int, int, str]] = field(default_factory=list)
    slot: Optional[Slot] = None
    target_log: str = ""

    @property
    def display(self) -> str:
        """
        How this unit is named in reports.

        The folder alone is ambiguous - `eet` holds both EET and EET_end - so
        the tp2 stem is appended whenever it differs from the folder.
        """
        stem = os.path.splitext(self.tp2_file)[0]
        if stem.lower().startswith("setup-"):
            stem = stem[6:]
        if normalize_key(stem) == normalize_key(self.folder):
            return self.folder
        return f"{self.folder}/{stem}"

    def render(self) -> List[str]:
        out = []
        for path, lang, comp, comment in self.lines:
            line = f"~{path}~ #{lang} #{comp}"
            if comment:
                line += f" // {comment}"
            out.append(line)
        return out


def collect_units(specs: Sequence[Tuple[str, str]]) -> Tuple[List[Unit], List[str]]:
    """
    Read the logs into orderable units.

    `specs` is a sequence of (path, log_role) pairs where log_role is
    `WeiDU.log` or `WeiDU-BGEE.log`. Units are keyed per (log, tp2): a mod
    legitimately installed on both games appears twice, and stays twice.
    """
    from .weidu import parse_weidu_log

    units: Dict[Tuple[str, str], Unit] = {}
    warnings: List[str] = []
    offset = 0
    for path, role in specs:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            parsed = parse_weidu_log(fh.read(), source=str(path))
        warnings.extend(parsed.warnings)
        highest = 0
        for key in parsed.order:
            mod = parsed.mods[key]
            for component in mod.components:
                # The log line, not the order the parser happened to group
                # folders in: EET_end lives inside EET's folder but installs
                # last, and grouping by folder would report it as install #4.
                seq = offset + component.line
                highest = max(highest, component.line)
                unit_key = (role, tp2_key(component.tp2_file))
                unit = units.get(unit_key)
                if unit is None:
                    unit = Unit(key=unit_key[1], tp2_file=component.tp2_file,
                                folder=mod.folder, source_log=role, seq=seq)
                    units[unit_key] = unit
                unit.seq = min(unit.seq, seq)
                unit.lines.append((component.path or
                                   f"{mod.folder}\\{component.tp2_file}",
                                   component.language, component.index,
                                   component.comment))
        offset += highest
    return sorted(units.values(), key=lambda u: u.seq), warnings


# -------------------------------------------------------------------- the plan
@dataclass
class Move:
    key: str
    display: str
    frm: str
    to: str
    reason: str


@dataclass
class OrderPlan:
    logs: Dict[str, List[Unit]] = field(default_factory=dict)
    moved: List[Move] = field(default_factory=list)        # reordered within a log
    phase_notes: List[Move] = field(default_factory=list)  # wrong log
    cycles: List[List[str]] = field(default_factory=list)
    unranked: List[str] = field(default_factory=list)
    blockers: List = field(default_factory=list)           # rules.Violation
    residual: List = field(default_factory=list)           # rules.Violation
    warnings: List[str] = field(default_factory=list)
    edges: int = 0

    @property
    def compliant(self) -> bool:
        """True when the *input* already satisfied everything checkable."""
        return not (self.moved or self.cycles or self.blockers or
                    self.phase_notes)

    @property
    def verified(self) -> bool:
        """True when the *output* satisfies every order rule that was checked."""
        return not self.residual

    def render(self, role: str) -> str:
        lines = [HEADER.rstrip("\n"),
                 "// Ordered by iemod-fetch against install-order rules"]
        for unit in self.logs.get(role, ()):
            lines.extend(unit.render())
        return "\n".join(lines) + "\n"

    def write(self, directory: str) -> List[str]:
        os.makedirs(directory, exist_ok=True)
        written = []
        for role in self.logs:
            path = os.path.join(directory, role)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(self.render(role))
            written.append(path)
        return written


def _edges(units: List[Unit], ruleset: RuleSet,
           include_optional: bool) -> Tuple[Dict[str, Set[str]], int]:
    """
    Hard ordering constraints: `after -> before` pairs, per log.

    Only rules whose BOTH sides are present in the SAME log produce an edge. A
    mod in the pre-EET log does not order against a mod in the EET log; they are
    two different installs.
    """
    by_log: Dict[str, Dict[str, Unit]] = {}
    for unit in units:
        by_log.setdefault(unit.target_log, {})[unit.key] = unit

    edges: Dict[str, Set[str]] = {}
    count = 0
    for rule in ruleset.rules:
        # ONLY explicit order rules become edges. A dependency says "this mod
        # needs that mod present", which is not the same claim as "install it
        # later": BWS-NG records both `EET: EET_end` and `EET_end: EET`, and
        # reading either as an ordering constraint invents a cycle and pushes
        # the EET core to the end of the install. Dependencies are checked by
        # rules.check(), where they belong.
        if rule.kind != "order":
            continue
        if rule.optional and not include_optional:
            continue
        direction = rule.direction
        if direction not in ("before", "after"):
            continue

        for members in by_log.values():
            left = members.get(rule.left.mod)
            if left is None:
                continue
            for spec in rule.right:
                right = members.get(spec.mod)
                if right is None or right.key == left.key:
                    continue
                if direction == "before":
                    first, second = left.key, right.key
                else:
                    first, second = right.key, left.key
                if second not in edges:
                    edges[second] = set()
                if first not in edges[second]:
                    edges[second].add(first)
                    count += 1
    return edges, count


def _priorities(units: List[Unit]) -> Dict[str, Tuple[int, int, int]]:
    """
    The order the catalogue wants, as a sort key per unit.

    A unit the catalogue does not know inherits the position of the last known
    unit that preceded it in the ORIGINAL log, so it stays where the operator
    put it instead of being swept to the end. Its own sequence number breaks the
    tie, preserving the input order among unknowns.
    """
    priorities: Dict[str, Tuple[int, int, int]] = {}
    inherited: Dict[str, Tuple[int, int]] = {}
    for unit in units:
        if unit.slot is not None:
            base = (unit.slot.rank, unit.slot.ord)
            inherited[unit.target_log] = base
        else:
            base = inherited.get(unit.target_log, (-1, -1))
        priorities[unit.key] = (base[0], base[1], unit.seq)
    return priorities


def _toposort(units: List[Unit], edges: Dict[str, Set[str]],
              priorities) -> Tuple[List[Unit], List[List[str]]]:
    """
    Kahn's algorithm, ties broken by catalogue priority.

    Rules are hard constraints; the catalogue position is only the preference
    used to choose among the units that are ready at the same moment. That is
    what makes the result "as close to the reference order as the rules allow"
    rather than "the reference order, rules permitting".

    A cycle is never fatal: the lowest-priority member is released and the cycle
    is reported, so the operator always gets a complete plan plus the exact list
    of rules that contradict each other.
    """
    members = {u.key: u for u in units}
    pending = {k: {d for d in edges.get(k, ()) if d in members} for k in members}
    dependents: Dict[str, Set[str]] = {k: set() for k in members}
    for key, deps in pending.items():
        for dep in deps:
            dependents[dep].add(key)

    ready = [(priorities[k], k) for k, deps in pending.items() if not deps]
    heapq.heapify(ready)
    emitted: List[Unit] = []
    cycles: List[List[str]] = []
    left = set(members)

    while left:
        if not ready:
            stuck = sorted(left, key=lambda k: priorities[k])
            cycles.append(stuck if len(stuck) <= 12 else stuck[:12] + ["..."])
            forced = stuck[0]
            pending[forced] = set()
            heapq.heappush(ready, (priorities[forced], forced))
            continue
        _, key = heapq.heappop(ready)
        if key not in left:
            continue
        left.discard(key)
        emitted.append(members[key])
        for dependent in sorted(dependents[key]):
            pending[dependent].discard(key)
            if not pending[dependent] and dependent in left:
                heapq.heappush(ready, (priorities[dependent], dependent))
    return emitted, cycles


def _minimum_moves(before: List[str], after: List[str]) -> List[Tuple[str, int, int]]:
    """
    The smallest set of units that has to move to get from `before` to `after`.

    Naively comparing indexes overstates the damage wildly: moving one mod to
    the front shifts every other index by one and reports 146 mods "moved" when
    one moved. Everything on a longest common subsequence of the two orders can
    stay where it is; only the rest genuinely moved, and that count is the
    honest answer to "how far out is my install?".
    """
    n, m = len(before), len(after)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        row, nxt = table[i], table[i + 1]
        for j in range(m - 1, -1, -1):
            row[j] = nxt[j + 1] + 1 if before[i] == after[j] else max(nxt[j], row[j + 1])
    keep = set()
    i = j = 0
    while i < n and j < m:
        if before[i] == after[j]:
            keep.add(before[i])
            i += 1
            j += 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1
    positions = {key: idx for idx, key in enumerate(before)}
    return [(key, positions[key], idx)
            for idx, key in enumerate(after)
            if key not in keep and positions[key] != idx]


def plan_order(specs: Sequence[Tuple[str, str]], index: OrderIndex,
               ruleset: Optional[RuleSet] = None, context=None,
               include_optional: bool = False,
               reassign_phase: bool = False) -> OrderPlan:
    """
    Build a rule-compliant install order for the components in `specs`.

    `specs` pairs each input log with the role it plays: `WeiDU.log` for the
    EET (merged-game) install, `WeiDU-BGEE.log` for the pre-EET BG1 phase.
    """
    ruleset = ruleset or RuleSet()
    units, warnings = collect_units(specs)
    plan = OrderPlan(warnings=warnings)

    for unit in units:
        unit.slot = index.get(unit.key)
        unit.target_log = unit.source_log
        if unit.slot is None:
            plan.unranked.append(unit.display)

    # Phase disagreements are reported; acting on one restructures the install.
    present = {(u.target_log, u.key) for u in units}
    for unit in units:
        if unit.slot is None:
            continue
        wanted = PRE_EET_LOG if unit.slot.pre_eet else EET_LOG
        if wanted == unit.source_log or (wanted, unit.key) in present:
            continue
        note = Move(unit.key, unit.display, unit.source_log, wanted,
                    f"catalogue category {unit.slot.category!r}")
        plan.phase_notes.append(note)
        if reassign_phase:
            unit.target_log = wanted

    edges, plan.edges = _edges(units, ruleset, include_optional)
    priorities = _priorities(units)

    for role in (PRE_EET_LOG, EET_LOG):
        subset = [u for u in units if u.target_log == role]
        if not subset:
            continue
        ordered, cycles = _toposort(subset, edges, priorities)
        plan.logs[role] = ordered
        plan.cycles.extend(cycles)
        names = {u.key: u.display for u in ordered}
        for key, old, new in _minimum_moves([u.key for u in subset],
                                            [u.key for u in ordered]):
            plan.moved.append(Move(key, names[key], str(old), str(new), role))

    findings = _verify(plan, ruleset, context)
    plan.blockers = [v for v in findings if v.kind != "order"]
    plan.residual = [v for v in findings if v.kind == "order"]
    return plan


def _as_install(units: List[Unit], label: str) -> Install:
    """Present the planned order to the checker exactly as a log would be."""
    install = Install(label=label)
    line = 0
    for unit in units:
        for path, _lang, component, _comment in unit.lines:
            folder = normalize_key(path.replace("\\", "/").split("/")[0])
            for key in dict.fromkeys((folder, unit.key)):
                install.display.setdefault(key, unit.display)
                install.components.setdefault(key, set()).add(component)
                install.positions.setdefault(key, {}).setdefault(component, line)
            line += 1
    return install


def _verify(plan: OrderPlan, ruleset: RuleSet, context) -> List:
    """
    Check the PLAN, not the input.

    Emitting a file called "rule-compliant" without checking it against the same
    rules would be a claim, not a result. Two kinds of finding can survive:

    * order findings - a bug or a contradiction in the rules; the plan is not
      compliant and says so rather than pretending.
    * everything else, chiefly incompatibilities - "these two must not coexist".
      Reordering does not change which mods are present, so no ordering can fix
      one. Which mod to lose is the operator's decision, not the tool's.
    """
    from .rules import Context
    installs = [_as_install(units, role) for role, units in plan.logs.items()]
    return [v for v in check_all(installs, ruleset, context or Context())
            if v.blocking or v.kind == "order"]


def render_plan_summary(plan: OrderPlan, directory: str, stream) -> None:
    """Print what the plan changed, and what it could not."""
    print(file=stream)
    print("INSTALL ORDER PLAN", file=stream)
    for role, units in plan.logs.items():
        print(f"  {role:<16} {len(units):>4} mods, "
              f"{sum(len(u.lines) for u in units):>4} components", file=stream)
    print(f"  written to       {os.path.abspath(directory)}", file=stream)
    print("  a plan for a FRESH install (mod_installer / Project Infinity);",
          file=stream)
    print("  WeiDU installs in file order, so an installed game needs reinstalling.",
          file=stream)

    if plan.compliant:
        print("  your current order already satisfies every rule checked.",
              file=stream)
    if plan.verified:
        print(f"  VERIFIED: the planned order satisfies every order rule checked "
              f"({plan.edges} constraint(s)).", file=stream)
    else:
        print(f"\n  NOT COMPLIANT: {len(plan.residual)} order rule(s) the plan "
              f"could not satisfy — the rules contradict each other:", file=stream)
        for violation in plan.residual:
            print(f"    {violation.summary}", file=stream)

    if plan.moved:
        print(f"\n  out of place ({len(plan.moved)}):", file=stream)
        for move in plan.moved:
            print(f"    {move.display:<32} {move.frm:>4} -> {move.to:<4} "
                  f"({move.reason})", file=stream)

    if plan.phase_notes:
        print(f"\n  wrong install phase ({len(plan.phase_notes)}) — NOT moved; "
              f"pass --reassign-phase to act:", file=stream)
        for move in plan.phase_notes:
            print(f"    {move.display:<32} {move.frm} -> {move.to}  {move.reason}",
                  file=stream)

    if plan.cycles:
        print(f"\n  contradictory rules ({len(plan.cycles)}) — the plan breaks the "
              f"cycle at its first member, verify by hand:", file=stream)
        for cycle in plan.cycles:
            print(f"    {' -> '.join(cycle)}", file=stream)

    if plan.blockers:
        incompatible = [v for v in plan.blockers if v.kind != "depends"]
        missing = [v for v in plan.blockers if v.kind == "depends"]
        if incompatible:
            print(f"\n  reordering CANNOT fix these ({len(incompatible)}) — the mods "
                  f"must not coexist; drop one side:", file=stream)
            for violation in incompatible:
                print(f"    {violation.summary}", file=stream)
        if missing:
            print(f"\n  missing prerequisites ({len(missing)}) — nothing to reorder, "
                  f"the mod is simply absent:", file=stream)
            for violation in missing:
                print(f"    {violation.summary}", file=stream)

    if plan.unranked:
        shown = ", ".join(plan.unranked[:8])
        more = f" (+{len(plan.unranked) - 8} more)" if len(plan.unranked) > 8 else ""
        print(f"\n  not in the catalogue ({len(plan.unranked)}) — left where you "
              f"put them: {shown}{more}", file=stream)
