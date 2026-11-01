"""
The programs an install runs (GUI-AUDIT M4 item 22b, ADR-0046): where each
is found, what is said about it, and WeiDU's pinned download - checked before
it is unpacked, unpacked safely, checked again as a program, and checked
again each time it is found.
"""
import hashlib
import io
import os
import re
import sys
import zipfile

import pytest

from iemod_fetch import toolchain
from iemod_fetch.errors import ChecksumMismatch, ConfigError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def program(folder, name, says):
    """A program answering `--version` with `says`, as this system runs one."""
    folder.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        path = folder / (name + ".cmd")
        path.write_text(f"@echo {says}\r\n")
    else:
        path = folder / name
        path.write_text(f"#!/bin/sh\necho '{says}'\n")
        path.chmod(0o755)
    return str(path)


# ------------------------------------------------------------------ found
def test_a_program_given_is_asked_its_version(tmp_path):
    found = toolchain.find("weidu", program(tmp_path, "weidu", "WeiDU version 25100"))
    assert found.ok and found.source == "given" and found.version == "25100"
    assert found.note is None


def test_a_version_not_tested_is_used_with_a_note(tmp_path):
    found = toolchain.find("weidu", program(tmp_path, "weidu", "WeiDU version 24900"))
    assert found.ok and "not one this program was tested with" in found.note


def test_something_that_is_not_the_program_is_refused(tmp_path):
    found = toolchain.find("mod_installer", program(tmp_path, "mi", "hello"))
    assert not found.ok and "does not answer --version" in found.problem
    assert "is not a file" in toolchain.find("weidu", str(tmp_path / "none")).problem


def test_mod_installer_older_than_16_is_refused_on_linux_only(tmp_path):
    """v12.1.1 reads weidu.log, WeiDU writes WeiDU.log (ADR-0046)."""
    old = program(tmp_path, "mod_installer", "mod_installer 12.1.1")
    refused = toolchain._examine("mod_installer", old, "given", system="linux")
    assert "stops after the first component on Linux" in refused.problem
    used = toolchain._examine("mod_installer", old, "given", system="win32")
    assert used.problem is None and "not one this program was tested with" in used.note


def test_the_bundles_mod_installer_comes_before_path(tmp_path, monkeypatch):
    here = tmp_path / "bundle"
    beside = program(here, "mod_installer", "mod_installer 16.0.0")
    if os.name == "nt":                      # the bundle's is an .exe; a .cmd stands in
        monkeypatch.setattr(toolchain, "_EXE", ".cmd")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(here / "iemod-fetch-gui"))
    monkeypatch.setenv("PATH", str(tmp_path / "nothing"))
    found = toolchain.find("mod_installer")
    assert found.ok and found.source == "bundled" and found.path == beside


def test_path_is_looked_in_and_mod_installer_is_never_downloaded(tmp_path, monkeypatch):
    on_path = tmp_path / "bin"
    program(on_path, "weidu", "WeiDU version 25100")
    monkeypatch.setenv("PATH", str(on_path))
    monkeypatch.setenv("PATHEXT", ".CMD;.EXE")
    assert toolchain.find("weidu").source == "PATH"
    missing = toolchain.find("mod_installer", tools_dir=str(tmp_path / "tools"))
    assert "wizard's bundle, which carries it" in missing.problem
    assert all(pin.tool == "weidu" for pin in toolchain.PINS.values())


# ------------------------------------------------------------------ pins
@pytest.mark.parametrize("system,machine,zip_name", [
    ("linux", "x86_64", "WeiDU-Linux-251.zip"), ("win32", "AMD64", "WeiDU-Windows-251.zip"),
    ("darwin", "arm64", "WeiDU-Mac-251.zip"), ("darwin", "x86_64", "WeiDU-Mac-251.zip")])
def test_each_system_has_its_weidu(system, machine, zip_name):
    assert toolchain.pin_for("weidu", system, machine).url.endswith("/v251.00/" + zip_name)


def test_a_system_with_no_pin_gets_none_and_a_download_says_so(tmp_path, monkeypatch):
    assert toolchain.pin_for("weidu", "linux", "aarch64") is None
    monkeypatch.setattr(toolchain, "pin_for", lambda tool: None)
    with pytest.raises(ConfigError, match="give the path of one"):
        toolchain.download(None, "weidu", str(tmp_path))


def test_the_pins_are_the_digests_ci_verifies():
    """ci.yml checks the same zips: one digest per file, or a bump forgot one."""
    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as fh:
        ci = fh.read()
    linux = toolchain.pin_for("weidu", "linux", "x86_64")
    windows = toolchain.pin_for("weidu", "win32", "amd64")
    assert re.search(r"WEIDU_SHA256:\s*(\w+)", ci)[1] == linux.sha256
    assert re.search(r"WEIDU_WIN_SHA256:\s*(\w+)", ci)[1] == windows.sha256
    assert re.search(r"WEIDU_URL:\s*(\S+)", ci)[1] == linux.url
    assert re.search(r"WEIDU_WIN_URL:\s*(\S+)", ci)[1] == windows.url


# ------------------------------------------------------------------ download
SCRIPT = b"#!/bin/sh\necho 'WeiDU version 25100'\n" if os.name != "nt" else \
    b"@echo WeiDU version 25100\r\n"


def release_zip(content=SCRIPT, member="WeiDU-Test/weidu"):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr(member, content)
        zf.writestr("WeiDU-Test/README-WeiDU.html", "<html/>")
    return out.getvalue()


class Client:
    """net.HttpClient's download as the toolchain calls it: the bytes served,
    and its sha256 compared before the file is in place, as the real one does."""

    def __init__(self, served):
        self.served, self.calls = served, []

    def download(self, url, dest, expected_sha256=None, progress=None, cancel=None):
        self.calls.append((url, expected_sha256))
        actual = hashlib.sha256(self.served).hexdigest()
        if expected_sha256 and actual != expected_sha256:
            raise ChecksumMismatch(url, expected_sha256, actual)
        with open(dest, "wb") as fh:
            fh.write(self.served)


@pytest.fixture
def pinned(monkeypatch):
    """A pin of a test release: its zip's and its program's real digests."""
    served = release_zip()
    name = "WeiDU-Test/weidu.cmd" if os.name == "nt" else "WeiDU-Test/weidu"
    if os.name == "nt":
        served = release_zip(member=name)
    pin = toolchain.Pin("weidu", "25100", "https://example.org/WeiDU-Test.zip",
                        hashlib.sha256(served).hexdigest(), name,
                        hashlib.sha256(SCRIPT).hexdigest())
    if os.name == "nt":
        monkeypatch.setattr(toolchain.Pin, "filename", property(lambda self: "weidu.cmd"))
    monkeypatch.setattr(toolchain, "pin_for", lambda tool: pin if tool == "weidu" else None)
    monkeypatch.setenv("PATH", "")
    return pin, served


def leftovers(tools):
    return sorted(os.listdir(tools)) if os.path.isdir(tools) else []


def test_weidu_is_downloaded_checked_and_found_there(tmp_path, pinned):
    pin, served = pinned
    client, tools = Client(served), str(tmp_path / "tools")
    found = toolchain.download(client, "weidu", tools)
    assert client.calls == [(pin.url, pin.sha256)]
    assert found.ok and found.source == "downloaded" and found.version == "25100"
    assert leftovers(tools) == ["weidu-25100"]               # no work folder left
    again = toolchain.find("weidu", tools_dir=tools)
    assert again.ok and again.source == "downloaded"


def test_a_tampered_download_is_refused_and_leaves_nothing(tmp_path, pinned):
    pin, served = pinned
    tampered = bytearray(served)
    tampered[len(tampered) // 2] ^= 0xFF
    tools = str(tmp_path / "tools")
    with pytest.raises(ChecksumMismatch):
        toolchain.download(Client(bytes(tampered)), "weidu", tools)
    assert leftovers(tools) == []


def test_a_zip_whose_program_is_not_the_pinned_one_is_refused(tmp_path, pinned, monkeypatch):
    """The zip's digest matches its pin, the program in it does not: refused."""
    pin, _served = pinned
    other = release_zip(content=b"something else", member=pin.member)
    monkeypatch.setattr(toolchain, "pin_for", lambda tool: toolchain.Pin(
        "weidu", "25100", pin.url, hashlib.sha256(other).hexdigest(), pin.member,
        pin.program_sha256))
    tools = str(tmp_path / "tools")
    with pytest.raises(ConfigError, match="not the program pinned"):
        toolchain.download(Client(other), "weidu", tools)
    assert leftovers(tools) == []


def test_a_zip_reaching_out_of_its_folder_is_refused(tmp_path, pinned, monkeypatch):
    pin, _served = pinned
    evil = release_zip(member="../../escaped")
    monkeypatch.setattr(toolchain, "pin_for", lambda tool: toolchain.Pin(
        "weidu", "25100", pin.url, hashlib.sha256(evil).hexdigest(), pin.member,
        pin.program_sha256))
    tools = tmp_path / "tools"
    with pytest.raises(Exception, match="(?i)unsafe|outside|escape|traversal|\\.\\."):
        toolchain.download(Client(evil), "weidu", str(tools))
    assert leftovers(str(tools)) == []
    assert not (tmp_path / "escaped").exists()


def test_a_downloaded_weidu_changed_since_is_not_run(tmp_path, pinned):
    pin, served = pinned
    tools = str(tmp_path / "tools")
    found = toolchain.download(Client(served), "weidu", tools)
    with open(found.path, "ab") as fh:
        fh.write(b"\n# swapped\n")
    again = toolchain.find("weidu", tools_dir=tools)
    assert not again.ok and "sha256 changed" in again.problem


def test_path_never_means_the_current_folder(tmp_path, monkeypatch):
    """shutil.which on Windows tries the current folder first (review of
    #86): a weidu there is not the one on PATH, and an empty PATH finds none."""
    here, elsewhere = tmp_path / "Downloads", tmp_path / "bin"
    program(here, "weidu", "WeiDU version 1")
    real = program(elsewhere, "weidu", "WeiDU version 25100")
    monkeypatch.chdir(here)
    monkeypatch.setenv("PATHEXT", ".CMD;.EXE")
    program(here / "bin", "weidu", "WeiDU version 2")
    monkeypatch.setenv("PATH", os.pathsep.join(["", os.curdir, "bin", str(elsewhere)]))
    assert toolchain.on_path("weidu") == real
    monkeypatch.setenv("PATH", os.curdir)
    assert toolchain.on_path("weidu") is None


def test_weidu_silent_on_apple_silicon_says_rosetta(tmp_path):
    silent = program(tmp_path, "weidu", "")
    found = toolchain._examine("weidu", silent, "PATH", system="darwin", machine="arm64")
    assert "softwareupdate --install-rosetta" in found.problem
    elsewhere = toolchain._examine("weidu", silent, "PATH", system="linux", machine="x86_64")
    assert "Rosetta" not in elsewhere.problem
