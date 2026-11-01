"""
Project Infinity mod lists, read as a selection (M2).

Project Infinity (PI) exports and imports an install list as text, one
component per line, in install order:

    A7-DLCMERGER-MERGE_SOD;DLC Merger - Merge "Siege of Dragonspear" DLC
    eefixpack:0;EE Fixpack - Core Fixes

The part before `;` names the component: a WeiDU LABEL, or `folder:number`
when the component has no LABEL. The part after is a description for people.
Infinity Mod Forge writes the same format (`install-EET.txt`).

A LABEL has to be found in some tp2 to become a component. The mods' own tp2s
decide - they are what WeiDU reads, and this tool reads their LABELs exactly as
WeiDU does (tra.py, 1,499 of 1,499 against --list-components-json). Where a
mod is not staged yet, krion64's records name the LABEL's component; they
agree with the tp2s for 708 of 732 LABELs found in both (docs/TESTING.md), so
an entry resolved that way says so. A line resolved by neither is reported,
never matched by its description.
"""
from dataclasses import dataclass, field
from collections.abc import Iterable

from .errors import ConfigError
from .naming import normalize_key
from .selection import Choice, Install, Selection, parse_selection, selection_to_json
from .weidu import KNOWN_GAMES

_GAMES = {game.upper(): game for game in KNOWN_GAMES}
TP2 = "tp2"
KRION = "krion64"


@dataclass(frozen=True)
class PiLine:
    ident: str
    description: str
    line: int


@dataclass(frozen=True)
class Target:
    tp2: str            # folder/setup-mod.tp2, forward slashes
    number: int
    origin: str         # TP2 (read from the mod) or KRION


@dataclass
class LabelIndex:
    """LABEL -> component, and folder -> its tp2, from tp2s first, krion64 second."""
    labels: dict[str, Target] = field(default_factory=dict)
    tp2s: dict[str, tuple[str, str]] = field(default_factory=dict)   # folder key -> (tp2, origin)
    ambiguous: dict[str, list[Target]] = field(default_factory=dict)

    def add(self, label: str, target: Target) -> None:
        key = label.strip().lower()
        known = self.labels.get(key)
        if known is None or (known.origin == KRION and target.origin == TP2):
            self.labels[key] = target
            self.ambiguous.pop(key, None)
        elif known.origin == target.origin and known != target:
            # Two tp2s (or two records) claim one LABEL: which one is not ours to pick.
            self.ambiguous.setdefault(key, [known]).append(target)

    def add_tp2(self, tp2: str, origin: str) -> None:
        folder = normalize_key(tp2.replace("\\", "/").split("/")[0])
        if folder not in self.tp2s or (self.tp2s[folder][1] == KRION and origin == TP2):
            self.tp2s[folder] = (tp2.replace("\\", "/"), origin)


def parse_pi_list(text: str) -> list[PiLine]:
    """Every `ident;description` line, in order; comments and blanks skipped."""
    out = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith(("#", "//")):
            continue
        ident, sep, description = line.partition(";")
        if not sep or not ident.strip():
            raise ConfigError(f"line {number}: not 'identifier;description': {line[:80]!r}")
        out.append(PiLine(ident.strip(), description.strip(), number))
    return out


def index_from_described(mods: Iterable[dict]) -> LabelIndex:
    """From api.describe_mods: the LABELs of the staged tp2s."""
    index = LabelIndex()
    for mod in mods:
        index.add_tp2(mod["tp2"], TP2)
        for component in mod["components"]:
            for label in component.get("labels", []):
                index.add(label, Target(mod["tp2"], component["number"], TP2))
    return index


def add_krion(index: LabelIndex, records: Iterable[dict]) -> LabelIndex:
    """krion64's per-mod records: `co[].pi` is the LABEL, `wp` the tp2, `wc`/`cn` the number."""
    for record in records:
        components = record.get("co") if isinstance(record, dict) else None
        for component in components if isinstance(components, list) else []:
            if not isinstance(component, dict) or not isinstance(component.get("wp"), str):
                continue
            path = component["wp"].replace("\\", "/")
            if "/" not in path:
                continue
            index.add_tp2(path, KRION)
            number = component.get("wc", component.get("cn"))
            if isinstance(component.get("pi"), str) and component["pi"] \
                    and isinstance(number, int):
                index.add(component["pi"], Target(path, number, KRION))
    return index


def selection_from_pi(lines: list[PiLine], game: str, index: LabelIndex
                      ) -> tuple[Selection, list[str]]:
    """
    The selection a PI list says, and one note per entry krion64 resolved.
    Raises ConfigError naming every line no source resolves.
    """
    name = _GAMES.get(game.upper())
    if name is None:
        raise ConfigError(f"unknown game {game!r} for a Project Infinity list")
    choices: list[Choice] = []
    notes: list[str] = []
    unresolved: list[str] = []
    for line in lines:
        target = _resolve(line.ident, index)
        if isinstance(target, str):
            unresolved.append(f"line {line.line}: {line.ident} ({line.description}) - {target}")
            continue
        if target.origin == KRION:
            notes.append(f"line {line.line}: {line.ident} -> {target.tp2} #{target.number} "
                         f"from krion64's records (the mod is not staged; checked "
                         f"against its tp2 once it is)")
        choices.append(Choice(tp2=target.tp2, component=target.number,
                              label=line.description.replace("~", "")))
    if unresolved:
        raise ConfigError("Project Infinity list: these entries name no known component "
                          "(fetch the mods first so their tp2 LABELs can be read):\n  "
                          + "\n  ".join(unresolved))
    # Through selection.json's own checks: a tp2 path from someone else's data
    # (krion64's `wp`) is refused here if it would leave its folder.
    selection = Selection([Install(name, choices)])
    return parse_selection(selection_to_json(selection), source="the PI list"), notes


def _resolve(ident: str, index: LabelIndex):
    """A Target, or the reason there is none."""
    folder, sep, number = ident.rpartition(":")
    if sep and number.isdigit() and folder:
        known = index.tp2s.get(normalize_key(folder))
        if known is None:
            return f"no tp2 known for folder '{folder}'"
        return Target(known[0], int(number), known[1])
    key = ident.lower()
    if key in index.ambiguous:
        claims = ", ".join(f"{t.tp2} #{t.number}" for t in index.ambiguous[key])
        return f"LABEL claimed by more than one component: {claims}"
    found: Target | None = index.labels.get(key)
    if found is None:
        return "LABEL not found in any staged tp2 or krion64 record"
    staged = index.tp2s.get(normalize_key(found.tp2.split("/")[0]))
    if found.origin == KRION and staged is not None and staged[1] == TP2:
        # The mod is here and its tp2 has no such LABEL: krion64 is out of date.
        return f"the staged {staged[0]} has no such LABEL (krion64 names #{found.number})"
    return found
