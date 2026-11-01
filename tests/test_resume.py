"""
Resuming a stopped install (GUI-AUDIT M4 item 23): the game's WeiDU.log
against the planned log - resumed when it is the plan's beginning, refused
otherwise - and the log of what is left.
"""
from iemod_fetch.resume import Progress, Resume, components, progress

PLAN = ("// Log of Currently Installed WeiDU Mods\n"
        "~EET/EET.TP2~ #0 #0 // EET core\n"
        "~UB/SETUP-UB.TP2~ #0 #0 // Restorations // @wlb-inputs: y,\n"
        "~UB/SETUP-UB.TP2~ #0 #10 // Portraits\n"
        "~CDTWEAKS/SETUP-CDTWEAKS.TP2~ #0 #2 // Tweak\n")


def game(*lines):
    return "// Log of Currently Installed WeiDU Mods\n" + "".join(line + "\n" for line in lines)


def test_a_game_with_nothing_is_fresh_and_its_rest_is_the_whole_plan():
    found = progress(PLAN, "")
    assert found.fresh and found.problem is None and (found.done, found.total) == (0, 4)
    assert len(components(found.rest())) == 4


def test_what_went_in_is_skipped_and_the_rest_keeps_its_recorded_answers():
    found = progress(PLAN, game("~EET\\EET.TP2~ #0 #0 // EET core: v14",
                                "~ub/setup-ub.tp2~ #0 #0 // Restorations"))
    assert found.problem is None and found.done == 2 and not found.finished
    rest = found.rest()
    assert "EET.TP2" not in rest and "#0 #0 // Restorations" not in rest
    assert "~UB/SETUP-UB.TP2~ #0 #10 // Portraits" in rest
    assert rest.startswith("// Log of Currently Installed WeiDU Mods")


def test_a_game_with_every_planned_component_is_finished():
    found = progress(PLAN, game(*PLAN.splitlines()[1:]))
    assert found.finished and components(found.rest()) == []


def test_another_component_another_order_or_one_more_is_not_resumed():
    other = progress(PLAN, game("~EET/EET.TP2~ #0 #0 // EET core",
                                "~UB/SETUP-UB.TP2~ #0 #10 // Portraits"))
    assert other.problem == ("the game is not this plan's install - line 2: the game has "
                             "ub/setup-ub.tp2 #0 #10 where the plan has ub/setup-ub.tp2 #0 #0")
    foreign = progress(PLAN, game("~TWEAKS/TWEAKS.TP2~ #0 #1 // x"))
    assert "line 1: the game has tweaks/tweaks.tp2 #0 #1 where the plan has eet/eet.tp2" \
        in foreign.problem
    more = progress(PLAN, game(*PLAN.splitlines()[1:], "~X/X.TP2~ #0 #0 // x"))
    assert "line 5: the game has x/x.tp2 #0 #0 where the plan has nothing" in more.problem


def test_another_language_or_folder_is_another_install_case_and_separators_are_not():
    other_language = progress(PLAN, game("~EET/EET.TP2~ #1 #0 // EET core"))
    assert "the game has eet/eet.tp2 #1 #0 where the plan has eet/eet.tp2 #0 #0" \
        in other_language.problem
    other_folder = progress(PLAN, game("~OLD/EET.TP2~ #0 #0 // EET core"))
    assert other_folder.problem is not None
    same = progress(PLAN, game("~.\\eet\\Eet.Tp2~  #0  #0 // EET core"))
    assert same.problem is None and same.done == 1


def test_every_diverging_line_is_named_up_to_a_few():
    found = progress(PLAN, game(*[f"~X/X.TP2~ #0 #{n} // x" for n in range(8)]))
    assert found.problem.count("the game has x/x.tp2") == 5
    assert found.problem.endswith("and 3 more line(s)")


def test_the_state_across_an_eet_installs_two_logs():
    pre = Progress([("a/a.tp2", 0, 0)], ["~A/A.TP2~ #0 #0"], [("a/a.tp2", 0, 0)], done=1)
    eet_fresh = Progress([("b/b.tp2", 0, 0)], ["~B/B.TP2~ #0 #0"], [])
    assert Resume({"WeiDU-BGEE.log": pre, "WeiDU.log": eet_fresh}).state == "partial"
    eet_done = Progress([("b/b.tp2", 0, 0)], ["~B/B.TP2~ #0 #0"], [("b/b.tp2", 0, 0)],
                        done=1)
    finished = Resume({"WeiDU-BGEE.log": pre, "WeiDU.log": eet_done})
    assert finished.state == "finished" and (finished.done, finished.total) == (2, 2)
    fresh = Progress([("a/a.tp2", 0, 0)], ["~A/A.TP2~ #0 #0"], [])
    assert Resume({"WeiDU-BGEE.log": fresh, "WeiDU.log": eet_fresh}).state == "fresh"
    wrong = progress(PLAN, game("~X/X.TP2~ #0 #0 // x"))
    mismatch = Resume({"WeiDU.log": wrong})
    assert mismatch.state == "mismatch" and mismatch.problem.startswith("WeiDU.log: ")
