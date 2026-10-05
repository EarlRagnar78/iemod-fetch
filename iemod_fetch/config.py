"""
Optional INI configuration.

Real mods run to 1.5 GB and a 148-mod run has a dozen knobs worth setting once,
so the byte ceiling and friends belong in a file next to the game install rather
than in every command line.

Precedence is the usual one and is not negotiable: an explicit CLI flag beats the
file, the file beats the built-in default. That is implemented by feeding the
file's values to `parser.set_defaults()` and re-parsing, so there is exactly one
definition of each default and no per-flag plumbing to drift.
"""
import configparser
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .errors import ConfigError

SECTION = "iemod-fetch"
FILENAME = "iemod-fetch.ini"

# Options that may be repeated on the command line; in the file, one per line or
# comma-separated.
LIST_KEYS = ("weidu_log", "catalogue", "only", "trusted_owner", "rules")
BOOL_KEYS = ("dry_run", "force", "refresh", "quiet", "allow_manual", "check_only",
             "accept_suggestions", "allow_http", "allow_exe", "accept_offsite",
             "include_optional",
             "no_discovery", "no_gh_cli", "no_git_credential",
             "all_manifest_entries")
INT_KEYS = ("workers", "timeout", "retries", "discovery_attempts")
SIZE_KEYS = ("max_bytes",)
STR_KEYS = ("manifest", "target", "aliases", "json_report", "emit_pinned_manifest",
            "mod_db", "suppress",
            "token_file", "oauth_client_id", "trusted_owners", "owner_cache")

KNOWN_KEYS = frozenset(LIST_KEYS + BOOL_KEYS + INT_KEYS + SIZE_KEYS + STR_KEYS)

_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([KMGT]?)(I?)B?\s*$", re.IGNORECASE)
_UNIT_POWER = {"": 0, "K": 1, "M": 2, "G": 3, "T": 4}


def parse_size(value, key: str = "value") -> int:
    """
    Accept `536870912`, `512MiB`, `1.5 GB`, `2G`. Binary and decimal units are
    both honoured: `MiB` is 1024^2, `MB` is 1000^2.
    """
    if isinstance(value, int):
        if value <= 0:
            raise ConfigError(f"{key}: must be a positive number of bytes")
        return value
    match = _SIZE_RE.match(str(value))
    if not match:
        raise ConfigError(
            f"{key}: {value!r} is not a size. Use bytes (536870912) or a unit "
            f"(512MiB, 1.5GB, 2G).")
    number, unit, binary = match.group(1), match.group(2).upper(), match.group(3)
    base = 1024 if (binary or not unit) else 1000
    result = int(float(number) * (base ** _UNIT_POWER[unit]))
    if result <= 0:
        raise ConfigError(f"{key}: must be a positive number of bytes")
    return result


def _split_list(raw: str) -> List[str]:
    parts = []
    for line in raw.splitlines():
        for raw_item in line.split(","):
            item = raw_item.strip()
            if item:
                parts.append(item)
    return parts


@dataclass
class FileConfig:
    # str | int | bool | list[str], decided per key by LIST_KEYS / BOOL_KEYS /
    # INT_KEYS / SIZE_KEYS. Any, not object: `object` forces every reader to
    # cast, which is noise around a value that has already been coerced.
    values: Dict[str, Any] = field(default_factory=dict)
    path: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.values)


def candidate_paths(explicit: Optional[str] = None,
                    target: Optional[str] = None) -> List[str]:
    """Where a config file may live, most specific first."""
    if explicit:
        return [explicit]
    paths = [os.path.join(os.getcwd(), FILENAME)]
    if target:
        paths.append(os.path.join(target, FILENAME))
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(os.path.join(appdata, FILENAME))
    home = os.path.expanduser("~")
    paths.append(os.path.join(home, ".config", FILENAME))
    return paths


def load_config(explicit: Optional[str] = None,
                target: Optional[str] = None) -> FileConfig:
    """
    Read the first config file that exists. A missing file is not an error
    unless it was named explicitly with --config.
    """
    for path in candidate_paths(explicit, target):
        if os.path.isfile(path):
            return _read(path)
    if explicit:
        raise ConfigError(f"--config {explicit}: no such file")
    return FileConfig()


def _read(path: str) -> FileConfig:
    parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
    try:
        with open(path, "r", encoding="utf-8") as fh:
            parser.read_file(fh)
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    except configparser.Error as exc:
        raise ConfigError(f"{path} is not a valid INI file: {exc}") from exc

    if not parser.has_section(SECTION):
        return FileConfig(path=path, warnings=[
            f"{path}: no [{SECTION}] section; nothing was applied"])

    config = FileConfig(path=path)
    for raw_key, raw_value in parser.items(SECTION):
        key = raw_key.strip().replace("-", "_")
        if key not in KNOWN_KEYS:
            config.warnings.append(f"{path}: ignoring unknown option {raw_key!r}")
            continue
        try:
            if key in BOOL_KEYS:
                config.values[key] = parser.getboolean(SECTION, raw_key)
            elif key in INT_KEYS:
                config.values[key] = parser.getint(SECTION, raw_key)
            elif key in SIZE_KEYS:
                config.values[key] = parse_size(raw_value, key)
            elif key in LIST_KEYS:
                config.values[key] = _split_list(raw_value)
            else:
                config.values[key] = raw_value.strip()
        except ValueError as exc:
            raise ConfigError(f"{path}: option {raw_key!r} = {raw_value!r}: {exc}") from exc
    return config
