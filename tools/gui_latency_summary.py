"""
What held the wizard's event loop: the traces of the M3 end-to-end test
(tests/gui/test_m3_end_to_end.py, run with IEMOD_LATENCY_TRACE) lined up.

For every run: its longest gap. For every gap over --over ms, in any run:
the garbage collections that overlapped it (with their generation and
length), the last two events the download sent before it and those it sent
during it (stamped in the download's thread, when sent), and how many events
the window took in during it (stamped when handled). A gap a collection
covers was the collector holding the GIL. A gap during which the download
kept sending, with no collection, was the window's thread waiting while the
worker ran; one with nothing sent either was every thread held (or the
runner not scheduling the process). Where the run held the loop past 40 ms,
faulthandler's watchdog (a C thread, no GIL needed) wrote every thread's
stack at that moment to <trace>.stacks.txt, shown after the run: what the
download, the test's own HTTP server (in the same process) and the window
were each running while the window waited.

    python tools/gui_latency_summary.py trace-*.json --over 50
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys


def explain(path: str, over_s: float) -> tuple[float, list[str]]:
    with open(path, encoding="utf-8") as fh:
        trace = json.load(fh)
    gaps = trace["gaps"]
    if not gaps:
        return 0.0, [f"{path}: no gap measured"]
    lines = []
    for end, gap in gaps:
        if gap < over_s:
            continue
        start = end - gap
        held = [(b, e, g) for b, e, g in trace["collections"] if b < end and e > start]
        before = [ev for ev in trace["events"] if ev[0] <= start][-2:]
        inside = [ev for ev in trace["events"] if start < ev[0] <= end]
        taken = sum(1 for t in trace.get("handled", []) if start < t <= end)
        lines.append(f"  gap {gap * 1000:.0f} ms")
        if held:
            for b, e, g in held:
                lines.append(f"    gc gen {g}: {(e - b) * 1000:.0f} ms, "
                             f"{max(0.0, min(e, end) - max(b, start)) / gap:.0%} of the gap")
        else:
            lines.append("    no garbage collection overlapped it")
        for when, what in (("sent before", before), ("sent during", inside)):
            for t, kind, folder in what:
                lines.append(f"    {when}: {kind} {folder} at {(t - start) * 1000:+.0f} ms")
        lines.append(f"    handled by the window during it: {taken} event(s)")
    return max(gap for _end, gap in gaps), lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("traces", nargs="+")
    parser.add_argument("--over", type=float, default=50.0, help="explain gaps over this (ms)")
    parser.add_argument("--limit", type=float, default=100.0, help="the test's limit (ms)")
    parser.add_argument("--stack-lines", type=int, default=60,
                        help="lines of each run's stack dump to show")
    args = parser.parse_args(argv)
    worst = []
    for path in args.traces:
        top, lines = explain(path, args.over / 1000)
        worst.append(top)
        print(f"{path}: longest gap {top * 1000:.1f} ms")
        print("\n".join(lines))
        try:
            with open(path + ".stacks.txt", encoding="utf-8", errors="replace") as fh:
                stacks = fh.read().strip()
        except OSError:
            stacks = ""
        if stacks:
            print("  stacks while the loop was held:")
            print("\n".join("    " + line for line in stacks.splitlines()[:args.stack_lines]))
    over = sum(1 for w in worst if w * 1000 >= args.limit)
    print(f"\n{len(worst)} runs; longest gap median {statistics.median(worst) * 1000:.1f} ms, "
          f"max {max(worst) * 1000:.1f} ms; {over} over {args.limit:.0f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
