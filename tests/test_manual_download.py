"""
A gated download supplied by hand (GUI-AUDIT M8 item 68, ADR-0052): for a mod
this tool cannot download - its page behind Cloudflare, a JavaScript button,
a login - the player saves the file and names it; it is held to the
manifest's pinned sha256 when there is one, and always to what a download is
held to (an archive, under the byte ceiling, unpacking to this mod with its
.tp2). The file is read where it is: no folder is scanned or watched.
"""
import hashlib
import json

import pytest

from iemod_fetch import api
from iemod_fetch.errors import ConfigError

from test_cli_end_to_end import StubClient, zip_bytes

G3 = "https://www.gibberlings3.net/mods/kits/ub/"      # never fetched: a page link


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A selection of one mod whose only source is a gated page."""
    (tmp_path / "lcc.json").write_text(json.dumps({"mods": [
        {"id": 1, "name": "Unfinished Business", "tp2": "ub", "urls": []}]}))
    (tmp_path / api.PROJECT_FILE).write_text(
        "[iemod-fetch]\ncatalogue = lcc.json\nno_update_data = true\n"
        "no_default_data = true\nno_discovery = true\n")
    api.save_selection(str(tmp_path), "BG2EE", [("ub/setup-ub.tp2", 0)],
                       data_dir=str(tmp_path / "no-cache"))
    stub = StubClient(releases={}, blobs={})
    monkeypatch.setattr(api, "HttpClient", lambda **kw: stub)
    monkeypatch.setattr(api, "resolve_credential",
                        lambda **kw: type("C", (), {"token": None, "describe":
                                                    lambda self: "anonymous"})())
    monkeypatch.chdir(tmp_path.parent)
    return tmp_path, stub


def saved(tmp_path, data, name="ub-v30.zip"):
    downloads = tmp_path / "Downloads"
    downloads.mkdir(exist_ok=True)
    path = downloads / name
    path.write_bytes(data)
    return str(path)


def test_a_mod_with_no_download_is_installed_from_the_file_the_player_saved(project):
    folder, stub = project
    first = api.download_selection(str(folder))
    assert [r["status"] for r in first["records"]] == ["manual"]
    data = zip_bytes("ub", "ub/setup-ub.tp2")
    path = saved(folder, data)
    record = api.supply_download(str(folder), "ub", path)
    assert record["status"] == "ok", record
    assert "from the file you chose, ub-v30.zip" in record["detail"]
    assert "no sha256 is pinned" in record["detail"]
    assert (folder / "Mods" / "ub" / "setup-ub.tp2").exists()
    assert stub.downloaded == []                                    # nothing fetched
    with open(path, "rb") as fh:                                    # left as it was
        assert fh.read() == data
    state = json.loads((folder / "Mods" / ".iemod-fetch-state.json").read_text())["mods"]["ub"]
    assert state["origin"] == "supplied" and state["supplied_file"] == "ub-v30.zip"
    assert state["sha256"] == hashlib.sha256(data).hexdigest()      # pinnable next time
    # a later run counts it as installed, verified
    again = api.download_selection(str(folder))
    assert [r["status"] for r in again["records"]] == ["skipped"]


def test_another_mods_archive_is_refused_and_nothing_is_installed(project):
    folder, _stub = project
    record = api.supply_download(str(folder), "ub", saved(folder, zip_bytes("tweaks")))
    assert record["status"] == "failed" and "ub-v30.zip" in record["detail"]
    assert not (folder / "Mods" / "ub").exists()


def test_a_page_saved_instead_of_the_file_is_refused(project):
    folder, _stub = project
    page = b"<!DOCTYPE html><html><title>Just a moment...</title></html>"
    record = api.supply_download(str(folder), "ub", saved(folder, page, "ub.zip"))
    assert record["status"] == "failed" and record["error_code"] == "not_an_archive"


def test_an_installer_exe_is_refused_and_never_run(project):
    """Some SHS and Nexus mods ship a Windows installer: not unpacked unless
    the project allows it (--allow-exe), and never run."""
    folder, _stub = project
    record = api.supply_download(str(folder), "ub",
                                 saved(folder, b"MZ\x90\x00" + b"\x00" * 200, "setup-ub.exe"))
    assert record["status"] == "failed" and "Windows executable" in record["detail"]
    assert "never run" in record["detail"]
    assert not (folder / "Mods" / "ub").exists()


def test_a_file_over_the_byte_ceiling_is_refused(project):
    folder, stub = project
    stub.max_bytes = 10
    record = api.supply_download(str(folder), "ub",
                                 saved(folder, zip_bytes("ub", "ub/setup-ub.tp2")))
    assert record["status"] == "failed" and record["error_code"] == "too_large"


def test_no_file_is_no_install(project, tmp_path):
    folder, _stub = project
    with pytest.raises(ConfigError, match="is not a file"):
        api.supply_download(str(folder), "ub", str(tmp_path / "nowhere.zip"))
    with pytest.raises(ConfigError, match="is not a file"):
        api.supply_download(str(folder), "ub", str(tmp_path))       # a folder


def test_a_copy_already_there_is_replaced_and_kept(project):
    folder, _stub = project
    api.supply_download(str(folder), "ub", saved(folder, zip_bytes("ub", "ub/setup-ub.tp2")))
    record = api.supply_download(str(folder), "ub",
                                 saved(folder, zip_bytes("ub", "ub/setup-ub.tp2") + b"",
                                       "ub-v31.zip"))
    assert record["status"] == "ok" and "previous copy kept" in record["detail"]
    assert list((folder / "Mods" / ".backup").iterdir())


# ----------------------------------------------------- a pinned sha256
@pytest.fixture
def pinned(project):
    folder, stub = project
    data = zip_bytes("ub", "ub/setup-ub.tp2")
    (folder / "mod_downloads.json").write_text(json.dumps({"mods": [
        {"name": "Unfinished Business", "tp2": "ub", "url": G3,
         "sha256": hashlib.sha256(data).hexdigest()}]}))
    with open(folder / api.PROJECT_FILE, "a", encoding="utf-8") as fh:
        fh.write("manifest = mod_downloads.json\n")
    return folder, data


def test_with_a_pinned_sha256_only_that_file_is_taken(pinned):
    folder, data = pinned
    other = zip_bytes("ub", "ub/setup-ub.tp2").replace(b"hello", b"HELLO")
    refused = api.supply_download(str(folder), "ub", saved(folder, other, "other.zip"))
    assert refused["status"] == "failed" and refused["error_code"] == "checksum_mismatch"
    assert "this file is not the one pinned for this mod" in refused["detail"]
    assert hashlib.sha256(data).hexdigest() in refused["detail"]          # both hashes
    assert hashlib.sha256(other).hexdigest() in refused["detail"]
    manifest = json.loads((folder / "mod_downloads.json").read_text())
    assert manifest["mods"][0]["sha256"] == hashlib.sha256(data).hexdigest()   # untouched
    assert not (folder / "Mods" / "ub").exists()
    record = api.supply_download(str(folder), "ub", saved(folder, data))
    assert record["status"] == "ok" and "matches the pinned one" in record["detail"]
    assert record["url"] == G3                                      # the page it came from
