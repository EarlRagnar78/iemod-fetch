"""
A mod's kind, as each source says it (GUI-AUDIT M5 item 26, ADR-0041).

lcc-docs' French labels and BWS-NG's codes are one taxonomy spelled two ways:
both become the same kinds, each source's kept apart, and two sources that
classify a mod with no kind in common are shown disagreeing, never settled.
krion64's install category and tags ride beside, never mapped into a kind.
"""
import json
import os

import pytest

from iemod_fetch import api
from iemod_fetch.available import available_mods, mods_document
from iemod_fetch.catalogues import CatalogueSet, SupplementaryCatalogue
from iemod_fetch.kinds import BWS_NG, KINDS, LCC_DOCS, disagree, kinds
from iemod_fetch.moddb import ModDatabase, ModRecord

SCHEMA = os.path.join(os.path.dirname(__file__), os.pardir, "schemas",
                      "mods-v1.schema.json")

LCC = CatalogueSet([SupplementaryCatalogue.from_entries([
    {"tp2": "ascension", "name": "Ascension", "games": ["BG2EE"],
     "categories": ["Quête", "Gameplay"], "urls": ["https://example.org/a.zip"]},
    {"tp2": "bg2fixpack", "name": "BG2 Fixpack", "games": ["BG2EE"],
     "categories": ["Patch non officiel"], "urls": ["https://example.org/f.zip"]},
    {"tp2": "newthing", "name": "New Thing", "games": ["BG2EE"],
     "categories": ["Catégorie nouvelle"], "urls": ["https://example.org/n.zip"]},
], name="lcc-docs")])

BWS = ModDatabase(records={
    "ascension": ModRecord(key="ascension", name="Ascension", categories=["quest"]),
    "bg2fixpack": ModRecord(key="bg2fixpack", name="BG2 Fixpack", categories=["kit"]),
}, origin="BWS-NG")

KRION = ModDatabase(records={
    "ascension": ModRecord(key="ascension", name="Ascension", version="2.0",
                           install_category="QUEST MODS BG2", tags=["story", "tob"]),
}, origin="krion64")


def by_key():
    return {m.key: m for m in available_mods(None, LCC, BWS, versions=[KRION])}


def test_every_label_both_sources_use_maps_onto_a_kind():
    assert set(LCC_DOCS.values()) <= set(KINDS)
    assert set(BWS_NG.values()) <= set(KINDS)
    assert len(set(LCC_DOCS.values())) == len(LCC_DOCS)   # one label, one kind
    assert len(set(BWS_NG.values())) == len(BWS_NG)


def test_labels_become_kinds_in_order_and_an_unknown_one_is_kept():
    assert kinds(["Gameplay", "Quête"], LCC_DOCS) == ("quest", "gameplay")
    assert kinds(["npc1d", "ui", "ui"], BWS_NG) == ("interface", "one-day NPC")
    assert kinds(["Nouveau", "Kit"], LCC_DOCS) == ("kit", "Nouveau")


def test_a_disagreement_needs_two_sources_that_both_classify():
    assert disagree(["quest"], ["kit"])
    assert not disagree(["quest", "gameplay"], ["quest"])
    assert not disagree([], ["kit"])
    # a label no table knows is not a kind: it cannot disagree (review of #65)
    assert not disagree(["Nouveau"], ["kit"])


def test_a_label_is_looked_up_ignoring_case_and_composition():
    decomposed = "Que\u0302te"                      # Quête, the accent apart
    assert kinds([decomposed, "GAMEPLAY"], LCC_DOCS) == ("quest", "gameplay")
    assert kinds(["Quest", "NPC1D"], BWS_NG) == ("quest", "one-day NPC")


def test_each_source_says_what_the_mod_is():
    ascension = by_key()["ascension"]
    assert ascension.kinds_by_source == {"lcc-docs": ("quest", "gameplay"),
                                         "BWS-NG": ("quest",)}
    assert ascension.kinds == ("quest", "gameplay")
    assert not ascension.kind_disagreement
    assert ascension.install_category == "QUEST MODS BG2"   # beside, not a kind
    assert ascension.tags == ("story", "tob")


def test_two_sources_with_no_kind_in_common_are_shown_disagreeing():
    fixpack = by_key()["bg2fixpack"]
    assert fixpack.kind_disagreement
    assert fixpack.kinds == ("kit", "unofficial patch")   # both kept, none chosen


def test_a_category_no_table_knows_is_shown_as_it_is():
    assert by_key()["newthing"].kinds == ("Catégorie nouvelle",)


def test_the_document_carries_the_kinds_and_the_schema_accepts_it():
    jsonschema = pytest.importorskip("jsonschema")
    doc = json.loads(mods_document(available_mods(None, LCC, BWS, versions=[KRION])))
    entry = {m["key"]: m for m in doc["mods"]}["bg2fixpack"]
    assert entry["kinds_by_source"] == {"lcc-docs": ["unofficial patch"],
                                        "BWS-NG": ["kit"]}
    assert entry["kind_disagreement"] is True
    with open(SCHEMA, encoding="utf-8") as fh:
        jsonschema.validate(doc, json.load(fh))


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_the_player_reads_each_source_by_its_name_on_the_real_path(tmp_path):
    """Review of #65: from the data cache's own layout, lcc-docs' catalogue
    was "mods.json" and BWS-NG's folder "bws-ng" - not what the player reads."""
    write(tmp_path / "lcc-docs" / "db" / "mods.json", [
        {"tp2": "turnabout", "name": "Turnabout", "categories": ["Quête"],
         "games": ["BG2EE"], "urls": []}])
    write(tmp_path / "bws-ng" / "data" / "mods" / "turnabout.json",
          {"name": "Turnabout", "categories": ["gameplay"]})
    write(tmp_path / "krion64" / "data" / "mods" / "turnabout.json",
          {"t": "turnabout", "v": "v3", "ord": 1, "c": "QUEST MODS BG2", "tags": ["tob"]})
    write(tmp_path / "krion64" / "data" / "version_cache.json", {})

    mod = {m.key: m for m in api.list_mods(
        catalogues=[str(tmp_path / "lcc-docs" / "db" / "mods.json")],
        mod_db=str(tmp_path / "bws-ng" / "data" / "mods"),
        releases=str(tmp_path / "krion64" / "data" / "version_cache.json"))}["turnabout"]

    assert mod.as_dict()["kinds_by_source"] == {"lcc-docs": ["quest"], "BWS-NG": ["gameplay"]}
    assert mod.kind_disagreement
    assert (mod.install_category, mod.tags) == ("QUEST MODS BG2", ("tob",))


def test_two_catalogues_of_one_file_name_stay_two_sources(tmp_path):
    for folder, label in (("a", "Kit"), ("b", "Quête")):
        write(tmp_path / folder / "mods.json", [
            {"tp2": "m", "name": "M", "categories": [label], "urls": []}])
    mods = available_mods(None, CatalogueSet.load(
        [str(tmp_path / "a" / "mods.json"), str(tmp_path / "b" / "mods.json")]))
    assert mods[0].kinds_by_source == {"a": ("kit",), "b": ("quest",)}
    assert mods[0].kind_disagreement
