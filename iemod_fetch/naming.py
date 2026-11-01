"""
Filesystem-name safety and TP2 identity matching.

Design note (see ADR-0002): matching is STRICT. Fuzzy matching exists only in
plan.py, where it may *propose* an alias for a human to approve - it may never
decide that a downloaded artefact is the right one.
"""
import os
import re

from .errors import UnsafeName

# Characters observed in the real corpus: 'c#endlessbg1', 'JA#BGT_AdvPack',
# 'A7#ImprovedArcher', 'l#coi-yvette', 'bp_in_bg', 'EET_end'.
_ALLOWED_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.#!$@()+&'~-]{0,62}$")

_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)
}


def safe_component(name: str) -> str:
    """
    Return `name` if it is safe to use as a SINGLE path component, else raise.

    Rejects traversal (`..`), separators, absolute/UNC/drive paths, NUL bytes,
    Windows reserved device names, and trailing dot/space (silently stripped by
    Windows). This is the control that stops a manifest from writing - or
    deleting - outside the target directory.
    """
    if not isinstance(name, str):
        raise UnsafeName(f"name must be a string, got {type(name).__name__}")
    stripped = name.strip()
    if not stripped:
        raise UnsafeName("empty name")
    if stripped in (".", ".."):
        raise UnsafeName(f"traversal component: {name!r}")
    if "/" in stripped or "\\" in stripped or "\x00" in stripped:
        raise UnsafeName(f"path separator or NUL in name: {name!r}")
    if os.path.isabs(stripped) or (len(stripped) > 1 and stripped[1] == ":"):
        raise UnsafeName(f"absolute path in name: {name!r}")
    if name != stripped or name.endswith((".", " ")):
        raise UnsafeName(f"leading/trailing whitespace or dot: {name!r}")
    if not _ALLOWED_COMPONENT.match(stripped):
        raise UnsafeName(f"disallowed characters in name: {name!r}")
    if stripped.split(".")[0].upper() in _WINDOWS_RESERVED:
        raise UnsafeName(f"Windows reserved device name: {name!r}")
    return stripped


def is_safe_component(name) -> bool:
    try:
        safe_component(name)
        return True
    except UnsafeName:
        return False


def archive_filename(remote, fallback: str) -> str:
    """
    Reduce a server-supplied file name to one safe path component.

    The name comes from a Content-Disposition header or a URL path - remote
    input - and is joined onto a work directory. Both separators are split on,
    whatever the host OS, because a backslash is a separator on the machine
    this tool actually runs on. Anything that is still not a safe component
    (drive-relative, reserved, too long) becomes `fallback`; the archive type
    is identified by magic bytes, so the name carries no meaning that matters.
    """
    if not isinstance(remote, str):
        return fallback
    last = remote.replace("\\", "/").rsplit("/", 1)[-1]
    return last if is_safe_component(last) else fallback


def normalize_key(value: str) -> str:
    """Fold a mod folder / tp2 name to its comparison key: lowercase alphanumerics."""
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def tp2_stem(filename: str) -> str:
    base = os.path.basename(filename)
    return base[:-4] if base.lower().endswith(".tp2") else base


def matches_tp2(filename: str, folder: str) -> bool:
    """
    STRICT identity test between a .tp2 filename and a mod folder name.

    WeiDU permits exactly two spellings, both of which appear in the real logs:
        <folder>/<folder>.tp2            e.g. DlcMerger/DlcMerger.tp2
        <folder>/setup-<folder>.tp2      e.g. eefixpack/SETUP-EEFIXPACK.TP2
    Anything else is NOT this mod. No substring matching.
    """
    if not filename.lower().endswith(".tp2"):
        return False
    key = normalize_key(folder)
    if not key:
        return False
    stem = normalize_key(tp2_stem(filename))
    return stem == key or stem == f"setup{key}"


def expected_tp2_names(folder: str) -> tuple:
    return (f"{folder}.tp2", f"setup-{folder}.tp2")


# Third-party text (release notes, catalogue notes) kept as text: control
# characters out, cut to a length (GUI-AUDIT item 51, ADR-0059)
# with the bidirectional marks and overrides: an RLO in a note would turn
# the lines after it around too (review of #123)
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def plain_text(value, limit: int = 1500) -> str | None:
    """A third party's text as text: a string, its control characters (but
    newlines and tabs) out, cut at `limit` with an ellipsis; None if empty."""
    if not isinstance(value, str):
        return None
    text = _CONTROL.sub("", value.replace("\r\n", "\n").replace("\r", "\n")).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + " ..."
    return text or None
