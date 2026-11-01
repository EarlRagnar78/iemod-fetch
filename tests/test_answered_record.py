"""
What an install answered is recorded, never read back (GUI-AUDIT M8 item 63).
From mod_installer's window - WeiDU's last 10 lines with each question - which
answers a question takes cannot be told: four reviews of #98 found every rule
on its text refusing right answers of real mods (Tweaks Anthology #3210 takes
0 outside its "between 6 and 15"). Recorded answers go in order, as before.
"""
from iemod_fetch.prompts import question_line

WINDOW = ("[weidu] WeiDU version 25100\n    \n    Installing [Restorations] [v30]\n"
          "    Restore the tavern? [y]es or [n]o\n    \n    Copying 1 file ...\n    {}")


def test_the_last_line_is_what_is_recorded_as_asked():
    assert question_line(WINDOW.format("Please select 1 or 2")) == "Please select 1 or 2"
    assert question_line("") == "" and question_line("  \n  ") == ""
