"""Per-mod pipeline and concurrent orchestration."""
import os
import shutil
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from dataclasses import replace as _replace

from .errors import (InstallConflict, ModFetchError, UnsafeArchive,
                     VerificationFailed)
from .install import State, install_from_archive, verify_mod_dir
from .manifest import ModSource
from .plan import Plan, WorkItem
from .report import Record, RunReport, Status, line_for
from .resolvers import (GitHubResolver, LandingPageResolver, Resolution,
                        repo_from_url)


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


class Runner:
    def __init__(self, client, options: Options, stream=None, org_index=None,
                 catalogue=None):
        self.client = client
        self.options = options
        self.org_index = org_index
        self.catalogue = catalogue
        self.github = GitHubResolver(client, allow_exe=options.allow_exe)
        self.landing = LandingPageResolver(client, accept_offsite=options.accept_offsite,
                                           allow_exe=options.allow_exe)
        self.state = State.load(options.target_dir)
        self._lock = threading.Lock()
        self._stream = stream

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

    def _attempt(self, source, folder, candidate, expect_tp2):  # noqa: ARG002
        """Download one candidate and install it. Exceptions propagate."""
        staging = os.path.join(self.options.target_dir, ".staging")
        os.makedirs(staging, exist_ok=True)
        workdir = tempfile.mkdtemp(prefix=f"iemod-{folder}-", dir=staging)
        try:
            archive = os.path.join(workdir, candidate.filename or f"{folder}.bin")
            result = self.client.download(candidate.url, archive,
                                          expected_sha256=candidate.sha256)
            outcome = install_from_archive(archive, self.options.target_dir, folder,
                                           force=self.options.force,
                                           allow_exe=self.options.allow_exe,
                                           expect_tp2=expect_tp2)
            return result, outcome
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def process(self, item: WorkItem) -> Record:
        folder, source = item.folder, item.source
        dest = os.path.join(self.options.target_dir, folder)
        advisories = self._advisories(folder, source, item.game)
        entry = self._entry(folder, source)
        # The tp2 this mod really ships, when it is not the WeiDU folder name:
        # the manifest's explicit override first, then the catalogue's record.
        expect_tp2 = ((source.expect_tp2 if source else None)
                      or (entry.expected_tp2 if entry else None))

        if not self.options.refresh:
            existing = verify_mod_dir(dest, folder, expect_tp2)
            if not existing and expect_tp2:
                # it may already be installed under the name the archive uses
                renamed = os.path.join(self.options.target_dir, expect_tp2)
                existing = verify_mod_dir(renamed, folder, expect_tp2)
                if existing:
                    dest = renamed
            if existing:
                return Record(folder, Status.SKIPPED,
                              f"already installed and verified ({existing})",
                              source_key=source.key if source else None,
                              tp2_file=existing, advisories=advisories)

        if source is None:
            if not self.has_fallbacks:
                return Record(folder, Status.MANUAL,
                              item.detail or "no entry in the manifest for this mod",
                              advisories=advisories)
            source = ModSource(key=folder, name=folder)   # resolved by fallback only

        resolution, discovered = self._resolve(source, folder)
        if not resolution.ok:
            return Record(folder, Status.MANUAL, resolution.reason,
                          source_key=source.key, url=source.url,
                          advisories=advisories, warnings=list(resolution.warnings))

        candidate = resolution.candidate
        if self.options.dry_run:
            return Record(folder, Status.PLANNED,
                          f"would download {candidate.origin} {candidate.filename}",
                          source_key=source.key, url=candidate.url,
                          version=candidate.version, origin=candidate.origin,
                          discovered_github=discovered, advisories=advisories,
                          warnings=list(resolution.warnings))

        try:
            try:
                result, outcome = self._attempt(source, folder, candidate, expect_tp2)
            except VerificationFailed:
                # The manifest's artefact is not this mod. A curated catalogue
                # often knows a better URL, so give that one turn before giving
                # up - the same strict check still gates the retry.
                alternate = self._catalogue_alternate(source, folder, entry, candidate)
                if alternate is None:
                    raise
                result, outcome = self._attempt(source, folder, alternate, expect_tp2)
                candidate = alternate
                resolution.warnings.append(
                    f"{folder}: the manifest's download did not contain this mod; "
                    f"installed from {entry.origin} instead ({alternate.url})")
        except InstallConflict as exc:
            return Record(folder, Status.CONFLICT, str(exc), source_key=source.key,
                          url=candidate.url)
        except (VerificationFailed, UnsafeArchive) as exc:
            return Record(folder, Status.FAILED, str(exc), source_key=source.key,
                          url=candidate.url)
        except ModFetchError as exc:
            return Record(folder, Status.FAILED, str(exc), source_key=source.key,
                          url=candidate.url)
        except OSError as exc:
            return Record(folder, Status.FAILED, f"filesystem error: {exc}",
                          source_key=source.key, url=candidate.url)

        # What the mod says about itself beats what any catalogue guessed.
        advisories = self._reconcile_with_tp2(advisories, outcome, item.game)

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
                      warnings=list(resolution.warnings))

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
        else:
            resolution = Resolution(reason="entry has no url and no github repository")

        entry = self.catalogue.lookup(folder, source.key) if self.catalogue else None
        if resolution.ok:
            return resolution, None

        # 1. a curated catalogue knows where this mod actually lives
        if entry:
            probe = self._probe_catalogue(source, folder, entry)
            if probe:
                return probe
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

    def _catalogue_alternate(self, source, folder, entry, used):
        """A catalogue-provided candidate whose URL differs from the one tried."""
        if not entry:
            return None
        probe = self._probe_catalogue(source, folder, entry)
        if not probe:
            return None
        candidate = probe[0].candidate
        return candidate if candidate and candidate.url != used.url else None

    def _probe_catalogue(self, source, folder, entry):
        """
        Try the sources a supplementary catalogue lists, best first.

        A URL that is itself the archive beats a repository (no guessing which
        release asset is meant), which beats a landing page (no scraping). All
        three still have to pass the .tp2 check before anything is installed.
        """
        for url in entry.direct_urls:
            probe = self.landing.resolve(_replace(source, url=url, github=None))
            if probe.ok:
                probe.warnings.append(
                    f"{folder}: resolved via {entry.origin} direct download -> {url}")
                return probe, None

        if entry.github:
            probe = self.github.resolve(_replace(source, github=entry.github))
            if probe.ok:
                probe.warnings.append(
                    f"{folder}: resolved via {entry.origin} -> {entry.github}; it will "
                    f"only be installed if it contains {folder}.tp2 or setup-{folder}.tp2")
                return probe, entry.github

        direct = set(entry.direct_urls)
        for url in entry.http_urls:
            # a repository PAGE is covered above; a direct file link is not
            if url in direct or repo_from_url(url):
                continue
            probe = self.landing.resolve(_replace(source, url=url, github=None))
            if probe.ok:
                probe.warnings.append(f"{folder}: resolved via {entry.origin} -> {url}")
                return probe, None
        return None

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
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self.process, item): item for item in targets}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    record = future.result()
                except Exception as exc:                  # never lose a worker crash
                    record = Record(item.folder, Status.FAILED,
                                    f"internal error: {type(exc).__name__}: {exc}")
                report.records.append(record)
                report.warnings.extend(record.warnings)
                if self._stream:
                    print(line_for(record, self._stream), file=self._stream, flush=True)

        try:
            self.state.save()
        except OSError as exc:
            report.warnings.append(f"could not write state file: {exc}")
        staging = os.path.join(self.options.target_dir, ".staging")
        if os.path.isdir(staging) and not os.listdir(staging):
            os.rmdir(staging)
        report.records.sort(key=lambda r: (r.status.value, r.folder.lower()))
        return report
