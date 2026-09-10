"""
Turn a completed run into a reproducible manifest.

ADR-0004 said the tool cannot invent trust it does not have, but it CAN record
what it actually fetched. This module promotes those observations - resolved
release tag, exact asset filename, sha256 of the bytes that were verified and
installed - back into the manifest, producing a lockfile you commit.

A pinned manifest is not a different format: it is the same
`mod_downloads.json` schema with the three optional integrity fields filled in,
so it stays readable by anything that reads the original.
"""
import json
import os
import posixpath
import time
import urllib.parse
from typing import Dict, List, Optional

from .errors import ManifestError
from .manifest import KNOWN_FIELDS, Manifest
from .report import Record, Status

PINNABLE = (Status.OK, Status.PLANNED, Status.SKIPPED)


def _asset_name(record: Record) -> Optional[str]:
    """Only a real release asset has a stable filename worth pinning."""
    if record.origin != "release-asset" or not record.url:
        return None
    name = posixpath.basename(urllib.parse.urlparse(record.url).path)
    return name or None


def build_pinned_manifest(manifest: Manifest, records: List[Record],
                          state: Optional[Dict[str, dict]] = None) -> dict:
    """
    Return a manifest dict with `release_tag`, `asset` and `sha256` filled in
    from this run, plus a per-entry note when nothing could be pinned.

    Entries the run did not touch are copied through unchanged - pinning is
    additive and never drops information.
    """
    state = state or {}
    by_key: Dict[str, Record] = {}
    for record in records:
        if record.status not in PINNABLE or not record.source_key:
            continue
        key = record.source_key.lower()
        # Prefer a record that actually carries a digest.
        if key not in by_key or (record.sha256 and not by_key[key].sha256):
            by_key[key] = record

    mods, pinned, partial = [], 0, 0
    for key in manifest.order:
        source = manifest.sources[key]
        entry = {"name": source.name, "tp2": source.key}
        if source.url:
            entry["url"] = source.url
        if source.github:
            entry["github"] = source.github
        if source.folder:
            entry["folder"] = source.folder
        if source.notes:
            entry["notes"] = source.notes

        pinned_from = by_key.get(key)
        tag = (pinned_from.version if pinned_from else None) or source.release_tag
        sha = (pinned_from.sha256 if pinned_from else None) or source.sha256
        asset = ((_asset_name(pinned_from) if pinned_from else None)
                 or source.asset)
        if not sha and key in state:
            stored = state[key]
            sha, tag = stored.get("sha256", sha), stored.get("version", tag)

        if tag:
            entry["release_tag"] = tag
        if asset:
            entry["asset"] = asset
        if sha:
            entry["sha256"] = sha
            pinned += 1
        else:
            partial += 1
            entry["notes"] = " | ".join(filter(None, [
                entry.get("notes"),
                "NOT PINNED: no sha256 observed for this entry"]))

        # Not an assert: `python -O` strips those, and this is the one check
        # that stops the generator emitting a manifest the loader will reject.
        unknown = set(entry) - KNOWN_FIELDS
        if unknown:
            raise ManifestError(
                f"pinned entry for {entry.get('tp2', '?')} has unknown field(s) "
                f"{sorted(unknown)}; the generator and manifest.KNOWN_FIELDS "
                f"have drifted apart")
        mods.append(entry)

    return {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "description": (
            f"Pinned mod catalogue produced by iemod-fetch from an actual run. "
            f"{pinned} of {len(mods)} entries carry a sha256 and will be verified "
            f"byte-for-byte on future runs; {partial} could not be pinned and will "
            f"still resolve to 'latest'."),
        "pinned_entries": pinned,
        "unpinned_entries": partial,
        "mods": mods,
    }


def write_pinned_manifest(path: str, payload: dict) -> None:
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)
