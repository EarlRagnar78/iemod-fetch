"""Name safety and STRICT tp2 identity - the fix for legacy defects L1/L3/L4."""
import os

import pytest

from iemod_fetch.errors import UnsafeName
from iemod_fetch.naming import (archive_filename, is_safe_component, matches_tp2,
                                normalize_key, safe_component)

DATA = os.path.join(os.path.dirname(__file__), "data")


@pytest.mark.parametrize("name", [
    "..", ".", "../victim", "..\\victim", "/etc/passwd", "C:\\Windows",
    "a/b", "a\\b", "with\x00nul", "", "   ", "trailing ", "trailing.",
    "CON", "nul.tp2", "LPT1", "-leading-dash-ok?no",
])
def test_unsafe_components_are_rejected(name):
    with pytest.raises(UnsafeName):
        safe_component(name)


@pytest.mark.parametrize("name", [
    "DlcMerger", "eefixpack", "c#endlessbg1", "JA#BGT_AdvPack", "A7#ImprovedArcher",
    "l#coi-yvette", "bp_in_bg", "EET_end", "BG1UB", "The Calling",
])
def test_real_corpus_names_are_accepted(name):
    assert safe_component(name) == name


def test_traversal_cannot_reach_outside_a_root():
    """The property that makes legacy defect L4 impossible."""
    root = "/srv/game/Mods"
    for evil in ("../victim", "..", "a/../../b"):
        assert not is_safe_component(evil)
    joined = os.path.join(root, safe_component("DlcMerger"))
    assert os.path.dirname(joined) == root           # one level down, whatever os.sep is


# ----------------------------------------------------------- strict matching
@pytest.mark.parametrize("filename,folder", [
    ("DlcMerger.tp2", "DlcMerger"),
    ("SETUP-EEFIXPACK.TP2", "eefixpack"),
    ("BG1UB.TP2", "bg1ub"),
    ("setup-margarita.tp2", "Margarita"),
    ("c#endlessbg1.tp2", "c#endlessbg1"),
])
def test_matches_the_two_legal_weidu_spellings(filename, folder):
    assert matches_tp2(filename, folder)


@pytest.mark.parametrize("filename,folder", [
    ("some-other-mod.tp2", "eefixpack"),      # legacy L1
    ("bg1ub.tp2", "ub"),                      # legacy L3: substring must NOT match
    ("bg1ub.tp2", "bg1"),
    ("setup-bg1npc.tp2", "bg1"),
    ("readme.txt", "bg1ub"),
    ("bg1ub.tp2", ""),
])
def test_rejects_everything_that_is_not_this_mod(filename, folder):
    assert not matches_tp2(filename, folder)


def test_normalize_key_folds_case_and_punctuation():
    assert normalize_key("C#SB_SILBER") == normalize_key("c#sb_silber") == "csbsilber"


def test_strict_matcher_accepts_every_pair_in_the_real_weidu_logs():
    """
    Evidence that strictness costs nothing: across all 796 component lines of
    the supplied logs, the strict rule identifies 100% of real mods.
    """
    from iemod_fetch.weidu import parse_weidu_files
    parsed = parse_weidu_files([os.path.join(DATA, "WeiDU.log"),
                                os.path.join(DATA, "WeiDUBGEE.log")])
    assert len(parsed.mods) == 148
    unmatched = [(m.folder, m.tp2_file) for m in parsed.mods.values()
                 if not matches_tp2(m.tp2_file, m.folder)]
    assert unmatched == []


# ------------------------------------------------- server-supplied filenames
# The archive name comes from a Content-Disposition header or a URL path: remote
# input. posixpath.basename does not split on backslashes, so on Windows
# '..\\..\\evil.zip' or 'C:\\x.zip' joined onto the work directory escaped it.
@pytest.mark.parametrize("remote,expected", [
    ("EET-13.4.zip", "EET-13.4.zip"),
    (r"..\..\evil.zip", "evil.zip"),
    ("../../evil.zip", "evil.zip"),
    (r"C:\Windows\x.zip", "x.zip"),
    ("C:x.zip", "fallback.bin"),
    ("feature/x.zip", "x.zip"),
    ("..", "fallback.bin"),
    ("", "fallback.bin"),
    (None, "fallback.bin"),
    ("NUL.zip", "fallback.bin"),
    ("x" * 300 + ".zip", "fallback.bin"),
])
def test_a_remote_archive_name_becomes_one_safe_component(remote, expected):
    assert archive_filename(remote, "fallback.bin") == expected


def test_a_remote_archive_name_never_leaves_the_work_directory(tmp_path):
    for remote in (r"..\..\evil.zip", "/etc/passwd", r"\\server\share\x.zip"):
        joined = os.path.join(str(tmp_path), archive_filename(remote, "f.bin"))
        assert os.path.dirname(os.path.abspath(joined)) == str(tmp_path)
