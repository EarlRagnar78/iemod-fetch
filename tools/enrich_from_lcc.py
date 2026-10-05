#!/usr/bin/env python3
"""
Fill gaps in mod_downloads.json from a supplementary catalogue.

Runtime catalogue lookup (--catalogue) works, but baking the result into the
manifest is better: it makes the file self-sufficient, reviewable in a diff,
and deterministic on the next run. Every field added carries provenance in
`notes`, so a later reader can tell what came from where.

    python3 tools/enrich_from_lcc.py \\
        -i mod_downloads.json -c ~/lcc-docs/db/mods.json -o mod_downloads.enriched.json

Only entries that currently have NO usable GitHub repository are touched; an
existing `github` is never overwritten. Nothing is verified by this script -
the fetcher still has to prove the archive contains the right .tp2.
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from iemod_fetch.catalogues import CatalogueSet          # noqa: E402
from iemod_fetch.manifest import parse_manifest          # noqa: E402
from iemod_fetch.resolvers import repo_from_url          # noqa: E402


def enrich(manifest_path, catalogue_paths, out_path, dry_run=False, with_advisories=True):
    with open(manifest_path, encoding="utf-8") as fh:
        catalogue_json = json.load(fh)
    catalogues = CatalogueSet.load(catalogue_paths)
    print(f"  catalogue: {len(catalogues)} mods from {len(catalogue_paths)} file(s)")

    added, advised, untouched = [], [], 0
    for entry in catalogue_json["mods"]:
        key = entry.get("tp2") or ""
        hit = catalogues.lookup(key, entry.get("folder"))
        if not hit:
            untouched += 1
            continue

        has_repo = bool(entry.get("github")) or bool(repo_from_url(entry.get("url", "")))
        if not has_repo and hit.github:
            entry["github"] = hit.github
            entry["url"] = f"https://github.com/{hit.github}/releases"
            entry["notes"] = " | ".join(filter(None, [
                entry.get("notes"), f"github from {hit.origin}"]))
            added.append((key, hit.github))
        else:
            untouched += 1

        if with_advisories:
            notes = hit.advisories()
            if notes:
                advised.append((key, notes))
                entry["notes"] = " | ".join(filter(None, [entry.get("notes")] + notes))

    print(f"\n  {len(added)} entr(ies) gained a GitHub repository:")
    for key, repo in added:
        print(f"      {key:26s} -> {repo}")
    if advised:
        print(f"\n  {len(advised)} entr(ies) carry a catalogue advisory:")
        for key, notes in advised[:12]:
            print(f"      {key:26s} {notes[0]}")
        if len(advised) > 12:
            print(f"      ... and {len(advised) - 12} more")

    result = parse_manifest(catalogue_json, source=out_path)
    print(f"\n  re-validated: {len(result.sources)} entries, "
          f"{sum('http://' in w for w in result.warnings)} cleartext URL(s)")

    if not dry_run:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(catalogue_json, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"  written: {out_path}")
    return added, advised


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-i", "--input", default="mod_downloads.json")
    parser.add_argument("-c", "--catalogue", action="append", required=True,
                        metavar="PATH", help="supplementary catalogue; repeatable")
    parser.add_argument("-o", "--output", default="mod_downloads.enriched.json")
    parser.add_argument("-n", "--dry-run", action="store_true")
    parser.add_argument("--no-advisories", action="store_true",
                        help="do not copy quality/status notes into the manifest")
    args = parser.parse_args(argv)
    enrich(args.input, args.catalogue, args.output, args.dry_run,
           with_advisories=not args.no_advisories)
    return 0


if __name__ == "__main__":
    sys.exit(main())
