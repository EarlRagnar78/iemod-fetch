"""Extraction safety - the fix for legacy defect L9 (and L10)."""
import gzip
import io
import tarfile
import zipfile

import pytest

from iemod_fetch.archives import Kind, detect_file, detect_kind, safe_extract
from iemod_fetch.errors import ExtractionError, UnsafeArchive


def make_zip(path, entries, symlinks=()):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries:
            zf.writestr(name, data)
        for name, target in symlinks:
            info = zipfile.ZipInfo(name)
            info.external_attr = (0o120777 << 16)
            zf.writestr(info, target)
    return path


def make_tar(path, members):
    with tarfile.open(path, "w:gz") as tf:
        for name, data, kind in members:
            info = tarfile.TarInfo(name)
            if kind == "sym":
                info.type, info.linkname = tarfile.SYMTYPE, data
                tf.addfile(info)
            else:
                payload = data.encode() if isinstance(data, str) else data
                info.size = len(payload)
                tf.addfile(info, io.BytesIO(payload))
    return path


# ------------------------------------------------------------ identification
def test_iemod_is_recognised_as_a_zip_by_content_not_extension(tmp_path):
    p = make_zip(tmp_path / "mod.iemod", [("Mod/Mod.tp2", "BACKUP ~x~")])
    assert detect_file(str(p)) is Kind.ZIP


def test_a_zip_named_temp_bin_is_still_a_zip(tmp_path):
    """The legacy script downloaded everything as `<tp2>_temp.bin`."""
    p = make_zip(tmp_path / "x_temp.bin", [("Mod/Mod.tp2", "x")])
    assert detect_file(str(p)) is Kind.ZIP


def test_plain_gzip_is_not_reported_as_a_tar(tmp_path):
    """Legacy defect L10."""
    p = tmp_path / "blob.gz"
    p.write_bytes(gzip.compress(b"not a tarball"))
    assert detect_file(str(p)) is Kind.GZIP


def test_html_is_not_an_archive():
    assert detect_kind(b"<html><body>404") is Kind.UNKNOWN


# --------------------------------------------------------------- traversal
def test_tar_member_escaping_the_root_is_refused(tmp_path):
    """Legacy defect L9: this wrote outside the destination."""
    arc = make_tar(tmp_path / "evil.tar.gz", [("../outside.txt", "pwned", "file")])
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(UnsafeArchive, match="escapes"):
        safe_extract(str(arc), str(dest))
    assert not (tmp_path / "outside.txt").exists()


def test_zip_member_escaping_the_root_is_refused(tmp_path):
    arc = make_zip(tmp_path / "evil.zip", [("../outside.txt", "pwned")])
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(UnsafeArchive, match="escapes"):
        safe_extract(str(arc), str(dest))
    assert not (tmp_path / "outside.txt").exists()


def test_absolute_paths_are_refused(tmp_path):
    arc = make_zip(tmp_path / "abs.zip", [("/etc/cron.d/pwn", "x")])
    with pytest.raises(UnsafeArchive, match="absolute"):
        safe_extract(str(arc), str(tmp_path / "d"))


def test_zip_symlink_members_are_refused(tmp_path):
    arc = make_zip(tmp_path / "link.zip", [("Mod/Mod.tp2", "x")],
                   symlinks=[("Mod/escape", "/etc/passwd")])
    with pytest.raises(UnsafeArchive, match="symlink"):
        safe_extract(str(arc), str(tmp_path / "d"))


def test_tar_symlink_pointing_outside_is_refused(tmp_path):
    arc = make_tar(tmp_path / "link.tar.gz", [("Mod/escape", "../../../etc/passwd", "sym")])
    with pytest.raises(UnsafeArchive):
        safe_extract(str(arc), str(tmp_path / "d"))


def test_decompression_bomb_is_refused(tmp_path):
    arc = tmp_path / "bomb.zip"
    with zipfile.ZipFile(arc, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big", b"\x00" * (64 * 1024 * 1024))
    with pytest.raises(UnsafeArchive, match="ratio|bomb"):
        safe_extract(str(arc), str(tmp_path / "d"))


# ------------------------------------------------------------- happy paths
def test_normal_mod_zip_extracts(tmp_path):
    arc = make_zip(tmp_path / "m.zip", [("DlcMerger/DlcMerger.tp2", "BACKUP ~x~"),
                                        ("DlcMerger/readme.txt", "hi")])
    dest = tmp_path / "d"
    assert safe_extract(str(arc), str(dest)) is Kind.ZIP
    assert (dest / "DlcMerger" / "DlcMerger.tp2").exists()


def test_normal_mod_tarball_extracts(tmp_path):
    arc = make_tar(tmp_path / "m.tar.gz", [("mod/setup-mod.tp2", "BACKUP ~x~", "file")])
    dest = tmp_path / "d"
    assert safe_extract(str(arc), str(dest)) is Kind.TAR
    assert (dest / "mod" / "setup-mod.tp2").exists()


# ------------------------------------------------------------------ policy
def test_windows_executables_are_not_unpacked_or_run_by_default(tmp_path):
    p = tmp_path / "installer.exe"
    p.write_bytes(b"MZ" + b"\x00" * 600)
    with pytest.raises(ExtractionError, match="never run"):
        safe_extract(str(p), str(tmp_path / "d"))


def test_unrecognised_payload_is_refused(tmp_path):
    p = tmp_path / "junk.zip"
    p.write_bytes(b"this is just text, not an archive at all" * 20)
    with pytest.raises(ExtractionError, match="not a recognised archive"):
        safe_extract(str(p), str(tmp_path / "d"))


def test_missing_external_unpacker_is_an_explicit_error(tmp_path, monkeypatch):
    monkeypatch.setattr("iemod_fetch.archives.shutil.which", lambda _: None)
    p = tmp_path / "m.rar"
    p.write_bytes(b"Rar!\x1a\x07\x00" + b"\x00" * 600)
    with pytest.raises(ExtractionError, match="p7zip-full|unar|unrar"):
        safe_extract(str(p), str(tmp_path / "d"))


# -------------------------------- finding unpackers on Windows (regression: .rar)
def test_a_tool_on_PATH_is_used(monkeypatch):
    from iemod_fetch import archives
    monkeypatch.setattr(archives.shutil, "which", lambda n: f"/usr/bin/{n}")
    assert archives.find_tool("7z") == "/usr/bin/7z"


def test_the_standard_windows_install_directory_is_searched(monkeypatch):
    """7-Zip installs to Program Files and does not add itself to PATH."""
    from iemod_fetch import archives
    monkeypatch.setattr(archives.shutil, "which", lambda _n: None)
    monkeypatch.setattr(archives.os.path, "isfile",
                        lambda p: p == r"C:\Program Files\7-Zip\7z.exe")
    assert archives.find_tool("7z") == r"C:\Program Files\7-Zip\7z.exe"


def test_winrar_is_searched_too(monkeypatch):
    from iemod_fetch import archives
    monkeypatch.setattr(archives.shutil, "which", lambda _n: None)
    monkeypatch.setattr(archives.os.path, "isfile",
                        lambda p: p == r"C:\Program Files\WinRAR\UnRAR.exe")
    assert archives.find_tool("unrar").endswith("UnRAR.exe")


def test_no_tool_anywhere_returns_none(monkeypatch):
    from iemod_fetch import archives
    monkeypatch.setattr(archives.shutil, "which", lambda _n: None)
    monkeypatch.setattr(archives.os.path, "isfile", lambda _p: False)
    assert archives.find_tool("7z") is None


def test_the_missing_unpacker_message_names_the_windows_package(tmp_path, monkeypatch):
    from iemod_fetch import archives
    monkeypatch.setattr(archives.shutil, "which", lambda _n: None)
    monkeypatch.setattr(archives.os.path, "isfile", lambda _p: False)
    p = tmp_path / "m.rar"
    p.write_bytes(b"Rar!\x1a\x07\x00" + b"\x00" * 600)
    with pytest.raises(ExtractionError, match="winget install 7zip"):
        safe_extract(str(p), str(tmp_path / "d"))
