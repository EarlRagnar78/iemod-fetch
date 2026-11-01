"""
Component names, the way WeiDU prints them (M2e).

Every case below is a form found while measuring tra.py against WeiDU 251's
own `--list-components` on 103 real mods (docs/TESTING.md): the expected
strings are what WeiDU printed, not what seemed sensible.
"""
import json
import os

import pytest

from iemod_fetch import api
from iemod_fetch.tra import component_names, describe, languages, mod_folder, parse_tra


def reader(files):
    return lambda path: files.get(path)


# ------------------------------------------------------------------ .tra
def test_tra_entries_in_every_delimiter():
    text = ('@1 = ~tilde~\n@2 = "quote"\n@3 = %percent%\n'
            '@4 = ~~~~~has ~tildes~ inside~~~~~\n')
    assert parse_tra(text) == {1: "tilde", 2: "quote", 3: "percent",
                               4: "has ~tildes~ inside"}


def test_tra_female_text_and_sound_are_skipped():
    assert parse_tra("@1 = ~he~ ~she~ [SND01]\n@2 = ~next~") == {1: "he", 2: "next"}


def test_tra_comments_are_not_entries():
    text = "// @1 = ~no~\n/* @2 = ~no~ */\n@3 = ~yes // not a comment~\n"
    assert parse_tra(text) == {3: "yes // not a comment"}


def test_a_later_tra_entry_wins():
    assert parse_tra("@1 = ~old~\n@1 = ~new~") == {1: "new"}


def test_a_bare_word_is_a_tra_value():
    """thepicturestandard: `@30=BG1NPC`; WeiDU prints BG1NPC."""
    assert parse_tra("@30=BG1NPC\n@3000=~Vanilla~") == {30: "BG1NPC", 3000: "Vanilla"}


# ------------------------------------------------------------- LANGUAGE
def test_language_names_and_directories_may_be_bare_words():
    """SCS writes `LANGUAGE ENGLISH english ~...~`: skipping it would shift
    every later language index."""
    tp2 = ("LANGUAGE ENGLISH english ~scs/tra/english/setup.tra~\n"
           "LANGUAGE ~Italiano~ ~italian~ ~scs/tra/italian/setup.tra~\n")
    assert [(lang.name, lang.directory, lang.tra_files) for lang in languages(tp2)] == [
        ("ENGLISH", "english", ["scs/tra/english/setup.tra"]),
        ("Italiano", "italian", ["scs/tra/italian/setup.tra"])]


def test_mod_folder_is_the_backup_directory_not_the_tp2_directory():
    """LCA keeps EE/LCA.tp2 with BACKUP ~LCA/backup~: WeiDU 251 resolves
    %MOD_FOLDER% to LCA."""
    assert mod_folder("BACKUP ~LCA/backup~\n") == "LCA"
    assert mod_folder("BACKUP ~thepicturestandard\\backup~\n") == "thepicturestandard"
    assert mod_folder("AUTHOR ~x~\n") == ""


# ---------------------------------------------------------------- names
TP2 = r"""
BACKUP ~mymod/backup~
VERSION ~v3~
LANGUAGE ~English~ ~english~ ~%MOD_FOLDER%/tra/%LANGUAGE%/setup.tra~
                             ~mymod/tra/%LANGUAGE%/%WEIDU_OS%.tra~
LANGUAGE ~Italiano~ ~italian~ ~mymod/tra/italian/setup.tra~

BEGIN @1
BEGIN @2 DESIGNATED 10
SUBCOMPONENT @3
BEGIN @4
SUBCOMPONENT @3
BEGIN @99
"""
FILES = {
    "mymod/tra/english/setup.tra": "@1 = ~First~\n@2 = ~Fast~\n@3 = ~Speed~\n@4 = ~Two\nlines~",
    "mymod/tra/english/win32.tra": "@2 = ~Fast on Windows~",
    "mymod/tra/english/unix.tra": "@2 = ~Fast on Unix~",
    "mymod/tra/italian/setup.tra": "@1 = ~Primo~",
}


def test_names_are_printed_as_weidu_prints_them():
    names = component_names(TP2, 0, reader(FILES))
    assert [(c.number, c.name) for c in names] == [
        (0, "First: v3"),
        (10, "Speed -> Fast on Windows: v3"),       # the later .tra file wins
        (11, "Speed -> Two lines: v3"),             # a line break is a space
        (12, "UNDEFINED STRING:   @99: v3"),        # WeiDU's own words
    ]
    assert [c.resolved for c in names] == [True, True, True, False]


def test_weidu_os_selects_the_platform_tra():
    names = component_names(TP2, 0, reader(FILES), weidu_os="unix")
    assert names[1].title == "Fast on Unix"
    names = component_names(TP2, 0, reader(FILES), weidu_os="osx")
    assert names[1].title == "Fast"           # no osx.tra: the shared one stands


def test_another_language_reads_its_own_tra():
    names = component_names(TP2, 1, reader(FILES))
    assert names[0].name == "Primo: v3"
    assert not names[1].resolved


def test_a_missing_tra_file_leaves_references_unresolved():
    names = component_names(TP2, 0, reader({}))
    assert not any(c.resolved for c in names[:2])


def test_describe_picks_the_first_preferred_language_offered():
    described = describe(TP2, reader(FILES), ["fr_FR", "it_IT"])
    assert described["language"] == 1
    assert described["languages"][1] == {"index": 1, "name": "Italiano",
                                         "directory": "italian"}
    assert described["components"][0] == {"number": 0, "name": "Primo: v3",
                                          "title": "Primo", "subgroup": None,
                                          "groups": [], "labels": [], "forced": False,
                                          "deprecated": False, "resolved": True}


def test_describe_defaults_to_the_first_language():
    assert describe(TP2, reader(FILES))["language"] == 0


# ------------------------------------------------------- the api, on disk
def stage(root):
    mod = os.path.join(root, "MyMod")
    os.makedirs(os.path.join(mod, "TRA", "English"))
    with open(os.path.join(mod, "MyMod.tp2"), "w", encoding="utf-8") as fh:
        fh.write("BACKUP ~MyMod/backup~\nVERSION ~1.0~\n"
                 "LANGUAGE ~English~ ~english~ ~mymod/tra/english/setup.tra~\n"
                 "BEGIN @1\nBEGIN @2\n")
    with open(os.path.join(mod, "TRA", "English", "setup.tra"), "wb") as fh:
        fh.write("@1 = ~Café~\n@2 = ~../escape~".encode("cp1252"))


def test_describe_mods_reads_staged_mods_case_insensitively(tmp_path):
    """Paths in a tp2 are matched as on Windows, and a pre-EE .tra in
    Windows-1252 still decodes."""
    stage(str(tmp_path))
    (mod,) = api.describe_mods(str(tmp_path))
    assert mod["tp2"] == "MyMod/MyMod.tp2"
    assert [c["name"] for c in mod["components"]] == ["Café: 1.0", "../escape: 1.0"]


def test_describe_mods_never_reads_outside_the_target(tmp_path):
    secret = tmp_path / "secret.tra"
    secret.write_text("@1 = ~leaked~")
    target = tmp_path / "Mods"
    (target / "x").mkdir(parents=True)
    (target / "x" / "x.tp2").write_text(
        "LANGUAGE ~English~ ~english~ ~../secret.tra~\nBEGIN @1\n")
    (mod,) = api.describe_mods(str(target))
    assert mod["components"][0]["resolved"] is False


def test_describe_mods_writes_the_versioned_document(tmp_path):
    stage(str(tmp_path / "Mods"))
    out = tmp_path / "components.json"
    outcome = api.run(api.Settings(describe_mods=str(out), target=str(tmp_path / "Mods")))
    assert outcome.exit_code == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    assert document["mods"][0]["components"][0]["number"] == 0


def test_the_document_matches_its_schema(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    stage(str(tmp_path / "Mods"))
    out = tmp_path / "components.json"
    api.run(api.Settings(describe_mods=str(out), target=str(tmp_path / "Mods")))
    schema_path = os.path.join(os.path.dirname(__file__), os.pardir, "schemas",
                               "components-v1.schema.json")
    with open(schema_path, encoding="utf-8") as fh:
        jsonschema.validate(json.loads(out.read_text(encoding="utf-8")), json.load(fh))


# ---------------------------------------------- the rest of WeiDU's view
# Measured against WeiDU 251's --list-components-json on the same 109 tp2s:
# which components are listed, and each one's title, subgroup, groups, labels
# and forced flag, 1,499 of 1,499 (docs/TESTING.md).
FLAGS = r"""
VERSION ~v2~
LANGUAGE ~English~ ~english~ ~m/tra/english/setup.tra~

BEGIN @1 DESIGNATED 1                      // DlcMerger's form
LABEL ~A7-DLCMERGER-MERGE_SOD~
SUBCOMPONENT @2
GROUP @3
REQUIRE_PREDICATE GAME_IS ~bgee~ @9
COPY ~a~ ~b~
  SAY 0 ~LABEL ~NOT-A-LABEL~ inside text~

BEGIN @4 DESIGNATED 2
FORCED_SUBCOMPONENT @2
LABEL ~ONE~ LABEL ~TWO~
GROUP @3 GROUP ~Tweaks~

BEGIN @5 DESIGNATED 145                    // Might and Guile's form
DEPRECATED @6
"""
FLAG_TRA = {"m/tra/english/setup.tra":
            "@1=~Merge SoD~ @2=~Merge DLC\ninto game~ @3=~Core~ @4=~Custom~ @5=~Old~ @6=~gone~"}


def flagged():
    return {c.number: c for c in component_names(FLAGS, 0, reader(FLAG_TRA))}


def test_labels_and_groups_are_read_from_the_flags_only():
    one = flagged()[1]
    assert one.labels == ["A7-DLCMERGER-MERGE_SOD"]     # not the text in SAY
    assert one.groups == ["Core"]


def test_a_component_can_have_several_labels_and_groups():
    two = flagged()[2]
    assert two.labels == ["ONE", "TWO"] and two.groups == ["Core", "Tweaks"]


def test_forced_subcomponent_is_flagged():
    assert (flagged()[1].forced, flagged()[2].forced) == (False, True)
    assert flagged()[1].subgroup == flagged()[2].subgroup


def test_a_deprecated_component_is_marked_as_weidu_hides_it():
    assert flagged()[145].deprecated and not flagged()[1].deprecated


def test_line_breaks_are_a_space_in_the_name_and_dropped_in_the_title():
    """--list-components prints 'Merge DLC into game -> ...'; its JSON gives
    'Merge DLCinto game' (Gavin, cdtweaks and bp-bgt-worldmap measured)."""
    one = flagged()[1]
    assert one.name == "Merge DLC into game -> Merge SoD: v2"
    assert one.subgroup == "Merge DLCinto game"


# ------------------------------------------------- from the review of PR #24
def test_a_percent_delimited_name_is_a_plain_string_as_weidu_reads_it():
    """WeiDU 251 lists `BEGIN %Literal Name%` as 'Literal Name' and `BEGIN %x%`
    as 'x': % is a string delimiter there, not a variable. The component used to
    vanish, shifting every number after it."""
    tp2 = "VERSION ~v1~\nBEGIN %Literal Name%\nBEGIN ~Second~\nBEGIN %x%\n"
    assert [(c.number, c.name) for c in component_names(tp2, 0, reader({}))] == [
        (0, "Literal Name: v1"), (1, "Second: v1"), (2, "x: v1")]


def test_windows_1252_punctuation_stays_punctuation(tmp_path):
    mod = tmp_path / "m"
    mod.mkdir()
    (mod / "m.tp2").write_text("LANGUAGE ~English~ ~english~ ~m/setup.tra~\nBEGIN @1\n")
    (mod / "setup.tra").write_bytes(b"@1 = ~Imoen\x92s Romance~")
    (described,) = api.describe_mods(str(tmp_path))
    assert described["components"][0]["title"] == "Imoen\u2019s Romance"


def test_a_symbolic_link_is_not_followed(tmp_path):
    outside = tmp_path / "outside.tra"
    outside.write_text("@1 = ~leaked~")
    mods = tmp_path / "Mods"
    (mods / "m").mkdir(parents=True)
    (mods / "m" / "m.tp2").write_text("LANGUAGE ~English~ ~english~ ~m/setup.tra~\nBEGIN @1\n")
    try:
        os.symlink(outside, mods / "m" / "setup.tra")
    except (OSError, NotImplementedError):
        pytest.skip("this platform cannot create a symbolic link here")
    (described,) = api.describe_mods(str(mods))
    assert described["components"][0]["resolved"] is False


def test_an_unreadable_file_is_unresolved_not_an_abort(tmp_path):
    mod = tmp_path / "m"
    mod.mkdir()
    (mod / "m.tp2").write_text("LANGUAGE ~English~ ~english~ ~m/setup.tra~\nBEGIN @1\n")
    (mod / "setup.tra").mkdir()          # where a file should be: reading it fails
    (described,) = api.describe_mods(str(tmp_path))
    assert described["components"][0]["resolved"] is False


def test_flags_after_require_file_and_a_multiline_predicate_are_read():
    tp2 = ("BEGIN ~A~\nREQUIRE_FILE ~x.2da~ ~need~\nLABEL ~A-L~\nCOPY ~a~ ~b~\n"
           "BEGIN ~B~\nREQUIRE_PREDICATE GAME_IS ~bgee~\n  OR MOD_IS_INSTALLED ~x.tp2~ 0 ~n~\n"
           "LABEL ~B-L~\nCOPY ~a~ ~b~\n  LABEL ~NOT-A-LABEL~\n")
    found = {c.number: c.labels for c in component_names(tp2, 0, reader({}))}
    assert found == {0: ["A-L"], 1: ["B-L"]}


def test_text_outside_the_mod_folder_is_never_read(tmp_path):
    (tmp_path / "secret.tra").write_text("@1=~x~")
    root = tmp_path / "mod"
    root.mkdir()
    assert api._text_under(str(root), "../secret.tra") is None
    assert api._text_under(str(root), "C:/secret.tra") is None


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no FIFOs here")
def test_a_fifo_is_not_opened(tmp_path):
    os.mkfifo(tmp_path / "x.tra")
    assert api._text_under(str(tmp_path), "x.tra") is None


# --------------------------------------- legacy code pages (GUI-AUDIT item 44)
@pytest.mark.parametrize("path,charset", [
    # WeiDU 251's README, HANDLE_CHARSETS' infer_charsets matrix
    ("m/schinese/a.tra", "cp936"), ("m/zh_CN/a.tra", "cp936"), ("m/tchinese/a.tra", "cp950"),
    ("m/czech/a.tra", "cp1250"), ("m/cs_CZ/a.tra", "cp1250"), ("m/japanese/a.tra", "cp932"),
    ("m/korean/a.tra", "cp949"), ("m/Polski/a.tra", "cp1250"), ("m/pl_PL/a.tra", "cp1250"),
    ("m\\RUSSIAN\\a.tra", "cp1251"), ("m/ru_RU/a.tra", "cp1251"),
    ("m/english/a.tra", "cp1252"), ("m/castilian/a.tra", "cp1252"), ("russian.tra", "cp1252"),
    # the nearest language folder decides, not a mod folder's name (review of #58)
    ("prussian_guard/english/a.tra", "cp1252"), ("polished_items/english/a.tra", "cp1252"),
    ("english_x/russian/a.tra", "cp1251"), ("m/tra/russian/a.tra", "cp1251"),
    ("m/russian/tra/a.tra", "cp1251")])
def test_the_code_page_is_the_language_folders(path, charset):
    from iemod_fetch.weidu_lex import legacy_charset
    assert legacy_charset(path) == charset


def test_a_legacy_russian_tra_reads_as_cyrillic(tmp_path):
    """Measured on 103 real mods: 2,286 Russian and 721 Chinese .tra files are
    not UTF-8, and cp1252 turned every one into Latin letters."""
    mod = tmp_path / "mymod"
    for lang, text, page in (("russian", "Умные маги", "cp1251"),
                             ("polish", "Mądrzy magowie", "cp1250"),
                             ("schinese", "聪明的法师", "cp936"),
                             ("english", "Café", "cp1252")):
        (mod / lang).mkdir(parents=True)
        (mod / lang / "setup.tra").write_bytes(f"@1 = ~{text}~".encode(page))
        assert api._text_under(str(tmp_path), f"mymod/{lang}/setup.tra") == f"@1 = ~{text}~"


def test_utf8_still_comes_first(tmp_path):
    (tmp_path / "russian").mkdir()
    (tmp_path / "russian" / "a.tra").write_bytes("@1 = ~Умные~".encode())
    assert api._text_under(str(tmp_path), "russian/a.tra") == "@1 = ~Умные~"
