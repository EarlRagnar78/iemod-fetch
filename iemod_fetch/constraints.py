"""
A staged mod's own install-time constraints, as rules (ADR-0025).

Community rule sets restate what a mod's tp2 already says - BWS-NG copies SCS's
`FORBID_COMPONENT ~setup-cdtweaks.tp2~ 2370` by hand into
`stratagems(4100):cdtweaks(2370,...)`. Once the mod is staged, the tp2 itself is
the better source: it travels with the version actually downloaded, and WeiDU
enforces it. Read here:

* `REQUIRE_COMPONENT` / `MOD_IS_INSTALLED`: the required component must be
  installed FIRST - an order rule, as the Infinity Orchestrator reads it - and
  must be present at all - a dependency;
* `FORBID_COMPONENT` / `NOT MOD_IS_INSTALLED`: the declaring component first,
  since WeiDU checks a FORBID only backwards, plus a warning that coexistence
  is not stated; a MUTUAL FORBID is an incompatibility;
* EET's merge check, from the staged EET mod: the BG:EE mods it can import
  (`tbl/compatibility.tbl`) and the wrong options it fails on. A BG:EE mod not
  on that list makes the EET core refuse the merge - and with it every mod
  that needs EET.
"""
import os
import re
from dataclasses import dataclass, field
from collections.abc import Iterable

from .naming import normalize_key
from .rules import DEPENDS, INCOMPATIBLE, ORDER, ModSpec, Rule
from .tp2 import Tp2Component, parse_components, tp2_identity

ORIGIN = "mod tp2"
_MAX_TP2_BYTES = 8 * 1024 * 1024


@dataclass
class EetMergeRules:
    allowed: set[str] = field(default_factory=set)          # BG:EE mods EET imports
    wrong_components: set[tuple[str, int]] = field(default_factory=set)
    source: str = ""


@dataclass
class ModConstraints:
    by_mod: dict[str, dict[int, Tp2Component]] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)        # no staged tp2
    unread: int = 0                                         # predicates not understood
    eet: EetMergeRules | None = None

    def summary(self) -> str:
        count = sum(len(c) for c in self.by_mod.values())
        text = (f"{len(self.by_mod)} mod(s), {count} component(s) read from their "
                f"own tp2; {self.unread} compound predicate(s) not evaluated")
        if self.missing:
            text += f"; {len(self.missing)} mod(s) not staged"
        if self.eet:
            text += f"; EET imports {len(self.eet.allowed)} BG:EE mod(s)"
        return text


def _find(root: str, name: str) -> str | None:
    """A file or directory under `root`, matched case-insensitively."""
    direct = os.path.join(root, name)
    if os.path.exists(direct):
        return direct
    try:
        for entry in os.listdir(root):
            if entry.lower() == name.lower():
                return os.path.join(root, entry)
    except OSError:
        return None
    return None


def _find_tp2(mod_dir: str, tp2_file: str) -> str | None:
    for dirpath, _dirnames, filenames in os.walk(mod_dir):
        for name in filenames:
            if name.lower() == tp2_file.lower():
                return os.path.join(dirpath, name)
    return None


def _read(path: str) -> str | None:
    try:
        if os.path.getsize(path) > _MAX_TP2_BYTES:
            return None
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def load_constraints(mods_dir: str,
                     mods: Iterable[tuple[str, str, str]]) -> ModConstraints:
    """`mods` is (key, folder, tp2 file) per planned mod; read each staged tp2."""
    result = ModConstraints()
    for key, folder, tp2_file in mods:
        if key in result.by_mod or key in result.missing:
            continue
        mod_dir = _find(mods_dir, folder)
        path = _find_tp2(mod_dir, tp2_file) if mod_dir else None
        text = _read(path) if path else None
        if text is None:
            result.missing.append(key)
            continue
        components = parse_components(text)
        result.by_mod[key] = {c.number: c for c in components}
        result.unread += sum(c.unread for c in components)
        if key == "eet" and path:
            result.eet = eet_merge_rules(os.path.dirname(path))
    return result


def tp2_rules(constraints: ModConstraints) -> list[Rule]:
    """
    The staged mods' own constraints as rules.

    A REQUIRE is an order rule (the required component first) plus a
    dependency. A FORBID is an ORDER rule - declaring component first - because
    WeiDU checks it only against what is already installed, and that is what
    one-sided FORBIDs mean in practice (EET: "EET should be installed BEFORE
    BP-BGT Worldmap"; Ascension forbids SCS #5900, which belongs after it).
    Only a MUTUAL FORBID - each side refusing the other - is an
    incompatibility: no order satisfies it.
    """
    forbidding = {(mod, number, other, refused)
                  for mod, components in constraints.by_mod.items()
                  for number, component in components.items()
                  for other, refused in component.forbids}
    rules: list[Rule] = []
    for mod, components in constraints.by_mod.items():
        for number, component in components.items():
            me = ModSpec(mod, mod, frozenset({number}))
            for other, wanted in component.requires:
                them = ModSpec(other, other, frozenset({wanted}))
                note = (f"{mod} #{number}'s own tp2 requires {other} #{wanted} "
                        f"to be installed first")
                rules.append(Rule(ORDER, them, (me,), severity="error",
                                  direction="before", message=note, origin=ORIGIN,
                                  evidence="mechanism-verified"))
                rules.append(Rule(DEPENDS, me, (them,), severity="error",
                                  message=note, origin=ORIGIN,
                                  evidence="mechanism-verified"))
            for other, refused in component.forbids:
                them = ModSpec(other, other, frozenset({refused}))
                if (other, refused, mod, number) in forbidding:
                    if (other, refused) < (mod, number):
                        continue                    # one rule per mutual pair
                    rules.append(Rule(
                        INCOMPATIBLE, me, (them,), severity="error", origin=ORIGIN,
                        evidence="mechanism-verified",
                        message=(f"{mod} #{number} and {other} #{refused} each "
                                 f"FORBID the other in their own tp2s: no order "
                                 f"installs both")))
                    continue
                rules.append(Rule(
                    ORDER, me, (them,), severity="error", direction="before",
                    origin=ORIGIN, evidence="mechanism-verified",
                    message=(f"{mod} #{number}'s own tp2 refuses to install after "
                             f"{other} #{refused} (FORBID): it goes first")))
                # One-sided FORBIDs mean either thing in practice: EET's means
                # "install me first", SCS #4100's against Tweaks #2370 means
                # "never together" (BWS-NG classes that pair incompatible). The
                # tp2 cannot tell them apart, so coexistence is a WARNING -
                # reported, never resolved automatically; a community rule
                # graded error is what decides.
                rules.append(Rule(
                    INCOMPATIBLE, me, (them,), severity="warning", origin=ORIGIN,
                    evidence="mechanism-verified",
                    message=(f"{mod} #{number} FORBIDs {other} #{refused}: WeiDU "
                             f"accepts {mod} first, but its author did not say the "
                             f"two coexist - check the community rules")))
    return rules


# EET's own check, EET/EET.tp2: each BG:EE log line must name a mod listed in
# tbl/compatibility.tbl, and two options are failed outright:
#   COUNT_REGEXP_INSTANCES "^~SOA[/\\]SETUP-SOA\.TP2~ #[0-9]+ #1 " num_matches
#   PATCH_IF (num_matches > 0) BEGIN PATCH_FAIL @900006 ...
_WRONG = re.compile(
    r'COUNT_REGEXP_INSTANCES\s+"\^~[^"]*?([\w-]+)\\\.TP2~ #\[0-9\]\+ #(\d+)', re.IGNORECASE)


def eet_merge_rules(eet_dir: str) -> EetMergeRules | None:
    """EET's merge check, read from a staged EET mod directory; None if absent."""
    table = _find(os.path.join(eet_dir, "tbl"), "compatibility.tbl") \
        if os.path.isdir(os.path.join(eet_dir, "tbl")) else None
    text = _read(table) if table else None
    if text is None:
        return None
    rules = EetMergeRules(source=table or "")
    for line in text.splitlines():
        first = line.split("//")[0].split()
        if first:
            rules.allowed.add(normalize_key(first[0]))
    tp2 = _find_tp2(eet_dir, "EET.tp2")
    body = _read(tp2) if tp2 else None
    if body:
        matches = list(_WRONG.finditer(body))
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            if "PATCH_FAIL" in body[match.end():end].upper():
                rules.wrong_components.add(
                    (tp2_identity(match.group(1)), int(match.group(2))))
    return rules
