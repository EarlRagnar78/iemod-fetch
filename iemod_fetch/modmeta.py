"""
Project Infinity mod metadata (`[Metadata]` ini).

A PI-aware mod ships a `<modname>.ini` beside its .tp2 — inside an .iemod
archive, or in the installed mod folder. It carries the mod's identity and,
importantly, its own ordering constraints:

    [Metadata]
    Name     = Sword Coast Stratagems
    Author   = DavidW
    Download = https://github.com/.../releases/latest
    Before   = eet_end, cdtweaks
    After    = spell_rev, item_rev

`Before`/`After` are lists of tp2 names. They are the primary source the
community rule sets were harvested from, so reading them means a mod that ships
its own ini needs no external rule file at all.

Key names follow the reference parser in lcc-docs (scripts/manager/ini.py, MIT).
The format is INI-shaped but not INI-strict — values contain unescaped `%`, `:`
and stray brackets — so it is parsed with a tolerant line scanner rather than
configparser.
"""
import os
import re
import zipfile
from dataclasses import dataclass, field
from typing import List, Optional

_SECTION = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")
_ENTRY = re.compile(r"^\s*(?P<key>\w+)\s*=\s*(?P<value>.*?)\s*$")
_COMMENT = re.compile(r"(?:^|\s)[#;].*$")
_MAX_INI_BYTES = 1024 * 1024


@dataclass
class ModMetadata:
    source: str = "<ini>"
    name: Optional[str] = None
    author: Optional[str] = None
    version: Optional[str] = None
    type: Optional[str] = None
    homepage: Optional[str] = None
    forum: Optional[str] = None
    download: Optional[str] = None
    readme: Optional[str] = None
    label_type: Optional[str] = None
    before: List[str] = field(default_factory=list)
    after: List[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def urls(self) -> List[str]:
        return [u for u in (self.download, self.homepage, self.forum) if u]

    @property
    def has_order_hints(self) -> bool:
        return bool(self.before or self.after)


def _split_tp2_list(value: str) -> List[str]:
    """`Before = eet_end, cdtweaks` -> ['eet_end', 'cdtweaks'] (lower-cased)."""
    return [part.replace(" ", "").replace("\r", "").lower()
            for part in (value or "").split(",")
            if part.replace(" ", "").replace("\r", "")]


def parse_metadata_ini(content: str, source: str = "<ini>") -> ModMetadata:
    meta = ModMetadata(source=source)
    in_metadata = False
    seen_section = False

    for line in content.splitlines():
        section = _SECTION.match(line)
        if section:
            seen_section = True
            in_metadata = section.group("name").strip().lower() == "metadata"
            continue
        # A file with no [Metadata] header at all is still read, as the
        # reference parser does; once a section appears, only that one counts.
        if seen_section and not in_metadata:
            continue
        entry = _ENTRY.match(_COMMENT.sub("", line))
        if not entry:
            continue
        key, value = entry.group("key").strip(), entry.group("value").strip()
        if key and key.lower() not in meta.raw:
            meta.raw[key.lower()] = value

    get = meta.raw.get
    meta.name = get("name") or None
    meta.author = get("author") or None
    meta.version = get("version") or None
    meta.type = get("type") or None
    meta.homepage = get("homepage") or None
    meta.forum = get("forum") or None
    meta.download = get("download") or None
    meta.readme = get("readme") or None
    meta.label_type = get("labeltype") or None
    meta.before = _split_tp2_list(get("before", ""))
    meta.after = _split_tp2_list(get("after", ""))
    return meta


def read_metadata_file(path: str) -> Optional[ModMetadata]:
    try:
        if os.path.getsize(path) > _MAX_INI_BYTES:
            return None
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return parse_metadata_ini(fh.read(), source=path)
    except OSError:
        return None


def find_metadata(mod_dir: str, folder: Optional[str] = None) -> Optional[ModMetadata]:
    """
    Find a mod's metadata ini in an installed mod directory.

    Prefers `<folder>.ini`, then any .ini carrying a [Metadata] section.
    """
    if not os.path.isdir(mod_dir):
        return None
    preferred = os.path.join(mod_dir, f"{folder or os.path.basename(mod_dir)}.ini")
    if os.path.isfile(preferred):
        meta = read_metadata_file(preferred)
        if meta:
            return meta
    for entry in sorted(os.listdir(mod_dir)):
        if entry.lower().endswith(".ini"):
            meta = read_metadata_file(os.path.join(mod_dir, entry))
            if meta and (meta.name or meta.has_order_hints):
                return meta
    return None


def read_iemod_metadata(archive_path: str) -> Optional[ModMetadata]:
    """
    Read the metadata ini out of an .iemod without extracting it.

    An .iemod is a zip (Project Infinity's distribution format), so the ini can
    be read before deciding what to do with the archive.
    """
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".ini")]
            names.sort(key=lambda n: (n.count("/"), len(n)))
            for name in names:
                info = zf.getinfo(name)
                if info.file_size > _MAX_INI_BYTES:
                    continue
                with zf.open(name) as fh:
                    text = fh.read().decode("utf-8", errors="replace")
                meta = parse_metadata_ini(text, source=f"{archive_path}!{name}")
                if meta.name or meta.has_order_hints:
                    return meta
    except (zipfile.BadZipFile, OSError, KeyError):
        return None
    return None
