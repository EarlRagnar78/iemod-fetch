#!/usr/bin/env python3
"""
How long the order page's check after a drop takes (GUI-AUDIT M5b item 31).

    python3 tools/order_check_benchmark.py [--data DATA_DIR --log WeiDU.log]
        [--moves N] [--size N] [--json OUT]

Two orders: the EET install of a real log, planned against the data cache's
krion64 order and BWS-NG / krion64 rules (its rule edges are the plan's own),
and a synthetic one of `--size` units
(3,000 by default) with up to three rules each to units placed before them.
On each, `--moves` random drops; for every drop the check limited to the
moved unit (`broken_after_move`, the page's) and the full one
(`broken_pairs`), timed. Printed and with --json written: p50 and p95 in
milliseconds, and how often the two disagreed (always 0, or the page is
wrong).

With --gui (PySide6, offscreen), also the time to the marks on the order
page itself, the synthetic order shown as rows: the check, reading the rows
and painting the rows whose mark changed.
"""
import argparse
import json
import os
import random
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from iemod_fetch.datasync import data_paths  # noqa: E402
from iemod_fetch.ordering import (EET_LOG, OrderIndex, broken_after_move,  # noqa: E402
                                  broken_pairs, plan_order, reverse)
from iemod_fetch.rules import RuleSet  # noqa: E402


def synthetic(size: int, seed: int) -> tuple[list[str], dict[str, set[str]]]:
    rng = random.Random(seed)
    order = [f"u{n}" for n in range(size)]
    before = {node: {order[rng.randrange(n)] for _ in range(rng.randint(0, 3))}
              for n, node in enumerate(order) if n}
    return order, before


def real(data: str, log: str) -> tuple[list[str], dict[str, set[str]]]:
    paths = data_paths(data)
    if not paths.order_catalogue:
        raise SystemExit(f"{data}: no krion64 data in this cache")
    plan = plan_order([(log, EET_LOG)], OrderIndex.load(paths.order_catalogue),
                      RuleSet.load(paths.rules))
    return [unit.node for unit in plan.logs.get(EET_LOG, ())], plan.rule_edges


def measure(order: list[str], before: dict, moves: int, seed: int) -> dict:
    rng = random.Random(seed)
    order = list(order)
    followers = reverse(before)
    breaks = broken_pairs(order, before)
    fast, full, wrong = [], [], 0
    for _ in range(moves):
        node = order.pop(rng.randrange(len(order)))
        order.insert(rng.randrange(len(order) + 1), node)
        started = time.perf_counter()
        breaks = broken_after_move(breaks, order, before, node, followers)
        fast.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        whole = broken_pairs(order, before)
        full.append((time.perf_counter() - started) * 1000)
        wrong += breaks != whole

    def pct(values: list[float]) -> dict:
        cuts = statistics.quantiles(values, n=20)
        return {"p50": round(statistics.median(values), 3), "p95": round(cuts[18], 3)}
    return {"units": len(order), "rule edges": sum(len(v) for v in before.values()),
            "moves": moves, "after a move (ms)": pct(fast), "full check (ms)": pct(full),
            "disagreements": wrong}


def gui(order: list[str], before: dict, moves: int, seed: int) -> dict:
    """The order page's own time to the marks after a drop, offscreen."""
    import tempfile
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QModelIndex
    from PySide6.QtWidgets import QApplication, QListWidget
    from iemod_fetch_gui.pages.order import OrderPage
    _app = QApplication.instance() or QApplication([])
    units = [{"node": n, "name": n, "tp2": f"{n}/{n}.tp2", "key": n, "part": 0,
              "split": False, "category": "", "components": [[f"{n}/{n}.tp2", 0, ""]],
              "constrained": False, "moved": False, "flagged": False,
              "after": sorted(before.get(n, ()))} for n in order]
    result = {"phases": [{"role": "EET", "title": "EET", "units": units}], "cycles": [],
              "violations": [], "planned": True, "custom": False}
    with tempfile.TemporaryDirectory() as folder:
        class Marks(OrderPage):
            def _reordered(self) -> None:       # the marks only: no save, no plan
                pass
        page = Marks(folder, plan=lambda *_args: result)
        page.show_result(result)
        view = page.tabs.widget(0)
        if not isinstance(view, QListWidget):
            raise SystemExit("the order page shows no list")
        rng, times = random.Random(seed), []
        for _ in range(moves):
            view.model().moveRow(QModelIndex(), rng.randrange(len(order)),
                                 QModelIndex(), rng.randrange(len(order) + 1))
            times.append(page.last_check_ms)
    cuts = statistics.quantiles(times, n=20)
    return {"rows": len(order), "drops": moves, "to the marks (ms)": {
        "p50": round(statistics.median(times), 3), "p95": round(cuts[18], 3)}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data", help="iemod-fetch's data cache (--update-data)")
    parser.add_argument("--log", help="a WeiDU.log (its EET install) to plan")
    parser.add_argument("--moves", type=int, default=1000)
    parser.add_argument("--size", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--json")
    parser.add_argument("--gui", action="store_true", help="time the order page too")
    args = parser.parse_args(argv)
    result = {"synthetic": measure(*synthetic(args.size, args.seed), args.moves, args.seed)}
    if args.data and args.log:
        result["log"] = measure(*real(args.data, args.log), args.moves, args.seed)
    if args.gui:
        result["page"] = gui(*synthetic(args.size, args.seed), min(args.moves, 300), args.seed)
    print(json.dumps(result, indent=2))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
    return 1 if any(part.get("disagreements") for part in result.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
