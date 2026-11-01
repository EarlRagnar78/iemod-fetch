"""
CHANGELOG.md is the release notes (ADR-0027): each `## [X.Y.Z]` section is
published as is. A text edit that cut the start of a bullet published
"`: walk the plan the way WeiDU will run it.**`" in the 2.2.0 notes.
"""
import os
import re

CHANGELOG = os.path.join(os.path.dirname(__file__), os.pardir, "CHANGELOG.md")


def lines():
    with open(CHANGELOG, encoding="utf-8") as fh:
        return fh.read().splitlines()


def test_no_line_starts_with_the_stump_of_a_cut_bullet():
    stumps = [(n, line) for n, line in enumerate(lines(), 1)
              if re.match(r"^[:;,.)\]]", line)]
    assert stumps == []


def test_bold_markers_pair_up_within_each_bullet():
    bullet, unpaired = [], []
    for n, line in enumerate(lines() + ["- end"], 1):
        if line.startswith(("- ", "#")) or not line.strip():
            text = " ".join(bullet)
            if text.count("**") % 2:
                unpaired.append((n, text[:60]))
            bullet = [line] if line.startswith("- ") else []
        elif bullet:
            bullet.append(line)
    assert unpaired == []
