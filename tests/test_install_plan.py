"""
The planned logs the wizard's install runs (GUI-AUDIT M4 item 22c): the
order the order page shows, with the project's languages, written where
start_install reads them - the step the command line makes with --plan-order.
"""
import json
import os
import re

import pytest

from iemod_fetch import api
from iemod_fetch.errors import ConfigError
from test_selection_plan import CHOSEN, KRION, MOCK, chosen_of


def write(folder, chosen=CHOSEN, game="EET"):
    return api.write_install_plan(game, chosen, folder=str(folder),
                                  rules=[os.path.join(MOCK, "rules")],
                                  target=os.path.join(MOCK, "Mods"),
                                  data_dir=str(folder / "no-cache"), order_catalogue=KRION)


def components(path):
    """(tp2 file, component) of each line of a planned log, in order."""
    with open(path, encoding="utf-8") as fh:
        found = (re.match(r"~([^~]+)~\s+#\d+\s+#(\d+)", line) for line in fh)
        return [(m[1].replace("\\", "/").rsplit("/", 1)[-1].lower(), int(m[2]))
                for m in found if m]


def test_an_eet_build_is_written_as_its_two_logs_in_the_planned_order(tmp_path):
    shown = api.selection_plan("EET", CHOSEN, folder=str(tmp_path),
                               rules=[os.path.join(MOCK, "rules")],
                               target=os.path.join(MOCK, "Mods"),
                               data_dir=str(tmp_path / "no-cache"), order_catalogue=KRION)
    result = write(tmp_path)
    plan_dir = tmp_path / api.INSTALL_PLAN_DIR
    assert result["plan_dir"] == str(plan_dir)
    assert sorted(os.path.basename(p) for p in result["logs"]) == ["WeiDU-BGEE.log",
                                                                   "WeiDU.log"]
    # what the order page shows is what runs, line for line
    for phase, log in zip(shown["phases"], ("WeiDU-BGEE.log", "WeiDU.log"), strict=True):
        planned = [(tp2.rsplit("/", 1)[-1].lower(), number) for unit in phase["units"]
                   for tp2, number, _label in unit["components"]]
        assert components(plan_dir / log) == planned


def test_what_the_order_breaks_comes_with_the_plan(tmp_path):
    """Review of #87: the install page shows what the plan breaks before it
    runs - the same order rules selection_plan reports."""
    assert write(tmp_path)["violations"] == [] and write(tmp_path)["cycles"] == []
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "order.json").write_text(json.dumps({"rules": [
        {"rule": "ub(-):ascension(-)", "direction": "before", "severity": "warning"}]}))
    kwargs = {"folder": str(tmp_path), "rules": [str(rules)],
              "target": os.path.join(MOCK, "Mods"), "data_dir": str(tmp_path / "no-cache"),
              "order_catalogue": KRION}
    phases = [p["units"] for p in api.selection_plan("EET", CHOSEN, **kwargs)["phases"]]
    ub = next(u for u in phases[1] if u["name"].lower() == "ub")
    phases[1].remove(ub)
    phases[1].append(ub)                                    # ub after ascension
    api.save_install_order(str(tmp_path), phases)
    shown = api.selection_plan("EET", CHOSEN, **kwargs)
    written = api.write_install_plan("EET", CHOSEN, **kwargs)
    assert written["violations"] and written["violations"] == shown["violations"]


def test_a_new_plan_replaces_the_last_ones_logs(tmp_path):
    write(tmp_path)
    bg2_only = chosen_of(os.path.join(MOCK, "WeiDU.log"))
    result = write(tmp_path, bg2_only)
    assert [os.path.basename(p) for p in result["logs"]] == ["WeiDU.log"]
    assert not (tmp_path / api.INSTALL_PLAN_DIR / "WeiDU-BGEE.log").exists()


def test_nothing_planned_is_said(tmp_path):
    with pytest.raises(ConfigError, match="no install order could be planned"):
        api.write_install_plan("EET", CHOSEN, folder=str(tmp_path),
                               target=os.path.join(MOCK, "Mods"),
                               data_dir=str(tmp_path / "no-cache"))


@pytest.mark.parametrize("game,expected", [
    ("EET", {"BGEE": "/g/bgee", "EET": "/g/bg2ee"}), ("BGEE", {"BGEE": "/g/bgee"}),
    ("BG2EE", {"BG2EE": "/g/bg2ee"})])
def test_the_projects_games_as_the_install_takes_them(tmp_path, game, expected):
    api.save_project(str(tmp_path), game, "/g/bgee", "/g/bg2ee")
    assert api.install_games(str(tmp_path)) == expected
