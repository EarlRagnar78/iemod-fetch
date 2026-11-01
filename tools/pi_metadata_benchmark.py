#!/usr/bin/env python3
"""
What the authors' own metadata inis add to the install order (ADR-0037).

    python3 tools/pi_metadata_benchmark.py MODS_DIR KRION_DATA_DIR RULES...

MODS_DIR holds one git clone per mod (sparse clones work: the ini is read from
the index with `git show`, never checked out). For every tp2, the Project
Infinity metadata ini beside it (`<tp2 name>.ini`, with or without `setup-`,
any case) is read with the tool's own parser, and its Before/After become
ordered pairs. Each pair is compared with krion64's install order
(KRION_DATA_DIR: categories.json + mods/) and with the order rules in RULES
(BWS-NG's data/rules, krion64's data/mods): does the order agree, does a rule
already say the same, or is the pair known only to the author?
"""
import collections
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from iemod_fetch.modmeta import parse_metadata_ini  # noqa: E402
from iemod_fetch.naming import normalize_key  # noqa: E402
from iemod_fetch.ordering import OrderIndex, tp2_key  # noqa: E402
from iemod_fetch.rules import ORDER, RuleSet  # noqa: E402

GIT_ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0")


def inis(mods_dir):
    """(tp2 path, ini text) for every metadata ini in the clones."""
    for repo in sorted(os.listdir(mods_dir)):
        root = os.path.join(mods_dir, repo)
        listed = subprocess.run(["git", "-C", root, "ls-files"], capture_output=True,
                                text=True, check=False).stdout.splitlines()
        by_lower = {name.lower(): name for name in listed}
        for name in listed:
            if not name.lower().endswith(".tp2"):
                continue
            folder, stem = os.path.split(name[:-4])
            stems = [stem] + ([stem[6:]] if stem.lower().startswith("setup-") else [])
            for candidate in stems:
                real = by_lower.get(os.path.join(folder, candidate + ".ini").lower())
                if not real:
                    continue
                text = subprocess.run(["git", "-C", root, "show", f"HEAD:{real}"],
                                      capture_output=True, check=False,
                                      env=GIT_ENV).stdout.decode("utf-8", "replace")
                if "[metadata]" in text.lower():
                    yield name, text
                    break


def main(argv) -> int:
    if len(argv) < 4:
        print(__doc__)
        return 2
    mods_dir, krion, rule_paths = argv[1], argv[2], argv[3:]
    index = OrderIndex.load(krion)
    said: dict = {}
    for rule in RuleSet.load(rule_paths).rules:
        if rule.kind != ORDER or rule.direction not in ("before", "after"):
            continue
        for other in rule.right:
            first, second = ((rule.left.mod, other.mod) if rule.direction == "before"
                             else (other.mod, rule.left.mod))
            said.setdefault(frozenset((first, second)), set()).add((first, second))
    pairs, files = set(), 0
    for tp2, text in inis(mods_dir):
        files += 1
        me = tp2_key(tp2)
        meta = parse_metadata_ini(text, source=tp2)
        pairs.update((me, normalize_key(o)) for o in meta.before if normalize_key(o))
        pairs.update((normalize_key(o), me) for o in meta.after if normalize_key(o))
    print(f"metadata inis: {files}; order pairs they state: {len(pairs)}")
    tally = collections.Counter()
    alone = []
    for first, second in sorted(pairs):
        rules = said.get(frozenset((first, second)), set())
        rule = ("a rule agrees" if (first, second) in rules and (second, first) not in rules
                else "a rule disagrees" if rules and (first, second) not in rules
                else "rules disagree with each other" if rules else "no rule")
        a, b = index.get(first), index.get(second)
        if not a or not b:
            order = "krion64 does not place both"
        elif a.pre_eet != b.pre_eet:
            order = "different game phases"
        elif (a.rank, a.ord) < (b.rank, b.ord):
            order = "krion64's order agrees"
        elif (a.rank, a.ord) == (b.rank, b.ord):
            order = "krion64 gives the same slot"
        else:
            order = "krion64's order contradicts"
        tally[(order, rule)] += 1
        if order != "krion64's order agrees" and rule == "no rule" \
                and order != "different game phases":
            alone.append(f"{first} before {second} ({order})")
    for (order, rule), count in sorted(tally.items()):
        print(f"  {order}; {rule}: {count}")
    print(f"known only to the authors' inis: {len(alone)}")
    for line in alone:
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
