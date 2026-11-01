"""
Preferred installation language, with fallback (ADR-0024).

A WeiDU log line says `#lang` as an INDEX: the position of a LANGUAGE
declaration in that mod's tp2. Index 1 is Italian in one mod, French in the
next. So "install everything in Italian, else English" cannot be done by
editing a number; each mod's own tp2 has to be read.

The model is BWS-NG's, the community tool that does this best: an ordered
preference list, and the first language a mod offers wins. A language is
recognised from the declaration's second string (the language directory, e.g.
`~italian~`, or a path ending in it) and, failing that, the first word of its
display name, through an alias table. BWS-NG's own table maps "dutch" to
German; this one does not.

Never guessed:
* a mod offering none of the preferred languages keeps the index its log had,
  and is reported with the languages it does offer;
* a mod whose tp2 is not in the staging directory (not fetched yet) keeps its
  index, and is reported.
"""
import os
import re
from dataclasses import dataclass, field
from collections.abc import Sequence

from .errors import ConfigError
from .tp2 import read_mod_tp2

# canonical code -> every spelling seen in tp2 LANGUAGE declarations and in
# what an operator would type. Lower-case, without accents where tp2s vary.
_ALIASES: dict[str, tuple[str, ...]] = {
    "en_US": ("english", "american", "en", "en_us", "en_gb", "en-us", "en-gb",
              "eng", "anglais", "englisch", "inglese", "ingles"),
    "it_IT": ("italian", "italiano", "it", "it_it", "ita"),
    "fr_FR": ("french", "francais", "francaise", "fr", "fr_fr", "fra", "fre"),
    "de_DE": ("german", "deutsch", "de", "de_de", "ger", "deu", "allemand"),
    "es_ES": ("spanish", "espanol", "castellano", "castilian", "es", "es_es",
              "spa"),
    "pl_PL": ("polish", "polski", "pl", "pl_pl", "pol"),
    "ru_RU": ("russian", "russkiy", "ru", "ru_ru", "rus"),
    "pt_BR": ("portuguese", "portugues", "brazilian", "brasileiro", "pt",
              "pt_br", "por"),
    "cs_CZ": ("czech", "cesky", "cestina", "cs", "cs_cz", "cze"),
    "zh_CN": ("chinese", "schinese", "zh", "zh_cn", "chs"),
    "ja_JP": ("japanese", "ja", "ja_jp", "jpn"),
    "ko_KR": ("korean", "ko", "ko_kr", "kor"),
    "uk_UA": ("ukrainian", "uk_ua", "ukr"),
    "nl_NL": ("dutch", "nederlands", "nl", "nl_nl"),
    "hu_HU": ("hungarian", "magyar", "hu", "hu_hu"),
    "tr_TR": ("turkish", "turkce", "tr", "tr_tr"),
    "sv_SE": ("swedish", "svenska", "sv", "sv_se"),
}
# Every language a preference can name: (code, English name), for a UI's list.
LANGUAGES: tuple[tuple[str, str], ...] = tuple(
    (code, names[0].capitalize()) for code, names in _ALIASES.items())
_LOOKUP = {alias: code for code, names in _ALIASES.items() for alias in names}
_FOLD = str.maketrans("àáâãäçèéêëìíîïñòóôõöùúûüčěřšž", "aaaaaceeeeiiiinooooouuuucersz")


def _fold(text: str) -> str:
    return text.strip().lower().translate(_FOLD)


def canonical(text: str) -> str | None:
    """The language a name, code or language path means; None if unknown."""
    folded = _fold(text or "")
    if not folded:
        return None
    last = re.split(r"[\\/]", folded.rstrip("\\/"))[-1]
    if last in _LOOKUP:
        return _LOOKUP[last]
    if folded in _LOOKUP:
        return _LOOKUP[folded]
    # "American English", "Italiano (traduzione di ...)": the language is a
    # word of the name, but only the FIRST word that is a language counts -
    # later words are credits ("traduccion de X" must not read as German).
    for word in re.findall(r"[a-z_]+", last):
        if word in _LOOKUP and len(word) > 2:
            return _LOOKUP[word]
    return None


def parse_preferences(value) -> list[str]:
    """`it_IT, english` -> ['it_IT', 'en_US']; an unknown language is an error."""
    items = value if isinstance(value, (list, tuple)) else str(value).split(",")
    out: list[str] = []
    for item in (str(i).strip() for i in items):
        if not item:
            continue
        code = canonical(item)
        if code is None:
            raise ConfigError(
                f"--language-preference: unknown language {item!r}; use a code "
                f"such as it_IT or a name such as italian")
        if code not in out:
            out.append(code)
    return out


def _declared(decl: tuple[str, str]) -> str | None:
    display, directory = decl
    return canonical(directory) or canonical(display)


def choose_language(decls: Sequence[tuple[str, str]],
                    preferences: Sequence[str]) -> tuple[int, str] | None:
    """(WeiDU language index, code) of the first preferred language offered."""
    offered = [_declared(d) for d in decls]
    for wanted in preferences:
        if wanted in offered:
            return offered.index(wanted), wanted
    return None


@dataclass
class Change:
    mod: str
    old: tuple[int, ...]
    new: int
    code: str


@dataclass
class LanguageReport:
    preferences: list[str]
    changed: list[Change] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)                   # already right
    no_match: list[tuple[str, list[str]]] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [(f"LANGUAGE PREFERENCE: {' > '.join(self.preferences)} "
                 f"(first one each mod offers)")]
        lines.append(f"  {len(self.changed)} mod(s) switched, {len(self.kept)} "
                     f"already in a preferred language")
        for change in self.changed:
            old = ",".join(f"#{n}" for n in change.old)
            lines.append(f"    {change.mod}: {old} -> #{change.new} ({change.code})")
        if self.no_match:
            lines.append(f"  {len(self.no_match)} mod(s) offer none of them, "
                         f"kept as logged:")
            for mod, offered in self.no_match:
                lines.append(f"    {mod}: offers {', '.join(offered) or 'nothing recognisable'}")
        if self.unread:
            lines.append(f"  {len(self.unread)} mod(s) not staged yet, kept as "
                         f"logged - fetch them and plan again: "
                         + ", ".join(self.unread[:12])
                         + (" ..." if len(self.unread) > 12 else ""))
        return "\n".join(lines)


def _find_dir(root: str, name: str) -> str | None:
    """`name` under `root`, matched case-insensitively (Linux staging dirs)."""
    direct = os.path.join(root, name)
    if os.path.isdir(direct):
        return direct
    try:
        for entry in os.listdir(root):
            if entry.lower() == name.lower() and os.path.isdir(os.path.join(root, entry)):
                return os.path.join(root, entry)
    except OSError:
        return None
    return None


def apply_language_preference(plan, mods_dir: str,
                              preferences: Sequence[str]) -> LanguageReport:
    """Rewrite each planned line's `#lang` to the first preferred language."""
    report = LanguageReport(preferences=list(preferences))
    cache: dict[tuple[str, str], list | None] = {}
    for units in plan.logs.values():
        for unit in units:
            if not unit.lines:
                continue
            folder = unit.lines[0][0].replace("\\", "/").split("/")[0]
            ident = (folder.lower(), unit.tp2_file.lower())
            if ident not in cache:
                mod_dir = _find_dir(mods_dir, folder) or _find_dir(mods_dir, unit.folder)
                info = read_mod_tp2(mod_dir, unit.tp2_file) if mod_dir else None
                cache[ident] = info.language_decls if info and info.language_decls else None
            decls = cache[ident]
            name = unit.display
            if decls is None:
                if name not in report.unread:
                    report.unread.append(name)
                continue
            choice = choose_language(decls, preferences)
            if choice is None:
                offered = sorted({c for c in (_declared(d) for d in decls) if c})
                if all(m != name for m, _o in report.no_match):
                    report.no_match.append((name, offered))
                continue
            index, code = choice
            old = tuple(sorted({lang for _p, lang, _c, _m in unit.lines}))
            if old == (index,):
                report.kept.append(name)
                continue
            unit.lines = [(path, index, comp, comment)
                          for path, _lang, comp, comment in unit.lines]
            report.changed.append(Change(name, old, index, code))
    return report
