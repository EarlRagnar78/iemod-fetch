"""Staged, non-destructive installation - the fix for legacy defects L1, L2, L4."""
import os
import zipfile

import pytest

from iemod_fetch.errors import InstallConflict, UnsafeName, VerificationFailed
from iemod_fetch.install import (State, install_from_archive, locate_mod_root,
                                 verify_mod_dir)


def mod_zip(path, folder="DlcMerger", tp2=None, extra=()):
    tp2 = tp2 or f"{folder}/{folder}.tp2"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(tp2, "BACKUP ~x~")
        for name, data in extra:
            zf.writestr(name, data)
    return str(path)


# ------------------------------------------------------------- verification
def test_unrelated_tp2_does_not_verify_a_mod_directory(tmp_path):
    """Legacy defect L1: this returned True."""
    d = tmp_path / "eefixpack"
    d.mkdir()
    (d / "some-other-mod.tp2").write_text("x")
    assert verify_mod_dir(str(d), "eefixpack") is None


def test_correct_tp2_verifies(tmp_path):
    d = tmp_path / "eefixpack"
    d.mkdir()
    (d / "SETUP-EEFIXPACK.TP2").write_text("x")
    assert verify_mod_dir(str(d), "eefixpack") == "SETUP-EEFIXPACK.TP2"


# ----------------------------------------------------------------- install
def test_installs_into_the_folder_weidu_expects(tmp_path):
    target = tmp_path / "Mods"
    arc = mod_zip(tmp_path / "m.zip", "DlcMerger",
                  extra=[("DlcMerger/readme.txt", "hi")])
    outcome = install_from_archive(arc, str(target), "DlcMerger")
    assert outcome.dest == str(target / "DlcMerger")
    assert (target / "DlcMerger" / "DlcMerger.tp2").exists()
    assert (target / "DlcMerger" / "readme.txt").exists()
    assert not (target / ".staging").exists()


def test_install_folder_name_comes_from_weidu_not_the_manifest_key(tmp_path):
    """
    Real case: WeiDU folder 'HiddenGameplayOptions', manifest key
    'a7-hiddengameplayoptions'. Installing under the manifest key would produce
    a directory WeiDU cannot use.
    """
    target = tmp_path / "Mods"
    arc = mod_zip(tmp_path / "m.zip", "HiddenGameplayOptions")
    install_from_archive(arc, str(target), "HiddenGameplayOptions")
    assert (target / "HiddenGameplayOptions" / "HiddenGameplayOptions.tp2").exists()
    assert not (target / "a7-hiddengameplayoptions").exists()


def test_archive_for_the_wrong_mod_is_rejected(tmp_path):
    target = tmp_path / "Mods"
    arc = mod_zip(tmp_path / "m.zip", "SomeOtherMod")
    with pytest.raises(VerificationFailed, match="none of them"):
        install_from_archive(arc, str(target), "DlcMerger")
    assert not (target / "DlcMerger").exists()


def test_archive_with_no_tp2_at_all_is_rejected(tmp_path):
    arc = tmp_path / "m.zip"
    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("docs/readme.txt", "nothing here")
    with pytest.raises(VerificationFailed, match="no .tp2"):
        install_from_archive(str(arc), str(tmp_path / "Mods"), "DlcMerger")


def test_traversal_in_the_folder_name_is_refused(tmp_path):
    arc = mod_zip(tmp_path / "m.zip", "x")
    with pytest.raises(UnsafeName):
        install_from_archive(arc, str(tmp_path / "Mods"), "../victim")


# ------------------------------------------------------------ data safety
def test_existing_directory_is_never_touched_without_force(tmp_path):
    """Legacy defect L4: the error path rmtree'd the destination."""
    target = tmp_path / "Mods"
    existing = target / "DlcMerger"
    existing.mkdir(parents=True)
    (existing / "DlcMerger.tp2").write_text("BACKUP ~x~")
    (existing / "my-hand-edits.txt").write_text("irreplaceable")

    arc = mod_zip(tmp_path / "m.zip", "DlcMerger")
    with pytest.raises(InstallConflict, match="--force"):
        install_from_archive(arc, str(target), "DlcMerger")

    assert (existing / "my-hand-edits.txt").read_text() == "irreplaceable"


def test_force_moves_the_old_directory_aside_rather_than_deleting_it(tmp_path):
    target = tmp_path / "Mods"
    existing = target / "DlcMerger"
    existing.mkdir(parents=True)
    (existing / "my-hand-edits.txt").write_text("irreplaceable")

    arc = mod_zip(tmp_path / "m.zip", "DlcMerger")
    outcome = install_from_archive(arc, str(target), "DlcMerger", force=True)

    assert outcome.backup and os.path.isdir(outcome.backup)
    assert os.path.exists(os.path.join(outcome.backup, "my-hand-edits.txt"))
    assert (target / "DlcMerger" / "DlcMerger.tp2").exists()


def test_a_failed_install_leaves_no_debris(tmp_path):
    target = tmp_path / "Mods"
    target.mkdir()
    arc = mod_zip(tmp_path / "m.zip", "WrongMod")
    with pytest.raises(VerificationFailed):
        install_from_archive(arc, str(target), "DlcMerger")
    assert sorted(os.listdir(target)) == []


# -------------------------------------------------------------------- state
def test_state_round_trips(tmp_path):
    state = State.load(str(tmp_path))
    state.record("DlcMerger", sha256="ab" * 32, version="v1.2", tp2_file="DlcMerger.tp2")
    state.save()
    assert State.load(str(tmp_path)).get("dlcmerger")["version"] == "v1.2"


def test_corrupt_state_file_does_not_crash_the_run(tmp_path):
    (tmp_path / ".iemod-fetch-state.json").write_text("{not json")
    assert State.load(str(tmp_path)).mods == {}


def test_locate_mod_root_finds_a_nested_wrapper_directory(tmp_path):
    staging = tmp_path / "s"
    inner = staging / "Mod-v1.2-release" / "DlcMerger"
    inner.mkdir(parents=True)
    (inner / "DlcMerger.tp2").write_text("x")
    root, tp2, matched = locate_mod_root(str(staging), "DlcMerger")
    assert root == str(inner) and tp2 == "DlcMerger.tp2" and matched == "DlcMerger"


# ============ archives whose tp2 differs from the WeiDU folder (real cases) ============
def test_a_renamed_mod_is_refused_without_an_override(tmp_path):
    """`Reflections` in the log, `Reflections_of_Destiny.tp2` in the archive."""
    arc = mod_zip(tmp_path / "m.zip", "Reflections_of_Destiny")
    with pytest.raises(VerificationFailed, match="expect_tp2"):
        install_from_archive(arc, str(tmp_path / "Mods"), "Reflections")


def test_expect_tp2_accepts_the_renamed_mod(tmp_path):
    target = tmp_path / "Mods"
    arc = mod_zip(tmp_path / "m.zip", "Reflections_of_Destiny")
    outcome = install_from_archive(arc, str(target), "Reflections",
                                   expect_tp2="Reflections_of_Destiny")
    # WeiDU needs the directory to match the tp2 the mod ships, so the archive's
    # own name wins over the stale log entry - and the change is reported.
    assert outcome.folder == "Reflections_of_Destiny"
    assert outcome.renamed_from == "Reflections"
    assert (target / "Reflections_of_Destiny" / "Reflections_of_Destiny.tp2").exists()
    assert not (target / "Reflections").exists()


def test_expect_tp2_still_refuses_an_unrelated_archive(tmp_path):
    """The override widens the accepted set by one name, not to anything."""
    arc = mod_zip(tmp_path / "m.zip", "SomethingElse")
    with pytest.raises(VerificationFailed):
        install_from_archive(arc, str(tmp_path / "Mods"), "Reflections",
                             expect_tp2="Reflections_of_Destiny")


def test_the_folder_name_still_wins_when_the_archive_matches_it(tmp_path):
    target = tmp_path / "Mods"
    arc = mod_zip(tmp_path / "m.zip", "DlcMerger")
    outcome = install_from_archive(arc, str(target), "DlcMerger",
                                   expect_tp2="SomethingElse")
    assert outcome.folder == "DlcMerger" and outcome.renamed_from is None


def test_verify_mod_dir_accepts_the_expected_tp2(tmp_path):
    d = tmp_path / "Reflections_of_Destiny"
    d.mkdir()
    (d / "Reflections_of_Destiny.tp2").write_text("x")
    assert verify_mod_dir(str(d), "Reflections") is None
    assert verify_mod_dir(str(d), "Reflections",
                          expect_tp2="Reflections_of_Destiny") is not None


# ------------------------------------------------ the mod's own version, from its tp2
def test_the_installed_version_is_read_from_the_tp2(tmp_path):
    target = tmp_path / "Mods"
    arc = tmp_path / "m.zip"
    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("DlcMerger/DlcMerger.tp2",
                    "BACKUP ~x~\nVERSION ~v2.1.3~\n"
                    "REQUIRE_PREDICATE GAME_IS ~bgee eet~ @1\n")
    outcome = install_from_archive(str(arc), str(target), "DlcMerger")
    assert outcome.version == "v2.1.3"
    assert outcome.tp2_info.normalised_games == ["BGEE", "EET"]


def test_a_tp2_without_a_version_is_not_an_error(tmp_path):
    arc = mod_zip(tmp_path / "m.zip", "DlcMerger")
    outcome = install_from_archive(arc, str(tmp_path / "Mods"), "DlcMerger")
    assert outcome.version is None and outcome.tp2_info is not None
