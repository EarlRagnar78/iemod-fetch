"""
The questions a planned install will meet, before it starts (GUI-AUDIT item
48, ADR-0049): api.install_questions reads the planned WeiDU logs, scans each
component's mod in the log's language, and says which are answered.
"""
from iemod_fetch import api

TP2 = """BACKUP ~mymod/backup~
LANGUAGE ~English~ ~english~ ~mymod/tra/english/setup.tra~
LANGUAGE ~Italiano~ ~italian~ ~mymod/tra/italian/setup.tra~
BEGIN @10 DESIGNATED 0
  PRINT @1
  ACTION_READLN portraits
BEGIN @11 DESIGNATED 10
  COPY_EXISTING ~sw1h01.itm~ ~override~
BEGIN @12 DESIGNATED 20
  ACTION_IF NOT FILE_EXISTS ~mymod/prefs.txt~ BEGIN
    PRINT @2
    ACTION_READLN chance
  END
BEGIN @13 DESIGNATED 30
  OUTER_SPRINT p @1
  PRINT ~%p%~
  ACTION_READLN other
"""


def project(tmp_path, log_lines):
    mods = tmp_path / "Mods" / "mymod"
    (mods / "tra" / "english").mkdir(parents=True)
    (mods / "tra" / "italian").mkdir(parents=True)
    (mods / "setup-mymod.tp2").write_text(TP2, encoding="utf-8")
    (mods / "tra" / "english" / "setup.tra").write_text(
        "@1 = ~Which portraits?~\n@2 = ~A percentage:~\n", encoding="utf-8")
    (mods / "tra" / "italian" / "setup.tra").write_text(
        "@1 = ~Quali ritratti?~\n@2 = ~Una percentuale:~\n", encoding="utf-8")
    plan = tmp_path / "install-plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text("// Log of Currently Installed WeiDU Mods\n"
                                    + "".join(line + "\n" for line in log_lines),
                                    encoding="utf-8")
    return str(plan), str(tmp_path / "Mods")


def by_number(found):
    return {c["number"]: c for c in found["components"]}


def test_each_component_says_what_it_asks_and_whether_it_is_answered(tmp_path):
    plan, mods = project(tmp_path, [
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #0 // Portraits // @wlb-inputs: 2",
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #10 // Swords",
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #20 // Chance",
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #30 // Other // @wlb-inputs: y"])
    found = by_number(api.install_questions(plan, mods))
    assert found[0]["status"] == "answered" and found[0]["recorded"] == ["2"]
    assert [q["text"] for q in found[0]["questions"]] == ["Which portraits?"]
    assert found[10]["status"] == "none" and found[10]["questions"] == []
    # asked only when a file is missing, no answer recorded: "maybe" - it may
    # or may not come, and the plan is not forecast unattended
    assert found[20]["status"] == "maybe"
    assert found[20]["questions"][0]["conditional"]
    # its text is set elsewhere: unknown, even with an answer recorded
    assert found[30]["status"] == "unknown" and not found[30]["questions"][0]["known"]


def test_the_questions_are_read_in_the_logs_language(tmp_path):
    plan, mods = project(tmp_path, ["~MYMOD/SETUP-MYMOD.TP2~ #1 #0 // Ritratti"])
    [component] = api.install_questions(plan, mods)["components"]
    assert component["questions"][0]["text"] == "Quali ritratti?"
    assert component["questions"][0]["key"] == "@1"


def test_unattended_only_when_nothing_is_left_to_ask(tmp_path):
    plan, mods = project(tmp_path, [
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #0 // Portraits // @wlb-inputs: 1",
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #10 // Swords"])
    found = api.install_questions(plan, mods)
    assert found["unattended"] and found["counts"] == {"answered": 1, "none": 1}
    plan, mods = project(tmp_path / "b", [
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #0 // Portraits"])
    assert not api.install_questions(plan, mods)["unattended"]


def test_a_mod_missing_from_the_mods_folder_is_said_so(tmp_path):
    plan, mods = project(tmp_path, ["~OTHER/SETUP-OTHER.TP2~ #0 #0 // Missing"])
    [component] = api.install_questions(plan, mods)["components"]
    assert component["status"] == "unknown"
    assert component["unread"] == ["OTHER/SETUP-OTHER.TP2 (not given)"]


TP2_MORE = """BACKUP ~mymod/backup~
LANGUAGE ~English~ ~english~ ~mymod/tra/english/setup.tra~
BEGIN @10 DESIGNATED 0
  PRINT @1
  ACTION_READLN portraits
BEGIN @11 DESIGNATED 10
  ACTION_INCLUDE ~%somevar%/ask.tpa~
BEGIN @12 DESIGNATED 20
  INCLUDE ~mymod/missing.tpa~
BEGIN @13 DESIGNATED 30
  PRINT @1
  ACTION_READLN a
  ACTION_IF FILE_EXISTS ~x~ BEGIN
    PRINT @2
    ACTION_READLN b
  END
BEGIN @14 DESIGNATED 40
  PRINT @1
  ACTION_READLN a
  PRINT @2
  ACTION_READLN b
"""


def project_more(tmp_path, log_lines, bom=False):
    plan, mods = project(tmp_path, [])
    (tmp_path / "Mods" / "mymod" / "setup-mymod.tp2").write_text(TP2_MORE, encoding="utf-8")
    text = ("\ufeff" if bom else "") + "".join(line + "\n" for line in log_lines)
    (tmp_path / "install-plan" / "WeiDU.log").write_text(text, encoding="utf-8")
    return plan, mods


def test_a_path_a_component_could_not_follow_makes_it_unknown_and_only_it(tmp_path):
    """Review of #104: an unreadable include of its own made a component
    "none", and the mod's unread paths marked its clean components unknown."""
    plan, mods = project_more(tmp_path, [
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #0 // ok // @wlb-inputs: 1",
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #10 // var path",
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #20 // missing"])
    found = api.install_questions(plan, mods)
    status = {c["number"]: (c["status"], c["unread"]) for c in found["components"]}
    assert status[0] == ("answered", [])
    assert status[10][0] == "unknown" and "somevar" in status[10][1][0]
    assert status[20][0] == "unknown" and "missing.tpa" in status[20][1][0]
    assert not found["unattended"]


def test_answers_cover_conditional_questions_or_it_is_only_maybe(tmp_path):
    plan, mods = project_more(tmp_path, [
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #30 // one sure, one conditional // @wlb-inputs: 1",
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #40 // two sure // @wlb-inputs: 1"])
    found = by_number(api.install_questions(plan, mods))
    assert found[30]["status"] == "maybe"
    assert found[40]["status"] == "partial"


def test_an_empty_or_unread_plan_is_not_forecast_unattended(tmp_path):
    assert api.install_questions(str(tmp_path / "none"), str(tmp_path))["unattended"] is False


def test_a_byte_order_mark_does_not_hide_the_first_line(tmp_path):
    plan, mods = project_more(tmp_path, ["~MYMOD/SETUP-MYMOD.TP2~ #0 #0 // ok"], bom=True)
    assert [c["number"] for c in api.install_questions(plan, mods)["components"]] == [0]


def test_only_the_two_logs_mod_installer_reads_in_its_order(tmp_path):
    plan, mods = project_more(tmp_path, ["~MYMOD/SETUP-MYMOD.TP2~ #0 #40 // eet side"])
    (tmp_path / "install-plan" / "WeiDU-BGEE.log").write_text(
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #0 // bgee side\n", encoding="utf-8")
    (tmp_path / "install-plan" / "old.log").write_text(
        "~MYMOD/SETUP-MYMOD.TP2~ #0 #30 // not read\n", encoding="utf-8")
    found = api.install_questions(plan, mods)["components"]
    assert [(c["log"], c["number"]) for c in found] == [("WeiDU-BGEE.log", 0), ("WeiDU.log", 40)]
