"""
mod_downloads.json loader and validator.

The manifest produced by Infinity Mod Forge carries no integrity metadata, so
this loader accepts (and encourages) three optional fields the tool will honour
when present: `sha256`, `release_tag`, and `asset`. See ADR-0004.
"""
import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .errors import ManifestError
from .naming import is_safe_component

_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

KNOWN_FIELDS = {"name", "tp2", "url", "github", "sha256", "release_tag",
                "asset", "folder", "notes", "expect_tp2"}

# Top-level keys iemod-fetch itself emits when pinning; ignored on read.
KNOWN_TOP_LEVEL = {"generated", "description", "mods", "pinned_entries",
                   "unpinned_entries"}


@dataclass
class ModSource:
    """Where a mod can be obtained. Distinct from *where it installs to*."""
    key: str                              # manifest 'tp2' value, catalogue id
    name: str
    url: Optional[str] = None
    github: Optional[str] = None
    sha256: Optional[str] = None
    release_tag: Optional[str] = None     # pin a specific release
    asset: Optional[str] = None           # pin a specific asset filename/glob
    folder: Optional[str] = None          # explicit install folder override
    expect_tp2: Optional[str] = None      # tp2 the archive really ships, if it
                                          # differs from the WeiDU folder name
    notes: Optional[str] = None

    @property
    def lookup(self) -> str:
        return self.key.lower()


@dataclass
class Manifest:
    sources: Dict[str, ModSource] = field(default_factory=dict)
    order: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    generated: Optional[str] = None


def load_manifest(path, allow_http: bool = False) -> Manifest:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except OSError as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{path} is not valid JSON: {exc}") from exc
    return parse_manifest(raw, source=str(path), allow_http=allow_http)


def parse_manifest(raw, source="<manifest>", allow_http: bool = False) -> Manifest:
    if isinstance(raw, list):
        entries, generated = raw, None
    elif isinstance(raw, dict):
        if "mods" not in raw:
            raise ManifestError(f"{source}: top-level object has no 'mods' key "
                                f"(found: {sorted(raw)[:8]})")
        entries, generated = raw["mods"], raw.get("generated")
    else:
        raise ManifestError(f"{source}: expected object or array, got {type(raw).__name__}")

    if not isinstance(entries, list):
        raise ManifestError(f"{source}: 'mods' must be an array")
    if not entries:
        raise ManifestError(f"{source}: 'mods' is empty - refusing to run a no-op")

    out = Manifest(generated=generated)
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ManifestError(f"{source}[{i}]: entry must be an object")

        key = entry.get("tp2")
        name = entry.get("name") or key
        if not key or not isinstance(key, str):
            raise ManifestError(f"{source}[{i}]: missing required string field 'tp2'")
        if not is_safe_component(key):
            raise ManifestError(
                f"{source}[{i}]: 'tp2' value {key!r} is not a safe directory name")
        if key.lower() in out.sources:
            raise ManifestError(f"{source}[{i}]: duplicate tp2 key {key!r}")

        for unknown in sorted(set(entry) - KNOWN_FIELDS):
            out.warnings.append(f"{source}[{i}] ({key}): ignoring unknown field {unknown!r}")

        url = entry.get("url") or None
        if url is not None:
            if not isinstance(url, str):
                raise ManifestError(f"{source}[{i}] ({key}): 'url' must be a string")
            if url.startswith("http://"):
                if not allow_http:
                    out.warnings.append(
                        f"{key}: cleartext http:// URL will be REFUSED "
                        f"(pass --allow-http to permit): {url}")
                else:
                    out.warnings.append(f"{key}: downloading over cleartext http://: {url}")
            elif not url.startswith("https://"):
                raise ManifestError(
                    f"{source}[{i}] ({key}): unsupported URL scheme in {url!r}")

        github = entry.get("github") or None
        if github is not None and not _REPO_RE.match(str(github)):
            out.warnings.append(
                f"{key}: 'github' value {github!r} is not owner/repo - ignoring it")
            github = None

        sha = entry.get("sha256") or None
        if sha is not None and not _SHA256_RE.match(str(sha)):
            raise ManifestError(f"{source}[{i}] ({key}): 'sha256' is not a 64-hex digest")

        folder = entry.get("folder") or None
        if folder is not None and not is_safe_component(folder):
            raise ManifestError(f"{source}[{i}] ({key}): 'folder' {folder!r} is unsafe")

        expect_tp2 = entry.get("expect_tp2") or None
        if expect_tp2 is not None and not is_safe_component(str(expect_tp2)):
            raise ManifestError(
                f"{source}[{i}] ({key}): 'expect_tp2' {expect_tp2!r} is not a "
                f"usable tp2/folder name")

        if not url and not github:
            out.warnings.append(f"{key}: no 'url' and no 'github' - manual download only")

        out.sources[key.lower()] = ModSource(
            key=key, name=str(name or key), url=url, github=github,
            sha256=sha.lower() if sha else None,
            release_tag=entry.get("release_tag") or None,
            asset=entry.get("asset") or None,
            folder=folder, expect_tp2=expect_tp2,
            notes=entry.get("notes") or None,
        )
        out.order.append(key.lower())
    return out
