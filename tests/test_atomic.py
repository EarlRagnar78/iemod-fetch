"""
iemod_fetch.atomic (GUI-AUDIT M7 item 46): a file is written whole or not at
all, through a temp of its own, and keeps the permissions it had.
"""
import os
import stat

import pytest

from iemod_fetch import atomic
from iemod_fetch.atomic import write_text


def leftovers(folder):
    return [n for n in os.listdir(folder) if n.endswith(".tmp")]


def test_a_new_file_is_written_whole(tmp_path):
    path = tmp_path / "sub" / "state.json"
    write_text(str(path), '{"a": 1}\n')
    assert path.read_text(encoding="utf-8") == '{"a": 1}\n'
    assert leftovers(path.parent) == []


def test_a_failed_write_leaves_the_old_file_and_no_temp(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text("old", encoding="utf-8")

    def broken(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(atomic.os, "replace", broken)
    with pytest.raises(OSError, match="disk full"):
        write_text(str(path), "new")
    assert path.read_text(encoding="utf-8") == "old"
    assert leftovers(tmp_path) == []


def test_each_write_has_its_own_temp(tmp_path, monkeypatch):
    """The old `path + ".tmp"` was one name for every writer of the file."""
    temps = []
    replace = os.replace
    monkeypatch.setattr(atomic.os, "replace",
                        lambda src, dst: (temps.append(src), replace(src, dst)))
    path = str(tmp_path / "state.json")
    (tmp_path / "state.json.tmp").write_text("a crash's leftover", encoding="utf-8")
    write_text(path, "one")
    write_text(path, "two")
    assert len(set(temps)) == 2 and path + ".tmp" not in temps
    assert (tmp_path / "state.json").read_text(encoding="utf-8") == "two"


def test_text_is_utf8(tmp_path):
    path = tmp_path / "c.ini"
    write_text(str(path), "C:/Giochi/Baldur’s Gate\n")
    assert path.read_bytes().decode("utf-8").startswith("C:/Giochi/Baldur’s")


@pytest.mark.skipif(os.name == "nt", reason="file modes are POSIX")
def test_permissions(tmp_path):
    kept = tmp_path / "kept.ini"
    kept.write_text("x", encoding="utf-8")
    os.chmod(kept, 0o700)
    write_text(str(kept), "y")
    assert stat.S_IMODE(os.stat(kept).st_mode) == 0o700       # its owner's choice

    new = tmp_path / "token.ini"
    write_text(str(new), "y")
    assert stat.S_IMODE(os.stat(new).st_mode) == 0o600        # owner only


def test_durable_flushes_the_file(tmp_path, monkeypatch):
    synced = []
    fsync = os.fsync
    monkeypatch.setattr(atomic.os, "fsync", lambda fd: (synced.append(fd), fsync(fd)))
    write_text(str(tmp_path / "a"), "x")
    assert synced == []
    write_text(str(tmp_path / "b"), "x", durable=True)
    assert len(synced) == (2 if os.name == "posix" else 1)    # the file, then its folder


@pytest.mark.skipif(os.name != "posix", reason="the folder is flushed on POSIX only")
def test_a_folder_that_cannot_be_flushed_does_not_fail_a_written_file(tmp_path, monkeypatch):
    """Review of #55: EINVAL from a network file system's folder came after the rename."""
    fsync = os.fsync

    def files_only(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(22, "Invalid argument")
        fsync(fd)
    monkeypatch.setattr(atomic.os, "fsync", files_only)
    write_text(str(tmp_path / "state.json"), "x", durable=True)
    assert (tmp_path / "state.json").read_text(encoding="utf-8") == "x"


def test_a_failed_write_removes_a_read_only_temp(tmp_path, monkeypatch):
    """Review of #55: Windows will not delete a read-only file, so the temp stayed."""
    path = tmp_path / "ro.json"
    path.write_text("old", encoding="utf-8")
    os.chmod(path, 0o400)
    removed = []
    unlink = os.unlink

    def strict(p):             # as Windows: a read-only file cannot be deleted
        if not os.stat(p).st_mode & stat.S_IWUSR:
            raise PermissionError(13, "Access is denied")
        removed.append(p)
        unlink(p)
    monkeypatch.setattr(atomic.os, "unlink", strict)
    monkeypatch.setattr(atomic.os, "replace", lambda s, d: (_ for _ in ()).throw(
        PermissionError(13, "Access is denied")))
    with pytest.raises(PermissionError):
        write_text(str(path), "new")
    assert removed and leftovers(tmp_path) == []
    os.chmod(path, 0o600)
