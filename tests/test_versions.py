"""Version comparison that admits when it cannot tell."""
import pytest

from iemod_fetch.versions import compare, is_newer, parse_version


@pytest.mark.parametrize("newer,older", [
    ("v5.2", "v5.0"), ("v1.2.0", "v0.11.0-alpha"), ("2.8", "2.7"),
    ("v14.1", "v14.0.9"), ("v1.0", "v1.0-alpha"), ("v1.0-beta", "v1.0-alpha"),
    ("v10", "v9"), ("v.4.6.4", "v4.6.3"),
    # a pre-release word sorts before a numbered release: real data has
    # `vAlpha_230919` alongside plain `v8`
    ("v8", "vAlpha_230919"),
])
def test_ranking(newer, older):
    assert compare(newer, older) == 1
    assert compare(older, newer) == -1
    assert is_newer(newer, older) is True


@pytest.mark.parametrize("a,b", [("v14.1", "14.1"), ("v1.0", "1.0"), ("4.0.7", "4.0.7")])
def test_equality_ignores_decoration(a, b):
    assert compare(a, b) == 0


@pytest.mark.parametrize("a,b", [
    ("vEAOB.9", "Alpha 3"),        # a named build against a pre-release word
    ("vEAOB.9", "v9"),             # an arbitrary word against a number
    ("release", "candidate"),      # two arbitrary words
])
def test_unrankable_pairs_say_so(a, b):
    """Guessing here would be worse than admitting ignorance."""
    assert compare(a, b) is None
    assert is_newer(a, b) is None


@pytest.mark.parametrize("value", [None, "", "   ", "v"])
def test_nothing_to_compare(value):
    assert parse_version(value) is None
    assert compare(value, "1.0") is None


# ------------------------------------- stability order for unreleased builds
def test_the_stated_stability_order():
    """
    master (a branch snapshot, no release tag) < alpha < beta < rc < numbered.

    A repository publishing no release is fetched as a snapshot of its default
    branch, and the tool records the branch name as the version.
    """
    ladder = ["master", "alpha", "beta", "rc", "1.0"]
    for older, newer in zip(ladder, ladder[1:]):
        assert compare(newer, older) == 1, f"{newer} should outrank {older}"


@pytest.mark.parametrize("branch", ["master", "main", "HEAD", "trunk"])
def test_a_branch_snapshot_ranks_below_any_numbered_release(branch):
    assert compare(branch, "v5.0") == -1
    assert is_newer(branch, "v5.0") is False


def test_a_snapshot_never_suppresses_a_rule_as_stale():
    """
    Ranking a snapshot lowest is the conservative choice: master is often newer
    code than the last tag, so treating it as newer would silently withhold real
    findings.
    """
    assert is_newer("master", "v1.0") is False


# --------------------------------------------------- regression: ADR-0019
def test_two_spellings_of_one_stability_level_are_equal_not_both_newer():
    """
    Found by property-based testing (`test_compare_is_antisymmetric`), not by
    any example test: `master` and `main` both rank -6, and the comparator
    returned 1 for BOTH orders. `is_newer` was therefore true in both
    directions, so an upstream renaming its default branch could mark a rule
    stale on nothing but the rename.
    """
    for left, right in (("master", "main"), ("alpha", "a"), ("beta", "b"),
                        ("rc", "pre"), ("snapshot", "nightly"), ("dev", "devel")):
        assert compare(left, right) == 0, (left, right)
        assert compare(right, left) == 0, (right, left)
        assert is_newer(left, right) is False
        assert is_newer(right, left) is False


def test_the_stability_ladder_still_holds_after_the_fix():
    assert compare("v1.0", "master") == 1
    assert compare("beta", "alpha") == 1
    assert compare("rc", "beta") == 1
    assert compare("alpha", "snapshot") == 1
