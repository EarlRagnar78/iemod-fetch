"""
A mod's kind, as each source says it (GUI-AUDIT M5 item 26, ADR-0041).

lcc-docs and BWS-NG classify mods in the same taxonomy - BWS-NG's is lcc-docs'
(ADR-0041) - spelled two ways: lcc-docs' French labels (`Quête`, `PNJ
recrutable`, `Sort et objet`, measured on its db/mods.json, 2026-10-23: 17
labels) and BWS-NG's codes (`quest`, `npc`, `spell`: 15). Both are mapped here
onto one vocabulary, so the selection can filter on one kind and show where
the two sources disagree. krion64 (the Infinity Mod Forge) does not classify
by kind but by install category (`QUEST MODS BG2`, `KIT & CLASS MODS`...):
that is shown beside, never mapped into a kind. The other way round, a kind
that decides a krion64 category places what krion64 does not (`place`, item
27): ADR-0041's measured table.

A label is looked up ignoring case and Unicode composition (`Quête` typed
either way). One this table does not know is kept as it is, so a source that
adds a category shows it rather than losing it - and, not being a kind, it
never makes a disagreement (review of #65).
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from collections.abc import Iterable, Mapping

# The kinds, in the order a mod's own kinds are listed (the selection's left
# list is alphabetical).
KINDS = ("interface", "cosmetic", "portraits and sound", "quest", "recruitable NPC",
         "one-day NPC", "NPC (other)", "kit", "spells and items", "smith and merchant",
         "gameplay", "tactics and scripts", "unofficial patch", "utility", "conversion",
         "party customisation", "GemRB")

LCC_DOCS = {
    "Interface": "interface", "Cosmétique": "cosmetic", "Portrait et son": "portraits and sound",
    "Quête": "quest", "PNJ recrutable": "recruitable NPC", "PNJ One Day": "one-day NPC",
    "PNJ (autre)": "NPC (other)", "Kit": "kit", "Sort et objet": "spells and items",
    "Forgeron et marchand": "smith and merchant", "Gameplay": "gameplay",
    "Script et tactique": "tactics and scripts", "Patch non officiel": "unofficial patch",
    "Utilitaire": "utility", "Conversion": "conversion",
    "Personnalisation du groupe": "party customisation", "GemRB": "GemRB",
}

BWS_NG = {
    "ui": "interface", "cosm": "cosmetic", "portrait": "portraits and sound",
    "quest": "quest", "npc": "recruitable NPC", "npc1d": "one-day NPC",
    "npcx": "NPC (other)", "kit": "kit", "spell": "spells and items", "smith": "smith and merchant",
    "gameplay": "gameplay", "tactic": "tactics and scripts", "patch": "unofficial patch",
    "util": "utility", "conv": "conversion",
}


# What the player reads for a source, by the name it was loaded under: the
# data cache's folders (datasync) and BWS-NG's repository name.
SOURCE_NAMES = {"lcc-docs": "lcc-docs", "bws-ng": "BWS-NG",
                "bigworldsetup-next-generation": "BWS-NG", "krion64": "krion64"}


def _fold(label: str) -> str:
    return unicodedata.normalize("NFC", label).strip().casefold()


def source_name(origin: str) -> str:
    """`bws-ng` is BWS-NG; a source this tool does not know keeps its own name."""
    return SOURCE_NAMES.get(_fold(origin), origin)


def kinds(labels: Iterable[str], table: Mapping[str, str]) -> tuple[str, ...]:
    """A source's labels as kinds, in KINDS' order; an unknown label kept as is."""
    folded = {_fold(label): kind for label, kind in table.items()}
    found = dict.fromkeys(folded.get(_fold(label), label) for label in labels if label)
    order = {kind: i for i, kind in enumerate(KINDS)}
    return tuple(sorted(found, key=lambda kind: (order.get(kind, len(KINDS)), kind)))


def disagree(a: Iterable[str], b: Iterable[str]) -> bool:
    """Two sources that both classify a mod, with no kind in common. A label
    no table knows is not a kind: it cannot disagree."""
    a, b = set(a) & set(KINDS), set(b) & set(KINDS)
    return bool(a and b and not a & b)


# ---------------------------------------------------- an install place by kind
# ADR-0041 decision 2: where krion64 does not place a mod, its kind does - only
# where the kind decides. Measured on 2026-10-23, over the mods krion64 places
# and lcc-docs / BWS-NG classify: the share of each kind in its top krion64
# category. Gameplay (33% / 29%), tactics, patches, utilities, conversions,
# spells and items (52% / 48%), portraits and NPC (other) decide nothing.
PLACES = {
    "interface": ("INTERFACE", "92% / 100%"),
    "cosmetic": ("GRAPHICS", "90% / 91%"),
    "kit": ("KIT & CLASS MODS", "87% / 86%"),
    "recruitable NPC": ("NEW NPC MODS", "84% / 92%"),
    "one-day NPC": ("NEW NPC MODS", "93% / 96%"),
    "smith and merchant": ("ITEM ADDITION MODS", "85% / 89%"),
    # a quest for BG:EE alone goes with BG1's quests, any other with BG2's:
    # 97 of 132 lcc-docs quests (73%; 23 of 27 BG1, 74 of 105 BG2)
    "quest": ("QUEST MODS BG2", "73%"),
}
BG1_QUESTS = "QUEST MODS BG1"


@dataclass(frozen=True)
class KindHint:
    """What the sources say a mod is, for placing it: its kinds, the games
    it lists, and which sources said so."""
    kinds: tuple[str, ...]
    games: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()


def place(hint: KindHint) -> tuple[str | None, str]:
    """
    The krion64 category a mod's kind decides, and why - or None and why not.
    Every kind the sources give must decide, and decide the same place: a
    quest that is also gameplay, or a kit that is also an NPC, has none.
    """
    if not hint.kinds:
        return None, "no source gives its kind"
    places: dict[str, str] = {}
    for kind in hint.kinds:
        if kind not in PLACES:
            return None, f"no place: its kind does not decide one ({kind})"
        category, share = PLACES[kind]
        if kind == "quest" and "BGEE" in hint.games and "BG2EE" not in hint.games:
            category = BG1_QUESTS
        places[category] = f"{kind}, {share}"
    if len(places) > 1:
        return None, ("no place: its kinds point to different places ("
                      + ", ".join(hint.kinds) + ")")
    (category, why), = places.items()
    said = ", ".join(hint.sources)
    return category, f"placed by kind: {why}" + (f" ({said})" if said else "")
