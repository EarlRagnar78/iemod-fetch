"""Version comparison that admits when it cannot tell."""
import itertools

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
    for older, newer in itertools.pairwise(ladder):
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


# ------------------------------------------------- compare_published, offers
def test_the_update_view_still_ranks_a_dotless_tag_by_its_number():
    """compare_published keeps its tested choice (test_freshness: v12 over 1.3);
    only an offer to replace a copy asks both readings to agree."""
    from iemod_fetch.versions import compare_published, newer_release
    assert compare_published("V19", "2.0") == 1
    assert not newer_release("V19", "2.0")       # as 1.9 it is older
    assert newer_release("V21", "2.0.5")         # as 21 and as 2.1, newer


def test_a_dotless_tag_spelling_its_own_release_is_still_equal():
    from iemod_fetch.versions import compare_published
    assert compare_published("V19", "1.9") == 0
    assert compare_published("v071", "0.71") == 0


@pytest.mark.parametrize("tag,installed,offered", [
    ("2.1.0", "v1.5 BETA", True),            # Ascension, measured
    ("v6.0", "v4.0", True),
    ("v4.1.0-rc1", "4.0", False),            # a candidate over a release
    ("v2.0-beta", "v1.5 BETA", True),        # a beta over a beta
    ("2025.05.18", "v1.5", False),           # a date over a version
    ("20180929", "v1.5 BETA", False),
    ("20240101", "20230101", True),          # dates on both sides rank
    ("V19", "2.0", False),                   # not known
    # the same number with a word added - a language, a platform, an author's
    # suffix (RoxanneSHS: ru for The-Rune, measured) - is not newer
    ("v04ru", "V0.4", False), ("v2.0-linux", "v2.0", False), ("v2.0-linux", "2", False),
    # review of #63: the number is compared, not the digits
    ("v11.0-fr", "1.10", True), ("v12.0-ee", "1.20", True), ("v3.1fr", "v3.0", True),
    ("v1.21-fix", "1.2.1", False),           # v1.21 is read as 1.2.1, word or not
    ("1.4c", "1.4", True),                   # a letter is a revision
    # review of #56, real tags from krion64's cache: a letter is a revision
    ("v4.81a", "v4.0", True), ("1.4.4a", "1.4", True), ("v2.5a", "1.0", True),
    ("1.4b", "1.3", True), ("v2.0-alpha", "v1.0", False),
    # an integer-numbered mod against a dotted copy: BG1NPC v32, Tweaks v18
    ("v32", "v31.1", True), ("v18", "17.0", True),
    # a leading zero is the dot before it: 0.71, as compare_published reads it
    ("v071", "0.70", True), ("v034", "0.33", True), ("v071", "0.72", False),
    ("v1.0", "v1.0", False),
    (None, "v1.0", False),
])
def test_an_offer_is_made_only_for_a_plainly_newer_release(tag, installed, offered):
    from iemod_fetch.versions import newer_release
    assert newer_release(tag, installed) is offered
