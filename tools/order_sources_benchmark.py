#!/usr/bin/env python3
"""
What each community source says about the KIND of a mod and its install place
(GUI-AUDIT M5 item 25, ADR-0041), measured on their real files.

    python3 tools/order_sources_benchmark.py KRION_DATA_DIR BWS_DATA_DIR \
        LCC_MODS_JSON [--log WeiDU.log] [--json OUT]

KRION_DATA_DIR is krion64's data/ (the Infinity Mod Forge's: categories.json,
mods/*.json); BWS_DATA_DIR is BigWorldSetup-NG's data/ (mods/*.json with their
categories, games/eet.json with its install sequences); LCC_MODS_JSON is
lcc-docs' db/mods.json. Mods are matched by tp2 name, as the plan does
(`ordering.tp2_key`).

Printed, and with --json written:
- per source: the mods it classifies, by category; krion64's components filed
  apart from their mod (`cat`) and its free-form tags;
- the overlap of the three by tp2, and for the mods both krion64 and another
  source classify, which of krion64's install categories each of the other's
  categories falls in (the mapping item 27 needs);
- BWS-NG's install sequence for EET's BG2 phase against krion64's order
  (category rank, then position): over the components both place, the share
  of pairs they order the other way round;
- with --log, the same for a real WeiDU.log: how many of its mods and
  components each source places, how many neither does, and the pairwise
  disagreement of each source with the log. The log's first lines are
  printed: a log written by a tool (Infinity Mod Forge, BWS) is that tool's
  order, not an independent one.

Read-only; nothing is downloaded. A record that cannot be read is skipped and
counted.
"""
import argparse
import collections
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from iemod_fetch.ordering import OrderIndex, name_key, tp2_key  # noqa: E402

Key = tuple[str, int]                     # (tp2 key, component number)
# BWS-NG's sequence lists WeiDU itself and its helpers; they are not mods
TOOLS = {"weidu", "weidu64", "weidufilechangelog", "eekeeper"}
LOG_LINE = re.compile(r"^\s*~([^~]+)~\s*#\d+\s*#(\d+)")


def _json(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------------ sources

def krion(data_dir: str) -> dict:
    """krion64's categories per mod, components filed apart, tags, order."""
    index = OrderIndex.load(data_dir)
    mods, apart, tags, skipped = {}, 0, collections.Counter(), 0
    for path in sorted(glob.glob(os.path.join(data_dir, "mods", "*.json"))):
        try:
            record = _json(path)
        except (OSError, ValueError):
            skipped += 1
            continue
        if not isinstance(record, dict):
            skipped += 1
            continue
        for tag in record.get("tags") or []:
            if isinstance(tag, str):
                tags[tag] += 1
        for co in record.get("co") or []:
            if isinstance(co, dict) and co.get("cat") and co.get("cat") != record.get("c"):
                apart += 1
        names = {co.get("wp") for co in record.get("co") or []
                 if isinstance(co, dict) and isinstance(co.get("wp"), str)}
        names.add(str(record.get("t") or ""))
        for name in filter(None, names):
            mods.setdefault(name_key(name), record.get("c"))
    return {"index": index, "mods": mods, "categories": list(index.categories),
            "apart": apart, "tags": tags, "skipped": skipped}


def bws(data_dir: str) -> dict:
    """BWS-NG's categories per mod and EET's BG2-phase install sequence."""
    mods, skipped = {}, 0
    for path in sorted(glob.glob(os.path.join(data_dir, "mods", "*.json"))):
        try:
            record = _json(path)
        except (OSError, ValueError):
            skipped += 1
            continue
        if not isinstance(record, dict) or not record.get("tp2"):
            skipped += 1
            continue
        mods[name_key(str(record["tp2"]))] = tuple(record.get("categories") or ())
    sequence: dict[Key, int] = {}
    eet = os.path.join(data_dir, "games", "eet.json")
    if os.path.isfile(eet):
        for part in _json(eet).get("sequences") or []:
            if isinstance(part, dict) and part.get("game") == "bg2ee":
                for entry in part.get("order") or []:
                    mod, _, number = str(entry).rpartition(":")
                    if mod and number.isdigit():
                        # a component listed twice keeps its first place
                        sequence.setdefault((name_key(mod), int(number)), len(sequence))
    return {"mods": mods, "sequence": sequence, "skipped": skipped}


EE_GAMES = {"BGEE", "SOD", "BG2EE", "EET"}


def lcc(path: str) -> dict:
    """lcc-docs' categories per mod for the Enhanced Edition games (one record
    may name several tp2s)."""
    payload = _json(path)
    records = payload.get("mods") if isinstance(payload, dict) else payload
    mods = {}
    for record in records or []:
        if not isinstance(record, dict):
            continue
        if not EE_GAMES & {str(g).upper() for g in record.get("games") or []}:
            continue
        for part in re.split(r"[;,]", str(record.get("tp2") or "")):
            name = part.strip()
            if name and name.lower() != "non-weidu":
                mods.setdefault(name_key(name), tuple(record.get("categories") or ()))
    return {"mods": mods}


# ------------------------------------------------------------------ measures

def disagreement(order_a: list[int], order_b: list[int]) -> tuple[int, int]:
    """Pairs two orders of the same items put the other way round, and pairs.
    A pair order_b ties (krion64 gives every component of a mod one place) is
    counted, and never as reversed: see `ties` for the share without them."""
    assert len(order_a) == len(order_b)
    pairs = sorted(zip(order_a, order_b, strict=True))
    values = [b for _, b in pairs]
    return _inversions(values), len(values) * (len(values) - 1) // 2


def ties(order_b: list[int]) -> int:
    """Pairs order_b puts at the same place."""
    return sum(n * (n - 1) // 2 for n in collections.Counter(order_b).values())


def _inversions(values: list[int]) -> int:
    """Inversions by merge sort: O(n log n) on thousands of components."""
    if len(values) < 2:
        return 0
    mid = len(values) // 2
    left, right = values[:mid], values[mid:]
    count = _inversions(left) + _inversions(right)
    merged, i, j = [], 0, 0
    while i < len(left) and j < len(right):
        if left[i] <= right[j]:
            merged.append(left[i])
            i += 1
        else:
            merged.append(right[j])
            count += len(left) - i
            j += 1
    merged += left[i:] + right[j:]
    values[:] = merged
    return count


def krion_position(index: OrderIndex, key: Key) -> tuple[int, int] | None:
    slot = index.component(*key) or index.get(key[0])
    return (slot.rank, slot.ord) if slot else None


def mapping(other: dict[str, tuple], krion_mods: dict[str, str | None]) -> dict:
    table: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for key, categories in other.items():
        target = krion_mods.get(key)
        if target is None:
            continue
        for category in categories or ("(none)",):
            table[str(category)][target] += 1
    return {cat: dict(counter.most_common()) for cat, counter in sorted(table.items())}


def read_log(path: str) -> tuple[list[str], list[Key]]:
    head, rows = [], []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("//") and len(head) < 4:
                head.append(line.rstrip())
            match = LOG_LINE.match(line)
            if match:
                rows.append((tp2_key(match.group(1)), int(match.group(2))))
    return head, rows


def measure(k: dict, b: dict, lc: dict, log: str | None) -> dict:
    index = k["index"]
    out: dict = {
        "krion64": {"mods": len(k["mods"]), "skipped": k["skipped"],
                    "by_category": dict(collections.Counter(k["mods"].values()).most_common()),
                    "components_filed_apart": k["apart"],
                    "tags": dict(k["tags"].most_common())},
        "bws_ng": {"mods": len(b["mods"]), "skipped": b["skipped"],
                   "by_category": dict(collections.Counter(
                       c for cats in b["mods"].values() for c in cats).most_common()),
                   "eet_bg2_sequence": len(b["sequence"])},
        "lcc_docs": {"mods": len(lc["mods"]),
                     "by_category": dict(collections.Counter(
                         c for cats in lc["mods"].values() for c in cats).most_common())},
    }
    kk, bk, lk = set(k["mods"]), set(b["mods"]), set(lc["mods"])
    out["overlap"] = {"krion64_and_bws": len(kk & bk), "krion64_and_lcc": len(kk & lk),
                      "bws_and_lcc": len(bk & lk), "all_three": len(kk & bk & lk),
                      "lcc_not_krion64": len(lk - kk), "bws_not_krion64": len(bk - kk)}
    out["mapping_to_krion64"] = {"bws_ng": mapping(b["mods"], k["mods"]),
                                 "lcc_docs": mapping(lc["mods"], k["mods"])}
    both = [(key, pos, krion_position(index, key)) for key, pos in b["sequence"].items()]
    both = [(key, pos, kp) for key, pos, kp in both if kp is not None]
    flat = [kp[0] * 100000 + kp[1] for _, _, kp in both]
    inv, pairs = disagreement([pos for _, pos, _ in both], flat)
    tied = ties(flat)
    out["bws_vs_krion64"] = {"components_both_place": len(both), "pairs": pairs,
                             "reversed": inv, "share": round(inv / pairs, 4) if pairs else None,
                             "tied_in_krion64": tied,
                             "share_without_ties": (round(inv / (pairs - tied), 4)
                                                    if pairs > tied else None)}
    seq_mods = sorted({key for key, _ in b["sequence"]})
    unplaced = [m for m in seq_mods if index.get(m) is None]
    out["bws_sequence_mods"] = {
        "mods": len(seq_mods),
        "not_placed_by_krion64": [m for m in unplaced if m not in TOOLS],
        "tools_left_out": [m for m in unplaced if m in TOOLS]}
    if log:
        head, rows = read_log(log)
        mods = list(dict.fromkeys(key for key, _ in rows))
        kpos = [krion_position(index, key) for key in rows]
        bpos = [b["sequence"].get(key) for key in rows]
        result = {"head": head, "components": len(rows), "mods": len(mods)}
        for name, positions in (("krion64", kpos), ("bws_ng", bpos)):
            placed = [(i, p) for i, p in enumerate(positions) if p is not None]
            flat = [p[0] * 100000 + p[1] if isinstance(p, tuple) else p for _, p in placed]
            inv, pairs = disagreement([i for i, _ in placed], flat)
            result[name] = {"components_placed": len(placed),
                            "mods_placed": len({rows[i][0] for i, _ in placed}),
                            "pairs": pairs, "reversed_vs_log": inv,
                            "share": round(inv / pairs, 4) if pairs else None}
        neither = [m for m in mods if index.get(m) is None
                   and not any(key[0] == m for key in b["sequence"])]
        result["mods_placed_by_neither"] = neither
        out["log"] = result
    return out


def render(result: dict, stream) -> None:
    w = stream.write
    for name in ("krion64", "bws_ng", "lcc_docs"):
        src = result[name]
        w(f"{name}: {src['mods']} mods classified\n")
        for cat, n in list(src["by_category"].items())[:30]:
            w(f"  {n:5}  {cat}\n")
    w(f"krion64 components filed apart from their mod (cat): "
      f"{result['krion64']['components_filed_apart']}\n")
    w(f"BWS-NG EET BG2-phase sequence: {result['bws_ng']['eet_bg2_sequence']} components\n")
    w(f"overlap by tp2: {json.dumps(result['overlap'])}\n")
    for name, table in result["mapping_to_krion64"].items():
        w(f"{name} category -> krion64 install category (mods both classify):\n")
        for cat, targets in table.items():
            top = ", ".join(f"{t} {n}" for t, n in list(targets.items())[:4])
            w(f"  {cat}: {top}\n")
    bk = result["bws_vs_krion64"]
    w(f"BWS-NG sequence vs krion64 order: {bk['components_both_place']} components both "
      f"place, {bk['reversed']} of {bk['pairs']} pairs the other way round ({bk['share']}; "
      f"{bk['share_without_ties']} without the {bk['tied_in_krion64']} pairs krion64 ties)\n")
    sq = result["bws_sequence_mods"]
    w(f"BWS-NG sequence: {sq['mods']} mods; {len(sq['not_placed_by_krion64'])} krion64 does "
      f"not place ({', '.join(sq['not_placed_by_krion64'])}); tools left out: "
      f"{', '.join(sq['tools_left_out'])}\n")
    if "log" in result:
        lg = result["log"]
        w("log: " + " | ".join(lg["head"]) + "\n")
        w(f"log: {lg['mods']} mods, {lg['components']} components\n")
        for name in ("krion64", "bws_ng"):
            s = lg[name]
            w(f"  {name}: places {s['mods_placed']} mods / {s['components_placed']} components; "
              f"{s['reversed_vs_log']} of {s['pairs']} pairs reversed vs the log ({s['share']})\n")
        w(f"  placed by neither: {len(lg['mods_placed_by_neither'])}: "
          f"{', '.join(lg['mods_placed_by_neither'][:40])}\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("krion")
    parser.add_argument("bws")
    parser.add_argument("lcc")
    parser.add_argument("--log")
    parser.add_argument("--json")
    args = parser.parse_args(argv)
    result = measure(krion(args.krion), bws(args.bws), lcc(args.lcc), args.log)
    render(result, sys.stdout)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
