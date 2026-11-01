"""
A game folder's backup and restore (GUI-AUDIT M4 item 21, ADR-0042): what
WeiDU changes is copied and checked by sha256, the rest listed; a restore
deletes nothing - what is in the way is moved aside - and says what it could
not put back.
"""
import json
import os
import pathlib
import threading

import pytest

from iemod_fetch import backup
from iemod_fetch.errors import ConfigError


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def game(tmp_path):
    root = tmp_path / "BG2EE"
    write(root / "chitin.key", b"KEY V1  original")
    write(root / "Baldur.exe", b"MZ" + b"\0" * 64)
    write(root / "override" / "spwi101.spl", b"SPL original")
    write(root / "lang" / "en_US" / "dialog.tlk", b"TLK english")
    write(root / "lang" / "de_DE" / "dialogF.tlk", b"TLK deutsch")
    write(root / "lang" / "en_US" / "fonts" / "font.ttf", b"font")   # listed only
    write(root / "data" / "AREA000A.bif", b"BIFF original")          # listed only
    write(root / "movies" / "intro.wbm", b"movie")                   # listed only
    (root / "empty").mkdir()                                         # stays empty
    return root


def install(root):
    """What an install does to a game folder."""
    write(root / "override" / "spwi101.spl", b"SPL patched by a mod")
    write(root / "override" / "newitem.itm", b"ITM added")
    write(root / "lang" / "en_US" / "dialog.tlk", b"TLK english with new strings")
    write(root / "chitin.key", b"KEY V1  with a new biff")
    write(root / "data" / "modded.bif", b"BIFF added")
    write(root / "WeiDU.log", b"~MYMOD/SETUP-MYMOD.TP2~ #0 #0 // My mod\n")
    write(root / "mymod" / "setup-mymod.tp2", b"BACKUP ~mymod/backup~")
    write(root / "mymod" / "backup" / "0" / "spwi101.spl", b"SPL original")
    write(root / "data" / "AREA000A.bif", b"BIFF changed by a mod!")       # not copied
    os.remove(root / "movies" / "intro.wbm")                                # not copied


def test_what_wei_du_changes_is_copied_and_the_rest_listed(tmp_path):
    root = game(tmp_path)
    path = backup.create(str(root), str(tmp_path / "backups"), name="before")
    manifest = backup.read_manifest(path)
    assert sorted(manifest["copied"]) == ["Baldur.exe", "chitin.key",
                                          "lang/de_DE/dialogF.tlk", "lang/en_US/dialog.tlk",
                                          "override/spwi101.spl"]
    assert "data/AREA000A.bif" in manifest["inventory"] and \
        "data/AREA000A.bif" not in manifest["copied"]
    assert manifest["copied"]["chitin.key"]["size"] == len(b"KEY V1  original")
    assert backup.verify(path) == {"ok": True, "files": 5, "problems": []}
    assert [b["name"] for b in backup.list_backups(str(tmp_path / "backups"))] == ["before"]


def test_a_restore_brings_the_game_back_and_deletes_nothing(tmp_path):
    root = game(tmp_path)
    path = backup.create(str(root), str(tmp_path / "backups"), name="before")
    install(root)
    plan = backup.plan_restore(path, str(root))
    assert plan["put_back"] == ["chitin.key", "lang/en_US/dialog.tlk", "override/spwi101.spl"]
    assert plan["displace"] == ["WeiDU.log", "data/modded.bif", "mymod/backup/0/spwi101.spl",
                                "mymod/setup-mymod.tp2", "override/newitem.itm"]
    assert plan["cannot_restore"] == ["data/AREA000A.bif: changed, and not in the backup",
                                      "movies/intro.wbm: missing, and not in the backup"]

    result = backup.restore(path, str(root))
    assert (root / "override" / "spwi101.spl").read_bytes() == b"SPL original"
    assert (root / "lang" / "en_US" / "dialog.tlk").read_bytes() == b"TLK english"
    assert (root / "chitin.key").read_bytes() == b"KEY V1  original"
    for gone in ("WeiDU.log", "data/modded.bif", "mymod", "override/newitem.itm"):
        assert not (root / gone).exists(), gone
    assert (root / "empty").is_dir()                 # it was empty before: kept
    aside = pathlib.Path(result["displaced_to"])
    # nothing deleted: every file moved away is in displaced-*/, under its path
    assert (aside / "override" / "spwi101.spl").read_bytes() == b"SPL patched by a mod"
    assert (aside / "mymod" / "setup-mymod.tp2").read_bytes() == b"BACKUP ~mymod/backup~"
    assert (aside / "WeiDU.log").read_bytes().startswith(b"~MYMOD")
    assert result["cannot_restore"] == plan["cannot_restore"]

    again = backup.plan_restore(path, str(root))     # finished: nothing left to do
    assert again["put_back"] == [] and again["displace"] == []


def test_a_damaged_backup_restores_nothing(tmp_path):
    root = game(tmp_path)
    path = backup.create(str(root), str(tmp_path / "backups"), name="before")
    install(root)
    (tmp_path / "backups" / "before" / "files" / "chitin.key").write_bytes(b"tampered")
    assert not backup.verify(path)["ok"]
    from iemod_fetch.errors import VerificationFailed
    with pytest.raises(VerificationFailed, match="damaged"):
        backup.restore(path, str(root))
    assert (root / "override" / "newitem.itm").exists()            # untouched


def test_a_restore_cut_short_is_finished_by_running_it_again(tmp_path):
    root = game(tmp_path)
    path = backup.create(str(root), str(tmp_path / "backups"), name="before")
    install(root)
    cancel = threading.Event()
    seen = []

    def on_progress(event):
        seen.append(event["event"])
        if event["event"] == "restore_displaced":
            cancel.set()                               # stop after the first move
    with pytest.raises(InterruptedError):
        backup.restore(path, str(root), on_progress=on_progress, cancel=cancel)
    assert seen.count("restore_displaced") == 1
    backup.restore(path, str(root))
    assert (root / "override" / "spwi101.spl").read_bytes() == b"SPL original"
    assert not (root / "mymod").exists()


def test_a_backup_is_refused_where_it_cannot_work(tmp_path):
    root = game(tmp_path)
    with pytest.raises(ConfigError, match="inside the game folder"):
        backup.create(str(root), str(root / "backups"))
    (tmp_path / "notagame").mkdir()
    with pytest.raises(ConfigError, match="chitin.key"):
        backup.create(str(tmp_path / "notagame"), str(tmp_path / "backups"))
    backup.create(str(root), str(tmp_path / "backups"), name="once")
    with pytest.raises(ConfigError, match="exists already"):
        backup.create(str(root), str(tmp_path / "backups"), name="once")


def test_a_cancelled_backup_is_never_taken_for_a_finished_one(tmp_path):
    root = game(tmp_path)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        backup.create(str(root), str(tmp_path / "backups"), name="half", cancel=cancel)
    assert not (tmp_path / "backups" / "half").exists()
    assert (tmp_path / "backups" / ("half" + backup.PARTIAL)).exists()
    assert backup.list_backups(str(tmp_path / "backups")) == []
    backup.create(str(root), str(tmp_path / "backups"), name="half")   # retried cleanly
    assert [b["name"] for b in backup.list_backups(str(tmp_path / "backups"))] == ["half"]


def test_the_command_line_backs_up_shows_then_restores(tmp_path, monkeypatch):
    import io

    from iemod_fetch import cli

    def run(*argv):
        out = io.StringIO()
        return cli.main(list(argv), stream=out), out.getvalue()

    def no_network(*_args, **_kwargs):
        raise AssertionError("a backup action reached for the network")
    monkeypatch.setattr("socket.socket.connect", no_network)
    monkeypatch.chdir(tmp_path)
    root = game(tmp_path)
    store = tmp_path / "store"
    code, out = run("--backup", str(root), "--backup-to", str(store))
    assert code == 0 and "5 files copied" in out
    [made] = backup.list_backups(str(store))
    assert run("--verify-backup", made["path"])[0] == 0
    install(root)
    code, shown = run("--restore-backup", made["path"])               # shown only
    # 1: two changes could not be put back, which the plan says already
    assert code == 1 and "move aside: 5 files" in shown and "--apply" in shown
    assert (root / "mymod").exists()
    # with --apply: restored; 1 because two changes could not be put back
    code, out = run("--restore-backup", made["path"], "--apply")
    assert code == 1 and "nothing was deleted" in out
    assert not (root / "mymod").exists()


# ------------------------------------------------- review of #48 (data safety)
def backed_up(tmp_path):
    root = game(tmp_path)
    return root, backup.create(str(root), str(tmp_path / "backups"), name="before")


def test_restores_never_share_a_displaced_folder(tmp_path, monkeypatch):
    """Two restores in one second used one displaced-<time>/ and the second's
    moves replaced the first's files."""
    monkeypatch.setattr(backup.time, "strftime", lambda *_a: "20261023T000000")
    root, path = backed_up(tmp_path)
    write(root / "override" / "user.itm", b"first")
    first = backup.restore(path, str(root))
    write(root / "override" / "user.itm", b"second")
    second = backup.restore(path, str(root))
    assert first["displaced_to"] != second["displaced_to"]
    assert (pathlib.Path(first["displaced_to"]) / "override" / "user.itm").read_bytes() == b"first"
    assert (pathlib.Path(second["displaced_to"]) / "override" / "user.itm").read_bytes() == b"second"


@pytest.mark.parametrize("rel", ["../../escape.txt", "/etc/escape.txt", "override/../../escape.txt"]
                         + (["C:/escape.txt", "override\\..\\..\\escape.txt"]
                            if os.name == "nt" else []))
def test_a_manifest_naming_a_path_outside_is_refused(tmp_path, rel):
    import hashlib
    import json
    root, path = backed_up(tmp_path)
    manifest_path = pathlib.Path(path) / backup.MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    data = b"echo pwned"
    manifest["copied"][rel] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    manifest["inventory"][rel] = len(data)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    from iemod_fetch.errors import VerificationFailed
    with pytest.raises(VerificationFailed, match="damaged"):
        backup.verify(path)
    with pytest.raises(VerificationFailed):
        backup.restore(path, str(root))
    assert not (tmp_path / "escape.txt").exists()


def test_a_manifest_missing_a_field_is_an_error_not_a_traceback(tmp_path):
    import json
    _root, path = backed_up(tmp_path)
    manifest_path = pathlib.Path(path) / backup.MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["copied"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    from iemod_fetch import cli
    import io
    assert cli.main(["--verify-backup", path], stream=io.StringIO()) == 1


def test_a_restore_writes_only_into_a_game_folder_and_the_one_backed_up(tmp_path):
    root, path = backed_up(tmp_path)
    documents = tmp_path / "Documents"
    write(documents / "thesis.docx", b"years of work")
    with pytest.raises(ConfigError, match="not a game folder"):
        backup.restore(path, str(documents), other_folder=True)
    assert (documents / "thesis.docx").read_bytes() == b"years of work"
    other = tmp_path / "BG2EE-copy"
    write(other / "chitin.key", b"KEY V1  another install")
    with pytest.raises(ConfigError, match="not the folder this backup was made of"):
        backup.restore(path, str(other))
    backup.restore(path, str(other), other_folder=True)              # named: allowed
    assert (other / "chitin.key").read_bytes() == b"KEY V1  original"


def test_a_file_differing_only_in_case_is_moved_aside_once(tmp_path):
    """On a case-sensitive system a mod's x.itm beside X.ITM is a file of its
    own and is moved aside; on a case-insensitive one (Windows, macOS) it IS
    X.ITM, changed, and is put back. Either way one restore finishes it."""
    probe = tmp_path / "Probe"
    probe.write_bytes(b"")
    case_sensitive = not (tmp_path / "probe").exists()
    root = game(tmp_path)
    write(root / "override" / "X.ITM", b"backed up")
    path = backup.create(str(root), str(tmp_path / "backups"), name="before")
    write(root / "override" / "x.itm", b"a mod's")
    plan = backup.plan_restore(path, str(root))
    if case_sensitive:
        assert plan["put_back"] == [] and plan["displace"] == ["override/x.itm"]
    else:
        assert plan["put_back"] == ["override/X.ITM"] and plan["displace"] == []
    backup.restore(path, str(root))
    assert (root / "override" / "X.ITM").read_bytes() == b"backed up"
    assert sorted(os.listdir(root / "override")) == ["X.ITM", "spwi101.spl"]
    again = backup.plan_restore(path, str(root))
    assert again["put_back"] == [] and again["displace"] == []


def test_folders_the_backup_had_stay_even_when_they_were_empty(tmp_path):
    root = game(tmp_path)
    (root / "save").mkdir()
    (root / "override" / "empty_sub").mkdir()
    path = backup.create(str(root), str(tmp_path / "backups"), name="before")
    write(root / "save" / "000000001-Quick-Save" / "BALDUR.gam", b"a save")
    write(root / "override" / "empty_sub" / "new.itm", b"added")
    backup.restore(path, str(root))
    assert (root / "save").is_dir() and (root / "override" / "empty_sub").is_dir()
    assert not (root / "save" / "000000001-Quick-Save").exists()     # added, emptied


def test_a_rerun_after_a_cut_removes_the_mod_folders_it_emptied(tmp_path):
    root, path = backed_up(tmp_path)
    install(root)
    cancel = threading.Event()

    def on_progress(event):
        if event["event"] == "restore_displaced" and event["file"].startswith("mymod/"):
            cancel.set()
    with pytest.raises(InterruptedError):
        backup.restore(path, str(root), on_progress=on_progress, cancel=cancel)
    backup.restore(path, str(root))
    assert not (root / "mymod").exists()


@pytest.mark.skipif(os.name == "nt", reason="symbolic links need privileges on Windows")
def test_links_are_never_followed(tmp_path):
    root = game(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.symlink(elsewhere, root / "movies-link")              # a link the backup lists
    path = backup.create(str(root), str(tmp_path / "backups"), name="before")
    assert backup.read_manifest(path)["links"] == ["movies-link"]
    # a backed-up file replaced by a dangling link: moved aside, never written through
    os.remove(root / "override" / "spwi101.spl")
    os.symlink(tmp_path / "outside.spl", root / "override" / "spwi101.spl")
    plan = backup.restore(path, str(root))
    assert plan["links"] == ["movies-link"] and (root / "movies-link").is_symlink()
    assert not (tmp_path / "outside.spl").exists()
    assert (root / "override" / "spwi101.spl").read_bytes() == b"SPL original"
    assert not (root / "override" / "spwi101.spl").is_symlink()


@pytest.mark.skipif(os.name == "nt", reason="symbolic links need privileges on Windows")
def test_a_backup_refuses_an_override_that_is_a_link(tmp_path):
    root = game(tmp_path)
    real = tmp_path / "real-override"
    (root / "override").rename(real)
    os.symlink(real, root / "override")
    with pytest.raises(ConfigError, match="is a link"):
        backup.create(str(root), str(tmp_path / "backups"))


def test_the_command_line_takes_one_backup_action_at_a_time(tmp_path):
    import io

    from iemod_fetch import cli
    root, path = backed_up(tmp_path)
    for argv in (["--backup", str(root), "--restore-backup", path, "--apply"],
                 ["--verify-backup", path, "--restore-backup", path],
                 ["--verify-backup", path, "--apply"],
                 ["--verify-backup", path, "--backup-to", str(tmp_path)]):
        assert cli.main(argv, stream=io.StringIO()) == 2, argv


def test_a_damaged_backup_exits_1_with_a_message(tmp_path):
    import io

    from iemod_fetch import cli
    root, path = backed_up(tmp_path)
    (pathlib.Path(path) / "files" / "chitin.key").write_bytes(b"tampered")
    assert cli.main(["--restore-backup", path, "--apply"], stream=io.StringIO()) == 1


# ------------------------------------------------- second review of #48
@pytest.mark.skipif(os.name == "nt", reason="'\\' and ':' cannot be in a Windows file name")
def test_names_with_backslash_or_colon_are_backed_up_and_moved_aside(tmp_path):
    """A mod unpacked from a Windows-made zip leaves `mymod\\backup\\a.itm` on
    Linux; a save may be named "Chapter 2: ...". Such a name once stopped
    every restore at the same file, and made a backup unreadable."""
    root = game(tmp_path)
    write(root / "save" / "Chapter 2: Irenicus" / "x.sav", b"a save")
    path = backup.create(str(root), str(tmp_path / "backups"), name="before")
    assert backup.verify(path)["ok"]
    write(root / "mymod\\backup\\0\\a.itm", b"from a Windows zip")
    write(root / "override" / "spwi101.spl", b"patched")
    result = backup.restore(path, str(root))
    assert not (root / "mymod\\backup\\0\\a.itm").exists()
    assert (pathlib.Path(result["displaced_to"]) / "mymod\\backup\\0\\a.itm").exists()
    assert (root / "override" / "spwi101.spl").read_bytes() == b"SPL original"
    assert [b["name"] for b in backup.list_backups(str(tmp_path / "backups"))] == ["before"]


@pytest.mark.skipif(os.name == "nt", reason="symbolic links need privileges on Windows")
def test_a_backup_reached_through_another_name_of_the_game_is_refused(tmp_path):
    """Compared by identity, not by spelling: an alias of the game folder
    (a link here; on macOS another letter case, a mount elsewhere)."""
    root = game(tmp_path)
    alias = tmp_path / "alias"
    os.symlink(root, alias)
    with pytest.raises(ConfigError, match="inside the game folder"):
        backup.create(str(root), str(alias / "backups"))


def test_empty_folders_made_since_are_left_alone(tmp_path):
    root, path = backed_up(tmp_path)
    (root / "save" / "my-new-slot").mkdir(parents=True)
    write(root / "mymod" / "setup-mymod.tp2", b"tp2")
    result = backup.restore(path, str(root))
    assert (root / "save" / "my-new-slot").is_dir()          # not touched by the moves
    assert result["removed_folders"] == ["mymod"]


def test_a_backup_of_another_folder_leaves_its_empty_folders(tmp_path):
    _root, path = backed_up(tmp_path)
    other = tmp_path / "other"
    write(other / "chitin.key", b"KEY")
    for name in ("save", "mpsave", "temp"):
        (other / name).mkdir()
    backup.restore(path, str(other), other_folder=True)
    assert all((other / name).is_dir() for name in ("save", "mpsave", "temp"))


def test_the_command_line_checks_the_backup_before_showing_a_plan(tmp_path):
    import io

    from iemod_fetch import cli
    _root, path = backed_up(tmp_path)
    (pathlib.Path(path) / "files" / "chitin.key").write_bytes(b"tampered")
    out = io.StringIO()
    assert cli.main(["--restore-backup", path], stream=out) == 1
    assert "DAMAGED" in out.getvalue()
    (pathlib.Path(path) / backup.MANIFEST).write_text("{not json", encoding="utf-8")
    assert cli.main(["--verify-backup", path], stream=io.StringIO()) == 1
    assert backup.list_backups(str(tmp_path / "backups")) == []   # skipped, not raised


@pytest.mark.parametrize("argv", [["--apply"], ["--restore-to", "x"], ["--backup-to", "x"]])
def test_backup_options_alone_are_an_error_not_a_normal_run(tmp_path, monkeypatch, argv):
    import io

    from iemod_fetch import cli

    def no_network(*_args, **_kwargs):
        raise AssertionError("reached for the network")
    monkeypatch.setattr("socket.socket.connect", no_network)
    monkeypatch.chdir(tmp_path)
    assert cli.main(argv, stream=io.StringIO()) == 2


def test_a_folder_leading_elsewhere_is_never_entered(tmp_path, monkeypatch):
    """A junction or a bind mount is not a link to os.path.islink: once it
    was entered, and files living outside the game were moved into the
    backup. Here the mount table names the folder (a bind mount needs root)."""
    root, path = backed_up(tmp_path)
    shared = root / "linked"
    write(shared / "user-file.txt", b"not the game's")
    monkeypatch.setattr(backup, "_mount_points",
                        lambda: {os.path.realpath(shared): os.stat(shared).st_dev})
    plan = backup.plan_restore(path, str(root))
    assert plan["displace"] == [] and plan["mounts"] == ["linked"]
    backup.restore(path, str(root))
    assert (shared / "user-file.txt").read_bytes() == b"not the game's"


# ------------------------------------------------- third review of #48
def test_a_mount_on_a_path_to_put_back_stops_the_restore_before_any_change(
        tmp_path, monkeypatch):
    """shutil.move onto a mount once copied it and rmtree()d the mounted
    folder - outside the game. Now the restore stops first, exit 1."""
    import io

    from iemod_fetch import cli
    from iemod_fetch.errors import ModFetchError
    root, path = backed_up(tmp_path)
    spot = root / "override" / "spwi101.spl"
    spot.unlink()
    write(spot / "precious.txt", b"lives outside the game")
    monkeypatch.setattr(backup, "_mount_points",
                        lambda: {os.path.realpath(spot): os.stat(spot).st_dev})
    plan = backup.plan_restore(path, str(root))
    assert plan["blocked"] == ["override/spwi101.spl"]
    with pytest.raises(ModFetchError, match="nothing restored"):
        backup.restore(path, str(root))
    assert (spot / "precious.txt").read_bytes() == b"lives outside the game"
    assert cli.main(["--restore-backup", path], stream=io.StringIO()) == 1


def test_a_folder_where_the_backup_has_a_file_is_emptied_and_replaced(tmp_path):
    root, path = backed_up(tmp_path)
    spot = root / "override" / "spwi101.spl"
    spot.unlink()
    write(spot / "inner.txt", b"a mod's")
    result = backup.restore(path, str(root))
    assert spot.read_bytes() == b"SPL original"
    aside = pathlib.Path(result["displaced_to"])
    assert (aside / "override" / "spwi101.spl" / "inner.txt").read_bytes() == b"a mod's"


def test_a_move_across_drives_never_leaves_two_copies(tmp_path, monkeypatch):
    """Across drives a file is copied, then removed; when it cannot be
    removed the copy is taken back, so a rerun starts from the same state."""
    import errno as _errno
    root, path = backed_up(tmp_path)
    write(root / "added.txt", b"added")

    def cross_device(_src, _dst):
        raise OSError(_errno.EXDEV, "cross-device")
    monkeypatch.setattr(backup.os, "rename", cross_device)
    real_remove = os.remove

    def busy(target):
        if str(target).endswith(os.path.join("BG2EE", "added.txt")):
            raise OSError(_errno.EBUSY, "busy")
        real_remove(target)
    monkeypatch.setattr(backup.os, "remove", busy)
    with pytest.raises(OSError):
        backup.restore(path, str(root))
    assert (root / "added.txt").read_bytes() == b"added"
    copies = list(pathlib.Path(path).glob("displaced-*/added.txt"))
    assert copies == []


def test_a_backups_folder_that_is_a_game_folder_by_another_path_is_refused(tmp_path):
    root = game(tmp_path)
    (root / "extras").mkdir()
    if os.name == "nt":
        pytest.skip("symbolic links need privileges on Windows")
    os.symlink(root / "extras", tmp_path / "backups-elsewhere")
    with pytest.raises(ConfigError, match="inside the game folder"):
        backup.create(str(root), str(tmp_path / "backups-elsewhere"))


def test_the_journal_names_only_what_was_moved(tmp_path):
    root, path = backed_up(tmp_path)
    (root / "MyNotes" / "drafts").mkdir(parents=True)
    journal = pathlib.Path(backup._journal_path(path, str(root)))
    journal.write_text(json.dumps({"game": os.path.realpath(root)}) +
                       '\n"../escape/x"\nnot json\n"MyNotes/drafts/x.txt"\n', encoding="utf-8")
    result = backup.restore(path, str(root))
    # never moved (not in any displaced- folder): its folder stays
    assert (root / "MyNotes" / "drafts").is_dir()
    assert result["removed_folders"] == [] and not journal.exists()


# ------------------------------------------------- fourth review of #48
def test_a_folder_with_subfolders_where_the_backup_has_a_file_is_restored(tmp_path):
    root, path = backed_up(tmp_path)
    (root / "Baldur.exe").unlink()
    write(root / "Baldur.exe" / "sub" / "mine.txt", b"mine")
    (root / "Baldur.exe" / "emptysub").mkdir()
    for _run in range(2):                       # once, and a rerun has nothing left
        backup.restore(path, str(root))
    assert (root / "Baldur.exe").read_bytes() == b"MZ" + b"\0" * 64
    asides = list(pathlib.Path(path).glob("displaced-*"))
    assert any((a / "Baldur.exe" / "sub" / "mine.txt").exists() for a in asides)
    assert any((a / "Baldur.exe" / "emptysub").is_dir() for a in asides)   # moved, kept


def test_a_journal_of_another_game_folder_removes_nothing_here(tmp_path):
    _root, path = backed_up(tmp_path)
    other = tmp_path / "copy"
    write(other / "chitin.key", b"KEY")
    (other / "mods" / "x").mkdir(parents=True)
    # a journal naming another folder, in this folder's journal file
    journal = pathlib.Path(backup._journal_path(path, str(other)))
    journal.write_text(json.dumps({"game": "/elsewhere"}) + '\n"mods/x/2"\n', encoding="utf-8")
    result = backup.restore(path, str(other), other_folder=True)
    assert (other / "mods" / "x").is_dir() and result["removed_folders"] == []


def test_a_copy_across_drives_cut_short_leaves_no_part_file(tmp_path, monkeypatch):
    import errno as _errno
    root, path = backed_up(tmp_path)
    write(root / "big.bin", b"x" * 4096)

    def cross_device(_src, _dst):
        raise OSError(_errno.EXDEV, "cross-device")

    def disk_full(src, dst, **_kw):
        pathlib.Path(dst).write_bytes(b"x" * 100)
        raise OSError(_errno.ENOSPC, "no space")
    monkeypatch.setattr(backup.os, "rename", cross_device)
    monkeypatch.setattr(backup.shutil, "copy2", disk_full)
    with pytest.raises(OSError):
        backup.restore(path, str(root))
    assert (root / "big.bin").stat().st_size == 4096
    assert list(pathlib.Path(path).glob("displaced-*/big.bin")) == []


def test_a_backup_inside_the_game_is_refused_by_the_plan_already(tmp_path):
    import io
    import shutil as _shutil

    from iemod_fetch import cli
    root, path = backed_up(tmp_path)
    inside = root / "mybackups" / "before"
    _shutil.move(path, inside)
    assert cli.main(["--restore-backup", str(inside)], stream=io.StringIO()) == 2


# ------------------------------------------------- fifth review of #48
def test_two_folders_cut_from_one_backup_each_finish_their_own(tmp_path):
    """One journal per game folder: restoring one backup into two folders,
    both cut, once overwrote the first folder's journal with the second's."""
    _root, path = backed_up(tmp_path)
    games = []
    for name in ("G1", "G2"):
        folder = tmp_path / name
        write(folder / "chitin.key", b"KEY")
        write(folder / "mymod" / "backup" / "0" / "a.itm", b"a")
        write(folder / "mymod" / "setup-mymod.tp2", b"tp2")
        games.append(folder)
    for folder in games:
        cancel = threading.Event()

        def on_progress(event, cancel=cancel):
            if event["event"] == "restore_displaced":
                cancel.set()
        with pytest.raises(InterruptedError):
            backup.restore(path, str(folder), on_progress=on_progress, cancel=cancel,
                           other_folder=True)
    for folder in games:
        backup.restore(path, str(folder), other_folder=True)
        assert not (folder / "mymod").exists(), folder


@pytest.mark.skipif(os.name == "nt", reason="needs a case-sensitive file system")
def test_a_folder_to_become_a_file_keeps_no_case_twin(tmp_path):
    probe = tmp_path / "Probe"
    probe.write_bytes(b"")
    if (tmp_path / "probe").exists():
        pytest.skip("case-insensitive file system")
    root = game(tmp_path)
    write(root / "foo", b"root file")
    write(root / "FOO" / "bar.txt", b"listed")
    path = backup.create(str(root), str(tmp_path / "backups"), name="before")
    (root / "foo").unlink()
    import shutil as _shutil
    _shutil.rmtree(root / "FOO")
    write(root / "foo" / "bar.txt", b"the player's")
    plan = backup.plan_restore(path, str(root))
    assert "foo/bar.txt" in plan["displace"]
    assert "FOO/bar.txt: missing, and not in the backup" in plan["cannot_restore"]
    result = backup.restore(path, str(root))
    assert (root / "foo").read_bytes() == b"root file"
    assert (pathlib.Path(result["displaced_to"]) / "foo" / "bar.txt").read_bytes() == \
        b"the player's"
