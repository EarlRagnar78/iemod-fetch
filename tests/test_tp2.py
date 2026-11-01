"""
Reading a mod's own .tp2 — the authority on its version and supported games.

Closes the gap reported in AUDIT.md: the WeiDU logs record no versions, but the
mods do.
"""
import os


from iemod_fetch.tp2 import parse_tp2, read_mod_tp2, read_tp2, strip_comments

FIXPACK = """
// a comment that mentions VERSION ~v99-wrong~ and GAME_IS ~pstee~
BACKUP ~eefixpack/backup~
AUTHOR ~someone@example.com~
VERSION ~v9.2.1~
BEGIN ~EE Fixpack~
LANGUAGE ~English~ ~english~ ~eefixpack/english/setup.tra~
LANGUAGE ~Italiano~ ~italian~ ~eefixpack/italian/setup.tra~
/* a block comment with VERSION ~v98-wrong~ */
REQUIRE_PREDICATE GAME_IS ~bgee sod bg2ee eet~ @2
ACTION_IF NOT GAME_IS ~iwdee~ BEGIN END
OUTER_SET x = GAME_IS ~pst~ ? 1 : 0
"""


def test_version_is_read_from_the_mod():
    assert parse_tp2(FIXPACK).version == "v9.2.1"


def test_comments_cannot_supply_a_version_or_a_game():
    """Both a // line and a /* block */ contain decoys."""
    info = parse_tp2(FIXPACK)
    assert info.version == "v9.2.1"
    assert "pstee" not in [g.lower() for g in info.games]


def test_name_authors_and_languages():
    info = parse_tp2(FIXPACK)
    assert info.mod_name == "EE Fixpack"
    assert info.authors == ["someone@example.com"]
    assert info.languages == ["English", "Italiano"]


def test_declared_games_are_normalised():
    assert parse_tp2(FIXPACK).normalised_games == ["BGEE", "SoD", "BG2EE", "EET"]


def test_negated_and_ternary_checks_are_not_requirements():
    """`NOT GAME_IS ~iwdee~` and `GAME_IS ~pst~ ? 1 : 0` state no support."""
    info = parse_tp2(FIXPACK)
    assert info.supports("IWDEE") is False
    assert info.supports("PST") is False
    assert info.supports("EET") is True


def test_a_ternary_anywhere_does_not_suppress_every_other_check():
    """
    Regression: anchoring the exclusion with `.*` under DOTALL let one
    `? 1 : 0` later in the file hide every GAME_IS above it.
    """
    content = ("REQUIRE_PREDICATE GAME_IS ~eet~ @1\n"
               "OUTER_SET x = GAME_IS ~pst~ ? 1 : 0\n")
    assert parse_tp2(content).normalised_games == ["EET"]


def test_a_mod_with_no_game_check_has_no_opinion():
    """Silence means 'installs anywhere', not 'incompatible'."""
    info = parse_tp2("VERSION ~v1~\nBEGIN ~Anything~\n")
    assert info.games == []
    assert info.supports("EET") is None


def test_game_includes_and_engine_is_also_count():
    info = parse_tp2("ACTION_IF GAME_INCLUDES ~tob~ BEGIN END\n"
                     "ACTION_IF ENGINE_IS ~bgee~ BEGIN END\n")
    assert set(info.normalised_games) == {"BG2", "BGEE"}


def test_a_missing_version_is_none_not_an_error():
    assert parse_tp2("BACKUP ~x~\n").version is None


def test_strip_comments_leaves_code():
    assert "KEEP" in strip_comments("/* gone */ KEEP // gone\n")


# --------------------------------------------------------------------- disk
def test_reading_from_disk(tmp_path):
    path = tmp_path / "setup-eefixpack.tp2"
    path.write_text(FIXPACK, encoding="utf-8")
    assert read_tp2(str(path)).version == "v9.2.1"


def test_a_missing_file_returns_none_rather_than_raising(tmp_path):
    assert read_tp2(str(tmp_path / "nope.tp2")) is None


def test_an_oversized_file_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "big.tp2"
    path.write_text("VERSION ~v1~")
    monkeypatch.setattr(os.path, "getsize", lambda _p: 99 * 1024 * 1024)
    assert read_tp2(str(path)) is None


def test_undecodable_bytes_do_not_crash(tmp_path):
    path = tmp_path / "x.tp2"
    path.write_bytes(b"VERSION ~v2\xff\xfe~\nBEGIN ~m~\n")
    assert read_tp2(str(path)) is not None


def test_read_mod_tp2_finds_the_file_case_insensitively(tmp_path):
    mod = tmp_path / "eefixpack"
    mod.mkdir()
    (mod / "SETUP-EEFIXPACK.TP2").write_text(FIXPACK, encoding="utf-8")
    assert read_mod_tp2(str(mod), "setup-eefixpack.tp2").version == "v9.2.1"


def test_read_mod_tp2_returns_none_when_absent(tmp_path):
    (tmp_path / "empty").mkdir()
    assert read_mod_tp2(str(tmp_path / "empty"), "x.tp2") is None


# ------------------------------------------- WeiDU's strings (GUI-AUDIT item 43)
QUOTED = '''BACKUP ~mymod/backup~
AUTHOR ~The "Quoted" Author~
VERSION ~v2 "smart"~
LANGUAGE ~Eng "lish"~ ~english~ ~mymod/english.tra~

BEGIN ~Use "smart" AI~
REQUIRE_PREDICATE GAME_IS ~bg2ee eet~ ~need "ee"~

BEGIN ~~~~~A ~tilde~ name~~~~~
'''


def test_a_string_closes_on_the_mark_that_opened_it():
    """WeiDU 251 on this tp2: --list-languages `0:Eng "lish"`, and
    --list-components-json names `Use "smart" AI` and `A ~tilde~ name`.
    The old regex read version `v2`, name `Use`, authors ['The', 'VERSION']."""
    info = parse_tp2(QUOTED)
    assert info.version == 'v2 "smart"'
    assert info.mod_name == 'Use "smart" AI'
    assert info.authors == ['The "Quoted" Author']
    assert info.games == ["bg2ee", "eet"]
    assert info.language_decls == [('Eng "lish"', "english")]


def test_five_tildes_hold_tildes():
    assert parse_tp2("BACKUP ~x~\nBEGIN ~~~~~A ~tilde~ name~~~~~\n").mod_name == "A ~tilde~ name"


def test_language_inside_code_is_not_a_declaration():
    """Measured on 119 real tp2s against WeiDU 251's --list-languages: 12 read
    code as a language (BoneHill's `reload_array = ... LANGUAGE`, ToA's
    `iconv_path =`) or lost SCS's bare directory `ENGLISH`; now all 119 agree."""
    tp2 = '''BACKUP ~x~
ACTION_IF FILE_EXISTS ~x~ BEGIN
  LAF HANDLE_CHARSETS STR_VAR iconv_path = ~%MOD_FOLDER%~ END
END
LANGUAGE ~English~ ENGLISH ~x/english/setup.tra~
LANGUAGE ~Deutsch~ german ~x/german/setup.tra~
'''
    info = parse_tp2(tp2)
    assert info.language_decls == [("English", "ENGLISH"), ("Deutsch", "german")]
    assert info.languages == ["English", "Deutsch"]


def test_version_is_the_preamble_line_not_a_variable():
    tp2 = 'BACKUP ~x~\nOUTER_SPRINT v ~%VERSION%~\nVERSION ~v3~\n'
    assert parse_tp2(tp2).version == "v3"


def test_a_one_line_preamble_keeps_version_and_language():
    """Review of #57: anchored to the line start, both were lost. WeiDU 251
    prints `// Comp: v1` and `0:English` for this tp2."""
    info = parse_tp2("BACKUP ~b/backup~ AUTHOR ~me~ VERSION ~v1~ "
                     "LANGUAGE ~English~ ~english~ ~english/a.tra~\nBEGIN ~Comp~\n")
    assert info.version == "v1"
    assert info.language_decls == [("English", "english")]


def test_words_inside_a_string_are_not_keywords():
    """Review of #57: a line of a README string starting `version`, or a
    PRINT reading `language packs`, was taken for the keyword. WeiDU 251:
    VERSION v2 and the one language English."""
    tp2 = ("BACKUP ~c/backup~\nREADME ~c/readme.txt\nversion 9 notes~\nVERSION ~v2~\n"
           "LANGUAGE ~English~ ~english~ ~english/a.tra~\n"
           "BEGIN ~Comp~\nPRINT ~Note:\nlanguage packs are separate.~\n")
    info = parse_tp2(tp2)
    assert info.version == "v2"
    assert info.language_decls == [("English", "english")]


def test_a_comment_mark_inside_a_string_does_not_end_it():
    """Review of #57: `~bg2ee // eet~` lost its close to the comment strip and
    the game list ran on into the next line."""
    info = parse_tp2("BACKUP ~x~\nREQUIRE_PREDICATE GAME_IS ~bg2ee // eet~ ~x~\n"
                     "ACTION_IF GAME_IS ~iwdee~ BEGIN END\n")
    assert "ACTION_IF" not in info.games and "iwdee" in info.games
