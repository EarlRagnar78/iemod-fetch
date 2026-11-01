#!/usr/bin/env python3
"""
Ground truth for tools/tra_benchmark.py: WeiDU's own component names.

    python3 tools/tra_oracle.py WEIDU MODS_DIR ORACLE.json

MODS_DIR holds one directory per mod repository. For every .tp2 in it and
every LANGUAGE it declares, this runs `WEIDU --nogame --list-components TP2 N`
from the directory WeiDU would run in - the parent of the mod folder - and
records what WeiDU printed. For language 0 it also records
`--list-components-json` (number, name, subgroup, group, label, forced), the
source of truth for everything but the printed name. No game is needed and
nothing is installed.
"""
import json
import os
import re
import subprocess
import sys

LINE = re.compile(r"^~(?P<tp2>[^~]+)~\s+#(?P<lang>\d+)\s+#(?P<comp>-?\d+)\s+//\s?(?P<text>.*)$")
LANGUAGE = re.compile(r"^\s*LANGUAGE\b", re.IGNORECASE | re.MULTILINE)
MAX_LANGUAGES = 12


def runs(mods_dir: str):
    """(game directory, tp2 relative to it) for every tp2 under each repository."""
    for repo in sorted(os.listdir(mods_dir)):
        base = os.path.join(mods_dir, repo)
        for dirpath, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d != ".git")
            for name in sorted(files):
                if not name.lower().endswith(".tp2"):
                    continue
                rel_dir = os.path.relpath(dirpath, base)
                parent = os.path.dirname(rel_dir) if rel_dir != "." else ""
                game = os.path.join(base, parent) if parent else base
                yield repo, game, os.path.relpath(os.path.join(dirpath, name), game)


def _json(weidu: str, game: str, tp2: str):
    try:
        result = subprocess.run([weidu, "--nogame", "--list-components-json", tp2, "0"],
                                cwd=game, capture_output=True, timeout=60, check=False)
    except subprocess.TimeoutExpired:
        return None
    text = result.stdout.decode("latin-1")
    start, end = text.find("[{"), text.rfind("}]")
    if start < 0 or end < start:
        return None
    try:
        return json.loads(text[start:end + 2])
    except ValueError:
        return None


def main(argv) -> int:
    weidu, mods_dir, out_path = argv[1:4]
    out = []
    for repo, game, tp2 in runs(mods_dir):
        with open(os.path.join(game, tp2), encoding="latin-1") as fh:
            count = max(1, len(LANGUAGE.findall(fh.read())))
        for lang in range(min(count, MAX_LANGUAGES)):
            try:
                result = subprocess.run(
                    [weidu, "--nogame", "--list-components", tp2, str(lang)],
                    cwd=game, capture_output=True, text=True, timeout=60,
                    encoding="latin-1", check=False)
            except subprocess.TimeoutExpired:
                continue
            components = []
            for line in result.stdout.split("\n"):       # not splitlines: 0x85 is text
                match = LINE.match(line.rstrip("\r").strip(" "))
                if match and int(match.group("lang")) == lang:
                    components.append([int(match.group("comp")), match.group("text")])
            entry = {"repo": repo, "game": game, "tp2": tp2, "lang": lang,
                     "components": components}
            if lang == 0:
                entry["json"] = _json(weidu, game, tp2)
            out.append(entry)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=0)
    lines = sum(len(o["components"]) for o in out)
    print(f"{len(out)} runs, {lines} component lines")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
