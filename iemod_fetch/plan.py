"""
Joining desired state (WeiDU.log) to the source catalogue (mod_downloads.json).

This module is where the legacy script went wrong at the design level. Its
`tp2` key was used for three different jobs at once: catalogue id, install
directory name, and identity check. In the real data those are NOT the same
string - 30 entries differ in case and 10 differ outright (`questpack` vs
`d0questpack`, `c#solaufein` vs `jasteys_solaufein`). Fuzzy matching was bolted
on to paper over that, and it leaked into verification, where it made every
check pass.

Here the three jobs are separated (ADR-0002):
  * install directory  = the WeiDU folder, verbatim  (authoritative)
  * catalogue lookup   = exact key, then explicit alias, then a *suggestion*
  * identity check     = strict, in naming.matches_tp2, never fuzzy
"""
import difflib
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .errors import ConfigError
from .manifest import Manifest, ModSource
from .naming import normalize_key, safe_component
from .weidu import ParsedLog

# Author/prefix conventions seen in the corpus; stripped only for SUGGESTIONS.
_PREFIXES = ("c#", "l#", "a7#", "a7-", "ja#", "d0", "ow", "jasteys_", "bp_",
             "eet_", "setup-", "the")
_SUGGEST_THRESHOLD = 0.60


@dataclass
class Suggestion:
    folder: str
    candidate_key: str
    score: float
    rationale: str


@dataclass
class WorkItem:
    folder: str                       # exact directory WeiDU expects on disk
    source: Optional[ModSource]
    origin: str                       # weidu | manifest
    match: str                        # exact | alias | suggested | none
    detail: str = ""
    game: Optional[str] = None        # which install this mod belongs to


@dataclass
class Plan:
    items: List[WorkItem] = field(default_factory=list)
    unresolved: List[WorkItem] = field(default_factory=list)
    suggestions: List[Suggestion] = field(default_factory=list)
    unused_sources: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def load_aliases(path) -> Dict[str, str]:
    """{"weidu_folder": "manifest_tp2_key"} - explicit, reviewable, in version control."""
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except OSError as exc:
        raise ConfigError(f"cannot read alias file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"alias file {path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in raw.items()):
        raise ConfigError(f"alias file {path} must be a flat object of string->string")
    # keys beginning with "_" are comments, not aliases
    return {k.lower(): v for k, v in raw.items() if not k.startswith("_")}


def _strip_prefix(key: str) -> str:
    for prefix in _PREFIXES:
        stripped = normalize_key(prefix)
        if stripped and key.startswith(stripped) and len(key) > len(stripped) + 2:
            return key[len(stripped):]
    return key


def suggest(folder: str, manifest: Manifest, limit: int = 3) -> List[Suggestion]:
    """Propose catalogue entries for an unmatched WeiDU folder. Never auto-applied."""
    target = normalize_key(folder)
    target_core = _strip_prefix(target)
    out = []
    for source in manifest.sources.values():
        cand = normalize_key(source.key)
        cand_core = _strip_prefix(cand)
        if cand_core and target_core and cand_core == target_core:
            out.append(Suggestion(folder, source.key, 0.97,
                                  f"identical after stripping author prefix ({cand_core})"))
            continue
        if len(target_core) >= 5 and (target_core in cand or cand_core in target):
            out.append(Suggestion(folder, source.key, 0.80, "one key contains the other"))
            continue
        ratio = difflib.SequenceMatcher(None, target_core, cand_core).ratio()
        if ratio >= _SUGGEST_THRESHOLD:
            out.append(Suggestion(folder, source.key, round(ratio, 3),
                                  f"string similarity {ratio:.0%}"))
    out.sort(key=lambda s: -s.score)
    return out[:limit]


def build_plan(installed: ParsedLog, manifest: Manifest,
               aliases: Optional[Dict[str, str]] = None,
               include_manifest_only: bool = False,
               accept_suggestions: bool = False) -> Plan:
    aliases = aliases or {}
    plan = Plan(warnings=list(installed.warnings) + list(manifest.warnings))
    consumed = set()

    for key in installed.order:
        mod = installed.mods[key]
        try:
            folder = safe_component(mod.folder)
        except ConfigError as exc:
            plan.warnings.append(f"skipping WeiDU folder {mod.folder!r}: {exc}")
            continue

        source, match, detail = None, "none", ""
        if key in manifest.sources:
            source, match = manifest.sources[key], "exact"
        elif key in aliases:
            alias_key = aliases[key].lower()
            if alias_key in manifest.sources:
                source, match = manifest.sources[alias_key], "alias"
                detail = f"alias -> {manifest.sources[alias_key].key}"
            else:
                plan.warnings.append(
                    f"alias {mod.folder} -> {aliases[key]!r} names no manifest entry")
        if source is None:
            options = suggest(mod.folder, manifest)
            plan.suggestions.extend(options)
            if options and accept_suggestions:
                source = manifest.sources[options[0].candidate_key.lower()]
                match = "suggested"
                detail = f"auto-accepted suggestion ({options[0].rationale})"

        item = WorkItem(folder=folder, source=source, origin="weidu",
                        match=match, detail=detail, game=mod.game)
        if source is None:
            plan.unresolved.append(item)
        else:
            consumed.add(source.lookup)
            plan.items.append(item)

    if include_manifest_only:
        for key in manifest.order:
            if key in consumed:
                continue
            source = manifest.sources[key]
            folder = source.folder or source.key
            plan.items.append(WorkItem(folder=folder, source=source,
                                       origin="manifest", match="exact",
                                       detail="not referenced by any WeiDU log"))
            consumed.add(key)

    plan.unused_sources = [manifest.sources[k].key for k in manifest.order
                           if k not in consumed]
    return plan
