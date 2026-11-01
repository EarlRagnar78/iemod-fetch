#!/usr/bin/env python3
"""
Measure iemod_fetch.tra against WeiDU's own --list-components.

    python3 tools/tra_benchmark.py ORACLE.json [--show N] [--min PERCENT]

ORACLE.json is a list of {"game", "tp2", "lang", "components": [[n, text]]},
each produced by `weidu --nogame --list-components TP2 LANG` run in "game"
(tools/tra_oracle.py writes it; docs/TESTING.md). Prints exact-match accuracy
and the first mismatches; with --min, exits 1 below that accuracy.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from iemod_fetch.tra import component_names  # noqa: E402


def reader(game: str):
    cache = {}

    def find(path: str):
        """Case-insensitive, as on Windows, relative to the game directory."""
        current = game
        for part in path.replace("\\", "/").split("/"):
            if part in ("", "."):
                continue
            try:
                names = cache.setdefault(current, os.listdir(current))
            except OSError:
                return None
            hit = next((n for n in names if n.lower() == part.lower()), None)
            if hit is None:
                return None
            current = os.path.join(current, hit)
        return current if os.path.isfile(current) else None

    def read(path: str):
        found = find(path)
        if found is None:
            return None
        with open(found, "rb") as fh:
            return fh.read().decode("latin-1")   # byte-exact, as WeiDU prints
    return read, find


def main(argv) -> int:
    with open(argv[1], encoding="utf-8") as fh:
        oracle = json.load(fh)
    show = int(argv[argv.index("--show") + 1]) if "--show" in argv else 15
    floor = float(argv[argv.index("--min") + 1]) if "--min" in argv else 0.0
    total = exact = missing = 0
    misses = []
    for run in oracle:
        if not run["components"]:
            continue
        read, find = reader(run["game"])
        tp2_path = find(run["tp2"])
        with open(tp2_path, "rb") as fh:
            tp2 = fh.read().decode("latin-1")
        predicted = {c.number: c.name for c in component_names(
            tp2, run["lang"], read, weidu_os="unix")}   # the oracle ran on Linux
        for number, text in run["components"]:
            total += 1
            got = predicted.get(number)
            if got is None:
                missing += 1
                misses.append((run["tp2"], run["lang"], number, text, None))
            elif got == text:
                exact += 1
            else:
                misses.append((run["tp2"], run["lang"], number, text, got))
    accuracy = 100 * exact / total if total else 0.0
    print(f"{exact}/{total} exact ({accuracy:.2f}%), {missing} components not found")
    for miss in misses[:show]:
        print("  ", miss)
    fields_ok = _json_fields(oracle, show)
    return 0 if accuracy >= floor and fields_ok >= floor else 1


def _json_fields(oracle, show: int) -> float:
    """Against --list-components-json: which components are listed (DEPRECATED
    ones are not), and each one's title, subgroup, groups, labels and forced."""
    totals = {key: [0, 0] for key in ("listed", "title", "subgroup", "groups",
                                      "labels", "forced")}
    misses = []
    for run in oracle:
        if not run.get("json"):
            continue
        read, find = reader(run["game"])
        with open(find(run["tp2"]), "rb") as fh:
            tp2 = fh.read().decode("latin-1")
        ours = {c.number: c for c in component_names(tp2, 0, read, weidu_os="unix")
                if not c.deprecated}
        want = {c["number"]: c for c in run["json"]}
        totals["listed"][1] += 1
        totals["listed"][0] += set(ours) == set(want)
        for number, expected in want.items():
            got = ours.get(number)
            if got is None:
                continue
            for key, mine, theirs in (
                    ("title", got.title, expected["name"]),
                    ("subgroup", got.subgroup or None, expected.get("subgroup")),
                    ("groups", got.groups, expected.get("group", [])),
                    ("labels", got.labels, expected.get("label", [])),
                    ("forced", got.forced, expected.get("forced", False))):
                totals[key][1] += 1
                if mine == theirs:
                    totals[key][0] += 1
                else:
                    misses.append((run["tp2"], number, key, theirs, mine))
    for key, (right, count) in totals.items():
        print(f"{key:9} {right}/{count}")
    for miss in misses[:show]:
        print("  ", miss)
    right = sum(r for r, _c in totals.values())
    count = sum(c for _r, c in totals.values())
    return 100 * right / count if count else 100.0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
