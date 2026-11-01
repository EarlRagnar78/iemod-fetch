"""
Component names, the way WeiDU prints them (M2).

A component tree is useless as a list of numbers. The names live in the mod's
own files: the tp2 says `BEGIN @100`, a LANGUAGE block says which .tra files
hold language N, and the .tra file says `@100 = ~Smarter mages~`. WeiDU
resolves them and prints `Group -> Name: VERSION` for --list-components and in
WeiDU.log. This module does the same resolution, deterministically and without
running WeiDU, so a GUI can show names for a mod that is merely staged.

It is measured against WeiDU 251's own --list-components on real mods
(docs/TESTING.md, tools/tra_benchmark.py); what it cannot resolve - a name
built at install time, a .tra file loaded by code - it reports as unresolved
rather than guessing.

Pure: the caller supplies `read(path) -> Optional[str]` for the .tra files, so
the core never touches the filesystem.
"""
import re
from dataclasses import dataclass, field
from collections.abc import Callable, Sequence

from .languages import choose_language
from .tp2 import _COMPONENT_START, _INLINED_FILE, _SUBCOMPONENT, component_number
from .weidu_lex import (Language, _skip, _string, _strings_after, _strip, _token,  # noqa: F401
                        languages)

Reader = Callable[[str], str | None]


# --------------------------------------------------------------- .tra files
_REF = re.compile(r"@(-?\d+)\s*=\s*")
_BARE = re.compile(r"[^\s~\"%@\[\]/]+")


def parse_tra(text: str) -> dict[int, str]:
    """`@N = ~text~ [~female text~] [[SOUND]]`, in order; later entries win."""
    out: dict[int, str] = {}
    i, n = 0, len(text)
    while i < n:
        i = _skip(text, i)
        match = _REF.match(text, i)
        if not match:
            # Not an entry: resynchronise on the next @, as WeiDU's lexer would
            # fail here; better one lost entry than a whole file.
            j = text.find("@", i + 1)
            if j < 0:
                break
            i = j
            continue
        value, j = _string(text, match.end())
        if value is None:
            # WeiDU also takes a bare word: thepicturestandard's `@30=BG1NPC`.
            bare = _BARE.match(text, match.end())
            if not bare:
                i = match.end()
                continue
            value, j = bare.group(0), bare.end()
        out[int(match.group(1))] = value
        j = _skip(text, j)
        female, k = _string(text, j)           # an optional second (female) string
        if female is not None:
            j = k
        j = _skip(text, j)
        if j < n and text[j] == "[":            # an optional [SOUND]
            close = text.find("]", j)
            j = n if close < 0 else close + 1
        i = j
    return out


# ---------------------------------------------------------- the tp2 itself
@dataclass
class ComponentName:
    """
    One component as WeiDU describes it. The field names follow WeiDU's own
    `--list-components-json`: `subgroup` is the SUBCOMPONENT, `groups` the
    GROUPs, `labels` the LABELs, `forced` a FORCED_SUBCOMPONENT.
    """
    number: int
    name: str                    # what WeiDU prints: "Subgroup -> Name: VERSION"
    title: str = ""              # the component's own name
    subgroup: str = ""           # its SUBCOMPONENT, resolved
    resolved: bool = True        # False when a reference had no text
    groups: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    forced: bool = False
    deprecated: bool = False     # WeiDU hides it from every list


_VERSION = re.compile(r"^[ \t]*VERSION\s+", re.IGNORECASE | re.MULTILINE)
_BACKUP = re.compile(r"^[ \t]*BACKUP\s+", re.IGNORECASE | re.MULTILINE)


def _version(clean: str) -> str:
    match = _VERSION.search(clean)
    if not match:
        return ""
    value, _j = _string(clean, match.end())
    return value if value is not None else ""


def mod_folder(tp2: str) -> str:
    """
    What WeiDU calls %MOD_FOLDER%: the directory of the BACKUP directive, not
    the directory the tp2 sits in. LCA keeps `EE/LCA.tp2` with `BACKUP
    ~LCA/backup~`, so its `%MOD_FOLDER%/tra/...` points into LCA/ - checked
    against WeiDU 251.
    """
    clean = _strip(tp2)
    match = _BACKUP.search(clean)
    if not match:
        return ""
    value, _j = _string(clean, match.end())
    if not value:
        return ""
    return value.replace("\\", "/").rstrip("/").rpartition("/")[0]


def _variables(path: str, folder: str, language: Language, weidu_os: str) -> str:
    """The variables WeiDU defines before it reads a LANGUAGE's .tra files."""
    for name, value in (("MOD_FOLDER", folder), ("LANGUAGE", language.directory),
                        ("WEIDU_OS", weidu_os)):
        path = re.sub(f"%{name}%", value.replace("\\", "/"), path, flags=re.IGNORECASE)
    return path


def _text(token: str, strings: dict[int, str]) -> tuple[str, bool]:
    token = token.strip()
    if token.startswith("@"):
        try:
            number = int(token[1:])
        except ValueError:
            return token, False
        if number in strings:
            return strings[number], True
        return f"UNDEFINED STRING:   @{number}", False     # what WeiDU prints
    value, _j = _string(token, 0)
    return (value, True) if value is not None else (token, False)


def _argument(chunk: str, at: int) -> str:
    """The string or @reference that follows position `at`."""
    i = _skip(chunk, at)
    if chunk.startswith("@", i):
        match = re.match(r"@-?\d+", chunk[i:])
        return match.group(0) if match else ""
    value, j = _string(chunk, i)
    return chunk[i:j] if value is not None else ""


def component_names(tp2: str, language_index: int, read: Reader,
                    folder: str | None = None, weidu_os: str = "win32") -> list[ComponentName]:
    """
    Every component's name in language `language_index`, as WeiDU prints it.

    `read(path)` returns a .tra file's text (paths as the tp2 writes them,
    after %MOD_FOLDER%, %LANGUAGE% and %WEIDU_OS%), or None when it does not
    exist. `weidu_os` is what WeiDU calls the platform: win32, osx or unix;
    a few mods keep per-platform .tra files. `folder` overrides %MOD_FOLDER%,
    which otherwise comes from the tp2's BACKUP directive, as WeiDU does.
    """
    clean = _strip(tp2)
    if folder is None:
        folder = mod_folder(tp2)
    langs = languages(tp2)
    strings: dict[int, str] = {}
    if 0 <= language_index < len(langs):
        language = langs[language_index]
        for path in language.tra_files:
            text = read(_variables(path, folder, language, weidu_os))
            if text is not None:
                strings.update(parse_tra(text))
    version = _version(clean)
    body = _INLINED_FILE.sub("", clean)
    starts = list(_COMPONENT_START.finditer(body))
    out = []
    number = -1
    for position, match in enumerate(starts):
        end = starts[position + 1].start() if position + 1 < len(starts) else len(body)
        chunk = body[match.start():end]
        number = component_number(chunk, number)
        title, ok = _text(_argument(chunk, chunk.upper().find("BEGIN") + 5), strings)
        subgroup, sub_ok = "", True
        sub = _SUBCOMPONENT.search(chunk)
        if sub:
            subgroup, sub_ok = _text(sub.group(1), strings)
        name = f"{subgroup} -> {title}" if sub else title
        # WeiDU prints a component on one line: a line break in its text is a space.
        name = _one_line(name)
        if version:
            name = f"{name}: {version}"
        flags = _flags(chunk)
        groups = [_joined(_text(g, strings)[0]) for g in _GROUP.findall(flags)]
        labels = [_text(label, strings)[0] for label in _LABEL.findall(flags)]
        out.append(ComponentName(
            number, name, _joined(title), _joined(subgroup), ok and sub_ok,
            groups=groups, labels=labels,
            forced=_FORCED.search(flags) is not None,
            deprecated=_DEPRECATED.search(flags) is not None))
    return out


def _one_line(text: str) -> str:
    """As --list-components and WeiDU.log print it: a line break is a space."""
    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def _joined(text: str) -> str:
    """As --list-components-json gives it: line breaks are dropped."""
    return text.replace("\r", "").replace("\n", "")


# Component flags: between BEGIN and the first action. LABEL, GROUP and
# DEPRECATED are legal only there, so the flags end at the first line that
# starts with something else (an action, a patch, ALWAYS-like code).
_FLAG_WORDS = ("BEGIN", "DESIGNATED", "SUBCOMPONENT", "FORCED_SUBCOMPONENT", "GROUP",
               "LABEL", "DEPRECATED", "REQUIRE_COMPONENT", "FORBID_COMPONENT",
               "REQUIRE_PREDICATE", "REQUIRE_FILE", "INSTALL_BY_DEFAULT", "NO_LOG_RECORD",
               "METADATA", "@", "~", '"')
# A REQUIRE_PREDICATE value can run over lines without parentheses: a line that
# starts like a predicate term continues it.
_PREDICATE_WORDS = frozenset(("OR", "AND", "NOT", "GAME_IS", "GAME_INCLUDES", "ENGINE_IS",
                              "MOD_IS_INSTALLED", "FILE_EXISTS", "FILE_EXISTS_IN_GAME",
                              "VARIABLE_IS_SET", "IS_AN_INT", "BIT_IS_SET"))
_GROUP = re.compile(r"\bGROUP\s+(~[^~]*~|\"[^\"]*\"|@-?\d+)")
_LABEL = re.compile(r"\bLABEL\s+(~[^~]*~|\"[^\"]*\"|[^\s~\"]+)")
_DEPRECATED = re.compile(r"\bDEPRECATED\b")
_FORCED = re.compile(r"\bFORCED_SUBCOMPONENT\b")


def _flags(chunk: str) -> str:
    """The component's flag section: BEGIN up to its first action."""
    lines: list[str] = []
    for n, line in enumerate(chunk.split("\n")):
        word = line.strip().split(None, 1)[0].upper() if line.strip() else ""
        if n and word and not any(word.startswith(w) for w in _FLAG_WORDS) \
                and not _predicate_term(word) and not _lines_continue(lines):
            break
        lines.append(line)
    return "\n".join(lines)


def _predicate_term(word: str) -> bool:
    return word in _PREDICATE_WORDS or word[0] in "!(%" or word[0].isdigit()


def _lines_continue(lines: list[str]) -> bool:
    """True while a flag's argument is still open: an unclosed ~ string or (."""
    text = "\n".join(lines)
    return text.count("~") % 2 == 1 or text.count("(") > text.count(")")


def describe(tp2: str, read: Reader, preferences: Sequence[str] = (),
             weidu_os: str = "win32") -> dict:
    """
    A mod's languages and its components' names, for a selection screen.

    The language is the first of `preferences` (codes such as it_IT) the mod
    offers, else its first, as WeiDU's own default. `components` keeps WeiDU's
    order; `resolved` is False where WeiDU too would print UNDEFINED STRING.
    """
    langs = languages(tp2)
    chosen = choose_language([(lang.name, lang.directory) for lang in langs], preferences)
    index = chosen[0] if chosen else 0
    names = component_names(tp2, index, read, weidu_os=weidu_os)
    return {
        "version": _version(_strip(tp2)) or None,
        "language": index if langs else None,
        "languages": [{"index": k, "name": lang.name, "directory": lang.directory}
                      for k, lang in enumerate(langs)],
        "components": [{"number": c.number, "name": c.name, "title": c.title,
                        "subgroup": c.subgroup or None, "groups": c.groups,
                        "labels": c.labels, "forced": c.forced,
                        "deprecated": c.deprecated, "resolved": c.resolved}
                       for c in names],
    }
