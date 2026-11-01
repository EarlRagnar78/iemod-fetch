"""ADR-0057: mod_installer's parser config for one install."""
import os
import sys
import tomllib
from pathlib import Path

import pytest

from iemod_fetch import mi_parser

# What the real mod_installer 16.0.0 writes as its defaults (built from the
# release's source, run once with an empty XDG_CONFIG_HOME)
REFERENCE = Path(__file__).parent / "data" / "mod_installer-16.0.0-parser.toml"


def test_the_defaults_are_mod_installers_own():
    ours = tomllib.loads(mi_parser.toml([]))
    real = tomllib.loads(REFERENCE.read_text())
    assert ours.keys() == real.keys()
    for key in real:
        if key != "metadata":
            assert ours[key] == real[key], key
    assert ours["metadata"]["mod_installer_version"] == "16.0.0"
    assert ours["metadata"]["created"].keys() == real["metadata"]["created"].keys()


def test_extra_phrases_are_added_once_and_sorted():
    data = tomllib.loads(mi_parser.toml(["zz top question", "do you want"]))
    real = tomllib.loads(REFERENCE.read_text())
    assert data["choice_phrase"] == sorted({*real["choice_phrase"], "zz top question"})


@pytest.mark.parametrize(("text", "phrase"), [
    ("How many extra kits should be installed?", "how many extra kits should be installed?"),
    # the last line is the one WeiDU prints just before it reads
    ("Kits\nHow many extra kits should be added?", "how many extra kits should be added?"),
    # a variable: the longest literal piece of the line
    ("Type the number for %name% kit portraits", "type the number for"),
    ("Pick your kit now: 1, 2 or 3", "pick your kit now: 1, 2 or 3"),
    ("Pick a kit: 1, 2 or 3", None),                      # 10 letters only
    # a rule or a heading is never the phrase while a later line says more
    ("*" * 40 + "\nHow many extra kits should be installed?",
     "how many extra kits should be installed?"),
    ("-" * 50 + "\nKit count?  1) one", None),
    ("Kits for the paladin class\n" + "=" * 30, "kits for the paladin class"),
    ("Do you want the new portraits?", None),             # asked already
    ("Installing the extra kits, how many?", None),       # a progress word: never a question
    ("Short one?", None),                                 # too short to tell apart
    ("%a% and %b%", None),
    ("", None),
    # as WeiDU prints it (review of #120): two lines, two spaces, a tab - the
    # phrase is one line's text, its spaces as they are
    ("Kits menu\nHow many extra  kits should be installed?",
     "how many extra  kits should be installed?"),
    ("Kits\r\n\tHow many kits\tshould be added?", "how many kits\tshould be added?"),
    # ASCII only: a line in another charset never reaches mod_installer's check
    ("Combien de kits voulez-vous installer\u00a0?", "combien de kits voulez-vous installer"),
    ("Écrivez le nombre de kits voulus", "crivez le nombre de kits voulus"),
])
def test_the_phrase_of_a_question(text, phrase):
    assert mi_parser.phrase(text) == phrase


def test_a_choice_word_on_any_line_is_asked_already():
    assert mi_parser.asked("Please enter the number\nof kits wanted here")
    assert mi_parser.phrase("Please enter the number\nof kits wanted here") is None
    # any line starts the question: the last line that says enough
    assert mi_parser.phrase("Should the tool convert the BG1 unique items?\n 1. No\n 2. Yes") \
        == "should the tool convert the bg1 unique items?"
    assert mi_parser.phrase("Convert the BG1 items?\n 1. No (skips usually unneeded changes)\n"
                            " 2. Yes") == "1. no (skips usually unneeded changes)"
    assert not mi_parser.asked("How many extra kits should be installed?", [])
    assert mi_parser.asked("How many extra kits should be installed?")


def test_phrases_of_an_install():
    texts = ["How many extra kits should be installed?", "Do you want it?",
             "How many extra kits should be installed?", ""]
    assert mi_parser.phrases(texts) == ["how many extra kits should be installed?"]


def test_toml_strings_are_escaped():
    data = tomllib.loads(mi_parser.toml(['say "yes" \\ now\tplease']))
    assert 'say "yes" \\ now\tplease' in data["choice_phrase"]


@pytest.mark.parametrize(("platform", "variable", "parts"), [
    ("linux", "XDG_CONFIG_HOME", ("mod_installer", "parser.toml")),
    ("darwin", "XDG_CONFIG_HOME", ("mod_installer", "parser.toml")),
    ("win32", "APPDATA", ("mod_installer", "config", "parser.toml")),
])
def test_where_mod_installer_looks(tmp_path, platform, variable, parts):
    env, extra = mi_parser.write(str(tmp_path), ["How many extra kits?? ok"], platform=platform)
    assert env == {variable: str(tmp_path)}
    path = tmp_path.joinpath(*parts)
    assert path.is_file()
    assert tomllib.loads(path.read_text())["metadata"]["mod_installer_version"] == "16.0.0"
    assert extra == ["how many extra kits?? ok"]


def test_the_install_points_mod_installer_at_its_own_config(tmp_path, monkeypatch):
    """The variable is set only in the child's environment, to a folder
    beside the plan - never the player's own."""
    from iemod_fetch import install_run
    from iemod_fetch.install_run import InstallRun
    monkeypatch.setattr(install_run, "version_of", lambda _program, _dir: "16.0.0")
    variable = "APPDATA" if sys.platform == "win32" else "XDG_CONFIG_HOME"
    monkeypatch.setenv(variable, str(tmp_path / "players-own"))
    code = f"import os; print(os.environ['{variable}'])"
    lines = []
    run = InstallRun([sys.executable, "-c", code], [], cwd=str(tmp_path), ask=lambda q, b: None,
                     on_event=lambda e: lines.append(e.text),
                     parser_dir=str(tmp_path / "plan" / "mod_installer-config"),
                     expected={("a.tp2", 0): [("q", "How many extra kits should be installed?")]},
                     raw_texts={(("a.tp2", 0), "q"): "Kits\nHow many extra kits should be installed?"})
    assert run.run().returncode == 0
    assert str(tmp_path / "plan" / "mod_installer-config") in lines
    assert run.parser_phrases == ["how many extra kits should be installed?"]
    assert os.environ[variable] == str(tmp_path / "players-own")
    assert not (tmp_path / "players-own").exists()


def test_another_mod_installer_gets_no_config(tmp_path, monkeypatch):
    """A version other than the one whose defaults the file carries would
    write its own over it: nothing is written, nothing counted as added."""
    from iemod_fetch import install_run
    from iemod_fetch.install_run import InstallRun
    monkeypatch.setattr(install_run, "version_of", lambda _program, _dir: "15.0.0")
    run = InstallRun([sys.executable, "-c", "pass"], [], cwd=str(tmp_path), ask=lambda q, b: None,
                     parser_dir=str(tmp_path / "cfg"),
                     raw_texts={(("a.tp2", 0), "q"): "How many extra kits should be installed?"})
    assert run.run().returncode == 0
    assert run.parser_phrases == [] and not (tmp_path / "cfg").exists()


def _program(tmp_path, body):
    script = tmp_path / "mi.py"
    script.write_text(body)
    program = tmp_path / ("mi.cmd" if sys.platform == "win32" else "mi")
    if sys.platform == "win32":
        program.write_text(f'@"{sys.executable}" "{script}" %*\r\n')
    else:
        program.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        program.chmod(0o755)
    return str(program)


# what mod_installer does before it reads --version: its parser config
SAYS_VERSION = """import os, sys
var = "APPDATA" if sys.platform == "win32" else "XDG_CONFIG_HOME"
open(os.path.join(os.environ[var], "touched"), "w").close()
print("mod_installer 16.0.0")
"""


def test_the_version_mod_installer_says_never_touches_the_players_config(tmp_path, monkeypatch):
    """Review of #120: mod_installer writes its parser config before it reads
    --version - the install's folder, or a scratch one, is what it gets."""
    from iemod_fetch import toolchain
    from iemod_fetch.install_run import version_of
    own = tmp_path / "players-own"
    own.mkdir()
    variable = "APPDATA" if sys.platform == "win32" else "XDG_CONFIG_HOME"
    monkeypatch.setenv(variable, str(own))
    program = _program(tmp_path, SAYS_VERSION)
    assert version_of(str(tmp_path / "missing"), str(tmp_path / "cfg")) == ""
    (tmp_path / "cfg").mkdir()
    assert version_of(program, str(tmp_path / "cfg")) == "16.0.0"
    assert (tmp_path / "cfg" / "touched").exists()
    assert toolchain.version_of(toolchain.MOD_INSTALLER, program) == "16.0.0"
    assert not (own / "touched").exists()
