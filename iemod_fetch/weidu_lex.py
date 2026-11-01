"""
How WeiDU reads a tp2's words and strings, shared by tp2.py and tra.py.

A string closes on the mark that opened it - `~Use "smart" AI~` holds its
quotes, `~~~~~...~~~~~` holds tildes - and a `//` inside one is text, not a
comment. A regex over `[~"](.*?)[~"]` gets each of these wrong (GUI-AUDIT M7
item 43); this scanner was measured against WeiDU 251's --list-components and
--list-languages on 103 real mods.
"""
import re
from dataclasses import dataclass, field


@dataclass
class Language:
    name: str
    directory: str
    tra_files: list[str] = field(default_factory=list)


def _skip(text: str, i: int) -> int:
    """Past whitespace and comments."""
    n = len(text)
    while i < n:
        if text[i].isspace():
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            break
    return i


def _string(text: str, i: int) -> tuple[str | None, int]:
    """A WeiDU string at i: ~...~, ~~~~~...~~~~~, "...", %...%."""
    if text.startswith("~~~~~", i):
        j = text.find("~~~~~", i + 5)
        return (None, i) if j < 0 else (text[i + 5:j], j + 5)
    if i < len(text) and text[i] in "~\"%":
        j = text.find(text[i], i + 1)
        return (None, i) if j < 0 else (text[i + 1:j], j + 1)
    return None, i


def _strip(content: str) -> str:
    """Comments out, strings kept: a '//' inside ~http://...~ is text."""
    out, i, n = [], 0, len(content)
    while i < n:
        c = content[i]
        if content.startswith("//", i):
            j = content.find("\n", i)
            i = n if j < 0 else j
            continue
        if content.startswith("/*", i):
            j = content.find("*/", i + 2)
            i = n if j < 0 else j + 2
            out.append(" ")
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


_BARE = re.compile(r"[^\s~\"%/]+")


def keyword_ends(clean: str, keyword: str) -> list[int]:
    """
    Where `keyword` stands as a word of code - not inside a string, not in a
    comment - in `clean` (comments already out): the offset just past it.
    Anywhere on a line, as WeiDU reads a one-line preamble (review of #57).
    """
    ends: list[int] = []
    i, n, word = 0, len(clean), keyword.upper()
    while True:
        i = _skip(clean, i)
        if i >= n:
            return ends
        value, j = _string(clean, i)
        if value is not None:
            i = j
            continue
        bare = _BARE.match(clean, i)
        if not bare:
            i += 1                       # a lone '/' or an unclosed quote
            continue
        if bare.group(0).upper() == word:
            ends.append(bare.end())
        i = bare.end()


def _strings_after(text: str, i: int, stop: int) -> list[str]:
    values: list[str] = []
    while True:
        i = _skip(text, i)
        if i >= stop:
            return values
        value, j = _string(text, i)
        if value is None:
            return values
        values.append(value)
        i = j


def _token(text: str, i: int, stop: int) -> tuple[str | None, int]:
    """A string, or a bare word as WeiDU also accepts one."""
    i = _skip(text, i)
    if i >= stop:
        return None, i
    value, j = _string(text, i)
    if value is not None:
        return value, j
    bare = re.match(r"[^\s~\"%/]+", text[i:stop])
    return (bare.group(0), i + bare.end()) if bare else (None, i)


def languages(tp2: str) -> list[Language]:
    """
    The LANGUAGE declarations, in order: index N is the Nth.

    `LANGUAGE name directory tra...`: the name and the directory may be bare
    words (`LANGUAGE English english ~x.tra~`, SCS's `ENGLISH`); the .tra
    files are strings. Skipping a declaration would shift every index after it.
    """
    clean = _strip(tp2)
    starts = keyword_ends(clean, "LANGUAGE")
    found = []
    for k, start in enumerate(starts):
        stop = starts[k + 1] if k + 1 < len(starts) else len(clean)
        name, i = _token(clean, start, stop)
        directory, i = _token(clean, i, stop)
        if name is None or directory is None:
            continue
        found.append(Language(name, directory, _strings_after(clean, i, stop)))
    return found


# The code page of a legacy (pre-UTF-8) .tra file, by its language folder:
# WeiDU 251's own table for HANDLE_CHARSETS' infer_charsets (README-WeiDU,
# "Compatibility matrix"), the code page of BG2's localised edition. The
# cp1252 languages are named too, so the nearest language folder decides:
# `polished_items/english/` is English (review of #58).
_CHARSETS = (("schinese", "cp936"), ("zh_cn", "cp936"), ("tchinese", "cp950"),
             ("czech", "cp1250"), ("cs_cz", "cp1250"), ("japanese", "cp932"),
             ("ja_jp", "cp932"), ("korean", "cp949"), ("ko_kr", "cp949"),
             ("polish", "cp1250"), ("polski", "cp1250"), ("pl_pl", "cp1250"),
             ("russian", "cp1251"), ("ru_ru", "cp1251"),
             ("english", "cp1252"), ("american", "cp1252"), ("en_us", "cp1252"),
             ("french", "cp1252"), ("francais", "cp1252"), ("fr_fr", "cp1252"),
             ("german", "cp1252"), ("deutsch", "cp1252"), ("de_de", "cp1252"),
             ("italian", "cp1252"), ("italiano", "cp1252"), ("it_it", "cp1252"),
             ("spanish", "cp1252"), ("castilian", "cp1252"), ("espanol", "cp1252"),
             ("castellano", "cp1252"), ("es_es", "cp1252"))


def legacy_charset(path: str) -> str:
    """`mod/russian/setup.tra` -> cp1251: the innermost folder naming a language."""
    for folder in reversed(path.lower().replace("\\", "/").split("/")[:-1]):
        for name, charset in _CHARSETS:
            if name in folder:
                return charset
    return "cp1252"
