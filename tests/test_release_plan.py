"""
What the release workflow tags, and where (ADR-0027).

The rule, adopted from R-studioConf's ADR-0006: the newest `## [X.Y.Z]` section
of CHANGELOG.md is the release; it is tagged on the main-line commit where
`__version__` first became X.Y.Z - the merge of the release pull request, so
every fix in that pull request is in, and nothing merged after it is. An
existing tag means already released: nothing to do.
"""
import subprocess

import pytest

from tools.release_plan import newest_release, plan, release_commit

CHANGELOG = """# Changelog

## [Unreleased]

## [2.2.0] - 2026-10-21
- b

## [2.1.0] - 2026-10-20
- a
"""


def test_the_newest_released_section_is_the_release():
    assert newest_release(CHANGELOG) == "2.2.0"


def test_a_changelog_with_only_unreleased_has_no_release():
    assert newest_release("## [Unreleased]\n- x\n") is None


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(repo, version, message):
    (repo / "iemod_fetch").mkdir(exist_ok=True)
    (repo / "iemod_fetch" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (repo / "notes.txt").write_text(message)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    """main: 2.0.0, then a release branch bumping to 2.1.0 plus a later fix,
    merged; then an unrelated commit still at 2.1.0."""
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.org")
    git(tmp_path, "config", "user.name", "t")
    commit(tmp_path, "2.0.0", "start")
    git(tmp_path, "checkout", "-q", "-b", "release")
    commit(tmp_path, "2.1.0", "bump")
    commit(tmp_path, "2.1.0", "fix found in review")
    git(tmp_path, "checkout", "-q", "main")
    git(tmp_path, "merge", "-q", "--no-ff", "-m", "Release 2.1.0 (#1)", "release")
    merge = git(tmp_path, "rev-parse", "HEAD")
    commit(tmp_path, "2.1.0", "docs after the release")
    return tmp_path, merge


def test_the_release_is_the_main_line_commit_where_the_version_appeared(repo):
    path, merge = repo
    assert release_commit(str(path), "2.1.0") == merge


def test_a_version_never_set_has_no_commit(repo):
    path, _merge = repo
    assert release_commit(str(path), "9.9.9") is None


def test_the_plan_skips_a_version_already_tagged(repo):
    path, _merge = repo
    head = git(path, "rev-parse", "HEAD")     # only notes.txt changed: not shipped
    assert plan(str(path), "2.1.0") == {"release": "true", "tag": "v2.1.0",
                                        "sha": head, "workflows_differ": "false"}
    git(path, "tag", "v2.1.0", head)
    assert plan(str(path), "2.1.0")["release"] == "false"


def touch(repo, path, text, message):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def test_the_head_is_released_when_nothing_shipped_changed_since(repo):
    """GITHUB_TOKEN cannot create a tag on a commit whose workflow files differ
    from the default branch (softprops/action-gh-release#411). When nothing that
    ships changed since the version commit, the head IS that release."""
    path, _merge = repo
    head = touch(path, ".github/workflows/ci.yml", "on: push\n", "a CI change")
    assert plan(str(path), "2.1.0")["sha"] == head


def test_a_true_backfill_says_what_the_token_cannot_do(repo):
    path, merge = repo
    touch(path, ".github/workflows/ci.yml", "on: push\n", "a CI change")
    commit(path, "2.2.0", "the next release")
    planned = plan(str(path), "2.1.0")
    assert planned["sha"] == merge
    assert planned["workflows_differ"] == "true"


def test_workflows_differ_is_false_when_they_do_not(repo):
    path, _merge = repo
    assert plan(str(path), "2.1.0")["workflows_differ"] == "false"


def test_an_explicit_version_releases_an_existing_tag_on_its_commit(repo):
    """A tag pushed by hand runs the workflow file of the TAGGED commit - for an
    old version, the old workflow. So the manual run with that version releases
    the existing tag with today's workflow; creating no ref, it needs no extra
    permission."""
    path, merge = repo
    git(path, "tag", "v2.1.0", merge)
    assert plan(str(path), "2.1.0")["release"] == "false"            # automatic: done
    assert plan(str(path), "2.1.0", explicit=True) == {
        "release": "true", "tag": "v2.1.0", "sha": merge, "workflows_differ": "false"}


from tools.release_plan import automatic  # noqa: E402


def test_with_the_newest_released_the_first_untagged_backfill_is_next(repo):
    """Automatic runs release the newest changelog version; once that is
    tagged, a version listed for back-fill and still untagged is next."""
    path, merge = repo
    head = git(path, "rev-parse", "HEAD")
    git(path, "tag", "v2.1.0", head)
    assert automatic(str(path), "2.1.0", backfill=[])["release"] == "false"
    git(path, "tag", "-d", "v2.1.0")
    commit(path, "2.2.0", "the next release")
    git(path, "tag", "v2.2.0")
    planned = automatic(str(path), "2.2.0", backfill=["2.1.0"])
    assert (planned["release"], planned["tag"], planned["sha"]) == ("true", "v2.1.0", merge)


def test_a_backfill_already_tagged_is_done(repo):
    path, merge = repo
    git(path, "tag", "v2.1.0", merge)
    commit(path, "2.2.0", "the next release")
    git(path, "tag", "v2.2.0")
    assert automatic(str(path), "2.2.0", backfill=["2.1.0"])["release"] == "false"


from tools.release_plan import pull_request  # noqa: E402


def test_a_pull_request_dry_runs_its_own_head_and_version(repo):
    """On a pull request that touches the release workflow, the pipeline is
    rehearsed on the PR's own commit - build and attestation, never publish -
    so a Dependabot bump of a release-only action is exercised before merge."""
    path, _merge = repo
    head = git(path, "rev-parse", "HEAD")
    assert pull_request(str(path)) == {"release": "true", "tag": "v2.1.0",
                                       "sha": head, "workflows_differ": "false"}
