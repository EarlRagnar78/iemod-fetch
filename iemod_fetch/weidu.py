"""
WeiDU.log parser.

The log is the authoritative statement of *desired state*: which mod folders
must exist, spelled exactly as WeiDU expects them on disk. The manifest is only
a catalogue of where to obtain them.
"""
import re
from dataclasses import dataclass, field

# Game identifiers as used by the LCC catalogue's `games` field.
KNOWN_GAMES = ("BG", "Tutu", "BG2", "BGT", "BGEE", "SoD", "BG2EE", "EET",
               "IWD", "IWDEE", "IWD2", "PST", "PSTEE")
_GAMES_LOWER = {g.lower(): g for g in KNOWN_GAMES}


def split_log_spec(spec: str):
    r"""
    Split a `-w` value into (path, game).

    `WeiDU.log:EET` names the game explicitly; a bare path leaves it to be
    inferred. Only a recognised game suffix is treated as one, so a Windows
    path like `C:\Games\WeiDU.log` is never mangled.
    """
    if ":" in spec:
        head, _, tail = spec.rpartition(":")
        if head and tail.lower() in _GAMES_LOWER:
            return head, _GAMES_LOWER[tail.lower()]
    return spec, None


# ~folder\SETUP-MOD.TP2~ #lang #component // Comment : Version
_LINE = re.compile(
    r"^~(?P<path>[^~]+)~\s*"
    r"#(?P<lang>-?\d+)\s*"
    r"#(?P<comp>-?\d+)\s*"
    r"(?://\s*(?P<comment>.*?))?\s*$"
)


@dataclass(frozen=True)
class Component:
    folder: str
    tp2_file: str
    language: int
    index: int
    comment: str = ""
    version: str | None = None     # a suffix shaped like a version (log_version)
    path: str = ""       # tp2 path exactly as the log spelled it, for round-tripping
    line: int = 0        # 1-based line in the log: the true install order


@dataclass
class InstalledMod:
    folder: str                       # exact on-disk directory name WeiDU expects
    tp2_file: str
    game: str | None = None        # which install this log describes
    components: list[Component] = field(default_factory=list)
    version: str | None = None     # only if the log actually recorded one

    @property
    def key(self) -> str:
        return self.folder.lower()


@dataclass
class ParsedLog:
    mods: dict[str, InstalledMod] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)   # install order, oldest first
    warnings: list[str] = field(default_factory=list)
    component_count: int = 0
    game: str | None = None

    def detect_game(self) -> str | None:
        """
        Infer which game this log describes from the mods it installs.

        Only EET is inferable with confidence: a log that installs the `eet`
        mod is an EET install, full stop. Anything else is left unknown rather
        than guessed - a wrong game would produce wrong compatibility warnings,
        which is worse than none. Override with `-w PATH:GAME`.
        """
        if "eet" in self.mods:
            return "EET"
        return None


def _mod_from_root_tp2(tp2_file: str) -> str:
    """The mod a root-level tp2 belongs to, by WeiDU's naming rule; '' if none."""
    if not tp2_file.lower().endswith(".tp2"):
        return ""
    stem = tp2_file[:-4]
    return stem[6:] if stem.lower().startswith("setup-") else stem


_DIGIT = re.compile(r"\d")


def log_version(comment: str) -> str | None:
    """
    The version at the end of a WeiDU.log comment, or None.

    WeiDU 251 writes `Name: VERSION` - one colon, no space before it, whatever
    its own header says (`[ : Version]`) - so `Margarita for BG: EE` and
    `Artisan's Kitpack: Adjust kit THAC0 ...` end the same way a version does.
    What follows the last ': ' is a version only if it looks like one: it has a
    digit, is not a `Group -> Name`, not an unresolved `@N`, and is at most four
    words (`Beta 2 - Working Master`). A trailing `// @wlb-inputs: ...` (BIO's
    recorded prompt answers) is not part of the name. Measured on 1,533 component lines of 103
    mods against their tp2 VERSION: no wrong version, none missed
    (docs/TESTING.md).
    """
    comment = comment.split(" // @", 1)[0]     # BIO's `// @wlb-inputs: ...` tag
    if ": " not in comment:
        return None
    suffix = comment.rsplit(": ", 1)[1].strip()
    if (not suffix or not _DIGIT.search(suffix) or "->" in suffix
            or suffix.startswith("@") or len([w for w in suffix.split() if w.strip("-")]) > 4):
        return None
    return suffix


def parse_weidu_log(text: str, source: str = "<weidu.log>") -> ParsedLog:
    """Parse WeiDU.log content. Unparseable lines are reported, never ignored."""
    out = ParsedLog()
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith("//"):
            continue
        m = _LINE.match(line)
        if not m:
            out.warnings.append(f"{source}:{lineno}: unparseable line: {line[:90]!r}")
            continue

        parts = [p for p in m.group("path").replace("\\", "/").split("/") if p]
        if len(parts) == 1:
            # An older mod whose tp2 sits in the game directory. WeiDU itself
            # names the mod after the tp2: setup-<mod>.tp2 or <mod>.tp2.
            parts = [_mod_from_root_tp2(parts[0]), parts[0]]
        if len(parts) < 2 or not parts[0]:
            out.warnings.append(
                f"{source}:{lineno}: tp2 not inside a mod folder: {m.group('path')!r}")
            continue
        folder, tp2_file = parts[0], parts[-1]
        comment = (m.group("comment") or "").strip()

        version = log_version(comment)

        comp = Component(folder, tp2_file, int(m.group("lang")),
                         int(m.group("comp")), comment, version,
                         path=m.group("path").strip(), line=lineno)
        out.component_count += 1

        key = folder.lower()
        if key not in out.mods:
            out.mods[key] = InstalledMod(folder=folder, tp2_file=tp2_file)
            out.order.append(key)
        mod = out.mods[key]
        mod.components.append(comp)
    for mod in out.mods.values():
        # A tp2's VERSION is on every one of its components: a suffix they do
        # not all share is part of a name, or the mod is half upgraded.
        versions = {c.version for c in mod.components}
        mod.version = versions.pop() if len(versions) == 1 else None
    return out


def parse_weidu_files(paths) -> ParsedLog:
    """
    Merge several logs (e.g. WeiDU.log + WeiDUBGEE.log) preserving order.

    Each entry is a path, or a (path, game) pair. When the game is not given it
    is inferred per log, so mods from a BGEE log are never judged against EET
    compatibility and vice versa.
    """
    merged = ParsedLog()
    for entry in paths:
        path, game = entry if isinstance(entry, (tuple, list)) else (entry, None)
        with open(path, encoding="utf-8", errors="replace") as fh:
            parsed = parse_weidu_log(fh.read(), source=str(path))
        parsed.game = game or parsed.detect_game()
        for mod in parsed.mods.values():
            mod.game = parsed.game
        merged.warnings.extend(parsed.warnings)
        merged.component_count += parsed.component_count
        merged.game = merged.game or parsed.game
        for key in parsed.order:
            if key in merged.mods:
                merged.mods[key].components.extend(parsed.mods[key].components)
            else:
                merged.mods[key] = parsed.mods[key]
                merged.order.append(key)
    return merged
