"""
Preferred installation language, with fallback (ADR-0024).

Modelled on BWS-NG, the community tool that does this best: an ordered list of
languages, the first one a mod offers wins. A mod's WeiDU `#lang` is the
POSITION of its LANGUAGE declaration in the tp2, so the tp2 is read, never
guessed. The load-bearing claims:

* the index is the declaration's position, duplicates and all;
* language names are matched through an alias table ("italiano", "it_IT",
  "Italian" are one language) - without BWS-NG's "dutch" -> German slip;
* a mod offering none of the preferred languages keeps the language its log
  had, and is reported; a mod whose tp2 cannot be read is reported, not guessed.
"""
import os

import pytest

from iemod_fetch.errors import ConfigError
from iemod_fetch.languages import (apply_language_preference, canonical,
                                   choose_language, parse_preferences)
from iemod_fetch.ordering import EET_LOG, OrderIndex, plan_order
from iemod_fetch.tp2 import parse_tp2

HERE = os.path.dirname(__file__)
KRION = os.path.join(HERE, "data", "krion")
HEADER = "// Log of Currently Installed WeiDU Mods\n"


@pytest.mark.parametrize("text,code", [
    ("italian", "it_IT"), ("Italiano", "it_IT"), ("it_IT", "it_IT"), ("it", "it_IT"),
    ("english", "en_US"), ("American English", "en_US"), ("en_GB", "en_US"),
    ("francais", "fr_FR"), ("Français", "fr_FR"), ("german", "de_DE"),
    ("Deutsch", "de_DE"), ("dutch", "nl_NL"), ("castellano", "es_ES"),
    ("Polski", "pl_PL"), ("russian", "ru_RU"), ("schinese", "zh_CN"),
    ("mod/tra/italian", "it_IT"), (r"mod\lang\english", "en_US"),
    ("klingon", None), ("", None),
])
def test_language_names_resolve_through_the_alias_table(text, code):
    assert canonical(text) == code


def test_preferences_must_name_known_languages():
    assert parse_preferences("it_IT, english") == ["it_IT", "en_US"]
    with pytest.raises(ConfigError, match="klingon"):
        parse_preferences("klingon,en_US")


TP2 = """
BACKUP ~mod/backup~ AUTHOR ~x~
LANGUAGE ~English~ ~english~ ~mod/tra/english/setup.tra~
LANGUAGE ~Francais~ ~french~ ~mod/tra/french/setup.tra~
LANGUAGE ~English (alternate)~ ~english~ ~mod/tra/english2/setup.tra~
LANGUAGE ~Italiano (traduzione di qualcuno)~ ~italian~ ~mod/tra/italian/setup.tra~
BEGIN ~Component~
"""


def test_the_index_is_the_declaration_position_duplicates_included():
    decls = parse_tp2(TP2).language_decls
    assert [d[1] for d in decls] == ["english", "french", "english", "italian"]


def test_the_first_preferred_language_the_mod_offers_wins():
    decls = parse_tp2(TP2).language_decls
    assert choose_language(decls, ["it_IT", "en_US"]) == (3, "it_IT")
    assert choose_language(decls, ["de_DE", "en_US"]) == (0, "en_US")
    assert choose_language(decls, ["de_DE"]) is None


# ----------------------------------------------------------- on a real plan
def write_mod(mods, folder, tp2, languages):
    path = mods / folder
    path.mkdir(parents=True)
    decls = "\n".join(f"LANGUAGE ~{name}~ ~{code}~ ~{folder}/tra/{code}/setup.tra~"
                      for name, code in languages)
    (path / tp2).write_text(f"BACKUP ~{folder}/backup~\nAUTHOR ~x~\n{decls}\n"
                            f"BEGIN ~c~\n", encoding="utf-8")


@pytest.fixture
def plan_and_mods(tmp_path):
    mods = tmp_path / "Mods"
    write_mod(mods, "alpha", "setup-alpha.tp2", [("English", "english"),
                                                  ("Italiano", "italian")])
    write_mod(mods, "beta", "setup-beta.tp2", [("English", "english")])
    write_mod(mods, "gamma", "setup-gamma.tp2", [("Francais", "french"),
                                                  ("Deutsch", "german")])
    log = tmp_path / "WeiDU.log"
    log.write_text(HEADER + "\n".join([
        r"~alpha\setup-alpha.tp2~ #0 #0 // a",
        r"~alpha\setup-alpha.tp2~ #0 #1 // a2",
        r"~beta\setup-beta.tp2~ #0 #0 // b",
        r"~gamma\setup-gamma.tp2~ #1 #0 // g",
        r"~delta\setup-delta.tp2~ #0 #0 // d",
    ]) + "\n", encoding="utf-8")
    plan = plan_order([(str(log), EET_LOG)], OrderIndex.load(KRION))
    return plan, str(mods)


def langs(plan):
    return {(u.key, comp): lang for u in plan.logs[EET_LOG]
            for _path, lang, comp, _comment in u.lines}


def test_each_mod_gets_its_preferred_language_or_the_fallback(plan_and_mods):
    plan, mods = plan_and_mods
    report = apply_language_preference(plan, mods, ["it_IT", "en_US"])
    got = langs(plan)
    assert got[("alpha", 0)] == 1 and got[("alpha", 1)] == 1      # Italian
    assert got[("beta", 0)] == 0                                   # English fallback
    assert got[("gamma", 0)] == 1                                  # kept as logged
    assert got[("delta", 0)] == 0                                  # kept: unreadable
    assert [c.mod for c in report.changed] == ["alpha"]
    assert [m for m, _offered in report.no_match] == ["gamma"]
    assert report.unread == ["delta"]


def test_the_report_says_what_it_did(plan_and_mods):
    plan, mods = plan_and_mods
    text = apply_language_preference(plan, mods, ["it_IT", "en_US"]).render()
    assert "alpha" in text and "it_IT" in text
    assert "gamma" in text and "fr_FR" in text          # what it offers instead
    assert "delta" in text


# ----------------------------------------------------------------- the CLI
def test_cli_rewrites_the_plan_and_tells_the_installer(tmp_path, plan_and_mods):
    import io

    from iemod_fetch import cli
    _plan, mods = plan_and_mods
    out = tmp_path / "plan"
    stream = io.StringIO()
    code = cli.main(["--check-only", "-m", os.path.join(HERE, "data", "mod_downloads.json"),
                     "-w", f"{tmp_path / 'WeiDU.log'}:EET", "-t", mods,
                     "--order-catalogue", KRION, "--plan-order", str(out),
                     "--language-preference", "italian,english", "--emit-installer"],
                    stream=stream)
    assert code == 0, stream.getvalue()
    planned = (out / "WeiDU.log").read_text()
    assert r"~alpha\setup-alpha.tp2~ #1 #0" in planned
    assert "LANGUAGE PREFERENCE" in stream.getvalue()
    script = next(p for p in out.iterdir() if p.suffix == ".sh").read_text()
    assert 'LANGUAGE="${LANGUAGE:-it_IT}"' in script     # the game's language too
