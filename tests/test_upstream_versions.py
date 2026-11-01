"""
The pinned WeiDU and mod_installer, compared with upstream (ADR-0028).

Dependabot cannot see them: WeiDU is a release zip with a sha256, mod_installer
a commit, both in ci.yml's `real-weidu` job. A weekly run compares them with
upstream and opens one issue per tool behind - never a pull request, because
a new digest must be checked by a person (the method of
Proxmox_biome_log_collector's upstream-versions.yml).
"""
from tools.upstream_versions import newest_weidu, pinned, verdicts

CI = """
    env:
      WEIDU_URL: https://github.com/WeiDUorg/weidu/releases/download/v251.00/WeiDU-Linux-251.zip
      WEIDU_SHA256: 3e1a34ec
      MOD_INSTALLER_REV: 3b6827a039db43e342be19f7610ecdd680fe0a62
      MOD_INSTALLER_VERSION: "16.0.0"
"""


def test_the_pins_are_read_from_ci_yml():
    assert pinned(CI) == {"weidu": "251.00", "mod_installer": "16.0.0"}


def test_nightlies_and_release_candidates_are_not_releases():
    tags = ["v249.00", "v251.00", "v251.06-rc5", "v252.01-nightly-5242d96", "v250.00"]
    assert newest_weidu(tags) == "251.00"
    assert newest_weidu(tags + ["v252.00"]) == "252.00"


def test_a_tool_behind_upstream_gets_an_issue_title():
    found = verdicts(pinned(CI), {"weidu": "252.00", "mod_installer": "16.0.0"})
    assert [(v.tool, v.latest) for v in found] == [("weidu", "252.00")]
    assert found[0].title == "WeiDU 252.00 is available (pinned 251.00)"


def test_nothing_is_reported_when_up_to_date_or_upstream_is_older():
    assert verdicts(pinned(CI), {"weidu": "251.00", "mod_installer": "15.2.0"}) == []


# ------------------------------------------------- Python (ADR-0043)
import os  # noqa: E402

from tools.upstream_versions import (  # noqa: E402
    newest_python, python_disagreements, python_issue, python_places)


def test_the_repository_names_one_python_everywhere():
    """.python-version, requires-python, ruff, mypy, the classifiers and
    iemod_fetch.PYTHON name one version, and no workflow names its own."""
    root = os.path.join(os.path.dirname(__file__), os.pardir)
    places = python_places(root)
    assert python_disagreements(places) == [], places
    assert not [p for p in places if p.endswith(" python-version")]


def test_a_workflow_that_names_its_own_python_is_a_disagreement(tmp_path):
    root = os.path.join(os.path.dirname(__file__), os.pardir)
    for name in (".python-version", "pyproject.toml", os.path.join("iemod_fetch", "__init__.py")):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(os.path.join(root, name), encoding="utf-8") as fh:
            target.write_text(fh.read(), encoding="utf-8")
    flows = tmp_path / ".github" / "workflows"
    flows.mkdir(parents=True)
    (flows / "x.yml").write_text('      - uses: actions/setup-python@v7\n'
                                 '        with: { python-version-file: .python-version }\n'
                                 '      - uses: actions/setup-python@v7\n'
                                 '        with:\n          python-version: "3.12"\n',
                                 encoding="utf-8")
    wrong = python_disagreements(python_places(str(tmp_path)))
    assert wrong == ["x.yml python-version: 3.12 (.python-version says 3.14)"]
    # the forms the repository used, and others (review of #50)
    for line, seen in (('with: { python-version: "3.12" }', "3.12"),
                       ("with: { python-version: '3.12', cache: pip }", "3.12"),
                       ('python-version: "3.12"   # pinned', "3.12"),
                       ('python-version: ["3.12"]', "3.12"),
                       ("python-version: 3.13", "3.13")):
        (flows / "x.yml").write_text(f"        {line}\n", encoding="utf-8")
        assert python_places(str(tmp_path))["x.yml python-version"] == seen, line
    (flows / "x.yml").write_text('python-version: "3.12"\npython-version: "3.14"\n',
                                 encoding="utf-8")
    assert python_places(str(tmp_path))["x.yml python-version"] == "several"


def test_the_newest_python_is_the_newest_stable_final_minor():
    manifest = [{"version": "3.16.0-alpha.1", "stable": False},
                {"version": "3.15.1", "stable": True},
                {"version": "3.15.0", "stable": True},
                {"version": "3.14.9", "stable": True},
                {"version": "3.9.25", "stable": True}]
    assert newest_python(manifest) == "3.15"
    assert newest_python([{"version": "3.15.0-rc.2", "stable": False}]) is None


def test_a_newer_python_gets_an_issue_and_the_same_one_none():
    title, body = python_issue("3.14", "3.15")
    assert title == "Python 3.15 is available (pinned 3.14)"
    assert ".python-version" in body and "--check" in body
    assert python_issue("3.14", "3.14") is None
    assert python_issue("3.14", "") is None
