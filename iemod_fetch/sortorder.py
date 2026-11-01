"""
Project Infinity's "Sorting Order" file, read as order rules (ADR-0037).

A player who built an install order in Project Infinity keeps it as a text
file of tp2 names (its wiki, "Sorting Order feature"):

    Ascension *          // every chosen component of Ascension
    ajantisbg2 *
    Ascension 101 102    // these two later, apart from the rest

It sorts only what is chosen - it never adds or drops a mod - and a component
named on its own line is taken out of its mod's `*` line. Each line is one
group; the groups go in file order. Here that becomes order rules between
consecutive groups of what the selection holds, origin "SortingOrder", so the
planner treats them as it treats any rule: they move what they name, and a
contradiction with another rule is reported, not silently won.
"""
import itertools
from dataclasses import dataclass

from .errors import ConfigError
from .naming import normalize_key
from .ordering import name_key
from .rules import ORDER, SORTING_ORDER, ModSpec, Rule

ORIGIN = SORTING_ORDER
_MAX_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class Entry:
    key: str                         # tp2 key
    name: str                        # as written
    numbers: tuple[int, ...] | None   # None: every chosen component ("*")
    line: int


def parse(text: str, source: str = "SortingOrder") -> list[Entry]:
    out = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("//", 1)[0].replace(",", " ").replace(";", " ").strip()
        if not line or line.startswith("#"):
            continue
        name, *rest = line.split()
        if not normalize_key(name):
            raise ConfigError(f"{source}:{number}: no tp2 name in {raw.strip()!r}")
        if rest == ["*"] or not rest:
            out.append(Entry(name_key(name), name, None, number))
            continue
        if not all(part.isdigit() for part in rest):
            raise ConfigError(f"{source}:{number}: expected '*' or component numbers "
                              f"after {name}, got {' '.join(rest)!r}")
        out.append(Entry(name_key(name), name, tuple(int(p) for p in rest), number))
    return out


def load(path: str) -> list[Entry]:
    try:
        with open(path, "rb") as fh:
            data = fh.read(_MAX_BYTES + 1)
    except OSError as exc:
        raise ConfigError(f"cannot read --sorting-order {path}: {exc}") from exc
    if len(data) > _MAX_BYTES:
        raise ConfigError(f"{path}: larger than {_MAX_BYTES} bytes")
    return parse(data.decode("utf-8-sig", errors="replace"), source=path)


def rules(entries: list[Entry], chosen: dict[str, set[int]]) -> list[Rule]:
    """
    Order rules from `entries` for a selection: `chosen` maps a tp2 key to the
    components chosen from it. A `*` line stands for the chosen components not
    named on a line of their own; a group nothing chosen falls in is skipped,
    and a component already placed by an earlier line stays there (a repeated
    line would otherwise order a mod before itself).
    """
    named: dict[str, set[int]] = {}
    for entry in entries:
        if entry.numbers is not None:
            named.setdefault(entry.key, set()).update(entry.numbers)
    groups: list[tuple[Entry, frozenset]] = []
    placed: dict[str, set[int]] = {}
    for entry in entries:
        have = chosen.get(entry.key, set()) - placed.get(entry.key, set())
        wanted = (have - named.get(entry.key, set()) if entry.numbers is None
                  else have & set(entry.numbers))
        if wanted:
            groups.append((entry, frozenset(wanted)))
            placed.setdefault(entry.key, set()).update(wanted)
    out = []
    for (first, a), (second, b) in itertools.pairwise(groups):
        out.append(Rule(
            ORDER, ModSpec(first.key, first.name, a), (ModSpec(second.key, second.name, b),),
            severity="warning", direction="before", origin=ORIGIN,
            message=f"your sorting order (line {first.line} before line {second.line})"))
    return out
