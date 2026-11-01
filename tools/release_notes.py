#!/usr/bin/env python3
"""
Release notes from CHANGELOG.md, and kept in step with it (ADR-0027).

    python3 tools/release_notes.py notes VERSION   # print the section
    python3 tools/release_notes.py sync            # fix published bodies
    python3 tools/release_notes.py latest          # "Latest" on the newest release

`sync` runs in the release workflow on every push to main that touches the
changelog: each `## [X.Y.Z]` section with a published release vX.Y.Z is
compared with that release's body, and a body that no longer matches is
rebuilt from the section. The "Verify this download" block the release was
built with is kept, since its digest belongs to the artifacts. Editing a
release creates no ref, so GITHUB_TOKEN may do it.

`latest` makes the newest version of CHANGELOG.md that has a published
release GitHub's "Latest". A back-fill's tag, created with RELEASE_TOKEN,
starts the tagged commit's own release workflow; an older one judges "Latest"
from its own changelog, and on 2026-10-31 v4.0.0's tag run made 4.0.0 Latest
over 4.0.1. That run cannot be changed afterwards; this puts it right at
release-latest.yml's six-hourly run, and at the next push to main that changes
CHANGELOG.md or the version (release.yml's notes job).
"""
import re
import subprocess
import sys

VERIFY = "\n\n### Verify this download"
_HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.MULTILINE)


def versions(changelog: str) -> list[str]:
    return _HEADING.findall(changelog)


def section(changelog: str, version: str) -> str | None:
    match = re.search(rf"^## \[{re.escape(version)}\].*?$(.*?)(?=^## \[|\Z)",
                      changelog, re.DOTALL | re.MULTILINE)
    return match.group(1).strip() if match else None


def refreshed(body: str, text: str) -> str | None:
    """The body `text` calls for, or None when it already says that."""
    cut = body.find(VERIFY)
    wanted = text + (body[cut:] if cut >= 0 else "")
    return None if wanted.strip() == body.strip() else wanted


def _gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=False)


def sync(changelog: str) -> int:
    for version in versions(changelog):
        tag = f"v{version}"
        shown = _gh("release", "view", tag, "--json", "body", "--jq", ".body")
        if shown.returncode != 0:
            continue                                   # not released (yet)
        wanted = refreshed(shown.stdout.rstrip("\n"), section(changelog, version) or "")
        if wanted is None:
            continue
        edited = subprocess.run(["gh", "release", "edit", tag, "--notes-file", "-"],
                                input=wanted, text=True, check=False)
        if edited.returncode != 0:
            return edited.returncode
        print(f"{tag}: notes updated from CHANGELOG.md")
    return 0


def newest_released(changelog: str, released) -> str | None:
    """The first version, newest first, that `released(tag)` says is out."""
    return next((f"v{v}" for v in versions(changelog) if released(f"v{v}")), None)


def published_tags() -> set[str] | None:
    """Every published release's tag (not a draft, not a prerelease), read in
    one call so the answer cannot change half way; None when GitHub did not
    answer - never "not released", which would demote the true Latest."""
    listed = _gh("api", "--paginate", "repos/{owner}/{repo}/releases",
                 "--jq", ".[] | select((.draft or .prerelease) | not) | .tag_name")
    if listed.returncode != 0:
        print(listed.stderr, file=sys.stderr)
        return None
    return {line.strip() for line in listed.stdout.splitlines() if line.strip()}


def latest(changelog: str) -> int:
    tags = published_tags()
    if tags is None:
        return 1                                   # say so; never guess
    tag = newest_released(changelog, tags.__contains__)
    if tag is None:
        return 0
    now = _gh("api", "repos/{owner}/{repo}/releases/latest", "--jq", ".tag_name")
    current = now.stdout.strip() if now.returncode == 0 else ""
    if current == tag:
        return 0
    edited = _gh("release", "edit", tag, "--latest")
    if edited.returncode != 0:
        print(edited.stderr, file=sys.stderr)
        return edited.returncode
    print(f"{tag}: marked Latest (was {current or 'none'})")
    return 0


def main(argv) -> int:
    with open("CHANGELOG.md", encoding="utf-8") as fh:
        changelog = fh.read()
    if len(argv) == 3 and argv[1] == "notes":
        version = argv[2].lstrip("v")
        print(section(changelog, version) or f"See CHANGELOG.md for {version}.")
        return 0
    if len(argv) == 2 and argv[1] == "sync":
        return sync(changelog)
    if len(argv) == 2 and argv[1] == "latest":
        return latest(changelog)
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
