"""
Room and the right WeiDU before an install (GUI-AUDIT M8 item 49, ADR-0055):
warnings, never refusals. Free space and WeiDU's answer are injected; the
sizes are real files.
"""
import os

from iemod_fetch import api, backup, readiness


def game(tmp_path, name="bg2ee", override=1000):
    folder = tmp_path / name
    (folder / "override").mkdir(parents=True)
    (folder / "lang" / "en_US").mkdir(parents=True)
    (folder / "chitin.key").write_bytes(b"k" * 100)
    (folder / "override" / "a.itm").write_bytes(b"o" * override)
    (folder / "lang" / "en_US" / "dialog.tlk").write_bytes(b"t" * 200)
    (folder / "lang" / "en_US" / "sound.wav").write_bytes(b"s" * 5000)   # not backed up
    (folder / "data").mkdir()
    (folder / "data" / "big.bif").write_bytes(b"b" * 7000)               # not backed up
    return str(folder)


def mods(tmp_path, tp2="BEGIN ~x~\n", size=3000):
    folder = tmp_path / "mods" / "m"
    folder.mkdir(parents=True)
    (folder / "m.tp2").write_text(tp2)
    (folder / "data.bin").write_bytes(b"d" * size)
    return str(tmp_path / "mods")


def test_a_backup_is_measured_as_it_is_made(tmp_path):
    folder = game(tmp_path)
    assert backup.size(folder) == 100 + 1000 + 200                      # root, override, tlk
    made = backup.create(folder, str(tmp_path / "backups"))
    copied = sum(os.path.getsize(os.path.join(here, n))
                 for here, _d, names in os.walk(os.path.join(made, backup.FILES))
                 for n in names)
    assert copied == backup.size(folder)


def test_no_room_for_the_backup_is_said(tmp_path):
    folder = game(tmp_path)
    backups = str(tmp_path / "backups")
    found = readiness.findings({"BG2EE": folder}, mods(tmp_path), None, backups_dir=backups,
                               free=lambda path: 10**9 if "bg2ee" in path else 500,
                               device=lambda path: "bg2ee" in path)
    assert len(found) == 1 and f"the backup in {backups}" in found[0]
    assert "an estimate" not in found[0] and "MiB is free" in found[0]


def test_no_room_for_the_install_is_an_estimate_said_as_one(tmp_path):
    folder, staged = game(tmp_path), mods(tmp_path)
    found = readiness.findings({"BG2EE": folder}, staged, None, free=lambda _path: 4000)
    assert len(found) == 1 and "the install into BG2EE" in found[0]
    assert "an estimate" in found[0]
    assert readiness.findings({"BG2EE": folder}, staged, None,
                              free=lambda _path: 10**9) == []


def test_what_lands_on_one_drive_is_added_up(tmp_path):
    """Review of #114: BG:EE, EET and the backups on one drive - each fits
    alone, all together do not."""
    bgee, eet = game(tmp_path, "bgee"), game(tmp_path, "eet")
    staged = mods(tmp_path, size=0)
    one = backup.size(bgee)                                     # each game's own need
    games = {"BGEE": bgee, "EET": eet}
    plenty = one * 2 + 100                                      # more than any one need
    found = readiness.findings(games, staged, None, backups_dir=str(tmp_path / "backups"),
                               free=lambda _p: plenty, device=lambda _p: "C:")
    assert len(found) == 1
    assert "the backup in" in found[0] and "the install into BGEE" in found[0]
    assert "the install into EET" in found[0] and "an estimate" in found[0]
    # on drives of their own, each fits
    assert readiness.findings(games, staged, None, backups_dir=str(tmp_path / "backups"),
                              free=lambda _p: plenty, device=lambda p: p) == []


def test_a_file_gone_during_the_scan_counts_nothing(tmp_path, monkeypatch):
    """Review of #114: the game or a scanner removes a file between the scan
    and its size."""
    folder = game(tmp_path)
    real = os.path.getsize

    def gone(path):
        if path.endswith("a.itm"):
            raise FileNotFoundError(path)
        return real(path)
    monkeypatch.setattr(backup.os.path, "getsize", gone)
    assert backup.size(folder) == 100 + 200


def test_a_weidu_older_than_tested_or_than_a_mod_needs(tmp_path):
    folder = game(tmp_path)
    staged = mods(tmp_path, "BEGIN ~x~\nREQUIRE_PREDICATE (WEIDU_VER >= 24900) ~old~\n"
                            "ACTION_IF WEIDU_VER > 25100 BEGIN END\n")
    big = lambda _path: 10**12  # noqa: E731
    found = readiness.findings({"BG2EE": folder}, staged, "/w", free=big,
                               version=lambda _tool, _path: "24600")
    assert found == ["WeiDU 24600 is older than 25100, the one this program is tested with",
                     (f"WeiDU 24600 is older than 25101, which {os.path.join('m', 'm.tp2')} "
                     "requires (WEIDU_VER)")]
    assert readiness.findings({"BG2EE": folder}, staged, "/w", free=big,
                              version=lambda _tool, _path: "25200") == []
    # a WeiDU that does not answer, or none given: nothing said about it
    assert readiness.findings({"BG2EE": folder}, staged, "/w", free=big,
                              version=lambda _tool, _path: None) == []
    assert readiness.findings({"BG2EE": folder}, staged, None, free=big) == []


def test_what_a_mod_requires_is_read_from_its_tp2_tpa_and_tph(tmp_path):
    staged = mods(tmp_path)
    (tmp_path / "mods" / "m" / "lib").mkdir()
    (tmp_path / "mods" / "m" / "lib" / "a.tph").write_text("PATCH_IF (WEIDU_VER >= 24700)")
    (tmp_path / "mods" / "m" / "readme.txt").write_text("WEIDU_VER >= 99999")
    assert readiness.weidu_needed(staged) == (24700, os.path.join("m", "lib", "a.tph"))
    assert readiness.weidu_needed(mods(tmp_path / "other")) is None


def test_the_api_says_the_same_with_the_real_disk(tmp_path):
    folder = game(tmp_path)
    assert api.install_readiness({"BG2EE": folder}, mods(tmp_path), None,
                                 backups_dir=str(tmp_path / "not-yet" / "backups")) == []


def test_a_drive_that_cannot_be_read_is_not_measured(tmp_path):
    """Review of #114: a network path or a drive that is not there is never
    an error - nothing is said of it."""
    folder = game(tmp_path)
    assert readiness.findings({"BG2EE": folder}, mods(tmp_path), None,
                              backups_dir=str(tmp_path / "b"), free=lambda _p: None) == []
