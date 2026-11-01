#!/usr/bin/env python3
"""
Measure iemod_fetch.readln on real mods (GUI-AUDIT M8 item 48, ADR-0049).

    python3 tools/readln_census.py CORPUS [--json OUT] [--show N]

CORPUS holds one folder per mod checkout (the files WeiDU reads: .tp2, .tpa,
.tph, .tpp, .tra). For every tp2 found, every ACTION_READLN/PATCH_READLN in
the mod's files is counted, and compared with the READLNs the scanner
attributes to a component (or to ALWAYS):

  reached   a READLN some component reaches: in its body, a function or
            macro it launches, or a file it includes
  unreached a READLN in the mod's files no component was found to reach:
            dead code, another tp2's, or a path the scanner could not follow
  tra       a reached READLN whose question is a .tra string found in the
            language (shown in the player's language)
  text      a reached READLN whose question is known at all: a .tra string,
            or a fixed text in the code (English whatever the language);
            `PRINT ~%var%~` is not counted - its text is set elsewhere

What it cannot measure: whether WeiDU really asks a reached READLN (a
condition may skip it) - that takes a real install, which no runner has the
game data for. The real prompts of GUI-AUDIT item 64 are the check on that.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from iemod_fetch.readln import scan, strip_keeping_lines  # noqa: E402

_WEIDU = (".tp2", ".tpa", ".tph", ".tpp", ".tpc", ".tra")
_READLN = re.compile(r"\b(?:ACTION|PATCH)_READLN\b", re.IGNORECASE)


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def load(root: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for base, _dirs, names in os.walk(root):
        if "/.git" in base.replace("\\", "/") + "/":
            continue
        for name in names:
            if name.lower().endswith(_WEIDU):
                path = os.path.join(base, name)
                with open(path, "rb") as fh:
                    files[os.path.relpath(path, root).replace(os.sep, "/")] = _decode(fh.read())
    return files


def readlns(files: dict[str, str]) -> set[tuple[str, int]]:
    out = set()
    for path, text in files.items():
        if path.lower().endswith(".tra"):
            continue
        clean = strip_keeping_lines(text)
        for m in _READLN.finditer(clean):
            out.add((path, clean.count("\n", 0, m.start()) + 1))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("corpus")
    ap.add_argument("--json")
    ap.add_argument("--show", type=int, default=20)
    args = ap.parse_args(argv)
    rows = []
    for mod in sorted(os.listdir(args.corpus)):
        root = os.path.join(args.corpus, mod)
        if not os.path.isdir(root):
            continue
        files = load(root)
        tp2s = [p for p in files if p.lower().endswith(".tp2")]
        present = readlns(files)
        reached: dict[tuple[str, int], dict] = {}
        unread: list[str] = []
        for tp2 in tp2s:
            found = scan(tp2, files)
            unread += found.unread
            for number, prompts in found.components.items():
                for p in prompts:
                    entry = reached.setdefault((p.file, p.line), {
                        "file": p.file, "line": p.line, "ref": p.ref, "text": p.text[:120], "raw": p.raw,
                        "tra": bool(p.ref and p.text),
                        "via": p.via, "conditional": p.conditional, "repeats": p.repeats,
                        "components": []})
                    entry["components"].append(f"{os.path.basename(tp2)}#{number}")
        rows.append({"mod": mod, "tp2s": len(tp2s), "readlns": len(present),
                     "reached": len(reached),
                     "resolved": sum(1 for r in reached.values() if r["text"]),
                     "tra": sum(1 for r in reached.values() if r["tra"]),
                     "unreached": sorted(f"{f}:{n}" for f, n in present - set(reached)),
                     "prompts": list(reached.values()),
                     "unread": sorted(set(unread))})
    with_q = [r for r in rows if r["readlns"]]
    total = sum(r["readlns"] for r in rows)
    reach = sum(r["reached"] for r in rows)
    res = sum(r["resolved"] for r in rows)
    tra = sum(r["tra"] for r in rows)
    print(f"{len(rows)} mods, {len(with_q)} with a READLN; {total} READLNs in their files, "
          f"{reach} reached from a component ({reach / total:.0%})" if total else
          f"{len(rows)} mods, no READLN")
    if reach:
        print(f"question known for {res} of {reach} reached ({res / reach:.0%}): "
              f"{tra} a .tra string in the language, {res - tra} a fixed text in the code")
    for r in with_q[:args.show]:
        print(f"\n{r['mod']}: {r['readlns']} READLN, {r['reached']} reached, "
              f"{r['resolved']} with text; unreached {len(r['unreached'])}")
        for p in r["prompts"][:6]:
            flags = ",".join(k for k in ("conditional", "repeats") if p[k])
            print(f"  {p['components'][0]:28} {p['ref'] or '-':7} {flags:20} {p['text'][:70]}")
        for u in r["unread"][:3]:
            print(f"  unread: {u}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
