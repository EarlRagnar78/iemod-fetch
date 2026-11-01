"""
Engine limits a big install can run out of (ADR-0034).

Three tables of the Enhanced Edition engine fill up as mods add to them, and
past the end a mod fails to install or the game misbehaves:

* **kits** - WeiDU's ADD_KIT refuses a kit number above 256 on every EE game
  ("The game requires ToBEx or GemRB to support more than 256 kits",
  WeiDU src/tpaction.ml). BG2:EE's own KITLIST.2DA holds 40 kits (IESDP).
* **spell states** - SPLSTATE.IDS ids run 0-255 without EEex (EEex's
  EEex_Stats_Patch.lua: "the vanilla range of [0-255]"); about 133 are taken
  by the game (IESDP's BG:EE list), leaving 123.
* **spell slots** - WeiDU's ADD_SPELL gives wizard and priest spells 50 ids
  per level (src/tph/define/add_spell.tpa, `tb#max_spell = 50`). What the
  engine does past that is not documented by a primary source.

Infinity Mod Forge warns on the same three with other numbers (320 kits, 128
spell states taken); those are reported beside ours, not used. What each
component adds comes from krion64's records (`k`, `ss`, `spLv`/`sp`) - and
only for components krion64 has measured, so every total says how much of the
selection it could see. Its spell-state counts include ids a mod only reads,
so that table is shown, never warned on. No game version is assumed: nothing here differs
between patch 2.5, 2.6 and 2.7 in any source found, and nothing is blocked -
these are warnings.

krion64's own counts are estimates with known faults, checked against its
scripts and 103 mod repositories (docs/TESTING.md): its spell scanner
(scan_spell_ids.js) reads only literal `APPEND spell.ids` lines, so a spell
added with ADD_SPELL - WeiDU's own way - is not counted (NWNForBG adds 6,
Region of Terror 4; krion64 records 0 for both); `ss` counts references; `k`
is entered by hand. So when the game folder is known - the WeiDU.log sits in
it, beside chitin.key - the tables are **measured** instead, by WeiDU's own
rules: the next kit number as get_next_kit_number finds it, a spell slot as
taken when ADD_SPELL would skip it (an id in SPELL.IDS or ADD_SPELL.IDS, or
an SPxxLnn.SPL already there), the spell states SPLSTATE.IDS lists. krion64's
numbers then only stand in for components the game does not have yet.
"""
import re
from dataclasses import dataclass, field
from collections.abc import Iterable, Mapping, Sequence

from .naming import normalize_key
from .ordering import tp2_key

WARN_SHARE = 0.9          # warn when 90% of a table is used


@dataclass(frozen=True)
class Limit:
    key: str
    label: str
    cap: int
    base: int
    source: str
    forge_cap: int | None = None     # what Infinity Mod Forge uses, if different
    forge_base: int | None = None


KITS = Limit("kits", "kits (KITLIST.2DA)", 256, 40,
             "WeiDU ADD_KIT refuses kit number > 256 on EE games (src/tpaction.ml); "
             "BG2:EE ships 40 kits (IESDP kitlist)", forge_cap=320, forge_base=37)
SPELL_STATES = Limit("spell_states", "spell states (SPLSTATE.IDS)", 256, 133,
                     "ids 0-255 without EEex (EEex_Stats_Patch.lua); ~133 used by the "
                     "game (IESDP splstate)", forge_base=128)
SPELL_SLOTS = 50          # per type and level: WeiDU add_spell.tpa
# The game's own spells per level, as Infinity Mod Forge counts them
# (VANILLA_SPELLS); w = wizard, p = priest. Not checked against a primary source.
GAME_SPELLS = {"w1": 22, "w2": 21, "w3": 21, "w4": 24, "w5": 18, "w6": 20, "w7": 20,
               "w8": 12, "w9": 18, "p1": 13, "p2": 14, "p3": 16, "p4": 17, "p5": 16,
               "p6": 14, "p7": 20}


@dataclass
class Tally:
    """One table: what the game takes, what the selection adds, and who adds it."""
    label: str
    cap: int
    base: int
    added: int = 0
    by: list[tuple[str, int, int]] = field(default_factory=list)   # (mod, component, n)
    source: str = ""
    note: str = ""
    checked: bool = True        # False: the counts are not reliable enough to warn on
    measured: bool = False      # base read from the game folder, not assumed

    @property
    def total(self) -> int:
        return self.base + self.added

    @property
    def severity(self) -> str | None:
        if not self.checked:
            return None
        if self.total > self.cap:
            return "error"
        if self.total >= self.cap * WARN_SHARE:
            return "warning"
        return None

    def as_dict(self) -> dict:
        return {"label": self.label, "cap": self.cap, "base": self.base,
                "added": self.added, "total": self.total, "severity": self.severity,
                "source": self.source, "note": self.note, "checked": self.checked,
                "measured": self.measured,
                "added_by": [{"mod": m, "component": c, "count": n} for m, c, n in self.by]}


@dataclass
class LimitsReport:
    install: str
    tallies: list[Tally] = field(default_factory=list)
    components: int = 0           # chosen components
    unknown_mods: list[str] = field(default_factory=list)   # mods krion64 has no record of
    eeex: bool = False
    measured_from: str | None = None     # the game folder the tables were read from
    unlevelled_spells: int = 0    # krion64 counts them but not by level: not checked

    def as_dict(self) -> dict:
        return {"install": self.install, "components": self.components,
                "mods_without_data": list(self.unknown_mods), "eeex": self.eeex,
                "spells_of_unknown_level": self.unlevelled_spells,
                "measured_from": self.measured_from,
                "tables": [t.as_dict() for t in self.tallies]}

    def render(self) -> str:
        lines = [f"  [{self.install}] engine limits"
                 + (f" (measured in {self.measured_from})" if self.measured_from else "")
                 + (f" - {len(self.unknown_mods)} mod(s) krion64 has no counts for, so "
                    f"these are at least: {', '.join(self.unknown_mods[:6])}"
                    + (" ..." if len(self.unknown_mods) > 6 else "")
                    if self.unknown_mods else "")]
        for tally in self.tallies:
            mark = {"error": "!!", "warning": " !"}.get(tally.severity or "",
                                                        "  " if tally.checked else " ?")
            lines.append(f"    {mark} {tally.label}: {tally.total}/{tally.cap} "
                         f"({tally.base} the game's, {tally.added} from mods)"
                         + (f" - {tally.note}" if tally.note else ""))
            for mod, number, count in sorted(tally.by, key=lambda b: -b[2])[:3]:
                lines.append(f"         {count:>3} {mod} #{number}")
        if self.unlevelled_spells:
            lines.append(f"       + {self.unlevelled_spells} new spell(s) whose level krion64 "
                         f"does not record: not counted against a level")
        return "\n".join(lines)


@dataclass(frozen=True)
class Measured:
    """What the game folder holds now; None where a table could not be read."""
    kits: int | None = None                       # the last kit number in use
    spell_slots: dict[str, int] | None = None     # "w1".."p7" -> slots taken of 50
    spell_states: int | None = None               # ids 0-255 in SPLSTATE.IDS


_ROW_NUMBER = re.compile(r"[\r\n]([0-9]+)(?=\s|$)")
_KITLIST_EX = re.compile(r"[\r\n]([0-9]+)[ \t]+\*[ \t]+\*")
_IDS_LINE = re.compile(r"^[ \t]*(0x[0-9a-fA-F]+|[0-9]+)[ \t]+\S", re.MULTILINE)
_SPELL_FILE = {"p": "sppr", "w": "spwi"}


def kits_in_use(kitlist: str) -> int | None:
    """
    The last kit number KITLIST.2DA holds - WeiDU's get_next_kit_number less
    one: the first free `N * *` row of an extended kitlist, else the number
    of the last numbered row. ADD_KIT fails once the next number passes 256.
    """
    extended = _KITLIST_EX.search(kitlist)
    if extended:
        return int(extended.group(1)) - 1
    rows = _ROW_NUMBER.findall(kitlist)
    return int(rows[-1]) if rows else None


def ids_numbers(text: str) -> list[int]:
    """The numbers an IDS file assigns (its header line is not one), read as
    WeiDU's lexer reads it: any line ending, comments skipped."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"//[^\r\n]*", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for value in _IDS_LINE.findall(text):
        out.append(int(value, 16) if value.lower().startswith("0x") else int(value))
    return out


def spell_slots_taken(spell_ids: str, add_spell_ids: str | None,
                      spell_files: Iterable[str]) -> dict[str, int]:
    """
    Per wizard/priest level, how many of the 50 slots ADD_SPELL would skip:
    an id in SPELL.IDS or ADD_SPELL.IDS, or a SPWI/SPPR file already in the
    game (add_spell.tpa, TB#ADD_SPELL_FIND_SLOT).
    """
    taken: set[tuple[str, int, int]] = set()     # ("w" or "p", level, slot)
    for text in (spell_ids, add_spell_ids or ""):
        for number in ids_numbers(text):
            kind, level, slot = number // 1000, number // 100 % 10, number % 100
            if kind in (1, 2) and 1 <= slot <= SPELL_SLOTS:
                taken.add(("p" if kind == 1 else "w", level, slot))
    files = {name.lower() for name in spell_files}
    for letter, prefix in _SPELL_FILE.items():
        for level in range(1, 10):
            for slot in range(1, SPELL_SLOTS + 1):
                if f"{prefix}{level}{slot:02d}" in files:
                    taken.add((letter, level, slot))
    out: dict[str, int] = {}
    for letter, level, _slot in taken:
        if level >= 1 and (letter == "w" or level <= 7):
            out[f"{letter}{level}"] = out.get(f"{letter}{level}", 0) + 1
    return out


def spell_states_in_use(splstate_ids: str) -> int:
    return len({n for n in ids_numbers(splstate_ids) if 0 <= n <= 255})


def _index(records: Iterable[dict]) -> dict[str, dict[int, dict]]:
    """
    krion64 records -> tp2 key -> component number -> component.

    Each component is filed under the tp2 its `wp` names - one folder can hold
    several tp2s (eet/EET.tp2 and eet/EET_end/EET_end.tp2), so neither the
    folder (`wf`) nor the record as a whole is the key. `t` stands in only for
    a component with no `wp`. Malformed records and components are skipped:
    these counts are advice and never stop the report.
    """
    out: dict[str, dict[int, dict]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("co"), list):
            continue
        title = record.get("t")
        for position, component in enumerate(record["co"]):
            if not isinstance(component, dict):
                continue
            number = component.get("wc", component.get("cn"))
            if not isinstance(number, int) or isinstance(number, bool):
                continue
            path = component.get("wp")
            key = (tp2_key(path) if isinstance(path, str) and path else
                   normalize_key(title) if isinstance(title, str) and title else "")
            if not key:
                continue
            entry = dict(component)
            if position == 0 and record.get("ss") and not entry.get("ss"):
                entry["ss"] = record["ss"]     # Mod Forge's mod-level spell states
            out.setdefault(key, {}).setdefault(number, entry)
    return out


def engine_limits(install: str, chosen: Sequence[tuple[str, int]],
                  records: Iterable[dict], eeex: bool = False,
                  measured: Measured | None = None,
                  installed: Iterable[tuple[str, int]] = (),
                  measured_from: str | None = None) -> LimitsReport:
    """
    The three tables for one install. `chosen` is (tp2 key, component number)
    in install order; `records` krion64's per-mod records. With `measured`
    (read from the game folder, which already holds `installed`), a measured
    table starts from what the game holds and krion64 only adds the chosen
    components the game does not have yet.
    """
    measured = measured or Measured()
    present = set(installed)
    index = _index(records)
    chosen = list(dict.fromkeys(chosen))        # a log can list a component twice
    report = LimitsReport(install, components=len(chosen), eeex=eeex,
                          measured_from=measured_from)
    kits = Tally(KITS.label, KITS.cap, KITS.base, source=KITS.source,
                 note=f"Infinity Mod Forge says {KITS.forge_cap}; WeiDU stops at {KITS.cap}")
    if measured.kits is not None:
        kits.base, kits.measured = measured.kits, True
        kits.source = "measured: the last kit number in KITLIST.2DA; " + KITS.source
    # krion64's `ss` counts a mod's SPLSTATE.IDS references, not only the ids it
    # adds: EE Fixpack is counted 19, and only looks existing ones up
    # (IDS_OF_SYMBOL). Summed, the user's real 148-mod EET install comes to
    # 257/256 - and it plays. So an estimate is shown, never warned on; a
    # measured table is.
    states = Tally(SPELL_STATES.label, SPELL_STATES.cap, SPELL_STATES.base,
                   source=SPELL_STATES.source, checked=False,
                   note=("EEex is installed: its extended states lift this" if eeex else
                         "krion64 counts references, not only new ids - an upper "
                         "bound, not checked"))
    if measured.spell_states is not None:
        states.base, states.measured = measured.spell_states, True
        states.source = "measured: ids 0-255 in SPLSTATE.IDS; " + SPELL_STATES.source
    slots = measured.spell_slots
    levels: dict[str, Tally] = {
        level: Tally(f"{'wizard' if level[0] == 'w' else 'priest'} level {level[1]} spells "
                     f"(SPELL.IDS)", SPELL_SLOTS, slots.get(level, 0) if slots is not None
                     else base,
                     source=("measured: slots ADD_SPELL would skip (SPELL.IDS, ADD_SPELL.IDS, "
                             "SPxxLnn.SPL); 50 per level (add_spell.tpa)" if slots is not None
                             else "WeiDU ADD_SPELL: 50 per level (add_spell.tpa); the game's "
                                  "count from Infinity Mod Forge"),
                     note=("" if slots is not None else
                           "krion64 does not count spells added with ADD_SPELL: a level "
                           "can be fuller than this"),
                     measured=slots is not None)
        for level, base in GAME_SPELLS.items()}
    unlevelled = 0
    unknown = set()
    for key, number in chosen:
        components = index.get(key)
        if components is None:
            if (key, number) not in present:
                unknown.add(key)
            continue
        component = components.get(number)
        if not component:
            continue
        here = (key, number) in present          # its additions are in what was measured
        _add(kits, key, number, component.get("k"), skip=here)
        _add(states, key, number, component.get("ss"), skip=here)
        per_level: Mapping = component.get("spLv") or {}
        if isinstance(per_level, dict) and per_level:
            for level, count in per_level.items():
                if level in levels:
                    _add(levels[level], key, number, count, skip=here)
        elif isinstance(component.get("sp"), int) and component["sp"] > 0 \
                and not (here and slots is not None):
            unlevelled += component["sp"]
    report.unknown_mods = sorted(unknown)
    if states.measured and not states.added:
        states.checked = True
        states.note = "EEex is installed: its extended states lift this" if eeex else ""
    if eeex:
        states.cap = 2 ** 32 - 1
    report.tallies = [kits, states] + [t for t in levels.values()
                                       if t.added or t.severity or (t.measured and t.base)]
    report.unlevelled_spells = unlevelled
    return report


def _add(tally: Tally, key: str, number: int, count, skip: bool = False) -> None:
    if skip and tally.measured:
        return
    if isinstance(count, int) and not isinstance(count, bool) and count > 0:
        tally.added += count
        tally.by.append((key, number, count))
