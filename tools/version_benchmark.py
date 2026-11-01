#!/usr/bin/env python3
"""
Measure the two version rules of M2d against what the mods themselves say.

    python3 tools/version_benchmark.py ORACLE.json KRION_DATA BWS_MODS MODS_DIR

1. `weidu.log_version`: for every component line WeiDU printed (ORACLE.json,
   from tools/tra_oracle.py - the same text WeiDU writes to WeiDU.log), is the
   version read from the line the tp2's VERSION?
2. `freshness.latest`: for every mod repository in MODS_DIR (`owner__repo`,
   cloned at HEAD) whose tp2 has a VERSION, does each source - and the rule,
   the newest of all - agree with it? KRION_DATA is krion64's data/
   (version_cache.json, mods/), BWS_MODS is BWS-NG's data/mods.

The truth in 2 is imperfect, and the report says how: an author who tags
v14.1 without bumping the tp2 makes a right answer count as "newer".
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from iemod_fetch.freshness import (RELEASE, Candidate, github_repo,  # noqa: E402
                                   latest, parse_release_cache)
from iemod_fetch.moddb import ModDatabase  # noqa: E402
from iemod_fetch.naming import normalize_key  # noqa: E402
from iemod_fetch.tra import _strip, _version  # noqa: E402
from iemod_fetch.versions import compare_published  # noqa: E402
from iemod_fetch.weidu import log_version  # noqa: E402


def tp2_version(path: str):
    with open(path, "rb") as fh:
        return _version(_strip(fh.read().decode("latin-1"))) or None


def log_lines(oracle) -> None:
    right = wrong = missed = quiet = 0
    for run in oracle:
        if run["lang"] != 0 or not run["components"]:
            continue
        truth = tp2_version(os.path.join(run["game"], run["tp2"]))
        for _number, text in run["components"]:
            got = log_version(text)
            if got == truth:
                right, quiet = (right + 1, quiet) if truth else (right, quiet + 1)
            elif got is None:
                missed += 1
            else:
                wrong += 1
                print(f"   wrong: {run['tp2']}: {text!r} -> {got!r}, tp2 says {truth!r}")
    print(f"log_version: {right} right, {wrong} wrong, {missed} missed, "
          f"{quiet} correctly none")


def sources(krion_data: str, bws_mods: str, mods_dir: str) -> None:
    with open(os.path.join(krion_data, "version_cache.json"), encoding="utf-8") as fh:
        releases = parse_release_cache(json.load(fh))
    bws = ModDatabase.load(bws_mods)
    krion = ModDatabase.load(os.path.join(krion_data, "mods"))
    rows = []
    for repo_dir in sorted(os.listdir(mods_dir)):
        if "__" not in repo_dir:
            continue
        repo = repo_dir.replace("__", "/", 1).lower()
        for path in glob.glob(os.path.join(mods_dir, repo_dir, "**", "*.tp2"), recursive=True):
            stem = os.path.basename(path)[:-4].lower()
            key = normalize_key(stem.removeprefix("setup-"))
            linked = [r for r in (bws.records.get(key), krion.records.get(key)) if r]
            repos = {github_repo(u) for r in linked
                     for u in [r.homepage] + [f.download for f in r.files]}
            truth = tp2_version(path)
            if repo not in repos or not truth:
                continue
            release = releases.get(repo)
            rows.append((key, truth,
                         Candidate(release.tag, RELEASE) if release else None,
                         _candidate(bws.records.get(key), "bws-ng"),
                         _candidate(krion.records.get(key), "krion64")))
    print(f"latest: {len(rows)} mods whose tp2 has a VERSION")
    rules = {"release alone": lambda r: r[2], "BWS-NG alone": lambda r: r[3],
             "krion64 alone": lambda r: r[4],
             "newest of all (the rule)": lambda r: latest(c for c in r[2:] if c)}
    for name, rule in rules.items():
        counts = {"same": 0, "older": 0, "newer": 0, "unknown": 0, "none": 0}
        for row in rows:
            found = rule(row)
            if not found:
                counts["none"] += 1
                continue
            result = compare_published(found.version, row[1])
            counts[{None: "unknown", 0: "same", -1: "older", 1: "newer"}[result]] += 1
        print(f"  {name:26} " + ", ".join(f"{k} {v}" for k, v in counts.items()))


def _candidate(record, origin):
    return Candidate(record.version, origin) if record and record.version else None


def main(argv) -> int:
    with open(argv[1], encoding="utf-8") as fh:
        log_lines(json.load(fh))
    sources(argv[2], argv[3], argv[4])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
