"""
The JSON contract every front end reads (ADR-0030).

Each JSON document the tool writes names its `schema_version`, so a reader can
refuse one it does not understand instead of misreading it; the schemas live
in `schemas/`. A finding carries an `id` derived from what it is about - kind,
install, mods, components, rule - and nothing else, so the same conflict keeps
the same id across runs, and a UI can answer "this one" by id.
"""
import hashlib
import json

SCHEMA_VERSION = 1


def stable_id(prefix: str, *parts) -> str:
    """`prefix-` + 16 hex digits of a digest of `parts`, in a canonical form."""
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]}"
