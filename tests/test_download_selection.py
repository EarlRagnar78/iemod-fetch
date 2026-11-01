"""
The wizard's download phase without a window (M3 phase 4, ADR-0039): the
project's selection fetched, verified and extracted by the run the command
line makes in the project - with no manifest, the community catalogue is where
every mod is found - with progress events, resume, retry of what failed, and
cancel. The transport is a stub: no network.
"""
import json
import os
import threading

import pytest

from iemod_fetch import api
from iemod_fetch.errors import ConfigError

from test_cli_end_to_end import StubClient, zip_bytes

DLC = "DlcMerger/DlcMerger.tp2"
FIX = "eefixpack/SETUP-EEFIXPACK.TP2"
URL_A = "https://github.com/o/r/releases/download/v1/DlcMerger.iemod"
URL_B = "https://github.com/o/r/releases/download/v2/eefixpack.zip"
SCHEMA = os.path.join(os.path.dirname(__file__), os.pardir, "schemas",
                      "events-v1.schema.json")


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "lcc.json").write_text(json.dumps({"mods": [
        {"id": 1, "name": "DLC Merger", "tp2": "DlcMerger",
         "urls": ["https://github.com/Argent77/A7-DlcMerger"]},
        {"id": 2, "name": "EE Fixpack", "tp2": "eefixpack",
         "urls": ["https://github.com/o/eefixpack"]}]}))
    (tmp_path / api.PROJECT_FILE).write_text(
        "[iemod-fetch]\ncatalogue = lcc.json\nno_update_data = true\n"
        "no_default_data = true\nno_discovery = true\n")
    api.save_selection(str(tmp_path), "BGEE", [(DLC, 0), (FIX, 0)],
                       data_dir=str(tmp_path / "no-cache"))
    stub = StubClient(
        releases={
            "Argent77/A7-DlcMerger": {"tag_name": "v1", "assets": [
                {"name": "DlcMerger.iemod", "browser_download_url": URL_A}]},
            "o/eefixpack": {"tag_name": "v2", "assets": [
                {"name": "eefixpack.zip", "browser_download_url": URL_B}]}},
        blobs={URL_A: zip_bytes("DlcMerger"),
               URL_B: zip_bytes("eefixpack", FIX)})
    monkeypatch.setattr(api, "HttpClient", lambda **kw: stub)
    monkeypatch.setattr(api, "resolve_credential",
                        lambda **kw: type("C", (), {"token": None, "describe":
                                                    lambda self: "anonymous"})())
    monkeypatch.chdir(tmp_path.parent)      # the project is read wherever we are
    return tmp_path, stub


def statuses(result):
    return {r["folder"]: r["status"] for r in result["records"]}


def test_with_no_manifest_the_catalogue_finds_every_mod(project):
    folder, stub = project
    events = []
    result = api.download_selection(str(folder), on_event=events.append)
    assert statuses(result) == {"DlcMerger": "ok", "eefixpack": "ok"}
    assert result["exit_code"] == 0 and not result["cancelled"]
    assert (folder / "Mods" / "DlcMerger" / "DlcMerger.tp2").exists()
    assert sorted(stub.downloaded) == sorted([URL_A, URL_B])
    # each mod: started, extracting once its download is verified, finished
    for mod in ("DlcMerger", "eefixpack"):
        kinds = [e["event"] for e in events if e.get("folder") == mod]
        assert kinds == ["mod_started", "mod_extracting", "mod_finished"]
    jsonschema = pytest.importorskip("jsonschema")
    with open(SCHEMA, encoding="utf-8") as fh:
        schema = json.load(fh)
    for event in events:
        jsonschema.validate(event, schema)


def test_running_again_resumes_and_downloads_nothing(project):
    folder, stub = project
    api.download_selection(str(folder))
    stub.downloaded.clear()
    result = api.download_selection(str(folder))
    assert statuses(result) == {"DlcMerger": "skipped", "eefixpack": "skipped"}
    assert stub.downloaded == []


def test_retrying_the_failed_ones_touches_nothing_else(project):
    folder, stub = project
    blob = stub.blobs.pop(URL_B)
    first = api.download_selection(str(folder))
    assert statuses(first) == {"DlcMerger": "ok", "eefixpack": "failed"}
    assert first["exit_code"] != 0
    stub.blobs[URL_B] = blob
    stub.downloaded.clear()
    again = api.download_selection(str(folder), only=["eefixpack"])
    assert statuses(again) == {"eefixpack": "ok"}
    assert stub.downloaded == [URL_B]


def test_a_cancelled_run_says_so_and_installs_nothing(project):
    folder, stub = project
    stop = threading.Event()
    stop.set()
    result = api.download_selection(str(folder), cancel=stop)
    assert result["cancelled"]
    assert set(statuses(result).values()) == {"cancelled"}
    assert stub.downloaded == []


def test_no_manifest_and_no_catalogue_is_no_download_source(project):
    folder, _stub = project
    (folder / api.PROJECT_FILE).write_text(
        "[iemod-fetch]\nno_update_data = true\nno_default_data = true\n")
    with pytest.raises(ConfigError, match="no download source"):
        api.download_selection(str(folder))


def test_a_manifest_named_in_the_project_is_read_from_the_project(project):
    folder, stub = project
    (folder / "mods.json").write_text(json.dumps({"mods": [
        {"name": "DLC Merger", "tp2": "DlcMerger", "github": "Argent77/A7-DlcMerger"},
        {"name": "EE Fixpack", "tp2": "eefixpack", "github": "o/eefixpack"}]}))
    (folder / api.PROJECT_FILE).write_text(
        "[iemod-fetch]\nmanifest = mods.json\ntarget = Out\nno_update_data = true\n"
        "no_default_data = true\nno_discovery = true\n")
    settings = api.project_settings(str(folder))
    assert settings.manifest == str(folder / "mods.json")
    assert settings.target == str(folder / "Out")
    result = api.download_selection(str(folder))
    assert statuses(result) == {"DlcMerger": "ok", "eefixpack": "ok"}
    assert (folder / "Out" / "eefixpack").is_dir()


def test_without_a_manifest_or_catalogue_flag_the_project_has_none(tmp_path):
    settings = api.project_settings(str(tmp_path))       # no ini at all
    assert settings.manifest is None
    assert settings.target == str(tmp_path / "Mods")


# ----------------------------------------- what the wizard's ini holds
@pytest.mark.parametrize("game,folders", [
    ("EET", {"bgee_dir": "BGEE_DIR", "bg2ee_dir": "BG2EE_DIR"}),
    ("BGEE", {"bgee_dir": "BGEE_DIR"}),            # one game: one folder
    ("BG2EE", {"bg2ee_dir": "BG2EE_DIR"})])
def test_a_project_the_wizard_saved_downloads(project, game, folders):
    # Review of #39: phase 1 saves the game folders and languages, which only
    # a plan uses; the download refused every project the wizard made.
    folder, _stub = project
    paths = {key: str(folder / value) for key, value in folders.items()}
    # saved over the fixture's ini, whose catalogue and offline settings stay
    api.save_project(str(folder), game, language_preference=["it_IT", "en_US"], **paths)
    assert "language_preference" in (folder / api.PROJECT_FILE).read_text()
    result = api.download_selection(str(folder))
    assert statuses(result) == {"DlcMerger": "ok", "eefixpack": "ok"}


def test_the_command_line_in_a_wizard_project_fetches_the_same(project, monkeypatch):
    from iemod_fetch import cli
    folder, stub = project
    api.save_project(str(folder), "EET", str(folder / "a"), str(folder / "b"), ["en_US"])
    monkeypatch.chdir(folder)            # no mod_downloads.json here: the catalogue
    code = cli.main(["--config", api.PROJECT_FILE, "--selection", api.SELECTION_FILE],
                    stream=__import__("io").StringIO())
    assert code == 0
    assert sorted(stub.downloaded) == sorted([URL_A, URL_B])
    assert (folder / "Mods" / "eefixpack").is_dir()


def test_a_manifest_named_on_purpose_must_exist(project, monkeypatch):
    from iemod_fetch import cli
    folder, _stub = project
    monkeypatch.chdir(folder)
    code = cli.main(["--config", api.PROJECT_FILE, "--selection", api.SELECTION_FILE,
                     "-m", "typo.json"], stream=__import__("io").StringIO())
    assert code == 2                     # not silently the catalogue instead


def test_the_selection_is_what_is_fetched_whatever_the_ini_says(project):
    folder, stub = project
    api.save_selection(str(folder), "BGEE", [(FIX, 0)], data_dir=str(folder / "no-cache"))
    (folder / "mods.json").write_text(json.dumps({"mods": [
        {"name": "DLC Merger", "tp2": "DlcMerger", "github": "Argent77/A7-DlcMerger"},
        {"name": "EE Fixpack", "tp2": "eefixpack", "github": "o/eefixpack"}]}))
    (folder / api.PROJECT_FILE).write_text(
        "[iemod-fetch]\nmanifest = mods.json\nall_manifest_entries = true\n"
        "only = DlcMerger\ncheck_only = true\nno_update_data = true\n"
        "no_default_data = true\nno_discovery = true\n")
    result = api.download_selection(str(folder))
    assert statuses(result) == {"eefixpack": "ok"}
    assert stub.downloaded == [URL_B]


def test_a_mod_with_no_source_is_counted(project):
    folder, _stub = project
    (folder / "mods.json").write_text(json.dumps({"mods": [
        {"name": "EE Fixpack", "tp2": "eefixpack", "github": "o/eefixpack"}]}))
    (folder / api.PROJECT_FILE).write_text(
        "[iemod-fetch]\nmanifest = mods.json\nno_update_data = true\n"
        "no_default_data = true\nno_discovery = true\n")
    result = api.download_selection(str(folder))
    assert statuses(result) == {"eefixpack": "ok", "DlcMerger": "manual"}
    assert result["counts"]["manual"] == 1 and result["counts"]["ok"] == 1


def test_a_plan_flag_typed_with_another_value_is_still_refused(project, monkeypatch):
    # the ini's own value passes; a different one typed without --plan-order
    # would do nothing, and says so
    from iemod_fetch import cli
    folder, _stub = project
    api.save_project(str(folder), "BGEE", str(folder / "a"), None, ["en_US"])
    monkeypatch.chdir(folder)
    err = __import__("io").StringIO()
    monkeypatch.setattr("sys.stderr", err)
    code = cli.main(["--config", api.PROJECT_FILE, "--selection", api.SELECTION_FILE,
                     "--check-only", "--language-preference", "fr_FR"],
                    stream=__import__("io").StringIO())
    assert code == 2 and "--language-preference works on an install plan" in err.getvalue()


def test_with_no_manifest_a_failed_mod_says_what_the_catalogue_tried(project):
    # Measured on the real catalogue: every miss read "entry has no url and no
    # github repository", hiding the repository tried and its answer
    folder, stub = project
    del stub.releases["o/eefixpack"]
    api.save_selection(str(folder), "BGEE", [(DLC, 0), (FIX, 0), ("ghost/ghost.tp2", 0)],
                       data_dir=str(folder / "no-cache"))
    result = api.download_selection(str(folder))
    details = {r["folder"]: r["detail"] for r in result["records"]}
    assert "o/eefixpack" in details["eefixpack"]
    assert "no url and no github" not in details["eefixpack"]
    assert details["ghost"] == "no manifest entry, and the catalogue does not list this mod"


def test_take_newer_reaches_the_run_and_each_record_carries_its_offer(project, monkeypatch):
    """GUI-AUDIT item 59: the wizard's button is the command line's --take-newer."""
    folder, _ = project
    seen = {}
    real_run = api.run

    def spy(settings, **kw):
        seen["take_newer"] = settings.take_newer
        return real_run(settings, **kw)

    monkeypatch.setattr(api, "run", spy)
    result = api.download_selection(str(folder), take_newer=["DlcMerger"])
    assert seen["take_newer"] == ["DlcMerger"]
    assert all("newer" in r for r in result["records"])


@pytest.mark.parametrize("name", ["only", "take_newer"])
def test_a_folder_name_given_alone_is_refused(project, name):
    """Review of #62: "Ascension" was read as A, s, c, e, n, ..."""
    folder, _ = project
    with pytest.raises(ConfigError, match="list of mod folders"):
        api.download_selection(str(folder), **{name: "Ascension"})
