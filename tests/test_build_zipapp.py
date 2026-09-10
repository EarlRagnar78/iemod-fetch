"""The single-file deployment artefact must actually run."""
import os
import subprocess
import sys
import time

import pytest

import build

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def pyz(tmp_path_factory):
    target = str(tmp_path_factory.mktemp("dist") / "iemod-fetch.pyz")
    return build.build(target)


def run(pyz, *args, cwd=None):
    return subprocess.run([sys.executable, pyz, *args], stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=120, check=False,
                          cwd=cwd)


def test_the_archive_reports_its_version(pyz):
    proc = run(pyz, "--version")
    assert proc.returncode == 0
    assert "iemod-fetch" in proc.stdout.decode()


def test_the_archive_shows_help(pyz):
    proc = run(pyz, "--help")
    assert proc.returncode == 0
    assert b"--emit-pinned-manifest" in proc.stdout


def test_the_archive_validates_input_and_exits_2_on_config_error(pyz, tmp_path):
    (tmp_path / "mod_downloads.json").write_text('{"mods":[]}')
    proc = run(pyz, "-m", "mod_downloads.json", "-t", "Mods", cwd=str(tmp_path))
    assert proc.returncode == 2
    assert b"empty" in proc.stdout


def test_the_archive_carries_no_bytecode_or_caches(pyz):
    import zipfile
    with zipfile.ZipFile(pyz) as zf:
        names = zf.namelist()
    assert "__main__.py" in names
    assert any(n.startswith("iemod_fetch/") for n in names)
    assert not [n for n in names if "__pycache__" in n or n.endswith(".pyc")]


# ------------------------------------------------- reproducibility (ADR-0019)
def test_two_builds_of_one_source_tree_are_byte_identical(tmp_path):
    """
    The .pyz is what people download. If two builds of one commit differ, nobody
    can check that the artifact matches the source, and every signature and
    attestation downstream of it means less.

    zipapp writes each member's mtime into the archive, so this failed until
    build.py normalised the staged timestamps to SOURCE_DATE_EPOCH.
    """
    build_module = build

    first = tmp_path / "first.pyz"
    second = tmp_path / "second.pyz"
    build_module.build(str(first))
    time.sleep(1.1)                     # a different wall clock for the second
    build_module.build(str(second))

    assert first.read_bytes() == second.read_bytes()


def test_source_date_epoch_is_honoured(tmp_path, monkeypatch):
    """An explicit SOURCE_DATE_EPOCH changes the archive; a repeat does not."""
    build_module = build

    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    pinned = tmp_path / "pinned.pyz"
    build_module.build(str(pinned))

    monkeypatch.delenv("SOURCE_DATE_EPOCH")
    default = tmp_path / "default.pyz"
    build_module.build(str(default))

    assert pinned.read_bytes() != default.read_bytes()


def test_a_pre_1980_source_date_epoch_is_clamped(monkeypatch):
    """The zip format cannot store a timestamp before 1980; refusing is worse."""
    build_module = build

    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
    assert build_module._source_date_epoch() == build_module.DEFAULT_SOURCE_DATE_EPOCH


def test_a_malformed_source_date_epoch_fails_loudly(monkeypatch):
    build_module = build

    monkeypatch.setenv("SOURCE_DATE_EPOCH", "yesterday")
    with pytest.raises(SystemExit) as excinfo:
        build_module._source_date_epoch()
    assert "SOURCE_DATE_EPOCH" in str(excinfo.value)
