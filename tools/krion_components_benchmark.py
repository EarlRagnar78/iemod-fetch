#!/usr/bin/env python3
"""
How well krion64's component lists stand in for a mod not downloaded yet
(ADR-0035): its records against WeiDU's own --list-components.

    python3 tools/krion_components_benchmark.py ORACLE.json KRION_MODS_DIR [BWS_NG_MODS_DIR]

ORACLE.json is tools/tra_oracle.py's output (language 0 is used);
KRION_MODS_DIR is krion64's data/mods. Prints, over the mods both know: the
components WeiDU lists, how many krion64 has under the same number, those only
WeiDU has, those only krion64 has, and the mods whose lists are identical.

With BWS_NG_MODS_DIR (BigWorldSetup-NG's data/mods), the same is printed for
its records, and over the mods all three know: how many WeiDU components each
has, and how many their union has (ADR-0036).
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from iemod_fetch.choices import from_krion  # noqa: E402
from iemod_fetch.ordering import tp2_key  # noqa: E402


def main(argv) -> int:
    oracle_path, krion_dir = argv[1:3]
    with open(oracle_path, encoding="utf-8") as fh:
        oracle = json.load(fh)
    records = []
    for name in sorted(os.listdir(krion_dir)):
        if name.endswith(".json"):
            with open(os.path.join(krion_dir, name), encoding="utf-8") as fh:
                records.append(json.load(fh))
    krion: dict = {}
    for tp2s in from_krion(records).values():
        for tp2 in tp2s:              # one tp2 can be listed under several records
            krion.setdefault(tp2_key(tp2.tp2), set()).update(
                c.number for c in tp2.components)
    total = collections.Counter()
    for entry in oracle:
        if entry.get("lang") != 0:
            continue
        weidu = {number for number, _text in entry["components"]}
        known = krion.get(tp2_key(entry["tp2"]))
        if known is None:
            total["mods without a krion64 record"] += 1
            continue
        total["mods"] += 1
        total["components WeiDU lists"] += len(weidu)
        total["also in krion64"] += len(weidu & known)
        total["only WeiDU"] += len(weidu - known)
        total["only krion64"] += len(known - weidu)
        total["identical mods"] += weidu == known
    for key, value in total.items():
        print(f"{key:32} {value}")
    if len(argv) > 3:
        bws_compare(oracle, krion, bws_numbers(argv[3]))
    return 0


def bws_numbers(directory) -> dict:
    """BWS-NG's records: tp2 key -> component numbers (std ones and `muc` choices)."""
    out: dict = {}
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, name), encoding="utf-8-sig") as fh:
                record = json.load(fh)
        except (OSError, ValueError):
            continue
        if (not isinstance(record, dict) or not isinstance(record.get("tp2"), str)
                or not tp2_key(record["tp2"])
                or not isinstance(record.get("components"), dict)):
            continue
        numbers = set()
        for key, value in record["components"].items():
            if isinstance(value, dict) and value.get("type") == "muc":
                numbers.update(int(n) for n in value.get("components") or []
                               if str(n).isdigit())
            elif str(key).isdigit():
                numbers.add(int(key))
        out.setdefault(tp2_key(record["tp2"]), set()).update(numbers)
    return out


def bws_compare(oracle, krion, bws) -> None:
    total = collections.Counter()
    for entry in oracle:
        if entry.get("lang") != 0:
            continue
        weidu = {number for number, _text in entry["components"]}
        key = tp2_key(entry["tp2"])
        if key not in bws:
            continue
        total["BWS-NG mods"] += 1
        total["BWS-NG: of WeiDU's"] += len(weidu)
        total["BWS-NG: present"] += len(weidu & bws[key])
        total["BWS-NG: identical mods"] += weidu == bws[key]
        if key in krion:
            total["all three: mods"] += 1
            total["all three: WeiDU components"] += len(weidu)
            total["all three: krion64 has"] += len(weidu & krion[key])
            total["all three: BWS-NG has"] += len(weidu & bws[key])
            total["all three: union has"] += len(weidu & (krion[key] | bws[key]))
            total["all three: union not in tp2"] += len((krion[key] | bws[key]) - weidu)
    for key, value in total.items():
        print(f"{key:32} {value}")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
