"""
A copy from elsewhere, a newer GitHub release: offered, and taken only when
asked (--take-newer; ADR-0039 amendment, ADR-0005).

Measured on 2026-10-23: with GitHub out of reach Ascension came from a Beamdog
thread as v1.5 BETA while krion64's daily scan names its release 2.1.0.
"""
import io
import json
import zipfile

import pytest

from test_discovery_end_to_end import WEIDU, CATALOGUE, DiscoveryStub, make, run

FORUM = "https://forums.beamdog.com/uploads/FileUpload/2c/93c3.zip"
ASSET = "https://github.com/Gibberlings3/EndlessBG1/releases/download/v2.0/m.zip"
RELEASE = {"Gibberlings3/EndlessBG1": {
    "tag": "v2.0", "release_date": "2026-05-18",
    "release_url": "https://github.com/Gibberlings3/EndlessBG1/releases/tag/v2.0"}}


def mod_zip(version, folder="EndlessBG1"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{folder}/{folder}.tp2", f"BACKUP ~x~\nVERSION ~{version}~\n")
    return buf.getvalue()


def setup(tmp_path, monkeypatch, stub, cache=RELEASE,
          repo="https://github.com/Gibberlings3/EndlessBG1"):
    make(tmp_path, monkeypatch, stub, WEIDU, CATALOGUE)
    (tmp_path / "lcc.json").write_text(json.dumps({"mods": [
        {"tp2": "EndlessBG1", "name": "Endless BG1", "urls": [FORUM, repo]}]}))
    (tmp_path / "vc.json").write_text(json.dumps(cache))


ARGS = ["-w", "WeiDU.log", "-t", "Mods", "-c", "lcc.json", "--releases", "vc.json",
        "--no-discovery", "--json-report", "r.json"]


def record(tmp_path):
    return json.loads((tmp_path / "r.json").read_text())["records"][0]


def installed_version(tmp_path):
    return (tmp_path / "Mods" / "EndlessBG1" / "EndlessBG1.tp2").read_text()


def test_a_newer_github_release_is_offered_not_taken(tmp_path, monkeypatch):
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("v1.5 BETA")})
    setup(tmp_path, monkeypatch, stub)

    code, out = run(ARGS)

    assert code == 0, out
    assert "v1.5 BETA" in installed_version(tmp_path)
    rec = record(tmp_path)
    assert rec["newer"]["version"] == "v2.0"
    assert rec["newer"]["installed"] == "v1.5 BETA"
    assert rec["newer"]["repo"] == "Gibberlings3/EndlessBG1"
    assert "--take-newer EndlessBG1" in out
    assert stub.downloaded == [FORUM]                  # nothing taken unasked


def test_take_newer_replaces_the_copy_and_keeps_the_old_one(tmp_path, monkeypatch):
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("v1.5 BETA")})
    setup(tmp_path, monkeypatch, stub)
    assert run(ARGS)[0] == 0

    # GitHub answers on the second run, the one the player asked for
    stub.releases = {"Gibberlings3/EndlessBG1": {"tag_name": "v2.0", "assets": [
        {"name": "m.zip", "browser_download_url": ASSET}]}}
    stub.blobs[ASSET] = mod_zip("v2.0")
    code, out = run([*ARGS, "--take-newer", "EndlessBG1"])

    assert code == 0, out
    assert "VERSION ~v2.0~" in installed_version(tmp_path)
    assert stub.downloaded == [FORUM, ASSET]
    rec = record(tmp_path)
    assert rec["status"] == "ok" and "as asked" in rec["detail"]
    assert "previous copy kept" in rec["detail"]
    assert not rec["newer"]


def test_take_newer_all_takes_what_was_offered(tmp_path, monkeypatch):
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("v1.5 BETA")})
    setup(tmp_path, monkeypatch, stub)
    assert run(ARGS)[0] == 0
    stub.releases = {"Gibberlings3/EndlessBG1": {"tag_name": "v2.0", "assets": [
        {"name": "m.zip", "browser_download_url": ASSET}]}}
    stub.blobs[ASSET] = mod_zip("v2.0")

    code, out = run([*ARGS, "--take-newer", "all"])

    assert code == 0, out
    assert "VERSION ~v2.0~" in installed_version(tmp_path)


def test_without_github_the_copy_on_disk_is_kept(tmp_path, monkeypatch):
    """Asked for, unreachable: nothing changes, and never the forum copy again."""
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("v1.5 BETA")})
    setup(tmp_path, monkeypatch, stub)
    assert run(ARGS)[0] == 0

    code, out = run([*ARGS, "--take-newer", "EndlessBG1", "--allow-manual"])

    assert code == 0, out
    assert "v1.5 BETA" in installed_version(tmp_path)
    assert stub.downloaded == [FORUM]
    rec = record(tmp_path)
    assert rec["status"] == "manual" and "copy on disk is kept" in rec["detail"]


def test_the_take_still_passes_the_tp2_check(tmp_path, monkeypatch):
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("v1.5 BETA")})
    setup(tmp_path, monkeypatch, stub)
    assert run(ARGS)[0] == 0
    stub.releases = {"Gibberlings3/EndlessBG1": {"tag_name": "v2.0", "assets": [
        {"name": "m.zip", "browser_download_url": ASSET}]}}
    stub.blobs[ASSET] = mod_zip("v2.0", folder="SomeOtherMod")

    code, out = run([*ARGS, "--take-newer", "EndlessBG1"])

    assert code == 1
    assert "v1.5 BETA" in installed_version(tmp_path)


def test_no_offer_when_the_versions_cannot_be_ranked(tmp_path, monkeypatch):
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("EAOB.9")})
    setup(tmp_path, monkeypatch, stub, cache={"Gibberlings3/EndlessBG1": {
        "tag": "v1_Beta260923"}})

    code, out = run(ARGS)

    assert code == 0, out
    assert not record(tmp_path)["newer"]
    assert "--take-newer" not in out


def test_no_offer_from_a_repository_named_otherwise(tmp_path, monkeypatch):
    """
    Measured: finchnpc's sources name Pocket-Plane-Group/Finch_NPC and
    RoxanneSHS/Finch, and only the second is in the release scan (v53). A
    repository not named like the mod is not offered.
    """
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("v4.0")})
    setup(tmp_path, monkeypatch, stub, repo="https://github.com/RoxanneSHS/Endless",
          cache={"RoxanneSHS/Endless": {"tag": "v53"}})

    code, out = run(ARGS)

    assert code == 0, out
    assert not record(tmp_path)["newer"]


def test_a_copy_from_github_is_not_offered_its_own_release(tmp_path, monkeypatch):
    stub = DiscoveryStub(
        owners={},
        releases={"Gibberlings3/EndlessBG1": {"tag_name": "v1.0", "assets": [
            {"name": "m.zip", "browser_download_url": ASSET}]}},
        blobs={ASSET: mod_zip("v1.0")})
    setup(tmp_path, monkeypatch, stub)

    code, out = run(ARGS)

    assert code == 0, out
    assert stub.downloaded == [ASSET]
    assert not record(tmp_path)["newer"]


def test_asking_by_name_never_takes_an_older_release(tmp_path, monkeypatch):
    """Review of #52: the name alone took the release with no offer - v2.0 over v3.0."""
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("v3.0")})
    setup(tmp_path, monkeypatch, stub)
    assert run(ARGS)[0] == 0
    stub.releases = {"Gibberlings3/EndlessBG1": {"tag_name": "v2.0", "assets": [
        {"name": "m.zip", "browser_download_url": ASSET}]}}
    stub.blobs[ASSET] = mod_zip("v2.0")

    code, out = run([*ARGS, "--take-newer", "EndlessBG1"])

    assert code == 0, out
    assert "VERSION ~v3.0~" in installed_version(tmp_path)
    assert stub.downloaded == [FORUM]


def test_a_release_taken_is_not_taken_again_on_the_next_run(tmp_path, monkeypatch):
    """Review of #52: take_newer kept in the ini replaced the mod on every run."""
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("v1.5 BETA")})
    setup(tmp_path, monkeypatch, stub)
    assert run(ARGS)[0] == 0
    stub.releases = {"Gibberlings3/EndlessBG1": {"tag_name": "v2.0", "assets": [
        {"name": "m.zip", "browser_download_url": ASSET}]}}
    stub.blobs[ASSET] = mod_zip("v2.0")
    assert run([*ARGS, "--take-newer", "EndlessBG1"])[0] == 0

    code, out = run([*ARGS, "--take-newer", "EndlessBG1"])

    assert code == 0, out
    assert stub.downloaded == [FORUM, ASSET]
    assert record(tmp_path)["status"] == "skipped"


def test_the_take_asks_github_for_the_release_offered(tmp_path, monkeypatch):
    """Review of #52: it asked for /releases/latest, which may be older than the offer."""
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("v1.5 BETA")})
    setup(tmp_path, monkeypatch, stub)
    assert run(ARGS)[0] == 0
    stub.releases = {"Gibberlings3/EndlessBG1": {"tag_name": "v2.0", "assets": [
        {"name": "m.zip", "browser_download_url": ASSET}]}}
    stub.blobs[ASSET] = mod_zip("v2.0")
    stub.calls.clear()

    assert run([*ARGS, "--take-newer", "EndlessBG1"])[0] == 0

    asked = [u for u in stub.calls if "/repos/Gibberlings3/EndlessBG1/releases" in u]
    assert asked and all(u.endswith("/releases/tags/v2.0") for u in asked), asked


def test_a_release_candidate_is_not_offered_over_a_release(tmp_path, monkeypatch):
    """Follow-up (b): `v4.1.0-rc1` ranks above `4.0`, but is not the newer version."""
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("4.0")})
    setup(tmp_path, monkeypatch, stub, cache={"Gibberlings3/EndlessBG1": {
        "tag": "v4.1.0-rc1"}})

    code, out = run(ARGS)

    assert code == 0, out
    assert not record(tmp_path)["newer"]


def test_without_a_release_url_the_repo_is_spelled_as_its_source_spells_it(
        tmp_path, monkeypatch):
    """Follow-up (c): the scan's keys are lowercased."""
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("v1.5 BETA")})
    setup(tmp_path, monkeypatch, stub, cache={"Gibberlings3/EndlessBG1": {"tag": "v2.0"}})

    assert run(ARGS)[0] == 0

    assert record(tmp_path)["newer"]["repo"] == "Gibberlings3/EndlessBG1"


def test_a_repository_named_exactly_like_the_mod_comes_first(tmp_path, monkeypatch):
    """Follow-up (d): a name that only holds the mod's is the second choice."""
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("v1.5 BETA")})
    # the manifest names the other one, so it is listed first
    make(tmp_path, monkeypatch, stub, WEIDU, {"mods": [
        {"name": "Endless BG1", "tp2": "EndlessBG1",
         "github": "someone/EndlessBG1-Tweaks"}]})
    (tmp_path / "lcc.json").write_text(json.dumps({"mods": [
        {"tp2": "EndlessBG1", "name": "Endless BG1",
         "urls": [FORUM, "https://github.com/Gibberlings3/EndlessBG1"]}]}))
    (tmp_path / "vc.json").write_text(json.dumps({
        "someone/EndlessBG1-Tweaks": {"tag": "v9.0"},
        **RELEASE}))

    assert run(ARGS)[0] == 0

    newer = record(tmp_path)["newer"]
    assert newer["repo"] == "Gibberlings3/EndlessBG1" and newer["version"] == "v2.0"


def test_the_take_reads_the_new_copys_own_game_requirement(tmp_path, monkeypatch):
    """Follow-up (e): a release taken is checked against the game as any download."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("EndlessBG1/EndlessBG1.tp2",
                    "BACKUP ~x~\nVERSION ~v2.0~\nBEGIN ~c~\n"
                    "REQUIRE_PREDICATE GAME_IS ~bg2ee~ ~no~\n")
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("v1.5 BETA")})
    setup(tmp_path, monkeypatch, stub)
    args = [a if a != "WeiDU.log" else "WeiDU.log:EET" for a in ARGS]
    assert run(args)[0] == 0
    stub.releases = {"Gibberlings3/EndlessBG1": {"tag_name": "v2.0", "assets": [
        {"name": "m.zip", "browser_download_url": ASSET}]}}
    stub.blobs[ASSET] = buf.getvalue()

    code, out = run([*args, "--take-newer", "EndlessBG1"])

    assert code == 0, out
    rec = record(tmp_path)
    assert rec["status"] == "ok"
    assert any("declares support for" in a for a in rec["advisories"]), rec["advisories"]


def test_a_github_snapshot_is_not_offered_its_own_release(tmp_path, monkeypatch):
    """
    Measured on 2026-10-23 (download-sources, real=all): EET came as GitHub's
    source snapshot of v14.1, whose tp2 still says v14.0, and was offered
    v14.1 - the API's zipball URL did not read as GitHub.
    """
    snapshot = "https://api.github.com/repos/Gibberlings3/EndlessBG1/zipball/v2.0"
    stub = DiscoveryStub(
        owners={},
        releases={"Gibberlings3/EndlessBG1": {"tag_name": "v2.0", "assets": [],
                                               "zipball_url": snapshot}},
        blobs={snapshot: mod_zip("v1.0")})
    setup(tmp_path, monkeypatch, stub)

    code, out = run(ARGS)

    assert code == 0, out
    assert stub.downloaded == [snapshot]
    assert not record(tmp_path)["newer"]
    assert "--take-newer" not in out


@pytest.mark.parametrize("url,origin,github", [
    ("https://codeload.github.com/o/r/zip/refs/tags/v2.0", None, True),
    ("https://api.github.com/repos/o/r/zipball/v2.0", None, True),   # a state saved without origin
    ("https://www.shsforums.net/files/file/1-mod/", None, False),
    ("https://example.org/mod.zip", "release-asset", True),
])
def test_a_copy_reads_as_from_github_by_its_host_or_its_origin(url, origin, github):
    """Review of #63: a page that is not GitHub keeps its offer (`v3.1fr`
    over `v3.0` is still newer: test_versions)."""
    from iemod_fetch.runner import _from_github
    assert _from_github(url, origin) is github
