"""
The public API: what the command line does, as functions (ADR-0029, ADR-0030).

The command line and the GUI are two clients of this module. Neither holds
logic of its own: `cli.py` turns flags into `Settings` and prints; a GUI builds
`Settings` from its screens and reads the `Outcome`. Everything a front end may
rely on is in `__all__`; anything starting with an underscore may change.

    from iemod_fetch import api
    mods = api.list_mods("mod_downloads.json", catalogues=["lcc/db/mods.json"])
    outcome = api.run(api.Settings(selection="selection.json", target="Mods"),
                      on_event=print, cancel=threading.Event())
    outcome.exit_code, outcome.report, outcome.order_plan, outcome.conflict_report

`run` writes nothing to the terminal unless given a `stream`; its progress
reaches `on_event` (the events of schemas/events-v1.schema.json), and setting
`cancel` stops it at the next chunk. Errors are raised as `ModFetchError`
subclasses, each with a stable `code` (errors.py).
"""
import contextlib
import json
import os
import re
import stat
import struct
import sys
import tempfile
from dataclasses import dataclass, field, fields, replace
from typing import Any
from collections.abc import Callable, Mapping, Sequence

from .atomic import write_text
from .auth import resolve_credential
from . import backup
from .available import AvailableMod, available_mods, mark_fetched, mods_document
from .catalogues import CatalogueSet
# around a program the wizard itself starts (a browser): ADR-0058
from .childenv import spawning as starting_program  # noqa: F401
from . import datasync
from .conflicts import ConflictReport, build_conflict_report, render_conflict_report
from .constraints import ModConstraints, load_constraints, tp2_rules
from .errors import ConfigError
from .freshness import parse_release_cache
from . import gamedir
from . import mi_parser
from .gamedir import verify_eet
from .install import State, find_tp2_files
from .installer import build_installer
from . import config as _config
from .languages import LANGUAGES, apply_language_preference, parse_preferences
from .manifest import Manifest, load_manifest
from .kinds import KindHint
from .moddb import ModDatabase
from .modmeta import find_metadata
from .naming import normalize_key
from .net import DEFAULT_MAX_BYTES, HttpClient, https_context
from .ordering import (EET_LOG, PRE_EET_LOG, OrderIndex, broken_after_move, broken_pairs,
                       bws_sequence, plan_order, render_plan_summary, reverse, tp2_key)
from .ordering import order_fixes as _order_fixes
from .orgindex import OwnerIndex, load_trusted_owners
from .pinning import build_pinned_manifest, write_pinned_manifest
from .plan import build_plan, load_aliases
from .report import RunReport, render_summary
from . import (bio, choices, install_run, launch, limits, pi, premeta, prompts, readiness,
               readln, sortorder, toolchain)
from .decisions import Decisions, IgnoredOrder, decisions_to_json, parse_decisions
from .resolution import (ResolutionResult, apply_decisions, before_eet_core, keep_both_rules,
                         resolve_conflicts, resolve_refusals)
from .rules import DEPENDS, ORDER, Context, Install, RuleSet, check_all, load_suppressions
from .runner import Options, Runner
from .selection import Install as SelectionInstall
from .selection import one_line_label, tp2_problem
from .selection import (Choice, Selection, parse_selection,
                        selection_from_logs, selection_to_json)
from .simulate import simulate_install, steps_of
from .tp2 import read_mod_tp2
from .weidu_lex import legacy_charset
from .etagcache import ETagCache
from .urls import repo_from_url
from . import tra
from .contract import SCHEMA_VERSION, stable_id
from .weidu import ParsedLog, parse_weidu_files, parse_weidu_log, split_log_spec
from . import __version__

__all__ = ["Settings", "Outcome", "run", "list_mods", "load_selection", "prepare_https",
           "install_questions",
           "backup_game", "verify_backup", "plan_restore", "restore_backup", "list_backups",
           "backups_dir",
           "selection_of_logs", "update_data", "data_status", "describe_mods",
           "load_bio_code", "bio_code_of", "check_game_folders", "languages",
           "load_project", "save_project", "PROJECT_FILE", "mod_choices",
           "save_selection", "SELECTION_FILE", "selection_conflicts",
           "load_decisions", "save_decisions", "DECISIONS_FILE",
           "ignore_order", "unignore_order", "selection_digest", "start_install", "install_progress", "install_known_issues",
           "default_tools_dir", "find_tools", "tool_download", "download_tool",
           "selection_plan", "write_install_plan", "load_install_answers", "save_install_answers",
           "write_install_answers", "answer_key", "writable_answer", "INSTALL_ANSWERS_FILE", "install_games", "INSTALL_PLAN_DIR",
           "save_install_order", "reset_install_order",
           "order_breaks", "order_breaks_after_move", "order_followers", "order_fixes",
           "preview_install_order",
           "INSTALL_ORDER_FILE", "project_settings", "download_selection",
           "import_selection", "export_selection"]


# The command line's -m default. Unlike a manifest named on purpose, it may be
# absent: then, as for the wizard, the community catalogue is the source.
DEFAULT_MANIFEST = "mod_downloads.json"


@dataclass
class Settings:
    """
    Everything a run can be told. One field per command-line option, with the
    same name and default (`iemod-fetch --help` describes each), so a GUI and
    the command line mean the same thing by the same word.
    """
    # inputs
    manifest: str | None = DEFAULT_MANIFEST       # None: the catalogue only
    weidu_log: list[str] = field(default_factory=list)     # "PATH" or "PATH:GAME"
    selection: str | None = None
    bio_code: str | None = None         # a file holding a BIO-MODLIST-V1 code
    pi_list: str | None = None          # "PATH:GAME": a Project Infinity list
    aliases: str | None = None
    catalogue: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    mod_db: str | None = None
    order_catalogue: str | None = None
    eet_sequence: str | None = None     # BWS-NG games/eet.json
    releases: str | None = None         # krion64 data/version_cache.json
    suppress: str | None = None
    sorting_order: str | None = None    # a Project Infinity Sorting Order file
    fetch_metadata: bool = False           # fetch planned mods' own metadata inis
    all_manifest_entries: bool = False
    only: list[str] = field(default_factory=list)
    take_newer: list[str] = field(default_factory=list)
    # outputs
    target: str = "./Mods"
    json_report: str | None = None
    emit_pinned_manifest: str | None = None
    events: str | None = None
    list_mods: str | None = None
    describe_mods: str | None = None
    # a game folder's backup and restore (ADR-0042)
    backup: str | None = None           # GAME_DIR to back up
    backup_to: str | None = None        # where backups go
    verify_backup: str | None = None
    restore_backup: str | None = None
    restore_to: str | None = None       # the game folder (else the one backed up)
    apply: bool = False                    # restore: do it, not only show it
    emit_selection: str | None = None
    emit_bio_code: str | None = None
    plan_order: str | None = None
    resolve_conflicts: bool = False
    decisions: str | None = None        # decisions.json: the player's answers
    simulate: bool = False
    bgee_dir: str | None = None
    bg2ee_dir: str | None = None
    emit_installer: bool = False
    language_preference: Any = None        # "fr_FR,en_US" or a parsed list
    game_language: str | None = None
    conflict_report: str | None = None
    show_advisories: bool = False
    quiet: bool = False
    # behaviour
    include_optional: bool = False
    reassign_phase: bool = False
    check_only: bool = False
    dry_run: bool = False
    force: bool = False
    refresh: bool = False
    workers: int = 4
    allow_manual: bool = False
    accept_suggestions: bool = False
    # security and network
    allow_http: bool = False
    allow_exe: bool = False
    no_discovery: bool = False
    trusted_owners: str | None = None
    trusted_owner: list[str] = field(default_factory=list)
    discovery_attempts: int = 1
    owner_cache: str | None = None
    accept_offsite: bool = False
    max_bytes: int = DEFAULT_MAX_BYTES
    timeout: int = 45
    retries: int = 3
    # GitHub credential
    token_file: str | None = None
    no_gh_cli: bool = False
    no_git_credential: bool = False
    oauth_client_id: str | None = None
    # community data (ADR-0032)
    update_data: bool = False
    no_update_data: bool = False
    data_dir: str | None = None
    data_max_age: int = datasync.DEFAULT_MAX_AGE_HOURS
    no_default_data: bool = False

    @classmethod
    def from_namespace(cls, namespace) -> Settings:
        """From the command line's parsed arguments (or anything with the names)."""
        values = {}
        for f in fields(cls):
            if hasattr(namespace, f.name):
                value = getattr(namespace, f.name)
                if value is None and isinstance(getattr(cls(), f.name), list):
                    value = []
                values[f.name] = value
        return cls(**values)


@dataclass
class Outcome:
    """What a run produced. Any part may be None when the run did not make it."""
    exit_code: int
    report: RunReport | None = None
    order_plan: Any = None                  # ordering.OrderPlan, with --plan-order
    conflict_report: ConflictReport | None = None


class _Silent:
    """A stream that discards: `run` prints nothing unless given a stream."""

    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


def run(settings: Settings, stream=None, config=None, on_event=None,
        cancel=None, supplied: Mapping[str, str] | None = None) -> Outcome:
    """
    Do what `settings` asks: list mods, convert a selection, check, plan, fetch.

    `stream` receives the human-readable report (the command line passes
    stdout); `on_event` receives progress events; `cancel` (a threading.Event)
    stops the run. `settings` is not modified. `supplied` ({mod folder:
    path}) installs the file the player saved for a mod instead of
    downloading it (GUI-AUDIT item 68, ADR-0052).
    """
    settings = replace(settings, weidu_log=list(settings.weidu_log or []))
    stream = stream if stream is not None else _Silent()
    if not settings.restore_backup and (settings.apply or settings.restore_to):
        raise ConfigError("--apply and --restore-to go with --restore-backup")
    if not settings.backup and settings.backup_to:
        raise ConfigError("--backup-to goes with --backup")
    if settings.backup or settings.verify_backup or settings.restore_backup:
        # the game folder only: no community data, no network
        return Outcome(exit_code=_backup_action(settings, stream, on_event, cancel))
    if settings.update_data:
        results = update_data(settings, force=True, stream=stream, on_event=on_event)
        return Outcome(1 if all(r.status == "failed" for r in results) else 0)
    _use_data(settings, stream, on_event)
    with tempfile.TemporaryDirectory(prefix="iemod-selection-") as workdir:
        imported = _use_selection(settings, workdir)
        _emit_bio_code(settings, imported, stream)
        return _run(settings, stream, config, on_event, cancel, supplied)


def prepare_https() -> None:
    """
    Build the process's TLS context now (ADR-0048): on Windows that reads the
    whole certificate store while holding the GIL, which a window must not
    wait on. The wizard calls this before its window is shown; a run that
    finds it built does not build it again. A failure here (a broken trust
    store, an SSLKEYLOGFILE that cannot be opened) does not stop the wizard
    opening: nothing is kept, and the first HTTPS client builds it again and
    reports the error as that run's.
    """
    with contextlib.suppress(Exception):
        https_context()


def update_data(settings: Settings | None = None, force: bool = False,
                stream=None, on_event=None) -> list[datasync.SyncResult]:
    """
    Refresh the cached community data (lcc-docs, BWS-NG, krion64).

    Without `force`, a source checked within `settings.data_max_age` hours is
    left alone. A source that cannot be refreshed keeps its last good copy and
    is reported `failed`; this never raises for that.
    """
    settings = settings or Settings()
    results = datasync.refresh(_LazyClient(settings), _data_dir(settings),
                               datasync.SOURCES, max_age_hours=settings.data_max_age,
                               force=force)
    for result in results:
        if on_event is not None:
            on_event({"schema_version": SCHEMA_VERSION, "event": "data_source",
                      "name": result.name, "status": result.status,
                      "commit": result.commit, "date": result.date,
                      "changed": result.changed, "detail": result.detail,
                      "changes": result.changes})
    if stream is not None and not settings.quiet:
        for line in datasync.describe(results):
            if line.endswith(", fresh"):
                continue
            if line.startswith("    "):            # the detail of a change
                print(f"                {line.strip()}", file=stream)
            else:
                print(f"  data        : {line}", file=stream)
    return results


def data_status(data_dir: str | None = None) -> dict:
    """What the cache holds: per source, its repository, commit, date and check time."""
    return datasync.load_manifest(data_dir or datasync.default_data_dir())


def _data_dir(settings: Settings) -> str:
    return settings.data_dir or datasync.default_data_dir()


def _use_data(settings: Settings, stream, on_event) -> None:
    """
    Refresh the community data if it is older than `data_max_age`, then use it
    for every source flag the run was not given (ADR-0032). An explicit flag
    always wins; `--no-default-data` turns the defaults off.
    """
    if not (settings.no_update_data or os.environ.get("IEMOD_NO_UPDATE_DATA")):
        update_data(settings, stream=stream, on_event=on_event)
    if settings.no_default_data:
        return
    cached = datasync.data_paths(_data_dir(settings))
    if not settings.catalogue and cached.catalogue:
        settings.catalogue = [cached.catalogue]
    if not settings.rules and cached.rules:
        settings.rules = list(cached.rules)
    if not settings.mod_db and cached.mod_db:
        settings.mod_db = cached.mod_db
    if not settings.order_catalogue and cached.order_catalogue:
        settings.order_catalogue = cached.order_catalogue
    if not settings.eet_sequence and cached.eet_sequence:
        settings.eet_sequence = cached.eet_sequence
    if not settings.releases and cached.releases:
        settings.releases = cached.releases


def _before_eet_core(settings: Settings):
    """What may precede the EET core: BWS-NG's sequence if given, else EET's rule."""
    return before_eet_core(_eet_sequences(settings))


def _eet_sequences(settings, warnings: list[str] | None = None) -> dict | None:
    """
    BWS-NG's games/eet.json (--eet-sequence); None when not given, or not in
    the shape expected (the readers then stand on EET's own rule). A file
    given by hand that cannot be read stops the run; the data cache's own copy
    is only warned about: a broken download must not block every plan (review
    of #71).
    """
    if not settings.eet_sequence:
        return None
    try:
        with open(settings.eet_sequence, encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else None
    except (OSError, ValueError) as exc:
        cached = datasync.data_paths(_data_dir(settings)).eet_sequence
        if cached and os.path.abspath(cached) == os.path.abspath(settings.eet_sequence):
            if warnings is not None:
                warnings.append(f"BWS-NG's cached games/eet.json cannot be read ({exc}): "
                                f"its sequence places nothing; update the data")
            return None
        raise ConfigError(f"cannot read --eet-sequence {settings.eet_sequence}: "
                          f"{exc}") from exc


class _LazyClient:
    """
    The HTTP client, built on first use. Finding a credential runs `gh` and
    git's credential helper; a cache checked within the hour needs neither.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client: HttpClient | None = None

    def _get(self) -> HttpClient:
        if self._client is None:
            self._client = _http_client(self._settings)
        return self._client

    def get_json(self, url: str):
        return self._get().get_json(url)

    def read_bytes(self, url: str, limit: int | None = None) -> bytes:
        return self._get().read_bytes(url, limit=limit)


def _http_client(settings: Settings) -> HttpClient:
    credential = resolve_credential(token_file=settings.token_file,
                                    use_gh=not settings.no_gh_cli,
                                    use_git_credential=not settings.no_git_credential,
                                    oauth_client_id=settings.oauth_client_id)
    client = HttpClient(token=credential.token, allow_http=settings.allow_http,
                        timeout=settings.timeout, max_bytes=settings.max_bytes,
                        retries=settings.retries)
    client.etags = ETagCache(_etag_dir(settings))
    return client


def _etag_dir(settings: Settings) -> str:
    """Beside the community data, never inside it: a refresh swaps that folder whole."""
    return os.path.normpath(_data_dir(settings)) + "-http"


def list_mods(manifest: str | None = None, catalogues: Sequence[str] = (),
              mod_db: str | None = None, allow_http: bool = False,
              releases: str | None = None,
              weidu_logs: Sequence[str] = ()) -> list[AvailableMod]:
    """
    Every mod the given sources know about, one entry each, sorted by name.

    `releases` is krion64's version_cache.json (its sibling mods/ adds the
    versions krion64 records); with `weidu_logs` ("PATH" or "PATH:GAME") each
    mod also says what is installed and whether a newer version exists (M2d).
    """
    if manifest and (os.path.exists(manifest) or not (catalogues or mod_db)):
        loaded = load_manifest(manifest, allow_http=allow_http)
    else:
        loaded = Manifest()       # a catalogue alone is enough to choose from
    release_cache, versions = _releases(releases)
    return available_mods(loaded, CatalogueSet.load(catalogues),
                          ModDatabase.load(mod_db) if mod_db else None,
                          releases=release_cache, versions=versions,
                          installed=_installed_versions(weidu_logs))


def _github_releases(settings) -> dict:
    """
    Mod key -> (owner/repo, its latest release) from krion64's daily scan, for
    the repository named like the mod: what a copy from elsewhere is compared
    with (ADR-0039 amendment). Only a repository whose name is the mod's, or
    holds it - one named exactly like it first: "the newest any repository of
    the mod names" would offer RoxanneSHS/Finch v53 for Pocket Plane's
    finchnpc, a repository it cannot tell from a fork. The repository is read from the release's own URL, so a renamed
    one (InfinityMods/Ascension, now Gibberlings3's) is downloaded from where
    it lives; without one, as a source spells it rather than lowercased.
    """
    if not settings.releases:
        return {}
    cache, _ = _releases(settings.releases)
    out = {}
    for mod in list_mods(settings.manifest, settings.catalogue, settings.mod_db,
                         settings.allow_http, settings.releases):
        if not mod.key:
            continue
        named = [(normalize_key(repo.split("/", 1)[1]), repo) for repo in mod.repos]
        ranked = ([r for n, r in named if n == mod.key]
                  + [r for n, r in named if n != mod.key and mod.key in n])
        spelled = {s["github"].lower(): s["github"] for s in mod.sources
                   if isinstance(s.get("github"), str)}
        for repo in ranked:
            release = cache.get(repo)
            if release and not release.archived:
                out[mod.key] = (repo_from_url(release.url or "")
                                or spelled.get(repo, repo), release)
                break
    return out


def _releases(path: str | None):
    if not path:
        return {}, []
    try:
        with open(path, encoding="utf-8") as fh:
            cache = parse_release_cache(json.load(fh))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"--releases: cannot read {path}: {exc}") from None
    krion = os.path.join(os.path.dirname(os.path.abspath(path)), "mods")
    return cache, ([ModDatabase.load(krion, origin="krion64")]
                   if os.path.isdir(krion) else [])


def _installed_versions(specs: Sequence[str]) -> dict:
    """Mod key -> the version its WeiDU.log records, where it records one."""
    if not specs:
        return {}
    installed = parse_weidu_files([split_log_spec(spec) for spec in specs])
    return {normalize_key(mod.folder): mod.version
            for mod in installed.mods.values() if mod.version}


def load_selection(path: str) -> Selection:
    """Read and validate a selection.json; ConfigError names where and why."""
    with open(path, encoding="utf-8") as fh:
        return parse_selection(fh.read(), source=path)


def selection_of_logs(specs: Sequence[str]) -> Selection:
    """The selection that says what these WeiDU.logs ("PATH" or "PATH:GAME") say."""
    logs = []
    for spec in specs:
        path, game = split_log_spec(spec)
        logs.append((game, parse_weidu_files([(path, game)])))
    return selection_from_logs(logs)


_MAX_TEXT_BYTES = 8 * 1024 * 1024
_WEIDU_OS = "win32" if sys.platform.startswith("win") else (
    "osx" if sys.platform == "darwin" else "unix")


def _text_under(root: str, relative: str) -> str | None:
    """
    A mod's text file by the path its tp2 writes, as WeiDU on Windows finds it:
    case-insensitive, separators either way. Nothing outside `root` is read:
    `..` and symbolic links are refused at every step (an extracted mod never
    holds a link - archives.py refuses them), and the file itself is opened
    without following one.
    A file that cannot be read is None, like a missing one.
    """
    try:
        path = os.path.realpath(root)
        for part in relative.replace("\\", "/").split("/"):
            if part in ("", "."):
                continue
            # A drive ("C:"), a stream ("x:y") or an absolute part would leave root.
            if part == ".." or ":" in part or os.path.isabs(part) or not os.path.isdir(path):
                return None
            direct = os.path.join(path, part)
            if not os.path.lexists(direct):
                matches = [e for e in os.listdir(path) if e.lower() == part.lower()]
                if not matches:
                    return None
                direct = os.path.join(path, matches[0])
            if os.path.islink(direct):
                return None
            path = direct
        real_root = os.path.realpath(root)
        if os.path.commonpath([real_root, os.path.realpath(path)]) != real_root:
            return None
        if not stat.S_ISREG(os.lstat(path).st_mode):    # a FIFO would block the open
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as fh:
            info = os.fstat(fh.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_TEXT_BYTES:
                return None
            data = fh.read(_MAX_TEXT_BYTES + 1)
    except OSError:
        return None
    return _decode_text(data, relative)


def _decode_text(data: bytes, path: str = "") -> str:
    """
    UTF-8 (EE mods), else the code page of the language folder in `path` as
    WeiDU infers it (Russian cp1251, Polish and Czech cp1250, Chinese cp936,
    ...; GUI-AUDIT item 44), else Windows-1252 (pre-EE: 0x92
    is an apostrophe, not a control character), else Latin-1 for the five
    bytes 1252 leaves out.
    """
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    for charset in dict.fromkeys((legacy_charset(path), "cp1252")):
        try:
            return data.decode(charset)
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1")


# The wizard's project: one folder, one iemod-fetch.ini the CLI reads too
# (ADR-0031: every phase saves a file the command line also understands).
PROJECT_FILE = _config.FILENAME
_GUI_SECTION = "iemod-fetch-gui"
GAMES = ("EET", "BGEE", "BG2EE")


def check_game_folders(game: str, bgee_dir: str | None = None,
                       bg2ee_dir: str | None = None) -> dict:
    """
    Whether the folders are what `game` needs, as WeiDU's GAME_IS sees them:
    {"ok", "games": {"bgee", "bg2ee"}, "sod", "problems", "notes"}.
    """
    report = gamedir.check_folders(game, bgee_dir, bg2ee_dir)
    return {"game": game.upper(), "ok": not report.problems,
            "games": {"bgee": report.games[0], "bg2ee": report.games[1]},
            "sod": report.sod, "problems": list(report.problems),
            "notes": list(report.notes)}


def languages() -> list[dict]:
    """Every language a preference can name, as {"code", "name"}."""
    return [{"code": code, "name": name} for code, name in LANGUAGES]


def load_project(folder: str) -> dict:
    """
    The project saved in `folder` (its iemod-fetch.ini): game, the two game
    folders and the language preference. Missing values are None or []; a file
    that cannot be read is `problem`, with nothing else filled in.
    """
    path = os.path.join(folder, PROJECT_FILE)
    project: dict = {"path": path, "game": None, "bgee_dir": None, "bg2ee_dir": None,
                     "language_preference": [], "target": None, "problem": None}
    try:
        values = _config.load_config(explicit=path).values if os.path.isfile(path) else {}
        preference = values.get("language_preference")
        project["language_preference"] = parse_preferences(preference) if preference else []
    except ConfigError as exc:
        # A file the CLI would refuse too: say so, and start from nothing chosen.
        project["problem"] = str(exc)
        return project
    game = (_config.read_section(path, _GUI_SECTION).get("game") or "").upper()
    project.update(game=game if game in GAMES else None,
                   bgee_dir=values.get("bgee_dir"), bg2ee_dir=values.get("bg2ee_dir"),
                   target=values.get("target"))
    return project


def save_project(folder: str, game: str, bgee_dir: str | None = None,
                 bg2ee_dir: str | None = None,
                 language_preference: Sequence[str] = ()) -> str:
    """
    Write the project into `folder`/iemod-fetch.ini, keeping every other
    option there: `iemod-fetch` run in that folder then uses the same game
    folders and languages. A folder the game does not use is removed.
    """
    game = game.upper()
    if game not in GAMES:
        raise ConfigError(f"unknown game {game!r}: one of {', '.join(GAMES)}")
    preference = parse_preferences(list(language_preference))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, PROJECT_FILE)
    _config.write_values(path, {
        "bgee_dir": bgee_dir if game in ("EET", "BGEE") and bgee_dir else None,
        "bg2ee_dir": bg2ee_dir if game in ("EET", "BG2EE") and bg2ee_dir else None,
        "language_preference": ",".join(preference) if preference else None,
    }, extra={_GUI_SECTION: {"game": game}})
    return path


SELECTION_FILE = "selection.json"


def mod_choices(game: str | None = None, target: str | None = None,
                data_dir: str | None = None, catalogues: Sequence[str] = (),
                mod_db: str | None = None, krion: str | None = None,
                releases: str | None = None, manifest: str | None = None,
                weidu_logs: Sequence[str] = (), preferences: Sequence[str] = ()) -> list[dict]:
    """
    Every mod a player can choose for `game`, with its components (ADR-0035):
    list_mods' entry plus "tp2s" - per tp2, its components and where they come
    from: the staged mod's own tp2 under `target` (exact), else krion64's
    records (`krion` is its data/ folder). Sources not given come from the
    community-data cache (`data_dir`), as a run uses them. A mod with no known
    games is kept: unknown is not "does not run".
    """
    cached = datasync.data_paths(data_dir or datasync.default_data_dir())
    catalogues = list(catalogues) or ([cached.catalogue] if cached.catalogue else [])
    mod_db = mod_db or cached.mod_db
    krion = krion or cached.order_catalogue
    releases = releases or cached.releases
    mods = list_mods(manifest=manifest, catalogues=catalogues, mod_db=mod_db,
                     releases=releases, weidu_logs=weidu_logs)
    # the day of krion64's data, said beside what it says (item 51): from the
    # cache's record of what it fetched, when the data is the cache's
    krion_date = (_source_day(data_dir or datasync.default_data_dir(), "krion64")
                  if releases == cached.releases else None)
    if target and os.path.isdir(target):
        # the day each copy under `target` was fetched: lcc-docs' newer date
        # marks it "maybe updated" (ADR-0044); a copy put there by hand has none
        mark_fetched(mods, _fetch_days(target))
    staged = (choices.from_described(describe_mods(target, preferences))
              if target and os.path.isdir(target) else {})
    records = os.path.join(krion, "mods") if krion else None
    krion_tp2s = (choices.from_krion(_json_records(records))
                  if records and os.path.isdir(records) else {})
    tp2s = choices.merged(staged, krion_tp2s)
    wanted = (game or "").lower()
    out = []
    for mod in mods:
        if wanted and mod.games and wanted not in {g.lower() for g in mod.games}:
            continue
        entry = mod.as_dict()
        # the wizard's only, not the CLI's mods-v1 document (ADR-0044)
        entry.update(page=mod.page, fetched=mod.fetched, maybe_updated=mod.maybe_updated,
                     release=mod.release, krion_notes=[list(n) for n in mod.notes],
                     krion_date=krion_date)
        entry["tp2s"] = []
        for tp2 in tp2s.get(choices.folder_key(mod.tp2), []):
            described = tp2.as_dict()
            # A path selection.json would refuse cannot be chosen: say why.
            described["refused"] = tp2_problem(tp2.tp2)
            described["key"] = tp2_key(tp2.tp2)      # what rules and options name
            entry["tp2s"].append(described)
        out.append(entry)
    return out


def _source_day(data_dir: str, name: str) -> str | None:
    """The day of the commit the cache holds of source `name`, or None."""
    entry = datasync.load_manifest(data_dir).get(name)
    day = str(entry.get("date") or "")[:10] if isinstance(entry, dict) else ""
    return day or None


def _fetch_days(target: str) -> dict[str, str]:
    """{mod key: installed_at} for the copies this tool fetched that are still
    the ones in `target`: the folder is there and, where the record has the
    tp2's VERSION, the tp2 still says it (review of #122: a release the
    player unpacked by hand over a fetched folder keeps the old record)."""
    try:
        present = {name.lower(): name for name in os.listdir(target)}
    except OSError:
        return {}
    days = {}
    records: Mapping[str, object] = State.load(target).mods     # a hand-edited file
    for folder, entry in records.items():
        if not isinstance(entry, dict):
            continue
        actual = present.get(folder.lower())
        if actual is None or not os.path.isdir(os.path.join(target, actual)):
            continue
        recorded, tp2_file = entry.get("mod_version"), entry.get("tp2_file")
        if recorded and tp2_file:
            info = read_mod_tp2(os.path.join(target, actual), tp2_file)
            if info is None or info.version != recorded:
                continue
        days[normalize_key(folder)] = str(entry.get("installed_at") or "")
    return days


def save_selection(folder: str, game: str, chosen: Sequence[tuple[str, int]],
                   labels: dict | None = None, data_dir: str | None = None,
                   order_catalogue: str | None = None) -> str:
    """
    Write `folder`/selection.json: `chosen` is (tp2, component number) in
    install order. For EET it is two installs - the BG:EE phase and EET - as
    krion64's categories place each component (ADR-0038). The CLI reads it
    with --selection; it goes through selection.json's own checks first.
    """
    text = selection_to_json(_wizard_selection(game, chosen, labels,
                                               _order_index(data_dir, order_catalogue)))
    parse_selection(text, source="the wizard's selection")      # refuse before writing
    return _write_whole(folder, SELECTION_FILE, text)


def export_selection(path: str, game: str, chosen: Sequence[tuple[str, int]],
                     labels: dict | None = None, data_dir: str | None = None,
                     order_catalogue: str | None = None) -> str:
    """
    A preset (GUI-AUDIT item 19): the choice written as a selection.json at
    `path`, exactly as save_selection writes the project's, so either can be
    loaded back - or given to the command line with --selection.
    """
    text = selection_to_json(_wizard_selection(game, chosen, labels,
                                               _order_index(data_dir, order_catalogue)))
    parse_selection(text, source="the wizard's preset")
    folder, name = os.path.split(os.path.abspath(path))
    return _write_whole(folder, name, text)


def import_selection(path: str, game: str, known_tp2s: Sequence[str] = (),
                     target: str | None = None, data_dir: str | None = None,
                     order_catalogue: str | None = None) -> dict:
    """
    A preset to choose from (GUI-AUDIT item 19): a selection.json, a WeiDU.log,
    a BIO share code or a Project Infinity list, told apart by what the file
    holds. Its components are matched to the catalogue's tp2s (`known_tp2s`,
    as the wizard lists them): by path ignoring case, else by tp2 name - a log
    may spell `SETUP-EEFIXPACK.TP2` where the list has `eefixpack/setup-
    eefixpack.tp2`. A PI list's labels are resolved through the staged tp2s
    under `target`, then krion64's records, as --pi-list does.

    Returns {"kind": "selection" | "weidu-log" | "bio-code" | "pi-list",
    "games": [install games, in order], "chosen": [[tp2, number]] in the
    preset's order, "unmatched": ["tp2 #n" the list does not have],
    "notes": [...]}.
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read(_MAX_TEXT_BYTES + 1)
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    if len(data) > _MAX_TEXT_BYTES:
        raise ConfigError(f"{path}: larger than {_MAX_TEXT_BYTES} bytes, not a preset")
    text = _decode_text(data).lstrip("\ufeff")
    head = text.lstrip()
    notes: list[str] = []
    if head.startswith("{"):
        kind, selection = "selection", parse_selection(text, source=path)
    elif head.startswith(bio.PREFIX):
        kind, selection = "bio-code", bio.decode_share_code(head).to_selection()
    elif re.search(r"^\s*~[^~\r\n]+~\s*#\d+\s*#\d+", text, re.MULTILINE):
        parsed = parse_weidu_log(text, source=path)
        kind = "weidu-log"
        selection = selection_from_logs([(parsed.game or parsed.detect_game() or game,
                                          parsed)])
    else:
        kind = "pi-list"
        index = pi.index_from_described(
            describe_mods(target) if target and os.path.isdir(target) else [])
        order = order_catalogue or datasync.data_paths(
            data_dir or datasync.default_data_dir()).order_catalogue
        krion = os.path.join(order, "mods") if order else None
        if krion and os.path.isdir(krion):
            pi.add_krion(index, _json_records(krion))
        selection, pi_notes = pi.selection_from_pi(pi.parse_pi_list(text), game, index)
        notes += pi_notes
    if not any(install.components for install in selection.installs):
        # a fresh game's WeiDU.log holds only its header: loading it would
        # clear the whole choice, saying nothing
        raise ConfigError(f"{path}: it chooses no component ({kind.replace('-', ' ')})")
    games = [install.game.upper() for install in selection.installs]
    expected = {"EET", "BGEE"} if game.upper() == "EET" else {game.upper()}
    if set(games) - expected:
        notes.append(f"the preset is for {', '.join(games)}; the project is {game.upper()}")
    elif game.upper() == "EET" and "EET" not in games:
        notes.append("the preset is a BG:EE build, not EET; its components are chosen "
                     "for this EET build")
    by_path = {tp2.lower(): tp2 for tp2 in known_tp2s}
    by_name: dict = {}
    for tp2 in known_tp2s:
        by_name.setdefault(tp2_key(tp2), tp2)
    chosen, unmatched = [], []
    for install in selection.installs:
        for choice in install.components:
            known = by_path.get(choice.tp2.lower()) or by_name.get(tp2_key(choice.tp2))
            if known or not known_tp2s:
                chosen.append([known or choice.tp2, choice.component])
            else:
                unmatched.append(f"{choice.tp2} #{choice.component}")
    return {"kind": kind, "games": games, "chosen": chosen, "unmatched": unmatched,
            "notes": notes}


def _order_index(data_dir: str | None, order_catalogue: str | None = None):
    """krion64's install order from the data cache (or the path given), if there."""
    path = order_catalogue or datasync.data_paths(
        data_dir or datasync.default_data_dir()).order_catalogue
    if not path:
        return None
    try:
        return OrderIndex.load(path)
    except ConfigError:
        return None


def _wizard_selection(game: str, chosen: Sequence[tuple[str, int]],
                      labels: dict | None = None, index=None) -> Selection:
    """
    The wizard's choice as a selection. An EET build is two installs: what
    krion64 files under a pre-EET category goes on BG:EE before the
    conversion, the rest on the EET game (ADR-0038). Without krion64's data,
    or for one game, it is one install.
    """
    labels = labels or {}

    def choices(pairs):
        return [Choice(tp2=tp2, component=number,
                       label=one_line_label(labels.get((tp2, number), "")))
                for tp2, number in pairs]

    pairs = list(dict.fromkeys(chosen))
    if game.upper() == "EET" and index is not None:
        def pre_eet(tp2: str, number: int) -> bool:
            slot = index.component(tp2_key(tp2), number) or index.get(tp2_key(tp2))
            return bool(slot and slot.pre_eet)
        before = [pair for pair in pairs if pre_eet(*pair)]
        if before:
            rest = [pair for pair in pairs if not pre_eet(*pair)]
            return Selection([SelectionInstall("BGEE", choices(before)),
                              SelectionInstall("EET", choices(rest))])
    return Selection([SelectionInstall(game.upper(), choices(pairs))])


def _write_whole(folder: str, name: str, text: str) -> str:
    """Write `folder`/`name` whole or not at all: a half-written file is never read."""
    path = os.path.join(folder, name)
    write_text(path, text)
    return path


DECISIONS_FILE = "decisions.json"


def load_decisions(folder: str) -> dict:
    """
    `folder`/decisions.json as {"choose": {finding: option}, "accept": {finding:
    why}, "problem": None or why it could not be read}. A missing file is no
    decisions; an unreadable one is reported, never silently replaced.
    """
    path = os.path.join(folder, DECISIONS_FILE)
    out: dict = {"choose": {}, "accept": {}, "ignored_order": {}, "problem": None}
    if not os.path.exists(path):
        return out
    try:
        with open(path, encoding="utf-8") as fh:
            decisions = parse_decisions(fh.read(), source=path)
    except (OSError, UnicodeDecodeError, ConfigError) as exc:
        out["problem"] = str(exc)
        return out
    out["choose"], out["accept"] = dict(decisions.choose), dict(decisions.accept)
    out["ignored_order"] = {unit: {"after": i.after, "rules": list(i.rules), "why": i.why}
                            for unit, i in decisions.ignored_order.items()}
    return out


def save_decisions(folder: str, choose: dict | None = None,
                   accept: dict | None = None,
                   ignored_order: dict | None = None) -> str:
    """
    Write `folder`/decisions.json (ADR-0033): `choose` maps a finding id to the
    option chosen, `accept` a finding id to why it is accepted. The CLI applies
    it with --decisions; it goes through that reader's checks first.
    `ignored_order` (load_decisions' shape) is the install order's ignored
    rows; None keeps those the file has, so the conflicts page, which never
    shows them, does not drop them.
    """
    if ignored_order is None:
        ignored_order = load_decisions(folder)["ignored_order"]
    text = decisions_to_json(Decisions(
        dict(choose or {}), dict(accept or {}),
        {unit: IgnoredOrder(unit, i["after"], tuple(i["rules"]), i["why"])
         for unit, i in ignored_order.items()}))
    parse_decisions(text, source="the wizard's decisions")    # refuse before writing
    return _write_whole(folder, DECISIONS_FILE, text)


_WEIDU_FILES = (".tp2", ".tpa", ".tph", ".tpp", ".tpc", ".tra")


def _mod_files(mods_dir: str, folder: str) -> dict[str, str]:
    """Every WeiDU file of a mod folder, by its path from the game folder."""
    files: dict[str, str] = {}
    # the log may spell the folder in capitals; on Linux the name must match
    try:
        actual = next((n for n in os.listdir(mods_dir) if n.lower() == folder.lower()), folder)
    except OSError:
        return files
    root = os.path.join(mods_dir, actual)
    for base, _dirs, names in os.walk(root):
        for name in names:
            if name.lower().endswith(_WEIDU_FILES):
                path = os.path.join(base, name)
                try:
                    with open(path, "rb") as fh:
                        data = fh.read()
                except OSError:
                    continue
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    text = data.decode("cp1252", errors="replace")
                files[os.path.relpath(path, mods_dir).replace(os.sep, "/")] = text
    return files


def install_questions(plan_dir: str, mods_dir: str) -> dict:
    """
    The questions the planned install will meet, before it starts (GUI-AUDIT
    item 48, ADR-0049): for every component of `plan_dir`'s WeiDU-BGEE.log and
    WeiDU.log - the two logs mod_installer installs, in that order - the
    READLNs its mod's files reach (iemod_fetch/readln.py, in the language the
    log installs it in), and the answers the log records (`// @wlb-inputs:`).

    Returns {"components": [{"log", "tp2", "number", "language", "questions":
    [{"key", "text", "raw", "known", "conditional", "repeats", "via", "file",
    "line"}], "recorded": [answers], "status", "unread": [...]}],
    "unattended": bool, "counts": {status: n}}. A status is:
      "unknown"     the mod is not in the mods folder, a question's text is set
                    elsewhere, or reading the component could not follow a path
                    (a question may sit there) - even when nothing was found;
      "none"        it asks nothing that was found;
      "answered"    an answer recorded for every question it may ask;
      "maybe"       answers for the questions it surely asks, not for those
                    under a condition, which may or may not come;
      "partial"     fewer answers than the questions it surely asks;
      "unanswered"  questions it surely asks, no answer.
    A question that repeats until valid counts once: the recorded answer is
    taken to be valid. "unattended" holds only with components and every one
    "none" or "answered" - a forecast, not a promise: a lexical reading misses
    what runs at install time. The wizard's planned logs carry no answers yet
    (the phase-5 questionnaire is to write them), so there a component that
    asks is "unanswered" or "maybe" today.
    """
    scans: dict[tuple[str, int], readln.ModPrompts] = {}
    files_of: dict[str, dict[str, str]] = {}
    components = []
    for name in ("WeiDU-BGEE.log", "WeiDU.log"):
        path = os.path.join(plan_dir, name)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8-sig", errors="replace") as fh:   # a BOM is not a line
            lines = fh.read().splitlines()
        for line in lines:
            match = prompts._LOG_LINE.match(line)
            if not match:
                continue
            tp2 = match["path"].replace("\\", "/")
            folder, number, lang = tp2.split("/", 1)[0], int(match["number"]), int(match["lang"])
            if folder.lower() not in files_of:
                files_of[folder.lower()] = _mod_files(mods_dir, folder)
            files = files_of[folder.lower()]
            key = next((k for k in files if k.lower() == tp2.lower()), tp2)
            if (key, lang) not in scans:
                scans[(key, lang)] = readln.scan(key, files, language_index=lang)
            found = scans[(key, lang)]
            asked = found.of(number)
            unread = found.unread_of(number) if key in files else list(found.unread)
            recorded = prompts.wlb_inputs(line) or []
            read = key in files and not unread and all(q.keyed for q in asked)
            ahead = _beforehand(asked) if read else 0
            components.append({
                "log": name, "tp2": tp2, "number": number, "language": lang,
                "questions": [{"key": q.key, "text": q.text, "raw": q.raw, "known": q.keyed,
                               "conditional": q.conditional, "repeats": q.repeats,
                               "via": q.via, "file": q.file, "line": q.line,
                               "beforehand": i < ahead} for i, q in enumerate(asked)],
                "recorded": recorded, "status": _status(read, asked, recorded),
                "unread": unread})
    _one_batch_at_a_time(components)
    _by_question(components)
    return _coverage(components)


def _status(read: bool, asked: Sequence[Any], recorded: Sequence[str]) -> str:
    """install_questions' status of one component (its docstring says each)."""
    conditional = [q.conditional if isinstance(q, readln.Prompt) else q["conditional"]
                   for q in asked]
    if not read:
        return "unknown"
    if not asked:
        return "none"
    if len(recorded) >= len(asked):
        return "answered"
    if len(recorded) >= conditional.count(False):
        return "maybe"
    return "partial" if recorded else "unanswered"


def _coverage(components: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for c in components:
        status = str(c["status"])
        counts[status] = counts.get(status, 0) + 1
    return {"components": components, "counts": counts,
            "unattended": bool(components) and all(c["status"] in ("none", "answered")
                                                   for c in components)}


def _beforehand(asked: Sequence[readln.Prompt]) -> int:
    """
    How many of a component's questions, from the first, can be answered
    before the install (phase-5 questionnaire, ADR-0049). The log's answers
    are given in order, one per question, so an answer is only safe where
    the questions before it are surely asked once: the run stops before a
    question under a condition (if it were not asked, its answer would go
    to the next one) and before a question whose key came already (two
    questions that read alike would share one answer), and ends after a
    question asked until valid (an answer it refused would go to the next
    one). A component with an unknown question has none (install_questions).
    """
    count, seen = 0, set()
    for q in asked:
        if q.conditional or not q.keyed or q.key in seen:
            break
        seen.add(q.key)
        count += 1
        if q.repeats:
            break
    return count


def _batches(components: list[dict]) -> list[list[dict]]:
    """
    The components as mod_installer runs them: one log after the other, the
    consecutive components of one mod in one batch (16.0.0's
    WeiduBatchedComponents). prompts.Answers hands a batch's recorded
    answers out from one queue, so one component's question left without
    its own answer takes the next component's.
    """
    out: list[list[dict]] = []
    for c in components:
        name = (c["log"], prompts.tp2_name(c["tp2"]))
        if out and (out[-1][0]["log"], prompts.tp2_name(out[-1][0]["tp2"])) == name:
            out[-1].append(c)
        else:
            out.append([c])
    return out


def _covers_all(component: dict, given: int) -> bool:
    """`given` answers leave this component nothing to ask - so nothing of
    the next component's can be taken: every question answered, none asked
    until valid (a refused answer takes the next one), all of it read."""
    questions = component["questions"]
    return (component["status"] != "unknown" and given == len(questions)
            and not any(q["repeats"] for q in questions))


def _one_batch_at_a_time(components: list[dict]) -> None:
    """
    In a batch, a component's questions are answerable beforehand only when
    every component before it in the batch can be answered in full: else a
    question of an earlier one, left to the player, would take this one's
    answer (review of #107). Marks the rest not "beforehand".
    """
    for batch in _batches(components):
        open_ = False
        for c in batch:
            if open_:
                for q in c["questions"]:
                    q["beforehand"] = False
            ahead = sum(1 for q in c["questions"] if q["beforehand"])
            if not _covers_all(c, ahead):
                open_ = True


def _by_question(components: list[dict]) -> None:
    """
    Marks each question "by_question": answered by its key when it comes
    (start_install) - its text known and long enough to tell apart
    (prompts.recognisable), one mod_installer puts to anyone at all
    (mi_parser.asked: by its own words, or by the phrase start_install adds
    to its parser config, ADR-0057; else WeiDU waits for its timeout), and no
    other component of its batch asking the same (match_question would not
    know whose it is). The questionnaire offers these and counts them
    answered; no other (review of #111).
    """
    for batch in _batches(components):
        seen: dict[str, set[int]] = {}
        for c in batch:
            for q in c["questions"]:
                if q["known"] and q["text"]:
                    seen.setdefault(" ".join(q["text"].split()), set()).add(c["number"])
        for c in batch:
            for q in c["questions"]:
                text = " ".join(q["text"].split()) if q["known"] else ""
                q["by_question"] = bool(
                    text and prompts.recognisable(text)
                    and mi_parser.asked(q.get("raw") or q["text"])
                    and seen.get(text, set()) == {c["number"]})


INSTALL_ANSWERS_FILE = "install-answers.json"


def writable_answer(answer: str) -> bool:
    """An answer a log line can carry (prompts.writable)."""
    return prompts.writable(answer)


def load_install_answers(folder: str) -> dict[str, dict[str, str | None]]:
    """
    The answers the player gave in the phase-5 questionnaire (ADR-0049),
    kept in `folder`/install-answers.json: {"tp2#number": {question key:
    answer}}. A question is keyed by its .tra reference, else its text
    (readln.Prompt.key), so a reordered or re-planned install finds them
    again. {} when there are none or the file cannot be read; an answer the
    log cannot carry (a comma, a line end - a file edited by hand) is left
    out, so the questionnaire asks it again rather than every install
    failing on it (review of #107).
    """
    try:
        with open(os.path.join(folder, INSTALL_ANSWERS_FILE), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    answers = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, dict):
        return {}
    # None: the player left it to be asked during the install (kept, so the
    # questionnaire does not offer it every time)
    return {str(component): {str(k): (None if v is None else str(v)) for k, v in given.items()
                             if v is None or writable_answer(str(v))}
            for component, given in answers.items() if isinstance(given, dict)}


def save_install_answers(folder: str, answers: dict[str, dict[str, str | None]]) -> str:
    """Keep the questionnaire's answers in `folder` (load_install_answers)."""
    path = os.path.join(folder, INSTALL_ANSWERS_FILE)
    write_text(path, json.dumps({"v": 1, "answers": answers}, indent=1, sort_keys=True,
                                ensure_ascii=False) + "\n")
    return path


def answer_key(component: dict) -> str:
    """How a component of install_questions is named in the stored answers."""
    return f"{prompts.tp2_name(component['tp2'])}#{component['number']}"


def write_install_answers(plan_dir: str, mods_dir: str,
                          answers: dict[str, dict[str, str | None]],
                          coverage: dict | None = None) -> dict:
    """
    Put the player's answers into the planned logs (ADR-0049 point 5), as
    `// @wlb-inputs:` on each component's line, for the questions that can
    be answered beforehand (install_questions' "beforehand"), in order, up
    to the first one with no answer; in a batch, nothing after a component
    left with something to ask (its question would take the answers meant
    for the next). A component with nothing to give keeps its line as the
    plan wrote it. `coverage`: install_questions(plan_dir, mods_dir) when
    already read (it reads every mod's files). Returns the coverage with
    the answers written: what the install will still ask.
    """
    coverage = coverage if coverage is not None else install_questions(plan_dir, mods_dir)
    inputs: dict[str, dict[prompts.Key, list[str]]] = {}
    components = []
    for batch in _batches(coverage["components"]):
        open_ = False
        for component in batch:
            given = answers.get(answer_key(component), {})
            row: list[str] = []
            for question in component["questions"]:
                answer = given.get(question["key"])
                if open_ or not question["beforehand"] or answer is None:
                    break
                row.append(answer)
            if not _covers_all(component, len(row)):
                open_ = True
            if row:
                key = (prompts.tp2_name(component["tp2"]), component["number"])
                inputs.setdefault(component["log"], {})[key] = row
            recorded = row or component["recorded"]
            status = _status(component["status"] != "unknown", component["questions"],
                             recorded)
            # answered by question during the install (start_install): a
            # question whose text is known, with the player's answer for it
            if status in ("maybe", "partial", "unanswered") and all(
                    i < len(recorded) or (q.get("by_question")
                                          and given.get(q["key"]) is not None)
                    for i, q in enumerate(component["questions"])):
                status = "answered"
            components.append({**component, "recorded": recorded, "status": status})
    for name, rows in inputs.items():
        path = os.path.join(plan_dir, name)
        # read as text, written as text: the line ends are this system's,
        # as the plan wrote them (write_text)
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            text = fh.read()
        write_text(path, prompts.set_inputs(text, rows))
    return _coverage(components)


def start_install(plan_dir: str, games: dict[str, str], mods_dir: str,
                  mod_installer: str, weidu: str,
                  ask: Callable[[str, tuple], str | None],
                  on_event: Callable[[Any], None] | None = None,
                  language: str = "en_US", allow_existing: bool = False,
                  resume: bool = False, answers: dict[str, dict[str, str | None]] | None = None,
                  questions: dict | None = None,
                  **timing: float) -> install_run.InstallRun:
    """
    An install of a planned order ready to run (GUI-AUDIT M4 item 22,
    ADR-0045): mod_installer over `plan_dir`'s WeiDU logs, the mods in
    `mods_dir`, onto `games` ({"BGEE": folder, "EET": folder} for EET, else
    one game). Its run() blocks until mod_installer ends and returns an
    Outcome; cancel() stops it from another thread. `on_event` gets each line
    of output, each batch of components started and each answer given;
    `ask(question, batch)` answers what neither EET's folder nor the log's
    recorded `// @wlb-inputs:` answer - None cancels. ConfigError names what
    stops the install before it starts: a folder that is not a game, a game
    with mods already, the mods missing, a program missing. `resume` (item
    23): go on where the games' WeiDU.logs say an earlier install stopped -
    only what is left runs; a game that is not the plan's beginning is
    refused (install_progress says which, beforehand).

    `answers` (load_install_answers' shape) and `questions`
    (install_questions(plan_dir, mods_dir), read if not given): a question
    mod_installer shows is recognised by its expected text and answered by
    its key (ADR-0049) - also one under a condition, which the log's order
    cannot answer; one not recognised takes the log's next answer, as before.
    """
    if questions is None:
        try:
            questions = install_questions(plan_dir, mods_dir)
        except (OSError, ValueError):     # not read: answered in order, as before
            questions = {"components": []}
    expected: dict[prompts.Key, list[tuple[str, str]]] = {}
    by_key: dict[prompts.Key, dict[str, str]] = {}
    row_keys: dict[prompts.Key, list[str]] = {}
    raw: dict[tuple[prompts.Key, str], str] = {}     # as WeiDU prints them (ADR-0057)
    for component in questions.get("components", []):
        key = (prompts.tp2_name(component["tp2"]), component["number"])
        expected[key] = [(q["key"], q["text"] if q["known"] else "")
                         for q in component["questions"]]
        raw.update({(key, q["key"]): q.get("raw") or q["text"]
                    for q in component["questions"] if q["known"] and q["text"]})
        given = (answers or {}).get(answer_key(component), {})
        by_key[key] = {k: v for k, v in given.items() if v is not None}
        # the recorded answers are this program's row (write_install_answers):
        # each one's question is known; any other row is handed out in order
        row = []
        for q in component["questions"]:
            if not q["beforehand"] or given.get(q["key"]) is None:
                break
            row.append(given[q["key"]])
        recorded = list(component.get("recorded", []))
        if recorded and recorded == row[:len(recorded)] and len(recorded) == len(row):
            row_keys[key] = [q["key"] for q in component["questions"][:len(row)]]
    return install_run.start(plan_dir, games, mods_dir, mod_installer, weidu, ask,
                             on_event or (lambda _event: None), language=language,
                             allow_existing=allow_existing, resume_install=resume,
                             expected=expected, by_key=by_key, row_keys=row_keys,
                             raw_texts=raw, **timing)


def install_known_issues(games: dict[str, str], mods_dir: str) -> list[str]:
    """
    Known upstream faults the install of `games` with the mods in `mods_dir`
    will meet, each in words (GUI-AUDIT M8 item 65): said before installing,
    never a refusal. Today: EET's core and a Documents folder registered
    with a space, on Windows (EET's settings would go to a folder the game
    never reads).
    """
    return install_run.known_issues(games, mods_dir)


def install_launch_advice(plan_dir: str, platform: str | None = None) -> list[dict]:
    """
    How to start the game once `plan_dir`'s planned install is done
    (GUI-AUDIT M8 item 71, ADR-0054): for each planned log that installs a
    mod replacing how the game starts - EEex's main component - {"log",
    "tp2", "component", "program", "why", "platform_note"}. `platform`
    defaults to sys.platform; off Windows the note says what EEex needs
    there. Nothing is written; [] when no planned log asks for it.
    """
    logs = {}
    for name in (PRE_EET_LOG, EET_LOG):
        path = os.path.join(plan_dir, name)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                logs[name] = fh.read()
        except OSError:
            continue
    return launch.launch_advice(logs, platform or sys.platform)


def install_readiness(games: dict[str, str], mods_dir: str, weidu: str | None,
                      backups_dir: str | None = None) -> list[str]:
    """
    What may stop the install of `games` or their backup (GUI-AUDIT M8 item
    49, ADR-0055), each in words, never a refusal: room for a backup in
    `backups_dir` (exact), room for the install on each game's drive (an
    upper estimate, said as one), and WeiDU's version against the one this
    program is tested with and against what a staged mod requires. A drive
    whose free space cannot be read (a network path, a drive that is not
    there) is not measured: nothing is said of it, never an error. What
    lands on one drive is added up. It reads every game folder and every
    staged mod - seconds to minutes on a large install - so call it off a
    window's thread.
    """
    return readiness.findings(games, mods_dir, weidu, backups_dir)


def install_progress(plan_dir: str, games: dict[str, str]) -> dict:
    """
    How far the planned install in `plan_dir` went in `games` (GUI-AUDIT M4
    item 23): {"state": "fresh" | "partial" | "finished" | "mismatch",
    "done", "total", "problem", "phases": [{"log", "done", "total",
    "next"}]} - `next` names the first component left. The games' own
    WeiDU.logs are the state; nothing is written.
    """
    if not any(os.path.isfile(os.path.join(plan_dir, name)) for name in (PRE_EET_LOG, EET_LOG)):
        return {"state": "fresh", "done": 0, "total": 0, "problem": None, "phases": []}
    state = install_run.resume_state(plan_dir, games)
    return {"state": state.state, "done": state.done, "total": state.total,
            "problem": state.problem,
            "phases": [{"log": log, "done": phase.done, "total": phase.total,
                        "next": phase.next} for log, phase in state.phases.items()]}


def default_tools_dir() -> str:
    """Where mod_installer and WeiDU are downloaded: beside the community data."""
    return os.path.join(os.path.dirname(os.path.normpath(datasync.default_data_dir())),
                        "tools")


def find_tools(mod_installer: str | None = None, weidu: str | None = None,
               tools_dir: str | None = None) -> dict[str, toolchain.Found]:
    """
    The programs an install runs (GUI-AUDIT M4 item 22b, ADR-0046): each
    where the player says, else on PATH, else downloaded in `tools_dir` -
    with its version, a problem when it cannot be used, a note when it was
    not one this program was tested with.
    """
    folder = tools_dir or default_tools_dir()
    return {toolchain.MOD_INSTALLER: toolchain.find(toolchain.MOD_INSTALLER, mod_installer,
                                                    folder),
            toolchain.WEIDU: toolchain.find(toolchain.WEIDU, weidu, folder)}


def tool_download(tool: str) -> toolchain.Pin | None:
    """What downloading `tool` would fetch on this system (to ask the player
    first), None when nothing can be."""
    return toolchain.pin_for(tool)


def download_tool(tool: str, tools_dir: str | None = None,
                  progress: Callable[[int, int | None], None] | None = None,
                  cancel=None, client=None) -> toolchain.Found:
    """
    Download `tool`'s pinned release into `tools_dir` and check it against
    its sha256 - only on the player's word, as what it fetches is then run
    by the install (ADR-0046). ConfigError when this system has no pin.
    """
    return toolchain.download(client or HttpClient(), tool, tools_dir or default_tools_dir(),
                              progress=progress, cancel=cancel)


def selection_digest(game: str, chosen: Sequence[tuple[str, int]],
                     labels: dict | None = None, folder: str | None = None,
                     data_dir: str | None = None, target: str | None = None) -> str:
    """
    A digest of what a check or a plan of a wizard selection reads: the game,
    the components chosen, their labels, the project files that change the
    answer (its ini, install-order.txt, decisions.json), the data cache's
    record of its last refresh and its cache of the mods' own inis, and the
    mods staged under `target` - each mod folder and the files directly in it
    (its tp2, its metadata ini) - each by size and modification time. The
    same digest twice: nothing to check again (GUI-AUDIT M5b item 35).
    """
    data = data_dir or datasync.default_data_dir()
    paths = [(name, os.path.join(folder, name) if folder else "")
             for name in (PROJECT_FILE, INSTALL_ORDER_FILE, DECISIONS_FILE)]
    paths += [("data", os.path.join(data, datasync.MANIFEST)),
              ("metadata", os.path.join(data, premeta.CACHE_FILE))]
    files = [[name, *_stamp(path)] for name, path in paths]
    return stable_id("selection", game.upper(), [list(key) for key in chosen],
                     sorted([list(key), str(label)] for key, label in (labels or {}).items()),
                     files, _staged_stamp(target))


def _stamp(path: str) -> list[int]:
    """[size, mtime_ns] of `path`, [] when it is not there."""
    try:
        stat = os.stat(path) if path else None
    except OSError:
        return []
    return [stat.st_size, stat.st_mtime_ns] if stat else []


def _staged_stamp(target: str | None) -> list:
    """The mods staged under `target`, two levels deep, by name, size and time:
    a mod staged, removed or extracted again changes it (review of #82)."""
    if not target or not os.path.isdir(target):
        return []
    out = []
    with os.scandir(target) as entries:
        for entry in sorted(entries, key=lambda e: e.name):
            out.append([entry.name, *_stamp(entry.path)])
            if entry.is_dir(follow_symlinks=False):
                with os.scandir(entry.path) as inner:
                    out += [[entry.name, child.name, *_stamp(child.path)]
                            for child in sorted(inner, key=lambda c: c.name)]
    return out


def ignore_order(folder: str, unit: str, after: str, rules: Sequence[str],
                 why: str) -> str:
    """
    Ignore the order rules `rules` that the row `unit` of the install order
    breaks, while it stays just after the row `after` ("" for the first):
    kept in `folder`/decisions.json (M5b item 33, ADR-0033).
    """
    current = load_decisions(folder)
    if current["problem"]:
        raise ConfigError(current["problem"])
    ignored = dict(current["ignored_order"])
    ignored[unit] = {"after": after, "rules": list(rules), "why": why}
    return save_decisions(folder, current["choose"], current["accept"], ignored)


def unignore_order(folder: str, unit: str) -> str:
    """Show the row `unit` as broken again: its ignore is forgotten."""
    current = load_decisions(folder)
    if current["problem"]:
        raise ConfigError(current["problem"])
    ignored = {u: i for u, i in current["ignored_order"].items() if u != unit}
    return save_decisions(folder, current["choose"], current["accept"], ignored)


def selection_conflicts(game: str, chosen: Sequence[tuple[str, int]],
                        labels: dict | None = None, folder: str | None = None,
                        target: str | None = None, data_dir: str | None = None,
                        rules: Sequence[str] = (), mod_db: str | None = None,
                        order_catalogue: str | None = None,
                        fetch_metadata: bool = False,
                        sorting_order: str | None = None) -> dict:
    """
    What fights what in a selection, before anything is downloaded (M3 phase 2,
    ADR-0033): the findings a run with --selection --plan-order reports, each
    with its options and the player's decision from `folder`/decisions.json.

    They are the findings of the run's --conflict-report, with the same ids,
    which are the ids --decisions matches; an order finding the planned order
    settles is marked `fixed_by_plan`. Without an order catalogue there is no
    plan, and the selection is judged as it is. Staged mods
    under `target` add their own tp2's rules, as in a run. Beyond the
    report's fields, each side and each option carries its rule `key` and
    `chosen`: the chosen (tp2, component) pairs it covers - what deselecting
    it removes.

    Returns {"findings": [...], "stale": [decided ids no finding has; none
    when no rule was checked],
    "rules_checked": n, "planned": bool, "problem": None or why decisions.json
    could not be read, "needs": the dependencies the selection satisfies now,
    [{"chosen": [[tp2, n]], "on": [[[tp2, n]] per alternative], "rule"}]}.

    Each mod's own metadata ini (Before/After) is used for the mods not staged
    yet when it is in the data cache; `fetch_metadata` fetches the missing ones
    first (network). `sorting_order` is a Project Infinity Sorting Order file.
    """
    decided = (load_decisions(folder) if folder
               else {"choose": {}, "accept": {}, "problem": None})
    with _selection_analysis(game, chosen, labels, target, data_dir, rules, mod_db,
                             order_catalogue, fetch_metadata, sorting_order,
                             decided) as (settings, analysis, ruleset, plan):
        # Named by role even with no plan: the ids are then the ones a planned
        # run gives, so a decision saved now still matches once there is one.
        installs = _judged_installs(settings, analysis, True)
        report = build_conflict_report(installs, ruleset, analysis.context, plan)
        needs = _needs(installs, ruleset, analysis.context, chosen)
    findings = []
    for finding in report.findings:
        entry = finding.as_dict()
        for name, side in (("left", finding.left), ("right", finding.right)):
            if side is not None:
                entry[name]["key"] = side.key
                entry[name]["chosen"] = _covered(side.key, side.numbers, side.whole_mod,
                                                 chosen)
        for described, option in zip(entry["options"], finding.options, strict=False):
            described["key"] = option.key
            described["chosen"] = _covered(option.key, option.components,
                                           option.whole_mod, chosen)
        entry["decision"] = (
            {"choose": decided["choose"][finding.id]} if finding.id in decided["choose"]
            else {"accept": decided["accept"][finding.id]}
            if finding.id in decided["accept"] else None)
        findings.append(entry)
    known = {f["id"] for f in findings}
    # With no rule to judge by there are no findings, and every decision
    # would look stale: none is called so until something was judged.
    stale = (sorted((set(decided["choose"]) | set(decided["accept"])) - known)
             if report.rules_checked else [])
    return {"findings": findings, "stale": stale, "rules_checked": report.rules_checked,
            "planned": plan is not None, "problem": decided["problem"], "needs": needs}


def _needs(installs, ruleset, context, chosen) -> list[dict]:
    """
    Every dependency rule the selection satisfies now, as chosen pairs: the
    components that need (`chosen`) and, per alternative, what they need
    (`on`) - so unticking a component tells at once who is left without what
    it needs (GUI-AUDIT M5b item 34). A rule already broken is a finding.
    """
    include_optional = bool(context and context.include_optional)
    out = []
    for install in installs:
        for rule in ruleset.rules:
            if rule.kind != DEPENDS or (rule.optional and not include_optional):
                continue
            hit = install.matched(rule.left)
            if not hit:
                continue
            alternatives = []
            for spec in rule.right:
                met = install.matched(spec)
                if met:
                    alternatives.append(_covered(spec.mod, sorted(met), False, chosen))
            alternatives = [a for a in alternatives if a]
            needing = _covered(rule.left.mod, sorted(hit), False, chosen)
            if alternatives and needing:
                out.append({"chosen": needing, "on": alternatives,
                            "rule": f"{rule.left} needs "
                                    + " or ".join(str(spec) for spec in rule.right)})
    return out


@contextlib.contextmanager
def _selection_analysis(game, chosen, labels, target, data_dir, rules, mod_db,
                        order_catalogue, fetch_metadata, sorting_order, decided=None):
    """
    A wizard selection judged as a run judges it: its logs written as
    --selection writes them, the rules checked, and the order planned when
    krion64's data is there - with the "keep both" order the player chose in
    `decided` (load_decisions' dict). Yields (settings, analysis, ruleset, plan).
    """
    data_dir = data_dir or datasync.default_data_dir()
    cached = datasync.data_paths(data_dir)
    rules = list(rules) or list(cached.rules)
    mod_db = mod_db or cached.mod_db
    order_catalogue = order_catalogue or cached.order_catalogue
    index = _order_index(data_dir, order_catalogue)
    selection = _wizard_selection(game, chosen, labels, index)
    with tempfile.TemporaryDirectory(prefix="iemod-selection-") as work:
        logs = []
        for log in selection.weidu_logs():
            path = os.path.join(work, log.name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(log.text)
            logs.append(f"{path}:{log.game}")
        settings = Settings(weidu_log=logs, rules=rules, mod_db=mod_db,
                            order_catalogue=order_catalogue, quiet=True,
                            target=target or os.path.join(work, "Mods"),
                            data_dir=data_dir, fetch_metadata=fetch_metadata,
                            sorting_order=sorting_order,
                            catalogue=[cached.catalogue] if cached.catalogue else [],
                            eet_sequence=cached.eet_sequence)
        installed = parse_weidu_files([split_log_spec(spec) for spec in logs])
        analysis = _check_rules(settings, installed, _Silent())
        ruleset = analysis.ruleset or RuleSet()
        plan = None
        if index is not None and logs:
            unread: list[str] = []
            sequence = bws_sequence(_eet_sequences(settings, unread))
            kinds, roles = _kind_hints(settings), _log_roles(logs)
            decisions = (Decisions(dict(decided["choose"]), dict(decided["accept"]))
                         if decided else None)
            plan, ruleset = _plan_with_decided_order(
                lambda rule_set: plan_order(roles, index, rule_set, analysis.context,
                                            kinds=kinds, sequence=sequence),
                ruleset, analysis.context, decisions)
            plan.warnings.extend(unread)
        yield settings, analysis, ruleset, plan


INSTALL_ORDER_FILE = "install-order.txt"
_PHASE_TITLES = {EET_LOG: "EET", PRE_EET_LOG: "BG:EE before the conversion"}


def selection_plan(game: str, chosen: Sequence[tuple[str, int]],
                   labels: dict | None = None, folder: str | None = None,
                   target: str | None = None, data_dir: str | None = None,
                   rules: Sequence[str] = (), mod_db: str | None = None,
                   order_catalogue: str | None = None,
                   fetch_metadata: bool = False) -> dict:
    """
    The install order of a wizard selection (M3 phase 3, ADR-0038), planned
    as a run with --selection --plan-order plans it. `folder`/install-order.txt,
    the order the player set by hand, is applied as --sorting-order applies it
    (ADR-0037): on top of the rules, and a contradiction is reported.

    Returns {"phases": [{"role", "title", "units": [{"node", "name", "tp2",
    "category", "components": [[tp2, number, label]], "constrained", "after",
    "placed_by",
    "placed_from",
    "no_place", "moved", "flagged"}]}], "cycles": [[names]], "violations": [text], "planned",
    "custom": whether install-order.txt is in use}.
    """
    order_file = os.path.join(folder, INSTALL_ORDER_FILE) if folder else None
    custom = bool(order_file and os.path.isfile(order_file))
    return _selection_plan(game, chosen, labels, folder, order_file if custom else None,
                           target, data_dir, rules, mod_db, order_catalogue,
                           fetch_metadata)[0]


INSTALL_PLAN_DIR = "install-plan"


def write_install_plan(game: str, chosen: Sequence[tuple[str, int]],
                       labels: dict | None = None, folder: str = ".",
                       target: str | None = None, data_dir: str | None = None,
                       rules: Sequence[str] = (), mod_db: str | None = None,
                       order_catalogue: str | None = None,
                       fetch_metadata: bool = False) -> dict:
    """
    The planned WeiDU logs the install runs (GUI-AUDIT M4 item 22c): the
    order selection_plan shows - `folder`/install-order.txt, decisions.json -
    with the project's language preference applied, written to
    `folder`/install-plan/ as `--plan-order` writes them (WeiDU-BGEE.log
    before EET, WeiDU.log). Logs of an earlier plan there are replaced.

    Returns {"plan_dir", "logs": [paths], "languages": [notes], "violations":
    [the order rules the plan breaks, as selection_plan words them], "cycles":
    [[names]]} - for the player to see before installing; ConfigError when
    nothing could be planned (no order data, or nothing chosen).
    """
    order_file = os.path.join(folder, INSTALL_ORDER_FILE)
    project = load_project(folder)
    target = target or project_settings(folder).target
    with _selection_analysis(game, chosen, labels, target, data_dir, rules, mod_db,
                             order_catalogue, fetch_metadata, order_file if os.path.isfile(order_file)
                             else None, load_decisions(folder)) as (
                                 _settings, _analysis, _ruleset, plan):
        if plan is None or not plan.logs:
            raise ConfigError("no install order could be planned: refresh the community "
                              "data, and choose at least one component")
        notes: list[str] = []
        if project["language_preference"]:
            report = apply_language_preference(plan, os.path.abspath(target),
                                               project["language_preference"])
            notes = report.render().splitlines()
        plan_dir = os.path.join(folder, INSTALL_PLAN_DIR)
        for stale in (PRE_EET_LOG, EET_LOG):
            with contextlib.suppress(FileNotFoundError):
                os.remove(os.path.join(plan_dir, stale))
        logs = plan.write(plan_dir)
        violations = [v.summary for v in plan.residual]
        cycles = [list(c) for c in plan.cycles]
    return {"plan_dir": plan_dir, "logs": logs, "languages": notes,
            "violations": violations, "cycles": cycles}


def install_games(folder: str) -> dict[str, str]:
    """The project's game folders as start_install takes them: {"BGEE",
    "EET"} for EET (the BG2:EE folder becomes EET), else the one game."""
    project = load_project(folder)
    game = project["game"]
    if game == "EET":
        return {"BGEE": project["bgee_dir"] or "", "EET": project["bg2ee_dir"] or ""}
    if game == "BGEE":
        return {"BGEE": project["bgee_dir"] or ""}
    if game == "BG2EE":
        return {"BG2EE": project["bg2ee_dir"] or ""}
    raise ConfigError("the project names no game: choose it on the first page")


def preview_install_order(game: str, chosen: Sequence[tuple[str, int]],
                          labels: dict | None = None, folder: str | None = None,
                          phases: Sequence[Sequence[dict]] | None = None,
                          target: str | None = None, data_dir: str | None = None,
                          rules: Sequence[str] = (), mod_db: str | None = None,
                          order_catalogue: str | None = None,
                          fetch_metadata: bool = False) -> dict:
    """
    What selection_plan would give for `chosen` with `phases` as the order
    set by hand (as save_install_order takes it; None: the computed order),
    writing nothing to `folder`: a fix on the order page, previewed (M5b item
    32). Beyond selection_plan's keys, "errors": the summaries of the
    blocking findings that are not about order - what dropping a component
    can add (a mod that needs it).
    """
    with tempfile.TemporaryDirectory(prefix="iemod-preview-") as work:
        order_file = None
        if phases is not None:
            order_file = os.path.join(work, INSTALL_ORDER_FILE)
            with open(order_file, "w", encoding="utf-8") as fh:
                fh.write(_install_order_text(phases))
        result, findings = _selection_plan(game, chosen, labels, folder, order_file,
                                           target, data_dir, rules, mod_db,
                                           order_catalogue, fetch_metadata)
    result["errors"] = sorted({f["summary"] for f in findings
                               if f["kind"] != ORDER and f["severity"] == "error"
                               and not (f.get("stale_risk") or f.get("suppressed"))})
    return result


def _selection_plan(game, chosen, labels, folder, order_file, target, data_dir, rules,
                    mod_db, order_catalogue, fetch_metadata) -> tuple[dict, list[dict]]:
    """selection_plan's result with `order_file` as the order set by hand,
    and the rule pass's findings."""
    custom = order_file is not None
    decided = load_decisions(folder) if folder else None   # "keep both" orders
    with _selection_analysis(game, chosen, labels, target, data_dir, rules, mod_db,
                             order_catalogue, fetch_metadata, order_file, decided) as (
                                 _settings, analysis, _ruleset, plan):
        if plan is None:
            return ({"phases": [], "cycles": [], "violations": [], "planned": False,
                     "custom": custom}, analysis.findings)
        # per unit, not per mod: a split mod's other parts are neither moved
        # nor wrong because one part is (review of #74)
        moved = {(move.key, move.display) for move in plan.moved}
        names = {u.node: u.display for units in plan.logs.values() for u in units}
        phases: list[dict] = []
        for role in (PRE_EET_LOG, EET_LOG):
            units = plan.logs.get(role)
            if not units:
                continue
            title = (_PHASE_TITLES[role] if game.upper() == "EET"
                     else game.upper())
            phases.append({"role": role, "title": title, "units": [{
                "node": unit.node, "name": unit.display, "tp2": unit.tp2_file,
                "key": unit.key, "part": unit.part, "split": unit.split,
                "category": unit.slot.category if unit.slot else "",
                "components": [[path.replace("\\", "/"), number, comment]
                               for path, _lang, number, comment in unit.lines],
                "constrained": unit.node in plan.constrained,
                # the units a rule puts before it, by node: what the page
                # re-checks at once after a drop (item 31)
                "after": sorted(plan.rule_edges.get(unit.node, ())),
                # BWS-NG's sequence or its kind placed it, krion64 having
                # no place for it (items 27, 27a)
                "placed_by": unit.placed_by,
                "placed_from": unit.placed_from,
                "no_place": unit.no_place,
                "moved": (unit.key, unit.display) in moved,
                # what an order rule still finds wrong; a cycle names every
                # unit left when it was broken, so it is reported, not marked
                "flagged": bool(_broken(unit, plan.residual)),
                # the rules it breaks, as the plan words them, and every
                # order rule on it - the page's panel (item 33)
                "broken": _broken(unit, plan.residual),
                "rules": _rules_on(unit, plan, names),
            } for unit in units]})
        ignored = decided["ignored_order"] if decided else {}
        for phase in phases:
            above = ""
            for entry in phase["units"]:
                held = ignored.get(entry["node"])
                # an ignore holds while the row stays where it was and breaks
                # nothing new (item 33)
                entry["ignored"] = (
                    {"why": held["why"], "after": held["after"]}
                    if held and IgnoredOrder(entry["node"], held["after"],
                                             tuple(held["rules"]), held["why"]).holds(
                                                 above, set(entry["broken"]))
                    else None)
                above = entry["node"]
        return {"phases": phases, "cycles": [list(c) for c in plan.cycles],
                "violations": [v.summary for v in plan.residual],
                "planned": True, "custom": custom}, analysis.findings


def _broken(unit, violations) -> list[str]:
    """The order rules the plan could not keep that name this unit - its
    mod, and where the violation says which, one of its components - as the
    plan words them."""
    numbers = {line[2] for line in unit.lines}
    out = []
    for violation in violations:
        for at, key in enumerate(violation.mods[:2]):
            if key != unit.key:
                continue
            named = violation.left_components if at == 0 else violation.right_components
            if (not named or numbers & set(named)) and violation.summary not in out:
                out.append(violation.summary)
    return out


def _rules_on(unit, plan, names: dict) -> list[dict]:
    """
    The order rules on `unit` (not the player's own order): each with the
    unit it must come after or before, the rule as written, where it comes
    from, and whether it names a whole mod rather than components - the
    order page's panel (M5b item 33).
    """
    out = []
    for (second, first), rules in sorted(plan.edge_rules.items()):
        if unit.node not in (second, first):
            continue
        other, must = (first, "after") if second == unit.node else (second, "before")
        for rule in rules:
            out.append({
                "node": other, "name": names.get(other, other), "must": must,
                "rule": f"{rule.left} {rule.direction} "
                        + ", ".join(str(spec) for spec in rule.right),
                "source": rule.source or rule.origin, "severity": rule.severity,
                "whole": rule.left.components is None
                or any(spec.components is None for spec in rule.right)})
    return out


def order_breaks(order: Sequence[str], before: dict) -> set[tuple[str, str]]:
    """The rule pairs an order of a phase's units breaks: (unit, the one a
    rule puts before it). `before` is each unit's `after` from selection_plan,
    by node. The order page's full check after a drop (M5b item 31)."""
    return broken_pairs(order, before)


def order_breaks_after_move(previous: set, order: Sequence[str], before: dict,
                            moved: str, followers: dict | None = None) -> set:
    """`order_breaks` after one unit moved, looking only at its own pairs;
    `followers` is order_followers(before), made once per plan."""
    return broken_after_move(previous, order, before, moved, followers)


def order_fixes(order: Sequence[str], before: dict, node: str,
                followers: dict | None = None) -> list[dict]:
    """
    The moves of the unit `node` alone that mend a rule it breaks and break
    no other (M5b item 32): {"kind": "after" or "before", "anchor": the unit
    it goes just after or before, "order": the order with the move made,
    "fixed": the pairs it mends, "left": `node`'s pairs still broken}.
    """
    return [{"kind": fix.kind, "anchor": fix.anchor, "order": list(fix.order),
             "fixed": sorted(fix.fixed), "left": sorted(fix.breaks)}
            for fix in _order_fixes(order, before, node, followers)]


def order_followers(before: dict) -> dict:
    """unit -> the units a rule puts after it (the reverse of `before`)."""
    return reverse(before)


def save_install_order(folder: str, phases: Sequence[Sequence[dict]]) -> str:
    """
    Write the order the player set by hand, `phases` being each phase's units
    (as selection_plan gives them) in the order wanted, as
    `folder`/install-order.txt: a Project Infinity Sorting Order file, which
    the CLI reads with --sorting-order and PI itself can apply.
    """
    text = _install_order_text(phases)
    # The project's ini names it first, so the command line uses it too: if
    # the ini cannot be written, no order file is left for the wizard alone.
    project = os.path.join(folder, PROJECT_FILE)
    before = _config.read_section(project, _config.SECTION).get("sorting_order")
    if before != INSTALL_ORDER_FILE:
        _config.write_values(project, {"sorting_order": INSTALL_ORDER_FILE})
    try:
        return _write_whole(folder, INSTALL_ORDER_FILE, text)
    except BaseException:
        if before != INSTALL_ORDER_FILE:     # put back what was there, if anything
            _config.write_values(project, {"sorting_order": before})
        raise


def _install_order_text(phases: Sequence[Sequence[dict]]) -> str:
    """`phases` as a Sorting Order file, refused before anything is written."""
    lines = ["// Install order set in the iemod-fetch wizard (Project Infinity",
             "// Sorting Order format). Delete this file to use the computed order."]
    # A tp2 in both installs is written with its numbers in each: `*` would
    # name it whole in both (review of #74).
    seen: dict[str, set[int]] = {}
    for index, units in enumerate(phases):
        for unit in units:
            seen.setdefault(unit["tp2"].lower(), set()).add(index)
    for units in phases:
        for unit in units:
            # A tp2 name may hold spaces (`Setup-Unofficial Item Pack.tp2`); its
            # key ignores them, so the line drops them.
            name = "".join(premeta.tp2_name(unit["tp2"]).split())
            if not normalize_key(name):
                raise ConfigError(f"cannot write {unit['tp2']!r} as a sorting order line")
            numbers = " ".join(str(c[1]) for c in unit["components"])
            whole = not unit.get("split") and len(seen[unit["tp2"].lower()]) == 1
            lines.append(f"{name} *" if whole else f"{name} {numbers}")
    text = "\n".join(lines) + "\n"
    sortorder.parse(text, source="the wizard's install order")
    return text


def reset_install_order(folder: str) -> None:
    """Forget the order set by hand: the computed one applies again."""
    project = os.path.join(folder, PROJECT_FILE)
    # First, as above; and only the wizard's own file - a path the player
    # wrote there by hand is theirs.
    if _config.read_section(project, _config.SECTION).get("sorting_order") == INSTALL_ORDER_FILE:
        _config.write_values(project, {"sorting_order": None})
    path = os.path.join(folder, INSTALL_ORDER_FILE)
    if os.path.isfile(path):
        os.unlink(path)


# Settings that name a file, read relative to the project as the command line
# reads them when run in it (target is handled on its own: it has a default).
_PROJECT_PATH_KEYS = ("manifest", "aliases", "catalogue", "rules", "mod_db", "suppress",
                      "token_file", "trusted_owners", "owner_cache", "decisions",
                      "data_dir", "eet_sequence", "releases", "json_report", "events",
                      "emit_pinned_manifest")


def project_settings(folder: str) -> Settings:
    """
    The run `iemod-fetch --config FOLDER/iemod-fetch.ini` makes when started in
    FOLDER: the project ini's values over the defaults, the target and the
    manifest read relative to the project. With no manifest in the ini, the
    community catalogue is the only download source (ADR-0039).
    """
    path = os.path.join(folder, PROJECT_FILE)
    values = _config.load_config(explicit=path).values if os.path.isfile(path) else {}
    names = {f.name for f in fields(Settings)}

    def here(value):                    # a relative path, as read in FOLDER
        if isinstance(value, list):
            return [here(v) for v in value]
        if isinstance(value, str) and value and value != "-":
            return os.path.join(folder, value)
        return value
    settings = Settings(**{key: here(value) if key in _PROJECT_PATH_KEYS else value
                           for key, value in values.items() if key in names})
    settings.target = os.path.join(folder, values.get("target") or "Mods")
    if not values.get("manifest"):
        settings.manifest = None
    return settings


def download_selection(folder: str, on_event=None, cancel=None,
                       only: Sequence[str] = (), take_newer: Sequence[str] = (),
                       supplied: Mapping[str, str] | None = None) -> dict:
    """
    Phase 4 of the wizard (ADR-0039): download, verify and extract every mod of
    `folder`/selection.json into the project's target - the run
    `iemod-fetch --config FOLDER/iemod-fetch.ini --selection
    FOLDER/selection.json` makes in FOLDER. A mod already there and verified is
    skipped, so running again resumes; `only` (mod folders) retries those.
    `take_newer` (mod folders, or ["all"] for every one offered) installs the
    newer GitHub release a run offered for each, over the copy there
    (`--take-newer`, GUI-AUDIT item 59). `supplied` ({mod folder: path}):
    the file the player saved for a mod this tool cannot download, installed
    instead of a download (item 68, ADR-0052; see supply_download).
    `on_event` receives the run's progress events (from worker threads);
    setting `cancel` stops the downloads at their next chunk.

    Returns {"records": [{"folder", "status", "detail", "url", "version",
    "bytes", "error_code", "newer"}], "cancelled": bool, "counts": {...},
    "exit_code": int}; `newer` is the offer ({"version", "installed", "repo",
    "date", "url"}) or None.
    """
    for name, value in (("only", only), ("take_newer", take_newer)):
        if isinstance(value, str):      # a name, not a list: read letter by letter
            raise ConfigError(f"{name} is a list of mod folders, not {value!r}")
    settings = replace(
        project_settings(folder), selection=os.path.join(folder, SELECTION_FILE),
        # the selection is what is wanted, and this is a download
        weidu_log=[], pi_list=None, bio_code=None, only=list(only),
        take_newer=list(take_newer), quiet=True,
        check_only=False, dry_run=False, list_mods=None, describe_mods=None,
        emit_selection=None, emit_bio_code=None, update_data=False,
        all_manifest_entries=False,
        # what only a plan uses: the project's game folders and languages are
        # in its ini for every run, and this run fetches, it does not plan
        plan_order=None, language_preference=None, bgee_dir=None, bg2ee_dir=None,
        decisions=None, resolve_conflicts=False, emit_installer=False, simulate=False)
    outcome = run(settings, on_event=on_event, cancel=cancel, supplied=supplied)
    report = outcome.report
    if report is None:                  # not reached: a download run always reports
        raise ConfigError("the download run produced no report")
    records = [{"folder": r.folder, "status": r.status.value, "detail": r.detail,
                "url": r.url, "version": r.version, "bytes": r.bytes,
                "error_code": r.error_code, "newer": r.newer} for r in report.records]
    # with no catalogue to fall back on, a mod the manifest lacks is not tried
    records += [{"folder": u["folder"], "status": "manual", "detail": u["detail"],
                 "url": None, "version": None, "bytes": 0, "error_code": "unresolved",
                 "newer": None}
                for u in report.unresolved]
    counts = report.counts()
    counts["manual"] = counts.get("manual", 0) + len(report.unresolved)
    return {"records": records, "cancelled": report.cancelled,
            "counts": counts, "exit_code": outcome.exit_code}


def supply_download(folder: str, mod_folder: str, path: str, on_event=None) -> dict:
    """
    Install the file the player saved for one mod of `folder`'s selection, from
    a page this tool cannot download from - Gibberlings3, SHS, Nexus behind
    Cloudflare, a JavaScript button (GUI-AUDIT item 68, ADR-0052). The player
    opens the page (the record's `url`), saves the file and names it here;
    nothing else is read: no folder is scanned or watched. It is held to the
    manifest's pinned sha256 when there is one, and always to what a download
    is held to - an archive, under the byte ceiling, unpacking to this mod
    with its .tp2. A copy already there is replaced and kept in .backup/.

    Returns that mod's record, as download_selection gives it.
    """
    if not os.path.isfile(path):
        raise ConfigError(f"{path} is not a file")
    result = download_selection(folder, on_event=on_event, only=[mod_folder],
                                supplied={mod_folder: os.path.abspath(path)})
    wanted = mod_folder.lower()
    records: list[dict] = result["records"]
    for record in records:
        if record["folder"].lower() == wanted:
            return record
    # the archive's own name for the mod (a renamed mod) is the only record
    if len(records) == 1:
        return records[0]
    raise ConfigError(f"{mod_folder} is not in this project's selection")


def _covered(key: str, numbers: Sequence[int], whole_mod: bool,
             chosen: Sequence[tuple[str, int]]) -> list[list[Any]]:
    """
    The chosen (tp2, number) pairs a side or an option names: the tp2 the key
    names, as the plan keys its units - `eet` is EET.tp2, not EET_end.tp2 in
    the same folder - and only when no tp2 has that key, the folder's.
    """
    chosen = list(dict.fromkeys(chosen))
    named = [c for c in chosen if tp2_key(c[0]) == key]
    if not named:
        named = [c for c in chosen if choices.folder_key(c[0]) == key]
    return [[tp2, number] for tp2, number in named if whole_mod or number in numbers]


def describe_mods(target: str = "./Mods", preferences: Sequence[str] = ()) -> list[dict]:
    """
    Every staged mod's components, named as WeiDU would name them (M2e).

    `target` is the --target directory; WeiDU runs from it, so a tp2's paths
    are read relative to it. `preferences` are language codes in order.
    """
    root = os.path.abspath(target)
    preferences = parse_preferences(preferences) if preferences else []
    out = []
    for path in find_tp2_files(root):
        relative = os.path.relpath(path, root).replace(os.sep, "/")
        text = _text_under(root, relative)
        if text is None:
            continue
        entry = {"tp2": relative}
        entry.update(tra.describe(text, lambda p: _text_under(root, p),
                                  preferences, weidu_os=_WEIDU_OS))
        out.append(entry)
    return out


# --------------------------------------------------------------- internals
def load_bio_code(path: str) -> bio.BioModlist:
    """A BIO share code from a file (the code alone, as BIO copies it)."""
    with open(path, encoding="utf-8") as fh:
        return bio.decode_share_code(fh.read(bio.MAX_CODE_CHARS + 1))


def bio_code_of(selection: Selection, base: bio.BioModlist | None = None) -> str:
    """The BIO-MODLIST-V1 code for `selection`, keeping `base`'s other fields."""
    return bio.encode_share_code(bio.modlist_from_selection(selection, base, __version__))


def _use_selection(settings, workdir: str) -> bio.BioModlist | None:
    """
    Turn --selection or --bio-code into the WeiDU.log inputs every planner
    already reads.

    A selection says what a log says (ADR-0030), so it is written out as one log
    per install and passed on as `-w PATH:GAME`. The logs live only for the run.
    Returns the imported BIO payload, so an export can keep its other fields.
    """
    given = [flag for flag, value in (("--selection", settings.selection),
                                      ("--bio-code", settings.bio_code),
                                      ("--pi-list", settings.pi_list),
                                      ("--weidu-log", settings.weidu_log)) if value]
    if len(given) > 1:
        raise ConfigError(f"{' and '.join(given)} each define what is wanted: "
                          f"give one of them")
    imported = None
    if settings.bio_code:
        imported = load_bio_code(settings.bio_code)
        selection = imported.to_selection()
    elif settings.selection:
        with open(settings.selection, encoding="utf-8") as fh:
            selection = parse_selection(fh.read(), source=settings.selection)
    elif settings.pi_list:
        selection = _pi_selection(settings)
    else:
        return None
    for log in selection.weidu_logs():
        path = os.path.join(workdir, log.name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(log.text)
        settings.weidu_log.append(f"{path}:{log.game}")
    return imported


def _pi_selection(settings) -> Selection:
    """--pi-list PATH:GAME, resolved through the staged tp2s, then krion64's records."""
    path, game = split_log_spec(settings.pi_list)
    if not game:
        raise ConfigError("--pi-list needs the game it installs: --pi-list list.txt:EET")
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = pi.parse_pi_list(fh.read())
    target = os.path.abspath(settings.target)
    index = pi.index_from_described(describe_mods(target) if os.path.isdir(target) else [])
    krion = os.path.join(settings.order_catalogue, "mods") if settings.order_catalogue else None
    if krion and os.path.isdir(krion):
        pi.add_krion(index, _json_records(krion))
    selection, notes = pi.selection_from_pi(lines, game, index)
    for note in notes if not settings.quiet else ():
        print(f"[note] {note}", file=sys.stderr)
    return selection


def _json_records(directory: str):
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if not name.endswith(".json"):
            continue
        try:
            if os.path.getsize(path) > _MAX_TEXT_BYTES:
                continue
            with open(path, encoding="utf-8") as fh:
                record = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(record, dict):
            yield record


def _emit_bio_code(settings, imported, stream) -> None:
    """Write the run's input as a BIO share code (--emit-bio-code)."""
    if not settings.emit_bio_code:
        return
    if not settings.weidu_log:
        raise ConfigError("--emit-bio-code converts what is wanted: give --weidu-log, "
                          "--selection or --bio-code")
    code = bio_code_of(selection_of_logs(settings.weidu_log), imported)
    if settings.emit_bio_code == "-":
        stream.write(code + "\n")
        return
    with open(settings.emit_bio_code, "w", encoding="utf-8") as fh:
        fh.write(code + "\n")
    if not settings.quiet:
        print(f"  bio code    : wrote {settings.emit_bio_code}", file=stream)


def _list_mods(settings, stream) -> int:
    """What a selection screen offers: every mod any given source knows."""
    document = mods_document(list_mods(settings.manifest, settings.catalogue,
                                       settings.mod_db, settings.allow_http,
                                       settings.releases, settings.weidu_log))
    if settings.list_mods == "-":
        stream.write(document)
    else:
        with open(settings.list_mods, "w", encoding="utf-8") as fh:
            fh.write(document)
        if not settings.quiet:
            print(f"  mods        : wrote {settings.list_mods}", file=stream)
    return 0


def backups_dir(game_dir: str) -> str:
    """Where a game folder's backups go unless told: beside it, never in it."""
    game_dir = os.path.abspath(game_dir)
    return os.path.join(os.path.dirname(game_dir),
                        f"{os.path.basename(game_dir) or 'game'}-iemod-backups")


def backup_game(game_dir: str, backups: str | None = None, name: str | None = None,
                on_event=None, cancel=None) -> str:
    """Back a game folder up before installing (ADR-0042); the backup's path."""
    return backup.create(game_dir, backups or backups_dir(game_dir), name=name,
                         on_progress=on_event, cancel=cancel)


def verify_backup(path: str) -> dict:
    return backup.verify(path)


def plan_restore(path: str, game_dir: str | None = None) -> dict:
    """What restoring would do; changes nothing."""
    return backup.plan_restore(path, game_dir or backup.read_manifest(path)["game_dir"])


def restore_backup(path: str, game_dir: str | None = None, on_event=None,
                   cancel=None) -> dict:
    """Bring a game folder back to a backup; deletes nothing (ADR-0042).
    Naming game_dir is what allows restoring into another folder than the
    one backed up."""
    return backup.restore(path, game_dir or backup.read_manifest(path)["game_dir"],
                          on_progress=on_event, cancel=cancel,
                          other_folder=game_dir is not None)


def list_backups(game_dir: str, backups: str | None = None) -> list[dict]:
    return backup.list_backups(backups or backups_dir(game_dir))


def _backup_action(settings, stream, on_event, cancel) -> int:
    def say(line: str) -> None:
        if not settings.quiet:
            print(line, file=stream)

    actions = [flag for flag, value in (("--backup", settings.backup),
                                        ("--verify-backup", settings.verify_backup),
                                        ("--restore-backup", settings.restore_backup)) if value]
    if len(actions) > 1:
        raise ConfigError(f"{' and '.join(actions)}: one at a time")
    try:
        return _backup_step(settings, say, on_event, cancel)
    except (InterruptedError, KeyboardInterrupt):
        say("    stopped: nothing is lost; run the same command again to finish")
        return 1
    except OSError as exc:            # a full disk, a file in use: said, not a traceback
        say(f"    failed: {exc}")
        return 1


def _backup_step(settings, say, on_event, cancel) -> int:
    if settings.backup:
        path = backup_game(settings.backup, settings.backup_to, on_event=on_event,
                           cancel=cancel)
        manifest = backup.read_manifest(path)
        say(f"  backup      : {path} ({len(manifest['copied'])} files copied, "
            f"{len(manifest['inventory'])} listed)")
        if manifest["links"]:
            say(f"    not backed up: {len(manifest['links'])} links, left as they are "
                f"(first: {manifest['links'][0]})")
        return 0
    if settings.verify_backup:
        result = verify_backup(settings.verify_backup)
        say(f"  backup      : {result['files']} files, "
            + ("all as copied" if result["ok"] else "DAMAGED"))
        for problem in result["problems"]:
            say(f"    {problem}")
        return 0 if result["ok"] else 1
    check = verify_backup(settings.restore_backup)
    if not check["ok"]:              # said now, not only once --apply is given
        say(f"  restore     : {settings.restore_backup} is DAMAGED, it cannot be restored")
        for problem in check["problems"]:
            say(f"    {problem}")
        return 1
    plan = plan_restore(settings.restore_backup, settings.restore_to)
    say(f"  restore     : {plan['game_dir']} from {plan['backup']}")
    if os.path.normcase(plan["game_dir"]) != os.path.normcase(plan["backed_up_from"]):
        say(f"    note: the backup was made of {plan['backed_up_from']}")
    say(f"    put back  : {len(plan['put_back'])} files")
    say(f"    move aside: {len(plan['displace'])} files added since")
    for line in plan["cannot_restore"]:
        say(f"    cannot    : {line}")
    if plan["links"] or plan["mounts"]:
        say(f"    left alone: {len(plan['links']) + len(plan['mounts'])} links, junctions or "
            f"other drives, never entered")
    for rel in plan["blocked"][:5]:
        say(f"    blocked   : {rel} (a junction, mount or another drive is on or inside it)")
    say("    folders   : only the ones the moves leave empty, and the backup did not have, "
        "are removed")
    if plan["blocked"]:
        say("    nothing changed: remove what blocks the restore first")
        return 1
    if not settings.apply:
        say("    nothing changed: run again with --apply to restore")
        # 1 when a restore could not bring everything back, shown or done
        return 1 if plan["cannot_restore"] else 0
    result = restore_backup(settings.restore_backup, settings.restore_to,
                            on_event=on_event, cancel=cancel)
    for aside in result["displaced"]:
        say(f"    moved aside to {aside} (nothing was deleted)")
    if result["removed_folders"]:
        say(f"    removed {len(result['removed_folders'])} folders left empty")
    return 1 if result["cannot_restore"] else 0


def _describe_mods(settings, stream) -> int:
    """What a component screen shows: the staged mods' components, by name."""
    document = json.dumps({"schema_version": SCHEMA_VERSION,
                           "mods": describe_mods(settings.target,
                                                 settings.language_preference or ())},
                          indent=2, ensure_ascii=False) + "\n"
    if settings.describe_mods == "-":
        stream.write(document)
    else:
        with open(settings.describe_mods, "w", encoding="utf-8") as fh:
            fh.write(document)
        if not settings.quiet:
            print(f"  components  : wrote {settings.describe_mods}", file=stream)
    return 0


def _render_updates(settings, stream) -> None:
    """
    The update notice: installed mods some source names a newer version of.
    Silent without --releases data or a WeiDU.log; a mod whose versions cannot
    be ranked is counted, never reported as an update.
    """
    if not (settings.releases and settings.weidu_log):
        return
    mods = [m for m in list_mods(settings.manifest, settings.catalogue, settings.mod_db,
                                 settings.allow_http, settings.releases, settings.weidu_log)
            if m.installed]
    newer = [m for m in mods if m.update_available]
    unknown = sum(1 for m in mods if m.update_available is None)
    print(f"  updates     : {len(newer)} of {len(mods)} installed mods with a version "
          f"have a newer one" + (f" ({unknown} not comparable)" if unknown else ""),
          file=stream)
    for mod in newer:
        latest = mod.latest
        if latest is None:
            continue
        where = ", ".join(x for x in (latest.origin, latest.date) if x)
        print(f"    {mod.tp2:<24} {mod.installed} -> {latest.version} ({where})", file=stream)


@contextlib.contextmanager
def _event_sink(path, stream, callback=None):
    """
    The events go to `callback` and, with --events, to a file as one JSON
    object per line, flushed so a reader sees each as it happens.
    """
    if not path:
        yield callback
        return
    with contextlib.ExitStack() as stack:
        out = (stream if path == "-"
               else stack.enter_context(open(path, "w", encoding="utf-8")))

        def write(event: dict) -> None:
            out.write(json.dumps(event, sort_keys=True) + "\n")
            out.flush()
            if callback is not None:
                callback(event)
        yield write


def _emit_selection(settings, stream) -> None:
    """Write the --weidu-log input as the selection.json a UI would save."""
    if not settings.emit_selection:
        return
    if not settings.weidu_log:
        raise ConfigError("--emit-selection converts --weidu-log input: give one")
    with open(settings.emit_selection, "w", encoding="utf-8") as fh:
        fh.write(selection_to_json(selection_of_logs(settings.weidu_log)))
    if not settings.quiet:
        print(f"  selection   : wrote {settings.emit_selection}", file=stream)


@dataclass
class RuleAnalysis:
    """
    What the rule pass produced, passed explicitly to whatever needs it next.

    This used to be stashed on `_check_rules.last`, a function attribute, so the
    order planner and the conflict report could reach it. That is global mutable
    state dressed as a cache: it makes the call order load-bearing and invisible,
    it cannot be constructed in a test without calling the CLI, and mypy is right
    to refuse it. An empty instance means "no rules were loaded", which every
    consumer already handles.
    """
    ruleset: RuleSet | None = None
    context: Context | None = None
    installs: Sequence[Install] = ()
    findings: list[dict] = field(default_factory=list)
    # The staged mods' own tp2 constraints (ADR-0025): part of `ruleset` as
    # rules, and kept whole for the install simulation.
    constraints: ModConstraints | None = None

    def __bool__(self) -> bool:
        return self.ruleset is not None


def _check_rules(settings, installed, stream) -> RuleAnalysis:
    """
    Check each WeiDU log against the rule set, separately.

    One log is one game install: a mod in the BGEE log neither conflicts with
    nor orders against a mod in the EET log, so the logs are never merged for
    this.
    """
    if not settings.weidu_log:
        return RuleAnalysis()
    # A staged mod's own tp2 is a rule source in its own right - checked even
    # when no community rule set is given.
    constraints = _staged_constraints(
        settings, [(split_log_spec(spec)[0], None) for spec in settings.weidu_log])
    if settings.fetch_metadata:
        _fetch_metadata(settings, installed, stream)
    authors = _authors_order(settings, installed)
    sorting = _sorting_rules(settings, installed)
    if not settings.rules and not constraints.by_mod and not authors and not sorting:
        return RuleAnalysis(constraints=constraints)
    ruleset = RuleSet.load(settings.rules) if settings.rules else RuleSet()
    # The author's own Before/After, fetched before download (ADR-0037); a staged
    # mod's own ini is read in _rule_context instead, and wins.
    for name, meta in authors.items():
        ruleset.add_metadata_order(name, meta.before, meta.after,
                                   origin=f"{name}'s own ini ({meta.source})")
    ruleset.rules.extend(sorting)
    if not settings.quiet and (authors or sorting):
        print(f"  own inis    : {len(authors)} mod(s) not staged yet give their order"
              + (f"; sorting order: {len(sorting)} rule(s)" if sorting else ""),
              file=stream)
    if constraints.by_mod:
        ruleset.rules.extend(tp2_rules(constraints))
        if not settings.quiet:
            print(f"  own tp2s    : {constraints.summary()}", file=stream)
    context = _rule_context(settings, installed, ruleset, stream)
    installs = []
    for spec in settings.weidu_log:
        path, game = split_log_spec(spec)
        installs.append(Install.from_log(parse_weidu_files([(path, game)]),
                                         label=os.path.basename(path)))
    # `rule` is the Rule object the finding drilled down from - useful in
    # process, not serialisable, and the conflict report carries it properly.
    findings = [{"id": f.id, **{k: v for k, v in vars(f).items() if k != "rule"}}
                for f in check_all(installs, ruleset, context)]
    if not settings.quiet:
        age = ""
        if ruleset.updated:
            age = f", updated {ruleset.updated}"
            if (ruleset.age_days or 0) > 180:
                age += f" — {ruleset.age_days} days old, verify before acting"
        undirected = (f", {ruleset.undirected} order-sensitive pair(s) not "
                      f"evaluated (no direction recorded)"
                      if ruleset.undirected else "")
        print(f"  rules       : {len(ruleset)} loaded{age}; "
              f"{len(findings)} finding(s){undirected}", file=stream)
    for warning in ruleset.warnings[:5]:
        print(f"[warning] {warning}", file=sys.stderr)
    return RuleAnalysis(ruleset=ruleset, context=context, installs=installs,
                        findings=findings, constraints=constraints)


def _log_roles(specs):
    """
    Decide which input log is the EET install and which is the pre-EET BG1 one.

    An EET setup is two installs, and the plan has to keep them apart. The log
    that installs the EET core IS the merged-game log; the other is the BG1:EE
    phase. `-w PATH:EET` states it outright; otherwise it is inferred from the
    log's own contents, never from the filename - `WeiDUBGEE.log`,
    `weidu-bgee.log` and `bg1.log` are all names people actually use.
    """
    roles, eet_logs = [], []
    for spec in specs:
        path, game = split_log_spec(spec)
        parsed = parse_weidu_files([(path, game)])
        role = EET_LOG if (parsed.game or "").upper() == "EET" else PRE_EET_LOG
        if role == EET_LOG:
            eet_logs.append(path)
        roles.append((path, role))

    if len(eet_logs) > 1:
        raise ConfigError(
            "two logs both look like the EET install (" + ", ".join(eet_logs) +
            "). Name the pre-EET one explicitly, e.g. -w WeiDUBGEE.log:BGEE")
    others = [path for path, role in roles if role == PRE_EET_LOG]
    if len(others) > 1:
        # The plan has one pre-EET install; two logs would be merged into it.
        raise ConfigError(
            "more than one log is not the EET install (" + ", ".join(others) +
            "). An EET plan has one BG:EE phase: give one -w PATH:BGEE and one "
            "-w PATH:EET")
    if not eet_logs and len(roles) > 1:
        raise ConfigError(
            "no log installs the EET core, so which one is the merged game is a "
            "guess. Say so explicitly: -w WeiDU.log:EET")
    return roles


def _kind_hints(settings) -> dict[str, KindHint]:
    """What lcc-docs and BWS-NG say each mod is, for placing what krion64
    does not (ADR-0041 decision 2): the same merge --list-mods shows."""
    if not (settings.catalogue or settings.mod_db):
        return {}
    mods = available_mods(None, CatalogueSet.load(settings.catalogue),
                          ModDatabase.load(settings.mod_db) if settings.mod_db else None)
    return {mod.key: KindHint(mod.kinds, mod.games, tuple(mod.kinds_by_source))
            for mod in mods if mod.kinds}


def _plan_with_decided_order(plan_once, ruleset: RuleSet, context,
                             decisions: Decisions | None):
    """
    The plan, and the rule set it was planned with: where the player chose to
    keep both sides of a conflict, one installed last (decisions.json, item
    28), that order becomes a rule and the plan is made again with it - the
    conflict ids do not depend on the order, so they still match.
    """
    plan = plan_once(ruleset)
    if decisions is None or not decisions.choose:
        return plan, ruleset
    extra = keep_both_rules(build_conflict_report(plan.installs(), ruleset, context, plan),
                            decisions)
    if not extra:
        return plan, ruleset
    ruleset = replace(ruleset, rules=[*ruleset.rules, *extra])
    return plan_once(ruleset), ruleset


def _plan_order(settings, analysis: RuleAnalysis, stream):
    """Build the rule-compliant install order, if asked for."""
    if not getattr(settings, "plan_order", None):
        return None
    if not settings.weidu_log:
        raise ConfigError("--plan-order needs at least one --weidu-log to order")
    if not settings.order_catalogue:
        raise ConfigError(
            "--plan-order needs --order-catalogue PATH: a krion64 data directory "
            "(categories.json + mods/*.json). Without it there is no reference "
            "order to sort towards, and the tool will not invent one")

    index = OrderIndex.load(settings.order_catalogue)
    # Reuse the ruleset the checker just built: it carries the per-mod ordering
    # metadata read from installed .iemod/.ini files on top of --rules. Planning
    # against a thinner ruleset than the check uses would emit a plan the very
    # next check rejects.
    ruleset, context = analysis.ruleset, analysis.context
    if ruleset is None:
        ruleset = RuleSet.load(settings.rules) if settings.rules else RuleSet()
    specs = _log_roles(settings.weidu_log)
    # What each staged mod's own tp2 enforces (ADR-0025) is already in the rule
    # set the check built; the simulation needs the constraints themselves.
    constraints = analysis.constraints or _staged_constraints(settings, specs)
    unread: list[str] = []
    sequence = bws_sequence(_eet_sequences(settings, unread))
    kinds = _kind_hints(settings)
    decisions = None
    if settings.decisions:
        with open(settings.decisions, encoding="utf-8") as fh:
            decisions = parse_decisions(fh.read(), source=settings.decisions)
    plan, ruleset = _plan_with_decided_order(
        lambda rules: plan_order(specs, index, rules, context,
                                 include_optional=settings.include_optional,
                                 reassign_phase=settings.reassign_phase,
                                 kinds=kinds, sequence=sequence),
        ruleset, context, decisions)
    plan.warnings.extend(unread)
    for warning in unread:
        print(f"warning: {warning}", file=stream)
    games = _phase_games(settings, specs)
    resolution = None
    if settings.decisions or settings.resolve_conflicts:
        resolution = ResolutionResult()
        decided: set = set()
        if decisions is not None:
            # The player's answers first: a choice they made is never second-
            # guessed by the automatic resolution that follows.
            report = build_conflict_report(plan.installs(), ruleset or RuleSet(),
                                           context, plan)
            resolution.extend(apply_decisions(plan, report, decisions, ruleset, context))
            decided = decisions.findings
    if settings.resolve_conflicts and resolution is not None:
        # Judged on the PLAN's own installs, so the report's log labels are the
        # plan's roles, and re-verified by the same rules afterwards.
        report = build_conflict_report(plan.installs(), ruleset or RuleSet(),
                                       context, plan)
        resolution.extend(resolve_conflicts(plan, report, ruleset, context, skip=decided))
        if constraints.by_mod:
            resolution.extend(resolve_refusals(plan, constraints, games, ruleset, context,
                                               before_core=_before_eet_core(settings)))
    plan.resolution = resolution
    languages = None
    if settings.language_preference:
        languages = apply_language_preference(plan, os.path.abspath(settings.target),
                                              settings.language_preference)
    written = plan.write(settings.plan_order)
    if resolution is not None:
        path = os.path.join(settings.plan_order, "RESOLUTION.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(resolution.as_dict(), fh, indent=2, sort_keys=True)
            fh.write("\n")
        written.append(path)
    if not settings.quiet:
        print(f"  order plan  : {index.origin} "
              f"({len(index)} mods, {len(index.categories)} categories); "
              f"{plan.edges} ordering constraint(s)", file=stream)
        for path in written:
            print(f"                wrote {path}", file=stream)
        if resolution is not None:
            print("\n" + resolution.render(), file=stream)
        if languages is not None:
            print("\n" + languages.render(), file=stream)
    if settings.simulate:
        plan.simulation = simulate_install(
            {role: steps_of(units) for role, units in plan.logs.items()},
            constraints.by_mod, games=games, eet_rules=constraints.eet)
        if not settings.quiet:
            print("\n" + plan.simulation.render(), file=stream)
    if bool(settings.bgee_dir) != bool(settings.bg2ee_dir) and PRE_EET_LOG in plan.logs:
        print("[warning] the game folders are not checked: an EET install needs "
              "both bgee_dir and bg2ee_dir", file=sys.stderr)
    if settings.bgee_dir and settings.bg2ee_dir:      # an EET install's two games
        plan.game_report = verify_eet(
            settings.bgee_dir, settings.bg2ee_dir,
            plan_mods={unit.key for unit in plan.logs.get(PRE_EET_LOG, [])})
        print("\n" + plan.game_report.render(), file=stream)
    if settings.emit_installer:
        _emit_installer(settings, plan, stream)
    return plan


def _staged_constraints(settings, specs):
    """The tp2 constraints of every planned mod that is already staged."""
    mods = []
    for path, _role in specs:
        parsed = parse_weidu_files([(path, None)])
        for mod in parsed.mods.values():
            for component in mod.components:
                mods.append((tp2_key(component.tp2_file), mod.folder,
                             component.tp2_file))
    target = os.path.abspath(settings.target)
    if not os.path.isdir(target):
        return ModConstraints()
    return load_constraints(target, mods)


def _phase_games(settings, specs):
    """
    Which game each planned log installs on. The pre-EET log is BGEE and the
    EET log starts as BG2EE - unless a single non-EET log names its game
    (`-w WeiDU.log:BG2EE`), which then decides.
    """
    games = {}
    for spec, (_path, role) in zip(settings.weidu_log, specs, strict=False):
        _p, game = split_log_spec(spec)
        if role == PRE_EET_LOG and game and len(specs) == 1:
            games[role] = game
    return games


def _emit_installer(settings, plan, stream) -> None:
    """Write the scripts that hand the plan to mod_installer (ADR-0022)."""
    target = os.path.abspath(settings.target)
    plan_dir = os.path.abspath(settings.plan_order)
    try:
        mods_ref = os.path.relpath(target, plan_dir)
    except ValueError:            # Windows: the mods and the plan on different drives
        mods_ref = target
    installer = build_installer(plan, mods_relpath=mods_ref.replace(os.sep, "/"),
                                mods_dir=target, language=_game_language(settings))
    written = installer.write(plan_dir)
    if settings.quiet:
        return
    print(f"\nINSTALLER ({installer.mode}: mod_installer + WeiDU; review, then run)",
          file=stream)
    for path in written:
        print(f"  wrote {path}", file=stream)
    for problem in installer.problems:
        print(f"  !! {problem}", file=stream)
    for warning in installer.warnings:
        print(f"   ! {warning}", file=stream)
    games = ("BGEE_DIR=<BGEE game> BG2EE_DIR=<BG2EE game>"
             if installer.mode == "eet" else "GAME_DIR=<game>")
    script = "install-eet" if installer.mode == "eet" else "install"
    print(f"  run on a CLEAN copy of the game(s):\n"
          f"    Linux/macOS: {games} sh {os.path.join(plan_dir, script + '.sh')}\n"
          f"    Windows    : set the same variables, then "
          f"{os.path.join(plan_dir, script + '.cmd')}", file=stream)


def _conflict_report(settings, analysis: RuleAnalysis, plan):
    """
    The component-level view: what actually fights what, and the smallest fix.

    Ordering answers "in what sequence"; this answers "and what still clashes
    once the sequence is right". Findings the plan already resolves are marked
    as such instead of being reported twice.
    """
    if analysis.ruleset is None or not analysis.installs:
        return None
    judged = _judged_installs(settings, analysis, plan is not None)
    report = build_conflict_report(judged, analysis.ruleset, analysis.context, plan)
    files = {install.label: original.label
             for install, original in zip(judged, analysis.installs, strict=False)}
    for finding in report.findings:
        if files.get(finding.log, finding.log) != finding.log:
            finding.shown_log = files[finding.log]
    report.engine_limits = _engine_limits(settings)
    resolution = getattr(plan, "resolution", None)
    if resolution is not None:
        # What the plan settled is not outstanding work: an accepted finding is
        # withheld with the player's reason, a removed side is fixed in the plan.
        accepted = {a.finding_id: a.why for a in resolution.accepted}
        removed = {r.finding_id: r for r in resolution.removed if r.finding_id}
        for finding in report.findings:
            if finding.id in accepted:
                finding.suppressed = f"accepted in decisions.json: {accepted[finding.id]}"
            elif finding.id in removed:
                gone = removed[finding.id]
                finding.fixed_by_plan = True
                finding.remedy = (f"{gone.mod} " + ", ".join(f"#{n}" for n in gone.components)
                                  + (" removed by your decision" if gone.by == "decision"
                                     else " removed by --resolve-conflicts"))
    if settings.conflict_report:
        report.write_json(settings.conflict_report)
    return report


def _judged_installs(settings, analysis: RuleAnalysis, by_role: bool):
    """
    The installs the conflict report judges, named as --decisions names them.

    --decisions matches findings on the plan, whose installs are named by role
    (WeiDU.log for the EET game, WeiDU-BGEE.log otherwise), and a finding's id
    includes that name. A log named anything else - every log --selection
    writes, a BG2EE `WeiDU.log` - gave the report ids no decision could match.
    The report shows each log's own file name (Finding.shown_log).
    """
    if not by_role:
        return analysis.installs
    roles = [role for _path, role in _log_roles(settings.weidu_log)]
    return [replace(install, label=role)
            for install, role in zip(analysis.installs, roles, strict=False)]


def _metadata_cache(settings) -> premeta.MetadataCache:
    return premeta.MetadataCache(_data_dir(settings))


def _authors_order(settings, installed) -> dict:
    """
    Fetched metadata inis with an order, for the planned mods NOT staged, by
    tp2 name - what the plan's units and the rules are keyed by. Only an ini
    from the repository the catalogue names today counts; with
    --no-default-data, only when this run asked for them (--fetch-metadata).
    """
    if settings.no_default_data and not settings.fetch_metadata:
        return {}
    pairs = _not_staged(settings, installed)
    cache = _metadata_cache(settings)
    out = {}
    for wanted in _metadata_wanted(settings, pairs):
        meta = cache.get(wanted)
        if meta is not None:
            out[premeta.tp2_name(wanted.tp2_file)] = meta
    return out


def _not_staged(settings, installed) -> list:
    """
    (folder, tp2 path) of every tp2 planned from a mod not staged: its ini is
    not here yet. Per tp2, not per mod - EET's folder holds EET.tp2 and
    EET_end/EET_end.tp2, and each has its own ini.
    """
    target = os.path.abspath(settings.target)
    out: list = []
    seen: set = set()
    for mod in installed.mods.values():
        if os.path.isdir(os.path.join(target, mod.folder)):
            continue
        for component in mod.components:
            path = (component.path or f"{mod.folder}/{component.tp2_file}").replace("\\", "/")
            # Two logs may spell one tp2 differently (EET/EET.tp2, eet/EET.TP2).
            if (mod.folder.lower(), path.lower()) not in seen:
                seen.add((mod.folder.lower(), path.lower()))
                out.append((mod.folder, path))
    return out


def _sorting_rules(settings, installed) -> list:
    if not settings.sorting_order:
        return []
    chosen: dict = {}
    for mod in installed.mods.values():
        for component in mod.components:
            chosen.setdefault(tp2_key(component.tp2_file), set()).add(component.index)
    return sortorder.rules(sortorder.load(settings.sorting_order), chosen)


def _metadata_wanted(settings, folders_tp2s) -> list:
    """Where each mod's ini can be fetched: lcc-docs' repository, else krion64's."""
    catalogue = CatalogueSet.load(settings.catalogue) if settings.catalogue else None
    krion: dict = {}
    if settings.order_catalogue:
        mods_dir = os.path.join(settings.order_catalogue, "mods")
        if os.path.isdir(mods_dir):
            for record in _json_records(mods_dir):
                gh = record.get("gh") if isinstance(record, dict) else None
                if (isinstance(gh, dict) and isinstance(record.get("t"), str)
                        and isinstance(gh.get("o"), str) and isinstance(gh.get("r"), str)):
                    repo = repo_from_url(f"https://github.com/{gh['o']}/{gh['r']}")
                    if repo:
                        krion.setdefault(normalize_key(record["t"]), repo)
    wanted = []
    for folder, tp2_file in folders_tp2s:
        entry = catalogue.find(folder=folder) if catalogue else None
        repo = (entry.github if entry else None) or krion.get(normalize_key(folder))
        if repo:
            wanted.append(premeta.Wanted(folder, tp2_file, repo))
    return wanted


def _fetch_metadata(settings, installed, stream) -> dict:
    cache = _metadata_cache(settings)
    # One try, a short wait: an ini is a nicety, and the wizard checks after
    # every change - offline must cost seconds, not minutes (premeta backs off).
    quick = replace(settings, retries=1, timeout=min(settings.timeout, 15))
    found, missing, problems = premeta.fetch(
        _LazyClient(quick), cache, _metadata_wanted(settings, _not_staged(settings, installed)))
    cache.save()
    if not settings.quiet:
        print(f"  mod inis    : fetched {found}, none for {missing}"
              + (f", {len(problems)} not reachable" if problems else ""), file=stream)
    for problem in problems[:5]:
        print(f"[warning] metadata ini: {problem}", file=sys.stderr)
    return {"found": found, "missing": missing, "problems": problems}


def _rule_context(settings, installed, ruleset, stream):
    """
    Gather what is needed to judge whether a rule is still current: the version
    of each installed mod, the versions the rules were built against, mods that
    ship their own ordering metadata, and any verified suppressions.
    """
    target = os.path.abspath(settings.target)
    context = Context(suppressions=load_suppressions(settings.suppress),
                      include_optional=settings.include_optional)

    if settings.mod_db:
        context.baseline = ModDatabase.load(settings.mod_db)
        if not settings.quiet:
            print(f"  mod database: {len(context.baseline)} mods "
                  f"(versions the rules were written against)", file=stream)

    state = State.load(target)
    for key, entry in state.mods.items():
        if entry.get("mod_version"):
            context.installed_versions[normalize_key(key)] = entry["mod_version"]

    # Anything already on disk can be read directly, which is better than the
    # state file: it reflects what is installed now, not what we last fetched.
    for mod in installed.mods.values():
        folder_key = normalize_key(mod.folder)
        mod_dir = os.path.join(target, mod.folder)
        if not os.path.isdir(mod_dir):
            continue
        info = read_mod_tp2(mod_dir, mod.tp2_file)
        if info and info.version:
            context.installed_versions[folder_key] = info.version
        meta = find_metadata(mod_dir, mod.folder)
        if meta and meta.has_order_hints:
            context.mods_with_own_ini.add(folder_key)
            ruleset.add_metadata_order(mod.folder, meta.before, meta.after)
        forge = os.path.join(mod_dir, "mod-forge.json")
        if os.path.isfile(forge) and os.path.getsize(forge) <= _MAX_TEXT_BYTES:
            # The author's own conflicts and known issues (Infinity Mod Forge's
            # format). A broken file is the author's to fix, not a reason to stop.
            try:
                own = RuleSet.load_file(forge)
            except ConfigError as exc:
                print(f"[warning] {exc}", file=sys.stderr)
            else:
                ruleset.rules.extend(own.rules)
                ruleset.notes.extend(own.notes)
    return context


def _game_language(settings) -> str:
    """--game-language, else the first preferred mod language, else en_US."""
    if settings.game_language:
        return str(settings.game_language)
    return str(settings.language_preference[0]) if settings.language_preference else "en_US"


def _require_plan(settings, from_file: dict | None = None) -> None:
    """
    Flags that act on an install plan are meaningless without one. A value the
    config file gives is not refused: the wizard's project ini holds the game
    folders and languages for every run in the project, a download included
    (ADR-0039), and a BG:EE or BG2:EE project names one folder. The same flag
    typed with another value still is.
    """
    ini = from_file or {}
    given = {name: getattr(settings, name) for name in (
        "resolve_conflicts", "decisions", "emit_installer", "simulate", "bgee_dir",
        "bg2ee_dir", "language_preference")}             # as typed, before parsing

    def typed(name: str) -> bool:
        return bool(given[name]) and ini.get(name) != given[name]
    if settings.language_preference:
        settings.language_preference = parse_preferences(settings.language_preference)
    if bool(settings.bgee_dir) != bool(settings.bg2ee_dir) and \
            (typed("bgee_dir") or typed("bg2ee_dir")):
        raise ConfigError("--bgee-dir and --bg2ee-dir go together: an EET install "
                          "needs both games")
    if settings.plan_order:
        return
    for name in given:
        if typed(name):
            flag = "--" + name.replace("_", "-")
            raise ConfigError(f"{flag} works on an install plan: add "
                              f"--plan-order DIR (and --order-catalogue)")


def _engine_limits(settings) -> list:
    """
    Kits, spell states and spell slots per install: measured in the game
    folder when the log sits in one (beside chitin.key), estimated from
    krion64's counts for what the game does not hold yet.
    """
    krion = os.path.join(settings.order_catalogue, "mods") if settings.order_catalogue else None
    if not settings.weidu_log:
        return []
    records = list(_json_records(krion)) if krion and os.path.isdir(krion) else []
    reports = []
    for spec in settings.weidu_log:
        path, game = split_log_spec(spec)
        parsed = parse_weidu_files([(path, game)])
        chosen = [(tp2_key(c.tp2_file), c.index)
                  for mod in parsed.mods.values() for c in mod.components]
        eeex = any(key == "eeex" for key, _number in chosen)
        folder = os.path.dirname(os.path.abspath(path))
        measured, installed = _measure_game(folder)
        if not records and measured is None:
            continue
        reports.append(limits.engine_limits(
            game or parsed.game or os.path.basename(path), chosen, records, eeex=eeex,
            measured=measured, installed=installed,
            measured_from=folder if measured is not None else None))
    return reports


def _measure_game(folder: str):
    """(Measured, the components its WeiDU.log lists), or (None, ()) if not a game."""
    if not os.path.isfile(os.path.join(folder, "chitin.key")) and \
            not any(e.lower() == "chitin.key" for e in os.listdir(folder)):
        return None, ()

    def text(resource):
        try:
            data = gamedir.read_resource(folder, resource)
        except (OSError, ValueError, struct.error, MemoryError, OverflowError):
            # a damaged key or BIFF: that table is not measured
            return None
        return None if data is None else data.decode("latin-1")
    kitlist, spell_ids = text("kitlist.2da"), text("spell.ids")
    splstate = text("splstate.ids")
    try:
        files = gamedir.spell_files(folder)
    except OSError:
        files = set()
    measured = limits.Measured(
        kits=limits.kits_in_use(kitlist) if kitlist else None,
        spell_slots=(limits.spell_slots_taken(spell_ids, text("add_spell.ids"), files)
                     if spell_ids else None),
        spell_states=limits.spell_states_in_use(splstate) if splstate else None)
    log = next((os.path.join(folder, e) for e in os.listdir(folder)
                if e.lower() == "weidu.log"), None)
    installed = []
    if log is not None:
        try:
            installed = [(tp2_key(c.tp2_file), c.index)
                         for mod in parse_weidu_files([(log, None)]).mods.values()
                         for c in mod.components]
        except (ConfigError, OSError):
            installed = []
    return measured, installed


def _analyse(settings, installed, stream):
    """Rule check, order plan and conflict report, over what is staged now."""
    analysis = _check_rules(settings, installed, stream)
    order_plan = _plan_order(settings, analysis, stream)
    return analysis.findings, order_plan, _conflict_report(settings, analysis, order_plan)


def _run(settings, stream, config=None, on_event=None, cancel=None,
         supplied=None) -> Outcome:
    if settings.list_mods:
        _list_mods(settings, stream)
        return Outcome(exit_code=0)
    if settings.describe_mods:
        _describe_mods(settings, stream)
        return Outcome(exit_code=0)
    _require_plan(settings, config.values if config is not None else {})
    _emit_selection(settings, stream)
    target = os.path.abspath(settings.target)
    if settings.manifest == DEFAULT_MANIFEST and not os.path.exists(DEFAULT_MANIFEST) \
            and settings.catalogue:
        settings.manifest = None        # the default is optional; a named file is not
    if settings.manifest:
        manifest = load_manifest(settings.manifest, allow_http=settings.allow_http)
    elif settings.catalogue:
        # No manifest (the wizard, ADR-0039): every mod is found through the
        # community catalogue - lcc-docs, from the data cache - and must still
        # prove itself by the tp2 its archive contains.
        manifest = Manifest()
    else:
        raise ConfigError("no download source: no manifest, and no lcc-docs catalogue "
                          "in the data cache (run with --update-data, or give -m)")

    if settings.weidu_log:
        installed = parse_weidu_files([split_log_spec(spec) for spec in settings.weidu_log])
    else:
        installed = ParsedLog()
        if not settings.all_manifest_entries:
            raise ConfigError(
                "no --weidu-log given. Pass at least one WeiDU.log to define which "
                "mods are wanted, or --all-manifest-entries to fetch the whole "
                "catalogue.")

    plan = build_plan(installed, manifest, aliases=load_aliases(settings.aliases),
                      include_manifest_only=settings.all_manifest_entries or not settings.weidu_log,
                      accept_suggestions=settings.accept_suggestions)

    if settings.only:
        wanted = {name.lower() for name in settings.only}
        plan.items = [i for i in plan.items if i.folder.lower() in wanted]
        plan.unresolved = [i for i in plan.unresolved if i.folder.lower() in wanted]
    supplied = {folder.lower(): path for folder, path in (supplied or {}).items()}
    if supplied:
        # a mod no source names is installed from the file the player chose
        plan.items += [i for i in plan.unresolved if i.folder.lower() in supplied]
        plan.unresolved = [i for i in plan.unresolved if i.folder.lower() not in supplied]

    if settings.check_only:
        findings, order_plan, conflict_report = _analyse(settings, installed, stream)
        report = RunReport(findings=findings)
        if not settings.quiet:
            render_summary(report, target, stream=stream)
            if order_plan is not None:
                render_plan_summary(order_plan, settings.plan_order, stream)
            if conflict_report is not None:
                render_conflict_report(conflict_report, stream,
                                       show_notes=settings.show_advisories)
                if settings.conflict_report:
                    print(f"  full report written to {settings.conflict_report}",
                          file=stream)
            _render_updates(settings, stream)
        if settings.json_report:
            report.write_json(settings.json_report)
        refused = bool(order_plan is not None and (
            (order_plan.simulation and order_plan.simulation.refused)
            or (order_plan.game_report and order_plan.game_report.problems)))
        return Outcome(1 if report.blocking_findings or refused else 0,
                       report, order_plan, conflict_report)

    credential = resolve_credential(token_file=settings.token_file,
                                    use_gh=not settings.no_gh_cli,
                                    use_git_credential=not settings.no_git_credential,
                                    oauth_client_id=settings.oauth_client_id)
    client = HttpClient(token=credential.token, allow_http=settings.allow_http,
                        timeout=settings.timeout, max_bytes=settings.max_bytes,
                        retries=settings.retries)
    client.etags = ETagCache(_etag_dir(settings))

    for warning in (config.warnings if config else []):
        print(f"[warning] {warning}", file=sys.stderr)

    if not settings.quiet:
        print(f"iemod-fetch {__version__}", file=stream)
        if config is not None and config.path:
            print(f"  config      : {config.path} ({len(config.values)} setting(s))",
                  file=stream)
        print(f"  catalogue   : {settings.manifest or '(none: the community catalogue)'} "
              f"({len(manifest.sources)} entries)", file=stream)
        games = sorted({m.game for m in installed.mods.values() if m.game})
        print(f"  weidu logs  : {', '.join(settings.weidu_log) or '(none)'} "
              f"({len(installed.mods)} mods, {installed.component_count} components"
              f"{'; game: ' + ', '.join(games) if games else ''})", file=stream)
        print(f"  target      : {target}", file=stream)
        print(f"  credential  : {credential.describe()}", file=stream)
        print(f"  to process  : {len(plan.items)} resolved, "
              f"{len(plan.unresolved)} unresolved", file=stream)
        if settings.dry_run:
            print("  MODE        : dry run, nothing will be written", file=stream)
        print(file=stream)

    os.makedirs(target, exist_ok=True)
    options = Options(target_dir=target, workers=settings.workers, dry_run=settings.dry_run,
                      force=settings.force, allow_exe=settings.allow_exe,
                      accept_offsite=settings.accept_offsite, refresh=settings.refresh,
                      discovery_attempts=settings.discovery_attempts,
                      take_newer=frozenset(n.lower() for n in settings.take_newer),
                      supplied=supplied)

    catalogue = CatalogueSet.load(settings.catalogue)
    if catalogue and not settings.quiet:
        print(f"  catalogues  : {len(settings.catalogue)} file(s), {len(catalogue)} mods",
              file=stream)

    org_index = None
    if not settings.no_discovery:
        owners = load_trusted_owners(settings.trusted_owners, manifest=manifest,
                                     extra=settings.trusted_owner)
        org_index = OwnerIndex(
            client=client, owners=owners,
            cache_path=settings.owner_cache or os.path.join(target, ".owner-index.json"))
        if not settings.quiet:
            print(f"  discovery   : enabled over {len(owners)} trusted owner(s)",
                  file=stream)
    with _event_sink(settings.events, stream, on_event) as sink:
        runner = Runner(client, options, stream=None if settings.quiet else stream,
                        org_index=org_index, catalogue=catalogue or None,
                        on_event=sink, cancel=cancel,
                        releases=_github_releases(settings))
        report = runner.run(plan)
    # Checked and planned AFTER the fetch, so the mods' own tp2s are read from
    # what this run just staged: one run takes a selection from nothing to a
    # checked plan.
    report.findings, order_plan, conflict_report = _analyse(settings, installed, stream)

    if not settings.quiet:
        render_summary(report, target, stream=stream)
        if order_plan is not None:
            render_plan_summary(order_plan, settings.plan_order, stream)
        if conflict_report is not None:
            render_conflict_report(conflict_report, stream,
                                   show_notes=settings.show_advisories)
            if settings.conflict_report:
                print(f"  full report written to {settings.conflict_report}",
                      file=stream)
        _render_updates(settings, stream)
    if settings.emit_pinned_manifest:
        payload = build_pinned_manifest(manifest, report.records,
                                        state=runner.state.mods)
        write_pinned_manifest(settings.emit_pinned_manifest, payload)
        if not settings.quiet:
            print(f"\nPinned manifest written to {settings.emit_pinned_manifest} "
                  f"({payload['pinned_entries']} of {len(payload['mods'])} entries "
                  f"carry a sha256)", file=stream)
            if settings.dry_run:
                print("  note: --dry-run downloads nothing, so only release_tag/asset "
                      "could be pinned. Re-run without --dry-run to pin sha256.",
                      file=stream)
    if settings.json_report:
        report.write_json(settings.json_report)
        if not settings.quiet:
            print(f"\nJSON report written to {settings.json_report}", file=stream)
    return Outcome(report.exit_code(allow_manual=settings.allow_manual),
                   report, order_plan, conflict_report)
