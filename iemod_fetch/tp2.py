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
from typing import List, Optional

_MAX_TP2_BYTES = 8 * 1024 * 1024

_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_COMMENT_LINE = re.compile(r"^//.*|\s//.*", re.MULTILINE)

_QUOTED = r'[~"](.*?)[~"]'
_VERSION = re.compile(r"\bVERSION\s+[~\"](.+?)[~\"]", re.IGNORECASE)
_AUTHOR = re.compile(rf"\bAUTHOR\s*{_QUOTED}", re.IGNORECASE | re.DOTALL)
_BEGIN = re.compile(rf"\bBEGIN\s*{_QUOTED}", re.IGNORECASE | re.DOTALL)
_LANGUAGE = re.compile(r"\bLANGUAGE\s*((?:[~\"](?:.*?)[~\"]\s*)+)",
                       re.IGNORECASE | re.DOTALL)
_STRING = re.compile(_QUOTED, re.DOTALL)
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
    "bg1": "BG", "totsc": "BG", "tutu": "Tutu", "bgt": "BGT",
    "soa": "BG2", "tob": "BG2", "bg2": "BG2",
    "bgee": "BGEE", "sod": "SoD", "bg2ee": "BG2EE", "eet": "EET",
    "iwd": "IWD", "how": "IWD", "totlm": "IWD", "iwd2": "IWD2",
    "iwdee": "IWDEE", "pst": "PST", "pstee": "PSTEE",
}


@dataclass
class Tp2Info:
    path: str
    version: Optional[str] = None
    mod_name: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    games: List[str] = field(default_factory=list)
    languages: List[str] = field(default_factory=list)

    @property
    def normalised_games(self) -> List[str]:
        """The declared games mapped onto this tool's identifiers."""
        out = []
        for token in self.games:
            mapped = _GAME_ALIASES.get(token.lower())
            if mapped and mapped not in out:
                out.append(mapped)
        return out

    def supports(self, game: Optional[str]) -> Optional[bool]:
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
    clean = strip_comments(content)
    info = Tp2Info(path=path)

    match = _VERSION.search(clean)
    if match:
        info.version = match.group(1).strip() or None
    match = _BEGIN.search(clean)
    if match:
        info.mod_name = match.group(1).strip() or None

    info.authors = [a.strip() for a in _AUTHOR.findall(clean) if a.strip()]

    seen = set()
    for block in _GAMES.findall(clean):
        for raw_token in re.split(r"[\s,]+", block.strip()):
            token = raw_token.strip()
            if token and token.lower() not in seen:
                seen.add(token.lower())
                info.games.append(token)

    for block in _LANGUAGE.finditer(clean):
        # a LANGUAGE block is (display name, directory, tra files...)
        values = _STRING.findall(block.group(1))
        if values:
            name = values[0].strip()
            if name and name not in info.languages:
                info.languages.append(name)
    return info


def read_tp2(path: str) -> Optional[Tp2Info]:
    """Parse a .tp2 from disk. Returns None rather than raising on any problem."""
    try:
        if os.path.getsize(path) > _MAX_TP2_BYTES:
            return None
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return parse_tp2(fh.read(), path=path)
    except OSError:
        return None


def read_mod_tp2(mod_dir: str, tp2_file: str) -> Optional[Tp2Info]:
    """Read the tp2 that identifies an installed mod directory."""
    direct = os.path.join(mod_dir, tp2_file)
    if os.path.isfile(direct):
        return read_tp2(direct)
    for dirpath, _dirnames, filenames in os.walk(mod_dir):
        for name in filenames:
            if name.lower() == tp2_file.lower():
                return read_tp2(os.path.join(dirpath, name))
    return None
