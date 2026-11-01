import os

import pytest

from iemod_fetch.weidu import log_version, parse_weidu_files, parse_weidu_log

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


# Older mods install their tp2 into the game directory, and WeiDU logs it with
# no folder. WeiDU's own naming rule makes setup-<mod>.tp2 the mod <mod>, so
# the folder is derived by that rule - not guessed - and the line is kept
# verbatim for round-tripping. These lines were dropped with a warning, so the
# mod was never planned, fetched or checked.
@pytest.mark.parametrize("line,folder,tp2", [
    ("~SETUP-D0QUESTPACK.TP2~ #0 #5 // Shadow Thieves: v3.5", "D0QUESTPACK",
     "SETUP-D0QUESTPACK.TP2"),
    ("~setup-ascension.tp2~ #0 #0 // Ascension", "ascension", "setup-ascension.tp2"),
    ("~TOBEX.TP2~ #0 #100 // Core", "TOBEX", "TOBEX.TP2"),
])
def test_a_root_level_tp2_names_its_mod_by_weidus_rule(line, folder, tp2):
    log = parse_weidu_log(line + "\n")
    assert log.warnings == []
    mod = log.mods[folder.lower()]
    assert (mod.folder, mod.tp2_file) == (folder, tp2)
    assert mod.components[0].path == line.split("~")[1]


def test_a_bare_setup_prefix_is_still_rejected():
    log = parse_weidu_log("~setup-.tp2~ #0 #0\n")
    assert log.mods == {} and len(log.warnings) == 1


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


def test_supplied_logs_record_one_version():
    """
    These logs were written by Infinity Mod Forge, and only HPS Portraits'
    lines end in a version (`...: 1.2`). Option texts that end the same way -
    cdtweaks' `: 120`, `: Use BG2 values` - are not shared by every component
    of the mod, so they are not taken for one.
    """
    log = parse_weidu_files([os.path.join(DATA, "WeiDU.log")])
    assert [(m.folder, m.version) for m in log.mods.values() if m.version] == [
        ("HPS_PORTRAITS_PROJECT", "1.2")]


# Lines as WeiDU 251 writes them: `Name: VERSION`, one colon, whatever its
# header says. Checked by installing a test mod with the real WeiDU.
def test_weidu_writes_the_version_after_a_plain_colon():
    log = parse_weidu_log("~MYMOD/SETUP-MYMOD.TP2~ #0 #0 // Margarita for BG: EE: v1.2\n"
                          "~MYMOD/SETUP-MYMOD.TP2~ #0 #1 // Plain: v1.2\n")
    assert log.mods["mymod"].version == "v1.2"


def test_a_name_with_a_colon_is_not_a_version():
    assert log_version("Aura NPC for Baldur's Gate: Enhanced Edition") is None
    assert log_version("Artisan's Kitpack: Adjust kit THAC0 progression to match "
                       "tweaked THAC0 tables") is None
    assert log_version("Kitpack: 3e-accurate Dragon Disciple -> Original Stat Bonuses") is None
    assert log_version("UNDEFINED STRING:   @800") is None


def test_versions_in_the_forms_mods_use():
    assert log_version("Core Fixes: Beta 2 - Working Master") == "Beta 2 - Working Master"
    assert log_version("EET_modConverter: beta 0.1") == "beta 0.1"
    assert log_version("Old style : v3") == "v3"


def test_bio_prompt_answers_after_the_version_are_not_the_version():
    """BIO's own help: `... // EET core (resource importation): v14.0 //
    @wlb-inputs: C:\\My Games\\BG2`."""
    line = r"EET core (resource importation): v14.0 // @wlb-inputs: C:\My Games\BG2"
    assert log_version(line) == "v14.0"
    assert log_version("EET core: v14.0 // @wlb-inputs: y") == "v14.0"


def test_a_mod_half_upgraded_has_no_single_version():
    log = parse_weidu_log("~m/setup-m.tp2~ #0 #0 // A: v1\n~m/setup-m.tp2~ #0 #1 // B: v2\n")
    assert log.mods["m"].version is None


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
