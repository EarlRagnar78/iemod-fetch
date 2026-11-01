"""
selection.json v1: the selection a UI builds, as an alternative to WeiDU.log
(ADR-0030).

A selection is one or two installs (two for EET: the pre-EET BGEE phase and
the EET game), each an ordered list of components. It says the same thing a
WeiDU.log says, so it is converted to and from one without loss, and every
planner that reads logs reads a selection through that conversion.
"""
import json
import os

import pytest

from iemod_fetch.errors import ConfigError
from iemod_fetch.selection import (SCHEMA_VERSION, parse_selection,
                                   selection_from_logs, selection_to_json)
from iemod_fetch.weidu import parse_weidu_log

DATA = os.path.join(os.path.dirname(__file__), "data")
SCHEMA = os.path.join(os.path.dirname(__file__), os.pardir, "schemas",
                      "selection-v1.schema.json")

EET = {
    "schema_version": 1,
    "installs": [
        {"game": "BGEE", "components": [
            {"tp2": "eefixpack/setup-eefixpack.tp2", "component": 0, "language": 0,
             "label": "Core Fixes"}]},
        {"game": "EET", "components": [
            {"tp2": "EET/EET.tp2", "component": 0, "language": 0},
            {"tp2": "scs/setup-scs.tp2", "component": 4000, "language": 1}]},
    ],
}


def test_a_selection_becomes_the_weidu_logs_it_describes():
    selection = parse_selection(json.dumps(EET))
    logs = selection.weidu_logs()
    assert [(log.game, log.name) for log in logs] == [
        ("BGEE", "WeiDU-BGEE.log"), ("EET", "WeiDU-EET.log")]
    eet = parse_weidu_log(logs[1].text)
    assert eet.order == ["eet", "scs"]
    scs = eet.mods["scs"].components[0]
    assert (scs.tp2_file, scs.index, scs.language) == ("setup-scs.tp2", 4000, 1)
    bgee = parse_weidu_log(logs[0].text)
    assert bgee.mods["eefixpack"].components[0].comment == "Core Fixes"


def test_a_weidu_log_round_trips_through_a_selection():
    with open(os.path.join(DATA, "WeiDU.log"), encoding="utf-8") as fh:
        original = parse_weidu_log(fh.read())
    selection = selection_from_logs([("EET", original)])
    again = parse_weidu_log(parse_selection(selection_to_json(selection))
                            .weidu_logs()[0].text)
    assert again.order == original.order
    assert ([(c.path, c.language, c.index, c.comment)
             for m in again.mods.values() for c in m.components]
            == [(c.path, c.language, c.index, c.comment)
                for m in original.mods.values() for c in m.components])


def test_the_written_json_names_its_schema_version():
    selection = parse_selection(json.dumps(EET))
    assert json.loads(selection_to_json(selection))["schema_version"] == SCHEMA_VERSION


@pytest.mark.parametrize("change,message", [
    (lambda d: d.update(schema_version=2), "schema_version"),
    (lambda d: d.update(colour="red"), "colour"),
    (lambda d: d["installs"].append({"game": "BG2EE", "components": []}), "at most two"),
    (lambda d: d["installs"][1].update(game="BG2EE"), "EET"),
    (lambda d: d["installs"][0].update(game="Zork"), "Zork"),
    (lambda d: d["installs"][1]["components"][0].update(component="0"), "component"),
    (lambda d: d["installs"][1]["components"][0].update(tp2="../x/setup-x.tp2"), "tp2"),
    (lambda d: d["installs"][1]["components"][0].update(tp2="C:/x/setup-x.tp2"), "tp2"),
    (lambda d: d["installs"][1]["components"][0].update(tp2="a~b/setup-x.tp2"), "tp2"),
    (lambda d: d["installs"][1]["components"][0].update(tp2="EET/EET.txt"), ".tp2"),
    (lambda d: d["installs"][1]["components"][0].update(label="a~b"), "label"),
    (lambda d: d["installs"].clear(), "at least one"),
])
def test_a_wrong_selection_is_refused_with_the_reason(change, message):
    data = json.loads(json.dumps(EET))
    change(data)
    with pytest.raises(ConfigError, match=message):
        parse_selection(json.dumps(data))


def test_not_json_is_refused_as_a_configuration_error():
    with pytest.raises(ConfigError, match="not valid JSON"):
        parse_selection("{")


def test_the_json_schema_accepts_what_the_parser_accepts():
    jsonschema = pytest.importorskip("jsonschema")
    with open(SCHEMA, encoding="utf-8") as fh:
        schema = json.load(fh)
    jsonschema.validate(EET, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**EET, "schema_version": 2}, schema)

