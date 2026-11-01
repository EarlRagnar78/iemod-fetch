"""
packaging/gui_bundle.py (GUI-AUDIT item 20, ADR-0040): the helpers that do not
need PyInstaller - the zip's name, its licence files and its bytes, which are
the same for the same folder.
"""
import importlib.util
import os
import stat
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = importlib.util.spec_from_file_location(
    "gui_bundle", os.path.join(ROOT, "packaging", "gui_bundle.py"))
assert SPEC and SPEC.loader
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)

VERSIONS = {"qt": "6.12.0", "pyside6": "6.12.0", "pyinstaller": "6.22.3",
            "python": "3.12.3"}


def program(tmp_path):
    folder = tmp_path / "out" / bundle.NAME
    (folder / "_internal" / "PySide6").mkdir(parents=True)
    (folder / bundle.NAME).write_bytes(b"\x7fELF program")
    (folder / "_internal" / "PySide6" / "libQt6Core.so.6").write_bytes(b"qt")
    return folder


@pytest.mark.parametrize("system,machine,expected", [
    ("Linux", "x86_64", "linux-x86_64"), ("Windows", "AMD64", "windows-x86_64"),
    ("Darwin", "arm64", "macos-arm64"), ("Linux", "aarch64", "linux-arm64")])
def test_the_zip_is_named_for_its_system(monkeypatch, system, machine, expected):
    monkeypatch.setattr(bundle.platform, "system", lambda: system)
    monkeypatch.setattr(bundle.platform, "machine", lambda: machine)
    assert bundle.tag() == expected


def test_the_qt_notice_names_the_licence_versions_and_source():
    text = bundle.notice(VERSIONS)
    assert "LGPL-3.0-only" in text and "Qt 6.12.0" in text and "PySide6 6.12.0" in text
    assert "https://download.qt.io/official_releases/qt/" in text
    assert "licenses/LGPL-3.0-only.txt" in text and "licenses/GPL-3.0-only.txt" in text


def test_the_folder_carries_the_licences(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle, "versions", lambda: VERSIONS)
    folder = program(tmp_path)
    bundle.add_licences(str(folder))
    assert (folder / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")
    assert sorted(os.listdir(folder / "licenses")) == ["GPL-3.0-only.txt",
                                                       "LGPL-3.0-only.txt",
                                                       "Python-LICENSE.txt",
                                                       "filelock-LICENSE",
                                                       "publicsuffixlist-LICENSE"]
    # MIT asks for its text and notice, which the licence file is: no source offer
    assert "MIT License" in (folder / "licenses" / "filelock-LICENSE").read_text(encoding="utf-8")
    assert not (folder / "NOTICE-filelock.txt").exists()
    # the runtime library's own licence, MPL-2.0 (ADR-0043)
    mpl = (folder / "licenses" / "publicsuffixlist-LICENSE").read_text(encoding="utf-8")
    assert "Mozilla Public License" in mpl
    notice = (folder / "NOTICE-publicsuffixlist.txt").read_text(encoding="utf-8")
    assert "unmodified" in notice and "https://pypi.org/project/publicsuffixlist/" in notice
    lgpl = (folder / "licenses" / "LGPL-3.0-only.txt").read_text(encoding="utf-8")
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in lgpl and "Version 3" in lgpl
    assert "Qt 6.12.0" in (folder / "NOTICE-Qt.txt").read_text(encoding="utf-8")


def test_the_same_folder_zips_to_the_same_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle, "tag", lambda: "linux-x86_64")
    folder = program(tmp_path)
    first = bundle.pack(str(folder), str(tmp_path / "a"))
    os.utime(folder / bundle.NAME, (1_900_000_000, 1_900_000_000))
    second = bundle.pack(str(folder), str(tmp_path / "b"))
    with open(first, "rb") as a, open(second, "rb") as b:
        assert a.read() == b.read()
    assert os.path.basename(first) == "iemod-fetch-gui-linux-x86_64.zip"
    with zipfile.ZipFile(first) as zf:
        assert zf.namelist() == [f"{bundle.NAME}/{bundle.NAME}",
                                 f"{bundle.NAME}/_internal/PySide6/libQt6Core.so.6"]


def links(base):
    """Qt's framework links as a macOS .app holds them; skip where none can be made."""
    if os.name == "nt":             # Windows builds hold no links; its links take no '/'
        pytest.skip("links are a macOS and Linux matter")
    versions = base / "QtCore.framework" / "Versions"
    (versions / "A").mkdir(parents=True)
    (versions / "A" / "QtCore").write_bytes(b"qt")
    try:
        os.symlink("A", versions / "Current", target_is_directory=True)
        os.symlink("Versions/Current/QtCore", versions.parent / "QtCore")
    except OSError:                 # Windows without the privilege to make links
        pytest.skip("cannot make a symbolic link here")


def test_links_in_a_macos_app_stay_links(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle, "tag", lambda: "macos-arm64")
    app = tmp_path / "out" / f"{bundle.NAME}.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / bundle.NAME).write_bytes(b"program")
    links(app / "Contents" / "Frameworks")
    path = bundle.pack(str(app), str(tmp_path / "dist"))
    with zipfile.ZipFile(path) as zf:
        entries = {i.filename: i for i in zf.infolist()}
        prefix = f"{bundle.NAME}.app/Contents/Frameworks/QtCore.framework/"
        for name, target in ((prefix + "Versions/Current", b"A"),
                             (prefix + "QtCore", b"Versions/Current/QtCore")):
            assert stat.S_ISLNK(entries[name].external_attr >> 16)
            assert zf.read(name) == target
        assert prefix + "Versions/Current/QtCore" not in entries     # not a copy


def test_linux_links_stay_links_and_unpack_as_links(tmp_path, monkeypatch):
    # Review of #42: following them doubled Qt in the zip (60 to 89 MB), and a
    # library replaced as NOTICE-Qt.txt says still loaded from its other copy
    monkeypatch.setattr(bundle, "tag", lambda: "linux-x86_64")
    monkeypatch.setattr(bundle.platform, "system", lambda: "Linux")
    folder = program(tmp_path)
    links(folder / "_internal")
    path = bundle.pack(str(folder), str(tmp_path / "dist"))
    with zipfile.ZipFile(path) as zf:
        prefix = f"{bundle.NAME}/_internal/QtCore.framework/"
        assert stat.S_ISLNK(zf.getinfo(prefix + "QtCore").external_attr >> 16)
    bundle.unpack(path, str(tmp_path / "unpacked"))
    unpacked = tmp_path / "unpacked" / bundle.NAME / "_internal" / "QtCore.framework"
    assert os.path.islink(unpacked / "QtCore")
    assert (unpacked / "QtCore").read_bytes() == b"qt"


@pytest.mark.skipif(os.name == "nt", reason="file modes are POSIX")
def test_the_unpacked_program_is_still_executable(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle, "tag", lambda: "linux-x86_64")
    monkeypatch.setattr(bundle.platform, "system", lambda: "Linux")
    folder = program(tmp_path)
    os.chmod(folder / bundle.NAME, 0o700)
    path = bundle.pack(str(folder), str(tmp_path / "dist"))
    bundle.unpack(path, str(tmp_path / "unpacked"))
    unpacked = tmp_path / "unpacked" / bundle.NAME / bundle.NAME
    assert unpacked.read_bytes() == b"\x7fELF program"
    assert os.stat(unpacked).st_mode & 0o100


def test_a_bundle_with_another_version_than_the_pin_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle.importlib.metadata, "version", lambda name: "0.0.1")
    with pytest.raises(SystemExit, match="pins"):
        bundle.build(str(tmp_path))


def test_mod_installer_goes_beside_the_program_with_its_licence(tmp_path):
    """ADR-0046: the program the wizard installs with, beside the wizard's
    own, its GPL-3.0 text and a notice of its source at the commit built."""
    folder = program(tmp_path)
    built = tmp_path / "built"
    built.mkdir()
    name = "mod_installer" + (".exe" if os.name == "nt" else "")
    (built / name).write_bytes(b"\x7fELF mod_installer")
    (built / "LICENSE").write_text("GNU GENERAL PUBLIC LICENSE\nVersion 3", encoding="utf-8")
    bundle.add_mod_installer(str(folder), str(built))
    assert (folder / name).read_bytes() == b"\x7fELF mod_installer"
    assert "GENERAL PUBLIC LICENSE" in (folder / "licenses" / "mod_installer-LICENSE").read_text(
        encoding="utf-8")
    notice = (folder / "NOTICE-mod_installer.txt").read_text(encoding="utf-8")
    assert "unmodified" in notice and "General Public License v3.0" in notice
    assert "https://github.com/dark0dave/mod_installer/tree/3b6827a" in notice
    assert "mod_installer-16.0.0-source.tar.gz" in notice


# --- the libraries a bundle takes from the build system (GUI-AUDIT item 61) --

def _with_libraries(tmp_path, names):
    folder = tmp_path / "b"
    for name in names:
        path = folder / "_internal" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x7fELF")
    return folder


def test_only_what_the_build_system_gave_is_counted(tmp_path):
    folder = _with_libraries(tmp_path, [
        "libssl.so.3", "libz.so.1", "libfoo.so",
        "libpython3.14.so.1.0",                                   # Python's (PSF)
        "python3.14/lib-dynload/_ssl.cpython-314-x86_64-linux-gnu.so",
        "libpyside6.abi3.so.6.12",                                # the wheel's
        "PySide6/Qt/lib/libQt6Core.so.6", "shiboken6/libshiboken6.abi3.so.6.12",
        "readme.txt"])
    assert bundle.system_libraries(str(folder)) == ["libfoo.so", "libssl.so.3", "libz.so.1"]


@pytest.mark.skipif(os.name == "nt", reason="symbolic links")
def test_a_link_into_a_wheels_folder_is_the_wheels(tmp_path):
    folder = _with_libraries(tmp_path, ["PySide6/Qt/lib/libicuuc.so.73", "libssl.so.3"])
    os.symlink("PySide6/Qt/lib/libicuuc.so.73", folder / "_internal" / "libicuuc.so.73")
    assert bundle.system_libraries(str(folder)) == ["libssl.so.3"]


@pytest.mark.skipif(not os.path.isfile("/usr/share/doc/zlib1g/copyright"),
                    reason="needs a Debian or Ubuntu system's zlib1g")
def test_each_library_ships_with_its_package_copyright_and_source(tmp_path):
    folder = _with_libraries(tmp_path, ["libz.so.1"])
    owners = {"libz.so.1": ("zlib1g", "1:1.3.dfsg-3.1ubuntu2.2", "zlib",
                            "1:1.3.dfsg-3.1ubuntu2.2")}
    got = bundle.add_system_licences(str(folder), str(folder), owners.get, distro="ubuntu")
    assert got == ["zlib1g"]
    assert (folder / "licenses" / "system" / "zlib1g.copyright").read_text(encoding="utf-8")
    notice = (folder / "NOTICE-system-libraries.txt").read_text(encoding="utf-8")
    assert "libz.so.1" in notice and "zlib1g 1:1.3.dfsg-3.1ubuntu2.2" in notice
    assert "https://launchpad.net/ubuntu/+source/zlib/1:1.3.dfsg-3.1ubuntu2.2" in notice


def test_a_library_no_package_owns_stops_the_build(tmp_path):
    folder = _with_libraries(tmp_path, ["libmystery.so.1"])
    with pytest.raises(SystemExit, match="libmystery.so.1"):
        bundle.add_system_licences(str(folder), str(folder), lambda name: None, distro="ubuntu")


def test_no_system_library_writes_no_notice(tmp_path):
    folder = _with_libraries(tmp_path, ["libpython3.14.so.1.0"])
    assert bundle.add_system_licences(str(folder), str(folder), lambda name: None) == []
    assert not (folder / "NOTICE-system-libraries.txt").exists()


@pytest.mark.parametrize("distro, expected", [
    ("ubuntu", "https://launchpad.net/ubuntu/+source/openssl/3.0.13-0ubuntu3.16"),
    ("debian", "https://sources.debian.org/src/openssl/3.0.13-0ubuntu3.16/"),
    ("fedora", "apt-get source openssl=3.0.13-0ubuntu3.16")])
def test_the_source_is_named_where_the_distribution_keeps_it(distro, expected):
    assert bundle.source_link(distro, "openssl", "3.0.13-0ubuntu3.16") == expected


@pytest.mark.skipif(not os.path.isfile("/var/lib/dpkg/status"), reason="needs dpkg")
def test_dpkg_names_the_package_of_a_real_library():
    found = bundle.debian_package("libz.so.1")
    assert found is not None and found[0].startswith("zlib1g") and found[2] == "zlib"
    assert bundle.debian_package("libno-such-library.so.9") is None


def _fake_system(tmp_path, copyright_text):
    docs = tmp_path / "doc" / "libfoo1"
    docs.mkdir(parents=True)
    (docs / "copyright").write_text(copyright_text, encoding="utf-8")
    common = tmp_path / "common"
    common.mkdir()
    (common / "LGPL-2.1").write_text("GNU LESSER GENERAL PUBLIC LICENSE 2.1", encoding="utf-8")
    (common / "Apache-2.0").write_text("Apache License 2.0", encoding="utf-8")
    owner = {"libfoo.so.1": ("libfoo1", "1.0-1", "foo", "1.0-1")}
    return str(tmp_path / "doc"), str(common), owner.get


def test_the_common_licences_a_copyright_file_names_ship_too(tmp_path):
    """Debian's copyright files point at /usr/share/common-licenses/<X>
    without its text (review of #121)."""
    docs, common, owner = _fake_system(tmp_path, (
        "License: LGPL-2.1+\n On Debian systems, see /usr/share/common-licenses/LGPL-2.1.\n"
        "License: Apache-2.0\n see /usr/share/common-licenses/Apache-2.0\n"))
    folder = _with_libraries(tmp_path, ["libfoo.so.1"])
    bundle.add_system_licences(str(folder), str(folder), owner, distro="debian",
                               common=common, docs=docs)
    texts = folder / "licenses" / "system" / "common-licenses"
    assert sorted(os.listdir(texts)) == ["Apache-2.0", "LGPL-2.1"]
    assert "LESSER" in (texts / "LGPL-2.1").read_text(encoding="utf-8")


def test_a_named_licence_with_no_text_stops_the_build(tmp_path):
    docs, common, owner = _fake_system(tmp_path, "see /usr/share/common-licenses/MPL-1.1\n")
    folder = _with_libraries(tmp_path, ["libfoo.so.1"])
    with pytest.raises(SystemExit, match="MPL-1.1"):
        bundle.add_system_licences(str(folder), str(folder), owner, distro="debian",
                                   common=common, docs=docs)


def test_linux_without_dpkg_stops_rather_than_ship_no_licence(tmp_path, monkeypatch):
    folder = _with_libraries(tmp_path, ["libssl.so.3"])
    monkeypatch.setattr(bundle.shutil, "which", lambda name: None)
    monkeypatch.setattr(bundle.platform, "system", lambda: "Linux")
    with pytest.raises(SystemExit, match="dpkg-query"):
        bundle.add_system_licences(str(folder), str(folder))
    monkeypatch.setattr(bundle.platform, "system", lambda: "Windows")
    assert bundle.add_system_licences(str(folder), str(folder)) == []


def test_a_build_that_carries_readline_stops(tmp_path):
    folder = _with_libraries(tmp_path, ["libreadline.so.8"])
    with pytest.raises(SystemExit, match="libreadline.so.8"):
        bundle.check_unwanted(str(folder))
    bundle.check_unwanted(str(_with_libraries(tmp_path / "ok", ["libssl.so.3"])))
