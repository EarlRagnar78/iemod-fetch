"""
A file held for a moment on Windows - an antivirus scanning what was just
written - is renamed once it is let go, not refused (GUI-AUDIT M8 item 66).
Retried 12 times, 10 ms doubling to 1 s (Chriz Easy BG's measure, the idea);
any other error, and every error off Windows, at once.
"""
import ast
import errno
import os
import pathlib

import pytest

from iemod_fetch import atomic

ROOT = pathlib.Path(__file__).resolve().parent.parent / "iemod_fetch"


def held(winerror):
    exc = PermissionError(errno.EACCES, "The process cannot access the file")
    exc.winerror = winerror
    return exc


class Flaky:
    """Fails `times` times with `error`, then works."""

    def __init__(self, times, error):
        self.times, self.error, self.calls = times, error, 0

    def __call__(self, *args):
        self.calls += 1
        if self.calls <= self.times:
            raise self.error
        return "done"


@pytest.mark.parametrize("winerror", [5, 32, 33])
def test_a_held_file_is_tried_again_until_it_is_let_go(winerror):
    waits = []
    flaky = Flaky(3, held(winerror))
    assert atomic.retried(flaky, windows=True, sleep=waits.append) == "done"
    assert flaky.calls == 4 and waits == [0.01, 0.02, 0.04]


def test_it_gives_up_after_twelve_tries_and_about_five_seconds():
    waits = []
    flaky = Flaky(99, held(32))
    with pytest.raises(PermissionError):
        atomic.retried(flaky, windows=True, sleep=waits.append)
    assert flaky.calls == 12 and len(waits) == 11
    assert waits[-1] == 1.0 and 5.0 < sum(waits) < 5.5


@pytest.mark.parametrize("error", [
    held(2),                                            # not a hold
    FileNotFoundError(errno.ENOENT, "gone"),
    OSError(errno.EXDEV, "cross-device"),
])
def test_any_other_error_is_raised_at_once(error):
    flaky = Flaky(1, error)
    with pytest.raises(type(error)):
        atomic.retried(flaky, windows=True, sleep=lambda _s: pytest.fail("waited"))
    assert flaky.calls == 1


def test_off_windows_nothing_is_retried():
    flaky = Flaky(1, held(32))
    with pytest.raises(PermissionError):
        atomic.retried(flaky, windows=False, sleep=lambda _s: pytest.fail("waited"))


def test_replace_and_move_do_the_rename(tmp_path):
    (tmp_path / "a").write_text("a")
    atomic.replace(str(tmp_path / "a"), str(tmp_path / "b"))
    assert (tmp_path / "b").read_text() == "a"
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "f").write_text("f")
    atomic.move(str(tmp_path / "d"), str(tmp_path / "e"))
    assert (tmp_path / "e" / "f").read_text() == "f" and not (tmp_path / "d").exists()


def test_move_copies_only_across_file_systems(tmp_path, monkeypatch):
    calls = []

    def cross_device(_source, _target):
        raise OSError(errno.EXDEV, "Invalid cross-device link")
    monkeypatch.setattr(atomic.os, "replace", cross_device)
    monkeypatch.setattr(atomic.shutil, "move", lambda s, t: calls.append((s, t)))
    atomic.move("a", "b")
    assert calls == [("a", "b")]

    def held_file(_source, _target):
        raise held(5) if os.name == "nt" else PermissionError(errno.EACCES, "held")
    monkeypatch.setattr(atomic.os, "replace", held_file)
    monkeypatch.setattr(atomic, "retried", lambda op, *a, **k: op(*a))
    with pytest.raises(PermissionError):                # never a copy for a held file
        atomic.move("a", "b")
    assert calls == [("a", "b")]


def test_every_rename_in_the_tool_goes_through_atomic():
    """A new os.replace/os.rename/os.renames/shutil.move - called, or imported
    by name - would not wait out a held file. The tool and the wizard both.
    (pathlib's .rename/.replace are not looked for: str.replace reads the same;
    none is used.)"""
    banned = {("os", "replace"), ("os", "rename"), ("os", "renames"), ("shutil", "move")}
    direct = []
    for path in sorted([*ROOT.glob("*.py"), *ROOT.parent.glob("iemod_fetch_gui/**/*.py")]):
        if path.name == "atomic.py" and path.parent == ROOT:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and (node.func.value.id, node.func.attr) in banned):
                direct.append(f"{path.name}:{node.lineno}")
            if isinstance(node, ast.ImportFrom) and node.module in ("os", "shutil"):
                direct += [f"{path.name}:{node.lineno} imports {alias.name}"
                           for alias in node.names if (node.module, alias.name) in banned]
    assert direct == []


# ------------------------------------------------- review of #102
def test_a_small_write_waits_only_briefly_the_window_may_wait_on_it():
    """write_text runs on the GUI's thread too (the order's drag, Save): it
    gives a held file about 150 ms, not 5 s."""
    waits = []
    flaky = Flaky(99, held(32))
    with pytest.raises(PermissionError):
        atomic.retried(flaky, windows=True, sleep=waits.append, budget_s=atomic.BRIEF_S)
    assert sum(waits) <= atomic.BRIEF_S + 1e-9 and waits == [0.01, 0.02, 0.04, 0.08]


def test_write_text_asks_for_the_brief_wait(tmp_path, monkeypatch):
    seen = []
    real = atomic.retried
    monkeypatch.setattr(atomic, "retried",
                        lambda op, *a, **k: seen.append(k.get("budget_s")) or real(op, *a, **k))
    atomic.write_text(str(tmp_path / "f.json"), "{}")
    assert seen == [atomic.BRIEF_S]


def test_an_access_denial_no_wait_ends_is_raised_at_once(tmp_path):
    """Review of #102: a target folder that is there already, or a read-only
    file, refuses with winerror 5 for good - not 5 s of waiting."""
    (tmp_path / "there").mkdir()
    flaky = Flaky(99, held(5))
    with pytest.raises(PermissionError):
        atomic.retried(flaky, windows=True, sleep=lambda _s: pytest.fail("waited"),
                       for_good=lambda: atomic._for_good(str(tmp_path / "there")))
    assert flaky.calls == 1
    assert not atomic._for_good(str(tmp_path / "none"))
    held_32 = Flaky(1, held(32))                       # a sharing violation is still waited out
    assert atomic.retried(held_32, windows=True, sleep=lambda _s: None,
                          for_good=lambda: True) == "done"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_a_read_only_target_file_is_for_good(tmp_path):
    target = tmp_path / "ro.txt"
    target.write_text("x")
    target.chmod(0o444)
    try:
        assert atomic._for_good(str(target)) or os.geteuid() == 0
    finally:
        target.chmod(0o644)


def test_a_mod_moves_in_one_rename_never_entry_by_entry(tmp_path, monkeypatch):
    """Review of #102: the mod's folder moves whole from the staging folder."""
    import zipfile

    from iemod_fetch.install import install_from_archive
    arc = tmp_path / "m.zip"
    with zipfile.ZipFile(arc, "w") as zf:
        for name in ("Ub/setup-ub.tp2", "Ub/a.txt", "Ub/b.txt", "Ub/c.txt"):
            zf.writestr(name, "BACKUP ~x~")
    moves = []
    real = atomic.move
    monkeypatch.setattr(atomic, "move", lambda s, t: moves.append((s, t)) or real(s, t))
    outcome = install_from_archive(str(arc), str(tmp_path / "Mods"), "Ub")
    assert len(moves) == 1 and moves[0][1] == str(tmp_path / "Mods" / "Ub")
    assert outcome.file_count == 4 and (tmp_path / "Mods" / "Ub" / "c.txt").exists()


def test_a_move_that_fails_puts_the_old_copy_back(tmp_path, monkeypatch):
    import zipfile

    from iemod_fetch.install import install_from_archive
    mods = tmp_path / "Mods"
    (mods / "Ub").mkdir(parents=True)
    (mods / "Ub" / "setup-ub.tp2").write_text("old")
    arc = tmp_path / "m.zip"
    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("Ub/setup-ub.tp2", "new")
    real = atomic.move

    def held_on_install(source, target):
        if ".staging" in source:
            raise PermissionError(errno.EACCES, "held")
        real(source, target)
    monkeypatch.setattr(atomic, "move", held_on_install)
    with pytest.raises(PermissionError):
        install_from_archive(str(arc), str(mods), "Ub", force=True)
    assert (mods / "Ub" / "setup-ub.tp2").read_text() == "old"     # put back


def test_a_read_only_mod_folder_from_the_archive_is_made_writable(tmp_path, monkeypatch):
    """Second review of #102: the folder moves as the unpacker made it; a
    read-only one would stop WeiDU creating <mod>/backup/ in it, and on
    POSIX cannot be renamed into another folder at all (third review: passes
    as root only if the mode is set after the move)."""
    import stat
    import zipfile

    from iemod_fetch import install
    arc = tmp_path / "m.zip"
    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("Ub/setup-ub.tp2", "BACKUP ~x~")
    real_extract = install.safe_extract

    def read_only_root(archive, dest, **kw):
        real_extract(archive, dest, **kw)
        os.chmod(os.path.join(dest, "Ub"), 0o500)
    monkeypatch.setattr(install, "safe_extract", read_only_root)
    outcome = install.install_from_archive(str(arc), str(tmp_path / "Mods"), "Ub")
    mode = stat.S_IMODE(os.stat(outcome.dest).st_mode)
    assert mode & stat.S_IRWXU == stat.S_IRWXU


def test_when_putting_the_old_copy_back_fails_too_one_message_says_where_it_is(
        tmp_path, monkeypatch):
    import zipfile

    from iemod_fetch.install import install_from_archive
    mods = tmp_path / "Mods"
    (mods / "Ub").mkdir(parents=True)
    (mods / "Ub" / "setup-ub.tp2").write_text("old")
    arc = tmp_path / "m.zip"
    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("Ub/setup-ub.tp2", "new")
    real = atomic.move

    def held_back(source, target):
        if ".staging" in source or ".backup" in source:
            raise PermissionError(errno.EACCES, "held")
        real(source, target)
    monkeypatch.setattr(atomic, "move", held_back)
    with pytest.raises(OSError, match=r"Ub: not installed .*kept in .*\.backup.*putting it back "
                                      r"failed too") as excinfo:
        install_from_archive(str(arc), str(mods), "Ub", force=True)
    assert isinstance(excinfo.value.__cause__, PermissionError)
    assert excinfo.value.__cause__.errno == errno.EACCES          # the move's own error
    kept = list((mods / ".backup").iterdir())
    assert len(kept) == 1 and (kept[0] / "setup-ub.tp2").read_text() == "old"
