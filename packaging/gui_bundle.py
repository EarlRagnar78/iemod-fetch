#!/usr/bin/env python3
"""
Build the wizard as a program that needs no Python (GUI-AUDIT item 20,
ADR-0040): PyInstaller, one folder, zipped as
`dist/iemod-fetch-gui-<os>-<arch>.zip`, then started once to prove it runs.

    pip install "iemod-fetch[gui]" pyinstaller
    python packaging/gui_bundle.py [--dist dist] [--mod-installer DIR]

`--mod-installer DIR`: what packaging/mod_installer.py built there - the
program the wizard installs with (ADR-0046) goes beside the wizard's own,
with its licence (GPL-3.0) and a NOTICE saying where its source is.

One folder, not one file: Qt is LGPL-3.0, and its libraries stay separate
files beside the program, which a user may replace with their own build of
Qt (LGPL-3.0 section 4). The folder carries this project's licence, the LGPL
and GPL texts and NOTICE-Qt.txt, which says where Qt's and PySide6's source
is. The command line has its own bundle, built the same way: cli_bundle.py.

The zip is unpacked again and the program in it started with --check
(offscreen): a build, or a zip, that cannot open its window fails here, not on
a player's machine. On macOS the .app is signed again, ad hoc, once the licence
files are in it. Links stay links in the zip (a .app's frameworks, Linux's
library names), as `unzip` and desktop archive tools restore them: copies would
double Qt's size and leave two files to replace for one library.
"""
import argparse
import importlib.metadata
import os
import re
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "iemod-fetch-gui"
with open(os.path.join(ROOT, "requirements", "runtime.txt"), encoding="utf-8") as _fh:
    RUNTIME_PINS = dict(re.findall(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", _fh.read(),
                                   re.MULTILINE))
RUNTIME = tuple(RUNTIME_PINS)
FIXED = (1980, 1, 1, 0, 0, 0)                 # every entry's date: same folder, same zip
ENTRY = "import sys\nfrom iemod_fetch_gui.app import main\n\nsys.exit(main())\n"
# Qt modules the wizard never uses: kept out to keep the download small.
# readline: GNU Readline (GPL-3.0) for an interactive prompt neither program
# has; left out, so is the library (GUI-AUDIT item 61).
EXCLUDE = ("tkinter", "readline", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
           "PySide6.QtWebEngineCore", "PySide6.QtMultimedia", "PySide6.Qt3DCore")


def tag() -> str:
    system = {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), "linux")
    machine = platform.machine().lower().replace("amd64", "x86_64").replace("aarch64", "arm64")
    return f"{system}-{machine}"


def notice(versions: dict) -> str:
    return f"""iemod-fetch-gui bundles third-party software.

Qt {versions['qt']} and PySide6 {versions['pyside6']} (with shiboken6) are used
under the GNU Lesser General Public License v3.0 (LGPL-3.0-only); its text is
licenses/LGPL-3.0-only.txt, and the GPL it extends is licenses/GPL-3.0-only.txt.
They are dynamically linked: Qt's and PySide6's libraries are separate files in
this folder (under _internal, or Contents/Frameworks in the macOS app), and you
may replace them with your own builds of the same versions.

Source code:
  Qt       https://download.qt.io/official_releases/qt/
  PySide6  https://download.qt.io/official_releases/QtForPython/pyside6/
           https://code.qt.io/cgit/pyside/pyside-setup.git/

The Python {versions['python']} runtime is under the PSF License Agreement
(licenses/Python-LICENSE.txt, https://docs.python.org/3/license.html). The
libraries this folder takes from the system it was built on, if any, are in
NOTICE-system-libraries.txt with their licences. The program was built with
PyInstaller {versions['pyinstaller']}, whose bootloader exception allows this
distribution (https://pyinstaller.org/en/stable/license.html).

iemod-fetch itself is under the MIT License: LICENSE.
"""


def versions() -> dict:
    import PyInstaller
    import PySide6
    from PySide6 import QtCore
    return {"qt": QtCore.qVersion(), "pyside6": PySide6.__version__,
            "pyinstaller": PyInstaller.__version__,
            "python": platform.python_version()}


def build(work: str) -> str:
    entry = os.path.join(work, "iemod_fetch_gui_main.py")
    with open(entry, "w", encoding="utf-8") as fh:
        fh.write(ENTRY)
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
            "--windowed", "--name", NAME, "--distpath", os.path.join(work, "out"),
            "--workpath", os.path.join(work, "build"), "--specpath", work,
            "--paths", ROOT]
    for module in EXCLUDE:
        args += ["--exclude-module", module]
    args += runtime_args()
    subprocess.run(args + [entry], check=True, cwd=work)
    folder = os.path.join(work, "out", NAME)
    if platform.system() == "Darwin" and os.path.isdir(os.path.join(work, "out",
                                                                     NAME + ".app")):
        folder = os.path.join(work, "out", NAME + ".app")
    return folder


def runtime_args() -> list[str]:
    """The runtime's libraries (ADR-0043) with their data and metadata: the
    Public Suffix List is a data file PyInstaller does not see by itself. The
    pinned version, as build.py checks for the .pyz."""
    args = []
    for name, pinned in RUNTIME_PINS.items():
        installed = importlib.metadata.version(name)
        if installed != pinned:
            raise SystemExit(f"{name} {installed} is installed, requirements/runtime.txt "
                             f"pins {pinned}")
        args += ["--collect-data", name, "--copy-metadata", name]
    return args


def executable(folder: str) -> str:
    if folder.endswith(".app"):
        return os.path.join(folder, "Contents", "MacOS", NAME)
    return os.path.join(folder, NAME + (".exe" if os.name == "nt" else ""))


def add_licences(folder: str) -> None:
    target = folder if not folder.endswith(".app") else os.path.join(
        folder, "Contents", "Resources")
    shutil.copy(os.path.join(ROOT, "LICENSE"), os.path.join(target, "LICENSE"))
    licences = os.path.join(target, "licenses")
    os.makedirs(licences, exist_ok=True)
    for name in sorted(os.listdir(os.path.join(ROOT, "packaging", "licenses"))):
        shutil.copy(os.path.join(ROOT, "packaging", "licenses", name), licences)
    add_runtime_licences(target)
    shutil.copy(python_licence(), os.path.join(licences, "Python-LICENSE.txt"))
    add_system_licences(folder, target)
    with open(os.path.join(target, "NOTICE-Qt.txt"), "w", encoding="utf-8") as fh:
        fh.write(notice(versions()))


def python_licence() -> str:
    """The interpreter's own LICENSE.txt: beside the standard library on
    POSIX, in the installation's root on Windows (where it also carries the
    texts of the libraries python.org's build links: OpenSSL, libffi, bzip2...)."""
    import sysconfig
    for place in (sysconfig.get_paths()["stdlib"], sys.base_prefix):
        path = os.path.join(place, "LICENSE.txt")
        if os.path.isfile(path):
            return path
    raise SystemExit("build aborted: this Python has no LICENSE.txt to ship with it")


# "/usr/share/common-licenses/GPL-2." in a Debian copyright file
_COMMON = re.compile(r"/usr/share/common-licenses/([\w.+-]+)")
# A shared library's file name: libssl.so.3, libz.so.1, libfoo.so
_SHARED = re.compile(r"\.so(\.\d+)*$")


def system_libraries(folder: str) -> list[str]:
    """The shared libraries PyInstaller took from the build system into the
    folder: not Python's own (libpython, its extension modules), not what a
    wheel brought (PySide6's Qt, shiboken6: NOTICE-Qt.txt says those)."""
    wheels = ("PySide6", "shiboken6")
    found = set()
    for here, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in wheels]
        for name in files:
            # a link into a wheel's folder (_internal/libQt6Core.so.6) is the wheel's
            real = os.path.relpath(os.path.realpath(os.path.join(here, name)),
                                   os.path.realpath(folder)).replace("\\", "/").split("/")
            if (_SHARED.search(name) and ".cpython-" not in name and ".abi3." not in name
                    and not name.startswith("libpython3") and not set(real) & set(wheels)):
                found.add(name)
    return sorted(found)


def debian_package(name: str) -> tuple[str, str, str, str] | None:
    """(package, version, source package, source version) that installed the
    library `name` on this system, as dpkg says; None when none did."""
    owner = None
    # the path the loader resolves the name to (where PyInstaller took it),
    # then any path: a basename alone can match a second copy elsewhere
    cache = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True, check=False)
    for line in cache.stdout.splitlines():
        if line.strip().startswith(name + " ") and "=>" in line:
            path = os.path.realpath(line.split("=>", 1)[1].strip())
            found = subprocess.run(["dpkg-query", "-S", path], capture_output=True,
                                   text=True, check=False)
            if found.returncode == 0:
                owner = found
                break
    if owner is None:
        owner = subprocess.run(["dpkg-query", "-S", f"*/{name}"], capture_output=True,
                               text=True, check=False)
    if owner.returncode != 0:
        return None
    package = owner.stdout.splitlines()[0].split(": ", 1)[0].split(", ")[0]
    fields = subprocess.run(["dpkg-query", "-W", "-f",
                             "${Package}\t${Version}\t${source:Package}\t${source:Version}",
                             package], capture_output=True, text=True, check=False)
    parts = fields.stdout.split("\t")
    return (parts[0], parts[1], parts[2], parts[3]) if fields.returncode == 0 and \
        len(parts) == 4 else None


def source_link(distro: str, source: str, version: str) -> str:
    if distro == "ubuntu":
        return f"https://launchpad.net/ubuntu/+source/{source}/{version}"
    if distro == "debian":
        return f"https://sources.debian.org/src/{source}/{version}/"
    return f"apt-get source {source}={version}"


def _distro() -> str:
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            return dict(line.rstrip("\n").split("=", 1) for line in fh
                        if "=" in line).get("ID", "").strip('"')
    except OSError:
        return ""


def add_system_licences(folder: str, target: str, package_of=debian_package,
                        distro: str | None = None,
                        common: str = "/usr/share/common-licenses",
                        docs: str = "/usr/share/doc") -> list[str]:
    """For each library the build system gave the folder (GUI-AUDIT item 61):
    its package's copyright file under licenses/system/, and a line in
    NOTICE-system-libraries.txt with the package, its version and where its
    source is. Measured on Debian and Ubuntu (dpkg); a library no package owns
    stops the build - it would ship without its licence. Elsewhere (Windows,
    macOS: python.org's builds) Python's LICENSE.txt is the record."""
    libraries = system_libraries(folder)
    if not libraries:
        return []
    if package_of is debian_package and not shutil.which("dpkg-query"):
        if platform.system() != "Linux":
            return []                 # Windows, macOS: Python's LICENSE.txt is the record
        raise SystemExit("build aborted: this Linux system has no dpkg-query to say whose "
                         "these bundled libraries are, so no licence would ship with them: "
                         + ", ".join(libraries))
    distro = _distro() if distro is None else distro
    owned: dict[str, tuple[tuple[str, str, str, str], list[str]]] = {}
    unowned = []
    for name in libraries:
        found = package_of(name)
        if found is None:
            unowned.append(name)
        else:
            owned.setdefault(found[0], (found, []))[1].append(name)
    if unowned:
        raise SystemExit("build aborted: no package says where these bundled libraries "
                         "come from, so no licence ships with them: " + ", ".join(unowned))
    system = os.path.join(target, "licenses", "system")
    os.makedirs(system, exist_ok=True)
    lines = []
    referred: set[str] = set()
    for package in sorted(owned):
        (_, version, source, source_version), names = owned[package]
        copyright_file = os.path.join(docs, package, "copyright")
        if os.path.isfile(copyright_file):
            shutil.copy(copyright_file, os.path.join(system, package + ".copyright"))
            text = f"licenses/system/{package}.copyright"
            with open(copyright_file, encoding="utf-8", errors="replace") as fh:
                referred |= {name.rstrip(".") for name in _COMMON.findall(fh.read())}
        else:
            raise SystemExit(f"build aborted: {package} ships no copyright file "
                             f"({copyright_file}) for {', '.join(names)}")
        lines.append(f"{', '.join(names)}\n  {package} {version} - {text}\n"
                     f"  source: {source_link(distro, source, source_version)}\n")
    # Debian's copyright files name the common licences by path, without
    # their text (review of #121): the texts they name ship too
    if referred:
        texts = os.path.join(system, "common-licenses")
        os.makedirs(texts, exist_ok=True)
        missing = [name for name in sorted(referred)
                   if not os.path.isfile(os.path.join(common, name))]
        if missing:
            raise SystemExit("build aborted: a copyright file names a licence this system "
                             f"has no text of ({common}): " + ", ".join(missing))
        for name in sorted(referred):
            shutil.copyfile(os.path.realpath(os.path.join(common, name)),
                            os.path.join(texts, name))
    with open(os.path.join(target, "NOTICE-system-libraries.txt"), "w",
              encoding="utf-8") as fh:
        fh.write(f"""Libraries this folder carries from the system it was built on ({distro or "unknown"}),
unmodified, each a separate file under _internal that you may replace with your
own build. Each one's licence is its package's copyright file; the common
licences those files name (/usr/share/common-licenses/...) are in
licenses/system/common-licenses/. The LGPL and GPL ones are offered in source at
the address given, the exact version shipped.

""" + "\n".join(lines))
    return sorted(owned)


def add_runtime_licences(target: str) -> None:
    """The runtime's libraries (ADR-0043): each one's licence file under
    licenses/, and for an MPL-2.0 one the NOTICE that says where its source is.
    The wizard's bundle and the command line's (cli_bundle.py) both carry them."""
    licences = os.path.join(target, "licenses")
    os.makedirs(licences, exist_ok=True)
    for name in RUNTIME:                     # publicsuffixlist MPL-2.0, filelock MIT
        dist = importlib.metadata.distribution(name)
        if dist.metadata.get("License-Expression") == "MPL-2.0":
            # MPL-2.0 3.2(a): where the Source Code Form of what ships compiled is
            urls = dict(url.split(", ", 1) for url in dist.metadata.get_all("Project-URL") or ())
            with open(os.path.join(target, f"NOTICE-{name}.txt"), "w", encoding="utf-8") as fh:
                fh.write(f"{name} {dist.version}, unmodified, is part of this program, under "
                         f"the Mozilla Public License 2.0 (licenses/{name}-LICENSE).\n"
                         f"Its source code: https://pypi.org/project/{name}/{dist.version}/#files"
                         + (f" and {urls['Homepage']}" if "Homepage" in urls else "") + "\n")
        for entry in dist.files or ():
            if "licenses" in str(entry).replace("\\", "/").split("/") or \
                    entry.name.startswith(("LICENSE", "COPYING")):
                shutil.copy(str(entry.locate()),
                            os.path.join(licences, f"{name}-{entry.name}"))


def program_dir(folder: str) -> str:
    """Where the wizard's own program lies, and mod_installer beside it."""
    return os.path.dirname(executable(folder))


def add_mod_installer(folder: str, built: str) -> None:
    """mod_installer, as packaging/mod_installer.py built it in `built`."""
    sys.path.insert(0, os.path.join(ROOT, "packaging"))
    import mod_installer as recipe
    name = "mod_installer" + (".exe" if os.name == "nt" else "")
    shutil.copy2(os.path.join(built, name), os.path.join(program_dir(folder), name))
    target = folder if not folder.endswith(".app") else os.path.join(
        folder, "Contents", "Resources")
    licences = os.path.join(target, "licenses")
    os.makedirs(licences, exist_ok=True)
    shutil.copy(os.path.join(built, "LICENSE"), os.path.join(licences, "mod_installer-LICENSE"))
    with open(os.path.join(target, "NOTICE-mod_installer.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"""mod_installer {recipe.VERSION}, by dark0dave, unmodified, is a separate program
in this folder ({name}), under the GNU General Public License v3.0
(licenses/mod_installer-LICENSE). The wizard runs it to install mods.

It was built with Rust {recipe.RUST} by packaging/mod_installer.py of
iemod-fetch, from this source (its Corresponding Source):
  {recipe.SOURCE}, attached to the same iemod-fetch release as this
  bundle, on its GitHub release page - and, while upstream keeps it, at
  {recipe.REPOSITORY}/tree/{recipe.REV}
The Rust libraries it links are those its Cargo.lock names, from crates.io.
""")


def sign(folder: str) -> None:
    """Re-sign a macOS .app ad hoc: the licence files added after PyInstaller
    signed it would otherwise break its signature, and macOS refuses it."""
    if folder.endswith(".app"):
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", folder], check=True)
        subprocess.run(["codesign", "--verify", "--deep", "--strict", folder], check=True)


# GPL-3.0 libraries neither program uses: a build that carries one stops
_UNWANTED = re.compile(r"^lib(readline|gdbm)\b")


def check_unwanted(folder: str) -> None:
    found = sorted(name for _here, _dirs, files in os.walk(folder) for name in files
                   if _UNWANTED.match(name))
    if found:
        raise SystemExit("build aborted: the bundle carries GPL-3.0 libraries it does not "
                         "use: " + ", ".join(found))


def check(folder: str, work: str) -> None:
    """Start the built program once, offscreen, as a player would."""
    check_unwanted(folder)
    project = os.path.join(work, "project")
    os.makedirs(project, exist_ok=True)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    done = subprocess.run([executable(folder), "--check", "--project", project],
                          env=env, capture_output=True, text=True, timeout=120,
                          check=False)
    if done.returncode != 0 or "ok" not in done.stdout:
        raise SystemExit(f"the built program does not start (exit {done.returncode}):\n"
                         f"{done.stdout}\n{done.stderr}")
    beside = os.path.join(program_dir(folder),
                          "mod_installer" + (".exe" if os.name == "nt" else ""))
    if os.path.exists(beside):
        said = subprocess.run([beside, "--version"], capture_output=True, text=True,
                              timeout=60, check=False).stdout.strip()
        if not said.startswith("mod_installer "):
            raise SystemExit(f"the bundled mod_installer does not start: {said!r}")


def unpack(path: str, into: str) -> None:
    """Unzip as a player would: ditto on macOS; elsewhere as `unzip` does, links
    made again and the files' modes restored, so the program stays executable."""
    os.makedirs(into, exist_ok=True)
    if platform.system() == "Darwin":
        subprocess.run(["ditto", "-x", "-k", path, into], check=True)
        return
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            mode = info.external_attr >> 16
            target = os.path.join(into, *info.filename.split("/"))
            if stat.S_ISLNK(mode):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.symlink(zf.read(info).decode("utf-8"), target)
                continue
            zf.extract(info, into)
            if mode & 0o777:
                os.chmod(target, mode & 0o777)


def pack(folder: str, dist: str, name: str = NAME) -> str:
    os.makedirs(dist, exist_ok=True)
    path = os.path.join(dist, f"{name}-{tag()}.zip")
    base = os.path.dirname(folder)
    # Links stay links: a macOS .app's frameworks (Versions/Current) would lose
    # their layout and signature as copies, and Linux's links to Qt's libraries
    # would become second copies - the zip 48% bigger, and a library replaced
    # in one place still loaded from the other. Windows builds hold none.
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for here, dirs, files in os.walk(folder):
            dirs.sort()
            for entry in [d for d in dirs if os.path.islink(os.path.join(here, d))]:
                link(zf, os.path.join(here, entry), base)
            for entry in sorted(files):
                full = os.path.join(here, entry)
                if os.path.islink(full):
                    link(zf, full, base)
                    continue
                info = zipfile.ZipInfo.from_file(full, os.path.relpath(full, base))
                info.date_time = FIXED
                with open(full, "rb") as fh:
                    zf.writestr(info, fh.read(), zipfile.ZIP_DEFLATED)
    return path


def link(zf: zipfile.ZipFile, full: str, base: str) -> None:
    info = zipfile.ZipInfo(os.path.relpath(full, base).replace(os.sep, "/"), FIXED)
    info.create_system = 3                              # Unix, so the mode is read
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    zf.writestr(info, os.readlink(full))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dist", default=os.path.join(ROOT, "dist"))
    parser.add_argument("--mod-installer", metavar="DIR",
                        help="put the mod_installer packaging/mod_installer.py built in DIR "
                             "in the bundle")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="iemod-gui-") as work:
        folder = build(work)
        add_licences(folder)
        if args.mod_installer:
            add_mod_installer(folder, os.path.abspath(args.mod_installer))
        sign(folder)
        path = pack(folder, os.path.abspath(args.dist))
        unpacked = os.path.join(work, "unpacked")
        unpack(path, unpacked)
        check(os.path.join(unpacked, os.path.basename(folder)), work)
    sys.stdout.write(f"{path} ({os.path.getsize(path):,} bytes)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
