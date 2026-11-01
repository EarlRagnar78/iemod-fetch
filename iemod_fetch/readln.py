"""
The questions a mod will ask while it installs, read before installing
(GUI-AUDIT M8 item 48, ADR-0049).

WeiDU asks with `ACTION_READLN var` (`PATCH_READLN` inside a patch): it
reads one line from the player into `var`. The question itself is whatever
the mod printed just before: `PRINT @n`, a string of the language's .tra (25
of the 45 reached in the census), or a fixed text (17), or a variable set
elsewhere (3, unknown). A prompt is keyed by the .tra reference, which does
not change with the language or with the lines mod_installer shows around it
(ADR-0045's window), else by its text, and shown in the chosen language.
A READLN after FAIL or ABORT in its block is never asked, and not reported.

Read for each component of a tp2: the READLNs in its own body, in the
functions and macros it launches, and in the files it includes, followed
recursively. A READLN inside `ACTION_IF`/`PATCH_IF`/`ACTION_MATCH` may not be
asked (`conditional`); one inside a loop may be asked again until the answer
is valid (`repeats`). One in the tp2's `ALWAYS` block is asked before every
component (`always`).

What is not seen, and said so (`unread`): an include whose path is built from
variables other than %MOD_FOLDER%, %LANGUAGE% and %WEIDU_OS%, or not found.
Not said: a function or macro defined in no file of the mod - WeiDU's own
library, which asks nothing - and a question printed by an external program. The reading is lexical, as tp2.py's and tra.py's are; nothing runs.
Pure: the files come in as text, nothing is opened here.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from .tp2 import _COMPONENT_START, _INLINED_FILE, component_number
from .tra import _text, _variables, mod_folder, parse_tra
from .weidu_lex import _skip, _string, _strip, languages

_BARE = re.compile(r"[^\s~\"%/()=<>!&|,;]+")
_DEFINE = {"DEFINE_ACTION_FUNCTION", "DEFINE_PATCH_FUNCTION",
           "DEFINE_ACTION_MACRO", "DEFINE_PATCH_MACRO", "DEFINE_DIMORPHIC_FUNCTION"}
_LAUNCH = {"LAF", "LPF", "LAM", "LPM", "LAUNCH_ACTION_FUNCTION", "LAUNCH_PATCH_FUNCTION",
           "LAUNCH_ACTION_MACRO", "LAUNCH_PATCH_MACRO"}
_INCLUDE = {"INCLUDE", "ACTION_INCLUDE", "PATCH_INCLUDE", "REINCLUDE", "ACTION_REINCLUDE",
            "PATCH_REINCLUDE"}
_READLN = {"ACTION_READLN", "PATCH_READLN"}
_PRINT = {"PRINT", "PATCH_PRINT"}
# words whose BEGIN opens a conditional or a repeating block
_CONDITION = {"ACTION_IF", "PATCH_IF", "ELSE"}
_LOOP = {"WHILE", "OUTER_WHILE", "PATCH_WHILE", "FOR", "OUTER_FOR", "PATCH_FOR",
         "ACTION_FOR_EACH", "PATCH_FOR_EACH", "ACTION_PHP_EACH", "PHP_EACH",
         "ACTION_BASH_FOR", "PATCH_BASH_FOR"}
# Forms closed by an END with no BEGIN of their own: `LAF name ... END`,
# `ACTION_MATCH x WITH ... DEFAULT ... END`, `ACTION_TRY ... WITH ... END`.
# Counting only BEGIN/END cuts a function body at its first LAF (review of #101).
_END_OPENERS = {"LAF", "LPF", "LAUNCH_ACTION_FUNCTION", "LAUNCH_PATCH_FUNCTION"}
_BRANCHING = {"ACTION_MATCH", "PATCH_MATCH", "ACTION_TRY", "PATCH_TRY"}   # conditional
_OPENERS = {"BEGIN"} | _END_OPENERS | _BRANCHING
_FAIL = {"FAIL", "PATCH_FAIL", "ABORT", "PATCH_ABORT"}
_WHOLE_VARIABLE = re.compile(r"\s*%[^%\s]+%\s*")
_CONSTANT = re.compile(r"\bOUTER_(?:TEXT_)?SPRINT\s+~?(\w+)~?\s+~([^~\n]*)~", re.IGNORECASE)
_COMPONENT_NUMBER = re.compile(r"%COMPONENT_NUMBER%", re.IGNORECASE)
# a file written inside another: `<<<<<<<< name` ... `>>>>>>>>` (WeiDU's inlined files)
_INLINED = re.compile(r"^[ \t]*<{8}[ \t]*(?P<name>\S+)[^\n]*\n(?P<body>.*?)^[ \t]*>{8}",
                      re.MULTILINE | re.DOTALL)


@dataclass
class Prompt:
    """One READLN a component reaches."""
    ref: str                   # "@123": the printed question's .tra string, else ""
    text: str                  # the question in the chosen language ("" unknown)
    file: str                  # where the READLN is (the mod's relative path)
    line: int
    via: str = ""              # "" in the component; else "function NAME" / "include PATH"
    conditional: bool = False  # inside an IF/MATCH: may not be asked
    repeats: bool = False      # inside a loop: asked again until valid
    variable: str = ""         # the variable the answer goes to
    component: int | None = None   # the component that reaches it
    raw: str = ""              # the text as WeiDU prints it: its lines and spaces (ADR-0057)

    @property
    def keyed(self) -> bool:
        """The question is known: a .tra reference or a fixed text."""
        return bool(self.ref or self.text)

    @property
    def key(self) -> str:
        """What an answer is stored under: the .tra reference, else the text,
        else (an unknown question) where it is asked and by which component -
        never empty. Two calls of one asking function from one component
        still share it (LCA's xa_determine_quantity asks what its caller
        passes), so an unknown question is never answered from a stored
        answer: it is asked (ADR-0049)."""
        return (self.ref or self.text
                or f"{self.file}:{self.line}:{self.variable}#{self.component}")


@dataclass
class ModPrompts:
    tp2: str
    # by component: the questions installing it may ask, in order - its
    # ALWAYS block's first (`via` "always"), WeiDU runs that before each one
    components: dict[int, list[Prompt]] = field(default_factory=dict)
    unread: list[str] = field(default_factory=list)   # what could not be followed
    # by component: what its own reading could not follow (its ALWAYS block's
    # included) - a component that asks nothing found may still ask there
    unread_by: dict[int, list[str]] = field(default_factory=dict)

    def of(self, number: int) -> list[Prompt]:
        """The questions installing component `number` may ask, in order."""
        return self.components.get(number, [])

    def unread_of(self, number: int) -> list[str]:
        """What reading component `number` could not follow."""
        return self.unread_by.get(number, [])


@dataclass
class _Token:
    word: str          # a bare word as written (WeiDU's keywords are
                       # case-sensitive: `SET end = 5` is a variable), "" for a string
    value: str         # the word as written, or the string's content
    raw: str           # the string with its marks, as written ("@12" for a ref)
    at: int


def _tokens(clean: str) -> list[_Token]:
    out: list[_Token] = []
    i, n = 0, len(clean)
    while True:
        i = _skip(clean, i)
        if i >= n:
            return out
        value, j = _string(clean, i)
        if value is not None:
            out.append(_Token("", value, clean[i:j], i))
            i = j
            continue
        bare = _BARE.match(clean, i)
        if not bare:
            i += 1
            continue
        word = bare.group(0)
        out.append(_Token(word, word, word, i))
        i = bare.end()


def _block_end(tokens: list[_Token], start: int) -> int:
    """The index just past the END matching the BEGIN at or after `start`."""
    depth = 0
    for k in range(start, len(tokens)):
        if tokens[k].word in _OPENERS:
            depth += 1
        elif tokens[k].word == "END":
            depth -= 1
            if depth == 0:
                return k + 1
    return len(tokens)


def strip_keeping_lines(content: str) -> str:
    """Comments out, strings kept, as weidu_lex._strip - but a /* ... */ keeps
    its line breaks, so a line counted in the result is the file's line
    (review of #101: SCS's install_sfo.tpa was reported 3 to 61 lines early)."""
    out, i, n = [], 0, len(content)
    while i < n:
        c = content[i]
        if content.startswith("//", i):
            j = content.find("\n", i)
            i = n if j < 0 else j
            continue
        if content.startswith("/*", i):
            j = content.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(" " + "\n" * content.count("\n", i, j))
            i = j
            continue
        if c in "~\"%":
            value, j = _string(content, i)
            if value is not None:
                out.append(content[i:j])
                i = j
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _line(text: str, at: int) -> int:
    return text.count("\n", 0, at) + 1


@dataclass
class _Source:
    path: str
    text: str
    tokens: list[_Token]


class _Reader:
    def __init__(self, files: Mapping[str, str], strings: dict[int, str],
                 folder: str, language, weidu_os: str, constants: dict[str, str] | None = None,
                 prefix: str = ""):
        self.constants = constants or {}
        self.prefix = prefix
        self.files = {k.replace("\\", "/").lower(): (k, v) for k, v in files.items()}
        for _path, text in list(self.files.values()):
            for m in _INLINED.finditer(text):
                name = m.group("name").replace("\\", "/").lower().lstrip("./")
                self.files.setdefault(name, (m.group("name"), m.group("body")))
        self.strings = strings
        self.folder, self.language, self.weidu_os = folder, language, weidu_os
        self.unread: list[str] = []
        self.sources: dict[str, _Source] = {}
        self.functions: dict[str, tuple[_Source, int, int]] = {}
        # sorted: the same definitions on every platform (os.walk order is not)
        for key in sorted(self.files):
            if key.endswith((".tpa", ".tph", ".tpp", ".tpc", ".tp2")):
                self._define(key)

    def source(self, key: str) -> _Source | None:
        if key not in self.files:
            return None
        if key not in self.sources:
            path, text = self.files[key]
            clean = _INLINED_FILE.sub(lambda m: "\n" * m.group(0).count("\n"),
                                      strip_keeping_lines(text))
            self.sources[key] = _Source(path, clean, _tokens(clean))
        return self.sources[key]

    def _define(self, key: str) -> None:
        src = self.source(key)
        if src is None:
            return
        toks = src.tokens
        for k, tok in enumerate(toks):
            if tok.word in _DEFINE and k + 1 < len(toks):
                name = toks[k + 1].value.upper()
                begin = next((m for m in range(k + 2, len(toks)) if toks[m].word == "BEGIN"),
                             None)
                if begin is not None:
                    self.functions.setdefault(name, (src, begin, _block_end(toks, begin)))

    def include_key(self, raw: str, number: int | None) -> str | None:
        path = _variables(raw, self.folder, self.language, self.weidu_os)
        if number is not None:
            path = _COMPONENT_NUMBER.sub(str(number), path)
        for name, value in self.constants.items():
            path = re.sub(f"%{re.escape(name)}%", value, path, flags=re.IGNORECASE)
        if "%" in path:
            self.unread.append(f"include {raw} (a path built from variables)")
            return None
        key = path.replace("\\", "/").lower().lstrip("./")
        # paths are the game folder's; a tp2 kept deeper (a checkout) is read
        # with the folder its mod sits in put first
        if key not in self.files and self.prefix and (self.prefix + key) in self.files:
            return self.prefix + key
        return key

    def text_of(self, tok: _Token | None) -> tuple[str, str]:
        if tok is None:
            return "", ""
        if tok.raw.startswith("@"):
            text, ok = _text(tok.raw, self.strings)
            return tok.raw, text if ok else ""
        if tok.raw.startswith("%") or _WHOLE_VARIABLE.fullmatch(tok.value):
            return "", ""          # `PRINT ~%xa_prompt%~`: the text is set elsewhere
        return "", tok.value

    def walk(self, src: _Source, start: int, stop: int, via: str, seen: frozenset[str],
             number: int | None, cond: bool = False, loop: bool = False) -> list[Prompt]:
        """The READLNs reached from tokens[start:stop] of `src`, in order."""
        toks = src.tokens
        out: list[Prompt] = []
        last_print: _Token | None = None
        # one frame per open block: (conditional, repeats, dead after a FAIL, kind);
        # kind "try" is a TRY's body, which its WITH closes: the handlers run
        # because the body failed, so a FAIL there leaves them alive
        stack: list[tuple[bool, bool, bool, str]] = [(cond, loop, False, "")]
        pending: str | None = None
        previous = ""
        k = start
        while k < stop:
            tok = toks[k]
            word = tok.word
            c, lp, dead, kind = stack[-1]
            if word in _DEFINE:
                # a definition asks nothing until it is launched
                begin = next((m for m in range(k + 2, stop) if toks[m].word == "BEGIN"), stop)
                k = _block_end(toks, begin)
                previous = "END"
                continue
            if word == "ELSE" and previous != "END":
                pass                                    # READ_LONG 0 x ELSE 0: a default value
            elif word in _CONDITION:
                pending = "cond"
            elif word in _LOOP:
                pending = "loop"
            elif word == "BEGIN":
                stack.append((c or pending == "cond", lp or pending == "loop", dead, ""))
                pending = None
            elif word in ("ACTION_TRY", "PATCH_TRY"):
                stack.append((c, lp, dead, "try"))      # the body, until WITH
            elif word in _BRANCHING:
                stack.append((True, lp, dead, ""))      # MATCH ... END
            elif word == "WITH" and kind == "try":
                parent_dead = stack[-2][2] if len(stack) > 1 else False
                stack[-1] = (True, lp, parent_dead, "")  # the handlers, until END
            elif word == "END":
                if len(stack) > 1:
                    stack.pop()
            elif word in _FAIL:
                stack[-1] = (c, lp, True, kind)         # what follows is never run
            elif word in _PRINT and k + 1 < stop:
                last_print = toks[k + 1]
            elif word in _READLN and k + 1 < stop:
                if not dead:
                    ref, text = self.text_of(last_print)
                    out.append(Prompt(ref, " ".join(text.split()), src.path,
                                      _line(src.text, tok.at), via, c, lp, toks[k + 1].value,
                                      raw=text))
                last_print = None
            elif word in _LAUNCH and k + 1 < stop:
                name = toks[k + 1].value.upper()
                if word in _END_OPENERS:
                    stack.append((c, lp, dead, ""))     # LAF name ... END
                if not dead and name not in seen and name in self.functions:
                    fsrc, b, e = self.functions[name]
                    out += self.walk(fsrc, b, e, via or f"function {toks[k + 1].value}",
                                     seen | {name}, number, c, lp)
                # a name the mod does not define is WeiDU's own library
                # (HANDLE_CHARSETS, ADD_CRE_EFFECT, ...), which asks nothing
                k += 2
                previous = word
                continue
            elif word in _INCLUDE:
                m = k + 1
                while m < stop and toks[m].word == "":
                    raw = toks[m].raw
                    key = (None if raw.startswith("%") else self.include_key(toks[m].value, number))
                    if raw.startswith("%"):
                        self.unread.append(f"include {raw} (a path built from variables)")
                    if key is not None and key not in seen and not dead:
                        inc = self.source(key)
                        if inc is None and not c:
                            # inside an IF it is expected (FILE_EXISTS guards it)
                            self.unread.append(f"include {key} (not found)")
                        elif inc is not None:
                            out += self.walk(inc, 0, len(inc.tokens),
                                             via or f"include {toks[m].value}",
                                             seen | {key}, number, c, lp)
                    m += 1
                k = m
                previous = ""
                continue
            previous = word
            k += 1
        return out


def scan(tp2_path: str, files: Mapping[str, str], language_index: int = 0,
         weidu_os: str = "win32") -> ModPrompts:
    """
    Every question each component of `tp2_path` may ask. `files` maps each
    file of the mod - paths as WeiDU sees them from the game folder, e.g.
    `stratagems/lib/x.tpa` - to its text; the tp2 must be among them.
    `language_index` is the LANGUAGE the questions are shown in.
    """
    lookup = {k.replace("\\", "/").lower(): v for k, v in files.items()}
    tp2_key = tp2_path.replace("\\", "/").lower()
    tp2_text = lookup.get(tp2_key)
    found = ModPrompts(tp2_path)
    if tp2_text is None:
        found.unread.append(f"{tp2_path} (not given)")
        return found
    # %MOD_FOLDER% is BACKUP's folder (tra.mod_folder, measured on LCA), but
    # with `BACKUP ~weidu_external/backup/stratagems~` (SCS) the files are in
    # the tp2's own folder: when BACKUP's folder holds no file of the mod,
    # the tp2's folder is the one includes are read from.
    folder = mod_folder(tp2_text)
    # paths are the game folder's; a tp2 kept deeper (a checkout, EET's own
    # modConverter) is read with what precedes its mod folder put first
    at = tp2_key.rfind(folder.lower() + "/") if folder else -1
    prefix = tp2_key[:at] if at > 0 else ""
    if not folder or not any(k.startswith(prefix + folder.lower() + "/") for k in lookup):
        folder, prefix = tp2_key.rpartition("/")[0], ""
    langs = languages(tp2_text)
    language = langs[language_index] if 0 <= language_index < len(langs) else None
    strings: dict[int, str] = {}
    if language is not None:
        for path in language.tra_files:
            tra_key = _variables(path, folder, language, weidu_os).replace("\\", "/").lower()
            text = lookup.get(tra_key, lookup.get(prefix + tra_key))
            if text is not None:
                strings.update(parse_tra(text))
    lang = language if language is not None else type("L", (), {"directory": ""})()
    # `OUTER_SPRINT NAME ~literal~` before the first component: a constant a
    # path may be built from (EEUITweaks' %PKGNAME%)
    stripped = _strip(tp2_text)
    first_component = _COMPONENT_START.search(stripped)
    preamble = stripped[:first_component.start()] if first_component else stripped
    constants = {m.group(1): m.group(2) for m in _CONSTANT.finditer(preamble)
                 if "%" not in m.group(2)}
    reader = _Reader(files, strings, folder, lang, weidu_os, constants, prefix)
    src = reader.source(tp2_key)
    if src is None:             # not reached: the tp2 is among the files read
        found.unread.append(f"{tp2_path} (not read)")
        return found
    toks = src.tokens
    # component chunks, by offset, as tp2.py and tra.py cut them
    starts = [m.start() for m in _COMPONENT_START.finditer(src.text)]
    first = next((k for k, t in enumerate(toks) if starts and t.at >= starts[0]), len(toks))
    # ALWAYS ... END: WeiDU runs it before each component, %COMPONENT_NUMBER% set
    always = next(((k + 1, _block_end_from(toks, k + 1)) for k in range(first)
                   if toks[k].word == "ALWAYS"), None)
    number = -1
    for position, start in enumerate(starts):
        stop_at = starts[position + 1] if position + 1 < len(starts) else len(src.text)
        number = component_number(src.text[start:stop_at], number)
        lo = next((k for k, t in enumerate(toks) if t.at >= start), len(toks))
        hi = next((k for k, t in enumerate(toks) if t.at >= stop_at), len(toks))
        mark = len(reader.unread)
        prompts = (reader.walk(src, always[0], always[1], "always", frozenset({tp2_key}), number)
                   if always else [])
        prompts += reader.walk(src, lo, hi, "", frozenset({tp2_key}), number)
        for prompt in prompts:
            prompt.component = number
        if prompts:
            found.components[number] = prompts
        if len(reader.unread) > mark:
            found.unread_by[number] = list(dict.fromkeys(reader.unread[mark:]))
    found.unread = list(dict.fromkeys(reader.unread))
    return found


def _block_end_from(tokens: list[_Token], k: int) -> int:
    """ALWAYS ... END has no BEGIN of its own: its END is the one at depth 0."""
    depth = 0
    for m in range(k, len(tokens)):
        if tokens[m].word in _OPENERS:
            depth += 1
        elif tokens[m].word == "END":
            if depth == 0:
                return m
            depth -= 1
    return len(tokens)
