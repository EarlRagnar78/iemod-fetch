"""Per-mod pipeline and concurrent orchestration."""
import os
import shutil
import tempfile
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from dataclasses import replace as _replace

from .contract import SCHEMA_VERSION
from .archives import Kind, detect_kind
from .errors import (Cancelled, ChecksumMismatch, InstallConflict, ModFetchError,
                     NotAnArchive, NotThisMod, TooLarge, Unresolved, VerificationFailed)
from .install import State, install_from_archive, verify_mod_dir
from .manifest import ModSource
from .naming import archive_filename, normalize_key
from .net import DownloadResult, sha256_file
from .plan import Plan, WorkItem
from .report import Record, RunReport, Status, line_for
from .resolvers import (Candidate, GitHubResolver, LandingPageResolver, Resolution,
                        repo_from_url)
from .urls import is_forum_post
from .versions import newer_release




# A copy from GitHub, whatever the URL it came by: a release asset, or the
# source snapshot GitHub's API serves (api.github.com/repos/O/R/zipball/...,
# codeload.github.com). Measured on 2026-10-23: EET's snapshot was offered its
# own release (v14.1, whose tp2 still says v14.0) because the API's URL did
# not read as GitHub.
_GITHUB_ORIGINS = frozenset({"release-asset", "source-snapshot"})
_GITHUB_HOSTS = frozenset({"github.com", "www.github.com", "api.github.com",
                           "codeload.github.com", "objects.githubusercontent.com",
                           "release-assets.githubusercontent.com"})


def _from_github(url, origin) -> bool:
    if origin in _GITHUB_ORIGINS:
        return True
    return (urllib.parse.urlsplit(url or "").hostname or "").lower() in _GITHUB_HOSTS


def _pinned(source) -> str:
    """What pins a source to one file, if anything: a sha256, a tag, an asset."""
    return ", ".join(f"{name} {value}" for name, value in (
        ("sha256", source.sha256), ("release_tag", source.release_tag),
        ("asset", source.asset)) if value)


def _unpinned(source, repo):
    """The same source, as a GitHub repository's latest release."""
    return _replace(source, url=None, github=repo, release_tag=None, asset=None,
                    sha256=None)


@dataclass
class Options:
    target_dir: str
    workers: int = 4
    dry_run: bool = False
    force: bool = False
    allow_exe: bool = False
    accept_offsite: bool = False
    refresh: bool = False          # re-download even if verified on disk
    discovery_attempts: int = 1    # trusted-owner candidates to actually try
    # folders (lowercased) whose newer GitHub release replaces the copy on
    # disk; "all" takes every one a run offered (ADR-0039 amendment)
    take_newer: frozenset = frozenset()
    # folders (lowercased) the player supplied a saved file for, from a page
    # this tool cannot download from (GUI-AUDIT item 68, ADR-0052)
    supplied: dict = field(default_factory=dict)


class Runner:
    """
    Fetch every mod of a plan, several at a time.

    `on_event`, when given, receives a dict for each thing that happens -
    run_started, mod_started, download_progress, mod_finished, run_finished -
    each with `schema_version` and `event` (ADR-0030). It is called from worker
    threads, one call at a time. `cancel` is a threading.Event: once set, no
    new mod starts, a download in flight stops at its next chunk, and the
    report says `cancelled`. Ctrl-C sets it too.
    """

    def __init__(self, client, options: Options, stream=None, org_index=None,
                 catalogue=None, on_event=None, cancel=None, releases=None):
        self.client = client
        self.options = options
        # mod key -> (owner/repo, the latest release krion64's daily scan saw)
        self.releases = releases or {}
        self.org_index = org_index
        self.catalogue = catalogue
        self.github = GitHubResolver(client, allow_exe=options.allow_exe)
        self.landing = LandingPageResolver(client, accept_offsite=options.accept_offsite,
                                           allow_exe=options.allow_exe)
        self.state = State.load(options.target_dir)
        self._lock = threading.Lock()
        self._stream = stream
        self._on_event = on_event
        self.cancel = cancel if cancel is not None else threading.Event()
        # a wait between the client's retries ends when the run is cancelled
        if getattr(client, "cancel", False) is None:
            client.cancel = self.cancel

    def _emit(self, event: str, **fields) -> None:
        if self._on_event is None:
            return
        with self._lock:
            self._on_event({"schema_version": SCHEMA_VERSION, "event": event, **fields})

    @property
    def has_fallbacks(self) -> bool:
        """True when something other than the manifest can resolve a mod."""
        return bool(self.catalogue) or self.org_index is not None

    # -------------------------------------------------------------- one mod
    def _entry(self, folder, source):
        """The catalogue entry for this mod: by folder, manifest key, or repo."""
        if not self.catalogue:
            return None
        return self.catalogue.find(folder=folder,
                                   key=source.key if source else None,
                                   repo=source.github if source else None)

    def _advisories(self, folder, source, game):
        """Health notes the catalogue raises about this mod, if any."""
        entry = self._entry(folder, source)
        if not entry:
            return []
        return entry.advisories() + entry.game_advisories(game)

    def _local_file(self, path: str, expected_sha256: str | None) -> DownloadResult:
        """A file the player saved, held to what a download is held to: a
        regular file, under the byte ceiling, an archive by its first bytes,
        and the pinned sha256 when the manifest has one (ADR-0052)."""
        if not os.path.isfile(path):
            raise VerificationFailed(f"{path} is not a file")
        size = os.path.getsize(path)
        ceiling = getattr(self.client, "max_bytes", None)
        if ceiling and size > ceiling:
            raise TooLarge(f"{path}: {size:,} bytes, over the {ceiling:,} byte ceiling")
        with open(path, "rb") as fh:
            head = fh.read(512)
        kind = detect_kind(head)
        if kind is Kind.UNKNOWN:
            raise NotAnArchive(path, head[:160])
        actual = sha256_file(path)
        if expected_sha256 and actual.lower() != expected_sha256.lower():
            # never taken in its place: the pin stays what it was
            raise ChecksumMismatch(f"this file is not the one pinned for this mod ({path})",
                                   expected_sha256, actual)
        return DownloadResult(path, actual, size, kind, path)

    def _attempt(self, source, folder, candidate, expect_tp2,  # noqa: ARG002
                 force=False, local=None):
        """Download one candidate - or take the file the player supplied,
        `local` - and install it. Exceptions propagate."""
        if local is not None:
            result = self._local_file(local, candidate.sha256)
            self._emit("mod_extracting", folder=folder)
            # read where it is: the player's file is never moved or changed
            outcome = install_from_archive(local, self.options.target_dir, folder,
                                           force=force, allow_exe=self.options.allow_exe,
                                           expect_tp2=expect_tp2)
            return result, outcome
        staging = os.path.join(self.options.target_dir, ".staging")
        os.makedirs(staging, exist_ok=True)
        workdir = tempfile.mkdtemp(prefix=f"iemod-{folder}-", dir=staging)
        try:
            archive = os.path.join(workdir,
                                   archive_filename(candidate.filename, f"{folder}.bin"))
            extra: dict = {}
            if self._on_event is not None:
                extra["progress"] = lambda done, total: self._emit(
                    "download_progress", folder=folder, bytes=done, total=total)
            extra["cancel"] = self.cancel
            result = self.client.download(candidate.url, archive,
                                          expected_sha256=candidate.sha256, **extra)
            self._emit("mod_extracting", folder=folder)
            outcome = install_from_archive(archive, self.options.target_dir, folder,
                                           force=self.options.force or force,
                                           allow_exe=self.options.allow_exe,
                                           expect_tp2=expect_tp2)
            return result, outcome
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def process(self, item: WorkItem) -> Record:
        if self.cancel.is_set():
            return Record(item.folder, Status.CANCELLED, "the run was stopped before it",
                          error_code=Cancelled.code)
        self._emit("mod_started", folder=item.folder)
        return self._process(item)

    def _process(self, item: WorkItem) -> Record:
        folder, source = item.folder, item.source
        dest = os.path.join(self.options.target_dir, folder)
        advisories = self._advisories(folder, source, item.game)
        entry = self._entry(folder, source)
        # The tp2 this mod really ships, when it is not the WeiDU folder name:
        # the manifest's explicit override first, then the catalogue's record.
        expect_tp2 = ((source.expect_tp2 if source else None)
                      or (entry.expected_tp2 if entry else None))

        taking = self._taking_newer(folder, expect_tp2)
        if taking:
            return self._take_newer(item, taking, expect_tp2, advisories)
        supplied = self.options.supplied.get(folder.lower())
        if supplied:
            return self._supply(item, supplied, expect_tp2, advisories)

        if not self.options.refresh:
            existing = verify_mod_dir(dest, folder, expect_tp2)
            if not existing and expect_tp2:
                # it may already be installed under the name the archive uses
                renamed = os.path.join(self.options.target_dir, expect_tp2)
                existing = verify_mod_dir(renamed, folder, expect_tp2)
                if existing:
                    dest = renamed
            if existing:
                kept = self.state.get(os.path.basename(dest)) or {}
                newer = self._newer(folder, kept.get("url"), kept.get("mod_version"),
                                    kept.get("origin"))
                return Record(folder, Status.SKIPPED,
                              f"already installed and verified ({existing})",
                              source_key=source.key if source else None,
                              tp2_file=existing,
                              advisories=advisories + self._offer(folder, newer),
                              newer=newer)

        if source is None:
            if not self.has_fallbacks:
                return Record(folder, Status.MANUAL,
                              item.detail or "no entry in the manifest for this mod",
                              advisories=advisories, error_code=Unresolved.code)
            source = ModSource(key=folder, name=folder)   # resolved by fallback only

        resolution, discovered = self._resolve(source, folder)
        if not resolution.ok:
            return Record(folder, Status.MANUAL, resolution.reason,
                          source_key=source.key, url=source.url,
                          advisories=advisories, warnings=list(resolution.warnings),
                          error_code=Unresolved.code)

        candidate = resolution.candidate
        if self.options.dry_run:
            return Record(folder, Status.PLANNED,
                          f"would download {candidate.origin} {candidate.filename}",
                          source_key=source.key, url=candidate.url,
                          version=candidate.version, origin=candidate.origin,
                          discovered_github=discovered, advisories=advisories,
                          warnings=list(resolution.warnings))

        try:
            refused = [candidate.url]
            other = []                  # refusals for another reason than "not this mod"
            skip = {candidate.url}      # what was refused, and each source used
            while True:
                try:
                    result, outcome = self._attempt(source, folder, candidate, expect_tp2)
                    break
                except VerificationFailed as exc:
                    # The artefact is not this mod: the manifest's, or the
                    # catalogue's first source - a file scraped from a forum
                    # thread lcc-docs lists was a save game, debug logs or
                    # another mod's patch. Each of the catalogue's other sources gets
                    # one turn - a source, not a URL: one that redirects to a
                    # new signed URL each time would otherwise come round
                    # forever - and the same strict check gates every one.
                    if self.cancel.is_set():
                        raise Cancelled("cancelled") from exc
                    if not isinstance(exc, NotThisMod):
                        other.append(f"{candidate.url}: {exc}")
                    alternate = self._catalogue_alternate(source, folder, entry, skip)
                    if alternate is None:
                        if len(refused) > 1:
                            raise VerificationFailed(
                                f"none of the {len(refused)} sources tried contained this "
                                f"mod: {', '.join(refused)}"
                                + "".join(f"; {why}" for why in other)) from exc
                        raise
                    candidate = alternate
                    refused.append(candidate.url)
                except NotAnArchive as exc:
                    # baldurs-gate.de's XenForo `/download` answers 301 to the
                    # mod's GitHub releases page - HTML, not the file. That
                    # page names the repository the author publishes from, so
                    # its release is taken instead: once, and held to the same
                    # .tp2 check (GUI-AUDIT M7 item 55).
                    repo = repo_from_url(exc.final_url or "")
                    if (not repo or _pinned(source)
                            or ("github", repo.lower()) in {
                                (k, str(v).lower()) for k, v in
                                (s for s in skip if isinstance(s, tuple))}):
                        raise
                    skip.update({("github", repo), ("github", repo.lower())})
                    probe = self.github.resolve(_unpinned(source, repo))
                    if probe.candidate is None:
                        # the same code as the failure it stands for: the
                        # report's error codes are a contract (ADR-0030)
                        raise NotAnArchive(exc.url, exc.sniff, exc.final_url, note=(
                            f"; it leads to {repo} on GitHub, whose release could "
                            f"not be had: {probe.reason}")) from exc
                    resolution.warnings.append(
                        f"{folder}: {exc.url} leads to {repo} on GitHub; its release "
                        f"is used instead")
                    candidate = probe.candidate
            if len(refused) > 1:
                resolution.warnings.append(
                    f"{folder}: {', '.join(refused[:-1])} did not contain this mod; "
                    f"installed from {entry.origin} instead ({candidate.url})"
                    + "".join(f"; {why}" for why in other))
        except Cancelled as exc:
            return Record(folder, Status.CANCELLED, "stopped during the download",
                          source_key=source.key, url=candidate.url, error_code=exc.code)
        except InstallConflict as exc:
            return Record(folder, Status.CONFLICT, str(exc), source_key=source.key,
                          url=candidate.url, error_code=exc.code)
        except ModFetchError as exc:
            return Record(folder, Status.FAILED, str(exc), source_key=source.key,
                          url=candidate.url, error_code=exc.code)
        except OSError as exc:
            return Record(folder, Status.FAILED, f"filesystem error: {exc}",
                          source_key=source.key, url=candidate.url,
                          error_code="filesystem")

        # What the mod says about itself beats what any catalogue guessed.
        advisories = self._reconcile_with_tp2(advisories, outcome, item.game)
        if is_forum_post(candidate.url):
            declared = outcome.version or candidate.version or "no version"
            advisories.append(
                f"installed from a forum post ({candidate.url}), which may be older "
                f"than the author's release: the mod declares {declared}")
        newer = self._newer(folder, candidate.url, outcome.version, candidate.origin)
        advisories += self._offer(folder, newer)   # the name --take-newer reads

        with self._lock:
            self.state.record(outcome.folder, sha256=result.sha256, url=candidate.url,
                              version=candidate.version, tp2_file=outcome.tp2_file,
                              mod_version=outcome.version,
                              declares_games=", ".join(
                                  outcome.tp2_info.normalised_games) or None
                              if outcome.tp2_info else None,
                              source_key=source.key, origin=candidate.origin)
        # Prefer the version the mod declares over the release tag it shipped in.
        shown = outcome.version or candidate.version
        detail = f"installed {outcome.tp2_file} ({result.size:,} bytes"
        detail += f", {shown})" if shown else ")"
        if outcome.renamed_from:
            detail += (f"; the mod now ships as '{outcome.folder}' (your log says "
                       f"'{outcome.renamed_from}') - installed under the new name")
        if outcome.backup:
            detail += f"; previous copy kept at {os.path.basename(outcome.backup)}"
        return Record(outcome.folder, Status.OK, detail, source_key=source.key,
                      url=candidate.url, sha256=result.sha256,
                      version=outcome.version or candidate.version,
                      tp2_file=outcome.tp2_file,
                      origin=candidate.origin, bytes=result.size,
                      discovered_github=discovered, advisories=advisories,
                      warnings=list(resolution.warnings), newer=newer)

    # ------------------------------------------------- a file supplied by hand
    def _supply(self, item, path, expect_tp2, advisories) -> Record:
        """
        Install the file the player saved from a page this tool cannot
        download from - behind Cloudflare, a JavaScript button, a login
        (GUI-AUDIT item 68, ADR-0052). It is held to the manifest's pinned
        sha256 when there is one; with none, to what every download is held
        to: it unpacks to this mod, its .tp2 where WeiDU looks. The file is
        read where it is; no folder is scanned or watched.
        """
        folder, source = item.folder, item.source
        key = source.key if source else None
        page = source.url if source else None
        pin = source.sha256 if source else None
        candidate = Candidate(url=page or "", filename=os.path.basename(path),
                              origin="supplied", sha256=pin)
        try:
            # the player chose this mod's file: a copy on disk is replaced,
            # kept in .backup/ as --force keeps it
            result, outcome = self._attempt(source, folder, candidate, expect_tp2,
                                            force=True, local=path)
        except ModFetchError as exc:
            return Record(folder, Status.FAILED, f"{os.path.basename(path)}: {exc}",
                          source_key=key, url=page, advisories=advisories,
                          error_code=exc.code)
        except OSError as exc:
            return Record(folder, Status.FAILED, f"filesystem error: {exc}",
                          source_key=key, url=page, advisories=advisories,
                          error_code="filesystem")
        advisories = self._reconcile_with_tp2(advisories, outcome, item.game)
        with self._lock:
            self.state.record(outcome.folder, sha256=result.sha256, url=page,
                              tp2_file=outcome.tp2_file, mod_version=outcome.version,
                              declares_games=", ".join(
                                  outcome.tp2_info.normalised_games) or None
                              if outcome.tp2_info else None,
                              source_key=key, origin="supplied",
                              supplied_file=os.path.basename(path))
        checked = ("its sha256 matches the pinned one" if pin else
                   "no sha256 is pinned for it: checked by its .tp2, its sha256 recorded")
        detail = (f"installed {outcome.tp2_file} ({result.size:,} bytes"
                  f"{', ' + outcome.version if outcome.version else ''}) from the file "
                  f"you chose, {os.path.basename(path)}; {checked}")
        if outcome.backup:
            detail += f"; previous copy kept at {os.path.basename(outcome.backup)}"
        return Record(outcome.folder, Status.OK, detail, source_key=key, url=page,
                      sha256=result.sha256, version=outcome.version,
                      tp2_file=outcome.tp2_file, origin="supplied", bytes=result.size,
                      advisories=advisories)

    # ------------------------------------------------- a newer GitHub release
    def _newer(self, folder, url, version, origin=None):
        """
        The GitHub release to offer instead of a copy that came from elsewhere:
        the latest release of the repository named like the mod, as krion64's
        daily scan saw it, when it is newer than the VERSION the copy's tp2
        declares. None when it cannot be told - no such repository or release,
        a copy from GitHub already, versions that cannot be ranked. Offered,
        never taken unasked (ADR-0005, ADR-0039 amendment).
        """
        known = self.releases.get(normalize_key(folder))
        if not known or not version or _from_github(url, origin):
            return None
        repo, release = known
        if not newer_release(release.tag, version):
            return None
        return {"version": release.tag, "installed": version, "repo": repo,
                "date": release.date, "url": release.url}

    @staticmethod
    def _offer(folder, newer):
        if not newer:
            return []
        when = f", {newer['date']}" if newer.get("date") else ""
        return [(f"GitHub has a newer release: {newer['version']} ({newer['repo']}{when}); "
                 f"this copy declares {newer['installed']}. To install it instead: "
                 f"--take-newer {folder}")]

    def _taking_newer(self, folder, expect_tp2):
        """
        The (repo, release) to install for `folder` under --take-newer: only
        one offered for the copy on disk, named or by `all`. Asking by name
        never takes an older release, nor the same one again on each run
        (review of #52).
        """
        wanted = self.options.take_newer
        if not wanted or not (folder.lower() in wanted or "all" in wanted):
            return None
        kept = self.state.get(folder) or (self.state.get(expect_tp2) if expect_tp2 else None) or {}
        if not self._newer(folder, kept.get("url"), kept.get("mod_version"),
                           kept.get("origin")):
            return None
        return self.releases.get(normalize_key(folder))

    def _take_newer(self, item, known, expect_tp2, advisories) -> Record:
        """
        Install the GitHub release asked for, over the copy on disk (kept in
        .backup/, as --force keeps it). Only that release - its tag, not
        whatever GitHub calls latest now (review of #52): if it cannot be had,
        the mod is left as it is - the catalogue's other sources would only
        bring back the copy being replaced.
        """
        folder = item.folder
        repo, release = known
        source = _replace(item.source or ModSource(key=folder, name=folder),
                          url=None, github=repo, release_tag=release.tag, asset=None,
                          sha256=None)
        resolution = self.github.resolve(source)
        candidate = resolution.candidate
        if candidate is None:
            return Record(folder, Status.MANUAL,
                          f"--take-newer: {repo} {release.tag} could not be had "
                          f"({resolution.reason}); the copy on disk is kept",
                          source_key=source.key, advisories=advisories,
                          error_code=Unresolved.code)
        if self.options.dry_run:
            return Record(folder, Status.PLANNED,
                          f"would replace the copy on disk with {repo} {release.tag}",
                          source_key=source.key, url=candidate.url,
                          version=candidate.version, origin=candidate.origin,
                          advisories=advisories)
        try:
            result, outcome = self._attempt(source, folder, candidate, expect_tp2,
                                            force=True)
        except Cancelled as exc:
            return Record(folder, Status.CANCELLED, "stopped during the download",
                          source_key=source.key, url=candidate.url, error_code=exc.code)
        except ModFetchError as exc:
            return Record(folder, Status.FAILED, f"{exc}; the copy on disk is kept",
                          source_key=source.key, url=candidate.url, error_code=exc.code)
        except OSError as exc:
            return Record(folder, Status.FAILED, f"filesystem error: {exc}",
                          source_key=source.key, url=candidate.url,
                          error_code="filesystem")
        # the new copy's own GAME_IS, as for any other download
        advisories = self._reconcile_with_tp2(advisories, outcome, item.game)
        with self._lock:
            self.state.record(outcome.folder, sha256=result.sha256, url=candidate.url,
                              version=candidate.version, tp2_file=outcome.tp2_file,
                              mod_version=outcome.version,
                              declares_games=", ".join(
                                  outcome.tp2_info.normalised_games) or None
                              if outcome.tp2_info else None,
                              source_key=source.key, origin=candidate.origin)
        detail = (f"installed {outcome.tp2_file} ({result.size:,} bytes, "
                  f"{outcome.version or candidate.version}) from {repo}, as asked")
        if outcome.backup:
            detail += f"; previous copy kept at {os.path.basename(outcome.backup)}"
        return Record(outcome.folder, Status.OK, detail, source_key=source.key,
                      url=candidate.url, sha256=result.sha256,
                      version=outcome.version or candidate.version,
                      tp2_file=outcome.tp2_file, origin=candidate.origin,
                      bytes=result.size, advisories=advisories,
                      warnings=list(resolution.warnings))

    def _led_to_github(self, source, folder, landing):
        """
        The release of the repository a landing page redirected to (item 55) -
        never for a source pinned to a file: a pin means that file or nothing.
        """
        if _pinned(source):
            landing.reason += (f"; it is pinned to a file ({_pinned(source)}), so "
                               f"{landing.github}'s release is not taken instead")
            return landing
        probe = self.github.resolve(_unpinned(source, landing.github))
        if not probe.ok:
            landing.reason += f"; {probe.reason}"
            return landing
        probe.warnings.append(f"{folder}: {source.url} leads to {landing.github} on "
                              f"GitHub; its release is used")
        return probe

    def _resolve(self, source, folder):
        """
        Catalogue first, trusted owners only as a fallback.

        Returns (resolution, discovered_repo_or_None). A discovered repo is
        still only a candidate: the archive must pass the strict .tp2 check in
        install_from_archive before anything is written.
        """
        if source.github or (source.url or "").startswith("https://github.com/"):
            resolution = self.github.resolve(source)
        elif source.url:
            resolution = self.landing.resolve(source)
            if resolution.github:
                resolution = self._led_to_github(source, folder, resolution)
        else:
            resolution = Resolution(reason="entry has no url and no github repository")

        entry = self.catalogue.lookup(folder, source.key) if self.catalogue else None
        if resolution.ok:
            return resolution, None

        # 1. a curated catalogue knows where this mod actually lives
        empty = not (source.url or source.github)      # no manifest entry for it
        if entry:
            tried: list = []
            probe = self._probe_catalogue(source, folder, entry, tried)
            if probe:
                return probe
            if tried:
                # what the catalogue's sources answered, not only that the
                # (absent) manifest entry had none
                said = f"{entry.origin}: " + "; ".join(tried)
                resolution.reason = said if empty else f"{resolution.reason}; {said}"
        elif empty and self.catalogue:
            resolution.reason = "no manifest entry, and the catalogue does not list this mod"
        if not self.org_index:
            return resolution, None

        candidates = self.org_index.candidates(folder, source.name)
        if not candidates:
            return resolution, None

        for candidate in candidates[:max(0, self.options.discovery_attempts)]:
            repo = candidate.repo.full_name
            probe = self.github.resolve(_replace(source, github=repo))
            if probe.ok:
                probe.warnings.append(
                    f"{folder}: no catalogue source resolved; using {repo} found in "
                    f"your trusted owners ({candidate.rationale}). It will only be "
                    f"installed if it contains {folder}.tp2 or setup-{folder}.tp2.")
                return probe, repo

        shortlist = ", ".join(f"{c.repo.full_name} ({c.rationale})" for c in candidates)
        resolution.reason += f"; trusted-owner candidates to review: {shortlist}"
        return resolution, None

    @staticmethod
    def _reconcile_with_tp2(advisories, outcome, game):
        """
        Replace guessed compatibility notes with what the .tp2 actually declares.

        A catalogue's `games` list is maintained by hand and lags reality. The
        mod's own GAME_IS is not a guess, so when the two disagree the tp2 wins:
        it either withdraws a false alarm or raises a better-founded one.
        """
        info = outcome.tp2_info
        if not info or not game:
            return advisories
        verdict = info.supports(game)
        if verdict is None:
            return advisories                      # the mod states no requirement

        kept = [note for note in advisories if "-compatible" not in note]
        if verdict is False:
            kept.append(
                f"the mod's own .tp2 declares support for "
                f"{', '.join(info.normalised_games)} - not {game}")
        return kept

    def _catalogue_alternate(self, source, folder, entry, skip: set):
        """The catalogue's best candidate from a source not used yet, whose URL
        was not refused; the source and the URL join `skip`."""
        if not entry:
            return None
        used: list = []
        probe = self._probe_catalogue(source, folder, entry, skip=skip, used=used)
        if not probe:
            return None
        candidate = probe[0].candidate
        skip.update(used)
        skip.add(candidate.url)
        return candidate

    def _probe_catalogue(self, source, folder, entry, tried=None, skip=(), used=None):
        """
        Try the sources a supplementary catalogue lists, best first.

        A URL that is itself the archive beats a repository (no guessing which
        release asset is meant), which beats a landing page (no scraping). A
        forum thread, or a file attached to one, comes after all of them: what
        anyone in the thread posted is often not the mod, or an old copy of it
        (ADR-0039 amendment). All of them still have to pass the .tp2 check
        before anything is installed. Why each one failed is added to `tried`,
        when given. A source in `skip`, or whose candidate is - used already,
        or downloaded and refused - is passed over, so the next one gets its
        turn; the source returned is added to `used`, when given.
        """
        def failed(where, probe):
            if tried is not None and probe.reason:
                tried.append(f"{where}: {probe.reason}")

        def fresh(probe, slot):
            if slot in skip or not probe.ok or probe.candidate.url in skip:
                return False
            if used is not None:
                used.append(slot)
            return True

        def from_url(url, how, kind):
            if (kind, url) in skip:
                return None
            src = _replace(source, url=url, github=None)
            probe = self.landing.resolve(src)
            if probe.github:            # a link that redirected to GitHub (item 55)
                probe = self._led_to_github(src, folder, probe)
            if fresh(probe, (kind, url)):
                probe.warnings.append(f"{folder}: resolved via {entry.origin} {how}-> {url}")
                return probe
            failed(url, probe)
            return None

        direct = entry.direct_urls
        # a repository PAGE is covered by entry.github; a direct file link is not
        pages = [u for u in entry.http_urls if u not in direct and not repo_from_url(u)]

        for url in direct:
            if not is_forum_post(url) and (probe := from_url(url, "direct download ",
                                                             "direct")):
                return probe, None

        if entry.github and ("github", entry.github) not in skip:
            probe = self.github.resolve(_replace(source, github=entry.github))
            if fresh(probe, ("github", entry.github)):
                probe.warnings.append(
                    f"{folder}: resolved via {entry.origin} -> {entry.github}; it will "
                    f"only be installed if it contains {folder}.tp2 or setup-{folder}.tp2")
                return probe, entry.github
            failed(entry.github, probe)

        for url in pages:
            if not is_forum_post(url) and (probe := from_url(url, "", "page")):
                return probe, None
        for url in direct:
            if is_forum_post(url) and (probe := from_url(url, "forum attachment ", "direct")):
                return probe, None
        for url in pages:
            if is_forum_post(url) and (probe := from_url(url, "forum thread ", "page")):
                return probe, None
        return None

    def _collect(self, report: RunReport, item: WorkItem, future) -> None:
        try:
            record = future.result()
        except Exception as exc:                          # never lose a worker crash
            record = Record(item.folder, Status.FAILED,
                            f"internal error: {type(exc).__name__}: {exc}",
                            error_code="internal")
        report.records.append(record)
        report.warnings.extend(record.warnings)
        self._emit("mod_finished", folder=record.folder, status=record.status.value,
                   detail=record.detail)
        if self._stream:
            print(line_for(record, self._stream), file=self._stream, flush=True)

    # ------------------------------------------------------------- all mods
    def run(self, plan: Plan) -> RunReport:
        report = RunReport(warnings=list(plan.warnings))
        os.makedirs(os.path.join(self.options.target_dir, ".staging"), exist_ok=True)

        targets = list(plan.items)
        if self.has_fallbacks:
            targets += list(plan.unresolved)     # a fallback may still find them
        else:
            for item in plan.unresolved:
                hints = [vars(s) for s in plan.suggestions if s.folder == item.folder]
                report.unresolved.append({
                    "folder": item.folder,
                    "detail": "no entry in mod_downloads.json for this WeiDU mod folder",
                    "suggestions": hints})
        report.suggestions = [vars(s) for s in plan.suggestions]

        workers = max(1, min(self.options.workers, len(targets) or 1))
        self._emit("run_started", mods=len(targets))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self.process, item): item for item in targets}
            try:
                for future in as_completed(futures):
                    self._collect(report, futures[future], future)
            except KeyboardInterrupt:
                # Stop the downloads in flight at their next chunk instead of
                # waiting for each to finish; what completed is still recorded.
                self.cancel.set()
                for future in futures:
                    future.cancel()
                report.cancelled = True
                raise
        report.cancelled = self.cancel.is_set()
        self._emit("run_finished", cancelled=report.cancelled, counts=report.counts())

        try:
            self.state.save()
        except OSError as exc:
            report.warnings.append(f"could not write state file: {exc}")
        staging = os.path.join(self.options.target_dir, ".staging")
        if os.path.isdir(staging) and not os.listdir(staging):
            os.rmdir(staging)
        report.records.sort(key=lambda r: (r.status.value, r.folder.lower()))
        return report
