"""
Archive identification and extraction that refuses to write outside its root.

Threat model: a mod archive is untrusted input from a forum download or a
release asset nobody checksums. It may contain `../` members, absolute paths,
symlinks pointing at the game install, or be a decompression bomb.
"""
import enum
import os
import posixpath
import shutil
import subprocess
import tarfile
import zipfile
from dataclasses import dataclass
from typing import List, Optional

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
            # `filter="data"` (3.12+, backported to 3.9.17+/3.10.12+/3.11.4+)
            # is the stdlib's own hardened extraction. Where it exists it is
            # strictly better than anything written here; where it does not, the
            # fallback extracts one member at a time and re-checks the resolved
            # destination, rather than trusting a bare extractall.
            if hasattr(tarfile, "data_filter"):
                tf.extractall(dest, filter="data")
            else:                                    # pragma: no cover - old runtimes
                for member in members:
                    tf.extract(member, dest)
                    _assert_within(dest, os.path.join(dest, member.name))
    except tarfile.TarError as exc:
        raise ExtractionError(f"cannot read tar archive {path}: {exc}") from exc


# Windows installers do not put these on PATH.
_WINDOWS_TOOL_PATHS = {
    "7z": (r"C:\Program Files\7-Zip\7z.exe",
           r"C:\Program Files (x86)\7-Zip\7z.exe"),
    "unrar": (r"C:\Program Files\WinRAR\UnRAR.exe",
              r"C:\Program Files (x86)\WinRAR\UnRAR.exe"),
}


def find_tool(name: str):
    """Locate an unpacker on PATH, or in its usual Windows install directory."""
    found = shutil.which(name)
    if found:
        return found
    for candidate in _WINDOWS_TOOL_PATHS.get(name, ()):
        expanded = os.path.expandvars(candidate)
        if os.path.isfile(expanded):
            return expanded
    return None


def _external_tools(kind: Kind, path: str, dest: str):
    if kind is Kind.RAR:
        table = [("7z", ["7z", "x", "-y", "-bd", f"-o{dest}", "--", path]),
                 ("7za", ["7za", "x", "-y", "-bd", f"-o{dest}", "--", path]),
                 ("unar", ["unar", "-q", "-o", dest, path]),
                 ("unrar", ["unrar", "x", "-y", "-idq", path, dest + os.sep])]
    else:
        table = [("7z", ["7z", "x", "-y", "-bd", f"-o{dest}", "--", path]),
                 ("7za", ["7za", "x", "-y", "-bd", f"-o{dest}", "--", path]),
                 ("unar", ["unar", "-q", "-o", dest, path])]
    resolved = []
    for tool, cmd in table:
        binary = find_tool(tool)
        if binary:
            resolved.append((tool, [binary] + cmd[1:]))
    return resolved


def _extract_external(path: str, dest: str, kind: Kind) -> None:
    """
    Hand the container to an unpacker. A .exe is never executed - it is only
    read as a data file by 7z/unar, which understand SFX headers.
    """
    candidates = _external_tools(kind, path, dest)
    if not candidates:
        raise ExtractionError(
            f"{os.path.basename(path)} is a {kind.value} archive and no unpacker was "
            f"found. Install 7-Zip (Windows: winget install 7zip.7zip; Linux: "
            f"apt install p7zip-full), or unar/unrar. Standard Windows install "
            f"directories are searched, so PATH is not required.")
    failures = []
    for tool, cmd in candidates:
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  timeout=_TOOL_TIMEOUT, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            failures.append(f"{tool}: {exc}")
            continue
        if proc.returncode == 0:
            return
        failures.append(f"{tool}: exit {proc.returncode}: "
                        f"{proc.stdout.decode('utf-8', 'replace').strip()[:200]}")
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
        _extract_zip(path, dest)
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


def list_entries(path: str) -> Optional[List[ArchiveEntry]]:
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
    tool = next((find_tool(t) for t in ("7z", "7za") if find_tool(t)), None)
    if not tool:
        return None
    try:
        proc = subprocess.run([tool, "l", "-slt", "-ba", "--", path],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=_TOOL_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    names = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        if line.startswith("Path = "):          # -slt gives one key per line
            names.append(ArchiveEntry(line[7:].strip()))
    return names
