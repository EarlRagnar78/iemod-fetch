"""
The programs an install runs - mod_installer and WeiDU (GUI-AUDIT M4 item
22b, ADR-0046) - and where each is found.

* mod_installer: where the player says, else the one the wizard's bundle
  carries beside its own program (packaging/mod_installer.py built it), else
  on PATH. There is no download: upstream's only release, v12.1.1, stops
  after the first component on Linux.
* WeiDU: where the player says, else on PATH, else its official release
  downloaded into this program's per-user tools folder - pinned, checked
  against its sha256 before it is unpacked, unpacked by archives.safe_extract,
  checked again as a program, and only when the player says so. A downloaded
  WeiDU is checked against its sha256 again each time it is found, so a
  program swapped there is not run.

The pins were measured, not copied: WeiDUorg's v251 release zips (GPL-2.0).
The Linux binary is static; the Mac one is x86_64 (Rosetta on Apple
silicon).

A program found is asked its `--version`. One this program was not tested
with is used, with a note: it is the player's choice. A mod_installer older
than 16 on Linux is refused (ADR-0046).
"""
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass

from . import atomic
from .archives import safe_extract
from . import childenv
from .childenv import child_env
from .errors import ConfigError

MOD_INSTALLER, WEIDU = "mod_installer", "weidu"
# what install_run was verified against (CI's real-weidu job, ADR-0045/0046)
VERIFIED = {MOD_INSTALLER: ("16.0.0",), WEIDU: ("25100",)}
_VERSION = {MOD_INSTALLER: re.compile(r"mod_installer (\d+\.\d+\.\d+)"),
            WEIDU: re.compile(r"WeiDU version (\d+)")}
_EXE = ".exe" if sys.platform == "win32" else ""

_WD = "https://github.com/WeiDUorg/weidu/releases/download/v251.00/"


@dataclass(frozen=True)
class Pin:
    tool: str
    version: str
    url: str
    sha256: str                  # of the zip the url serves
    member: str                  # the program inside it
    program_sha256: str          # of the program, as it lies in the tools folder
    licence: str = "GPL-2.0"
    home: str = "https://github.com/WeiDUorg/weidu"

    @property
    def filename(self) -> str:
        return self.tool + (".exe" if self.member.endswith(".exe") else "")


# (tool, sys.platform, platform.machine() lower-cased) -> its pin
PINS: dict[tuple[str, str, str], Pin] = {}
for _machines, _pin in (
        ((("linux", "x86_64"),), Pin(
            WEIDU, "25100", _WD + "WeiDU-Linux-251.zip",
            "3e1a34ec5d6e934b1d4a34541a1312d0170b120c6efe903a732415acde3bd3c0",
            "WeiDU-Linux/weidu",
            "881c6b62e031480c305b11cbdd6acabf8403d5550661d17e505872ccc4c7415d")),
        ((("darwin", "arm64"), ("darwin", "x86_64")), Pin(
            WEIDU, "25100", _WD + "WeiDU-Mac-251.zip",
            "f387eae88aca0d48842708a6a255f6cf6dabe58fc7370cb4521f1661b3a7bc1e",
            "WeiDU-Mac/weidu",
            "4470a51afac576785408a9f90e63951f97447412226cb8bc74850842ea18084c")),
        ((("win32", "amd64"),), Pin(
            WEIDU, "25100", _WD + "WeiDU-Windows-251.zip",
            "a54c6198d6ebed8139793fcacb225500d563657c23fc775b840383f9750493d8",
            "WeiDU-Windows/weidu.exe",
            "0d17e26e3f3ef5b36796eb0ee8ae73cb851d8b62c9702c2e224da2945caafb75"))):
    for _system, _machine in _machines:
        PINS[(_pin.tool, _system, _machine)] = _pin


def pin_for(tool: str, system: str | None = None, machine: str | None = None) -> Pin | None:
    """The pinned download of `tool` for this system, None when there is none."""
    return PINS.get((tool, system or sys.platform, (machine or platform.machine()).lower()))


@dataclass
class Found:
    tool: str
    path: str | None = None
    version: str | None = None
    source: str = ""             # "given" | "bundled" | "PATH" | "downloaded"
    problem: str | None = None   # why it cannot be used; None when it can
    note: str | None = None      # usable, but worth saying

    @property
    def ok(self) -> bool:
        return self.path is not None and self.problem is None


def version_of(tool: str, path: str, timeout: float = 15.0) -> str | None:
    """`path --version`, read: the version, None when it does not answer as `tool`.
    mod_installer loads, and on a version mismatch rewrites, its parser config
    before it reads its arguments (src/main.rs): it is pointed at a folder
    thrown away after, never the player's own (review of #120, ADR-0057)."""
    with tempfile.TemporaryDirectory(prefix="iemod-mi-",
                                     ignore_cleanup_errors=True) as scratch:
        extra = {}
        if tool == MOD_INSTALLER:
            extra = {"APPDATA" if sys.platform == "win32" else "XDG_CONFIG_HOME": scratch}
        try:
            done = childenv.run([path, "--version"], capture_output=True,  # noqa: S603
                                 timeout=timeout, env=child_env(extra or None), check=False)
        except (OSError, subprocess.SubprocessError):
            return None
    match = _VERSION[tool].search(done.stdout.decode("utf-8", "replace")
                                  + done.stderr.decode("utf-8", "replace"))
    return match[1] if match else None


def _sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def downloaded_path(tool: str, tools_dir: str, pin: Pin | None = None) -> str | None:
    """Where the pinned download of `tool` lies in `tools_dir`, if it is there."""
    pin = pin or pin_for(tool)
    return os.path.join(tools_dir, f"{tool}-{pin.version}", pin.filename) if pin else None


def bundled(tool: str) -> str | None:
    """The mod_installer the wizard's bundle carries beside its own program
    (ADR-0046); None when this is not that bundle or it has none."""
    if tool != MOD_INSTALLER or not getattr(sys, "frozen", False):
        return None
    path = os.path.join(os.path.dirname(sys.executable), MOD_INSTALLER + _EXE)
    return path if os.path.isfile(path) else None


def on_path(tool: str) -> str | None:
    """`tool` in PATH's folders only. Not shutil.which: on Windows it looks in
    the current folder first, whatever `path=` says (Python 3.14, read), so a
    weidu.exe in the folder the wizard was started from would be run (review
    of #86)."""
    names = [tool]
    if sys.platform == "win32":
        names = [tool + ext.lower() for ext in
                 os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if ext]
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        if not folder or not os.path.isabs(folder):
            continue                            # "", "." or "bin": the current folder's
        for name in names:
            candidate = os.path.join(folder, name)
            if os.path.isfile(candidate) and (sys.platform == "win32"
                                              or os.access(candidate, os.X_OK)):
                return candidate
    return None


def _examine(tool: str, path: str, source: str, system: str | None = None,
             machine: str | None = None) -> Found:
    found = Found(tool, path, source=source)
    found.version = version_of(tool, path)
    if found.version is None:
        found.problem = f"{path} does not answer --version as {tool} does"
        if tool == WEIDU and (system or sys.platform) == "darwin" \
                and (machine or platform.machine()).lower() == "arm64":
            # WeiDU's Mac build is x86_64 only
            found.problem += (" - on Apple silicon WeiDU needs Rosetta 2: "
                              "softwareupdate --install-rosetta")
    elif tool == MOD_INSTALLER and (system or sys.platform).startswith("linux") \
            and int(found.version.split(".")[0]) < 16:
        found.problem = (f"mod_installer {found.version} stops after the first component "
                         "on Linux (it reads weidu.log, WeiDU writes WeiDU.log); 16 or "
                         "newer is needed")
    elif found.version not in VERIFIED[tool]:
        found.note = (f"{tool} {found.version} is not one this program was tested with "
                      f"({', '.join(VERIFIED[tool])}); it is used as it is")
    return found


def find(tool: str, given: str | None = None, tools_dir: str | None = None) -> Found:
    """
    `tool` where the player says (`given`: no other is looked for), else the
    bundle's (mod_installer), else on PATH, else its pinned download in
    `tools_dir` (WeiDU) - used only while it still matches its sha256.
    """
    if given:
        if not os.path.isfile(given):
            return Found(tool, problem=f"{given} is not a file")
        return _examine(tool, given, "given")
    beside = bundled(tool)
    if beside:
        return _examine(tool, beside, "bundled")
    in_path = on_path(tool)
    if in_path:
        return _examine(tool, in_path, "PATH")
    pin = pin_for(tool)
    path = downloaded_path(tool, tools_dir, pin) if tools_dir else None
    if path and pin and os.path.isfile(path):
        if _sha256(path) != pin.program_sha256:
            return Found(tool, problem=f"{path} is not the {tool} downloaded there "
                                       "(its sha256 changed) - download it again")
        return _examine(tool, path, "downloaded")
    if tool == MOD_INSTALLER:
        return Found(tool, problem="no mod_installer given, none beside this program and "
                                   "none on PATH: give the path of one (16 or newer), or "
                                   "use the wizard's bundle, which carries it")
    return Found(tool, problem=f"no {tool} given, none on PATH"
                               + ("" if pin else ", and none can be downloaded for "
                                  f"this system ({sys.platform} {platform.machine()})"))


def download(client, tool: str, tools_dir: str, progress=None, cancel=None) -> Found:
    """
    Download `tool`'s pin into `tools_dir`, check it, and find it there. Only
    on the player's word: what is downloaded here is run by the install
    (ADR-0046). ConfigError when this system has no pin.
    """
    pin = pin_for(tool)
    if pin is None:
        raise ConfigError(f"no {tool} download for this system ({sys.platform} "
                          f"{platform.machine()}): give the path of one")
    target = os.path.join(tools_dir, f"{tool}-{pin.version}", pin.filename)
    os.makedirs(tools_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix=f".{tool}-", dir=tools_dir)
    try:
        fetched = os.path.join(work, "download.zip")
        # https only, size-capped, its sha256 compared before anything is
        # unpacked (net.HttpClient, ADR-0003)
        client.download(pin.url, fetched, expected_sha256=pin.sha256,
                        progress=progress, cancel=cancel)
        unpacked = os.path.join(work, "unpacked")
        safe_extract(fetched, unpacked)          # no traversal, links or absolute paths
        program = os.path.join(unpacked, *pin.member.split("/"))
        if not os.path.isfile(program) or _sha256(program) != pin.program_sha256:
            raise ConfigError(f"{tool} from {pin.url} is not the program pinned for it")
        os.chmod(program, 0o700)         # run by the install; the folder is per user
        os.makedirs(os.path.dirname(target), exist_ok=True)
        atomic.replace(program, target)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return _examine(tool, target, "downloaded")
