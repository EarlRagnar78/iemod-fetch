"""
The components a player chooses from, before and after a mod is downloaded
(M3 phase 2, ADR-0035).

A choice has to be offered before anything is downloaded, but the only exact
list of a mod's components is its own tp2, read the way WeiDU reads it
(tra.describe, 9,889 of 9,889 names identical to WeiDU's). So there are two
sources, and every component says which one it came from:

* `tp2` - the staged mod's own tp2. Once a mod is staged, it alone decides.
* `krion64` - krion64's per-mod records, for a mod not downloaded yet. Measured
  against WeiDU 251's --list-components on 105 real mods (docs/TESTING.md):
  1,471 of 1,529 components present, 85 of 105 mods identical; the rest are
  components a mod added or dropped since the record was written. So a choice
  made from them is checked again against the tp2 once the mod is staged.

Exclusive choices are WeiDU's SUBCOMPONENTs: of the components that share
one, a player installs at most one. From a tp2 that is the subgroup; from
krion64 its `g` (mutex group) with `scn` as the subgroup's name. A component
removed from the mod (`gone`) or that WeiDU hides (DEPRECATED) is not offered.
"""
from dataclasses import dataclass, field
from collections.abc import Iterable

from .naming import normalize_key

TP2 = "tp2"
KRION = "krion64"


@dataclass
class Component:
    number: int
    name: str
    subgroup: str = ""            # the SUBCOMPONENT's title, if any
    exclusive: str = ""           # components sharing a non-empty key exclude each other
    groups: list[str] = field(default_factory=list)
    requires: list[int] = field(default_factory=list)   # same-mod components it needs
    forced: bool = False          # FORCED_SUBCOMPONENT: one of the group must be chosen

    def as_dict(self) -> dict:
        return {"number": self.number, "name": self.name, "subgroup": self.subgroup,
                "exclusive": self.exclusive, "groups": list(self.groups),
                "requires": list(self.requires), "forced": self.forced}


@dataclass
class ModTp2:
    """One tp2 of a mod folder (EET ships two) and what it offers."""
    tp2: str                      # folder/setup-mod.tp2, forward slashes
    origin: str                   # TP2 or KRION
    components: list[Component] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"tp2": self.tp2, "origin": self.origin,
                "components": [c.as_dict() for c in self.components]}


def folder_key(tp2: str) -> str:
    """The mod folder a tp2 path names, as a catalogue key."""
    return normalize_key(tp2.replace("\\", "/").split("/")[0])


def from_described(described: Iterable[dict]) -> dict[str, list[ModTp2]]:
    """api.describe_mods' output: folder key -> its tp2s, exact."""
    out: dict[str, list[ModTp2]] = {}
    for mod in described:
        if not isinstance(mod, dict) or not isinstance(mod.get("tp2"), str):
            continue
        components = []
        for raw in mod.get("components") or []:
            if raw.get("deprecated"):
                continue
            subgroup = raw.get("subgroup") or ""
            components.append(Component(
                int(raw["number"]), raw.get("title") or raw.get("name") or "",
                subgroup=subgroup, exclusive=f"sub:{subgroup}" if subgroup else "",
                groups=list(raw.get("groups") or []), forced=bool(raw.get("forced"))))
        out.setdefault(folder_key(mod["tp2"]), []).append(
            ModTp2(mod["tp2"].replace("\\", "/"), TP2, components))
    return out


def from_krion(records: Iterable[dict]) -> dict[str, list[ModTp2]]:
    """krion64's per-mod records: folder key -> its tp2s, as krion64 lists them."""
    out: dict[str, dict[str, ModTp2]] = {}
    for record in records:
        listed = record.get("co") if isinstance(record, dict) else None
        if not isinstance(listed, list):
            continue
        numbers = {}                  # index in co[] -> component number (for rd/x)
        for index, raw in enumerate(listed):
            if isinstance(raw, dict):
                number = _number(raw)
                if number is not None:
                    numbers[index] = number
        for index, raw in enumerate(listed):
            if not isinstance(raw, dict) or raw.get("gone") or index not in numbers:
                continue
            path = raw.get("wp")
            if not isinstance(path, str) or "/" not in path.replace("\\", "/"):
                continue
            path = path.replace("\\", "/")
            group = raw.get("g")
            subgroup = _text(raw.get("scn"))
            requires = [numbers[i] for i in _indexes(raw.get("rd")) if i in numbers]
            name = _text(raw.get("n")) or f"#{numbers[index]}"
            tp2 = out.setdefault(folder_key(path), {}).setdefault(
                path.lower(), ModTp2(path, KRION))
            if any(c.number == numbers[index] for c in tp2.components):
                continue        # two records list this tp2, or one lists a number twice
            tp2.components.append(Component(
                numbers[index], name, subgroup=subgroup,
                exclusive=f"g:{group}" if group not in (None, "") else "",
                groups=[raw["grn"]] if isinstance(raw.get("grn"), str) else [],
                requires=requires))
    return {key: list(tp2s.values()) for key, tp2s in out.items()}


def merged(staged: dict[str, list[ModTp2]],
           krion: dict[str, list[ModTp2]]) -> dict[str, list[ModTp2]]:
    """Per mod folder, the staged tp2s if the mod is staged, else krion64's."""
    out = dict(krion)
    out.update(staged)
    return out


def _number(raw: dict) -> int | None:
    number = raw.get("wc", raw.get("cn"))
    return number if isinstance(number, int) and not isinstance(number, bool) else None


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def _indexes(value) -> list[int]:
    items = value if isinstance(value, list) else [value]
    return [i for i in items if isinstance(i, int) and not isinstance(i, bool)]
