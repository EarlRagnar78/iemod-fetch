#!/usr/bin/env python3
"""
Compare the pinned WeiDU and mod_installer with upstream (ADR-0028).

Dependabot cannot see these pins: WeiDU is a release zip with a sha256 and
mod_installer a commit, both in ci.yml's `real-weidu` job. This compares them
with upstream and opens one issue per tool that is behind. It never opens a
pull request: a new digest has to be checked by a person. This is the method of
Proxmox_biome_log_collector's upstream-versions.yml.

    python3 tools/upstream_versions.py     # needs gh, GH_TOKEN; exit 1 = behind

Upstream, read through the GitHub API:
* WeiDU: the newest WeiDUorg/weidu tag that is a release (vNNN.NN). Nightlies
  and release candidates are left out.
* mod_installer: `version` in Cargo.toml on dark0dave/mod_installer's default
  branch. Its git tags stop at v12.1.1, so the version is the only signal.
* Python (ADR-0043): the newest stable minor in actions/python-versions'
  manifest - what setup-python can install - against .python-version; and
  every place that names the version (requires-python, ruff, mypy, the
  classifiers, `iemod_fetch.PYTHON`, a literal `python-version:` left in a
  workflow) against .python-version. Dependabot never updates
  `python-version` (dependabot-core's github_actions parser reads only
  `uses:`), so this is where a new Python is noticed. It opens an issue,
  never a pull request: the move is made once a full build passes on it.
"""
import base64
import glob
import json
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from collections.abc import Iterable

CI = ".github/workflows/ci.yml"
_WEIDU_PIN = re.compile(r"WEIDU_URL:\s*\S*/releases/download/v(\d+\.\d+)/")
_MI_PIN = re.compile(r"MOD_INSTALLER_VERSION:\s*\"?(\d+\.\d+\.\d+)\"?")
_WEIDU_TAG = re.compile(r"^v(\d+\.\d+)$")
_CARGO_VERSION = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)

NAMES = {"weidu": "WeiDU", "mod_installer": "mod_installer"}
WHERE = {"weidu": "https://github.com/WeiDUorg/weidu/releases",
         "mod_installer": "https://github.com/dark0dave/mod_installer"}


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def pinned(ci_yaml: str) -> dict[str, str]:
    out = {}
    weidu, installer = _WEIDU_PIN.search(ci_yaml), _MI_PIN.search(ci_yaml)
    if weidu:
        out["weidu"] = weidu.group(1)
    if installer:
        out["mod_installer"] = installer.group(1)
    return out


def newest_weidu(tags: Iterable[str]) -> str | None:
    releases = [m.group(1) for m in map(_WEIDU_TAG.match, tags) if m]
    return max(releases, key=_key) if releases else None


@dataclass
class Verdict:
    tool: str
    pinned: str
    latest: str

    @property
    def title(self) -> str:
        return f"{NAMES[self.tool]} {self.latest} is available (pinned {self.pinned})"

    @property
    def body(self) -> str:
        return (f"Upstream: {WHERE[self.tool]}\n\n"
                "To bump (docs/RELEASING.md, \"Pinned test toolchain\"):\n\n"
                + ("1. Download `WeiDU-Linux-<version>.zip` from the release yourself "
                   "and run `sha256sum`.\n2. Update `WEIDU_URL` and `WEIDU_SHA256` in "
                   "`.github/workflows/ci.yml`.\n"
                   if self.tool == "weidu" else
                   "1. Pick the commit whose Cargo.toml says the new version and read "
                   "its changes (command line, EET mode).\n2. Update `MOD_INSTALLER_REV` "
                   "and `MOD_INSTALLER_VERSION` in `.github/workflows/ci.yml`, and `REV` "
                   "and `VERSION` in `packaging/mod_installer.py` (the wizard's bundle, "
                   "ADR-0046). If upstream released it, consider retiring the build.\n")
                + "3. CI green - the real-WeiDU job installs the mock EET plan with it.\n")


def verdicts(pins: dict[str, str], latest: dict[str, str]) -> list[Verdict]:
    return [Verdict(tool, pins[tool], latest[tool]) for tool in ("weidu", "mod_installer")
            if tool in pins and latest.get(tool)
            and _key(latest[tool]) > _key(pins[tool])]


# ------------------------------------------------------------------ Python
MANIFEST = "https://raw.githubusercontent.com/actions/python-versions/main/versions-manifest.json"
_WORKFLOW_PYTHON = re.compile(r"""python-version\s*:\s*\[?\s*["']?([^"'\s,}\]#]+)""")
_STABLE = re.compile(r"^3\.(\d+)\.(\d+)$")


def newest_python(manifest: list) -> str | None:
    """The newest minor (3.N) with a stable, final release in the manifest."""
    minors = [int(m.group(1)) for m in
              (_STABLE.match(str(entry.get("version", ""))) for entry in manifest
               if entry.get("stable"))
              if m]
    return f"3.{max(minors)}" if minors else None


def python_places(root: str = ".") -> dict[str, str]:
    """Every place that names the project's Python, and what it names
    ("" where it names none it should, "several" where it names more than
    one)."""
    def read(path: str) -> str:
        with open(os.path.join(root, path), encoding="utf-8") as fh:
            return fh.read()
    project = read("pyproject.toml")
    found: dict[str, str] = {".python-version": read(".python-version").strip()}

    def one(name: str, pattern: str, text: str, form=lambda m: m.group(1)) -> None:
        values = {form(m) for m in re.finditer(pattern, text, re.MULTILINE)}
        found[name] = values.pop() if len(values) == 1 else ("several" if values else "")
    one("requires-python", r'^requires-python\s*=\s*">=\s*(3\.\d+)"', project)
    one("ruff target-version", r'^target-version\s*=\s*"py3(\d+)"', project,
        lambda m: f"3.{m.group(1)}")
    one("mypy python_version", r'^python_version\s*=\s*"(3\.\d+)"', project)
    one("classifiers", r'"Programming Language :: Python :: (3\.\d+)"', project)
    one("iemod_fetch.PYTHON", r"^PYTHON\s*=\s*\((3),\s*(\d+)\)",
        read(os.path.join("iemod_fetch", "__init__.py")),
        lambda m: f"{m.group(1)}.{m.group(2)}")
    flows = glob.glob(os.path.join(root, ".github", "workflows", "*.y*ml")) + \
        glob.glob(os.path.join(root, ".github", "actions", "**", "*.y*ml"), recursive=True)
    for path in sorted(flows):
        # any form: `python-version: "3.12"`, in a flow mapping
        # (`with: { python-version: '3.12', cache: pip }`), followed by a
        # comment, or as a list; never `python-version-file:` (review of #50)
        values = set(_WORKFLOW_PYTHON.findall(read(os.path.relpath(path, root))))
        if values:
            found[f"{os.path.basename(path)} python-version"] = \
                values.pop() if len(values) == 1 else "several"
    return found


def python_disagreements(places: dict[str, str]) -> list[str]:
    wanted = places[".python-version"]
    return [f"{place}: {value or 'none'} (.python-version says {wanted})"
            for place, value in places.items() if value != wanted]


def python_issue(pinned_python: str, newest: str) -> tuple[str, str] | None:
    if newest and _key(newest) > _key(pinned_python):
        body = (f"Upstream: https://www.python.org/downloads/ - "
                f"{MANIFEST}\n\n"
                "ADR-0043: the project moves when the whole toolchain supports it.\n\n"
                f"1. Set `.python-version` to {newest}; requires-python, ruff's "
                "target-version, mypy's python_version, the classifiers and "
                "`iemod_fetch.PYTHON` with it (tests/test_upstream_versions.py holds "
                "them together).\n"
                "2. CI green on Linux and Windows, the wizard's bundle built and "
                "started (`--check`), PySide6 and PyInstaller wheels for it.\n"
                "3. Read the new version's What's New for changed defaults.\n")
        return f"Python {newest} is available (pinned {pinned_python})", body
    return None


def _gh(*args: str) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True,
                          check=True).stdout


def _upstream() -> dict[str, str]:
    tags = json.loads(_gh("api", "--paginate", "--slurp",
                          "repos/WeiDUorg/weidu/tags?per_page=100"))
    names = [tag["name"] for page in tags for tag in page]
    cargo = json.loads(_gh("api", "repos/dark0dave/mod_installer/contents/Cargo.toml"))
    text = base64.b64decode(cargo["content"]).decode("utf-8")
    version = _CARGO_VERSION.search(text)
    return {"weidu": newest_weidu(names) or "",
            "mod_installer": version.group(1) if version else ""}


def _python_check() -> list[tuple[str, str]]:
    """Issues to open about Python: disagreeing places, a newer Python."""
    places = python_places()
    issues = []
    wrong = python_disagreements(places)
    for line in wrong:
        print(f"Python: {line}")
    if wrong:
        issues.append(("The project names more than one Python version",
                       "ADR-0043: one version, `.python-version`'s.\n\n"
                       + "\n".join(f"- {line}" for line in wrong) + "\n"))
    with urllib.request.urlopen(MANIFEST, timeout=60) as response:   # noqa: S310
        newest = newest_python(json.load(response))
    print(f"Python: pinned {places['.python-version']}, newest stable {newest}")
    issue = python_issue(places[".python-version"], newest or "")
    if issue:
        issues.append(issue)
    return issues


def main() -> int:
    with open(CI, encoding="utf-8") as fh:
        pins = pinned(fh.read())
    latest = _upstream()
    for tool in ("weidu", "mod_installer"):
        print(f"{NAMES[tool]}: pinned {pins.get(tool)}, upstream {latest.get(tool)}")
    behind = verdicts(pins, latest)
    for verdict in behind:
        search = f'in:title "{NAMES[verdict.tool]} {verdict.latest} is available"'
        open_ = _gh("issue", "list", "--state", "open", "--search", search,
                    "--json", "number", "--jq", "length").strip()
        if open_ == "0":
            _gh("issue", "create", "--title", verdict.title, "--body", verdict.body)
            print(f"opened: {verdict.title}")
    python = _python_check()
    for title, body in python:
        open_ = _gh("issue", "list", "--state", "open", "--search",
                    f'in:title "{title}"', "--json", "number", "--jq", "length").strip()
        if open_ == "0":
            _gh("issue", "create", "--title", title, "--body", body)
            print(f"opened: {title}")
    return 1 if behind or python else 0  # a red run means something to bump


if __name__ == "__main__":
    sys.exit(main())
