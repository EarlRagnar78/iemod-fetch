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
