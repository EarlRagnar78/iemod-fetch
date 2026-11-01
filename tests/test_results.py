"""
What each component of an install came to (GUI-AUDIT M8 item 69, ADR-0053):
WeiDU's own verdicts in WSETUP.DEBUG, held to WeiDU.log before and after.
The debug text below is the shape the real mod_installer 16.0.0 and WeiDU
v251 write (measured; test_real_mod_installer.py checks it against them).
"""
from iemod_fetch import results as r

WEIDU = "/opt/weidu/weidu"


def block(tp2, numbers, body):
    return (f"WeiDU v 25100 Log\n\n {WEIDU} {tp2} --force-install-list {numbers} "
            f"--use-lang en_US --language 0 --no-exit-pause --logapp --autolog "
            f"--log-extern\n[./chitin.key] loaded, 24 bytes\n{body}\n\t\tWeiDU Timings\n"
            f"TOTAL                            0.072\n")


DEBUG = (block("good/good.tp2", "0", "Installing [One] [2]\nSaving This Log:\n"
               "GOOD/GOOD.TP2  0  0 Installed ~One~\n\nSUCCESSFULLY INSTALLED      One\n")
         + block("good/good.tp2", "1", "Installing [Warns] [2]\ncareful\nSaving This Log:\n"
                 "\nINSTALLED WITH WARNINGS     Warns\n")
         + block("bad/bad.tp2", "1", "Installing [Broken]\nFAILURE:\nbroken\n"
                 "ERROR Installing [Broken], rolling back to previous state\n"
                 "NOT INSTALLED DUE TO ERRORS Broken\n"))
LOG = ("// Log of Currently Installed WeiDU Mods\n"
       "~GOOD/GOOD.TP2~ #0 #0 // One: 2\n~GOOD/GOOD.TP2~ #0 #1 // Warns: 2\n")


def test_each_weidu_run_gives_its_components_verdicts():
    assert r.debug_verdicts(DEBUG) == {
        ("good.tp2", 0): (r.OK, "One"), ("good.tp2", 1): (r.WARNINGS, "Warns"),
        ("bad.tp2", 1): (r.ERRORS, "Broken")}


def test_a_batch_of_several_components_is_matched_in_its_order():
    text = block("Mod\\SETUP-MOD.TP2", "3 10 20",
                 "Installing [A]\nSUCCESSFULLY INSTALLED      A\nInstalling [B]\n"
                 "INSTALLED WITH WARNINGS     B\nInstalling [C]\n"
                 "NOT INSTALLED DUE TO ERRORS C\n")
    assert r.debug_verdicts(text) == {("setup-mod.tp2", 3): (r.OK, "A"),
                                      ("setup-mod.tp2", 10): (r.WARNINGS, "B"),
                                      ("setup-mod.tp2", 20): (r.ERRORS, "C")}


def test_a_run_cut_short_has_no_verdict_for_its_last_component():
    text = block("m/m.tp2", "0 1", "Installing [A]\nSUCCESSFULLY INSTALLED      A\n"
                                   "Installing [B]\n")
    assert r.debug_verdicts(text) == {("m.tp2", 0): (r.OK, "A")}


def test_a_verdict_out_of_step_with_its_installing_line_is_not_guessed():
    text = block("m/m.tp2", "0", "Installing [A]\nSUCCESSFULLY INSTALLED      Other\n")
    assert r.debug_verdicts(text) == {}


def test_the_log_decides_and_the_debug_file_says_why():
    planned = [("good.tp2", 0), ("good.tp2", 1), ("bad.tp2", 0), ("bad.tp2", 1)]
    after = LOG + "~BAD/BAD.TP2~ #0 #0 // Fine\n"
    found = {res.key: res for res in r.results(planned, "", after, DEBUG)}
    assert found[("good.tp2", 0)].status == r.OK and found[("good.tp2", 0)].name == "One"
    assert found[("good.tp2", 1)].status == r.WARNINGS
    # in the log, no word in the debug file: installed, said so
    assert found[("bad.tp2", 0)].status == r.OK
    assert "no word" in found[("bad.tp2", 0)].note
    assert found[("bad.tp2", 1)].status == r.ERRORS and found[("bad.tp2", 1)].note == ""


def test_where_the_two_disagree_the_log_wins():
    planned = [("good.tp2", 0), ("bad.tp2", 1)]
    # the debug file says One went in, the log does not list it
    found = r.results(planned, "", "~BAD/BAD.TP2~ #0 #1 // Broken\n", DEBUG)
    assert [(x.status, bool(x.note)) for x in found] == [(r.ERRORS, True), (r.OK, True)]
    assert "WeiDU.log does not list it" in found[0].note
    assert "debug file says it failed" in found[1].note


def test_not_reached_and_already_there():
    planned = [("good.tp2", 0), ("late.tp2", 5)]
    found = r.results(planned, LOG, LOG, "")
    assert [(x.status, x.note) for x in found] == [
        (r.OK, "already installed before this run"), (r.NOT_REACHED, "")]
    assert found[1].as_dict() == {"tp2": "late.tp2", "component": 5, "name": "",
                                  "status": r.NOT_REACHED, "note": ""}


def test_a_component_skipped_by_its_predicate_does_not_shift_the_others():
    """Review of #109, measured with the real WeiDU: a component whose
    REQUIRE_PREDICATE fails gets `SKIPPING: [Name]` and no verdict."""
    text = block("skip/skip.tp2", "0 1 2",
                 "Installing [First] [1]\nSKIPPING: [Middle]\nInstalling [Last] [1]\n"
                 "Saving This Log:\nSKIP/SKIP.TP2  0  0 Installed ~First~\n"
                 "SKIP/SKIP.TP2  0  2 Installed ~Last~\n\nSUCCESSFULLY INSTALLED      First\n"
                 "SUCCESSFULLY INSTALLED      Last\n")
    assert r.debug_verdicts(text) == {("skip.tp2", 0): (r.OK, "First"),
                                      ("skip.tp2", 2): (r.OK, "Last")}
    found = r.results([("skip.tp2", 0), ("skip.tp2", 1), ("skip.tp2", 2)], "",
                      "~SKIP/SKIP.TP2~ #0 #0 // First\n~SKIP/SKIP.TP2~ #0 #2 // Last\n", text)
    assert [(x.status, x.note) for x in found] == [(r.OK, ""), (r.NOT_REACHED, ""), (r.OK, "")]


def test_a_component_passed_over_without_a_word_keeps_only_exact_numbers():
    """The order cannot be trusted when WeiDU's saved lines contradict it:
    an install keeps its exact number, a failure is left to the log."""
    text = block("m/m.tp2", "0 1 2",
                 "Installing [B]\nInstalling [C]\nSaving This Log:\n"
                 "M/M.TP2  0  1 Installed ~B~\n\nSUCCESSFULLY INSTALLED      B\n"
                 "NOT INSTALLED DUE TO ERRORS C\n")
    assert r.debug_verdicts(text) == {("m.tp2", 1): (r.OK, "B")}
