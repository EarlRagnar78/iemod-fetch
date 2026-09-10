import os

import pytest

from iemod_fetch.weidu import parse_weidu_files, parse_weidu_log

DATA = os.path.join(os.path.dirname(__file__), "data")


def test_parses_the_documented_line_format():
    log = parse_weidu_log(
        "// Log of Currently Installed WeiDU Mods\n"
        "~DlcMerger\\DlcMerger.tp2~ #0 #3 // Merge DLC: All available DLCs\n"
        "~eefixpack\\SETUP-EEFIXPACK.TP2~ #0 #0 // Core Fixes\n")
    assert list(log.mods) == ["dlcmerger", "eefixpack"]
    assert log.mods["dlcmerger"].folder == "DlcMerger"
    assert log.mods["eefixpack"].tp2_file == "SETUP-EEFIXPACK.TP2"
    assert log.component_count == 2


def test_a_colon_in_a_component_name_is_not_a_version():
    """'Margarita for Baldur's Gate: Enhanced Edition' must not parse as a version."""
    log = parse_weidu_log("~Margarita\\SETUP-MARGARITA.TP2~ #0 #0 "
                          "// Margarita for Baldur's Gate: Enhanced Edition\n")
    assert log.mods["margarita"].version is None


def test_spaced_colon_is_a_version():
    log = parse_weidu_log("~ub\\ub.tp2~ #0 #1 // Unfinished Business : v4.2\n")
    assert log.mods["ub"].version == "v4.2"


def test_unparseable_lines_are_reported_not_silently_dropped():
    log = parse_weidu_log("this is not a weidu line\n~x\\x.tp2~ #0 #0\n")
    assert len(log.warnings) == 1 and "unparseable" in log.warnings[0]
    assert len(log.mods) == 1


def test_real_logs_parse_completely():
    log = parse_weidu_files([os.path.join(DATA, "WeiDU.log"),
                             os.path.join(DATA, "WeiDUBGEE.log")])
    assert log.warnings == []
    assert log.component_count == 796
    assert len(log.mods) == 148


def test_supplied_logs_record_no_versions_at_all():
    """
    Honest limitation: these logs pin nothing, so this install cannot be
    reproduced from them - only re-fetched at 'latest'.
    """
    log = parse_weidu_files([os.path.join(DATA, "WeiDU.log")])
    assert [m.folder for m in log.mods.values() if m.version] == []


# ------------------------------------------------------------ game context
def test_eet_is_detected_from_the_log_itself():
    log = parse_weidu_log("~eet\\EET.TP2~ #0 #0 // EET core\n"
                          "~cdtweaks\\setup-cdtweaks.tp2~ #0 #1 // Tweak\n")
    assert log.detect_game() == "EET"


def test_a_non_eet_log_is_left_unknown_rather_than_guessed():
    """A wrong game produces wrong warnings, which is worse than no warnings."""
    log = parse_weidu_log("~bg1ub\\BG1UB.TP2~ #0 #1 // Restoration\n")
    assert log.detect_game() is None


def test_the_supplied_logs_are_classified_correctly():
    eet = parse_weidu_files([os.path.join(DATA, "WeiDU.log")])
    bgee = parse_weidu_files([os.path.join(DATA, "WeiDUBGEE.log")])
    assert eet.game == "EET"
    assert bgee.game is None                    # BGEE is not inferable; say so
    assert eet.mods["cdtweaks"].game == "EET"


def test_each_log_keeps_its_own_game_when_merged():
    merged = parse_weidu_files([(os.path.join(DATA, "WeiDU.log"), None),
                                (os.path.join(DATA, "WeiDUBGEE.log"), "BGEE")])
    assert merged.mods["cdtweaks"].game == "EET"
    assert merged.mods["karatur"].game == "BGEE"


@pytest.mark.parametrize("spec,expected", [
    ("WeiDU.log", ("WeiDU.log", None)),
    ("WeiDU.log:EET", ("WeiDU.log", "EET")),
    ("WeiDU.log:bgee", ("WeiDU.log", "BGEE")),
    ("/srv/games/WeiDU.log:BG2EE", ("/srv/games/WeiDU.log", "BG2EE")),
    ("C:\\Games\\WeiDU.log", ("C:\\Games\\WeiDU.log", None)),   # not mangled
    ("WeiDU.log:notagame", ("WeiDU.log:notagame", None)),
])
def test_log_spec_parsing(spec, expected):
    from iemod_fetch.weidu import split_log_spec
    assert split_log_spec(spec) == expected
