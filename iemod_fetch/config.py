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
import io
from dataclasses import dataclass, field
from typing import Any

from .atomic import write_text
from .errors import ConfigError

SECTION = "iemod-fetch"
FILENAME = "iemod-fetch.ini"

# Options that may be repeated on the command line; in the file, one per line or
# comma-separated.
LIST_KEYS = ("weidu_log", "catalogue", "only", "trusted_owner", "rules", "take_newer")
BOOL_KEYS = ("dry_run", "force", "refresh", "quiet", "allow_manual", "check_only",
             "accept_suggestions", "allow_http", "allow_exe", "accept_offsite",
             "include_optional",
             "no_discovery", "no_gh_cli", "no_git_credential",
             "all_manifest_entries", "resolve_conflicts", "emit_installer", "simulate",
             "no_update_data", "no_default_data", "fetch_metadata")
INT_KEYS = ("workers", "timeout", "retries", "discovery_attempts", "data_max_age")
SIZE_KEYS = ("max_bytes",)
STR_KEYS = ("manifest", "target", "aliases", "json_report", "emit_pinned_manifest",
            "mod_db", "suppress", "game_language", "language_preference", "bgee_dir", "bg2ee_dir",
            "token_file", "oauth_client_id", "trusted_owners", "owner_cache",
            "selection", "emit_selection", "list_mods", "describe_mods", "events", "data_dir", "eet_sequence", "releases", "decisions", "bio_code", "emit_bio_code", "pi_list",
            "sorting_order")

# Files the wizard writes beside the project's ini and names in it: read
# relative to the ini, wherever the command line is run from.
FILE_RELATIVE_KEYS = ("sorting_order",)

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


def _split_list(raw: str) -> list[str]:
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
    values: dict[str, Any] = field(default_factory=dict)
    path: str | None = None
    warnings: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.values)


def candidate_paths(explicit: str | None = None,
                    target: str | None = None) -> list[str]:
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


def load_config(explicit: str | None = None,
                target: str | None = None) -> FileConfig:
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
        with open(path, encoding="utf-8") as fh:
            parser.read_file(fh)
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    except configparser.Error as exc:
        raise ConfigError(f"{path} is not a valid INI file: {exc}") from exc

    if not parser.has_section(SECTION):
        return FileConfig(path=path, warnings=[
            f"{path}: no [{SECTION}] section; nothing was applied"])

    config = FileConfig(path=path)
    try:
        items = parser.items(SECTION)
    except configparser.Error as exc:     # a lone % is interpolation syntax
        raise ConfigError(f"{path}: {exc} (write a literal % as %%)") from exc
    for raw_key, raw_value in items:
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
                value = raw_value.strip()
                if key in FILE_RELATIVE_KEYS and value and not os.path.isabs(value):
                    value = os.path.join(os.path.dirname(os.path.abspath(path)), value)
                config.values[key] = value
        except ValueError as exc:
            raise ConfigError(f"{path}: option {raw_key!r} = {raw_value!r}: {exc}") from exc
    return config


def write_values(path: str, values: dict[str, Any],
                 extra: dict[str, dict[str, str]] | None = None) -> None:
    """
    Set `values` in the [iemod-fetch] section of `path`, keeping every other
    option and section; `extra` sets options of other sections (the GUI keeps
    its own there). A value of None removes the option. Written whole and
    swapped in, so a crash never leaves half a file. Comments are not kept:
    configparser does not read them back.
    """
    unknown = sorted(set(values) - KNOWN_KEYS)
    if unknown:
        raise ConfigError(f"{path}: unknown option(s) {', '.join(unknown)}")
    parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                parser.read_file(fh)
        except (OSError, configparser.Error) as exc:
            raise ConfigError(f"cannot update {path}: {exc}") from exc
    for section, options in [(SECTION, values)] + sorted((extra or {}).items()):
        if not parser.has_section(section):
            parser.add_section(section)
        for key, value in options.items():
            # The reader accepts `bgee-dir` for `bgee_dir`: replace either spelling.
            parser.remove_option(section, key.replace("_", "-"))
            if value is None:
                parser.remove_option(section, key)
                continue
            if isinstance(value, (list, tuple)):
                text = ", ".join(str(v) for v in value)
            elif isinstance(value, bool):
                text = "true" if value else "false"
            else:
                text = str(value)
            # Read back with interpolation: a literal % is written %% (C:/100%BG).
            parser.set(section, key, text.replace("%", "%%"))
    # An existing file keeps the permissions its owner gave it; a new one is
    # readable by its owner only (it may hold a token): write_text's rule.
    buf = io.StringIO()
    parser.write(buf)
    write_text(path, buf.getvalue())


def read_section(path: str, section: str) -> dict[str, str]:
    """The raw options of one section of `path` ({} when absent or unreadable)."""
    parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
    try:
        with open(path, encoding="utf-8") as fh:
            parser.read_file(fh)
        return dict(parser.items(section)) if parser.has_section(section) else {}
    except (OSError, configparser.Error):
        return {}
