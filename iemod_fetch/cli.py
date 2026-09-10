"""Command line interface."""
import argparse
from typing import List, Optional, Sequence
from dataclasses import dataclass, field
import os
import sys

from . import __version__
from .auth import resolve_credential
from .catalogues import CatalogueSet
from .config import LIST_KEYS, load_config
from .errors import ConfigError, ModFetchError
from .manifest import load_manifest
from .net import DEFAULT_MAX_BYTES, HttpClient
from .orgindex import OwnerIndex, load_trusted_owners
from .pinning import build_pinned_manifest, write_pinned_manifest
from .moddb import ModDatabase
from .naming import normalize_key
from .modmeta import find_metadata
from .plan import build_plan, load_aliases
from .install import State
from .tp2 import read_mod_tp2
from .conflicts import build_conflict_report, render_conflict_report
from .ordering import (EET_LOG, PRE_EET_LOG, OrderIndex, plan_order,
                       render_plan_summary)
from .rules import Context, Install, RuleSet, check_all, load_suppressions
from .report import RunReport, render_summary
from .runner import Options, Runner
from .weidu import ParsedLog, parse_weidu_files, split_log_spec


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
    src.add_argument("--suppress", metavar="PATH",
                     help="JSON list of rules you have verified no longer apply")
    src.add_argument("--all-manifest-entries", action="store_true",
                     help="also fetch catalogue entries no WeiDU log references")
    src.add_argument("--only", action="append", default=None, metavar="FOLDER",
                     help="restrict the run to these mod folders; repeatable")

    out = parser.add_argument_group("output")
    out.add_argument("-t", "--target", default="./Mods", help="install root (default: %(default)s)")
    out.add_argument("--json-report", metavar="PATH", help="write a machine-readable report")
    out.add_argument("--emit-pinned-manifest", metavar="PATH",
                     help="write a copy of the catalogue with release_tag, asset "
                          "and sha256 filled in from this run - commit it to make "
                          "future runs reproducible (combine with --refresh to pin "
                          "mods already installed)")
    out.add_argument("--plan-order", metavar="DIR",
                     help="write a rule-compliant WeiDU.log + WeiDU-BGEE.log pair "
                          "into DIR: the components you already have, sorted to "
                          "satisfy --rules and --order-catalogue. This is an "
                          "install PLAN for a fresh install, not a repair of a "
                          "game already installed")
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
        return _run(args, stream, config)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except ModFetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


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
    ruleset: Optional[RuleSet] = None
    context: Optional[Context] = None
    installs: Sequence[Install] = ()
    findings: List[dict] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ruleset is not None


def _check_rules(args, installed, stream) -> RuleAnalysis:
    """
    Check each WeiDU log against the rule set, separately.

    One log is one game install: a mod in the BGEE log neither conflicts with
    nor orders against a mod in the EET log, so the logs are never merged for
    this.
    """
    if not args.rules or not args.weidu_log:
        return RuleAnalysis()
    ruleset = RuleSet.load(args.rules)
    context = _rule_context(args, installed, ruleset, stream)
    installs = []
    for spec in args.weidu_log:
        path, game = split_log_spec(spec)
        installs.append(Install.from_log(parse_weidu_files([(path, game)]),
                                         label=os.path.basename(path)))
    # `rule` is the Rule object the finding drilled down from - useful in
    # process, not serialisable, and the conflict report carries it properly.
    findings = [{k: v for k, v in vars(f).items() if k != "rule"}
                for f in check_all(installs, ruleset, context)]
    if not args.quiet:
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
                        findings=findings)


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
    if not eet_logs and len(roles) > 1:
        raise ConfigError(
            "no log installs the EET core, so which one is the merged game is a "
            "guess. Say so explicitly: -w WeiDU.log:EET")
    return roles


def _plan_order(args, analysis: "RuleAnalysis", stream):
    """Build the rule-compliant install order, if asked for."""
    if not getattr(args, "plan_order", None):
        return None
    if not args.weidu_log:
        raise ConfigError("--plan-order needs at least one --weidu-log to order")
    if not args.order_catalogue:
        raise ConfigError(
            "--plan-order needs --order-catalogue PATH: a krion64 data directory "
            "(categories.json + mods/*.json). Without it there is no reference "
            "order to sort towards, and the tool will not invent one")

    index = OrderIndex.load(args.order_catalogue)
    # Reuse the ruleset the checker just built: it carries the per-mod ordering
    # metadata read from installed .iemod/.ini files on top of --rules. Planning
    # against a thinner ruleset than the check uses would emit a plan the very
    # next check rejects.
    ruleset, context = analysis.ruleset, analysis.context
    if ruleset is None:
        ruleset = RuleSet.load(args.rules) if args.rules else RuleSet()
    specs = _log_roles(args.weidu_log)
    plan = plan_order(specs, index, ruleset, context,
                      include_optional=args.include_optional,
                      reassign_phase=args.reassign_phase)
    written = plan.write(args.plan_order)
    if not args.quiet:
        print(f"  order plan  : {index.origin} "
              f"({len(index)} mods, {len(index.categories)} categories); "
              f"{plan.edges} ordering constraint(s)", file=stream)
        for path in written:
            print(f"                wrote {path}", file=stream)
    return plan


def _conflict_report(args, analysis: "RuleAnalysis", plan):
    """
    The component-level view: what actually fights what, and the smallest fix.

    Ordering answers "in what sequence"; this answers "and what still clashes
    once the sequence is right". Findings the plan already resolves are marked
    as such instead of being reported twice.
    """
    if analysis.ruleset is None or not analysis.installs:
        return None
    report = build_conflict_report(analysis.installs, analysis.ruleset,
                                   analysis.context, plan)
    if args.conflict_report:
        report.write_json(args.conflict_report)
    return report


def _rule_context(args, installed, ruleset, stream):
    """
    Gather what is needed to judge whether a rule is still current: the version
    of each installed mod, the versions the rules were built against, mods that
    ship their own ordering metadata, and any verified suppressions.
    """
    target = os.path.abspath(args.target)
    context = Context(suppressions=load_suppressions(args.suppress),
                      include_optional=args.include_optional)

    if args.mod_db:
        context.baseline = ModDatabase.load(args.mod_db)
        if not args.quiet:
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
    return context


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


def _run(args, stream, config=None) -> int:
    target = os.path.abspath(args.target)
    manifest = load_manifest(args.manifest, allow_http=args.allow_http)

    if args.weidu_log:
        installed = parse_weidu_files([split_log_spec(spec) for spec in args.weidu_log])
    else:
        installed = ParsedLog()
        if not args.all_manifest_entries:
            raise ConfigError(
                "no --weidu-log given. Pass at least one WeiDU.log to define which "
                "mods are wanted, or --all-manifest-entries to fetch the whole "
                "catalogue.")

    plan = build_plan(installed, manifest, aliases=load_aliases(args.aliases),
                      include_manifest_only=args.all_manifest_entries or not args.weidu_log,
                      accept_suggestions=args.accept_suggestions)

    if args.only:
        wanted = {name.lower() for name in args.only}
        plan.items = [i for i in plan.items if i.folder.lower() in wanted]
        plan.unresolved = [i for i in plan.unresolved if i.folder.lower() in wanted]

    analysis = _check_rules(args, installed, stream)
    findings = analysis.findings
    order_plan = _plan_order(args, analysis, stream)
    conflict_report = _conflict_report(args, analysis, order_plan)

    if args.check_only:
        report = RunReport(findings=findings)
        if not args.quiet:
            render_summary(report, target, stream=stream)
            if order_plan is not None:
                render_plan_summary(order_plan, args.plan_order, stream)
            if conflict_report is not None:
                render_conflict_report(conflict_report, stream,
                                       show_notes=args.show_advisories)
                if args.conflict_report:
                    print(f"  full report written to {args.conflict_report}",
                          file=stream)
        if args.json_report:
            report.write_json(args.json_report)
        return 1 if report.blocking_findings else 0

    credential = resolve_credential(token_file=args.token_file,
                                    use_gh=not args.no_gh_cli,
                                    use_git_credential=not args.no_git_credential,
                                    oauth_client_id=args.oauth_client_id)
    client = HttpClient(token=credential.token, allow_http=args.allow_http,
                        timeout=args.timeout, max_bytes=args.max_bytes,
                        retries=args.retries)

    for warning in (config.warnings if config else []):
        print(f"[warning] {warning}", file=sys.stderr)

    if not args.quiet:
        print(f"iemod-fetch {__version__}", file=stream)
        if config is not None and config.path:
            print(f"  config      : {config.path} ({len(config.values)} setting(s))",
                  file=stream)
        print(f"  catalogue   : {args.manifest} ({len(manifest.sources)} entries)", file=stream)
        games = sorted({m.game for m in installed.mods.values() if m.game})
        print(f"  weidu logs  : {', '.join(args.weidu_log) or '(none)'} "
              f"({len(installed.mods)} mods, {installed.component_count} components"
              f"{'; game: ' + ', '.join(games) if games else ''})", file=stream)
        print(f"  target      : {target}", file=stream)
        print(f"  credential  : {credential.describe()}", file=stream)
        print(f"  to process  : {len(plan.items)} resolved, "
              f"{len(plan.unresolved)} unresolved", file=stream)
        if args.dry_run:
            print("  MODE        : dry run, nothing will be written", file=stream)
        print(file=stream)

    os.makedirs(target, exist_ok=True)
    options = Options(target_dir=target, workers=args.workers, dry_run=args.dry_run,
                      force=args.force, allow_exe=args.allow_exe,
                      accept_offsite=args.accept_offsite, refresh=args.refresh,
                      discovery_attempts=args.discovery_attempts)

    catalogue = CatalogueSet.load(args.catalogue)
    if catalogue and not args.quiet:
        print(f"  catalogues  : {len(args.catalogue)} file(s), {len(catalogue)} mods",
              file=stream)

    org_index = None
    if not args.no_discovery:
        owners = load_trusted_owners(args.trusted_owners, manifest=manifest,
                                     extra=args.trusted_owner)
        org_index = OwnerIndex(
            client=client, owners=owners,
            cache_path=args.owner_cache or os.path.join(target, ".owner-index.json"))
        if not args.quiet:
            print(f"  discovery   : enabled over {len(owners)} trusted owner(s)",
                  file=stream)
    runner = Runner(client, options, stream=None if args.quiet else stream,
                    org_index=org_index, catalogue=catalogue or None)
    report = runner.run(plan)
    report.findings = findings

    if not args.quiet:
        render_summary(report, target, stream=stream)
        if order_plan is not None:
            render_plan_summary(order_plan, args.plan_order, stream)
        if conflict_report is not None:
            render_conflict_report(conflict_report, stream,
                                   show_notes=args.show_advisories)
            if args.conflict_report:
                print(f"  full report written to {args.conflict_report}",
                      file=stream)
    if args.emit_pinned_manifest:
        payload = build_pinned_manifest(manifest, report.records,
                                        state=runner.state.mods)
        write_pinned_manifest(args.emit_pinned_manifest, payload)
        if not args.quiet:
            print(f"\nPinned manifest written to {args.emit_pinned_manifest} "
                  f"({payload['pinned_entries']} of {len(payload['mods'])} entries "
                  f"carry a sha256)", file=stream)
            if args.dry_run:
                print("  note: --dry-run downloads nothing, so only release_tag/asset "
                      "could be pinned. Re-run without --dry-run to pin sha256.",
                      file=stream)
    if args.json_report:
        report.write_json(args.json_report)
        if not args.quiet:
            print(f"\nJSON report written to {args.json_report}", file=stream)
    return report.exit_code(allow_manual=args.allow_manual)
