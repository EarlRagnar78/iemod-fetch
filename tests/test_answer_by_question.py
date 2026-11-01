"""
A question recognised by its expected text and answered by its key (ADR-0049,
item 48): prompts.match_question over mod_installer's window, and Answers
kept in step when an answer is taken by question.
"""
from iemod_fetch.prompts import Answers, match_question

A, B = ("setup-a.tp2", 0), ("setup-a.tp2", 10)
WINDOW = ("[weidu] WeiDU version 25100\nInstalling [A] [v1]\nCopying 1 file ...\n"
          "Which portraits do you want?\n  1 - old\n  2 - new\nChoose 1 or 2 for portraits:")


def test_the_question_that_ends_the_window_is_found():
    expected = [(A, "@1", "Choose 1 or 2 for portraits:"),
                (A, "@2", "Which portraits do you want?"),
                (B, "@3", "Enter a percentage between 0 and 100:")]
    assert match_question(WINDOW, expected) == (A, "@1")
    # an earlier line of the window is not the question being asked
    assert match_question(WINDOW, expected[1:]) is None


def test_white_space_and_a_variable_are_read_as_weidu_prints_them():
    text = "Detected BG:EE directory as %bgee_dir%. Is this correct? [Y]es  [N]o"
    window = "Detected BG:EE directory as C:\\Games\\BGEE.\nIs this correct? [Y]es [N]o"
    assert match_question(window, [(A, "@9", text)]) == (A, "@9")


def test_a_short_text_says_too_little_to_be_recognised():
    assert match_question("Continue? y/n", [(A, "@1", "y/n")]) is None
    assert match_question("Continue? %x%", [(A, "@1", "%answer%")]) is None


def test_the_longer_of_two_matching_texts_wins_and_a_tie_is_no_answer():
    window = "Do you want to install the portraits now? (y/n)"
    assert match_question(window, [(A, "@1", "install the portraits now? (y/n)"),
                                   (A, "@2", "Do you want to install the portraits now? (y/n)")]) \
        == (A, "@2")
    # the same text asked by two components: which one is not known
    assert match_question(window, [(A, "@2", "Do you want to install the portraits now? (y/n)"),
                                   (B, "@7", "Do you want to install the portraits now? (y/n)")]) \
        is None


def test_an_answer_taken_by_question_leaves_the_rest_in_step():
    answers = Answers({A: ["1", "2"], B: ["30"]}, {A: ["@1", "@2"], B: ["@3"]})
    answers.start((A, B))
    assert answers.take(A, "@2") == "2"            # asked first: by its key
    assert answers.next() == "1" and answers.next() == "30" and answers.next() is None
    answers.start((A, B))
    assert answers.take(B, "@9") is None           # none recorded for it


def test_without_keys_the_answers_go_in_order_as_before():
    answers = Answers({A: ["1", "2"]})
    answers.start((A,))
    assert answers.take(A, "@1") is None and answers.next() == "1"


def test_a_trailing_variable_or_a_word_part_is_never_matched():
    """Review of #111: a text ending in a %variable% would swallow every line
    after it; a variable stays on its line; the text starts a word."""
    assert match_question("The game was detected in /x.\nInstalling\nWhich kit? Choose 1-3:",
                          [(A, "@1", "The game was detected in %dir%")]) is None
    assert match_question("Use the kit Fighter now?\nInstall Y? [y/n]",
                          [(A, "@1", "Use the kit %kit% Y? [y/n]")]) is None
    assert match_question("Reinstall the portraits now? (y/n)",
                          [(A, "@1", "install the portraits now? (y/n)")]) is None


def test_what_mod_installer_puts_to_anyone():
    from iemod_fetch.prompts import mod_installer_asks, recognisable
    assert mod_installer_asks("Please enter a number between 1 and 5:")
    assert mod_installer_asks("Do you want the new portraits?")
    assert not mod_installer_asks("How many extra kits should be installed?")
    assert not recognisable("Install to %dir%") and recognisable("Please enter a number:")


def test_a_question_after_a_quote_or_a_bracket_is_found():
    """Second review of #111: the text starts a word, not only after white space."""
    assert match_question('"Please enter a number between 1 and 5:',
                          [(A, "@1", "Please enter a number between 1 and 5:")]) == (A, "@1")
