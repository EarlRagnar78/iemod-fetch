"""
The phase-5 questionnaire's answers (ADR-0049 points 2 and 5): which
questions can be answered before the install, the answers kept in the
project, and written into the planned logs as `// @wlb-inputs:` - only where
the order of the questions makes them land on the right one.
"""
import pytest

from iemod_fetch import api, prompts

TP2 = """BACKUP ~mymod/backup~
LANGUAGE ~English~ ~english~ ~mymod/tra/english/setup.tra~
BEGIN @10 DESIGNATED 0
  PRINT @1
  ACTION_READLN portraits
  PRINT @3
  ACTION_READLN size
BEGIN @11 DESIGNATED 10
  PRINT @1
  ACTION_READLN first
  ACTION_IF NOT FILE_EXISTS ~mymod/prefs.txt~ BEGIN
    PRINT @2
    ACTION_READLN chance
  END
  PRINT @3
  ACTION_READLN after
BEGIN @12 DESIGNATED 20
  OUTER_SET ok = 0
  OUTER_WHILE ok = 0 BEGIN
    PRINT @2
    ACTION_READLN chance
    OUTER_SET ok = 1
  END
  PRINT @3
  ACTION_READLN size
BEGIN @13 DESIGNATED 30
  OUTER_SPRINT p @1
  PRINT ~%p%~
  ACTION_READLN other
  PRINT @3
  ACTION_READLN size
BEGIN @14 DESIGNATED 40
  COPY_EXISTING ~sw1h01.itm~ ~override~
"""


def project(tmp_path, log_lines):
    mods = tmp_path / "Mods" / "mymod"
    (mods / "tra" / "english").mkdir(parents=True)
    (mods / "setup-mymod.tp2").write_text(TP2, encoding="utf-8")
    (mods / "tra" / "english" / "setup.tra").write_text(
        "@1 = ~Please select the portraits to use:~\n@2 = ~Please enter a percentage:~\n"
        "@3 = ~Please enter how big it should be:~\n", encoding="utf-8")
    plan = tmp_path / "install-plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text("// Log of Currently Installed WeiDU Mods\n"
                                    + "".join(line + "\n" for line in log_lines),
                                    encoding="utf-8")
    return str(plan), str(tmp_path / "Mods")


ALL = [f"~MYMOD/SETUP-MYMOD.TP2~ #0 #{n} // c{n}" for n in (0, 10, 20, 30, 40)]


def by_number(found):
    return {c["number"]: c for c in found["components"]}


def ahead(component):
    return [q["beforehand"] for q in component["questions"]]


def alone(tmp_path, number):
    """One component as its own batch: what it can have answered by itself."""
    plan, mods = project(tmp_path / str(number), [ALL[(0, 10, 20, 30, 40).index(number)]])
    return api.install_questions(plan, mods)["components"][0]


def test_which_questions_can_be_answered_beforehand(tmp_path):
    assert ahead(alone(tmp_path, 0)) == [True, True]         # both surely asked, in order
    # under a condition: if it were not asked, its answer would go to the next
    assert ahead(alone(tmp_path, 10)) == [True, False, False]
    # asked until valid: answered, but nothing after it (a refused answer would
    # go to the next question)
    assert ahead(alone(tmp_path, 20)) == [True, False]
    # unknown text (status unknown): nothing beforehand
    unknown = alone(tmp_path, 30)
    assert unknown["status"] == "unknown" and ahead(unknown) == [False, False]
    assert alone(tmp_path, 40)["questions"] == []
    # all five in one batch: #0 answered in full, #10 may leave a question that
    # would take the next one's answer - nothing after it
    found = by_number(api.install_questions(*project(tmp_path / "all", ALL)))
    assert ahead(found[0]) == [True, True] and ahead(found[10]) == [True, False, False]
    assert ahead(found[20]) == [False, False]


def test_answers_are_kept_in_the_project(tmp_path):
    assert api.load_install_answers(str(tmp_path)) == {}
    api.save_install_answers(str(tmp_path), {"setup-mymod.tp2#0": {"@1": "2", "@3": ""}})
    assert api.load_install_answers(str(tmp_path)) == {"setup-mymod.tp2#0": {"@1": "2", "@3": ""}}
    (tmp_path / api.INSTALL_ANSWERS_FILE).write_text("not json")
    assert api.load_install_answers(str(tmp_path)) == {}       # unreadable: none


def test_answers_go_into_the_planned_log_in_order(tmp_path):
    plan, mods = project(tmp_path, ALL)
    answers = {"setup-mymod.tp2#0": {"@1": "2", "@3": ""},           # Enter is an answer
               "setup-mymod.tp2#10": {"@1": "y", "@2": "50", "@3": "big"},
               "setup-mymod.tp2#20": {"@2": "30", "@3": "small"}}
    found = by_number(api.write_install_answers(plan, mods, answers))
    log = (tmp_path / "install-plan" / "WeiDU.log").read_text(encoding="utf-8")
    assert "#0 // c0 // @wlb-inputs: 2,\n" in log
    # only the answer before the condition: the others are asked during the install
    assert "#10 // c10 // @wlb-inputs: y\n" in log
    # one batch: #10's later questions would take #20's answers - none written
    assert "#20 // c20\n" in log and "#40 // c40\n" in log and "#30 // c30\n" in log
    assert found[0]["status"] == "answered"
    # the rest are the same texts in several components of one batch: which
    # component asks is not known when they come, so not answered by question
    # either (review of #111) - asked during the install
    assert found[10]["status"] == "partial" and found[20]["status"] == "unanswered"
    assert not any(q["by_question"] for q in found[20]["questions"])


def test_a_question_under_a_condition_is_answered_by_question(tmp_path):
    """Its text known, long enough, one mod_installer asks, and unique in
    its batch: offered and counted answered, given by its key when it comes."""
    plan, mods = two_mod(tmp_path, ["~TWO/SETUP-TWO.TP2~ #0 #10 // a",
                                    "~TWO/SETUP-TWO.TP2~ #0 #20 // c"])
    found = by_number(api.install_questions(plan, mods))
    assert [q["by_question"] for q in found[10]["questions"]] == [True, True]
    assert ahead(found[20]) == [False] and found[20]["questions"][0]["by_question"]
    found = by_number(api.write_install_answers(plan, mods, {
        "setup-two.tp2#10": {"@1": "y", "@2": "n"}, "setup-two.tp2#20": {"@3": "z"}}))
    assert found[10]["status"] == "answered" and found[20]["status"] == "answered"
    # left to be asked (None): not answered
    found = by_number(api.write_install_answers(plan, mods, {
        "setup-two.tp2#10": {"@1": "y", "@2": None}, "setup-two.tp2#20": {"@3": "z"}}))
    assert found[10]["status"] == "maybe"          # the conditional one may come


def test_a_missing_answer_ends_the_row_and_a_rewrite_replaces_the_old_one(tmp_path):
    plan, mods = project(tmp_path, ALL)
    api.write_install_answers(plan, mods, {"setup-mymod.tp2#0": {"@1": "2", "@3": "x"}})
    api.write_install_answers(plan, mods, {"setup-mymod.tp2#0": {"@3": "x"}})
    log = (tmp_path / "install-plan" / "WeiDU.log").read_text(encoding="utf-8")
    # the first question has no answer now: nothing is written (the line as planned
    # keeps the earlier answers - a plan is written afresh before each install)
    assert log.count("@wlb-inputs") == 1


def test_an_answer_with_a_comma_cannot_be_written():
    log = "~A/SETUP-A.TP2~ #0 #0 // a\n"
    with pytest.raises(ValueError, match="comma"):
        prompts.set_inputs(log, {("setup-a.tp2", 0): ["1,2"]})


def test_set_inputs_keeps_every_other_line():
    log = ("// Log of Currently Installed WeiDU Mods\n"
           "~A/SETUP-A.TP2~ #0 #0 // a // @wlb-inputs: old\n"
           "~B/SETUP-B.TP2~ #0 #5 // b\n")
    out = prompts.set_inputs(log, {("setup-a.tp2", 0): ["n", ""], ("setup-b.tp2", 5): ["y"]})
    assert out == ("// Log of Currently Installed WeiDU Mods\n"
                   "~A/SETUP-A.TP2~ #0 #0 // a // @wlb-inputs: n,\n"
                   "~B/SETUP-B.TP2~ #0 #5 // b // @wlb-inputs: y\n")
    assert prompts.recorded_answers(out) == {("setup-a.tp2", 0): ["n", ""],
                                             ("setup-b.tp2", 5): ["y"]}
    assert prompts.set_inputs(out, {("setup-a.tp2", 0): []}).splitlines()[1] == \
        "~A/SETUP-A.TP2~ #0 #0 // a"


BATCH_TP2 = """BACKUP ~two/backup~
LANGUAGE ~English~ ~english~ ~two/english.tra~
BEGIN @10 DESIGNATED 10
  PRINT @1
  ACTION_READLN a
  ACTION_IF NOT FILE_EXISTS ~two/x~ BEGIN
    PRINT @2
    ACTION_READLN b
  END
BEGIN @11 DESIGNATED 20
  PRINT @3
  ACTION_READLN c
BEGIN @12 DESIGNATED 30
  PRINT @4
  ACTION_READLN d
BEGIN @13 DESIGNATED 40
  PRINT @4
  ACTION_READLN e
  PRINT @4
  ACTION_READLN f
"""


def two_mod(tmp_path, lines):
    mod = tmp_path / "Mods" / "two"
    mod.mkdir(parents=True)
    (mod / "setup-two.tp2").write_text(BATCH_TP2, encoding="utf-8")
    (mod / "english.tra").write_text(
        "@1 = ~Please enter the first value:~\n@2 = ~Do you want the optional part?~\n"
        "@3 = ~Please enter the third value:~\n@4 = ~Please enter a value here:~\n",
        encoding="utf-8")
    plan = tmp_path / "install-plan"
    plan.mkdir()
    (plan / "WeiDU.log").write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return str(plan), str(tmp_path / "Mods")


def test_in_a_batch_nothing_after_a_component_left_with_something_to_ask(tmp_path):
    """Review of #107: mod_installer runs consecutive components of one mod as
    one batch and hands their answers out from one queue - #10's conditional
    question, if asked, would take #20's answer."""
    plan, mods = two_mod(tmp_path, ["~TWO/SETUP-TWO.TP2~ #0 #10 // a",
                                    "~TWO/SETUP-TWO.TP2~ #0 #20 // c"])
    found = by_number(api.install_questions(plan, mods))
    assert ahead(found[10]) == [True, False] and ahead(found[20]) == [False]
    api.write_install_answers(plan, mods, {"setup-two.tp2#10": {"@1": "y", "@2": "n"},
                                           "setup-two.tp2#20": {"@3": "z"}})
    log = (tmp_path / "install-plan" / "WeiDU.log").read_text(encoding="utf-8")
    assert "#10 // a // @wlb-inputs: y\n" in log and "#20 // c\n" in log
    # delivered as the install delivers them: #20's question goes to the player
    queue = prompts.Answers(prompts.recorded_answers(log))
    queue.start((("setup-two.tp2", 10), ("setup-two.tp2", 20)))
    assert [queue.next(), queue.next()] == ["y", None]


def test_another_mod_between_them_is_another_batch(tmp_path):
    plan, mods = two_mod(tmp_path, ["~TWO/SETUP-TWO.TP2~ #0 #10 // a",
                                    "~MYMOD/SETUP-MYMOD.TP2~ #0 #40 // x",
                                    "~TWO/SETUP-TWO.TP2~ #0 #20 // c"])
    assert ahead(by_number(api.install_questions(plan, mods))[20]) == [True]


def test_a_component_answered_in_full_leaves_the_next_one_answerable(tmp_path):
    plan, mods = two_mod(tmp_path, ["~TWO/SETUP-TWO.TP2~ #0 #20 // c",
                                    "~TWO/SETUP-TWO.TP2~ #0 #30 // d"])
    found = api.write_install_answers(plan, mods, {"setup-two.tp2#20": {"@3": "1"},
                                                   "setup-two.tp2#30": {"@4": "2"}})
    assert [c["status"] for c in found["components"]] == ["answered", "answered"]
    assert found["unattended"]
    # an answer missing for #20 leaves #30's unwritten too
    plan, mods = two_mod(tmp_path / "b", ["~TWO/SETUP-TWO.TP2~ #0 #20 // c",
                                          "~TWO/SETUP-TWO.TP2~ #0 #30 // d"])
    api.write_install_answers(plan, mods, {"setup-two.tp2#30": {"@4": "2"}})
    assert "@wlb-inputs" not in (tmp_path / "b" / "install-plan" / "WeiDU.log").read_text()


def test_two_questions_that_read_alike_do_not_share_an_answer(tmp_path):
    plan, mods = two_mod(tmp_path, ["~TWO/SETUP-TWO.TP2~ #0 #40 // e"])
    [component] = api.install_questions(plan, mods)["components"]
    assert ahead(component) == [True, False]


def test_an_answer_the_log_cannot_carry_is_not_loaded(tmp_path):
    """Review of #107: one kept with a comma or a line end would fail every
    install; left out, the questionnaire asks it again."""
    (tmp_path / api.INSTALL_ANSWERS_FILE).write_text(
        '{"v": 1, "answers": {"a#0": {"@1": "1,2", "@2": "x\\ny", "@3": "ok"}}}')
    assert api.load_install_answers(str(tmp_path)) == {"a#0": {"@3": "ok"}}


@pytest.mark.parametrize("answer", ["a,b", "a\nb", "a\rb", "a\x0bb", "a\x85b", "a b"])
def test_any_line_break_python_reads_is_refused(answer):
    """Second review of #107: str.splitlines() breaks at more than \\n."""
    assert not prompts.writable(answer) and not api.writable_answer(answer)
    with pytest.raises(ValueError):
        prompts.set_inputs("~A/SETUP-A.TP2~ #0 #0 // a\n", {("setup-a.tp2", 0): [answer]})
    assert prompts.writable("a b") and prompts.writable("")
