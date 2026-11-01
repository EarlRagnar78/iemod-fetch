"""
The community data, kept current automatically (ADR-0032).

Order and conflict decisions are only as good as the lcc-docs, BWS-NG and
krion64 data behind them, and a clone nobody pulls goes stale silently. The
tool now refreshes a cache of that data on its own: once per `max_age`, only
the files it reads, only the ones that changed, each checked against the git
blob hash GitHub lists for it, and swapped in whole so a failed refresh never
leaves half an update. Offline, the last good copy is used and the run says so.
"""
import calendar
import hashlib
import json
import os
import time
import urllib.parse

import pytest

from iemod_fetch import datasync
from iemod_fetch.datasync import Source, data_paths, refresh
from iemod_fetch.errors import NetworkError

LCC = Source("lcc-docs", "o/lcc", ("db/mods.json",))
KRION = Source("krion64", "o/krion", ("data/categories.json", "data/mods/"))


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()  # noqa: S324


class FakeGitHub:
    """Repositories in memory: the two API calls and the raw files."""

    def __init__(self):
        self.repos = {}
        self.calls = []
        self.offline = False

    def publish(self, repo, files, date="2026-10-01T12:00:00Z"):
        sha = hashlib.sha1(repr(sorted(files.items())).encode()).hexdigest()  # noqa: S324
        self.repos[repo] = {"sha": sha, "date": date, "files": dict(files)}
        return sha

    def get_json(self, url):
        self.calls.append(url)
        if self.offline:
            raise NetworkError(f"{url}: offline")
        for repo, state in self.repos.items():
            if url == f"https://api.github.com/repos/{repo}/commits/HEAD":
                return {"sha": state["sha"],
                        "commit": {"committer": {"date": state["date"]}}}
            if url == f"https://api.github.com/repos/{repo}/git/trees/{state['sha']}?recursive=1":
                return {"truncated": state.get("truncated", False), "tree": [
                    {"path": p, "type": "blob", "sha": state.get("lie", {}).get(p, blob_sha(d)),
                     "size": len(d)} for p, d in state["files"].items()]}
        raise NetworkError(f"404 {url}")

    def read_bytes(self, url, limit=None):
        self.calls.append(url)
        # A URL is what a server sees: '#' starts a fragment and is never sent,
        # a space is not a valid character. Serve only what a real server would.
        sent = urllib.parse.urlsplit(url)
        if sent.fragment or " " in url:
            raise NetworkError(f"404 {url}")
        for repo, state in self.repos.items():
            prefix = f"/{repo}/{state['sha']}/"
            if sent.netloc == "raw.githubusercontent.com" and sent.path.startswith(prefix):
                path = urllib.parse.unquote(sent.path[len(prefix):])
                if path in state["files"]:
                    return state["files"][path]
        raise NetworkError(f"404 {url}")

    def raw_calls(self):
        return [c for c in self.calls if "raw.githubusercontent" in c]


@pytest.fixture
def hub():
    hub = FakeGitHub()
    hub.publish("o/lcc", {"db/mods.json": b"[]", "db/mods_fr.json": b"[]",
                          "README.md": b"x"})
    hub.publish("o/krion", {"data/categories.json": b'{"categories": {"A": {}}}',
                            "data/mods/a.json": b'{"t": "a"}',
                            "data/mods/b.json": b'{"t": "b"}',
                            "img/big.png": b"\x89PNG"})
    return hub


def test_the_first_refresh_fetches_only_the_files_the_tool_reads(tmp_path, hub):
    results = refresh(hub, str(tmp_path), (LCC, KRION))
    assert [r.status for r in results] == ["updated", "updated"]
    assert sorted(c.rsplit("/", 2)[-1] for c in hub.raw_calls()) == [
        "a.json", "b.json", "categories.json", "mods.json"]
    assert (tmp_path / "lcc-docs" / "db" / "mods.json").read_bytes() == b"[]"
    assert not (tmp_path / "lcc-docs" / "db" / "mods_fr.json").exists()
    manifest = json.loads((tmp_path / "sources.json").read_text())
    assert manifest["krion64"]["commit"] == hub.repos["o/krion"]["sha"]


def test_within_max_age_the_network_is_not_touched(tmp_path, hub):
    refresh(hub, str(tmp_path), (LCC, KRION))
    hub.calls.clear()
    results = refresh(hub, str(tmp_path), (LCC, KRION), max_age_hours=24)
    assert hub.calls == []
    assert [r.status for r in results] == ["fresh", "fresh"]


def test_an_unchanged_commit_costs_one_request_and_no_download(tmp_path, hub):
    refresh(hub, str(tmp_path), (LCC, KRION))
    hub.calls.clear()
    results = refresh(hub, str(tmp_path), (LCC, KRION), max_age_hours=0)
    assert [r.status for r in results] == ["current", "current"]
    assert len(hub.calls) == 2 and hub.raw_calls() == []


def test_a_new_commit_downloads_only_what_changed_and_drops_what_went(tmp_path, hub):
    refresh(hub, str(tmp_path), (KRION,))
    hub.publish("o/krion", {"data/categories.json": b'{"categories": {"A": {}}}',
                            "data/mods/a.json": b'{"t": "a", "v": "2"}'})
    hub.calls.clear()
    (result,) = refresh(hub, str(tmp_path), (KRION,), force=True)
    assert result.status == "updated" and (result.changed, result.removed) == (1, 1)
    assert [c.rsplit("/", 1)[-1] for c in hub.raw_calls()] == ["a.json"]
    assert not (tmp_path / "krion64" / "data" / "mods" / "b.json").exists()


def test_a_file_whose_hash_does_not_match_keeps_the_last_good_copy(tmp_path, hub):
    refresh(hub, str(tmp_path), (KRION,))
    hub.publish("o/krion", {"data/categories.json": b"tampered",
                            "data/mods/a.json": b'{"t": "a"}'})
    hub.repos["o/krion"]["lie"] = {"data/categories.json": "0" * 40}
    (result,) = refresh(hub, str(tmp_path), (KRION,), force=True)
    assert result.status == "failed" and "hash" in result.detail
    assert (tmp_path / "krion64" / "data" / "categories.json").read_bytes() \
        == b'{"categories": {"A": {}}}'
    assert (tmp_path / "krion64" / "data" / "mods" / "b.json").exists()


def test_paths_that_would_leave_the_cache_are_ignored(tmp_path, hub):
    hub.publish("o/krion", {"data/categories.json": b"{}",
                            "data/mods/../../../evil.json": b"{}",
                            "data/mods/ok.json": b"{}"})
    (result,) = refresh(hub, str(tmp_path), (KRION,))
    assert result.status == "updated"
    assert not (tmp_path.parent / "evil.json").exists()
    assert sorted(os.listdir(tmp_path / "krion64" / "data" / "mods")) == ["ok.json"]


def test_a_truncated_tree_is_refused_rather_than_half_used(tmp_path, hub):
    hub.repos["o/krion"]["truncated"] = True
    (result,) = refresh(hub, str(tmp_path), (KRION,))
    assert result.status == "failed" and "truncated" in result.detail


def test_offline_the_last_good_copy_is_still_served(tmp_path, hub):
    refresh(hub, str(tmp_path), (LCC, KRION))
    hub.offline = True
    results = refresh(hub, str(tmp_path), (LCC, KRION), force=True)
    assert [r.status for r in results] == ["failed", "failed"]
    paths = data_paths(str(tmp_path), (LCC, KRION))
    assert paths.catalogue.endswith(os.path.join("db", "mods.json"))
    assert paths.order_catalogue and os.path.isdir(paths.order_catalogue)


def test_cached_files_carry_the_upstream_commit_date(tmp_path, hub):
    """Rule staleness is judged by file age, so the age must be upstream's."""
    refresh(hub, str(tmp_path), (LCC,))
    stamp = os.path.getmtime(tmp_path / "lcc-docs" / "db" / "mods.json")
    expected = calendar.timegm(time.strptime("2026-10-01T12:00:00Z", "%Y-%m-%dT%H:%M:%SZ"))
    assert abs(stamp - expected) < 2


def test_the_cache_supplies_every_source_the_planner_reads(tmp_path):
    for rel in ("lcc-docs/db/mods.json", "bws-ng/data/rules/order.json",
                "bws-ng/data/mods/x.json", "bws-ng/data/games/eet.json",
                "krion64/data/categories.json",
                "krion64/data/mods/x.json", "krion64/data/version_cache.json"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
    paths = data_paths(str(tmp_path))
    assert paths.catalogue == str(tmp_path / "lcc-docs" / "db" / "mods.json")
    assert paths.rules == [str(tmp_path / "bws-ng" / "data" / "rules"),
                           str(tmp_path / "krion64" / "data" / "mods")]
    assert paths.mod_db == str(tmp_path / "bws-ng" / "data" / "mods")
    assert paths.order_catalogue == str(tmp_path / "krion64" / "data")
    assert paths.eet_sequence == str(tmp_path / "bws-ng" / "data" / "games" / "eet.json")
    assert paths.releases == str(tmp_path / "krion64" / "data" / "version_cache.json")


def test_the_default_sources_are_the_three_community_databases():
    assert [s.repo for s in datasync.SOURCES] == [
        "RiwsPy/lcc-docs", "Selphira/BigWorldSetup-Next-Generation",
        "krion64/krion64.github.io"]


# ---------------------------------------------------------- through the API
import shutil  # noqa: E402

from iemod_fetch import api, cli  # noqa: E402

HERE = os.path.dirname(__file__)
KRION_DATA = os.path.join(HERE, "data", "krion")
MANIFEST = os.path.join(HERE, "data", "mod_downloads.json")
REAL_EET = os.path.join(HERE, "data", "WeiDU.log")


def _cli(argv):
    import io
    out = io.StringIO()
    return cli.main(argv, stream=out), out.getvalue()


@pytest.fixture
def cached_krion(monkeypatch, tmp_path):
    """A cache that already holds krion64's data, as a refresh leaves it."""
    data = tmp_path / "cache"
    shutil.copytree(KRION_DATA, data / "krion64" / "data")
    monkeypatch.setenv("IEMOD_DATA_DIR", str(data))
    return data


def test_the_cache_stands_in_for_a_flag_that_was_not_given(cached_krion, tmp_path):
    """--plan-order used to need --order-catalogue; the cached krion64 data is it."""
    code, out = _cli(["--check-only", "-q", "-m", MANIFEST, "-w", f"{REAL_EET}:EET",
                      "-t", str(tmp_path / "Mods"), "--plan-order", str(tmp_path / "plan")])
    assert code in (0, 1), out
    assert (tmp_path / "plan" / "WeiDU.log").is_file()


def test_no_default_data_turns_the_cache_off(cached_krion, tmp_path):
    code, _out = _cli(["--check-only", "-q", "-m", MANIFEST, "-w", f"{REAL_EET}:EET",
                       "--plan-order", str(tmp_path / "plan"), "--no-default-data"])
    assert code == 2                             # --order-catalogue is needed again


def test_a_run_refreshes_the_data_when_it_starts(monkeypatch, tmp_path, hub):
    monkeypatch.delenv("IEMOD_NO_UPDATE_DATA")
    monkeypatch.setattr(api, "_http_client", lambda settings: hub)
    monkeypatch.setattr(datasync, "SOURCES", (LCC, KRION))
    events = []
    api.run(api.Settings(list_mods="-", manifest=MANIFEST,
                         data_dir=str(tmp_path / "cache")), on_event=events.append)
    assert [e["status"] for e in events if e["event"] == "data_source"] == [
        "updated", "updated"]
    assert (tmp_path / "cache" / "lcc-docs" / "db" / "mods.json").is_file()
    hub.calls.clear()
    api.run(api.Settings(list_mods="-", manifest=MANIFEST,
                         data_dir=str(tmp_path / "cache")))
    assert hub.calls == []                       # within --data-max-age


def test_update_data_refreshes_now_and_stops(monkeypatch, tmp_path, hub):
    monkeypatch.setattr(api, "_http_client", lambda settings: hub)
    monkeypatch.setattr(datasync, "SOURCES", (LCC, KRION))
    code, out = _cli(["--update-data", "--data-dir", str(tmp_path / "cache")])
    assert code == 0
    assert "lcc-docs: updated to" in out and "krion64: updated to" in out
    hub.offline = True
    code, out = _cli(["--update-data", "--data-dir", str(tmp_path / "cache")])
    assert code == 1 and "not refreshed" in out and "keeping" in out


def test_a_fresh_cache_does_not_even_look_for_a_credential(monkeypatch, tmp_path, hub):
    """Resolving a token runs `gh` and git's credential helper: not on every start."""
    monkeypatch.setattr(datasync, "SOURCES", (LCC,))
    monkeypatch.setattr(api, "_http_client", lambda settings: hub)
    api.update_data(api.Settings(data_dir=str(tmp_path)))
    built = []
    monkeypatch.setattr(api, "_http_client", lambda settings: built.append(1) or hub)
    api.update_data(api.Settings(data_dir=str(tmp_path)))
    assert built == []


def test_file_names_with_hash_or_space_are_fetched(tmp_path, hub):
    """
    Found by the first refresh against the real GitHub: BWS-NG and krion64 name
    files after mods like `A7#ImprovedArcher`, and an unencoded '#' turns the
    rest of the URL into a fragment the server never sees - a 404.
    """
    hub.publish("o/krion", {"data/categories.json": b"{}",
                            "data/mods/A7#ImprovedArcher.json": b'{"t": "x"}',
                            "data/mods/Two Words.json": b"{}"})
    (result,) = refresh(hub, str(tmp_path), (KRION,))
    assert result.status == "updated", result.detail
    assert (tmp_path / "krion64" / "data" / "mods" / "A7#ImprovedArcher.json").is_file()


# ------------------------------------------------- guards on upstream changes
# A refresh is only as good as what it brings in. Before the new copy replaces
# the last good one it is read with the tool's own parsers; a copy that does
# not parse, or whose counts collapse, is refused. What did change - rules,
# mods, versions, statuses - is recorded, so an update is never silent.
def _fixture_files(directory, prefix):
    files = {}
    for root, _dirs, names in os.walk(directory):
        for name in names:
            path = os.path.join(root, name)
            rel = os.path.relpath(path, directory).replace(os.sep, "/")
            with open(path, "rb") as fh:
                files[f"{prefix}/{rel}"] = fh.read()
    return files


KRION_CHECKED = Source("krion64", "o/krion", ("data/categories.json", "data/mods/",
                                             "data/version_cache.json"),
                       check=datasync.check_krion64)
LCC_CHECKED = Source("lcc-docs", "o/lcc", ("db/mods.json",), check=datasync.check_lcc_docs)


ONE_PP = {"t": "1pp", "c": "GRAPHICS", "ord": 100, "v": "v4.2.1", "conflicts": [
    {"with": "cdtweaks", "severity": "hard", "reason": "avatar by armour",
     "myComps": "#113; #104", "theirComps": "#120; #80", "source": "eemodsetup",
     "evidenceLevel": "mechanism-verified"}]}


@pytest.fixture
def real_krion(hub):
    """The krion64 fixture plus one record in krion64's real conflict format."""
    files = _fixture_files(KRION_DATA, "data")
    files["data/mods/1pp.json"] = json.dumps(ONE_PP).encode()
    hub.publish("o/krion", files)
    return files


def test_a_good_update_is_measured_and_kept(tmp_path, hub, real_krion):
    (result,) = refresh(hub, str(tmp_path), (KRION_CHECKED,))
    assert result.status == "updated", result.detail
    entry = json.loads((tmp_path / "sources.json").read_text())["krion64"]
    assert entry["metrics"]["order entries"] > 0 and entry["metrics"]["rules"] > 0


def test_an_update_whose_counts_collapse_is_refused(tmp_path, hub, real_krion):
    refresh(hub, str(tmp_path), (KRION_CHECKED,))
    kept = {p: d for p, d in real_krion.items() if not p.startswith("data/mods/")}
    kept["data/mods/EET_END.json"] = real_krion["data/mods/EET_END.json"]
    hub.publish("o/krion", kept)
    (result,) = refresh(hub, str(tmp_path), (KRION_CHECKED,), force=True)
    assert result.status == "rejected" and "collapsed" in result.detail
    assert (tmp_path / "krion64" / "data" / "mods" / "cdtweaks.json").is_file()


def test_an_update_that_does_not_parse_is_refused(tmp_path, hub, real_krion):
    refresh(hub, str(tmp_path), (KRION_CHECKED,))
    hub.publish("o/krion", {**real_krion, "data/categories.json": b"{not json"})
    (result,) = refresh(hub, str(tmp_path), (KRION_CHECKED,), force=True)
    assert result.status == "rejected" and "categories.json" in result.detail
    good = (tmp_path / "krion64" / "data" / "categories.json").read_bytes()
    assert good == real_krion["data/categories.json"]


def test_a_refused_commit_is_not_downloaded_again(tmp_path, hub, real_krion):
    refresh(hub, str(tmp_path), (KRION_CHECKED,))
    hub.publish("o/krion", {**real_krion, "data/categories.json": b"{not json"})
    refresh(hub, str(tmp_path), (KRION_CHECKED,), force=True)
    hub.calls.clear()
    (result,) = refresh(hub, str(tmp_path), (KRION_CHECKED,), force=True)
    assert result.status == "rejected"
    assert hub.raw_calls() == [] and len(hub.calls) == 1


def test_what_changed_upstream_is_reported(tmp_path, hub, real_krion):
    refresh(hub, str(tmp_path), (KRION_CHECKED,))
    changed = dict(real_krion)
    record = json.loads(changed["data/mods/cdtweaks.json"])
    record["v"] = "v99"
    changed["data/mods/cdtweaks.json"] = json.dumps(record).encode()
    del changed["data/mods/eeex.json"]
    hub.publish("o/krion", changed)
    (result,) = refresh(hub, str(tmp_path), (KRION_CHECKED,), force=True)
    assert result.status == "updated", result.detail
    changes = result.changes
    assert changes["removed"] == ["eeex"]
    assert changes["changed"]["cdtweaks"][1] == "v99"
    text = "\n".join(datasync.describe([result]))
    assert "1 removed" in text and "cdtweaks" in text and "v99" in text


def test_a_status_change_in_the_mod_list_is_reported(tmp_path, hub):
    entries = [{"tp2": "oldmod", "name": "Old", "status": [], "last_update": "2024-01-01"},
               {"tp2": "keep", "name": "Keep"}]
    hub.publish("o/lcc", {"db/mods.json": json.dumps(entries).encode()})
    refresh(hub, str(tmp_path), (LCC_CHECKED,))
    entries[0]["status"] = ["obsolete"]
    hub.publish("o/lcc", {"db/mods.json": json.dumps(entries).encode()})
    (result,) = refresh(hub, str(tmp_path), (LCC_CHECKED,), force=True)
    assert result.changes["changed"]["oldmod"][1].startswith("obsolete")
