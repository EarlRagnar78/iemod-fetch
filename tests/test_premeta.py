"""
The author's own install order before download (ADR-0037): Project Infinity's
metadata ini fetched from the mod's repository, and its Sorting Order file.

The network is a fake client: what it is asked for, and what it answers, is
the test. The end-to-end tests plan the EET mock with nothing staged, so only
the fetched ini or the sorting order can move a mod the catalogue does not
place.
"""
import json
import os

import pytest

from iemod_fetch import api, premeta, sortorder
from iemod_fetch.errors import ConfigError, HttpStatusError, NetworkError

HERE = os.path.dirname(__file__)
MOCK = os.path.join(HERE, "data", "eetmock")
INI = "[Metadata]\nName = Unfinished Business\nBefore = ascension\nAfter = EET\n"


class FakeClient:
    """raw.githubusercontent.com and the contents API, from `files`
    ({"owner/repo": {"Path/In/Repo.ini": text}}); `fail` fails every request."""

    def __init__(self, files=None, fail=None):
        self.files, self.fail, self.asked = files or {}, fail, []

    def _repo_path(self, url, base):
        rest = url[len(base) + 1:]
        owner, name, *path = rest.split("/")
        return f"{owner}/{name}", path

    def read_bytes(self, url, limit=None):
        self.asked.append(url)
        if self.fail:
            raise self.fail
        repo, path = self._repo_path(url, premeta.RAW)
        where = "/".join(path[1:])                  # after HEAD
        if where in self.files.get(repo, {}):
            return self.files[repo][where].encode()
        raise HttpStatusError(url, 404, "Not Found")

    def get_json(self, url):
        self.asked.append(url)
        if self.fail:
            raise self.fail
        repo, path = self._repo_path(url, premeta.API)
        folder = "/".join(path[1:]).strip("/")         # after "contents"
        files = self.files.get(repo, {})
        if folder and not any(p.startswith(folder + "/") for p in files):
            raise HttpStatusError(url, 404, "Not Found")
        out = {}
        for p in files:
            if folder and not p.startswith(folder + "/"):
                continue
            rest = p[len(folder) + 1:] if folder else p
            head, _, tail = rest.partition("/")
            out[head] = "dir" if tail else "file"
        return [{"name": name, "type": kind} for name, kind in out.items()]


UB = premeta.Wanted("ub", "setup-ub.tp2", "Pocket-Plane-Group/ub")
REPO = "pocket-plane-group/ub"


# ------------------------------------------------------------- fetching
def test_the_ini_is_looked_for_beside_the_tp2_named_after_it():
    assert premeta.candidates("ub", "setup-ub.tp2") == [
        "ub/setup-ub.ini", "setup-ub.ini", "ub/ub.ini", "ub.ini"]
    # GitHub is case-sensitive; Region of Terror ships RoT/rot.ini
    assert "RoT/rot.ini" in premeta.candidates("RoT", "setup-RoT.tp2")
    # a tp2 below its mod folder: its ini is beside it, not in the mod folder
    assert premeta.candidates("eet", "eet/EET_end/EET_end.tp2")[0] == "eet/EET_end/EET_end.ini"


def test_a_found_ini_is_cached_and_gives_the_authors_order(tmp_path):
    client = FakeClient({REPO: {"ub/ub.ini": INI}})
    cache = premeta.MetadataCache(str(tmp_path))
    assert premeta.fetch(client, cache, [UB], now=100.0) == (1, 0, [])
    cache.save()
    meta = premeta.MetadataCache(str(tmp_path)).get(UB)
    assert meta.before == ["ascension"] and meta.after == ["eet"]
    # an ini from another repository than the catalogue names today does not count
    moved = premeta.Wanted("ub", "setup-ub.tp2", "someone/else")
    assert premeta.MetadataCache(str(tmp_path)).get(moved) is None


@pytest.mark.parametrize("folder, tp2, path", [
    # Deities of Faerun ships Deitiesoffaerun.ini beside DeitiesOffaerun.tp2
    ("DeitiesOfFaerun", "DeitiesOffaerun.tp2", "DeitiesOfFaerun/Deitiesoffaerun.ini"),
    # a WeiDU log may spell the whole path in capitals
    ("ASCENSION", "ASCENSION.TP2", "ascension/Ascension.ini"),
    ("might_and_guile", "setup-might_and_guile.tp2", "might_and_guile/Might_and_Guile.ini"),
])
def test_the_ini_is_found_whatever_its_case(tmp_path, folder, tp2, path):
    client = FakeClient({"o/r": {path: INI, f"{path.split('/')[0]}/x.tp2": ""}})
    cache = premeta.MetadataCache(str(tmp_path))
    wanted = premeta.Wanted(folder, tp2, "o/r")
    assert premeta.fetch(client, cache, [wanted], now=1.0) == (1, 0, [])
    assert cache.entries[premeta.cache_key(wanted)]["path"] == path


def test_a_missing_ini_is_remembered_and_not_asked_for_again_for_a_week(tmp_path):
    client = FakeClient({REPO: {"ub/setup-ub.tp2": ""}})
    cache = premeta.MetadataCache(str(tmp_path))
    assert premeta.fetch(client, cache, [UB], now=100.0) == (0, 1, [])
    asked = len(client.asked)
    assert asked and cache.get(UB) is None
    premeta.fetch(client, cache, [UB], now=100.0 + 86400)
    assert len(client.asked) == asked
    premeta.fetch(client, cache, [UB], now=100.0 + 8 * 86400)
    assert len(client.asked) == 2 * asked


def test_another_repository_is_asked_again(tmp_path):
    client = FakeClient()
    cache = premeta.MetadataCache(str(tmp_path))
    premeta.fetch(client, cache, [UB], now=100.0)
    moved = premeta.Wanted("ub", "setup-ub.tp2", "Spellhold-Studios/ub")
    premeta.fetch(client, cache, [moved], now=101.0)
    assert any("spellhold-studios/ub" in url for url in client.asked)


def test_a_network_error_keeps_the_last_good_entry(tmp_path):
    good = FakeClient({REPO: {"ub/setup-ub.ini": INI}})
    cache = premeta.MetadataCache(str(tmp_path))
    premeta.fetch(good, cache, [UB], now=100.0)
    down = FakeClient(fail=NetworkError("offline"))
    found, missing, problems = premeta.fetch(down, cache, [UB], now=100.0 + 8 * 86400)
    assert (found, missing) == (0, 0) and problems == ["ub: offline"]
    assert cache.get(UB).before == ["ascension"]


def test_offline_costs_one_request_then_backs_off_for_an_hour(tmp_path):
    # The wizard checks after every change: offline must not ask for every mod
    # every time.
    mods = [premeta.Wanted(f"m{n}", f"m{n}.tp2", f"o/m{n}") for n in range(50)]
    down = FakeClient(fail=NetworkError("offline"))
    cache = premeta.MetadataCache(str(tmp_path))
    found, missing, problems = premeta.fetch(down, cache, mods, now=100.0)
    assert len(down.asked) == 1 and len(problems) == 1 and (found, missing) == (0, 0)
    premeta.fetch(down, cache, mods, now=100.0 + 1800)
    assert len(down.asked) == 1
    premeta.fetch(down, cache, mods, now=100.0 + 3700)
    assert len(down.asked) == 2


def test_one_blocked_repository_does_not_stop_the_others(tmp_path):
    # A 451 (or 401, or a file over the cap) is that repository's: recorded as
    # checked for it alone, and the next mod is still asked.
    class Blocked(FakeClient):
        def read_bytes(self, url, limit=None):
            if "/o/blocked/" in url:
                self.asked.append(url)
                raise HttpStatusError(url, 451, "Unavailable For Legal Reasons")
            return super().read_bytes(url, limit)
    client = Blocked({REPO: {"ub/ub.ini": INI}})
    blocked = premeta.Wanted("blocked", "blocked.tp2", "o/blocked")
    cache = premeta.MetadataCache(str(tmp_path))
    found, missing, problems = premeta.fetch(client, cache, [blocked, UB], now=1.0)
    assert found == 1 and len(problems) == 1 and "451" in problems[0]
    asked = len(client.asked)
    premeta.fetch(client, cache, [blocked, UB], now=2.0)
    assert len(client.asked) == asked             # the blocked one backs off an hour
    premeta.fetch(client, cache, [blocked, UB], now=2.0 + 3700)
    assert len(client.asked) > asked              # then it is asked again; UB is not


def test_a_repositorys_error_keeps_the_ini_found_before(tmp_path):
    cache = premeta.MetadataCache(str(tmp_path))
    premeta.fetch(FakeClient({REPO: {"ub/ub.ini": INI}}), cache, [UB], now=1.0)

    class Gone(FakeClient):
        def read_bytes(self, url, limit=None):
            raise HttpStatusError(url, 451, "Unavailable For Legal Reasons")
    premeta.fetch(Gone(), cache, [UB], now=1.0 + 8 * 86400)
    assert cache.get(UB).before == ["ascension"]


@pytest.mark.parametrize("status, reason", [(401, "Bad credentials"), (403, "Forbidden"),
                                            (429, "Too Many Requests")])
def test_a_refused_credential_or_a_quota_stops_the_run(tmp_path, status, reason):
    # 401 would hit every repository; a secondary quota is a bare 403.
    down = FakeClient(fail=HttpStatusError("u", status, reason))
    mods = [premeta.Wanted(f"m{n}", f"m{n}.tp2", f"o/m{n}") for n in range(5)]
    premeta.fetch(down, premeta.MetadataCache(str(tmp_path)), mods, now=1.0)
    assert len(down.asked) == 1


def test_odd_paths_are_cleaned_before_use():
    odd = premeta.Wanted("x", "./x//sub/x.tp2", "o/x")
    assert odd.directory == "x/sub"
    assert premeta.candidates("x", "./x//sub/x.tp2")[0] == "x/sub/x.ini"


def test_each_tp2_of_a_folder_has_its_own_ini(tmp_path):
    # EET ships EET.tp2 and EET_end/EET_end.tp2 in one folder, each with an ini.
    files = {"eet/EET.ini": "[Metadata]\nAfter = eefixpack\n",
             "eet/EET_end/EET_end.ini": "[Metadata]\nAfter = stratagems\n"}
    client = FakeClient({"o/eet": files})
    eet = premeta.Wanted("eet", "eet/EET.tp2", "o/eet")
    end = premeta.Wanted("eet", "eet/EET_end/EET_end.tp2", "o/eet")
    cache = premeta.MetadataCache(str(tmp_path))
    assert premeta.fetch(client, cache, [eet, end], now=1.0) == (2, 0, [])
    assert cache.get(eet).after == ["eefixpack"] and cache.get(end).after == ["stratagems"]
    # and a log in capitals still finds the one below, by listing each level
    caps = premeta.Wanted("EET", "EET/EET_END/EET_END.TP2", "o/eet")
    fresh = premeta.MetadataCache(str(tmp_path / "other"))
    assert premeta.fetch(client, fresh, [caps], now=1.0) == (1, 0, [])
    assert fresh.entries[premeta.cache_key(caps)]["path"] == "eet/EET_end/EET_end.ini"


def test_the_planned_tp2s_are_listed_one_by_one(tmp_path):
    from iemod_fetch.weidu import parse_weidu_files
    log = tmp_path / "WeiDU.log"
    log.write_text("~eet\\EET.tp2~ #0 #0 // EET core\n"
                   "~ub\\setup-ub.tp2~ #0 #0 // UB\n"
                   "~eet\\EET_end\\EET_end.tp2~ #0 #0 // EET end\n"
                   "~ub\\setup-ub.tp2~ #0 #1 // UB 1\n")
    installed = parse_weidu_files([(str(log), "EET")])
    pairs = api._not_staged(api.Settings(target=str(tmp_path / "none")), installed)
    assert sorted(pairs) == [("eet", "eet/EET.tp2"), ("eet", "eet/EET_end/EET_end.tp2"),
                             ("ub", "ub/setup-ub.tp2")]


def test_one_tp2_spelled_two_ways_is_fetched_once(tmp_path):
    from iemod_fetch.weidu import parse_weidu_files
    first, second = tmp_path / "a.log", tmp_path / "b.log"
    first.write_text("~EET\\EET.tp2~ #0 #0 // core\n")
    second.write_text("~eet\\EET.TP2~ #0 #1 // other\n")
    installed = parse_weidu_files([(str(first), "EET"), (str(second), "EET")])
    pairs = api._not_staged(api.Settings(target=str(tmp_path / "none")), installed)
    assert len(pairs) == 1


def test_a_file_without_a_metadata_section_is_not_taken():
    client = FakeClient({REPO: {"ub/setup-ub.ini": "[Settings]\nx=1\n"}})
    cache = premeta.MetadataCache("/nonexistent-for-the-test")
    assert premeta.fetch(client, cache, [UB], now=1.0) == (0, 1, [])


def test_a_broken_cache_file_is_started_again(tmp_path):
    (tmp_path / premeta.CACHE_FILE).write_text("{ not json")
    assert premeta.MetadataCache(str(tmp_path)).entries == {}


# --------------------------------------------------------- sorting order
def test_the_sorting_order_file_reads_as_project_infinity_writes_it():
    entries = sortorder.parse("Ascension *  // all of it\n\najantisbg2 *\n"
                              "Ascension 101 102 // apart\n# a note\n")
    assert [(e.key, e.numbers) for e in entries] == [
        ("ascension", None), ("ajantisbg2", None), ("ascension", (101, 102))]


@pytest.mark.parametrize("text", ["Ascension one\n", "Ascension * 3\n"])
def test_a_line_that_is_neither_star_nor_numbers_is_refused(text):
    with pytest.raises(ConfigError, match=":1:"):
        sortorder.parse(text, source="order.txt")


def test_named_components_leave_their_mods_star_line():
    # The wiki's own example: Ascension's portraits go after Ajantis.
    entries = sortorder.parse("Ascension *\najantisbg2 *\nAscension 101 102\n")
    rules = sortorder.rules(entries, {"ascension": {0, 1, 101, 102}, "ajantisbg2": {0}})
    pairs = [((r.left.mod, sorted(r.left.components)),
              (r.right[0].mod, sorted(r.right[0].components))) for r in rules]
    assert pairs == [(("ascension", [0, 1]), ("ajantisbg2", [0])),
                     (("ajantisbg2", [0]), ("ascension", [101, 102]))]


def test_a_repeated_line_does_not_order_a_mod_before_itself():
    entries = sortorder.parse("a *\nb *\na *\na 1 2\n")
    rules = sortorder.rules(entries, {"a": {1, 2, 3}, "b": {1}})
    assert all(r.left.mod != r.right[0].mod or not (r.left.components & r.right[0].components)
               for r in rules)
    assert [(r.left.mod, sorted(r.left.components)) for r in rules][0] == ("a", [3])


def test_what_is_not_chosen_is_not_ordered():
    entries = sortorder.parse("a *\nb *\nc *\n")
    rules = sortorder.rules(entries, {"a": {1}, "c": {2}})
    assert [(r.left.mod, r.right[0].mod) for r in rules] == [("a", "c")]


# ------------------------------------------------------------ end to end
def plan(tmp_path, **extra):
    extra.setdefault("no_default_data", True)
    settings = api.Settings(
        check_only=True, quiet=True, manifest=os.path.join(HERE, "data", "mod_downloads.json"),
        weidu_log=[os.path.join(MOCK, "WeiDU.log") + ":EET"],
        target=str(tmp_path / "nothing-staged"), rules=[os.path.join(MOCK, "rules")],
        order_catalogue=os.path.join(HERE, "data", "krion"),
        plan_order=str(tmp_path / "plan"), data_dir=str(tmp_path / "data"),
        no_update_data=True, **extra)
    api.run(settings)
    lines = (tmp_path / "plan" / "WeiDU.log").read_text().splitlines()
    return [line.split("\\")[0].lstrip("~").lower() for line in lines if line.startswith("~")]


def test_without_the_ini_the_log_order_stands(tmp_path):
    order = plan(tmp_path)
    assert order.index("ascension") < order.index("ub")


def cached_ub_ini(tmp_path, repo):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / premeta.CACHE_FILE).write_text(json.dumps({"ub:ub": {
        "repo": repo, "path": "ub/ub.ini", "text": INI, "checked": 1}}))
    catalogue = tmp_path / "lcc.json"
    catalogue.write_text(json.dumps([{"tp2": "ub", "name": "UB", "games": ["EET"],
                                      "urls": ["https://github.com/Pocket-Plane-Group/ub"]}]))
    return str(catalogue)


def test_a_cached_ini_moves_a_mod_not_downloaded_yet(tmp_path):
    catalogue = cached_ub_ini(tmp_path, REPO)
    order = plan(tmp_path, catalogue=[catalogue], fetch_metadata=False,
                 no_default_data=False)
    assert order.index("ub") < order.index("ascension")


def test_an_ini_from_another_repository_is_not_used(tmp_path):
    catalogue = cached_ub_ini(tmp_path, "someone/else")
    order = plan(tmp_path, catalogue=[catalogue], no_default_data=False)
    assert order.index("ascension") < order.index("ub")


def test_no_default_data_means_no_cached_ini_either(tmp_path):
    catalogue = cached_ub_ini(tmp_path, REPO)
    order = plan(tmp_path, catalogue=[catalogue])
    assert order.index("ascension") < order.index("ub")


def test_a_staged_mods_own_ini_does_not_silence_the_players_sorting_order():
    # A mod's own ini replaces the COMMUNITY's order rules about it; the
    # player's Sorting Order is not one of them.
    from iemod_fetch.rules import Context, RuleSet, _applicable
    rule = sortorder.rules(sortorder.parse("ascension *\nub *\n"),
                           {"ascension": {0}, "ub": {0}})[0]
    kept = _applicable(RuleSet(rules=[rule]), Context(mods_with_own_ini={"ascension"}))
    assert kept == [rule]


def test_a_sorting_order_moves_what_it_names(tmp_path):
    path = tmp_path / "SortingOrder.txt"
    path.write_text("ub *\nascension *\n")
    order = plan(tmp_path, sorting_order=str(path))
    assert order.index("ub") < order.index("ascension")
