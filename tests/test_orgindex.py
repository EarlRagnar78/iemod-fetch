"""
Trusted-owner discovery: a scoped allowlist, not a global search.

The distinction from legacy defect L7 is the whole point, so it is asserted
directly: the search space is bounded, and a hit is still gated by the strict
.tp2 check before anything is installed.
"""
import json

import pytest

from iemod_fetch.errors import NetworkError
from iemod_fetch.manifest import parse_manifest
from iemod_fetch.orgindex import OwnerIndex, load_trusted_owners


class OwnerStub:
    def __init__(self, owners):
        self.owners = owners
        self.calls = []

    def get_json(self, url):
        self.calls.append(url)
        for owner, repos in self.owners.items():
            if f"/users/{owner}/repos" in url:
                if "page=1" in url:
                    return [{"name": r, "owner": {"login": owner}} for r in repos]
                return []
        raise NetworkError(f"404 {url}")


def index(owners, **kw):
    return OwnerIndex(client=OwnerStub(owners), owners=list(owners), **kw)


# ------------------------------------------------------------ bounded search
def test_only_allowlisted_owners_are_ever_queried():
    idx = index({"Gibberlings3": ["EndlessBG1"]})
    idx.candidates("EndlessBG1")
    assert all("/users/Gibberlings3/repos" in url for url in idx.client.calls)
    assert not any("search" in url for url in idx.client.calls)


def test_a_repo_in_an_untrusted_owner_is_invisible():
    idx = index({"Gibberlings3": ["SomethingElse"]})
    assert idx.candidates("EndlessBG1") == []


def test_an_unreachable_owner_is_recorded_and_does_not_abort_the_others():
    idx = OwnerIndex(client=OwnerStub({"Gibberlings3": ["EndlessBG1"]}),
                     owners=["DoesNotExist", "Gibberlings3"])
    hits = idx.candidates("EndlessBG1")
    assert [h.repo.full_name for h in hits] == ["Gibberlings3/EndlessBG1"]
    assert "doesnotexist" in idx.failures


# ---------------------------------------------------------------- matching
@pytest.mark.parametrize("folder,repo", [
    ("EndlessBG1", "EndlessBG1"),                      # exact
    ("questpack", "d0questpack"),                      # author prefix
    ("HiddenGameplayOptions", "A7-HiddenGameplayOptions"),
    ("SirinesCall", "Lure_Of_Sirines_Call"),           # containment
])
def test_realistic_name_shapes_are_matched(folder, repo):
    idx = index({"Gibberlings3": [repo]})
    hits = idx.candidates(folder)
    assert hits and hits[0].repo.name == repo


def test_an_unrelated_repository_does_not_match():
    idx = index({"Gibberlings3": ["Tweaks-Anthology", "SwordCoastStratagems"]})
    assert idx.candidates("EndlessBG1") == []


def test_forks_and_archived_repos_rank_below_the_real_thing():
    class Rich(OwnerStub):
        def get_json(self, url):
            self.calls.append(url)
            if "page=1" not in url:
                return []
            return [{"name": "EndlessBG1", "owner": {"login": "Fork"}, "fork": True},
                    {"name": "EndlessBG1", "owner": {"login": "Gibberlings3"}}]

    idx = OwnerIndex(client=Rich({}), owners=["Gibberlings3"])
    hits = idx.candidates("EndlessBG1")
    assert hits[0].repo.owner == "Gibberlings3"
    assert "fork" in hits[1].rationale


def test_results_are_deterministic():
    idx = index({"Gibberlings3": ["EndlessBG1"], "Pocket-Plane-Group": ["EndlessBG1"]})
    first = [c.repo.full_name for c in idx.candidates("EndlessBG1", limit=5)]
    assert first == sorted(first)


# ---------------------------------------------------------------- allowlist
def test_the_allowlist_includes_owners_the_manifest_already_trusts():
    manifest = parse_manifest({"mods": [
        {"name": "x", "tp2": "x", "github": "SomeModder/Repo"}]})
    owners = load_trusted_owners(None, manifest=manifest)
    assert "SomeModder" in owners
    assert "Gibberlings3" in owners          # shipped houses too


def test_the_allowlist_can_be_replaced_wholesale(tmp_path):
    path = tmp_path / "owners.json"
    path.write_text(json.dumps(["OnlyThisOne"]))
    owners = load_trusted_owners(str(path))
    assert owners == ["OnlyThisOne"]


def test_extra_owners_are_appended_without_duplicates():
    owners = load_trusted_owners(None, extra=["Gibberlings3", "BrandNew"])
    assert owners.count("Gibberlings3") == 1 and "BrandNew" in owners


# -------------------------------------------------------------------- cache
def test_listings_are_cached_across_index_instances(tmp_path):
    cache = str(tmp_path / "owners-cache.json")
    first = index({"Gibberlings3": ["EndlessBG1"]}, cache_path=cache)
    first.candidates("EndlessBG1")
    assert first.client.calls

    second = index({"Gibberlings3": ["EndlessBG1"]}, cache_path=cache)
    assert second.candidates("EndlessBG1")
    assert second.client.calls == []          # served entirely from cache


def test_a_corrupt_cache_is_ignored_not_fatal(tmp_path):
    cache = tmp_path / "owners-cache.json"
    cache.write_text("{not json")
    idx = index({"Gibberlings3": ["EndlessBG1"]}, cache_path=str(cache))
    assert idx.candidates("EndlessBG1")


def test_the_cache_preserves_the_owner_spelling(tmp_path):
    """
    Suggested `"github"` values must be pasteable verbatim. The cache used to
    write the lower-cased lookup key, so a second run offered `gitjas/ToA`.
    """
    cache = str(tmp_path / "owners.json")
    first = index({"Gitjas": ["ToA"]}, cache_path=cache)
    assert first.candidates("ToA")[0].repo.full_name == "Gitjas/ToA"

    second = index({"Gitjas": ["ToA"]}, cache_path=cache)
    assert second.client.calls == []                      # served from cache
    assert second.candidates("ToA")[0].repo.full_name == "Gitjas/ToA"
