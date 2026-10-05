import os

import pytest

from iemod_fetch.errors import ManifestError
from iemod_fetch.manifest import load_manifest, parse_manifest

DATA = os.path.join(os.path.dirname(__file__), "data")


def test_the_real_manifest_loads():
    manifest = load_manifest(os.path.join(DATA, "mod_downloads.json"))
    assert len(manifest.sources) == 148
    assert manifest.sources["dlcmerger"].github == "Argent77/A7-DlcMerger"


def test_the_real_manifest_warns_about_its_three_cleartext_urls():
    manifest = load_manifest(os.path.join(DATA, "mod_downloads.json"))
    http_warnings = [w for w in manifest.warnings if "http://" in w]
    assert len(http_warnings) == 3


def test_a_null_github_field_with_a_profile_url_is_reported():
    """Real entry: FowlWish -> https://github.com/Glittergear, github: null."""
    manifest = load_manifest(os.path.join(DATA, "mod_downloads.json"))
    assert manifest.sources["fowlwish"].github is None


@pytest.mark.parametrize("tp2", ["../victim", "a/b", "", "CON", ".."])
def test_unsafe_tp2_keys_are_refused(tp2):
    with pytest.raises(ManifestError):
        parse_manifest({"mods": [{"name": "x", "tp2": tp2, "url": "https://x/"}]})


def test_empty_mod_list_is_an_error_not_a_silent_success():
    """The legacy script printed 'all mods present' for an empty manifest."""
    with pytest.raises(ManifestError, match="empty"):
        parse_manifest({"mods": []})


def test_missing_mods_key_is_an_error():
    with pytest.raises(ManifestError, match="no 'mods' key"):
        parse_manifest({"modules": []})


def test_duplicate_keys_are_refused():
    with pytest.raises(ManifestError, match="duplicate"):
        parse_manifest({"mods": [{"name": "a", "tp2": "x", "url": "https://a/"},
                                 {"name": "b", "tp2": "x", "url": "https://b/"}]})


def test_a_malformed_github_field_is_downgraded_to_a_warning():
    manifest = parse_manifest({"mods": [{"name": "a", "tp2": "x",
                                         "github": "not-a-repo",
                                         "url": "https://a/"}]})
    assert manifest.sources["x"].github is None
    assert any("owner/repo" in w for w in manifest.warnings)


def test_a_bad_sha256_is_fatal():
    with pytest.raises(ManifestError, match="64-hex"):
        parse_manifest({"mods": [{"name": "a", "tp2": "x", "url": "https://a/",
                                  "sha256": "nope"}]})


def test_integrity_fields_round_trip():
    manifest = parse_manifest({"mods": [{"name": "a", "tp2": "x",
                                         "github": "o/r", "sha256": "ab" * 32,
                                         "release_tag": "v1.0", "asset": "*.iemod"}]})
    source = manifest.sources["x"]
    assert (source.sha256, source.release_tag, source.asset) == ("ab" * 32, "v1.0", "*.iemod")
