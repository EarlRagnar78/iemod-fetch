"""
Archive identification and extraction that refuses to write outside its root.

Threat model: a mod archive is untrusted input from a forum download or a
release asset nobody checksums. It may contain `../` members, absolute paths,
symlinks pointing at the game install, or be a decompression bomb.
"""
import contextlib
import enum
import gzip
import os
import posixpath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
import zlib
from dataclasses import dataclass

from . import atomic
from . import childenv
from .childenv import child_env
from .errors import ExtractionError, UnsafeArchive

MAX_TOTAL_BYTES = 2 * 1024 ** 3       # 2 GiB uncompressed ceiling
MAX_ENTRIES = 100_000
MAX_RATIO = 200                       # compression ratio bomb threshold
_RATIO_FLOOR = 8 * 1024 * 1024        # only apply the ratio guard above 8 MiB
_TOOL_TIMEOUT = 600


class Kind(enum.Enum):
    ZIP = "zip"          # also .iemod (Project Infinity) - a zip by another name
    TAR = "tar"
    GZIP = "gzip"
    BZIP2 = "bzip2"
    XZ = "xz"
    RAR = "rar"
    SEVENZIP = "7z"
    MSDOS = "msdos"      # .exe - possibly a self-extracting archive
    UNKNOWN = "unknown"


_MAGIC = (
    (b"PK\x03\x04", Kind.ZIP), (b"PK\x05\x06", Kind.ZIP), (b"PK\x07\x08", Kind.ZIP),
    (b"\x1f\x8b", Kind.GZIP),
    (b"BZh", Kind.BZIP2),
    (b"\xfd7zXZ\x00", Kind.XZ),
    (b"Rar!\x1a\x07", Kind.RAR),
    (b"7z\xbc\xaf\x27\x1c", Kind.SEVENZIP),
    (b"MZ", Kind.MSDOS),
)

# What the stdlib readers raise on a truncated or corrupted stream - a partial
# download, in practice. None of it is a ModFetchError, so each is translated
# at the boundary instead of escaping the runner as an "internal error".
try:
    import lzma
    _LZMA_ERRORS: tuple = (lzma.LZMAError,)
except ImportError:                                  # pragma: no cover - minimal builds
    _LZMA_ERRORS = ()
_DAMAGED = (zipfile.BadZipFile, tarfile.TarError, zlib.error, EOFError,
            gzip.BadGzipFile) + _LZMA_ERRORS

TAR_LIKE = (Kind.TAR, Kind.GZIP, Kind.BZIP2, Kind.XZ)
EXTERNAL_ONLY = (Kind.RAR, Kind.SEVENZIP, Kind.MSDOS)


def detect_kind(head: bytes) -> Kind:
    """Identify an archive from its leading bytes. Never trusts the extension."""
    if not head:
        return Kind.UNKNOWN
    for magic, kind in _MAGIC:
        if head.startswith(magic):
            return kind
    if len(head) >= 262 and head[257:262] == b"ustar":
        return Kind.TAR
    return Kind.UNKNOWN


def detect_file(path: str) -> Kind:
    with open(path, "rb") as fh:
        head = fh.read(512)
    kind = detect_kind(head)
    # A .gz/.bz2/.xz may wrap a tar or a single file; only tarfile can tell.
    if kind in (Kind.GZIP, Kind.BZIP2, Kind.XZ):
        try:
            with tarfile.open(path, "r:*"):
                return Kind.TAR
        except (tarfile.TarError, OSError, EOFError):
            return kind
    return kind


# --------------------------------------------------------------- validation
def _reject_member(name: str, what: str = "member") -> str:
    """Raise unless `name` is a relative path that stays inside the root."""
    if not name or name in (".", ".."):
        raise UnsafeArchive(f"archive {what} has an empty or traversal name: {name!r}")
    if "\x00" in name:
        raise UnsafeArchive(f"archive {what} name contains NUL: {name!r}")
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        raise UnsafeArchive(f"archive {what} has an absolute path: {name!r}")
    parts = [p for p in normalized.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise UnsafeArchive(f"archive {what} escapes the extraction root: {name!r}")
    return posixpath.join(*parts) if parts else ""


def _zip_is_link(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def _assert_within(root: str, path: str) -> None:
    root_real = os.path.realpath(root)
    target = os.path.realpath(path)
    if target != root_real and not target.startswith(root_real + os.sep):
        raise UnsafeArchive(f"path escapes extraction root: {path}")


def _audit_extracted_tree(root: str) -> None:
    """Post-extraction sweep: no symlink may point outside the root."""
    for dirpath, dirnames, filenames in os.walk(root):
        for entry in list(dirnames) + list(filenames):
            full = os.path.join(dirpath, entry)
            if os.path.islink(full):
                target = os.path.realpath(full)
                root_real = os.path.realpath(root)
                if target != root_real and not target.startswith(root_real + os.sep):
                    raise UnsafeArchive(
                        f"archive contains a symlink escaping the root: {full} -> {target}")


# --------------------------------------------------------------- extraction
def _extract_zip(path: str, dest: str) -> None:
    with zipfile.ZipFile(path, "r") as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise UnsafeArchive(f"archive has {len(infos)} entries (limit {MAX_ENTRIES})")
        total = 0
        for info in infos:
            _reject_member(info.filename)
            if _zip_is_link(info):
                raise UnsafeArchive(f"archive contains a symlink member: {info.filename}")
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                raise UnsafeArchive(
                    f"uncompressed size exceeds {MAX_TOTAL_BYTES} bytes (zip bomb?)")
            if (info.file_size > _RATIO_FLOOR and info.compress_size
                    and info.file_size / info.compress_size > MAX_RATIO):
                raise UnsafeArchive(
                    f"member {info.filename} has a {info.file_size // info.compress_size}:1 "
                    f"compression ratio (zip bomb?)")
        # Member by member, re-checking the resolved destination immediately
        # before each write. `extractall` would hand the whole name list back to
        # the stdlib after our validation, so a name we approved and a path the
        # library ultimately resolves are two different facts. Extracting one
        # entry at a time keeps them the same fact, and costs nothing.
        for info in infos:
            written = zf.extract(info, dest)
            _assert_within(dest, written)


def _extract_tar(path: str, dest: str) -> None:
    try:
        with tarfile.open(path, "r:*") as tf:
            members = tf.getmembers()
            if len(members) > MAX_ENTRIES:
                raise UnsafeArchive(f"archive has {len(members)} entries")
            total = 0
            for member in members:
                _reject_member(member.name)
                if member.islnk() or member.issym():
                    _reject_member(member.linkname, what="link target")
                elif not (member.isfile() or member.isdir()):
                    raise UnsafeArchive(
                        f"archive contains a special file ({member.name}); refusing")
                total += max(member.size, 0)
                if total > MAX_TOTAL_BYTES:
                    raise UnsafeArchive("uncompressed size exceeds ceiling (tar bomb?)")
            # `filter="data"` is the stdlib's own hardened extraction, on top of
            # the checks above; every supported Python has it (ADR-0043).
            tf.extractall(dest, filter="data")
    except _DAMAGED as exc:
        raise _damaged(path, exc) from exc


def _damaged(path: str, exc: BaseException) -> ExtractionError:
    return ExtractionError(
        f"{os.path.basename(path)} is damaged or incomplete "
        f"({type(exc).__name__}: {exc}) - usually a partial download; "
        f"delete it and fetch again")


# Windows installers do not put these on PATH.
_WINDOWS_TOOL_PATHS = {
    "7z": (r"C:\Program Files\7-Zip\7z.exe",
           r"C:\Program Files (x86)\7-Zip\7z.exe"),
    "unrar": (r"C:\Program Files\WinRAR\UnRAR.exe",
              r"C:\Program Files (x86)\WinRAR\UnRAR.exe"),
}


def _windows_tar() -> str | None:
    """Windows 10 and 11 ship libarchive's bsdtar as System32\\tar.exe. Not
    `tar` from PATH: that may be Git's GNU tar, which reads no RAR."""
    path = os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32", "tar.exe")
    return path if os.path.isfile(path) else None


def find_tool(name: str):
    """Locate an unpacker on PATH, or in its usual Windows install directory."""
    if name == "bsdtar" and sys.platform == "win32":
        return _windows_tar()
    found = shutil.which(name)
    if found:
        return found
    for candidate in _WINDOWS_TOOL_PATHS.get(name, ()):
        expanded = os.path.expandvars(candidate)
        if os.path.isfile(expanded):
            return expanded
    return None


# Each unpacker's command, extracting `path` into the folder `out`.
_COMMANDS = {
    "bsdtar": lambda path, out: ["-x", "-f", path, "-C", out],
    "unar": lambda path, out: ["-q", "-f", "-D", "-o", out, path],
    "7z": lambda path, out: ["x", "-y", "-bd", f"-o{out}", "--", path],
    "7za": lambda path, out: ["x", "-y", "-bd", f"-o{out}", "--", path],
    "unrar": lambda path, out: ["x", "-y", "-idq", path, out + os.sep],
}

# The order each kind is tried in (ADR-0047, measured on lcc-docs' 105 RAR
# archives, docs/TESTING.md): libarchive opened 95 on Debian trixie, Windows
# and macOS alike, unar most of the rest, and the player's own 7-Zip or
# WinRAR - never shipped, used when installed - is the last resort. Debian's
# 7zip is the dfsg build without the RAR code: it fails, after writing.
_ORDER = {
    Kind.RAR: ("bsdtar", "unar", "7z", "7za", "unrar"),
    Kind.SEVENZIP: ("7z", "7za", "bsdtar", "unar"),
    Kind.MSDOS: ("7z", "7za", "unar"),
}


def _external_tools(kind: Kind):
    """(tool, its program) for each unpacker of `kind` installed, in order."""
    found = ((tool, find_tool(tool)) for tool in _ORDER[kind])
    return [(tool, binary) for tool, binary in found if binary]


def _seven_zip_listing(path: str) -> list[tuple] | None:
    """
    (name, size) for every member, from `7z l -slt`. None when 7-Zip is not
    installed or cannot read the file - the caller decides what that means.
    """
    tool = next((find_tool(t) for t in ("7z", "7za") if find_tool(t)), None)
    if not tool:
        return None
    try:
        proc = childenv.run([tool, "l", "-slt", "-ba", "--", path],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=_TOOL_TIMEOUT, check=False, env=child_env())
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    members: list[tuple] = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        if line.startswith("Path = "):          # -slt gives one key per line
            members.append((line[7:].strip(), 0))
        elif line.startswith("Size = ") and members:
            size = line[7:].strip()
            members[-1] = (members[-1][0], int(size) if size.isdigit() else 0)
    return members


def _preflight_external(path: str) -> None:
    """
    Hold an archive bound for an external unpacker to the zip/tar rules -
    names, entry count, total size - before anything is written. Without
    7-Zip there is no listing, and the post-extraction audit is what remains.
    """
    members = _seven_zip_listing(path)
    if members is None:
        return
    if len(members) > MAX_ENTRIES:
        raise UnsafeArchive(f"archive has {len(members)} entries (limit {MAX_ENTRIES})")
    total = 0
    for name, size in members:
        _reject_member(name)
        total += size
        if total > MAX_TOTAL_BYTES:
            raise UnsafeArchive(
                f"uncompressed size exceeds {MAX_TOTAL_BYTES} bytes (archive bomb?)")


def _writable_again(function, path, _exc) -> None:
    """rmtree's onexc: a read-only folder an archive restored is made
    writable and the removal tried again (review of #93)."""
    os.chmod(os.path.dirname(path) or path, 0o700)
    if os.path.isdir(path):
        os.chmod(path, 0o700)
    function(path)


def _remove(path: str) -> None:
    """A file or folder an unpacker wrote, gone - read-only parts included."""
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, onexc=_writable_again)
    elif os.path.lexists(path):
        os.remove(path)


def _extract_external(path: str, dest: str, kind: Kind) -> None:
    """
    Hand the container to an unpacker. A .exe is never executed - it is only
    read as a data file by 7z/unar, which understand SFX headers.
    """
    _preflight_external(path)
    candidates = _external_tools(kind)
    if not candidates:
        raise ExtractionError(
            f"{os.path.basename(path)} is a {kind.value} archive and no unpacker was "
            f"found. Debian/Ubuntu: apt install libarchive-tools unar; macOS: brew "
            f"install unar (bsdtar is built in); Windows 10 and 11 have tar.exe built "
            f"in. An installed 7-Zip (winget install 7zip.7zip) or WinRAR is used too "
            f"(standard install folders are searched) - Debian's own 7zip package cannot read RAR.")
    failures = []
    for tool, binary in candidates:
        # each attempt in a folder of its own: a tool that fails may have
        # written already (Debian's dfsg 7z writes every file wrong, then
        # exits 2), and the next one must not extract over its leftovers
        work = tempfile.mkdtemp(prefix=".unpack-", dir=os.path.dirname(os.path.abspath(dest)))
        try:
            try:
                proc = childenv.run([binary, *_COMMANDS[tool](path, work)],
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      timeout=_TOOL_TIMEOUT, check=False, env=child_env())
            except (OSError, subprocess.TimeoutExpired) as exc:
                failures.append(f"{tool}: {exc}")
                continue
            if proc.returncode == 0:
                moved: list[str] = []
                try:
                    for entry in os.listdir(work):
                        atomic.replace(os.path.join(work, entry), os.path.join(dest, entry))
                        moved.append(entry)
                    return
                except OSError as exc:          # e.g. an antivirus holding a file
                    for entry in moved:         # take back what went in
                        _remove(os.path.join(dest, entry))
                    failures.append(f"{tool}: extracted, but could not be moved into "
                                    f"place: {exc}")
                    continue
            failures.append(f"{tool}: exit {proc.returncode}: "
                            f"{proc.stdout.decode('utf-8', 'replace').strip()[:200]}")
        finally:
            with contextlib.suppress(OSError):     # a leftover, not a failure
                _remove(work)
    raise ExtractionError(f"all unpackers failed for {os.path.basename(path)}: "
                          + "; ".join(failures))


def safe_extract(path: str, dest: str, allow_exe: bool = False) -> Kind:
    """
    Extract `path` into `dest`, which must already exist and be empty-ish.

    Returns the detected Kind. Raises UnsafeArchive on any member that would
    escape `dest`, and ExtractionError if the format cannot be handled here.
    """
    kind = detect_file(path)
    os.makedirs(dest, exist_ok=True)

    if kind is Kind.ZIP:
        try:
            _extract_zip(path, dest)
        except _DAMAGED as exc:
            raise _damaged(path, exc) from exc
    elif kind is Kind.TAR:
        _extract_tar(path, dest)
    elif kind is Kind.MSDOS:
        if not allow_exe:
            raise ExtractionError(
                f"{os.path.basename(path)} is a Windows executable. Self-extracting "
                f"installers are not unpacked unless --allow-exe is given, and are "
                f"never run.")
        _extract_external(path, dest, kind)
    elif kind in EXTERNAL_ONLY:
        _extract_external(path, dest, kind)
    elif kind in (Kind.GZIP, Kind.BZIP2, Kind.XZ):
        raise ExtractionError(
            f"{os.path.basename(path)} is a compressed single file, not a mod archive")
    else:
        raise ExtractionError(
            f"{os.path.basename(path)} is not a recognised archive (magic bytes did "
            f"not match zip/tar/rar/7z)")

    _assert_within(dest, dest)
    _audit_extracted_tree(dest)
    return kind


# ------------------------------------------------------------------ listing
@dataclass
class ArchiveEntry:
    name: str

    @property
    def basename(self) -> str:
        return posixpath.basename(self.name.replace("\\", "/"))


def list_entries(path: str) -> list[ArchiveEntry] | None:
    """
    List archive member names without extracting. Returns None when the format
    needs an external tool that is not installed (caller must not treat that as
    'archive does not contain the mod').
    """
    kind = detect_file(path)
    if kind is Kind.ZIP:
        try:
            with zipfile.ZipFile(path, "r") as zf:
                return [ArchiveEntry(n) for n in zf.namelist()]
        except (zipfile.BadZipFile, OSError) as exc:
            raise ExtractionError(f"cannot list {path}: {exc}") from exc
    if kind is Kind.TAR:
        try:
            with tarfile.open(path, "r:*") as tf:
                return [ArchiveEntry(n) for n in tf.getnames()]
        except (tarfile.TarError, OSError) as exc:
            raise ExtractionError(f"cannot list {path}: {exc}") from exc
    members = _seven_zip_listing(path)
    return None if members is None else [ArchiveEntry(name) for name, _ in members]
