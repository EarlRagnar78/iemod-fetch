"""
Discovery in a full run: it may find a source, but it may never override the
strict .tp2 check. This is the guard that keeps ADR-0008 from re-introducing
legacy defect L7.
"""
import hashlib
import io
import json
import zipfile


from iemod_fetch import cli
from iemod_fetch.archives import Kind
from iemod_fetch.errors import NetworkError
from iemod_fetch.net import DownloadResult


def zip_bytes(folder):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{folder}/{folder}.tp2", "BACKUP ~x~")
    return buf.getvalue()


class DiscoveryStub:
    def __init__(self, owners, releases, blobs):
        self.owners, self.releases, self.blobs = owners, releases, blobs
        self.downloaded, self.calls = [], []

    def get_json(self, url):
        self.calls.append(url)
        for owner, repos in self.owners.items():
            if f"/users/{owner}/repos" in url:
                return ([{"name": r, "owner": {"login": owner}} for r in repos]
                        if "page=1" in url else [])
        for repo, payload in self.releases.items():
            if f"/repos/{repo}/" in url:
                return payload
        raise NetworkError(f"404 {url}")

    def download(self, url, dest_path, expected_sha256=None, require_archive=True):
        if url not in self.blobs:
            raise NetworkError(f"404 {url}")
        data = self.blobs[url]
        with open(dest_path, "wb") as fh:
            fh.write(data)
        self.downloaded.append(url)
        return DownloadResult(dest_path, hashlib.sha256(data).hexdigest(),
                              len(data), Kind.ZIP, url)

    def open(self, url):
        raise NetworkError(f"no landing page: {url}")


def make(tmp_path, monkeypatch, stub, weidu, manifest):
    (tmp_path / "WeiDU.log").write_text(weidu)
    (tmp_path / "mod_downloads.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(cli, "HttpClient", lambda **kw: stub)
    monkeypatch.setattr(cli, "resolve_credential",
                        lambda **kw: type("C", (), {"token": None,
                                                    "describe": lambda self: "anon"})())
    monkeypatch.chdir(tmp_path)


def run(args, extra=()):
    out = io.StringIO()
    code = cli.main([*args, *extra], stream=out)
    return code, out.getvalue()


WEIDU = "~EndlessBG1\\EndlessBG1.tp2~ #0 #0 // Endless BG1\n"
CATALOGUE = {"mods": [{"name": "Endless BG1", "tp2": "EndlessBG1"}]}   # no url, no github
ASSET = "https://github.com/Gibberlings3/EndlessBG1/releases/download/v1/mod.zip"


def test_a_mod_with_no_catalogue_source_is_found_in_a_trusted_owner(tmp_path, monkeypatch):
    stub = DiscoveryStub(
        owners={"Gibberlings3": ["EndlessBG1"]},
        releases={"Gibberlings3/EndlessBG1": {"tag_name": "v1", "assets": [
            {"name": "mod.zip", "browser_download_url": ASSET}]}},
        blobs={ASSET: zip_bytes("EndlessBG1")})
    make(tmp_path, monkeypatch, stub, WEIDU, CATALOGUE)

    code, out = run(["-w", "WeiDU.log", "-t", "Mods",
                     "--trusted-owner", "Gibberlings3"])

    assert code == 0, out
    assert (tmp_path / "Mods" / "EndlessBG1" / "EndlessBG1.tp2").exists()
    assert "DISCOVERED SOURCES" in out
    assert '"github": "Gibberlings3/EndlessBG1"' in out      # promote-me hint


def test_a_discovered_repo_with_the_wrong_tp2_is_not_installed(tmp_path, monkeypatch):
    """The owner is trusted and the name matches - and it is still refused."""
    stub = DiscoveryStub(
        owners={"Gibberlings3": ["EndlessBG1"]},
        releases={"Gibberlings3/EndlessBG1": {"tag_name": "v1", "assets": [
            {"name": "mod.zip", "browser_download_url": ASSET}]}},
        blobs={ASSET: zip_bytes("CompletelyDifferentMod")})
    make(tmp_path, monkeypatch, stub, WEIDU, CATALOGUE)

    code, out = run(["-w", "WeiDU.log", "-t", "Mods",
                     "--trusted-owner", "Gibberlings3"])

    assert code == 1
    assert not (tmp_path / "Mods" / "EndlessBG1").exists()
    assert "none of them is 'EndlessBG1.tp2'" in out


def test_discovery_never_overrides_a_working_catalogue_entry(tmp_path, monkeypatch):
    catalogue = {"mods": [{"name": "Endless BG1", "tp2": "EndlessBG1",
                           "github": "Gibberlings3/EndlessBG1"}]}
    stub = DiscoveryStub(
        owners={"Gibberlings3": ["EndlessBG1"]},
        releases={"Gibberlings3/EndlessBG1": {"tag_name": "v1", "assets": [
            {"name": "mod.zip", "browser_download_url": ASSET}]}},
        blobs={ASSET: zip_bytes("EndlessBG1")})
    make(tmp_path, monkeypatch, stub, WEIDU, catalogue)

    code, out = run(["-w", "WeiDU.log", "-t", "Mods"])
    assert code == 0
    assert "DISCOVERED SOURCES" not in out
    assert not any("/users/" in c for c in stub.calls)   # index never even built


def test_no_discovery_restores_the_strict_catalogue_only_behaviour(tmp_path, monkeypatch):
    stub = DiscoveryStub(
        owners={"Gibberlings3": ["EndlessBG1"]},
        releases={"Gibberlings3/EndlessBG1": {"tag_name": "v1", "assets": [
            {"name": "mod.zip", "browser_download_url": ASSET}]}},
        blobs={ASSET: zip_bytes("EndlessBG1")})
    make(tmp_path, monkeypatch, stub, WEIDU, CATALOGUE)

    code, out = run(["-w", "WeiDU.log", "-t", "Mods", "--no-discovery"])
    assert code == 1
    assert stub.downloaded == []
    assert "MANUAL ACTION REQUIRED" in out


def test_candidates_beyond_the_attempt_limit_are_reported_not_downloaded(
        tmp_path, monkeypatch):
    stub = DiscoveryStub(
        owners={"Gibberlings3": ["EndlessBG1"], "Pocket-Plane-Group": ["EndlessBG1"]},
        releases={},                                   # neither publishes a release
        blobs={})
    make(tmp_path, monkeypatch, stub, WEIDU, CATALOGUE)

    code, out = run(["-w", "WeiDU.log", "-t", "Mods",
                     "--trusted-owner", "Gibberlings3",
                     "--trusted-owner", "Pocket-Plane-Group"])
    assert code == 1
    assert stub.downloaded == []
    assert "candidates to review" in out


def test_the_real_shs_migration_case_is_handled(tmp_path, monkeypatch):
    """
    Five entries in the supplied manifest point at SpellholdStudios (no hyphen),
    the account SHS abandoned in 2022 after its owner disappeared; the mods now
    live in Spellhold-Studios (hyphenated). When the stale repo 404s, discovery
    finds the migrated one in the other trusted owner - which is exactly the
    class of breakage this feature exists for.
    """
    url = "https://github.com/Spellhold-Studios/Arath_NPC/releases/download/v1/m.zip"
    stub = DiscoveryStub(
        owners={"SpellholdStudios": [], "Spellhold-Studios": ["Arath_NPC"]},
        releases={"Spellhold-Studios/Arath_NPC": {"tag_name": "v6", "assets": [
            {"name": "m.zip", "browser_download_url": url}]}},
        blobs={url: zip_bytes("arath")})
    make(tmp_path, monkeypatch, stub,
         "~arath\\arath.tp2~ #0 #0 // Arath NPC\n",
         {"mods": [{"name": "Arath NPC", "tp2": "arath",
                    "github": "SpellholdStudios/Arath_NPC"}]})

    code, out = run(["-w", "WeiDU.log", "-t", "Mods",
                     "--trusted-owner", "SpellholdStudios",
                     "--trusted-owner", "Spellhold-Studios"])

    assert code == 0, out
    assert (tmp_path / "Mods" / "arath" / "arath.tp2").exists()
    assert '"github": "Spellhold-Studios/Arath_NPC"' in out


# ------------------------------------------------- supplementary catalogue
LCC_JSON = json.dumps({"mods": [
    {"tp2": "EndlessBG1", "name": "Endless BG1", "safe": 2, "status": ["stable"],
     "urls": ["https://forums.example/t/endless", "https://github.com/Gibberlings3/EndlessBG1"]},
    {"tp2": "Shaky", "name": "Shaky Mod", "safe": 1, "status": ["beta"],
     "last_update": "2017-10-18",
     "urls": ["https://github.com/Gibberlings3/Shaky"]},
]})


def test_a_catalogue_resolves_a_mod_the_manifest_cannot(tmp_path, monkeypatch):
    stub = DiscoveryStub(
        owners={},
        releases={"Gibberlings3/EndlessBG1": {"tag_name": "v1", "assets": [
            {"name": "mod.zip", "browser_download_url": ASSET}]}},
        blobs={ASSET: zip_bytes("EndlessBG1")})
    make(tmp_path, monkeypatch, stub, WEIDU, CATALOGUE)
    (tmp_path / "lcc.json").write_text(LCC_JSON)

    code, out = run(["-w", "WeiDU.log", "-t", "Mods", "-c", "lcc.json",
                     "--no-discovery", "--json-report", "r.json"])

    assert code == 0, out
    assert (tmp_path / "Mods" / "EndlessBG1" / "EndlessBG1.tp2").exists()
    assert '"github": "Gibberlings3/EndlessBG1"' in out          # promote-me hint
    warnings = json.loads((tmp_path / "r.json").read_text())["warnings"]
    assert any("resolved via lcc.json" in w for w in warnings)


def test_a_weidu_mod_absent_from_the_manifest_entirely_can_still_be_found(
        tmp_path, monkeypatch):
    """
    HPS_PORTRAITS_PROJECT-shaped case: the folder is in WeiDU.log but has no
    manifest entry at all. Without a fallback that is MANUAL; with a catalogue
    it becomes resolvable.
    """
    stub = DiscoveryStub(
        owners={},
        releases={"Gibberlings3/EndlessBG1": {"tag_name": "v1", "assets": [
            {"name": "mod.zip", "browser_download_url": ASSET}]}},
        blobs={ASSET: zip_bytes("EndlessBG1")})
    make(tmp_path, monkeypatch, stub, WEIDU,
         {"mods": [{"name": "Unrelated", "tp2": "somethingelse", "github": "o/r"}]})
    (tmp_path / "lcc.json").write_text(LCC_JSON)

    code, out = run(["-w", "WeiDU.log", "-t", "Mods", "-c", "lcc.json",
                     "--no-discovery", "--allow-manual"])
    assert (tmp_path / "Mods" / "EndlessBG1" / "EndlessBG1.tp2").exists(), out


def test_a_catalogue_entry_is_still_gated_by_the_tp2_check(tmp_path, monkeypatch):
    stub = DiscoveryStub(
        owners={},
        releases={"Gibberlings3/EndlessBG1": {"tag_name": "v1", "assets": [
            {"name": "mod.zip", "browser_download_url": ASSET}]}},
        blobs={ASSET: zip_bytes("NotTheRightMod")})
    make(tmp_path, monkeypatch, stub, WEIDU, CATALOGUE)
    (tmp_path / "lcc.json").write_text(LCC_JSON)

    code, out = run(["-w", "WeiDU.log", "-t", "Mods", "-c", "lcc.json"])
    assert code == 1
    assert not (tmp_path / "Mods" / "EndlessBG1").exists()


def test_catalogue_advisories_reach_the_report(tmp_path, monkeypatch):
    url = "https://github.com/Gibberlings3/Shaky/releases/download/v1/m.zip"
    stub = DiscoveryStub(
        owners={},
        releases={"Gibberlings3/Shaky": {"tag_name": "v1", "assets": [
            {"name": "m.zip", "browser_download_url": url}]}},
        blobs={url: zip_bytes("Shaky")})
    make(tmp_path, monkeypatch, stub, "~Shaky\\Shaky.tp2~ #0 #0 // Shaky\n",
         {"mods": [{"name": "Shaky", "tp2": "Shaky",
                    "github": "Gibberlings3/Shaky"}]})
    (tmp_path / "lcc.json").write_text(LCC_JSON)

    code, out = run(["-w", "WeiDU.log", "-t", "Mods", "-c", "lcc.json",
                     "--json-report", "r.json"])
    assert code == 0
    # printed next to the mod as it is installed, and again in a summary block
    assert "may cause problems" in out
    assert "MOD HEALTH WARNINGS" in out
    record = json.loads((tmp_path / "r.json").read_text())["records"][0]
    assert any("beta" in a for a in record["advisories"])


def test_a_direct_catalogue_url_is_used_ahead_of_the_repository(tmp_path, monkeypatch):
    """
    Real case: `vampire_world` lives inside Spellhold-Studios/Miscellaneous, a
    COLLECTION repository whose release assets are not the mod. The catalogue's
    direct link points at the archive itself, so it must win - and the GitHub
    API must not be consulted at all.
    """
    direct = ("https://github.com/Spellhold-Studios/Miscellaneous/raw/refs/heads/"
              "main/mods/EndlessBG1.zip")
    stub = DiscoveryStub(
        owners={},
        releases={"Spellhold-Studios/Miscellaneous": {"tag_name": "v1", "assets": [
            {"name": "something-else.zip",
             "browser_download_url": "https://github.com/x/wrong.zip"}]}},
        blobs={direct: zip_bytes("EndlessBG1")})
    make(tmp_path, monkeypatch, stub, WEIDU, CATALOGUE)
    (tmp_path / "lcc.json").write_text(json.dumps({"mods": [
        {"tp2": "EndlessBG1", "name": "Endless BG1", "safe": 2, "status": ["stable"],
         "urls": ["https://github.com/Spellhold-Studios/Miscellaneous", direct]}]}))

    code, out = run(["-w", "WeiDU.log", "-t", "Mods", "-c", "lcc.json",
                     "--no-discovery", "--json-report", "r.json"])

    assert code == 0, out
    assert (tmp_path / "Mods" / "EndlessBG1" / "EndlessBG1.tp2").exists()
    assert stub.downloaded == [direct]
    assert not any("/repos/" in c for c in stub.calls)      # API never consulted
    warnings = json.loads((tmp_path / "r.json").read_text())["warnings"]
    assert any("direct download" in w for w in warnings)


def test_the_catalogue_url_gets_a_turn_when_the_manifest_artefact_is_wrong(
        tmp_path, monkeypatch):
    """
    The manifest's repo resolves and downloads fine but contains a different
    mod. Rather than failing, the curated catalogue's URL is tried once - and
    the same strict .tp2 check still gates it.
    """
    wrong = "https://github.com/o/wrong/releases/download/v1/wrong.zip"
    right = "https://github.com/Gibberlings3/EndlessBG1/raw/refs/heads/main/EndlessBG1.zip"
    stub = DiscoveryStub(
        owners={},
        releases={"o/wrong": {"tag_name": "v1", "assets": [
            {"name": "wrong.zip", "browser_download_url": wrong}]}},
        blobs={wrong: zip_bytes("SomeOtherMod"), right: zip_bytes("EndlessBG1")})
    make(tmp_path, monkeypatch, stub, WEIDU,
         {"mods": [{"name": "Endless BG1", "tp2": "EndlessBG1", "github": "o/wrong"}]})
    (tmp_path / "lcc.json").write_text(json.dumps({"mods": [
        {"tp2": "EndlessBG1", "name": "Endless BG1", "urls": [right]}]}))

    code, out = run(["-w", "WeiDU.log", "-t", "Mods", "-c", "lcc.json",
                     "--no-discovery", "--json-report", "r.json"])

    assert code == 0, out
    assert (tmp_path / "Mods" / "EndlessBG1" / "EndlessBG1.tp2").exists()
    assert stub.downloaded == [wrong, right]          # tried the manifest first
    warnings = json.loads((tmp_path / "r.json").read_text())["warnings"]
    assert any("did not contain this mod" in w for w in warnings)


def test_the_retry_does_not_lower_the_bar(tmp_path, monkeypatch):
    """If the catalogue's artefact is also wrong, the run still fails."""
    wrong = "https://github.com/o/wrong/releases/download/v1/wrong.zip"
    alsowrong = "https://host.example/also-wrong.zip"
    stub = DiscoveryStub(
        owners={},
        releases={"o/wrong": {"tag_name": "v1", "assets": [
            {"name": "wrong.zip", "browser_download_url": wrong}]}},
        blobs={wrong: zip_bytes("SomeOtherMod"), alsowrong: zip_bytes("StillWrong")})
    make(tmp_path, monkeypatch, stub, WEIDU,
         {"mods": [{"name": "Endless BG1", "tp2": "EndlessBG1", "github": "o/wrong"}]})
    (tmp_path / "lcc.json").write_text(json.dumps({"mods": [
        {"tp2": "EndlessBG1", "name": "Endless BG1", "urls": [alsowrong]}]}))

    code, out = run(["-w", "WeiDU.log", "-t", "Mods", "-c", "lcc.json", "--no-discovery"])
    assert code == 1
    assert not (tmp_path / "Mods" / "EndlessBG1").exists()


def test_the_catalogue_supplies_the_renamed_tp2_automatically(tmp_path, monkeypatch):
    """
    Real case: the log says `Reflections`, the mod ships `Reflections_of_Destiny`,
    and the catalogue knows it — so no manual expect_tp2 is needed.
    """
    url = "https://github.com/subtledoctor/Reflections-of-Destiny/releases/download/v1/m.zip"
    stub = DiscoveryStub(
        owners={},
        releases={"subtledoctor/Reflections-of-Destiny": {"tag_name": "v1", "assets": [
            {"name": "m.zip", "browser_download_url": url}]}},
        blobs={url: zip_bytes("Reflections_of_Destiny")})
    make(tmp_path, monkeypatch, stub,
         "~Reflections\\Reflections.tp2~ #0 #0 // Reflections of Destiny\n",
         {"mods": [{"name": "Reflections of Destiny", "tp2": "Reflections",
                    "github": "subtledoctor/Reflections-of-Destiny"}]})
    (tmp_path / "lcc.json").write_text(json.dumps({"mods": [
        {"tp2": "Reflections_of_Destiny", "name": "Reflections of Destiny",
         "urls": ["https://github.com/subtledoctor/Reflections-of-Destiny/"]}]}))

    code, out = run(["-w", "WeiDU.log", "-t", "Mods", "-c", "lcc.json", "--no-discovery"])

    assert code == 0, out
    assert (tmp_path / "Mods" / "Reflections_of_Destiny" /
            "Reflections_of_Destiny.tp2").exists()
    assert "now ships as" in out
