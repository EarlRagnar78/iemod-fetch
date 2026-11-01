"""
Reading a mod's own .tp2 file.

The WeiDU logs record no version (all 796 component lines in the supplied logs
omit it) and `mod_downloads.json` pins nothing, so I previously reported that
this install could not be made reproducible. That was too pessimistic: the
authoritative answer is inside the mod itself. A .tp2 declares

    VERSION ~v4.2~
    AUTHOR ~someone@example.com~
    LANGUAGE ~English~ ~english~ ~english/setup.tra~
    ... GAME_IS ~bg2ee eet~ ...

so after installing we can read the real version, the games the mod itself says
it supports, and its languages - none of which any catalogue has to be trusted
for.

The parsing approach (strip comments first, then match quoted strings; ignore
`GAME_IS` guarded by NOT/! or followed by `? 1 : 0`) follows
scripts/manager/tp2.py in https://github.com/RiwsPy/lcc-docs (MIT,
(c) 2025 RiwsPy). Re-implemented here rather than vendored.
"""
import os
import re
from dataclasses import dataclass, field

from .weidu_lex import _skip, _string, _strip, keyword_ends, languages

_MAX_TP2_BYTES = 8 * 1024 * 1024

_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_COMMENT_LINE = re.compile(r"^//.*|\s//.*", re.MULTILINE)

# A WeiDU string closes on the mark that opened it: `~Use "smart" AI~` holds
# its quotes, and `~~~~~...~~~~~` holds tildes (checked against WeiDU 251's
# --list-components-json). Any of the three is one value: _first() takes it.
_QUOTED = r'(?:~~~~~(.*?)~~~~~|~([^~]*)~|"([^"]*)")'
_AUTHOR = re.compile(rf"\bAUTHOR\s*{_QUOTED}", re.IGNORECASE | re.DOTALL)
_BEGIN = re.compile(rf"\bBEGIN\s*{_QUOTED}", re.IGNORECASE | re.DOTALL)
# A positive game assertion: not negated, and not the `GAME_IS ~x~ ? 1 : 0`
# idiom, which yields a value rather than stating a requirement.
#
# The exclusion must look only at what immediately follows the closing quote.
# Anchoring it with `.*` under DOTALL (as the upstream regex does) lets a single
# `? 1 : 0` anywhere later in the file suppress every match in it.
_GAMES = re.compile(
    r"(?<!\bNOT\s)(?<!\!)(?:GAME_IS|ENGINE_IS|GAME_INCLUDES|GAME_SUPPORTS)"
    rf"\s+{_QUOTED}(?!\s*\?\s*1\s*:\s*0)",
    re.IGNORECASE)

# tp2 game tokens -> the identifiers used elsewhere in this tool
_GAME_ALIASES = {
    "bg1": "BG", "totsc": "BG", "tutu": "Tutu", "tutu_totsc": "Tutu", "bgt": "BGT",
    "soa": "BG2", "tob": "BG2", "bg2": "BG2",
    "bgee": "BGEE", "sod": "SoD", "bg2ee": "BG2EE", "eet": "EET",
    "iwd": "IWD", "how": "IWD", "totlm": "IWD", "iwd2": "IWD2",
    "iwdee": "IWDEE", "pst": "PST", "pstee": "PSTEE",
}


@dataclass
class Tp2Info:
    path: str
    version: str | None = None
    mod_name: str | None = None
    authors: list[str] = field(default_factory=list)
    games: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    # Every LANGUAGE declaration as (display name, language directory/code), in
    # order and WITH duplicates: WeiDU's `#lang` is the position in this list.
    language_decls: list[tuple[str, str]] = field(default_factory=list)

    @property
    def normalised_games(self) -> list[str]:
        """The declared games mapped onto this tool's identifiers."""
        out = []
        for token in self.games:
            mapped = _GAME_ALIASES.get(token.lower())
            if mapped and mapped not in out:
                out.append(mapped)
        return out

    def supports(self, game: str | None) -> bool | None:
        """
        True/False if the mod declares its games, None if it declares none.

        A tp2 that never calls GAME_IS installs anywhere, so silence means
        "no opinion", not "incompatible".
        """
        if not game or not self.normalised_games:
            return None
        return game in self.normalised_games


def strip_comments(content: str) -> str:
    return _COMMENT_LINE.sub("", _COMMENT_BLOCK.sub("", content))


def parse_tp2(content: str, path: str = "<tp2>") -> Tp2Info:
    # comments out, strings whole: a `//` inside ~http://...~ or ~a // b~ is
    # text, so no field runs on past its closing mark (review of #57)
    clean = _strip(content)
    info = Tp2Info(path=path)

    # VERSION as a word of code, followed by its string: never `%VERSION%`
    # or a word inside a string (review of #57)
    for end in keyword_ends(clean, "VERSION"):
        value, _j = _string(clean, _skip(clean, end))
        if value is not None:
            info.version = value.strip() or None
            break
    match = _BEGIN.search(clean)
    if match:
        info.mod_name = _first(match.groups()).strip() or None

    info.authors = [a.strip() for a in map(_found, _AUTHOR.findall(clean)) if a.strip()]

    seen = set()
    for games in map(_found, _GAMES.findall(clean)):
        for raw_token in re.split(r"[\s,]+", games.strip()):
            token = raw_token.strip()
            if token and token.lower() not in seen:
                seen.add(token.lower())
                info.games.append(token)

    # (display name, directory): WeiDU's own reading, bare words included
    # (SCS's `LANGUAGE ~English~ ENGLISH ...`), never a LANGUAGE inside code
    for language in languages(content):
        name = language.name.strip()
        info.language_decls.append((name, language.directory.strip()))
        if name and name not in info.languages:
            info.languages.append(name)
    return info


def read_tp2(path: str) -> Tp2Info | None:
    """Parse a .tp2 from disk. Returns None rather than raising on any problem."""
    try:
        if os.path.getsize(path) > _MAX_TP2_BYTES:
            return None
        with open(path, encoding="utf-8", errors="replace") as fh:
            return parse_tp2(fh.read(), path=path)
    except OSError:
        return None


def read_mod_tp2(mod_dir: str, tp2_file: str) -> Tp2Info | None:
    """Read the tp2 that identifies an installed mod directory."""
    direct = os.path.join(mod_dir, tp2_file)
    if os.path.isfile(direct):
        return read_tp2(direct)
    for dirpath, _dirnames, filenames in os.walk(mod_dir):
        for name in filenames:
            if name.lower() == tp2_file.lower():
                return read_tp2(os.path.join(dirpath, name))
    return None


# ---------------------------------------------------- component constraints
# What WeiDU itself enforces when it installs a component (ADR-0025). Only the
# flag forms are read: REQUIRE_COMPONENT / FORBID_COMPONENT / REQUIRE_PREDICATE
# are legal ONLY as component flags, so finding them inside a component's text
# is unambiguous. A MOD_IS_INSTALLED inside an ACTION_IF is code, not a
# requirement, and is deliberately not read.
_STR = r'(?:~([^~]*)~|"([^"]*)"|%([^%]*)%|([^\s~"%()]+))'
# A component's BEGIN starts its own line, with its name on that line - or
# alone on it, the name on the next (LCA's `BEGIN` / `@800`). Mid-line BEGINs
# are code (`DEFINE_ASSOCIATIVE_ARRAY x BEGIN ~k~ => ~v~ END`, ACTION_IF
# blocks); EET's tp2 has 97 of those and 2 components.
_COMPONENT_START = re.compile(
    r'^[ \t]*BEGIN(?:[ \t]+|[ \t]*\r?\n[ \t]*)'
    r'(?:~[^~\n]*~|"[^"\n]*"|%[^%\n]*%|@-?\d+|\w+(?=[ \t]+DESIGNATED\b))',
    re.IGNORECASE | re.MULTILINE)
_DESIGNATED = re.compile(r"\bDESIGNATED\s+(\d+)", re.IGNORECASE)
# FORCED_SUBCOMPONENT is a SUBCOMPONENT that cannot be skipped: same group.
_SUBCOMPONENT = re.compile(r'(?:\b|(?<=FORCED_))SUBCOMPONENT\s+(~[^~]*~|"[^"]*"|@-?\d+)',
                           re.IGNORECASE)
_REQUIRE_COMPONENT = re.compile(rf"\bREQUIRE_COMPONENT\s+{_STR}\s+{_STR}", re.IGNORECASE)
_FORBID_COMPONENT = re.compile(rf"\bFORBID_COMPONENT\s+{_STR}\s+{_STR}", re.IGNORECASE)
_REQUIRE_PREDICATE = re.compile(r"\bREQUIRE_PREDICATE\b", re.IGNORECASE)
_ARG = r'(?:~[^~]*~|"[^"]*"|%[^%]*%|[^\s~"%()@]+)'
_MSG = r'(?:@-?\d+|~[^~]*~|"[^"]*")'
_NEG = r"(?:NOT\s+|!\s*)"
# The simple, common predicate forms: one test, optionally negated (`NOT x`,
# `!x`, `!(x)`) and optionally in one pair of parentheses. Anything else (OR,
# AND, labels, file checks) is counted as unread rather than half-understood.
_SIMPLE_PREDICATE = re.compile(
    rf"\s*(?P<neg1>{_NEG})?(?P<open>\(\s*)?(?P<neg2>{_NEG})?"
    rf"(?:(?P<kw>GAME_IS|ENGINE_IS|GAME_INCLUDES)\s+(?P<game>{_ARG})"
    rf"|MOD_IS_INSTALLED\s+(?P<tp2>{_ARG})\s+(?P<num>{_ARG}))"
    rf"\s*(?(open)\))\s*{_MSG}",
    re.IGNORECASE)
# A component that refuses in its body rather than its header: DlcMerger's
# `ACTION_IF (NOT GAME_IS ~bgee~) BEGIN ABORT @50`.
_BODY_ABORT = re.compile(
    rf"\bACTION_IF\s*\(?\s*(?P<neg>{_NEG})?GAME_IS\s+(?P<game>{_ARG})\s*\)?\s*"
    r"BEGIN\s+(?:ABORT|FAIL)\b", re.IGNORECASE)

# What ENGINE_IS / GAME_INCLUDES hold on, in the games this tool plans for.
_ENGINE = {"bgee": ["BGEE"], "bg2ee": ["BG2EE", "EET"], "iwdee": ["IWDEE"],
           "pstee": ["PSTEE"]}
_INCLUDES = {"bg1": ["BGEE", "EET", "BG", "Tutu", "BGT"], "totsc": ["BGEE", "EET", "BG", "Tutu", "BGT"],
             "sod": ["BGEE", "EET"], "bg2": ["BG2EE", "EET", "BG2", "BGT"],
             "soa": ["BG2EE", "EET", "BG2", "BGT"], "tob": ["BG2EE", "EET", "BG2", "BGT"],
             "iwd": ["IWDEE", "IWD"], "how": ["IWDEE", "IWD"], "pst": ["PSTEE", "PST"]}


@dataclass
class Tp2Component:
    number: int
    requires: list[tuple[str, int]] = field(default_factory=list)
    forbids: list[tuple[str, int]] = field(default_factory=list)
    games: list[str] = field(default_factory=list)       # only on these (all hold)
    not_games: list[str] = field(default_factory=list)   # never on these
    group: str = ""                                      # SUBCOMPONENT group
    unread: int = 0                                      # predicates not understood
    game_rules: int = 0                                  # game requirements read


def _first(groups) -> str:
    return next((g for g in groups if g is not None), "")


def _found(groups: tuple[str, ...]) -> str:
    """The value of a findall() match of _QUOTED: its groups not taken are ''."""
    return next((g for g in groups if g), "")


def tp2_identity(name: str) -> str:
    """`cdtweaks/SETUP-CDTWEAKS.TP2` -> `cdtweaks`: how rules name a mod."""
    stem = os.path.splitext(os.path.basename(name.replace("\\", "/")))[0]
    if stem.lower().startswith("setup-"):
        stem = stem[6:]
    return re.sub(r"[^a-z0-9]", "", stem.lower())


def _unquote(text: str) -> str:
    text = text.strip()
    return text[1:-1] if text[:1] in "~\"%" and len(text) > 1 else text


def _games(text: str, keyword: str = "GAME_IS") -> list[str]:
    table = {"GAME_IS": None, "ENGINE_IS": _ENGINE, "GAME_INCLUDES": _INCLUDES}[
        keyword.upper()]
    out: list[str] = []
    for token in re.split(r"[\s,]+", _unquote(text).lower()):
        if not token:
            continue
        names = (table.get(token, []) if table is not None
                 else [_GAME_ALIASES[token]] if token in _GAME_ALIASES else [])
        out.extend(n for n in names if n not in out)
    return out


def _require_games(component: Tp2Component, games: list[str]) -> None:
    """Every game requirement must hold, so they intersect."""
    if not games:
        return
    if component.game_rules == 0:
        component.games = list(games)
    else:
        component.games = [g for g in component.games if g in games] or ["(none)"]
    component.game_rules += 1


def _number(text: str) -> int | None:
    text = text.strip()
    return int(text) if text.lstrip("-").isdigit() else None


# WeiDU's inlined file, `<<<<<<<< name` ... `>>>>>>>>`: its text is file content,
# not tp2 code - EET_end.tp2 inlines a .d file that reads `BEGIN ~%file%~`.
_INLINED_FILE = re.compile(r"^[ \t]*<{8}.*?^[ \t]*>{8}", re.MULTILINE | re.DOTALL)


def component_number(chunk: str, previous: int) -> int:
    """
    WeiDU's numbering: DESIGNATED if given, else the previous component's
    number + 1 - not the position in the file. Measured: EEUITweaks' five
    undesignated components after DESIGNATED 5041 are 5042-5046.
    """
    designated = _DESIGNATED.search(chunk)
    return int(designated.group(1)) if designated else previous + 1


def parse_components(content: str) -> list[Tp2Component]:
    """Every component of a tp2 with the constraints WeiDU enforces on it."""
    clean = _INLINED_FILE.sub("", strip_comments(content))
    starts = [m.start() for m in _COMPONENT_START.finditer(clean)]
    components: list[Tp2Component] = []
    previous = -1
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(clean)
        chunk = clean[start:end]
        previous = component_number(chunk, previous)
        component = Tp2Component(number=previous)
        group = _SUBCOMPONENT.search(chunk)
        component.group = group.group(1) if group else ""
        for match in _REQUIRE_COMPONENT.finditer(chunk):
            number = _number(_first(match.groups()[4:]))
            if number is not None:
                component.requires.append(
                    (tp2_identity(_first(match.groups()[:4])), number))
        for match in _FORBID_COMPONENT.finditer(chunk):
            number = _number(_first(match.groups()[4:]))
            if number is not None:
                component.forbids.append(
                    (tp2_identity(_first(match.groups()[:4])), number))
        for flag in _REQUIRE_PREDICATE.finditer(chunk):
            simple = _SIMPLE_PREDICATE.match(chunk, flag.end())
            if simple is None:
                component.unread += 1
                continue
            negated = bool(simple.group("neg1")) != bool(simple.group("neg2"))
            if simple.group("kw"):
                games = _games(simple.group("game"), simple.group("kw"))
                if negated:
                    component.not_games.extend(
                        g for g in games if g not in component.not_games)
                else:
                    _require_games(component, games)
                continue
            number = _number(_unquote(simple.group("num")))
            if number is None:
                component.unread += 1
                continue
            target = (tp2_identity(_unquote(simple.group("tp2"))), number)
            (component.forbids if negated else component.requires).append(target)
        for abort in _BODY_ABORT.finditer(chunk):
            games = _games(abort.group("game"))
            if abort.group("neg"):
                _require_games(component, games)        # aborts unless one of these
            else:
                component.not_games.extend(g for g in games
                                           if g not in component.not_games)
        components.append(component)
    return components
