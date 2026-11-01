"""
Command line interface: flags in, `api.run`, exit code out.

Nothing is decided here. The parser turns flags into `api.Settings`; what the
tool does with them is `api.run`, the same function a GUI calls (ADR-0029).
"""
import argparse
import sys

from . import __version__, api
from .config import LIST_KEYS, load_config
from .errors import ConfigError, ModFetchError
from .net import DEFAULT_MAX_BYTES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iemod-fetch",
        description="Download and stage Infinity Engine mods for WeiDU / Project "
                    "Infinity, driven by a WeiDU.log and a mod_downloads.json catalogue.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="exit codes: 0 success, 1 failures or unresolved mods, 2 bad configuration")
    parser.add_argument("--version", action="version", version=f"iemod-fetch {__version__}")
    parser.add_argument("--config", metavar="PATH",
                        help="INI file of defaults (default: iemod-fetch.ini in the "
                             "working directory, the target directory, %%APPDATA%% or "
                             "~/.config). An explicit flag always overrides it.")

    src = parser.add_argument_group("inputs")
    src.add_argument("-m", "--manifest", default="mod_downloads.json",
                     help="source catalogue (default: %(default)s)")
    src.add_argument("-w", "--weidu-log", action="append", default=None, metavar="PATH[:GAME]",
                     help="WeiDU.log defining desired state; repeatable. Append "
                          ":GAME (EET, BGEE, BG2EE, SoD...) to say which install "
                          "the log describes - EET is detected automatically - so "
                          "catalogue compatibility warnings are judged per game")
    src.add_argument("--selection", metavar="PATH",
                     help="selection.json (schema 1): the mods, components and "
                          "languages chosen, without a WeiDU.log - what a UI saves. "
                          "Used instead of --weidu-log, never with it")
    src.add_argument("--bio-code", metavar="PATH",
                     help="a file holding a BIO-MODLIST-V1 share code (Born2BSalty's "
                          "Infinity Orchestrator): its WeiDU logs are what is wanted, "
                          "instead of -w or --selection")
    src.add_argument("--pi-list", metavar="PATH:GAME",
                     help="a Project Infinity / Infinity Mod Forge list "
                          "(LABEL;description or folder:number;description per line) "
                          "as what is wanted. LABELs are read from the staged tp2s "
                          "first, krion64's records second; an unknown one is an error")
    src.add_argument("--aliases", metavar="PATH",
                     help="JSON map {weidu_folder: manifest_tp2} for entries whose "
                          "names differ between the log and the catalogue")
    src.add_argument("-c", "--catalogue", action="append", default=None, metavar="PATH",
                     help="supplementary mod database consulted when the manifest "
                          "cannot resolve a mod, e.g. db/mods.json from "
                          "https://github.com/RiwsPy/lcc-docs (MIT). Repeatable; "
                          "also surfaces the catalogue's obsolete/beta advisories")
    src.add_argument("--rules", action="append", default=None, metavar="PATH",
                     help="install-order / incompatibility / dependency rules: a "
                          "JSON file or a directory of them, in the "
                          "BigWorldSetup-Next-Generation shape "
                          "(data/rules/*.json). Repeatable")
    src.add_argument("--mod-db", metavar="PATH",
                     help="per-mod database the rules were built from "
                          "(BigWorldSetup-Next-Generation data/mods). Supplies "
                          "sha256 + direct URLs, and the version each rule was "
                          "written against, so stale rules can be flagged")
    src.add_argument("--order-catalogue", metavar="PATH",
                     help="krion64 data directory (categories.json + mods/*.json) "
                          "giving each mod's install-order category and position; "
                          "required by --plan-order")
    src.add_argument("--eet-sequence", metavar="PATH",
                     help="BigWorldSetup-NG data/games/eet.json: its bg2ee "
                          "sequence says which mods may go on BG2:EE before the "
                          "EET core, and places in --plan-order a mod krion64 "
                          "does not (default: the data cache; without it, EET's "
                          "readme rule - only the EE Fixpack - and no such place)")
    src.add_argument("--releases", metavar="PATH",
                     help="krion64's data/version_cache.json: each mod repository's "
                          "latest GitHub release; with its sibling mods/, the "
                          "versions krion64 records. Says which installed mods have "
                          "a newer version. Default: the data cache")
    src.add_argument("--sorting-order", metavar="PATH",
                     help="a Project Infinity 'Sorting Order' file (one 'tp2 *' or "
                          "'tp2 N N' per line): what it names is installed in its "
                          "order, as order rules on top of --rules (ADR-0037)")
    src.add_argument("--fetch-metadata", action="store_true",
                     help="fetch the author's own metadata ini (Before/After) of "
                          "every planned mod not staged yet, from the repository "
                          "the catalogue names, into the data cache (ADR-0037). "
                          "Fetched ones are used by every later run")
    src.add_argument("--suppress", metavar="PATH",
                     help="JSON list of rules you have verified no longer apply")
    src.add_argument("--all-manifest-entries", action="store_true",
                     help="also fetch catalogue entries no WeiDU log references")
    src.add_argument("--only", action="append", default=None, metavar="FOLDER",
                     help="restrict the run to these mod folders; repeatable")
    src.add_argument("--take-newer", action="append", default=None, metavar="FOLDER",
                     help="install the newer GitHub release a run offered for this "
                          "mod, over the copy on disk (kept in .backup/); 'all' "
                          "takes every one offered. Repeatable")

    out = parser.add_argument_group("output")
    out.add_argument("--decisions", metavar="PATH",
                     help="decisions.json: your answer to each conflict the rules "
                          "do not decide - an option id from --conflict-report, or "
                          "accept with a reason. Applied to the plan before "
                          "--resolve-conflicts, then re-checked; needs --plan-order")
    out.add_argument("-t", "--target", default="./Mods", help="install root (default: %(default)s)")
    out.add_argument("--json-report", metavar="PATH", help="write a machine-readable report")
    out.add_argument("--emit-pinned-manifest", metavar="PATH",
                     help="write a copy of the catalogue with release_tag, asset "
                          "and sha256 filled in from this run - commit it to make "
                          "future runs reproducible (combine with --refresh to pin "
                          "mods already installed)")
    out.add_argument("--events", metavar="PATH",
                     help="write progress as JSON lines (schema 1: run_started, "
                          "mod_started, download_progress, mod_extracting, "
                          "mod_finished, "
                          "run_finished) for a UI or a log collector; '-' for "
                          "stdout, best with -q")
    out.add_argument("--list-mods", metavar="PATH",
                     help="write every mod the manifest, --catalogue and --mod-db "
                          "know about as JSON (schema 1; '-' for stdout), then "
                          "stop. Needs no WeiDU.log and downloads nothing")
    out.add_argument("--describe-mods", metavar="PATH",
                     help="write the components of every mod staged under --target, "
                          "named as WeiDU names them (tp2 + .tra, in the first "
                          "--language-preference the mod offers), as JSON (schema 1; "
                          "'-' for stdout), then stop. Runs no WeiDU")
    out.add_argument("--emit-bio-code", metavar="PATH",
                     help="write what is wanted (-w, --selection or --bio-code) as a "
                          "BIO-MODLIST-V1 share code ('-' for stdout); an imported "
                          "code keeps its name, sources and configs")
    out.add_argument("--emit-selection", metavar="PATH",
                     help="write the --weidu-log input as a selection.json; with "
                          "--check-only nothing else is fetched")
    out.add_argument("--plan-order", metavar="DIR",
                     help="write a rule-compliant WeiDU.log + WeiDU-BGEE.log pair "
                          "into DIR: the components you already have, sorted to "
                          "satisfy --rules and --order-catalogue. This is an "
                          "install PLAN for a fresh install, not a repair of a "
                          "game already installed")
    out.add_argument("--resolve-conflicts", action="store_true",
                     help="with --plan-order: remove from the PLAN the components "
                          "an error-graded, non-speculative incompatibility rule "
                          "pins - the remedy the conflict report names. Anything "
                          "the rules do not decide is listed for you. Your own "
                          "logs are never edited (ADR-0021)")
    out.add_argument("--simulate", action="store_true",
                     help="with --plan-order: walk the plan the way WeiDU will run "
                          "it - BGEE, then BG2EE becoming EET - checking every "
                          "staged mod's own tp2 constraints and EET's merge check; "
                          "reports what WeiDU would refuse (ADR-0025)")
    out.add_argument("--bgee-dir", metavar="DIR",
                     help="with --plan-order, for EET: the BG:EE game the plan's "
                          "WeiDU-BGEE.log installs onto. Verified with WeiDU's own "
                          "GAME_IS markers and EET's requirements (SoD present or "
                          "DlcMerger planned) - never written to (ADR-0026)")
    out.add_argument("--bg2ee-dir", metavar="DIR",
                     help="with --plan-order, for EET: the clean BG2:EE game that "
                          "becomes EET; verified the same way")
    out.add_argument("--emit-installer", action="store_true",
                     help="with --plan-order: also write install scripts (sh and "
                          "Windows cmd) into the plan directory that hand the plan "
                          "to mod_installer + WeiDU - for EET, both games in one "
                          "run. Written for you to run; never run by iemod-fetch "
                          "(ADR-0022)")
    out.add_argument("--language-preference", metavar="LANGS",
                     help="with --plan-order: install every mod in the first of "
                          "these languages it offers, e.g. it_IT,en_US (or "
                          "italian,english). Read from each staged mod's tp2; a "
                          "mod offering none keeps its logged language (ADR-0024)")
    out.add_argument("--game-language", default=None, metavar="CODE",
                     help="game language the installer scripts pass on (default: "
                          "the first --language-preference, else en_US)")
    out.add_argument("--conflict-report", metavar="PATH",
                     help="write the full component-level conflict report as "
                          "JSON: which component of which mod fights which "
                          "component of which other mod, with provenance")
    out.add_argument("--show-advisories", action="store_true",
                     help="also show unverified advisory findings (krion64's "
                          "`advisories` channel). Off by default: they are "
                          "observations nobody has traced, and they outnumber "
                          "the verified findings")
    out.add_argument("-q", "--quiet", action="store_true")

    bak = parser.add_argument_group(
        "game folder backup (ADR-0042; each of these runs alone, then stops)")
    bak.add_argument("--backup", metavar="GAME_DIR",
                     help="back the game folder up before installing: override/, the "
                          "lang/*/dialog*.tlk and the files at its root are copied with "
                          "their sha256, everything else is listed")
    bak.add_argument("--backup-to", metavar="DIR",
                     help="where --backup writes (default: GAME_DIR-iemod-backups beside "
                          "the game folder)")
    bak.add_argument("--verify-backup", metavar="BACKUP",
                     help="check every copy in a backup against its sha256")
    bak.add_argument("--restore-backup", metavar="BACKUP",
                     help="show what restoring the backup would do; with --apply, do it. "
                          "Nothing is deleted: what is in the way is moved into the "
                          "backup's displaced-<time>/ folder")
    bak.add_argument("--restore-to", metavar="GAME_DIR",
                     help="the game folder to restore (default: the one backed up)")
    bak.add_argument("--apply", action="store_true",
                     help="with --restore-backup: restore, not only show the plan")

    beh = parser.add_argument_group("behaviour")
    beh.add_argument("--include-optional", action="store_true",
                     help="also report optional integrations a rule set knows "
                          "about (soft dependencies), not just requirements")
    beh.add_argument("--reassign-phase", action="store_true",
                     help="with --plan-order, also move a mod into the other log "
                          "when the catalogue says it belongs to the other install "
                          "phase. Off by default: that changes which game the mod "
                          "is installed onto, not just when")
    beh.add_argument("--check-only", action="store_true",
                     help="only check the WeiDU log(s) against --rules and report; "
                          "resolve nothing, download nothing, touch no network")
    beh.add_argument("-n", "--dry-run", action="store_true",
                     help="resolve and report without downloading anything")
    beh.add_argument("-f", "--force", action="store_true",
                     help="replace an existing mod directory (the old one is moved "
                          "to .backup/, never deleted)")
    beh.add_argument("--refresh", action="store_true",
                     help="re-download even mods already verified on disk")
    beh.add_argument("-j", "--workers", type=int, default=4, metavar="N")
    beh.add_argument("--allow-manual", action="store_true",
                     help="exit 0 even when some mods need a manual download")
    beh.add_argument("--accept-suggestions", action="store_true",
                     help="auto-apply the best fuzzy catalogue match for unmatched "
                          "WeiDU folders (NOT recommended: review them and write "
                          "an --aliases file instead)")

    sec = parser.add_argument_group("security policy")
    sec.add_argument("--allow-http", action="store_true",
                     help="permit cleartext http:// downloads (3 entries in the "
                          "supplied manifest need this)")
    sec.add_argument("--allow-exe", action="store_true",
                     help="unpack self-extracting .exe archives (never executed)")
    disc = parser.add_argument_group("trusted-owner discovery (ADR-0008)")
    disc.add_argument("--no-discovery", action="store_true",
                      help="do not look for unresolved mods in your trusted owners")
    disc.add_argument("--trusted-owners", metavar="PATH",
                      help="JSON list of GitHub owners to search (default: the "
                           "shipped modding houses plus every owner your manifest "
                           "already uses)")
    disc.add_argument("--trusted-owner", action="append", default=None, metavar="OWNER",
                      help="add one owner to the allowlist; repeatable")
    disc.add_argument("--discovery-attempts", type=int, default=1, metavar="N",
                      help="how many candidates to actually download and verify "
                           "(default: %(default)s; the rest are only reported)")
    disc.add_argument("--owner-cache", metavar="PATH",
                      help="where to cache owner repository listings "
                           "(default: <target>/.owner-index.json)")

    sec.add_argument("--accept-offsite", action="store_true",
                     help="follow download links that leave the mod's own site")
    sec.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES, metavar="N",
                     help="per-download ceiling (default: %(default)s)")
    sec.add_argument("--timeout", type=int, default=45, metavar="SECONDS")
    sec.add_argument("--retries", type=int, default=3, metavar="N")

    data = parser.add_argument_group(
        "community data (lcc-docs, BWS-NG, krion64; ADR-0032)",
        "Kept in a cache and refreshed automatically when a run starts, at most "
        "once per --data-max-age hours; used for --catalogue, --rules, --mod-db "
        "and --order-catalogue whenever those are not given")
    data.add_argument("--update-data", action="store_true",
                      help="refresh the cached data now, whatever its age, and stop")
    data.add_argument("--no-update-data", action="store_true",
                      help="do not contact GitHub for the data; use the cache as it is "
                           "(also: IEMOD_NO_UPDATE_DATA=1)")
    data.add_argument("--data-dir", metavar="DIR",
                      help="where the cache lives (default: $IEMOD_DATA_DIR, else the "
                           "per-user cache directory, e.g. %%LOCALAPPDATA%%\\iemod-fetch\\data "
                           "or ~/.cache/iemod-fetch/data)")
    data.add_argument("--data-max-age", type=int, default=24, metavar="HOURS",
                      help="refresh when the cache was last checked longer ago than "
                           "this (default: %(default)s)")
    data.add_argument("--no-default-data", action="store_true",
                      help="do not use the cached data in place of flags not given")

    auth = parser.add_argument_group("github credential (optional; raises rate limits)")
    auth.add_argument("--token-file", metavar="PATH",
                      help="read the token from a file (preferred over env vars)")
    auth.add_argument("--no-gh-cli", action="store_true",
                      help="do not consult `gh auth token`")
    auth.add_argument("--no-git-credential", action="store_true",
                      help="do not consult git's credential helper (Git Credential "
                           "Manager on Windows already holds a GitHub token if you "
                           "have pushed over HTTPS)")
    auth.add_argument("--oauth-client-id", metavar="ID",
                      help="client id of an OAuth app YOU own, to run the device flow")
    return parser


def main(argv=None, stream=sys.stdout) -> int:
    parser = build_parser()
    try:
        args, config = _parse_with_config(parser, argv)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    try:
        return api.run(api.Settings.from_namespace(args), stream, config).exit_code
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except ModFetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


def _parse_with_config(parser, argv):
    """
    Parse twice: once to discover --config/--target, then again with the file's
    values installed as defaults. An explicit flag therefore always wins, and
    every default still has exactly one definition (the parser).
    """
    preview, _unknown = parser.parse_known_args(argv)
    config = load_config(preview.config, getattr(preview, "target", None))

    scalars = {k: v for k, v in config.values.items() if k not in LIST_KEYS}
    if scalars:
        parser.set_defaults(**scalars)
    args = parser.parse_args(argv)

    # repeatable options: the CLI replaces the file's list rather than adding to it
    for key in LIST_KEYS:
        if getattr(args, key, None) is None:
            setattr(args, key, list(config.values.get(key) or []))
    return args, config
