"""
How to start the game after the install (GUI-AUDIT M8 item 71, ADR-0054):
EEex's main component replaces how the game starts - InfinityLoader.exe,
never the game's own program (Bubb13/EEex v1.3.1 README and tp2, read at
a6d21ab).
"""
from iemod_fetch import api, launch

HEADER = "// Log of Currently Installed WeiDU Mods\n"
EEEX_MAIN = "~EEEX\\EEEX.TP2~ #0 #1 // EEex: v1.3.1\n"


def test_eexs_main_component_says_to_start_infinityloader():
    advice = launch.launch_advice({"WeiDU.log": HEADER + EEEX_MAIN}, "win32")
    assert advice == [{"log": "WeiDU.log", "tp2": "eeex.tp2", "component": 1,
                       "program": "InfinityLoader.exe", "why": advice[0]["why"],
                       "platform_note": ""}]
    assert "never with the game's own program" in advice[0]["why"]


def test_its_quick_menu_core_alone_changes_nothing():
    assert launch.launch_advice({"WeiDU.log": HEADER + "~EEex/EEex.tp2~ #0 #0 // Quick Menu Core\n"},
                                "win32") == []


def test_said_once_per_log_however_many_modules():
    text = HEADER + EEEX_MAIN + "".join(f"~EEex/EEex.tp2~ #0 #{n} // module\n"
                                        for n in range(2, 9))
    advice = launch.launch_advice({"WeiDU-BGEE.log": text, "WeiDU.log": text}, "win32")
    assert [a["log"] for a in advice] == ["WeiDU-BGEE.log", "WeiDU.log"]


def test_off_windows_it_says_what_eeex_needs_there():
    for platform, needs in (("linux", "Proton or Wine"), ("darwin", "CrossOver")):
        advice = launch.launch_advice({"WeiDU.log": HEADER + EEEX_MAIN}, platform)
        assert needs in advice[0]["platform_note"]


def test_no_loader_no_advice():
    text = HEADER + "~bg1npc/bg1npc.tp2~ #0 #0 // BG1NPC\n~EEexRemote/x.tp2~ #0 #1 // other\n"
    assert launch.launch_advice({"WeiDU.log": text}, "win32") == []


def test_the_api_reads_the_planned_logs(tmp_path):
    (tmp_path / "WeiDU.log").write_text(HEADER + EEEX_MAIN, encoding="utf-8")
    advice = api.install_launch_advice(str(tmp_path), platform="win32")
    assert [(a["log"], a["program"]) for a in advice] == [("WeiDU.log", "InfinityLoader.exe")]
    assert api.install_launch_advice(str(tmp_path / "none")) == []
