"""
Property-based tests: laws the code must obey for EVERY input, not for the
examples somebody thought of.

Example-based TDD proves a function works on the cases you imagined. It cannot
prove the absence of a case you did not imagine, and the defects that hurt in
this codebase have all been of that shape: a `? 1 : 0` anywhere in a tp2 killing
every GAME_IS match, a folder name whose capitalisation decided which mod owned
an ordering slot. Hypothesis generates and then SHRINKS a counterexample, so a
failure arrives as the smallest input that breaks the law.

The properties are chosen where a law actually exists:

* the security predicates are total - they answer for every string, never raise;
* version comparison is a strict weak ordering - if it is not, the sort that
  decides which release wins is undefined;
* every parser is total over arbitrary text - a log or catalogue is attacker-
  adjacent input, and a crash there is a denial of service on the whole run;
* the order planner is lossless and idempotent, whatever the input order.

Skipped, not failed, when Hypothesis is absent: the runtime is stdlib-only by
policy (ADR-0002) and `python3 -m pytest` must work with nothing installed.
"""
import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, assume, given, settings  # noqa: E402
from hypothesis import strategies as st                      # noqa: E402

from iemod_fetch.config import parse_size                    # noqa: E402
from iemod_fetch.errors import ConfigError, UnsafeName       # noqa: E402
from iemod_fetch.naming import (matches_tp2, normalize_key,  # noqa: E402
                                safe_component)
from iemod_fetch.ordering import _minimum_moves, tp2_key     # noqa: E402
from iemod_fetch.tp2 import parse_tp2                        # noqa: E402
from iemod_fetch.versions import compare, is_newer, parse_version  # noqa: E402
from iemod_fetch.weidu import parse_weidu_log                # noqa: E402

SETTINGS = settings(max_examples=300, deadline=None,
                    suppress_health_check=[HealthCheck.too_slow])

# Real mod folders are ASCII-ish, but the input is a JSON file and a log file
# written by other tools: anything can arrive.
TEXT = st.text(max_size=80)
NAMES = st.one_of(
    TEXT,
    st.text(alphabet="abcABC019._-\\/: ", max_size=40),
    st.sampled_from(["", ".", "..", "/", "\\", "CON", "NUL", "a.", "a ",
                     "C:\\x", "\x00", "../../etc/passwd", "a/../b"]),
)
VERSIONS = st.one_of(
    TEXT,
    st.from_regex(r"v?[0-9]{1,3}(\.[0-9]{1,3}){0,3}[a-z]?", fullmatch=True),
    st.sampled_from(["master", "main", "alpha", "beta 3", "v1.0-rc2",
                     "Alpha 3", "vEAOB.9", "snapshot", "v8", "1.0.0.0"]),
)


# ------------------------------------------------------------- naming safety
@given(NAMES)
@SETTINGS
def test_safe_component_is_total(name):
    """
    It answers for every string. A predicate guarding path traversal that itself
    raises on odd input is a denial of service in the guard.
    """
    try:
        result = safe_component(name)
    except UnsafeName:
        return
    assert isinstance(result, str) and result == name


@given(NAMES)
@SETTINGS
def test_an_accepted_component_can_never_traverse(name):
    """The one property that matters: what it accepts stays inside one level."""
    try:
        accepted = safe_component(name)
    except UnsafeName:
        return
    import os
    import posixpath
    assert accepted not in ("", ".", "..")
    assert "\x00" not in accepted
    assert "/" not in accepted and "\\" not in accepted
    assert not os.path.isabs(accepted)
    assert posixpath.normpath(posixpath.join("root", accepted)).startswith("root/")


@given(NAMES)
@SETTINGS
def test_normalize_key_is_idempotent_and_closed(key):
    once = normalize_key(key)
    assert normalize_key(once) == once
    assert once == "" or once.isalnum()
    assert once.islower() or once.isdigit() or not once.isalpha()


@given(NAMES, NAMES)
@SETTINGS
def test_matches_tp2_is_total(filename, folder):
    assert matches_tp2(filename, folder) in (True, False)


@given(NAMES)
@SETTINGS
def test_tp2_key_agrees_with_normalize_key(filename):
    """
    The ordering key and the rule key must be the same function of a name, or a
    rule about a mod silently matches nothing - which is how every EET_end rule
    went unchecked before ADR-0017.
    """
    key = tp2_key(filename)
    assert key == normalize_key(key)


# ------------------------------------------------------- version comparison
@given(VERSIONS)
@SETTINGS
def test_parse_version_is_total(text):
    parse_version(text)          # must not raise, whatever arrives


@given(VERSIONS)
@SETTINGS
def test_compare_is_reflexive(text):
    assert compare(text, text) in (0, None)


@given(VERSIONS, VERSIONS)
@SETTINGS
def test_compare_is_antisymmetric(left, right):
    forward, backward = compare(left, right), compare(right, left)
    if forward is None or backward is None:
        assert forward is None and backward is None
    else:
        assert forward == -backward


@given(VERSIONS, VERSIONS, VERSIONS)
@SETTINGS
def test_compare_is_transitive(a, b, c):
    """
    Without transitivity the ordering is not a strict weak ordering, and
    `sorted()` over releases produces a different answer depending on the input
    order - a non-deterministic choice of which release to download.
    """
    first, second = compare(a, b), compare(b, c)
    if first is None or second is None:
        return
    if first < 0 and second < 0:
        assert (compare(a, c) or 0) < 0
    if first > 0 and second > 0:
        assert (compare(a, c) or 0) > 0
    if first == 0 and second == 0:
        assert compare(a, c) in (0, None)


@given(VERSIONS, VERSIONS)
@SETTINGS
def test_is_newer_agrees_with_compare(left, right):
    verdict = is_newer(left, right)
    order = compare(left, right)
    if order is None:
        assert verdict is None
    else:
        assert verdict is (order > 0)


@given(st.integers(min_value=0, max_value=40),
       st.integers(min_value=0, max_value=40))
@SETTINGS
def test_a_release_tag_always_beats_a_branch_snapshot(major, minor):
    """
    The operator's stated ordering: master (no release tag) < alpha < beta <
    numbered. A snapshot ranking above a tagged release would silently prefer
    an untested branch head.
    """
    numbered = f"v{major}.{minor}"
    for snapshot in ("master", "main", "snapshot", "alpha", "beta"):
        assert (compare(numbered, snapshot) or 0) > 0


# ---------------------------------------------------------------- parsers
@given(st.text(max_size=400))
@SETTINGS
def test_parse_weidu_log_never_raises(text):
    """
    A WeiDU log is written by other people's tools and hand-edited constantly.
    Every line it cannot read must become a warning, never an exception.
    """
    parsed = parse_weidu_log(text)
    assert parsed.component_count == sum(len(m.components) for m in parsed.mods.values())
    assert set(parsed.order) == set(parsed.mods)
    assert len(parsed.order) == len(set(parsed.order))


@given(st.lists(st.tuples(st.text(alphabet="abcdef", min_size=1, max_size=6),
                          st.integers(0, 9),
                          st.integers(0, 9999)),
                max_size=25))
@SETTINGS
def test_a_well_formed_log_round_trips(entries):
    """Every line written in WeiDU's own format is read back exactly."""
    lines = [f"~{folder}\\setup-{folder}.tp2~ #{lang} #{comp} // c{comp}"
             for folder, lang, comp in entries]
    parsed = parse_weidu_log("\n".join(lines))
    assert parsed.warnings == []
    assert parsed.component_count == len(entries)
    seen = [(c.folder, c.language, c.index)
            for key in parsed.order for c in parsed.mods[key].components]
    assert sorted(seen) == sorted(entries)


@given(st.text(max_size=400))
@SETTINGS
def test_parse_tp2_never_raises(text):
    info = parse_tp2(text)
    assert info.version is None or isinstance(info.version, str)
    assert all(isinstance(g, str) for g in info.games)


# ------------------------------------------------------------------ config
@given(TEXT)
@SETTINGS
def test_parse_size_either_returns_a_positive_int_or_explains(text):
    try:
        value = parse_size(text, "max_bytes")
    except ConfigError as exc:
        assert "max_bytes" in str(exc)
        return
    assert isinstance(value, int) and value > 0


@given(st.integers(min_value=1, max_value=10 ** 9),
       st.sampled_from(["", "B", "KB", "KiB", "MB", "MiB", "GB", "GiB"]))
@SETTINGS
def test_size_units_are_monotonic(amount, unit):
    smaller = parse_size(f"{amount}{unit}", "max_bytes")
    bigger = parse_size(f"{amount + 1}{unit}", "max_bytes")
    assert bigger > smaller


# --------------------------------------------------------- ordering metrics
@given(st.lists(st.integers(0, 30), unique=True, max_size=25))
@SETTINGS
def test_no_moves_are_reported_for_an_unchanged_order(items):
    assert _minimum_moves(items, list(items)) == []


@given(st.lists(st.integers(0, 30), unique=True, max_size=18),
       st.randoms(use_true_random=False))
@SETTINGS
def test_minimum_moves_never_exceeds_the_list(items, rng):
    shuffled = list(items)
    rng.shuffle(shuffled)
    moves = _minimum_moves(items, shuffled)
    assert len(moves) <= len(items)
    assert {key for key, _o, _n in moves} <= set(items)


@given(st.lists(st.integers(0, 12), unique=True, min_size=1, max_size=12))
@SETTINGS
def test_moving_one_element_to_the_front_costs_one_move(items):
    """
    The regression the LCS metric exists for: index comparison called this N
    moves, and reported 146 mods out of place when one was.
    """
    assume(len(items) > 1)
    rotated = [items[-1]] + items[:-1]
    assert len(_minimum_moves(items, rotated)) == 1
