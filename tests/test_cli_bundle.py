"""
packaging/cli_bundle.py (GUI-AUDIT item 36, ADR-0043): the command line as a
program that needs no Python, for the systems whose Python is older than the
one 4.0.0 needs. The helpers that do not need PyInstaller: the zip's name, the
licence files, and the check run on the unzipped program.
"""
import importlib.util
import os
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = importlib.util.spec_from_file_location(
    "cli_bundle", os.path.join(ROOT, "packaging", "cli_bundle.py"))
assert SPEC and SPEC.loader
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)

VERSIONS = {"pyinstaller": "6.22.3", "python": "3.14.6"}


def test_the_zip_is_named_apart_from_the_wizards(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.shared, "tag", lambda: "windows-x86_64")
    folder = tmp_path / "out" / cli.NAME
    folder.mkdir(parents=True)
    (folder / "iemod-fetch.exe").write_bytes(b"MZ")
    path = cli.shared.pack(str(folder), str(tmp_path / "dist"), cli.ZIP)
    assert os.path.basename(path) == "iemod-fetch-cli-windows-x86_64.zip"
    with zipfile.ZipFile(path) as zf:
        assert zf.namelist() == ["iemod-fetch/iemod-fetch.exe"]


def test_the_folder_carries_the_licences_and_no_qt_notice(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "versions", lambda: VERSIONS)
    folder = tmp_path / cli.NAME
    folder.mkdir()
    cli.add_licences(str(folder))
    assert (folder / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")
    assert sorted(os.listdir(folder / "licenses")) == ["Python-LICENSE.txt",
                                                       "filelock-LICENSE",
                                                       "publicsuffixlist-LICENSE"]
    assert "PSF" in (folder / "licenses" / "Python-LICENSE.txt").read_text(encoding="utf-8")
    assert (folder / "NOTICE-publicsuffixlist.txt").exists()      # MPL-2.0's source offer
    notice = (folder / "NOTICE.txt").read_text(encoding="utf-8")
    assert "Python 3.14.6" in notice and "PyInstaller 6.22.3" in notice
    assert not (folder / "NOTICE-Qt.txt").exists()
    assert not any("GPL" in name for name in os.listdir(folder / "licenses"))


def test_the_names_inside_the_zip_do_not_shadow_its_name(tmp_path, monkeypatch):
    """pack() names the zip before it walks the folder (review of #70)."""
    monkeypatch.setattr(cli.shared, "tag", lambda: "linux-x86_64")
    folder = tmp_path / "out" / cli.NAME
    (folder / "_internal").mkdir(parents=True)
    (folder / "_internal" / "lib.so").write_bytes(b"x")
    path = cli.shared.pack(str(folder), str(tmp_path / "dist"), cli.ZIP)
    assert os.path.basename(path) == "iemod-fetch-cli-linux-x86_64.zip"


def test_the_wizard_and_qt_are_left_out():
    assert {"PySide6", "shiboken6", "iemod_fetch_gui"} <= set(cli.EXCLUDE)


def fake_program(folder, script):
    """A stand-in for the built program: a script the check can run."""
    folder.mkdir(parents=True)
    path = folder / (cli.NAME + (".exe" if os.name == "nt" else ""))
    if os.name == "nt":
        pytest.skip("a script cannot stand in for an .exe")
    path.write_text(f"#!{sys.executable}\n{script}", encoding="utf-8")
    path.chmod(0o755)


def test_the_check_runs_the_version_and_the_help(tmp_path):
    fake_program(tmp_path / "p", "import sys\n"
                 "print('iemod-fetch 4.0.0' if '--version' in sys.argv else 'usage: x')\n")
    cli.check(str(tmp_path / "p"), str(tmp_path))


def test_a_program_that_does_not_start_stops_the_build(tmp_path):
    fake_program(tmp_path / "p", "import sys\nsys.exit('ModuleNotFoundError: filelock')\n")
    with pytest.raises(SystemExit, match="does not run --version"):
        cli.check(str(tmp_path / "p"), str(tmp_path))


def elf(path, needs):
    path.write_bytes(b"\x7fELF" + b"\0" * 60 + b"".join(b"GLIBC_2.%d\0" % n for n in needs))


def test_the_newest_glibc_any_bundled_file_needs_is_found(tmp_path):
    (tmp_path / "_internal").mkdir()
    elf(tmp_path / cli.NAME, [2, 17])
    elf(tmp_path / "_internal" / "libpython3.14.so.1.0", [3, 34, 38])
    (tmp_path / "_internal" / "notes.txt").write_bytes(b"GLIBC_2.99\0")   # not ELF
    assert cli.glibc_needed(str(tmp_path)) == (2, 38)


def test_a_linux_bundle_that_would_not_start_on_debian_trixie_stops_the_build(tmp_path):
    """Debian trixie, the floor, has glibc 2.41 (ADR-0043 amendment of
    2026-10-31): a bundle needing more would not start there. Built on
    ubuntu-24.04, setup-python's 3.14 needs 2.38, which passes."""
    elf(tmp_path / cli.NAME, [2, 42])
    with pytest.raises(SystemExit, match="glibc 2.42"):
        cli.check_glibc(str(tmp_path))
    elf(tmp_path / cli.NAME, [2, 17, 38, 41])
    cli.check_glibc(str(tmp_path))
    # packed relative relocations need 2.36 with no GLIBC_2.36 in sight -
    # which trixie has; below it the bundle stops
    (tmp_path / cli.NAME).write_bytes(b"\x7fELF" + b"\0" * 60 + b"GLIBC_2.17\0GLIBC_ABI_DT_RELR\0")
    assert cli.glibc_needed(str(tmp_path)) == (2, 36)
    cli.check_glibc(str(tmp_path))
    with pytest.raises(SystemExit, match="glibc 2.36"):
        cli.check_glibc(str(tmp_path), limit=(2, 35))
    assert cli.MAX_GLIBC == (2, 41)
