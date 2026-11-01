"""
Which unpacker opens a .rar or .7z, in what order, and what a failed one
leaves behind (GUI-AUDIT M6 item 40, ADR-0047).

The order comes from the measurement in docs/TESTING.md: libarchive (bsdtar;
Windows' own tar.exe) first for RAR, then unar, then the player's own 7-Zip
or WinRAR. A tool that fails must leave nothing behind for the next one -
Debian's 7zip (the dfsg build, no RAR code) writes every file with the wrong
contents before it exits 2.
"""
import os
import subprocess

import pytest

from iemod_fetch import archives
from iemod_fetch.archives import Kind, safe_extract
from iemod_fetch.errors import ExtractionError

RAR4 = b"Rar!\x1a\x07\x00" + b"\x00" * 600


def _out_dir(cmd: list[str]) -> str:
    """Where a command line tells its tool to write."""
    for flag in ("-C", "-o"):
        if flag in cmd:
            return cmd[cmd.index(flag) + 1]
    for part in cmd:
        if part.startswith("-o") and len(part) > 2:     # 7z's -o<dir>
            return part[2:]
    return cmd[-1]                                       # unrar: <archive> <dir>


class Tools:
    """Fake unpackers: each writes its files where told and exits as set."""

    def __init__(self, monkeypatch, behaviour: dict[str, tuple[int, dict]]):
        self.behaviour, self.calls = behaviour, []
        monkeypatch.setattr(archives, "find_tool",
                            lambda name: f"/fake/{name}" if name in behaviour else None)
        monkeypatch.setattr(archives.subprocess, "run", self)

    def __call__(self, cmd, **_kw):
        tool = os.path.basename(cmd[0])
        if len(cmd) > 1 and cmd[1] == "l":                  # 7z's listing: none
            return subprocess.CompletedProcess(cmd, 2, b"", b"")
        self.calls.append(tool)
        code, files = self.behaviour[tool]
        out = _out_dir(cmd)
        for rel, data in files.items():
            os.makedirs(os.path.join(out, os.path.dirname(rel)), exist_ok=True)
            with open(os.path.join(out, rel), "w", encoding="utf-8") as fh:
                fh.write(data)
        return subprocess.CompletedProcess(cmd, code, b"", b"")


def _tree(folder) -> dict[str, str]:
    out = {}
    for root, _dirs, files in os.walk(folder):
        for name in files:
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as fh:
                out[os.path.relpath(path, folder).replace(os.sep, "/")] = fh.read()
    return out


@pytest.fixture
def rar(tmp_path):
    path = tmp_path / "mod.rar"
    path.write_bytes(RAR4)
    return str(path)


def test_a_failed_unpacker_leaves_nothing_for_the_next_one(monkeypatch, rar, tmp_path):
    """A tool can write, then fail: Debian's dfsg 7z writes every file with
    the wrong contents and exits 2 (measured), bsdtar stops after the first
    file of a solid RAR4. The next tool's files must be all that is left."""
    tools = Tools(monkeypatch, {
        "bsdtar": (1, {"mod/mod.tp2": "garbage", "mod/junk.txt": "x"}),
        "unar": (0, {"mod/mod.tp2": "BACKUP ~mod/backup~"})})
    out = tmp_path / "out"
    assert safe_extract(rar, str(out)) is Kind.RAR
    assert tools.calls == ["bsdtar", "unar"]
    assert _tree(out) == {"mod/mod.tp2": "BACKUP ~mod/backup~"}


def test_rar_goes_to_libarchive_first_then_unar_then_the_players_7zip(monkeypatch, rar,
                                                                     tmp_path):
    """The measured order (ADR-0047): bsdtar opened 95 of the 105 RAR
    archives on every system, unar what bsdtar could not, the player's
    7-Zip or WinRAR the rest."""
    every = {tool: (1, {}) for tool in ("bsdtar", "unar", "7z", "7za", "unrar")}
    tools = Tools(monkeypatch, every)
    with pytest.raises(ExtractionError, match="all unpackers failed"):
        safe_extract(rar, str(tmp_path / "out"))
    assert tools.calls == ["bsdtar", "unar", "7z", "7za", "unrar"]


def test_7z_goes_to_7zip_first(monkeypatch, tmp_path):
    arc = tmp_path / "mod.7z"
    arc.write_bytes(b"7z\xbc\xaf\x27\x1c" + b"\x00" * 600)
    every = {tool: (1, {}) for tool in ("bsdtar", "unar", "7z", "7za")}
    tools = Tools(monkeypatch, every)
    with pytest.raises(ExtractionError):
        safe_extract(str(arc), str(tmp_path / "out"))
    assert tools.calls == ["7z", "7za", "bsdtar", "unar"]


def test_unar_keeps_the_archives_own_layout(monkeypatch, rar, tmp_path):
    """-D: no folder of unar's own around several top-level entries - the
    layout the measurement compared against 7-Zip's."""
    seen = []

    def run(cmd, **_kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, b"", b"")
    monkeypatch.setattr(archives, "find_tool",
                        lambda name: "/fake/unar" if name == "unar" else None)
    monkeypatch.setattr(archives.subprocess, "run", run)
    with pytest.raises(ExtractionError):
        safe_extract(rar, str(tmp_path / "out"))
    assert "-D" in seen[0] and "-f" in seen[0]


def test_a_move_that_fails_counts_as_that_tools_failure(monkeypatch, rar, tmp_path):
    """Moving the files into place can fail (on Windows, an antivirus still
    holding one): that tool counts as failed, what it moved is taken out
    again, and the next tool is tried - no bare OSError (review of #93)."""
    tools = Tools(monkeypatch, {
        "bsdtar": (0, {"mod/a.txt": "bsdtar", "zz.txt": "bsdtar"}),
        "unar": (0, {"mod/a.txt": "unar"})})
    real, moved = os.replace, []

    def replace(src, dst):
        if not moved:                       # bsdtar's first entry goes in ...
            moved.append(dst)
            return real(src, dst)
        if len(moved) == 1:                 # ... its second does not
            moved.append(dst)
            raise PermissionError(13, "in use", src)
        return real(src, dst)
    monkeypatch.setattr(archives.os, "replace", replace)
    out = tmp_path / "out"
    safe_extract(rar, str(out))
    assert tools.calls == ["bsdtar", "unar"]
    assert _tree(out) == {"mod/a.txt": "unar"}


def test_a_read_only_folder_a_tool_left_is_still_removed(monkeypatch, rar, tmp_path):
    """A failed tool may restore a read-only folder from the archive; its
    scratch folder is removed all the same, not left beside the destination
    (review of #93). The refusal is simulated - the first removal of the
    file is denied, as in a read-only folder - so the test holds as root."""
    def run(cmd, **_kw):
        locked = os.path.join(_out_dir(cmd), "locked")
        os.makedirs(locked)
        with open(os.path.join(locked, "f.txt"), "w", encoding="utf-8") as fh:
            fh.write("x")
        return subprocess.CompletedProcess(cmd, 1, b"", b"")
    real_unlink, denied = os.unlink, []

    def unlink(name, *args, **kwargs):
        if os.path.basename(str(name)) == "f.txt" and not denied:
            denied.append(name)
            raise PermissionError(13, "Permission denied", name)
        return real_unlink(name, *args, **kwargs)
    monkeypatch.setattr(archives, "find_tool",
                        lambda name: "/fake/bsdtar" if name == "bsdtar" else None)
    monkeypatch.setattr(archives.subprocess, "run", run)
    monkeypatch.setattr(os, "unlink", unlink)
    with pytest.raises(ExtractionError):
        safe_extract(rar, str(tmp_path / "out"))
    assert denied
    assert [n for n in os.listdir(tmp_path) if n.startswith(".unpack-")] == []


def test_windows_own_tar_is_libarchive(monkeypatch, tmp_path):
    """Windows 10 and 11 ship libarchive's bsdtar as System32\\tar.exe; a
    `tar` found on PATH may be Git's GNU tar, which reads no RAR."""
    system = tmp_path / "Windows"
    (system / "System32").mkdir(parents=True)
    (system / "System32" / "tar.exe").write_bytes(b"MZ")
    monkeypatch.setattr(archives.sys, "platform", "win32")
    monkeypatch.setenv("SYSTEMROOT", str(system))
    monkeypatch.setattr(archives.shutil, "which", lambda _name: None)
    assert archives.find_tool("bsdtar") == str(system / "System32" / "tar.exe")


def test_with_no_unpacker_the_player_is_told_what_to_install(monkeypatch, rar, tmp_path):
    monkeypatch.setattr(archives, "find_tool", lambda _name: None)
    with pytest.raises(ExtractionError) as stop:
        safe_extract(rar, str(tmp_path / "out"))
    text = str(stop.value)
    assert "libarchive-tools" in text and "unar" in text and "7-Zip" in text
    assert "p7zip-full" not in text          # Debian's has no RAR code
