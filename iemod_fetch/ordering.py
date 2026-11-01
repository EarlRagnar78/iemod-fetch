"""
Whole-install order planning.

Answers the question "is my install in the right order, and if not, what order
*would* be right?" by re-sorting the components already named in the WeiDU logs
and writing a fresh, rule-compliant pair of logs.

Three things this deliberately does NOT do, because each would be a guess:

* It never invents, drops or edits a component. The plan contains exactly the
  components the input logs contain, spelled exactly as they were spelled.
* It never resolves a hard incompatibility. Reordering cannot fix "these two
  mods must not coexist"; only removing one can. Where the rule itself pins the
  side to remove, `resolution.resolve_conflicts` can do it on request
  (ADR-0021); otherwise which one to lose is the operator's decision.
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
from collections.abc import Iterable, Mapping, Sequence

from .errors import ConfigError
from .kinds import KindHint, place
from .naming import normalize_key
from .rules import SORTING_ORDER, Install, RuleSet, check_all

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


def name_key(name: str) -> str:
    """
    tp2_key for a name that may lack `.tp2`: a catalogue title or a folder.
    tp2_key strips one extension, which for "www.urstuff2athkatla" would be
    ".urstuff2athkatla"; the name is taken as a tp2 name first.
    """
    return tp2_key(name if name.lower().endswith(".tp2") else name + ".tp2")


# --------------------------------------------------------------- the catalogue
@dataclass(frozen=True)
class Slot:
    """Where a catalogue says a mod belongs."""
    category: str
    rank: int          # index of the category in the catalogue's own order
    ord: int           # position within that category
    pre_eet: bool
    # > 0: right after the mod at (rank, ord), in this order - BWS-NG's
    # sequence carried onto krion64's (ADR-0041 decision 2a)
    after: int = 0


@dataclass
class OrderIndex:
    """
    Install-order positions, read from a krion64-shaped data directory.

    `data/categories.json` gives the phase order (its key order IS the order);
    each `data/mods/*.json` gives one mod's category (`c`) and its position
    inside it (`ord`), plus the WeiDU folders (`co[].wf`) it installs as.
    """
    slots: dict[str, Slot] = field(default_factory=dict)
    # krion64 places single components elsewhere than their mod: stratagems
    # #1500 in SPELL MODS, #4100 in POST EET (`co[].cn` + `co[].cat`).
    component_slots: dict[tuple[str, int], Slot] = field(default_factory=dict)
    categories: list[str] = field(default_factory=list)
    origin: str = ""
    warnings: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.slots)

    def get(self, key: str) -> Slot | None:
        return self.slots.get(key)

    def component(self, key: str, number: int) -> Slot | None:
        """Where one component belongs, when the catalogue places it apart."""
        return self.component_slots.get((key, number))

    @classmethod
    def load(cls, path: str) -> OrderIndex:
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
        with open(os.path.join(root, "categories.json"),
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
                with open(file, encoding="utf-8") as fh:
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
        for slot, identities, _folders, _parts in loaded:
            for name in identities:
                index.slots.setdefault(name_key(name), slot)
        for slot, _identities, folders, _parts in loaded:
            for name in folders:
                index.slots.setdefault(name_key(name), slot)
        for _slot, identities, folders, parts in loaded:
            for name in list(identities) + list(folders):
                for number, part in parts.items():
                    index.component_slots.setdefault((name_key(name), number), part)
        return index

    def _slot_for(self, record, rank_of: dict[str, int], file: str):
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
        parts: dict[int, Slot] = {}
        if isinstance(record.get("t"), str):
            identities.add(record["t"])
        for component in record.get("co") or ():
            if not isinstance(component, dict):
                continue
            moved_to = component.get("cat")
            number = component.get("cn")
            if (moved_to in rank_of and moved_to != category
                    and isinstance(number, int) and not isinstance(number, bool)):
                # krion64's own export orders a moved component by its new
                # category and the MOD's `ord`; the component `ord` it does not
                # read, so neither does this.
                parts[number] = Slot(category=moved_to, rank=rank_of[moved_to],
                                     ord=slot.ord, pre_eet=False)
            if isinstance(component.get("wp"), str):
                # the file name whole: tp2_key strips `.tp2` once, so a stem with
                # its own dots (www.urstuff2athkatla.tp2) keeps them
                identities.add(os.path.basename(component["wp"].replace("\\", "/")))
            if isinstance(component.get("wf"), str):
                folders.add(component["wf"])
        stems = {os.path.splitext(name)[0] for name in identities}
        return slot, identities, folders - identities - stems, parts


# ------------------------------------------------------------------- the units
@dataclass
class Unit:
    """One tp2 from the logs, with every component of it that was installed."""
    key: str
    tp2_file: str
    folder: str
    source_log: str
    seq: int                                  # earliest log line, true input order
    lines: list[tuple[str, int, int, str]] = field(default_factory=list)
    slot: Slot | None = None
    target_log: str = ""
    part: int = 0              # > 0 once a mod is split across the order
    split: bool = False        # whether this mod was split at all
    parts: int = 1             # how many parts the mod was split into
    placed_by: str = ""        # why BWS-NG's sequence or its kind placed it
    placed_from: str = ""      # "BWS-NG" or "kind", where one did
    no_place: str = ""         # why its kind could not, where it was asked

    @property
    def node(self) -> str:
        """Unique id in the ordering graph: one mod, one log, one part."""
        return f"{self.target_log}|{self.key}|{self.part}"

    @property
    def display(self) -> str:
        """
        How this unit is named in reports.

        The folder alone is ambiguous - `eet` holds both EET and EET_end - so
        the tp2 stem is appended whenever it differs from the folder. A split
        mod names the part: `stratagems #4100`, `cdtweaks (part 2/3)`.
        """
        base = self.mod_display
        if not self.split:
            return base
        numbers = [comp for _path, _lang, comp, _comment in self.lines]
        if len(numbers) == 1:
            return f"{base} #{numbers[0]}"
        return f"{base} (part {self.part + 1}/{self.parts})"

    @property
    def mod_display(self) -> str:
        """The mod's own name, whichever part this is."""
        stem = os.path.splitext(self.tp2_file)[0]
        if stem.lower().startswith("setup-"):
            stem = stem[6:]
        if normalize_key(stem) == normalize_key(self.folder):
            return self.folder
        return f"{self.folder}/{stem}"

    def render(self) -> list[str]:
        out = []
        for path, lang, comp, comment in self.lines:
            line = f"~{path}~ #{lang} #{comp}"
            if comment:
                line += f" // {comment}"
            out.append(line)
        return out


def collect_units(specs: Sequence[tuple[str, str]]) -> tuple[list[Unit], list[str]]:
    """
    Read the logs into orderable units.

    `specs` is a sequence of (path, log_role) pairs where log_role is
    `WeiDU.log` or `WeiDU-BGEE.log`. Units are keyed per (log, tp2): a mod
    legitimately installed on both games appears twice, and stays twice.
    """
    from .weidu import parse_weidu_log

    units: dict[tuple[str, str], Unit] = {}
    warnings: list[str] = []
    offset = 0
    for path, role in specs:
        with open(path, encoding="utf-8", errors="replace") as fh:
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
    logs: dict[str, list[Unit]] = field(default_factory=dict)
    moved: list[Move] = field(default_factory=list)        # reordered within a log
    phase_notes: list[Move] = field(default_factory=list)  # wrong log
    cycles: list[list[str]] = field(default_factory=list)
    unranked: list[str] = field(default_factory=list)
    # ADR-0041 decision 2: what its kind placed, and why the rest has no place
    by_kind: list[tuple[str, str, str]] = field(default_factory=list)  # name, category, why
    by_sequence: list[tuple[str, str, str]] = field(default_factory=list)  # name, category, why
    sorting_order: bool = False   # the player's own order applies, over every place
    no_place: list[tuple[str, str, str]] = field(default_factory=list)  # log, name, why not
    blockers: list = field(default_factory=list)           # rules.Violation
    residual: list = field(default_factory=list)           # rules.Violation
    warnings: list[str] = field(default_factory=list)
    edges: int = 0
    # Units (`Unit.node`) a rule ties to another: where the rules, not the
    # catalogue's category, decide their place.
    constrained: set[str] = field(default_factory=set)
    # Those rules' edges, unit -> the units they put before it: what the page
    # re-checks at once after a drop (M5b item 31).
    rule_edges: dict[str, set[str]] = field(default_factory=dict)
    # the rules behind each of those edges, by (unit, the unit it must follow)
    edge_rules: dict[tuple[str, str], list] = field(default_factory=dict)
    simulation: object | None = None    # simulate.SimulationResult, if run
    game_report: object | None = None   # gamedir.GameReport, if folders given
    resolution: object | None = None    # resolution.ResolutionResult, if any

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

    def installs(self) -> list[Install]:
        """The planned order, as the checker and the conflict report see a log."""
        return [_as_install(units, role) for role, units in self.logs.items()]

    def reverify(self, ruleset: RuleSet, context=None) -> None:
        """Re-check the plan after it was edited (e.g. by conflict resolution)."""
        findings = _verify(self, ruleset, context)
        self.blockers = [v for v in findings if v.kind != "order"]
        self.residual = [v for v in findings if v.kind == "order"]

    def write(self, directory: str) -> list[str]:
        os.makedirs(directory, exist_ok=True)
        written = []
        for role in self.logs:
            path = os.path.join(directory, role)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(self.render(role))
            written.append(path)
        return written


def _order_rules(ruleset: RuleSet, include_optional: bool) -> list:
    """
    The rules that become ordering constraints.

    ONLY explicit order rules. A dependency says "this mod needs that mod
    present", which is not the same claim as "install it later": BWS-NG records
    both `EET: EET_end` and `EET_end: EET`, and reading either as an ordering
    constraint invents a cycle and pushes the EET core to the end of the
    install. Dependencies are checked by rules.check(), where they belong.
    """
    return [rule for rule in ruleset.rules
            if rule.kind == "order" and rule.direction in ("before", "after")
            and (include_optional or not rule.optional)]


def _numbers(unit: Unit) -> list[int]:
    return [comp for _path, _lang, comp, _comment in unit.lines]


def _split(units: list[Unit], rules: list, index: OrderIndex) -> list[Unit]:
    """
    Split a mod into contiguous parts where its components belong apart.

    Two things put components of one mod in different places: the catalogue
    (krion64 files stratagems #4100 under POST EET) and a rule that names
    specific components ("stratagems(5900) after cdtweaks"). A part is a run of
    consecutive components that agree on both; a mod nothing distinguishes stays
    one unit, exactly as before. Parts keep their original order unless a rule
    says otherwise, because they share the mod's catalogue position and are
    tie-broken by log line.
    """
    named: dict[str, list[frozenset]] = {}
    for rule in rules:
        for spec in (rule.left, *rule.right):
            if spec.components is not None:
                named.setdefault(spec.mod, []).append(spec.components)

    out: list[Unit] = []
    for unit in units:
        groups = named.get(unit.key, [])

        def signature(number: int, key: str = unit.key, groups=groups):
            part = index.component(key, number)
            return (part.rank if part else None,
                    tuple(number in group for group in groups))

        runs: list[list[tuple[str, int, int, str]]] = []
        last = object()
        for entry in unit.lines:
            sig = signature(entry[2])
            if sig != last:
                runs.append([])
                last = sig
            runs[-1].append(entry)
        if len(runs) == 1:
            out.append(unit)
            continue
        for n, run in enumerate(runs):
            first = run[0][2]
            out.append(Unit(key=unit.key, tp2_file=unit.tp2_file, folder=unit.folder,
                            source_log=unit.source_log, seq=unit.seq + n,
                            lines=list(run),
                            slot=index.component(unit.key, first) or unit.slot,
                            target_log=unit.target_log, part=n, split=True,
                            parts=len(runs), placed_by=unit.placed_by,
                            placed_from=unit.placed_from, no_place=unit.no_place))
    return out


def _edges(units: list[Unit], rules: list,
           why: dict[tuple[str, str], list] | None = None
           ) -> tuple[dict[str, set[str]], int]:
    """
    Hard ordering constraints, between parts: `after -> before`, per log.
    `why`, when given, collects the rules behind each edge, by (unit, the
    unit it must follow): what the order page shows per row (item 33).

    A rule constrains the parts holding the components it names (all parts for
    a whole-mod side). Only parts in the SAME log are constrained: a mod in the
    pre-EET log does not order against a mod in the EET log. A rule between two
    components of one mod is honoured too, as long as they are different parts.
    """
    by_log: dict[str, list[Unit]] = {}
    for unit in units:
        by_log.setdefault(unit.target_log, []).append(unit)

    def holders(members: list[Unit], spec) -> list[Unit]:
        return [u for u in members if u.key == spec.mod
                and (spec.components is None
                     or any(n in spec.components for n in _numbers(u)))]

    edges: dict[str, set[str]] = {}
    count = 0
    for rule in rules:
        for members in by_log.values():
            lefts = holders(members, rule.left)
            if not lefts:
                continue
            for spec in rule.right:
                for left in lefts:
                    for right in holders(members, spec):
                        if right is left:
                            continue
                        first, second = ((left, right) if rule.direction == "before"
                                         else (right, left))
                        bucket = edges.setdefault(second.node, set())
                        if why is not None:
                            behind = why.setdefault((second.node, first.node), [])
                            if rule not in behind:
                                behind.append(rule)
                        if first.node not in bucket:
                            bucket.add(first.node)
                            count += 1
    return edges, count


def _priorities(units: list[Unit]) -> dict[str, tuple[int, int, int, int]]:
    """
    The order the catalogue wants, as a sort key per unit.

    A unit the catalogue does not know inherits the position of the last known
    unit that preceded it in the ORIGINAL log, so it stays where the operator
    put it instead of being swept to the end. Its own sequence number breaks the
    tie, preserving the input order among unknowns.
    """
    priorities: dict[str, tuple[int, int, int, int]] = {}
    inherited: dict[str, tuple[int, int, int]] = {}
    for unit in units:
        if unit.slot is not None:
            base = (unit.slot.rank, unit.slot.ord, unit.slot.after)
            if not unit.placed_by:
                # what follows a mod its kind or BWS-NG moved stays where it
                # was: it inherits krion64's last place (review of #67)
                inherited[unit.target_log] = base
        else:
            base = inherited.get(unit.target_log, (-1, -1, 0))
        priorities[unit.node] = (base[0], base[1], base[2], unit.seq)
    return priorities


def broken_pairs(order: Sequence[str],
                 before: Mapping[str, Iterable[str]]) -> set[tuple[str, str]]:
    """
    The rule pairs `order` breaks: (unit, one a rule puts before it, found
    after it). `before` maps a unit to the units that must come first; a unit
    not in `order` breaks nothing. The full check after a drop (item 31).
    """
    at = {node: n for n, node in enumerate(order)}
    return {(node, first) for node, firsts in before.items() if node in at
            for first in firsts if first in at and at[first] > at[node]}


def broken_after_move(previous: set[tuple[str, str]], order: Sequence[str],
                      before: Mapping[str, Iterable[str]], moved: str,
                      after: Mapping[str, Iterable[str]] | None = None
                      ) -> set[tuple[str, str]]:
    """
    `broken_pairs` after one unit moved, from what was broken before it did:
    a move changes only the pairs the moved unit is in, so only those are
    looked at again - BWS-NG's technique (M5b item 31). Equal to the full
    check, by a property test. `after`, the reverse of `before` (`reverse`),
    saves reading every edge to find who waits on the moved unit.
    """
    at = {node: n for n, node in enumerate(order)}
    kept = {pair for pair in previous if moved not in pair}
    if moved not in at:
        return kept
    mine = {(moved, first) for first in before.get(moved, ()) if first in at
            and at[first] > at[moved]}
    if after is None:
        after = reverse(before)
    theirs = {(node, moved) for node in after.get(moved, ())
              if node in at and at[moved] > at[node]}
    return kept | mine | theirs


@dataclass(frozen=True)
class OrderFix:
    """One way to mend a row a rule finds in the wrong place (M5b item 32)."""
    kind: str                           # "after": just after `anchor`; "before": just before it
    node: str                           # the unit moved
    anchor: str                         # the unit it is put next to
    order: tuple[str, ...]              # the order with the fix made
    fixed: frozenset[tuple[str, str]]   # the broken pairs it mends
    breaks: frozenset[tuple[str, str]]  # the pairs of `node` still broken after it


def order_fixes(order: Sequence[str], before: Mapping[str, Iterable[str]], node: str,
                after: Mapping[str, Iterable[str]] | None = None) -> list[OrderFix]:
    """
    The moves of `node` alone that mend a rule it breaks and break no other:
    just after the last unit a rule puts before it, if that one is below it,
    and just before the first a rule puts after it, if that one is above it.
    A move that would break another pair is not offered - a fix adds no error
    (GUI-AUDIT M5b item 32).
    """
    if after is None:
        after = reverse(before)
    at = {unit: n for n, unit in enumerate(order)}
    if node not in at:
        return []
    now = broken_after_move(set(), order, before, node, after)
    firsts = [at[unit] for unit in before.get(node, ()) if unit in at]
    thens = [at[unit] for unit in after.get(node, ()) if unit in at]
    candidates = []
    if firsts and max(firsts) > at[node]:
        candidates.append(("after", order[max(firsts)]))
    if thens and min(thens) < at[node]:
        candidates.append(("before", order[min(thens)]))
    fixes = []
    for kind, anchor in candidates:
        moved = [unit for unit in order if unit != node]
        spot = moved.index(anchor) + (kind == "after")
        moved.insert(spot, node)
        left = broken_after_move(now, moved, before, node, after)
        if left < now:                  # mends some, breaks nothing new
            fixes.append(OrderFix(kind, node, anchor, tuple(moved),
                                  frozenset(now - left), frozenset(left)))
    return fixes


def reverse(before: Mapping[str, Iterable[str]]) -> dict[str, set[str]]:
    """unit -> the units a rule puts after it."""
    out: dict[str, set[str]] = {}
    for node, firsts in before.items():
        for first in firsts:
            out.setdefault(first, set()).add(node)
    return out


def _toposort(units: list[Unit], edges: dict[str, set[str]],
              priorities) -> tuple[list[Unit], list[list[str]]]:
    """
    Kahn's algorithm, ties broken by catalogue priority.

    Rules are hard constraints; the catalogue position is only the preference
    used to choose among the units that are ready at the same moment. That is
    what makes the result "as close to the reference order as the rules allow"
    rather than "the reference order, rules permitting".

    A cycle is never fatal: the cycle's first member in priority is released and the cycle
    is reported, so the operator always gets a complete plan plus the exact list
    of rules that contradict each other.
    """
    members = {u.node: u for u in units}
    pending = {k: {d for d in edges.get(k, ()) if d in members} for k in members}
    dependents: dict[str, set[str]] = {k: set() for k in members}
    for key, deps in pending.items():
        for dep in deps:
            dependents[dep].add(key)

    ready = [(priorities[k], k) for k, deps in pending.items() if not deps]
    heapq.heapify(ready)
    emitted: list[Unit] = []
    cycles: list[list[str]] = []
    left = set(members)

    reported: list[set[str]] = []
    while left:
        if not ready:
            # Stuck: some rules contradict each other. Release a unit only from
            # inside a real cycle that waits on nothing else - before, every
            # unit left was reported as "the cycle" and the top one forced even
            # when it was merely downstream of one, breaking a rule that held
            # (audit 2026-10-23, GUI-AUDIT item 42).
            cycle = _first_cycle(left, pending, priorities)
            if not any(cycle <= seen for seen in reported):
                reported.append(cycle)
                stuck = sorted(cycle, key=lambda k: priorities[k])
                names = [members[k].display if members[k].split else members[k].key
                         for k in stuck]
                cycles.append(names if len(names) <= 12 else names[:12] + ["..."])
            forced = min(cycle, key=lambda k: priorities[k])
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


def _first_cycle(left: set[str], pending: dict[str, set[str]], priorities) -> set[str]:
    """The strongly connected group of units, among those left, that waits on
    nothing outside itself - a cycle the order cannot pass without breaking
    one of its rules. Of several, the one holding the highest-priority unit."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    groups: list[set[str]] = []
    counter = 0
    for root in sorted(left, key=lambda k: priorities[k]):
        if root in index:
            continue
        work = [(root, iter(sorted(pending[root] & left)))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, deps = work[-1]
            advanced = False
            for dep in deps:
                if dep not in index:
                    index[dep] = low[dep] = counter
                    counter += 1
                    stack.append(dep)
                    on_stack.add(dep)
                    work.append((dep, iter(sorted(pending[dep] & left))))
                    advanced = True
                    break
                if dep in on_stack:
                    low[node] = min(low[node], index[dep])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                group = set()
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    group.add(member)
                    if member == node:
                        break
                groups.append(group)
    closed = [g for g in groups if all(pending[k] & left <= g for k in g)
              and (len(g) > 1 or any(k in pending[k] for k in g))]
    return min(closed, key=lambda g: min(priorities[k] for k in g))


def _minimum_moves(before: list[str], after: list[str]) -> list[tuple[str, int, int]]:
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


def plan_order(specs: Sequence[tuple[str, str]], index: OrderIndex,
               ruleset: RuleSet | None = None, context=None,
               include_optional: bool = False,
               reassign_phase: bool = False,
               kinds: Mapping[str, KindHint] | None = None,
               sequence: Sequence[tuple[str, int]] = ()) -> OrderPlan:
    """
    Build a rule-compliant install order for the components in `specs`.

    `specs` pairs each input log with the role it plays: `WeiDU.log` for the
    EET (merged-game) install, `WeiDU-BGEE.log` for the pre-EET BG1 phase.
    What krion64 does not place in the install after the EET core takes,
    first, its place in `sequence` - BWS-NG's EET order, (mod, component)
    pairs - right after the nearest entry before it that krion64 places;
    else the place its kind decides, from `kinds` (mod key -> what the
    sources say it is), where the kind decides one (ADR-0041 decision 2).
    """
    ruleset = ruleset or RuleSet()
    units, warnings = collect_units(specs)
    plan = OrderPlan(warnings=warnings)

    # Before the conversion EET's install is krion64's one category: no kind
    # places there. A single game's log is not that phase (review of #67).
    eet_build = any(role == EET_LOG for _path, role in specs)
    hints = kinds or {}
    in_folder: dict[tuple[str, str], int] = {}
    for unit in units:
        folder = (unit.source_log, normalize_key(unit.folder))
        in_folder[folder] = in_folder.get(folder, 0) + 1
    in_sequence: dict[tuple[str, int | None], int] = {}
    for at, (mod, number) in enumerate(sequence):
        in_sequence.setdefault((mod, number), at)
        in_sequence.setdefault((mod, None), at)
    for unit in units:
        unit.slot = index.get(unit.key)
        unit.target_log = unit.source_log
        disagree = ""
        if unit.slot is None and eet_build and unit.source_log == EET_LOG:
            disagree = _place_by_sequence(unit, index, sequence, in_sequence, plan)
        if unit.slot is None and not (eet_build and unit.source_log == PRE_EET_LOG):
            hint = hints.get(unit.key)
            if hint is None and in_folder[(unit.source_log, normalize_key(unit.folder))] == 1:
                # a catalogue names the folder; only its one tp2 may take it
                hint = hints.get(normalize_key(unit.folder))
            _place_by_kind(unit, index, hint, plan)
        if disagree and unit.slot is None:
            unit.no_place = "; ".join(filter(None, (disagree, unit.no_place)))
        elif disagree:
            unit.placed_by += f" ({disagree})"
            plan.by_kind[-1] = (*plan.by_kind[-1][:2], unit.placed_by)
        if unit.no_place:
            plan.no_place.append((unit.source_log, unit.display, unit.no_place))
        if unit.slot is None:
            plan.unranked.append(unit.display)

    # Phase disagreements are reported; acting on one restructures the install.
    present = {(u.target_log, u.key) for u in units}
    for unit in units:
        if unit.slot is None or unit.placed_by:      # a kind says nothing of the phase
            continue
        wanted = PRE_EET_LOG if unit.slot.pre_eet else EET_LOG
        if wanted == unit.source_log or (wanted, unit.key) in present:
            continue
        note = Move(unit.key, unit.display, unit.source_log, wanted,
                    f"catalogue category {unit.slot.category!r}")
        plan.phase_notes.append(note)
        if reassign_phase:
            unit.target_log = wanted

    rules = _order_rules(ruleset, include_optional)
    plan.sorting_order = any(rule.origin == SORTING_ORDER for rule in rules)
    units = _split(units, rules, index)
    edges, plan.edges = _edges(units, rules)
    # What a rule places - not the player's own sorting order, which ties every
    # unit to the next and would mark them all.
    placed, _count = _edges(units, [r for r in rules if r.origin != SORTING_ORDER],
                            plan.edge_rules)
    plan.constrained = set(placed).union(*placed.values()) if placed else set()
    plan.rule_edges = placed
    priorities = _priorities(units)

    for role in (PRE_EET_LOG, EET_LOG):
        subset = [u for u in units if u.target_log == role]
        if not subset:
            continue
        ordered, cycles = _toposort(subset, edges, priorities)
        plan.logs[role] = ordered
        plan.cycles.extend(cycles)
        by_node = {u.node: u for u in ordered}
        for node, old, new in _minimum_moves([u.node for u in subset],
                                             [u.node for u in ordered]):
            unit = by_node[node]
            plan.moved.append(Move(unit.key, unit.display, str(old), str(new), role))

    plan.reverify(ruleset, context)
    return plan


def _place_by_sequence(unit: Unit, index: OrderIndex, sequence: Sequence[tuple[str, int]],
                       at: Mapping[tuple[str, int | None], int], plan: OrderPlan) -> str:
    """
    After the nearest component before it, in BWS-NG's EET sequence, that
    krion64 places - BWS-NG's order carried onto krion64's, before any kind
    (ADR-0041 decision 2a). Units put after one anchor keep BWS-NG's order.

    Limits (review of #71): what BWS-NG installs before the EET core is not
    this install's to place. krion64 mostly places a whole mod where it
    starts, so a neighbour counts only in its mod's first run of the
    sequence (bws-fr-fixpack's #1, at the end, is not where krion64 puts
    it). And both neighbours are asked: where they are in different krion64
    categories, or there is none after it, the sequence decides nothing and
    says so (returned, for the reason the plan gives).
    """
    first = _numbers(unit)[0] if unit.lines else None
    start = at.get((unit.key, first), at.get((unit.key, None)))
    core = at.get(("eet", 0))
    if start is None or (core is not None and start < core):
        return ""
    runs = _first_runs(sequence)
    before = _anchor(index, ((i, sequence[i]) for i in range(start - 1, -1, -1)),
                     unit.key, runs)
    after = _anchor(index, ((i, sequence[i]) for i in range(start + 1, len(sequence))),
                    unit.key, runs)
    if before is None:
        return ""
    (mod, number), anchor = before
    if after is None:
        return "BWS-NG places nothing krion64 knows after it"
    if after[1].category != anchor.category:
        return (f"BWS-NG's neighbours disagree ({mod} in {anchor.category}, "
                f"{after[0][0]} in {after[1].category})")
    unit.slot = Slot(category=anchor.category, rank=anchor.rank, ord=anchor.ord,
                     pre_eet=False, after=start + 1)
    unit.placed_by = f"placed by BWS-NG's EET sequence: after {mod} #{number}"
    unit.placed_from = "BWS-NG"
    plan.by_sequence.append((unit.display, anchor.category, unit.placed_by))
    return ""


def _anchor(index: OrderIndex, entries, own: str, runs: dict[str, range]):
    """The first (entry, slot) of `entries` krion64 places after the core: a
    component krion64 places itself, or one in its mod's first run."""
    for at, (mod, number) in entries:
        if mod == own:
            continue
        slot = index.component(mod, number)
        if slot is None and at in runs.get(mod, range(0)):
            slot = index.get(mod)
        if slot is not None and not slot.pre_eet:
            return (mod, number), slot
    return None


def _first_runs(sequence: Sequence[tuple[str, int]]) -> dict[str, range]:
    """Each mod's first unbroken run of entries in the sequence."""
    runs: dict[str, range] = {}
    for at, (mod, _number) in enumerate(sequence):
        if mod not in runs:
            end = at
            while end < len(sequence) and sequence[end][0] == mod:
                end += 1
            runs[mod] = range(at, end)
    return runs


def bws_sequence(eet: object) -> list[tuple[str, int]]:
    """BWS-NG's `games/eet.json`, its bg2ee sequence as (mod key, component)."""
    sequences = eet.get("sequences") if isinstance(eet, dict) else None
    out: list[tuple[str, int]] = []
    for entry in next((s.get("order") or () for s in sequences or ()
                       if isinstance(s, dict) and str(s.get("game")).lower() == "bg2ee"),
                      ()):
        mod, _sep, number = str(entry).partition(":")
        if normalize_key(mod) and number.strip().isdigit():
            out.append((normalize_key(mod), int(number)))
    return out


def _place_by_kind(unit: Unit, index: OrderIndex, hint: KindHint | None,
                   plan: OrderPlan) -> None:
    """
    A slot from the mod's kind, after every mod krion64 places in that
    category - a preference, like krion64's own: the player's Sorting Order,
    the authors' inis and BWS-NG's rules still decide over it.
    """
    if hint is None:
        return
    category, why = place(hint)
    if category is None or category not in index.categories:
        unit.no_place = (why if category is None else
                         f"no place: krion64 has no {category!r}")
        return
    unit.slot = Slot(category=category, rank=index.categories.index(category),
                     ord=_AFTER_THE_CATEGORY, pre_eet=False)
    unit.placed_by = why
    unit.placed_from = "kind"
    plan.by_kind.append((unit.display, category, why))


_AFTER_THE_CATEGORY = 10 ** 6       # beyond any `ord` krion64 gives


def _as_install(units: list[Unit], label: str) -> Install:
    """Present the planned order to the checker exactly as a log would be."""
    install = Install(label=label)
    line = 0
    for unit in units:
        for path, _lang, component, comment in unit.lines:
            folder = normalize_key(path.replace("\\", "/").split("/")[0])
            label = comment.rsplit(" : ", 1)[0].strip() if comment else ""
            for key in dict.fromkeys((folder, unit.key)):
                install.display.setdefault(key, unit.mod_display)
                install.components.setdefault(key, set()).add(component)
                install.positions.setdefault(key, {}).setdefault(component, line)
                if label:
                    install.labels.setdefault(key, {}).setdefault(component, label)
            line += 1
    return install


def _verify(plan: OrderPlan, ruleset: RuleSet, context) -> list:
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
        mods = len({u.key for u in units})
        split = len({u.key for u in units if u.split})
        print(f"  {role:<16} {mods:>4} mods, "
              f"{sum(len(u.lines) for u in units):>4} components"
              + (f", {split} split across the order" if split else ""), file=stream)
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

    over = (" Your Sorting Order applies over these places." if plan.sorting_order
            else "")
    if plan.by_sequence:
        print(f"\n  placed by BWS-NG's EET sequence ({len(plan.by_sequence)}) — krion64 "
              f"does not place them; after the component before them there.{over}",
              file=stream)
        for name, category, why in plan.by_sequence:
            print(f"    {name:<32} {category}  ({why})", file=stream)

    if plan.by_kind:
        print(f"\n  placed by kind ({len(plan.by_kind)}) — krion64 does not place "
              f"them; after its own mods in the category.{over}", file=stream)
        for name, category, why in plan.by_kind:
            print(f"    {name:<32} {category}  ({why})", file=stream)

    if plan.unranked:
        shown = ", ".join(plan.unranked[:8])
        more = f" (+{len(plan.unranked) - 8} more)" if len(plan.unranked) > 8 else ""
        print(f"\n  not in the catalogue ({len(plan.unranked)}) — left where you "
              f"put them: {shown}{more}", file=stream)
        for _log, name, why in plan.no_place:
            print(f"    {name:<32} {why}", file=stream)
