#!/usr/bin/env python3
"""
Apply reviewed corrections to a mod_downloads.json catalogue.

Declarative rather than hand-edited: every change carries a reason, its
evidence and a confidence level in tools/corrections.json, so the diff can be
re-reviewed later instead of being archaeology.

    python3 tools/apply_corrections.py -i mod_downloads.json -o mod_downloads.fixed.json
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from iemod_fetch.manifest import parse_manifest  # noqa: E402


PIN_FIELDS = ("sha256", "release_tag", "asset", "github")


def merge_pins(catalogue, pinned_path):
    """
    Carry integrity pins from a previous (pinned) catalogue into a freshly
    regenerated one. Infinity Mod Forge rewrites mod_downloads.json from
    scratch, so without this step every regeneration silently discards your
    sha256 pins and drops you back to 'latest'.
    """
    with open(pinned_path, encoding="utf-8") as fh:
        previous = json.load(fh)
    old = {m.get("tp2", "").lower(): m for m in previous.get("mods", previous)}

    carried, skipped = 0, []
    for entry in catalogue["mods"]:
        source = old.get(entry.get("tp2", "").lower())
        if not source:
            continue
        for field in PIN_FIELDS:
            if source.get(field) and not entry.get(field):
                entry[field] = source[field]
                if field == "sha256":
                    carried += 1
    for key, entry in old.items():
        if entry.get("sha256") and key not in {m.get("tp2", "").lower()
                                               for m in catalogue["mods"]}:
            skipped.append(entry.get("tp2"))
    return carried, skipped


def apply(manifest_path, corrections_path, out_path, dry_run=False,
          merge_pins_from=None):
    with open(manifest_path, encoding="utf-8") as fh:
        catalogue = json.load(fh)
    with open(corrections_path, encoding="utf-8") as fh:
        corrections = json.load(fh)["corrections"]

    index = {m.get("tp2", "").lower(): m for m in catalogue["mods"]}
    applied, missing = [], []

    for correction in corrections:
        key = correction["tp2"].lower()
        entry = index.get(key)
        if entry is None:
            missing.append(correction["tp2"])
            continue
        before = {k: entry.get(k) for k in correction["set"]}
        entry.update(correction["set"])
        applied.append((correction["tp2"], before, correction["set"],
                        correction["confidence"]))

    for name, before, after, confidence in applied:
        print(f"  {name}  [{confidence}]")
        for field in after:
            if before.get(field) != after[field]:
                print(f"      {field}: {before.get(field)!r}")
                print(f"           -> {after[field]!r}")
    if missing:
        print(f"\n  WARNING: no manifest entry for {missing}", file=sys.stderr)

    if merge_pins_from:
        carried, dropped = merge_pins(catalogue, merge_pins_from)
        print(f"\n  carried {carried} sha256 pin(s) forward from {merge_pins_from}")
        if dropped:
            print(f"  NOTE: {len(dropped)} pinned mod(s) are no longer in the "
                  f"catalogue: {dropped[:6]}", file=sys.stderr)

    # A correction that breaks the schema is worse than the problem it fixes.
    result = parse_manifest(catalogue, source=out_path)
    http = [w for w in result.warnings if "http://" in w]
    print(f"\n  {len(applied)} correction(s) applied; manifest re-validates with "
          f"{len(result.sources)} entries and {len(http)} cleartext URL(s) remaining")

    if not dry_run:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(catalogue, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"  written: {out_path}")
    return len(applied), len(http)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-i", "--input", default="mod_downloads.json")
    parser.add_argument("-c", "--corrections",
                        default=os.path.join(ROOT, "tools", "corrections.json"))
    parser.add_argument("-o", "--output", default="mod_downloads.fixed.json")
    parser.add_argument("-n", "--dry-run", action="store_true")
    parser.add_argument("--merge-pins-from", metavar="PATH",
                        help="carry sha256/release_tag/asset/github from a previously "
                             "pinned catalogue into this freshly regenerated one")
    args = parser.parse_args(argv)
    apply(args.input, args.corrections, args.output, args.dry_run,
          merge_pins_from=args.merge_pins_from)
    return 0


if __name__ == "__main__":
    sys.exit(main())
