"""
Published release notes follow CHANGELOG.md (ADR-0027).

A correction to a released section is published by the next push to main:
the release's body is rebuilt from the section, keeping the "Verify this
download" block the release was built with (its digest belongs to the
artifacts, not to the changelog).
"""
from tools.release_notes import refreshed, section

CHANGELOG = """# Changelog

## [Unreleased]

## [2.2.0] - 2026-10-21
- **`--simulate`: walk the plan.** fixed

## [2.1.0] - 2026-10-20
- a
"""

VERIFY = ("\n\n### Verify this download\n```\nsha256  abc  iemod-fetch.pyz\n"
          "gh attestation verify iemod-fetch.pyz --repo o/r\n```\n")


def test_a_section_is_the_text_under_its_heading():
    assert section(CHANGELOG, "2.2.0") == "- **`--simulate`: walk the plan.** fixed"
    assert section(CHANGELOG, "2.1.0") == "- a"
    assert section(CHANGELOG, "9.9.9") is None


def test_a_cut_body_is_rebuilt_keeping_its_verify_block():
    body = ": walk the plan.** broken" + VERIFY
    assert refreshed(body, section(CHANGELOG, "2.2.0")) == (
        "- **`--simulate`: walk the plan.** fixed" + VERIFY)


def test_a_body_already_in_step_is_left_alone():
    body = "- **`--simulate`: walk the plan.** fixed" + VERIFY
    assert refreshed(body, section(CHANGELOG, "2.2.0")) is None


def test_a_body_without_a_verify_block_is_the_section():
    assert refreshed("old", "new") == "new"


# --------------------------------------------- "Latest" on the newest release
def test_the_newest_released_version_is_the_one_marked_latest():
    """A back-fill published after the newest release must not stay Latest."""
    from tools.release_notes import newest_released
    released = {"v2.1.0", "v2.2.0"}.__contains__
    assert newest_released(CHANGELOG, released) == "v2.2.0"


def test_an_unreleased_newest_section_is_skipped():
    from tools.release_notes import newest_released
    assert newest_released(CHANGELOG, {"v2.1.0"}.__contains__) == "v2.1.0"
    assert newest_released(CHANGELOG, set().__contains__) is None


def fake_gh(monkeypatch, releases: str, current: str, latest_code=0, list_code=0,
            edit_code=0):
    """gh's answers: the published releases' tags, releases/latest, an edit."""
    import subprocess
    from tools import release_notes
    calls = []

    def gh(*args):
        calls.append(args)
        if args[:2] == ("api", "--paginate"):
            return subprocess.CompletedProcess(args, list_code, releases, "boom")
        if args[0] == "api":
            body = current + "\n" if latest_code == 0 else '{"message":"Not Found"}'
            return subprocess.CompletedProcess(args, latest_code, body, "")
        return subprocess.CompletedProcess(args, edit_code, "", "denied")
    monkeypatch.setattr(release_notes, "_gh", gh)
    return calls


def test_latest_marks_the_newest_release_only_when_it_is_not_already(monkeypatch):
    from tools import release_notes
    calls = fake_gh(monkeypatch, "v2.2.0\nv2.1.0\n", "v2.1.0")   # a back-fill took Latest
    assert release_notes.latest(CHANGELOG) == 0
    assert ("release", "edit", "v2.2.0", "--latest") in calls
    calls = fake_gh(monkeypatch, "v2.2.0\nv2.1.0\n", "v2.2.0")   # already right
    assert release_notes.latest(CHANGELOG) == 0
    assert not any(c[:2] == ("release", "edit") for c in calls)


def test_github_not_answering_fails_and_demotes_nothing(monkeypatch):
    """A 5xx or a rate limit on the list is an error, never "not released":
    reading it so would mark an older release Latest (review of #103)."""
    from tools import release_notes
    calls = fake_gh(monkeypatch, "", "v2.2.0", list_code=1)
    assert release_notes.latest(CHANGELOG) == 1
    assert not any(c[:2] == ("release", "edit") for c in calls)


def test_no_latest_at_all_is_set_and_reported_as_none(monkeypatch, capsys):
    from tools import release_notes
    calls = fake_gh(monkeypatch, "v2.2.0\n", "", latest_code=1)     # releases/latest: 404
    assert release_notes.latest(CHANGELOG) == 0
    assert ("release", "edit", "v2.2.0", "--latest") in calls
    assert "(was none)" in capsys.readouterr().out


def test_a_refused_edit_fails_the_step(monkeypatch):
    from tools import release_notes
    fake_gh(monkeypatch, "v2.2.0\n", "v2.1.0", edit_code=1)
    assert release_notes.latest(CHANGELOG) == 1
