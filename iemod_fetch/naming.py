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
