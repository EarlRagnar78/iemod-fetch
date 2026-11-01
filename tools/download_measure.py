"""
How well each download source does on a real selection (ADR-0039), from the
JSON reports of real runs - the measurement the development sandbox could not
make (its proxy refuses third-party repositories).

    python tools/download_measure.py dry-catalogue.json [dry-manifest.json]
        [--real real.json] [--pick N|all]

Prints a Markdown summary: per run, the mods with a downloadable candidate
(planned/ok), with none (manual) and failed, by the candidate's origin, and
each miss with its reason; for a real run also what the player is told (GUI-
AUDIT M7 items 55, 58, 59): a mod installed from a forum post, a newer GitHub
release offered, a link that led to a GitHub repository. `--pick N` prints
instead, one per line, N planned mods of the first report to try for real
(deterministic: sorted by folder); `--pick all`, every one.
"""
import argparse
import collections
import json
import sys


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def summary(title, report):
    records = report.get("records") or []
    unresolved = report.get("unresolved") or []
    # over the run's --max-bytes: the measurement's own cap, not a defect
    by_status = collections.Counter(
        "over the size cap" if "byte ceiling" in str(r.get("detail") or "") else r["status"]
        for r in records)
    by_status["manual"] += len(unresolved)
    by_origin = collections.Counter(r.get("origin") or "-" for r in records
                                    if r["status"] in ("planned", "ok", "skipped"))
    lines = [f"### {title}", "",
             f"{len(records) + len(unresolved)} mods: " + ", ".join(
                 f"{n} {status}" for status, n in sorted(by_status.items()) if n), ""]
    if by_origin:
        lines += ["| candidate origin | mods |", "|---|---|"]
        lines += [f"| {origin} | {n} |" for origin, n in by_origin.most_common()]
        lines.append("")
    misses = [r for r in records if r["status"] not in ("planned", "ok", "skipped")]
    misses += [{"folder": u["folder"], "status": "manual", "detail": u["detail"]}
               for u in unresolved]
    if misses:
        lines += ["<details><summary>misses</summary>", "",
                  "| mod | status | why |", "|---|---|---|"]
        for record in sorted(misses, key=lambda r: r["folder"].lower()):
            why = " ".join(str(record.get("detail") or "").split())[:300]
            lines.append(f"| {record['folder']} | {record['status']} | "
                         f"{why.replace('|', '/')} |")
        lines += ["", "</details>", ""]
    return lines


def signals(report):
    """What a real run told the player beside the mods (items 55, 58, 59)."""
    records = report.get("records") or []
    forum = [r["folder"] for r in records
             if any("forum post" in a for a in r.get("advisories") or ())]
    newer = [(r["folder"], r["newer"]) for r in records if r.get("newer")]
    led = [w for w in report.get("warnings") or () if "on GitHub;" in w]
    lines = ["#### What the player was told", "",
             f"- installed from a forum post: {len(forum)}"
             + (f" ({', '.join(sorted(forum))})" if forum else ""),
             f"- a newer GitHub release offered: {len(newer)}",
             f"- a link that led to a GitHub repository: {len(led)}", ""]
    for folder, offer in sorted(newer):
        lines.append(f"  - {folder}: {offer.get('installed')} -> {offer.get('version')} "
                     f"({offer.get('repo')})")
    if newer:
        lines.append("")
    return lines


def pick_count(value):
    """`--pick`: 'all', or how many (0 or more)."""
    if value == "all":
        return value
    if value.isdigit():
        return int(value)
    raise argparse.ArgumentTypeError(f"a number or 'all', not {value!r}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("reports", nargs="+")
    parser.add_argument("--real")
    parser.add_argument("--pick", type=pick_count, metavar="N|all")
    args = parser.parse_args(argv)
    first = load(args.reports[0])
    if args.pick is not None:
        planned = sorted(r["folder"] for r in first.get("records") or []
                         if r["status"] == "planned")
        if args.pick != "all":
            planned = planned[:args.pick]
        if planned:                     # no line at all for none: a shell reads ""
            print("\n".join(planned))
        return 0
    titles = ["Catalogue only (no manifest, dry run)", "With the manifest (dry run)"]
    out = ["## Download sources, measured", ""]
    for title, path in zip(titles, args.reports, strict=False):
        out += summary(title, load(path))
    if args.real:
        real = load(args.real)
        out += summary("Real download (archive must hold the tp2)", real)
        out += signals(real)
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
