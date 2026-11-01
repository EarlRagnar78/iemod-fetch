#!/usr/bin/env python3
"""
Build a single-file executable `iemod-fetch.pyz`.

Restores the original script's best property - copy one file next to the game
install and run it - without giving up a testable package layout (ADR-0001).
The archive is pure Python; it carries the runtime's libraries
(requirements/runtime.txt, ADR-0043) - copied from the installed, hash-checked
distributions, so the build itself needs no network - and runs on the CPython
of .python-version (3.14), telling an older one so.

    python3 build.py                    # -> ./iemod-fetch.pyz
    python3 build.py -o /tmp/foo.pyz    # elsewhere
    ./iemod-fetch.pyz --help            # on POSIX; `py iemod-fetch.pyz` on Windows
"""
import argparse
import base64
import compileall
import hashlib
import importlib.metadata
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipapp

ROOT = os.path.dirname(os.path.abspath(__file__))
ENTRYPOINT = "import sys\nfrom iemod_fetch.cli import main\n\nsys.exit(main())\n"

# Reproducibility. `zipapp` writes each member's mtime into the archive, so two
# builds of one commit differ in bytes that have nothing to do with the code —
# and an artifact that cannot be rebuilt bit-for-bit cannot be checked against
# its source, which makes every signature and attestation downstream weaker.
# Normalising the timestamps costs one os.utime per file.
#
# SOURCE_DATE_EPOCH is the cross-ecosystem convention; the fallback is the
# zip format's own epoch, 1980-01-01, because zip cannot store anything earlier.
DEFAULT_SOURCE_DATE_EPOCH = 315532800          # 1980-01-01T00:00:00Z


def _source_date_epoch() -> int:
    raw = os.environ.get("SOURCE_DATE_EPOCH")
    if not raw:
        return DEFAULT_SOURCE_DATE_EPOCH
    try:
        return max(int(raw), DEFAULT_SOURCE_DATE_EPOCH)
    except ValueError:
        raise SystemExit(f"SOURCE_DATE_EPOCH is not an integer: {raw!r}") from None


def _normalise_times(root: str, when: int) -> None:
    """Give every staged file and directory the same timestamp."""
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        for name in filenames + dirnames:
            os.utime(os.path.join(dirpath, name), (when, when))
    os.utime(root, (when, when))


def _pins() -> dict[str, str]:
    """name -> version, from requirements/runtime.txt."""
    with open(os.path.join(ROOT, "requirements", "runtime.txt"), encoding="utf-8") as fh:
        return dict(re.findall(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", fh.read(), re.MULTILINE))


def _vendor(staging: str) -> None:
    """Copy each runtime library from its installed distribution into the
    archive: its package files, each checked against the distribution's
    RECORD, and its METADATA and licence files - not the installer's own
    records, which differ between pip and uv and would make two builds of
    one commit differ. The installed version must be the pinned one."""
    for name, version in sorted(_pins().items()):
        try:
            dist = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            raise SystemExit(f"build aborted: {name} is not installed; run "
                             f"pip install --require-hashes -r requirements/runtime.txt") from None
        if dist.version != version:
            raise SystemExit(f"build aborted: {name} {dist.version} is installed, "
                             f"requirements/runtime.txt pins {version}")
        for entry in dist.files or ():
            rel = str(entry).replace("\\", "/")
            parts = rel.split("/")
            if ".." in parts or rel.startswith("/") or os.path.isabs(rel) or ":" in parts[0]:
                continue                       # outside the package: a script, never copied
            if "__pycache__" in parts or rel.endswith(".pyc"):
                continue
            meta = parts[0].endswith(".dist-info")
            if meta and not (parts[-1] == "METADATA" or "licenses" in parts
                             or parts[-1].startswith(("LICENSE", "COPYING", "NOTICE"))):
                continue
            source = str(entry.locate())
            with open(source, "rb") as fh:
                data = fh.read()
            if entry.hash is None:
                if not meta:                   # a package file must be accounted for
                    raise SystemExit(f"build aborted: {rel} has no hash in its RECORD")
            else:
                digest = base64.urlsafe_b64encode(
                    hashlib.new(entry.hash.mode, data).digest()).rstrip(b"=").decode()
                if digest != entry.hash.value:
                    raise SystemExit(f"build aborted: {rel} differs from its RECORD")
            target = os.path.join(staging, *parts)
            if not os.path.realpath(target).startswith(os.path.realpath(staging) + os.sep):
                raise SystemExit(f"build aborted: {rel} would land outside the archive")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(data)


def build(target: str, interpreter: str = "/usr/bin/env python3",
          compressed: bool = True) -> str:
    package = os.path.join(ROOT, "iemod_fetch")
    if not os.path.isdir(package):
        raise SystemExit(f"cannot find {package}")

    with tempfile.TemporaryDirectory() as staging:
        shutil.copytree(package, os.path.join(staging, "iemod_fetch"),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        with open(os.path.join(staging, "__main__.py"), "w", encoding="utf-8") as fh:
            fh.write(ENTRYPOINT)
        _vendor(staging)

        # Fail the build rather than shipping a syntax error.
        if not compileall.compile_dir(staging, quiet=2, force=True):
            raise SystemExit("build aborted: package does not compile")
        for dirpath, dirnames, _ in os.walk(staging):
            for name in list(dirnames):
                if name == "__pycache__":
                    shutil.rmtree(os.path.join(dirpath, name))
                    dirnames.remove(name)

        # Deterministic order as well as deterministic times: os.walk order is
        # filesystem order, and zipapp preserves whatever it is handed.
        _normalise_times(staging, _source_date_epoch())
        zipapp.create_archive(staging, target=target, interpreter=interpreter,
                              compressed=compressed)
    os.chmod(target, 0o755)
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-o", "--output", default=os.path.join(ROOT, "iemod-fetch.pyz"))
    parser.add_argument("--interpreter", default="/usr/bin/env python3",
                        help="shebang for the archive (default: %(default)s)")
    parser.add_argument("--no-compress", action="store_true")
    parser.add_argument("--no-verify", action="store_true",
                        help="skip running the built archive")
    args = parser.parse_args(argv)

    target = build(args.output, args.interpreter, not args.no_compress)
    size = os.path.getsize(target)

    if not args.no_verify:
        proc = subprocess.run([sys.executable, target, "--version"],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=60, check=False)
        output = proc.stdout.decode("utf-8", "replace").strip()
        if proc.returncode != 0:
            raise SystemExit(f"built archive failed to run: {output}")
        print(f"verified: {output}")

    print(f"built {target} ({size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
