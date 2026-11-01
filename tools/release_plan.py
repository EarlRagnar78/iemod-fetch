#!/usr/bin/env python3
"""
Decide what the release workflow tags, and on which commit (ADR-0027).

Adopted from R-studioConf's ADR-0006: the newest `## [X.Y.Z]` section of
CHANGELOG.md names the release. It is tagged `vX.Y.Z` on the main-line
(first-parent) commit where `iemod_fetch/__init__.py` first says
`__version__ = "X.Y.Z"` - the merge of the release pull request, so every fix
made during its review is in, and nothing merged afterwards is. A tag that
already exists means already released.

When nothing that ships has changed since that commit, the head of main is
released instead: same artifacts, and the only commit GITHUB_TOKEN may tag when
the workflow files have changed since (a token without the `workflows`
permission cannot create a ref whose workflow files differ from the default
branch - softprops/action-gh-release#411). A back-fill that cannot avoid it is
reported as `workflows_differ=true`, so the workflow says what to do instead of
failing with a bare 403.

    python3 tools/release_plan.py [VERSION]

prints `release=`, `tag=`, `sha=` and `workflows_differ=` lines for
$GITHUB_OUTPUT; with no VERSION the newest released section of CHANGELOG.md is
used, then each version in $BACKFILL (comma-separated) still untagged.
`--pull-request` plans the rehearsal of a pull request's own commit. An
explicit VERSION whose tag exists releases that tag on its commit (a
tag pushed by hand runs the tagged commit's own, possibly older, workflow).
"""
import os
import re
import subprocess
import sys

VERSION_FILE = "iemod_fetch/__init__.py"
SHIPPED = ("iemod_fetch", "pyproject.toml", "build.py", "README.md", "LICENSE")
WORKFLOWS = ".github/workflows"
_SECTION = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.MULTILINE)
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def newest_release(changelog: str) -> str | None:
    """The first versioned section; `[Unreleased]` is not a release."""
    match = _SECTION.search(changelog)
    return match.group(1) if match else None


def _git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def release_commit(repo: str, version: str) -> str | None:
    """The oldest first-parent commit whose version file says `version`."""
    wanted = f'__version__ = "{version}"'
    commits = _git(repo, "rev-list", "--first-parent", "--reverse", "HEAD",
                   "--", VERSION_FILE).split()
    for sha in commits:
        text = subprocess.run(["git", "-C", repo, "show", f"{sha}:{VERSION_FILE}"],
                              capture_output=True, text=True, check=False).stdout
        if wanted in text.splitlines():
            return sha
    return None


def _same(repo: str, left: str, right: str, *paths: str) -> bool:
    return subprocess.run(["git", "-C", repo, "diff", "--quiet", left, right,
                           "--", *paths], check=False).returncode == 0


def plan(repo: str, version: str, explicit: bool = False) -> dict[str, str]:
    """`explicit`: asked for by version, so an existing tag is released as is."""
    tag = f"v{version}"
    found = subprocess.run(["git", "-C", repo, "rev-parse", "-q", "--verify",
                            f"refs/tags/{tag}^{{commit}}"], capture_output=True,
                           text=True, check=False)
    if found.returncode == 0:
        if explicit:
            return {"release": "true", "tag": tag, "sha": found.stdout.strip(),
                    "workflows_differ": "false"}
        return {"release": "false", "tag": tag, "sha": "", "workflows_differ": "false"}
    sha = release_commit(repo, version)
    if sha is None:
        raise SystemExit(f"{VERSION_FILE} never says __version__ = \"{version}\" on "
                         f"the main line: bump the version with the changelog")
    head = _git(repo, "rev-parse", "HEAD")
    if _same(repo, sha, head, *SHIPPED):
        sha = head
    differ = not _same(repo, sha, head, WORKFLOWS)
    return {"release": "true", "tag": tag, "sha": sha,
            "workflows_differ": "true" if differ else "false"}


def automatic(repo: str, newest: str, backfill: list[str]) -> dict[str, str]:
    """The newest changelog version; once tagged, the first untagged back-fill."""
    planned = plan(repo, newest)
    for version in backfill:
        if planned["release"] == "true":
            break
        planned = plan(repo, version)
    return planned


def pull_request(repo: str) -> dict[str, str]:
    """A rehearsal on a pull request: its own commit, tagged by its version.

    Build and attestation run, publishing never does. So a change to the
    release workflow, Dependabot's included, is exercised before it merges.
    """
    with open(os.path.join(repo, VERSION_FILE), encoding="utf-8") as fh:
        found = re.search(r'^__version__ = "(\d+\.\d+\.\d+)"', fh.read(), re.MULTILINE)
    if found is None:
        raise SystemExit(f"no __version__ in {VERSION_FILE}")
    return {"release": "true", "tag": f"v{found.group(1)}",
            "sha": _git(repo, "rev-parse", "HEAD"), "workflows_differ": "false"}


def main(argv) -> int:
    if argv[1:] == ["--pull-request"]:
        for key, value in pull_request(".").items():
            print(f"{key}={value}")
        return 0
    explicit = len(argv) > 1
    if explicit:
        version = argv[1].lstrip("v")
    else:
        with open("CHANGELOG.md", encoding="utf-8") as fh:
            found = newest_release(fh.read())
        if found is None:
            print("release=false")
            return 0
        version = found
    backfill = [v.strip().lstrip("v") for v in os.environ.get("BACKFILL", "").split(",")
                if v.strip()]
    for candidate in [version, *backfill]:
        if not _SEMVER.match(candidate):
            raise SystemExit(f"not a version: {candidate!r}")
    planned = (plan(".", version, explicit) if explicit
               else automatic(".", version, backfill))
    for key, value in planned.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
