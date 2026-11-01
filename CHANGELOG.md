# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html), where
the public surface is the CLI's flags and the JSON report schema — not the
Python API, which is internal.

## [Unreleased]

### Added
- **Release notes, repository activity and krion64's notes in the wizard**
  (GUI-AUDIT item 51, ADR-0059): a mod's details show krion64's notes,
  requirements, incompatibilities and EET placement, and from its daily
  scan the repository's last push, whether it was archived and the latest
  release's notes - escaped plain text cut to a fixed length, never a link,
  each line naming krion64 and the day of its data. `in` and `rec` are left
  out (17 and 10 of 814 records).
- **"Maybe updated" in the wizard's mod selection** (GUI-AUDIT item 50,
  ADR-0044): a mod whose lcc-docs date is after the day this tool fetched
  your copy is marked "(maybe updated)", with a filter and, in its details,
  both dates and lcc-docs' page - a date, never a version, so never "update
  available". It reaches mods with no GitHub release (30 to 55 of the
  supplied 149). The copy's day is the one recorded when it was fetched, not
  the tp2's file date (a zip unpacks with today's), compared by day; a copy
  with no record is not marked.
- **The Linux bundles measured on the distributions players run** (ADR-0056):
  the `bundles-distros` workflow, dispatched by release.yml for each tag it
  publishes, starts the release's wizard and command-line zips in fresh
  fedora, archlinux, ubuntu:24.04, ubuntu:latest and debian:trixie
  containers, and `tools/distro_libs.sh` names the system
  libraries Qt lacks there (offscreen, X11/XWayland, Wayland) and the
  package that ships each. On 4.0.1 the command line started on all five;
  the wizard started on all five once those packages were in.

### Fixed
- **Text that is not ours shows as text everywhere in the wizard** (review
  of #123): Qt renders a tooltip, a default QLabel or a message box as HTML
  when it looks like HTML. Now as written: the question WeiDU asks during an
  install (a mod's own text: "Enter the kit for <name>:" lost `<name>`, and a
  `<span>` could hide words), the mod list's kind and refused-tp2 tooltips,
  the download table's detail and newer-release tooltips, the install
  order's tooltips, the window's status line, the game page's folder
  findings, every message box (errors, questions, the preset summary,
  "Others need it", the install confirmation), and the install button's
  prerequisites tooltip.
  `tests/gui/test_tooltips.py` drives each with markup, and fails on a new
  tooltip that is neither a fixed string nor `plain_tip`.
- **The README names the system libraries the Linux wizard needs**, per
  distribution (apt, dnf, pacman), as measured: the window on an X11
  desktop needs the `libxcb-*` libraries (`libxcb-cursor` for Qt 6.5 and
  later), which nothing named before.
- A question with none of mod_installer's choice words ("press a key to
  continue", "Try again (y/n)?") no longer leaves WeiDU waiting 3 hours: each
  install gives mod_installer a parser config of its own, in
  `install-plan/mod_installer-config/`, with the plan's known question texts
  added as choice phrases (ADR-0057). The player's own mod_installer settings
  are neither read nor changed: on Windows too, `APPDATA` is set only for
  mod_installer, and only when it says it is 16.0.0. Each phrase comes from
  one line of the question as WeiDU prints it (a question on two lines, or
  with two spaces, is matched too). On 105 mods, the 11 of 37 known question
  texts that had none of mod_installer's words each get a phrase; checked
  with the real mod_installer 16.0.0 and WeiDU v251 on synthetic mods.
- Asking mod_installer its version (`--version`, at the folder check and
  before an install) no longer creates or resets the player's own
  mod_installer `parser.toml`: mod_installer writes it before it reads its
  arguments, so it is pointed at a scratch folder (ADR-0057).
- **A program a Windows bundle starts no longer sees the bundle's DLL
  folder** (GUI-AUDIT item 61, ADR-0058): git, gh, 7-Zip, unrar,
  mod_installer and the browser are started with PyInstaller's DLL
  directory cleared, under one lock, and it is put back at once; measured
  in a real bundle on Windows at build time.
- **Every library a Linux bundle carries ships with its licence**: the
  package's copyright file and the address of that exact version's source,
  in `licenses/system/` and NOTICE-system-libraries.txt (the 4.1.0 zips had
  none: 11 libraries in the command line, about 90 in the wizard); the
  wizard carries Python's licence too. GNU Readline (GPL-3.0), which
  neither program uses, is left out of both.

### Documentation
- `docs/GUIDA-TEST-REALE.md` (in Italian): a real install on Debian trixie,
  Ubuntu 24.04+, Bazzite (through Distrobox) and CachyOS with the games from
  GOG or Steam - working copies of the games, the system packages per
  distribution as PR #118 measured them, verifying the release's zips, two
  test rounds, collecting the outputs without game files (or through Claude
  Code's Remote Control), a checklist. Whether WeiDU on Linux needs `tolower`
  on the Enhanced Editions is to be measured there, not assumed.

## [4.1.0] - 2026-11-01

### Added
- **The install's room and WeiDU said in the confirmation** (GUI-AUDIT item
  49): the install page reads `api.install_readiness` on the plan's worker
  thread and lists its warnings before *Install* - never a refusal.
- **Room and the right WeiDU, said before installing** (GUI-AUDIT item 49,
  ADR-0055): `api.install_readiness` warns, and never refuses, when:
  - the backup will not fit where backups go (its exact size);
  - a game's drive may lack room for the install (an upper estimate, said
    as one);
  - WeiDU is older than the one this program is tested with, or than a
    staged mod requires (`WEIDU_VER >= N`).
  Shown in the install confirmation (below).
- **A watchdog that only warns** (ADR-0049 point 4): no output from the
  install for 10 minutes, and no question, is said once on the install page
  with the last lines - and, when they end with a question the mods ask that
  mod_installer does not put to anyone, that it will wait until
  mod_installer's timeout. It never stops anything. The threshold is
  provisional: each run records each batch's longest silence in
  `install-plan/results.json` to set it from real installs.
- **The install page says what each component came to and how to start the
  game** (GUI-AUDIT items 69 and 71): after an install the components that
  need a look - with warnings, not installed because of errors, not
  reached, or where WeiDU.log and WeiDU's debug file disagree - are listed in
  the output and all are counted in the summary; after a successful one,
  EEex's advice (start InfinityLoader.exe) is said for the game that is
  played - in EET the EET game's log, not BG:EE's, which is not played.
- **Questions answered by question during the install** (GUI-AUDIT item 48,
  ADR-0049 amendment): a question mod_installer puts to this program is
  recognised by its expected text (read from the mod's files in the log's
  language) at the end of its window and answered by its key - the player's
  answer from the questionnaire, else the log's recorded answer for that
  very question; a recorded answer meant for another question is never
  given to it. So the questionnaire now offers every question whose text is
  known, also those under a condition. A question not recognised takes the
  next recorded answer, as before. Measured with the real mod_installer
  16.0.0: it asks only questions holding one of its choice words ("enter",
  "choose", "do you want"...); 11 of the corpus' 42 known questions have
  none, and WeiDU then waits until mod_installer's 3-hour timeout.
- **How to start the game after installing EEex** (GUI-AUDIT item 71,
  ADR-0054): `api.install_launch_advice(plan_dir)` says, for each planned log
  that installs EEex's main component, to start the game with
  InfinityLoader.exe (EEex.exe before v0.9) and never with its own program,
  which crashes. Off Windows it adds that EEex needs the Windows game,
  through Proton or Wine on Linux or CrossOver on macOS. Said by the
  install page after a successful install (below).
- **Ordering facts as planner regression tests** (GUI-AUDIT item 70):
  facts from Chriz Easy BG's curation notes that the community data holds,
  run in the community-data workflow on the data it has just fetched:
  - held by BWS-NG's rules: BG1NPC before EET_end, Ascension before Spell
    Revisions and SCS, Bubb's Spell Menu after a UI replacement;
  - held by krion64's places: Yeslick before Crossmod, Artisan's Kitpack
    after item mods.
  Facts the data does not hold are listed in GUI-AUDIT, not invented.
- **What each component of an install came to** (GUI-AUDIT item 69,
  ADR-0053): the result is not only mod_installer's exit code. Each planned
  component is installed, installed with warnings, not installed because of
  errors, or not reached, according to WeiDU's own verdicts in the game's
  WSETUP.DEBUG (only what this run appended) checked against its WeiDU.log
  before and after. Where the two disagree, the log wins. It is written to
  `install-plan/results.json` and returned as `Outcome.results`; the
  install page lists what needs a look (below).
- **The questions are answered before the install** (GUI-AUDIT item 48,
  ADR-0049 points 2 and 5): before *Install*, the wizard puts the questions
  the mods will ask to the player in one window - those whose place is sure:
  not under a condition, not printed from a variable, none after a question
  asked until valid, and in a batch of one mod's components none after a
  component that may still ask (an answer given in order would otherwise
  land on the wrong question). The answers are kept in `PROJECT/install-answers.json`
  by question key, so the next install does not ask again, and written into
  the planned logs as `// @wlb-inputs:`; the confirmation lists the components
  that may still stop to ask. Cancel installs nothing. New in the api:
  `install_questions` says per question whether it is answerable
  `beforehand`; `load_install_answers`, `save_install_answers`,
  `write_install_answers`, `answer_key`.
- **A mod this tool cannot download, supplied by hand** (GUI-AUDIT item 68,
  ADR-0052): in the wizard's download phase, a mod whose page is behind
  Cloudflare, a JavaScript button or a login can be opened in the browser and
  installed from the file the player saved there (`api.supply_download`). The
  file is held to what a download is held to - an archive under the byte
  ceiling, holding this mod with its tp2 - and to the manifest's pinned
  sha256 when there is one; its sha256 is recorded. Only the file chosen is
  read: no folder is scanned or watched.
- **The game closed before an install starts** (GUI-AUDIT item 67,
  ADR-0051): before an install or a resume, a program running from a game
  folder (the game, a launcher, another WeiDU; under Wine or Proton found by
  its command line) stops it, named with its pid; so does, on Windows, a
  `dialog*.tlk` another program still holds after a short retry. Each says
  to close it and try again. mod_installer starts each batch's WeiDU
  itself, so at each batch a program found is only said, once, as a
  warning; the install goes on.
- **What an install answered is recorded** (GUI-AUDIT M8 item 63,
  ADR-0045): `install-plan/answers.json` lists each question's last line, the
  answer and where it came from (the log, the player, EET's folder), written
  on every install run. Recorded answers still go in order: no rule on a
  question's text can tell which answers a mod takes (Tweaks Anthology #3210
  takes 0 outside its "between 6 and 15"), so none holds one back.
- **A known EET fault is said before installing** (GUI-AUDIT M8 item 65,
  ADR-0045). On Windows, when the Documents folder is registered with a space
  (a OneDrive folder such as "OneDrive - Company\Documents", or "D:\My
  Documents") and the EET copy still cuts that value at the first space
  (`EET/lib/macros.tph`, still so in EET at c26a11a), the wizard's install
  confirmation says that EET's core will write the game's settings
  (Baldur.lua: language, campaign...) to a folder the game never reads -
  naming it - or fail; saves are not affected. It is a warning, not a refusal,
  and not said on a resume past EET's core.
- `api.install_questions(plan_dir, mods_dir)` (GUI-AUDIT item 48, ADR-0049):
  for every component of the planned WeiDU logs, the questions its mod's
  files reach - read in the language the log installs it in - and the answers
  the log records; each component is "none", "answered", "maybe" (answers
  for what it surely asks, not for a question under a condition), "partial",
  "unanswered" or "unknown" (a question whose text is set elsewhere, a path its
  reading could not follow, the mod not in the mods folder), and the plan is
  forecast unattended only when every component is none or answered. A
  forecast, not a promise. The phase-5 questionnaire (above) writes the
  planned logs' answers from it.

- **The questions a mod will ask, read before installing** (GUI-AUDIT item
  48, ADR-0049): `iemod_fetch/readln.py` finds, for each component, every
  `ACTION_READLN` it may reach - in its body, the functions and macros it
  launches, the files it includes, its ALWAYS block - with the question's text
  in the project's language, keyed by its .tra reference, and says which may
  not be asked (under a condition), which repeat until valid, and what could
  not be followed. Measured on 105 mods of the reference build
  (`tools/readln_census.py`): 45 of 51 READLNs reached (88%), the question
  known for 42 of those (25 a .tra string in the player's language, 17 a fixed
  English text); of the 6 not reached, 5 are SCS's, behind paths built while
  installing, and 1 follows a FAIL. The questionnaire before Install (above)
  is built on it.
- ADR-0049: every question is known before the install starts, the player
  answers them in one place, a timer never answers, and a watchdog only warns
  when an install goes silent (the owner's decisions).

### Release workflow
- "Latest" is put back on the newest release of CHANGELOG.md
  (`tools/release_notes.py latest`) every six hours (release-latest.yml) and
  at every push to `main` that changes CHANGELOG.md or the version: a
  back-fill's tag starts the tagged commit's own, older release workflow,
  which marked 4.0.0 Latest over 4.0.1 on 2026-10-31. It fails, changing
  nothing, when GitHub does not answer. docs/RELEASING.md says how to cancel
  that second run.

### Documentation
- **GUI-AUDIT item 62 withdrawn, measured.** The HD mods' archives pass
  today's ceilings: read from their zips' central directories by HTTP Range
  requests, BGEE Graphics Enhanced 0.2.0 unpacks to 1.744 GiB and BGGO 3.6 to
  1.457 GiB, both under the 2 GiB unpacked ceiling, and no member trips the
  ratio guard. `--max-bytes` defaults to 2 GiB, not the 300 MB one measuring run
  used.

### Fixed
- **A file Windows holds for a moment no longer stops a download, an
  extraction or a backup** (GUI-AUDIT M8 item 66, ADR-0050). A rename refused
  because another program - an antivirus scanning a file just written - holds
  the file is tried again for up to about 5 seconds (0.15 s for a project file
  saved from the window). An extracted mod moves into the mods folder in one
  rename, not file by file, and if that fails the copy it replaced is put
  back.
- EET's Documents-path warning (item 65): a block nested in the cut's own
  (`if (` over lines, `) else (`) no longer ends it early, so an EET copy
  that sets the whole path after such a block is not warned about; a set
  inside the nested block, which depends on its condition, still is.

## [4.0.1] - 2026-10-31

### Fixed
- The wizard's window no longer freezes on Windows when a download, a
  catalogue update or a conflict check starts (ADR-0048). Every HTTP client
  built its own TLS context, and on Windows that reads the whole certificate
  store while holding the GIL: 50-64 ms on a GitHub runner, 240 ms once,
  enough to fail the 4.0.0 release gate. One context is now built per
  process, by the wizard before its window is drawn; verification is
  unchanged. Measured after: worst gap 11.8 ms on windows-latest (was 63.9).

### Added
- `GUI latency` workflow and `tools/gui_latency_summary.py`: the M3 test, run
  30 times on Linux and Windows with `IEMOD_LATENCY_TRACE`, lines up each long
  event-loop gap with the garbage collections and the download's events. The
  4.0.0 release gate measured one 240 ms gap on windows-latest (limit 100 ms)
  where CI on the same commit had passed; a faulthandler watchdog dumps every
  thread's stack while the loop is held, which named the cause above.

### Release workflow
- `RELEASE_TOKEN` is used only by a release that needs it (its commit's
  workflow files differ from `main`'s), and then checked against GitHub in the
  first job, not trusted for being set. 4.0.0's run built and attested for 15
  minutes, then its publish step met "Bad credentials" from an expired token,
  and no tag was made. Every other release is tagged with the run's own
  token; a release that needs a token GitHub rejects stops at once, saying
  what to renew. docs/RELEASING.md, "RELEASE_TOKEN", says how - and why an old
  failed run must not be re-run once a newer release is out.
- "Latest" is judged against `main`'s changelog, also on a tag pushed by hand.
- 4.0.0 joins `BACKFILL`: with a working `RELEASE_TOKEN` it is tagged on its
  own commit by the next automatic run after 4.0.1, or at once by *Run
  workflow* with version 4.0.0 (its workflow files differ from `main`'s, so
  the run's own token may not create that tag).

## [4.0.0] - 2026-10-31

### Upgrading from 3.x
- **Python 3.14** is needed to run the `.pyz` or a pip install; an older one
  stops with one sentence saying so. Where the system's Python is older
  (Debian trixie's 3.13, Ubuntu 24.04's 3.12, macOS's own 3.9), take a release
  bundle instead: `iemod-fetch-cli-<os>-<arch>.zip` for the command line,
  `iemod-fetch-gui-...` for the wizard. Both carry their own Python.
- **Linux bundles need Debian trixie or Ubuntu 24.04**: they are built on
  Ubuntu 24.04 and started on Debian trixie before release, and no longer
  checked on Debian 12 or Ubuntu 22.04.
- **RAR archives** are opened with the system's tools (ADR-0047): on Debian
  and Ubuntu `apt install libarchive-tools unar`; macOS and Windows 10/11
  have libarchive built in, and `brew install unar` helps on macOS. An
  installed 7-Zip or WinRAR is still used, last. Debian's own `7zip` package
  cannot read RAR - it was extracting them wrong before this release.
- A `decisions.json` written by 4.0.0 can name `keep-both` or hold
  `ignored_order`; an older iemod-fetch refuses it.
- The command line, its flags, exit codes and JSON reports only gain: new
  flags (`--backup`, `--restore-backup`, `--take-newer`...), new fields (the
  conflict report's `action` can be `keep-both`; `--list-mods` reports more);
  nothing is removed or renamed. The Python API stays internal.

### Changed (breaking)
- **Debian trixie is the minimum platform for the Linux bundles** (ADR-0043
  amendment of 2026-10-31). Both are built on `ubuntu-24.04`, may need glibc
  up to 2.41 (trixie's; was 2.35) and are started inside `debian:trixie`
  before a release - the command line with `--version` and `--help`, the
  wizard with `--check` (it was never started on an older system before).
  Debian 12 and Ubuntu 22.04 are no longer checked. The Python stays 3.14:
  on trixie the bundles carry it; the `.pyz` and pip need one installed.
- **One Python version: 3.14** (ADR-0043, GUI-AUDIT M6 item 36). `requires-python
  = ">=3.14"`; an older Python stops with one sentence saying so, instead of a
  syntax error. `.python-version` names it and every workflow reads it (20
  literal `"3.12"`s and two test matrices gone); CI tests that one version on
  Linux and Windows (macOS informational). ruff's target, mypy's
  `python_version` and the classifiers follow it; the wizard extra needs
  PySide6 6.11 or newer. A release tag older than `.python-version` (3.0.0) is
  rebuilt on the 3.12 it was built with.
- The code is written for 3.14 (item 38), one mechanical change: ruff's
  pyupgrade rewrote about 1,080 annotations and imports (`Optional[X]` ->
  `X | None`, `List` -> `list`, `typing` -> `collections.abc`), and `UP` is now
  part of the lint; `hashlib.file_digest` hashes backups; tarfile's `data`
  filter is used without the fallback for runtimes that lacked it. No
  behaviour changes: the same 1,317 tests pass.
- **Fixed (security): two users' GitHub Pages were one site** (items 39 and
  41). `same_site` reduced both `modder.github.io` and `attacker.github.io` to
  `github.io`, so a landing page's link to another user's page escaped the
  offsite gate (`--accept-offsite`). The site is now the registrable domain by
  the **Public Suffix List** (publicsuffixlist, MPL-2.0 - the first runtime
  library, ADR-0043), private suffixes included (github.io, gitlab.io...); an
  address is its own site. The library is pinned by version and hash in
  `requirements/runtime.txt`, carried inside the `.pyz` (318 KB, from 198) -
  copied from the hash-checked installation, two builds still byte-identical -
  and the bundles with its licence, audited by pip-audit, bumped by
  Dependabot in a group of its own.
- The weekly upstream check also watches Python (item 37): an issue when a
  newer stable Python is available, or when a place names another version than
  `.python-version`; a test holds them together.

### Documentation
- **What Chriz Easy BG and the HD-remaster thread teach** (GUI-AUDIT M8 items
  62-71): read on chriz-bg-collection (MIT, 508256a) and Gibberlings3 thread
  41637. Ten proposals, ideas and credited facts only: a size allowance from a
  pinned size, answers sent only after their question, real prompts as test
  cases, the EET Documents-path bug on Windows, Windows rename retries, the game
  not running before each batch, a gated download supplied by hand, a result per
  component, ordering facts as tests, and how to start the game after EEex mods.
  No HD mod is new to the catalogue.
- **The plan after three audits** (GUI-AUDIT M5b-M8): editing the order by
  component with fixes after a manual move (measured against BWS-NG, Infinity
  Mod Runner and Project Infinity); one Python version and the libraries that
  earn their place (ADR-0043, for 4.0.0); defects the audits reproduced, to be
  fixed in the standard library (the offsite check with publicsuffixlist); and what the other projects do that this
  tool does not. ADR-0044: lcc-docs' dates as a second update signal.

### Added
- **Resume a stopped install** (GUI-AUDIT M4 item 23, ADR-0045). After a
  failure or a Cancel, each game's own WeiDU.log says what went in: when it is
  the plan's beginning, `api.start_install(resume=True)` and the wizard's
  *Install* run only the rest (`api.install_progress` says "N of M"); when it
  is not, nothing runs, each diverging line is named (tp2, language and
  component) and the backup is how to start again. A component stopped
  half-way by a Cancel (its uninstall record in the game, no log line) is not
  resumed either: WeiDU would back up its leftovers as the originals
  (measured). mod_installer runs with `--skip-installed=false`: on Linux its
  skip reads `weidu.log` and installed the first component again (measured
  on 16.0.0).
- **Fixed: the wizard's background work reported back from its own thread.**
  A worker's result reached the page in the worker's thread (measured with
  PySide6), changing widgets from there; it now arrives in the GUI thread,
  before the thread's end, and is dropped if the page closed meanwhile.
- **Phase 5 of the wizard: installation** (GUI-AUDIT M4 item 22c, ADR-0045).
  The programs (mod_installer from the bundle, WeiDU found or downloaded after
  a confirmation that names its source and GPL-2.0 licence), a backup of each
  game folder first, then *Install* after a last confirmation: the order page's
  order is written to `PROJECT/install-plan/` (`api.write_install_plan`, with
  the project's languages; `api.install_games`) and mod_installer runs over it
  with its output shown live, WeiDU's unrecorded questions asked in a dialog,
  and Cancel. Nothing is undone by itself; the backup is how to start again.
- **The programs an install runs** (GUI-AUDIT M4 item 22b, ADR-0046).
  `api.find_tools` finds mod_installer where the player says, else beside the
  wizard's own program (the bundle carries it), else on PATH; it is never
  downloaded, and one older than 16 is refused on Linux. WeiDU: where the
  player says, else on PATH, else its official v251 release, downloaded only
  on the player's word (`api.tool_download` says what and under which
  licence, `api.download_tool` fetches it): sha256 checked before it is
  unpacked, unpacked safely, the program checked against its own sha256 and
  again each time it is found, kept in a per-user tools folder. The wizard
  runs mod_installer with `--download=false`, so a missing mod is an error
  rather than mod_installer asking for a URL, and none of mod_installer's
  options comes from the player's environment (NEW_EET_DIR, OVERWRITE...).
  A program on PATH is never one in the current folder. An accented BG:EE
  folder is no longer refused on Windows: measured in CI, the real WeiDU
  opens folders even outside the ANSI code page.
- **mod_installer 16.0.0, built into the wizard's bundle** (ADR-0046, ahead of
  GUI-AUDIT M4 item 22b). `packaging/mod_installer.py` compiles the commit CI
  tests (3b6827a, upstream's main branch) with Rust 1.98.0, statically on
  Linux. The wizard's bundles for Linux, Windows and macOS carry it beside
  the program, with its GPL-3.0 licence and a notice of its source; each
  release attaches that source (`mod_installer-16.0.0-source.tar.gz`, in
  SHA256SUMS and attested). On Windows the C runtime is linked in, so it starts
  without the Visual C++ runtime. The real-WeiDU job tests that same build. Why: upstream's last release,
  v12.1.1, stops after the first component on Linux (it reads `weidu.log`,
  while WeiDU writes `WeiDU.log`), and nothing newer is released.
- **Which open-source tool opens the catalogue's RAR archives, measured**
  (GUI-AUDIT M6 item 40, before the choice): `tools/rar_measure.py` and the
  `RAR extractors` workflow download every distinct .rar link of lcc-docs,
  extract each with the official 7-Zip 26.00 (pinned by hash, the reference
  only, never shipped) and with Debian trixie's own bsdtar (libarchive), unar
  and 7zip (the dfsg build, without the unRAR code) - trixie is the floor -
  plus Windows' tar.exe and macOS' bsdtar and unar, and count the archives
  each extracts to the same files. Of 105 RAR archives: bsdtar 95 on every
  system, trixie's unar 94 (no RAR5), Homebrew's unar 103, the dfsg 7zip 1;
  two solid RAR4 archives no open-source tool extracts (docs/TESTING.md).
  Nothing is bundled yet: the extractor set comes with an ADR.
- **The install, run** (GUI-AUDIT M4 item 22a, ADR-0045, amending ADR-0022):
  `api.start_install` runs mod_installer - the command the generated scripts
  run, after the same checks - reads its output line by line and answers
  WeiDU's questions: EET's BG:EE folder, then the answers the planned log
  records (`// @wlb-inputs:`, BIO's format), then the player. Cancel stops
  mod_installer and everything it started (its own process group; a Job
  Object on Windows), and so does its end, for whatever it left running. The
  command line still runs nothing; the wizard's page comes with item 22c.
  Verified with the real mod_installer 16.0.0 and WeiDU v251 (CI's
  real-weidu job).
- **Several rows at once, keys and find on the order page; group defaults**
  (GUI-AUDIT M5b item 35). Rows are selected and dragged together, moved one
  place with Ctrl+Up / Ctrl+Down, and found by name. A mod ticked whole takes
  one option per SUBCOMPONENT group - the one chosen, else the first (it was
  Qt's last); the only option of a FORCED_SUBCOMPONENT group is not unticked
  while its mod stays. `api.selection_digest`: the check and the plan are not
  run again when nothing they read has changed - the selection, the project's
  files, the community data and the mods staged in the target folder.
- **Deselect knowing who needs it** (GUI-AUDIT M5b item 34). Unticking a
  component that chosen ones need - its own mod's `requires`, or a dependency
  rule the last check found satisfied - asks first: untick those too, keep
  it, or untick it alone. **Resolve for this component** chooses its missing
  prerequisites (one alternative of an "any one of", never every target)
  and then keeps it against the error incompatibilities naming it; warnings
  stay the player's, and nothing is done before the player confirms.
  `api.selection_conflicts` gives `needs`, the dependencies satisfied now.
- **The order page's row panel, and "Ignore..."** (GUI-AUDIT M5b item 33).
  Under the list, every order rule on the selected row: what it must come
  after or before, the rule as written, its source - red where broken,
  dimmed where it names a whole mod. A red row's broken rules can be ignored,
  with why, in `decisions.json` (`ignored_order`, ADR-0033 amendment): the row
  is then grey while it stays where it is and breaks no other rule; dragging
  it or a new broken rule shows it red again. The command line accepts and
  checks the new key; an older iemod-fetch refuses a file that has it.
- **Fixes on each red row of the order page** (GUI-AUDIT M5b item 32).
  "Fix..." offers what mends the selected row, each previewed before it is
  applied: just after the mod a rule puts before it, or just before the one a
  rule puts after it (checked at once against the plan's rules); planned again
  by the rules with the player's other moves kept, or its components turned
  off (both previewed by the planner, in the background, writing nothing).
  Only a fix that mends its rule and adds no other broken rule and no new
  error is applied; the preview says what would break. A property test holds
  every offered move to that. `api.order_fixes`, and
  `api.preview_install_order`: the plan of a hand order or a selection, with
  the errors it adds, written nowhere.
- **A drop on the order page is checked at once** (GUI-AUDIT M5b item 31).
  Only the rules the moved row is in are checked again - BWS-NG's technique -
  and only the rows whose mark changes are painted, so the red marks come at
  once while the full plan is made in the background. A property test holds
  the incremental check equal to the full one; measured on 3,000 rows, the
  page shows its marks in 3.7 ms (p50), 7.1 ms (p95). `api.selection_plan`
  gives each unit `after`, the units a rule puts before it.
- **Split a mod on the order page and move one component** (GUI-AUDIT M5b
  item 30). *Split into components* turns the selected mod into one row per
  component, so a single component can be dragged on its own; *Join the
  parts* puts them back in one row. The order is saved with `tp2 n` lines -
  the Sorting Order the command line already reads - and planned again; the
  page and `--plan-order` give the same order, component for component. A
  split part is marked moved or wrong on its own, and a tp2 in both installs
  is saved with its numbers in each.
- **The kinds and the places, checked every night on the live data**
  (GUI-AUDIT M5 item 29, ADR-0041 decision 5). `tools/places_check.py`, run by
  the community-data workflow on what it has just fetched, fails when
  lcc-docs or BWS-NG start using a category `kinds.py` does not map, when
  krion64 loses a category a kind places into, when BWS-NG's
  `games/eet.json` loses its bg2ee sequence, or when a count collapses under
  its floor - in the workflow, not in a player's run where it would quietly
  place nothing. It prints what the
  sequence and the kind place, and measures a log's plan against BWS-NG's
  order, without and with those places. The mock EET job now also installs a
  plan reordered by kind with the real WeiDU.
- **Keep both, one installed last** (GUI-AUDIT M5 item 28, ADR-0033
  amended). Two components that touch the same thing, where no rule says they
  must not coexist - an incompatibility graded below `error`, as krion64's
  partial and soft conflicts and overlap advisories are - now offer, each way
  round, "keep both, X installed last (its changes win)" besides deselecting
  a side. Chosen in `decisions.json` (by hand, or the wizard's new button),
  it becomes an order rule: the plan is made again with it, and the finding
  is recorded as accepted with that reason. A choice that contradicts
  another rule is reported by the plan, never hidden. A hard (`error`)
  incompatibility does not offer it, nor does a pair an error also covers, and
  where a tp2's FORBID_COMPONENT already orders the pair only that way round
  is offered; a kept order the plan could not keep goes back to the player.
  The conflict report's option `action` gains `keep-both`, and a
  decisions.json naming one is refused by an older iemod-fetch. Measured first: the rest of item 28 was already there
  (krion64's per-component categories split 242 components) or has no data
  (BWS-NG classifies no component on its own).
- **The command line as a program that needs no Python** (GUI-AUDIT M6 item
  36, ADR-0043). 4.0.0 needs Python 3.14; Ubuntu 24.04, Debian trixie and
  macOS's own `python3` are older. Each release now carries
  `iemod-fetch-cli-<os>-<arch>.zip` for Linux, Windows and macOS: a
  PyInstaller folder (one folder, not one file, which unpacks itself on
  every start and is what Windows antivirus software flags most), with the
  runtime's libraries and their licences, no Qt. Each is unzipped and run
  with `--version` and `--help` before it is published, attested, and listed
  in `SHA256SUMS` (macOS: its own `.sha256`). The build stops if any bundled
  file needs a glibc newer than the minimum platform has (review of #70); on
  Linux it is built and checked as *Changed (breaking)* above says - on
  Ubuntu 24.04, then started inside `debian:trixie`. On Linux and macOS, programs it starts (git,
  gh, 7-Zip, unrar) get the system's library path back, not the bundle's
  (`childenv.py`), so they load their own OpenSSL; on Windows they still see
  the bundle's DLL folder after their own (GUI-AUDIT row 61). Python's LICENSE.txt ships with it. Measured
  locally, with a standalone Python (glibc 2.17): 14.7 MB, built in 14 s; run
  with an empty environment and no Python on `PATH`, it took the data
  folder's lock and reached GitHub through a proxy over TLS. The size of the
  CI build, which carries the system's OpenSSL, is not measured here.
- **BWS-NG's EET sequence places a mod krion64 does not, before any kind**
  (ADR-0041 decision 2a, the rest of GUI-AUDIT item 27). In the install after
  the EET core, such a mod goes after the nearest component before it in
  BWS-NG's `games/eet.json` (bg2ee sequence, `--eet-sequence`, cached by
  default) that krion64 places - after every mod krion64 gives that place;
  several after one component keep BWS-NG's order. krion64 places a whole
  mod where it starts, so a neighbour counts only in its mod's first run of
  the sequence, and the neighbour after is asked too: where the two are in
  different krion64 categories, or there is none after, the sequence
  decides nothing and says why, and the kind is asked. What BWS-NG installs
  before the EET core is never moved after it. A preference like the rest:
  rules and the player's Sorting Order still win (the summary says so when
  one applies). The plan summary lists them under "placed by BWS-NG's EET
  sequence", the order page marks "(by BWS-NG)", `api.selection_plan` gives
  `placed_from`. A cached `eet.json` that cannot be read is warned about and
  places nothing; one given by hand still stops the run. Measured on the
  2026-10-23 data, by BWS-NG's ids (a log may spell a mod otherwise and
  then is not matched - a miss places nothing): the sequence names 364 mods,
  30 of which krion64 does not place; 4 come before the EET core (WeiDU,
  WeiDU64, WeiDU-FileChangeLog, EEKeeper). Of the 26 others, 16 are placed
  by the sequence, 3 by their kind after the neighbours disagreed, 7 say why
  they have no place; where a kind would also place one of the 16 (9), the
  two agree on 8.
- **A mod krion64 does not place takes the place its kind decides**
  (GUI-AUDIT M5 item 27, ADR-0041 decision 2). Interface, cosmetic, kit,
  recruitable and one-day NPC, smith and merchant mods go after krion64's own
  mods in the category their kind maps to (84-100% of the mods krion64 places
  agree), and a quest after BG1's or BG2's quests by the games it lists
  (73%); every kind the sources give must decide, and decide the same place.
  Gameplay, tactics, patches, utilities, conversions and spell-and-item mods
  decide nothing: such a mod stays where it was chosen, and the plan says why.
  A placement is a preference, as krion64's is - the player's Sorting Order,
  the authors' inis and BWS-NG's rules still decide over it - and never in
  the BG:EE phase before an EET conversion (a single game's install is placed
  too). A mod with no place keeps where it was chosen, also behind one its
  kind moved (review of #67). The plan summary lists what its kind placed and
  why a mod with a kind has no place; the wizard's order page marks "(by kind)" with the source,
  and `api.selection_plan` gives `placed_by` and `no_place`. Measured on the
  2026-10-23 data: of 1,071 mods with a kind that krion64 does not place, 445
  are placed (139 kits, 121 NPCs, 72 quests, 48 smiths, 38 cosmetic, 27
  interface), 626 are not; on the 397 krion64 places whose kind decides, the
  kind says krion64's category for 351 (88%). The supplied 146-mod log is the
  Forge's own: krion64 places all but a portrait pack no source classifies.
- **Choosing mods by kind** (GUI-AUDIT M5 item 26, ADR-0041 decision 4).
  lcc-docs' categories and BWS-NG's are one taxonomy spelled two ways
  (`Quête`, `quest`); `iemod_fetch/kinds.py` maps both onto one vocabulary.
  `--list-mods` gains `kinds`, `kinds_by_source` (what each source says),
  `kind_disagreement`, and krion64's `install_category` and `tags`, shown
  beside and never mapped - optional fields, the schema stays version 1. The
  wizard's selection lists kinds down the left, adds a "Kind" column, marked
  where two sources disagree, and a "Kinds disagree" filter; the details say
  which source says what. Nothing is settled for the player.
- **GitHub's answers are asked "changed since?"** (GUI-AUDIT M7 item 45,
  part 2). A run asks GitHub what the run before it asked - each mod's latest
  release, the community data's HEAD - and every answer used to spend the
  hourly limit. Answers are now kept with their ETag in `<data dir>-http`
  (`iemod_fetch/etagcache.py`, written whole, owner-only) and asked again
  with If-None-Match; an unchanged one is a `304` with no body. GitHub's
  docs, and a measurement here (X-RateLimit-Remaining went 14985 -> 14984 for
  a 200 and stayed 14984 for the 304): an authorized 304 is free. Without a
  token it still counts, and saves only the transfer. A git tree named by its
  commit is not kept: it never changes, and keeping one per new commit of the
  community data would only grow the folder (review of #64).
- **The wizard offers a newer GitHub release, and takes it on request**
  (GUI-AUDIT M7 item 59). The download page shows a mod's offer under "Newer
  release" with a box to tick; "Install the ticked newer releases" runs the
  command line's `--take-newer` for the ticked mods only - nothing is
  replaced unasked. `api.download_selection` takes `take_newer` and each
  record carries `newer`.
- **The download measurement, every mod and from home** (GUI-AUDIT M7 item
  57). The download-sources workflow, run by hand, takes `real=all` to
  download every mod the catalogue found instead of 20, and its summary says
  what the player was told: copies from a forum post, newer GitHub releases
  offered, links that led to a GitHub repository. `tools/measure_workstation.py`
  runs the same steps from a player's own connection, where Gibberlings3, SHS
  and Nexus do not answer with Cloudflare's 403 as they do to GitHub's
  runners, and writes one new folder with `summary.md` to paste back - the
  community data fetched into it, the player's own cache left alone; a step
  that leaves no report stops it with a non-zero exit.
- **A newer GitHub release is offered for a copy from elsewhere, and taken on
  request** (GUI-AUDIT M7 item 59, ADR-0039 amendment). When a mod comes from
  an author's site or a forum post and krion64's release scan names a newer
  release of the repository called like the mod, the run says so beside the
  mod and in its JSON record (`newer`: version, installed, repo, date, url).
  `--take-newer FOLDER` (repeatable; `all` for every one offered; `take_newer`
  in the ini) installs that release over the copy on disk, kept in
  `.backup/`; if GitHub cannot give it, the copy is left as it is. Only a
  release that is offered is taken, by its tag (never an older one, nor the
  same one again on the next run). Measured:
  Ascension from a Beamdog thread (v1.5 BETA) is offered 2.1.0 from
  Gibberlings3/Ascension (krion64 knows it as InfinityMods/Ascension, renamed);
  finchnpc is offered nothing: its only scanned repository, RoxanneSHS/Finch
  (v53, which is 5.3), is not named like the mod, and the rule trusts only
  a repository that is - it misses this one rather than guess. An offer
  needs a plainly newer release (`versions.newer_release`): never a dotless
  tag whose readings disagree (`V19`, 19 or 1.9, against `2.0`; a number
  like BG1NPC's `v32` against `v31.1` is not dotless, and `v071` reads
  0.71), never a release candidate, beta, alpha or `pre-` tag over a stable
  copy (`v4.1.0-rc1` over `4.0`; a bare letter is a revision: `v4.81a` is
  offered over `v4.0`),
  never a tag that is a date over a version
  (`20180929` over `v1.5 BETA`), and a repository named exactly like the mod
  is preferred to one whose name only holds it. A release taken is checked
  against the game's GAME_IS like any download.
- **A game folder's backup and restore** (GUI-AUDIT M4 item 21, ADR-0042):
  `--backup GAME_DIR [--backup-to DIR]` copies `override/`, the
  `lang/*/dialog*.tlk` and the root's files with their sha256 and lists every
  other file; `--verify-backup` checks the copies; `--restore-backup BACKUP`
  shows what a restore would do and, with `--apply`, does it. A restore
  deletes nothing: what is in the way is moved into the backup's
  `displaced-<time>/`, and what it cannot put back is named. `api.backup_game`,
  `api.plan_restore`, `api.restore_backup`, `api.list_backups`.
- `tools/order_sources_benchmark.py` (GUI-AUDIT M5 item 25, ADR-0041): what
  krion64 (the Infinity Mod Forge), BWS-NG and lcc-docs say about a mod's kind
  and install place, measured against each other and against a WeiDU.log.

### Fixed
- **RAR archives on Linux were extracted wrong and reported as extracted**
  (GUI-AUDIT M6 item 40, ADR-0047). 7-Zip was tried first; on Debian and
  Ubuntu `7z` is the dfsg build without the RAR code, which writes every file
  with the wrong contents and exits 2, and unar then extracted over those
  files, renaming its own. Measured on real catalogue archives: the old order
  gave a tree different from 7-Zip's for every one tried, with no error. Now
  each unpacker extracts into a folder of its own, deleted when it fails, and
  `.rar` goes first to libarchive (bsdtar; Windows' own `tar.exe`), then unar
  (with `-D`, the archive's own layout), then a 7-Zip or WinRAR the player has
  installed. Nothing is bundled. On lcc-docs' 105 RAR archives libarchive
  opens 95 on every system, and with unar 100 (trixie) to 103 (macOS).
- **CI tests the runtime libraries as pinned.** The test jobs installed the
  extras alone, and their loose range (`filelock>=4.2.1,<5`) pulled filelock
  4.2.5 the day it came out while `requirements/runtime.txt` pins 4.2.4, so the
  zipapp tests - which build from the pinned versions - failed on every pull
  request. The jobs now install `requirements/runtime.txt` by hash first.
- **A GitHub App installation token in the new stateless format is no longer
  dropped** when it comes from git's credential helper. GitHub's `ghs_` tokens
  became JWTs in 2026 (about 520 characters, with dots); the shape check that
  keeps a stored password from being sent as a bearer refused them, and the
  run went anonymous (60 requests an hour) without a word. `ghs_` followed by
  three base64url segments is now a token. `$GH_TOKEN`, `--token-file` and
  `gh` were never checked this way and were not affected (ADR-0005a note).
- **Two refreshes of the community data at once no longer break each other**
  (GUI-AUDIT M6 item 39). The wizard refreshing at start and `--update-data`
  shared one staging folder: one failed with `No such file or directory`, and
  the manifest saved last forgot the other's update. A refresh now holds
  `<data dir>/.lock` (filelock 4.2.4, MIT, pinned by hash; ADR-0043
  amendments) when it has something to do. Meanwhile `--update-data` waits up
  to five minutes; an ordinary run uses the last good copy at once and says
  another program is refreshing it; a run whose data is fresh is not
  affected.
- **A newer GitHub release is no longer offered for a copy that came from
  GitHub, nor for the same number with a word added** (GUI-AUDIT M7 item 59, measured by the
  download-sources run of every mod). EET came as GitHub's source snapshot of
  v14.1 - whose tp2 still says v14.0 - and was offered v14.1: the snapshot's
  `api.github.com/.../zipball` URL did not read as GitHub. A copy whose
  candidate is a release asset or a source snapshot, or whose URL is on any
  of GitHub's download hosts, is now never offered - so a fork's default-branch
  snapshot is no longer offered the main repository's release either. And
  The Rune's only tag, `v04ru`, was offered over `V0.4`: the same number with
  a word added - a language, a platform such as `_EE`, an author's suffix
  (RoxanneSHS's tags end in letters of the mod's name: ru for The-Rune) - is
  not newer; a single letter is still a revision. The number is compared, not
  the digits (review of #63): `v11.0-fr` is still offered over `1.10`. A
  compromise, deliberately: `20191024-fix` is the one real tag where the offer
  skipped could have been new - offering it would loop on every run.
- **A download link that ends on a GitHub repository's page takes that
  repository's release** (GUI-AUDIT M7 item 55). baldurs-gate.de's resource
  `/download` answers 301 to `github.com/<owner>/<repo>/releases`, an HTML
  page: AC_QUEST, bgqe, c#solaufein, JA#BGT_AdvPack and c#brage failed "did not
  return an archive". The repository the author's site names is now resolved as
  any GitHub source - once, with the same tp2 check - whether the redirect
  shows when the link is opened as a page (a manifest's or the catalogue's
  link to `/download`) or when it is downloaded (a resource page's link). A
  source pinned to a file - a `sha256`, a release tag or an asset - is never
  handed over: a pin means that file or nothing. A XenForo thread
  (`index.php?threads/...`) and a `/forums/topic/` page are now told as forum
  posts, so they come last; the dead Dark Tidings `.rar` came from one.
- **GitHub's secondary rate limit is waited out, not taken for a refusal**
  (GUI-AUDIT M7 item 45). A 403 from GitHub stopped at once unless the hourly
  quota was spent, but GitHub also answers 403 (or 429) when requests come too
  fast, and its docs say to wait and retry: the `Retry-After` seconds, else at
  least one minute, then longer. That is what the client now does, for
  GitHub only and only when the response says so (a Retry-After header, or
  "secondary rate limit" in the body); a real refusal and a spent hourly
  quota still stop at once with their own message - a 429 with the quota
  spent too, which was retried after 2 and 4 s. A secondary limit asking
  more than five minutes stops at once rather than retrying early, and
  Cancel ends any wait between retries at once (the GUI's Stop no longer
  sits out a rate limit). A `Retry-After` given as an HTTP date (RFC 9110)
  is now waited until, not ignored.
- **A Russian, Polish or Chinese mod's component names read in its own
  script** (GUI-AUDIT M7 item 44). A .tra file that is not UTF-8 was read as
  Windows-1252 whatever its language: on 103 real mods, 2,286 Russian and
  721 Chinese .tra files came out as Latin letters, and Polish and Czech
  ones lost their `ł`, `ś`, `ź`. The code page now follows the language
  folder, by WeiDU 251's own table for HANDLE_CHARSETS (Russian cp1251,
  Polish and Czech cp1250, Simplified Chinese cp936, Traditional cp950,
  Japanese cp932, Korean cp949); measured, every one of those files then
  decodes to its own script. UTF-8 is still tried first.
- **`--language-preference` picks the language WeiDU means** (GUI-AUDIT M7
  item 43). The tp2 reader took a string from `~` or `"` to the next `~` or
  `"`, and any `LANGUAGE` word as a declaration: `~Use "smart" AI~` read as
  `Use`, `~~~~~...~~~~~` strings not at all, and code such as
  `iconv_path = ...` or `reload_array = ... LANGUAGE` as a language. On the
  119 tp2s of 103 real mods, 12 language lists disagreed with WeiDU 251's
  `--list-languages`, and 11 mods got a wrong WeiDU language number for at
  least one of eight common languages - NTotSC's English was number 1, its
  German; BP-BGT-Worldmap offered none. The tp2 reader now uses the scanner
  the component names already used (moved to `iemod_fetch/weidu_lex.py`):
  all 119 agree with WeiDU.
- **Every saved file goes through one atomic write** (GUI-AUDIT M7 item 46).
  Eight places wrote `<file>.tmp` and renamed it over the file: one temp
  name for every writer, so two runs saving the same state, report or cache
  wrote into the same temp, and five of them left it behind when the write
  failed. `iemod_fetch.atomic.write_text` gives each write a temp of its own,
  removes it on failure and keeps the file's permissions (a new file is
  readable by its owner only, as the config already was); the install state
  is still flushed to disk, now its folder too on Linux and macOS. The
  `--conflict-report` file, written in place before, goes through it too. A
  missing parent folder of the report, the config or the data manifest is
  now created, as it already was for the others.
- **A wrong catalogue download no longer hides the catalogue's other sources**
  (GUI-AUDIT M7 item 54). With GitHub out of reach, a Beamdog thread lcc-docs
  lists gave 8 of the 145 mods of an EET log a file that is not the mod - a
  save game, `.debug` logs, a compatibility patch, another mod, a sound. The
  .tp2 check refused it, and the retry asked the catalogue again and got the
  same file, so the author's page the entry also lists was never tried. Each of the entry's sources now
  gets its turn - one turn per source, not per URL, so a link that redirects
  to a new signed URL each time cannot loop - each held to the same check;
  the warning names what was refused, and when every source is refused the
  failure names each one, with the reason of any refused for something other
  than not being the mod (a path escaping the target folder, say).
- **A forum's file comes last, and says so** (GUI-AUDIT M7 item 58, ADR-0039
  amendment). With GitHub out of reach - no token and 115 GitHub mods is
  enough - Ascension came from a Beamdog thread as v1.5 BETA (its repository:
  2.1.0) and Finch as v4.0 (v6.0), silently: the right tp2, years old. A
  forum thread or a file attached to one is now tried after the entry's own
  direct links, its repository and its other pages, and a mod installed from
  one carries an advisory naming the post and the version the mod declares.
- **A contradiction in the order rules no longer breaks rules outside it**
  (GUI-AUDIT M7 item 42). When the sort got stuck it reported every unit left
  as the cycle and released the first in priority even if it was not in the
  cycle: with A and B ordered after each other and "C after A", C was placed
  before A (D too), and two cycles were reported: all four units, then A
  and B. Now the real cycle is
  found (the strongly connected part nothing else holds back), reported once,
  and the unit released is one of its own.
- A tp2 whose name has dots of its own (`www.urstuff2athkatla.tp2`) was keyed
  by its first word (`www`): krion64's place for it was never found, and a
  Sorting Order line naming it ordered nothing.

### Changed
- The release starts the macOS wizard bundle's workflow for its own tag, so
  the macOS zip arrives minutes after the release instead of at the next
  six-hourly check, which remains for a run that fails (ADR-0040 amendment).

## [3.0.0] - 2026-10-23

The wizard up to download (milestone M3, GUI-AUDIT). The major version is
the plan's number for that milestone, not a break: no flag, file or report
field of the command line is removed or renamed. Its changes are additive -
a `mod_extracting` event, and a run with no `mod_downloads.json` that uses
the community catalogue instead of stopping - plus the fixes below.

### Added
- **Presets** in the wizard's mod selection (GUI-AUDIT item 19): *Save
  preset...* writes the choice as a selection.json (the same bytes as the
  project's, so `--selection` reads it); *Load preset...* chooses what a
  selection.json, a WeiDU.log, a BIO share code or a Project Infinity list
  chooses - told apart by the file's content - matched to the list ignoring
  case and spelling, each component chosen as a click would (its
  SUBCOMPONENT cleared, what it needs chosen). What the list does not have
  is named in a message, never guessed; a file that chooses nothing (a fresh
  game's WeiDU.log) is refused, replacing a choice asks first, and a preset
  never replaces the project's own files. `api.import_selection`,
  `api.export_selection`.
- **The wizard without Python** (GUI-AUDIT item 20, ADR-0040): the release
  workflow builds it with PyInstaller as one folder per OS - Linux and
  Windows (macOS by `release-macos.yml`, attached after the release when
  its runner starts) - unzips it and starts it once offscreen
  (`iemod-fetch-gui --check`), zips it deterministically as
  `iemod-fetch-gui-<os>-<arch>.zip`, attests it and lists it in SHA256SUMS.
  The folder carries the LGPL-3.0 and GPL-3.0 texts and `NOTICE-Qt.txt`
  (the Qt and PySide6 versions bundled and where their source is);
  `packaging/gui_bundle.py` builds it locally too.
- **The wizard's download and extraction** (phase 4, ADR-0039): a row per mod
  (downloading with bytes, extracting, done, already there, failed, no
  download found, cancelled), *Download*, *Cancel*, *Retry the failed*;
  running again resumes. It is the command line's run in the project
  (`api.download_selection`, `api.project_settings`), so either can carry on
  from the other. Phase 5 is now Installation, with M4.
- With no manifest (`Settings.manifest = None`, a project ini without
  `manifest`), every mod is found through the community catalogue; with
  neither, the run stops with "no download source".
- `download-sources.yml` and `tools/download_measure.py`: the supplied
  log resolved and partly downloaded against the real network, weekly.
- A `mod_extracting` progress event: the download is complete and verified,
  and its archive is being unpacked and checked. Additive to events schema 1.
- The conflicts panel offers **Forget them...** for decisions in
  `decisions.json` that match no conflict of the selection any more (an id
  saved by an earlier build, a conflict whose mod is gone). It asks first and
  removes only those; a decision about a mod you only unticked for now goes
  too, which the button's tooltip says. It acts only on the current, finished
  check (a decision live again by the time you answer is kept), and with no
  rules to judge by (no community data yet) no decision is called stale.
- `mod-metadata.yml` and `tools/premeta_live_check.py`: the metadata ini
  search checked against the real GitHub, including the case-insensitive
  listing the unit tests could only fake. It runs on pull requests that change
  the fetch and weekly. A repository gone, or one repository's own error,
  fails it; only a quota or network failure is inconclusive.

- **The M3 validation test** (`tests/gui/test_m3_end_to_end.py`): the real
  main window, offscreen, from the game folders to every mod downloaded on a
  fixture EET selection - a conflict resolved, a mod reordered, the
  `selection.json` byte-identical to what the command line's
  `--emit-selection` writes from WeiDU.logs of the same components, the real download
  from a loopback mirror cancelled mid-file (nothing half-installed) and
  resumed (only the rest fetched again), the event loop never held for
  100 ms, no connection but loopback. The wizard's tests now run on macOS
  too, informational like the rest of `macos.yml`.

### Fixed
- **WeaselMods downloads** (about 20 mods of an EET build). Its package pages
  draw the download button by script, so no link on the page was the file:
  the tool either found nothing or took the page's link to itself and
  "downloaded" an HTML page. A WordPress Download Manager package page now
  gives `?wpdmdl=<its post id>`, which the real site answers with the zip
  (checked on Alabaster Sands and The Bloodied Stings of Barovia); a link to
  the page itself is never a candidate. `tools/landing_probe.py` shows what a
  landing page gives the tool, from the download-sources workflow.
- A command-line run in a project the wizard made (`--config
  PROJECT/iemod-fetch.ini` without `--plan-order`) stopped on the
  `language_preference`, `bgee_dir` and `bg2ee_dir` the wizard writes there:
  "works on an install plan". A BG:EE or BG2:EE project, which names one
  folder, stopped even with `--plan-order`: "go together". Values from the
  config file are no longer refused; the same flags typed on the command
  line still are.
- The default `mod_downloads.json` is optional: absent, with the community
  catalogue present, the catalogue is the source. A manifest named with
  `-m` must still exist.
- With no manifest entry, a mod the catalogue could not resolve said only
  "entry has no url and no github repository"; it now says what each
  catalogue source answered (the repository tried and its HTTP status, the
  page that could not be read), or that the catalogue does not list it.
- A link typed with accents (lcc-docs: `.../BG2_Mes_créations`) made
  http.client raise, and the mod failed as an internal error before its
  other sources were tried; links are now sent percent-encoded.
- A bare HTTP 403 from the GitHub API was reported as "rate limited or
  credential rejected; set GH_TOKEN". It may be GitHub's secondary limit or
  a proxy or policy refusing the repository, which no token cures; it says
  so. A 401 says the credential was rejected.
- An lcc-docs record listing several tp2s (`EET;EET_end;EET_gui`) was read as
  one name, so EET, IWD1_EET and IWD2_EET were never found in the catalogue,
  by the command line's fallback either. Each tp2 is now found by its own
  name; among records sharing a tp2, the repository named after the mod wins
  (EET over EET_Android).

## [2.5.0] - 2026-10-22

### Added
- **The wizard's first phase** (M3, ADR-0031). `iemod_fetch_gui`, a PySide6
  app installed with the `gui` extra and started with `iemod-fetch-gui
  --project FOLDER`: choose EET, BG:EE or BG2:EE, the game folders - checked
  as WeiDU's GAME_IS sees them as they are typed - and the languages; Next
  saves the project's `iemod-fetch.ini`, which the CLI reads too. It reaches
  the tool only through the api (an import-linter contract), and the CLI and
  the `.pyz` stay standard library only. Tested with pytest-qt offscreen on
  Linux and Windows in CI.
- `api.check_game_folders`, `api.languages`, `api.load_project` and
  `api.save_project`: the first phase as functions, for any front end.
- **The wizard's mod selection** (phase 2, ADR-0035): categories, search,
  filters, a mod -> component tree with tri-state boxes and exclusive
  SUBCOMPONENT choices, a details pane; Next writes `selection.json`.
  Components come from the staged mod's own tp2, else from krion64's records
  (1,471 of 1,529 WeiDU components on 105 real mods,
  `tools/krion_components_benchmark.py`); each mod says which. The catalogue
  loads in a background thread; closing the window while it loads is safe.
- `api.mod_choices` (mods with their components, for a game) and
  `api.save_selection`.
- **The wizard's conflicts panel** (phase 2, ADR-0033): the selection is
  checked against the rules a run uses, in a worker thread after each change;
  each conflict's options are buttons - deselect a side, choose a missing
  prerequisite the list knows, or accept a conflict with its reason in
  `decisions.json`, which `--decisions` applies. An order finding the plan
  could not settle is explained, not offered as a choice: `--decisions`
  applies a reorder only by sorting, which already failed for it. A filter
  shows only the mods still in conflict. An unreadable `decisions.json` is
  reported and never overwritten; a check of a list the page no longer shows
  (another game) is dropped.
- `api.selection_conflicts`, `api.load_decisions` and `api.save_decisions`:
  the panel as functions; the findings and ids are those of a run with
  `--selection --plan-order`.
- `tools/download_sources_benchmark.py`: lcc-docs', krion64's and BWS-NG's
  download data against each other, with `--probe` asking GitHub (git, no
  token) which repositories and pinned release tags are live and which are
  newer; `tools/krion_components_benchmark.py` takes BWS-NG's records as a
  third argument. ADR-0036 records which source is used for what.

- **The authors' own install order before download** (ADR-0037).
  `--fetch-metadata` fetches each planned mod's Project Infinity metadata ini
  (`Before`/`After`) from the repository lcc-docs (else krion64) names, into the
  data cache, and every later run uses it for the mods not staged yet; the
  wizard's conflicts check fetches it for what is chosen. Of 314 order pairs in
  85 real inis, 19 were known to no rule and no catalogue
  (`tools/pi_metadata_benchmark.py`).
- `--sorting-order FILE`: a Project Infinity Sorting Order file, read as order
  rules between consecutive lines of what is chosen. It is the player's own:
  a downloaded mod's ini never silences it.

- **The wizard's install order** (phase 3, ADR-0038): one tab per install,
  in the order the run will use; bold where a rule places a mod, red where an
  order rule objects; drag to reorder, saved as `install-order.txt` (a
  Project Infinity Sorting Order file) that the project's ini hands to the
  CLI as `--sorting-order`. An EET selection is saved as two installs, the
  BG:EE phase and EET, as krion64's categories place each component. The
  ini's `sorting_order` is read relative to the ini.
- `api.selection_plan`, `api.save_install_order`, `api.reset_install_order`.

### Fixed
- `--conflict-report` with `--plan-order` gave findings ids that `--decisions`
  could not match whenever a log's file name was not the plan's role
  (`WeiDU.log` for EET, `WeiDU-BGEE.log` otherwise): every `--selection` run,
  and a BG2EE `WeiDU.log`. The report now names the installs as the plan does,
  so an accepted or chosen decision shows in it, with each log's own file
  name.
- The conflict report's schema did not allow the `known-issue` scope its
  known-issue findings carry, so a report with one failed validation.
- An EET plan given two non-EET logs merged them into one BG:EE phase, and
  their findings shared ids; it is now refused with what to give instead.
- **A `%` in `iemod-fetch.ini`** (a path like `C:/Games/100%BG`) stopped the
  CLI with a raw configparser traceback; it is now a ConfigError that says to
  write `%%`, and the wizard writes it that way.

## [2.4.0] - 2026-10-21

The community-data release (milestone M2 of `docs/GUI-AUDIT.md`): what the
GUI's selection screen needs to show, measured against the tools that are the
ground truth. The data refreshes itself, guarded; components are named exactly
as WeiDU names them (9,889 of 9,889 names, 1,499 of 1,499 LABELs); each mod
says whether an update exists; every conflict comes with its options and
`--decisions` applies the player's; BIO share codes and Project Infinity lists
go in (BIO's own encoder and decoder agree), and the engine limits - kits,
spell slots, spell states - are measured in the game folder by WeiDU's own
rules, checked against the real WeiDU. Measured: 857 → 1,039 tests; still no
runtime dependency. Only additions to the CLI flags and JSON reports; the text
conflict report now prints ids and options for ORDER findings too.

### Added
- **The community data is kept current automatically** (ADR-0032). Each run
  refreshes a cache of lcc-docs, BigWorldSetup-NG and krion64 before it starts,
  at most once per `--data-max-age` hours (default 24), and uses it for
  `--catalogue`, `--rules`, `--mod-db` and `--order-catalogue` whenever those
  are not given. Only the `.json` files the tool reads are fetched, only the
  changed ones, each checked against its git blob hash and swapped in whole;
  offline, the last good copy is used. `--update-data` refreshes now and
  stops, `--no-update-data` stays offline, `--no-default-data` uses only the
  flags, `--data-dir` moves the cache. `api.update_data` and `api.data_status`
  for the GUI; a `data_source` event per source.

- **Guards on every community-data update.** Before a refreshed copy replaces
  the last good one, every file must be valid JSON and the copy must parse with
  the tool's own readers; a count (mods, rules, order entries) at zero or below
  half of the last good copy's - a format change upstream - refuses the update.
  The last good copy stays and the refused commit is not downloaded again. An
  accepted update reports what changed: counts before and after, mods added and
  removed, versions (BWS-NG, krion64) and catalogue statuses (lcc-docs) that
  moved. The README and guide no longer ask for `git clone`.

- **Component names, as WeiDU prints them.** `--describe-mods PATH` writes,
  for every mod staged under `--target`, its languages and its components
  named from the tp2 and its `.tra` files (`Group -> Name: VERSION`), in the
  first `--language-preference` the mod offers; `api.describe_mods` for the
  GUI; `schemas/components-v1.schema.json`. Runs no WeiDU. Each component
  also carries what WeiDU's `--list-components-json` gives - its `subgroup`
  (SUBCOMPONENT), `groups`, `labels`, `forced` - and `deprecated`, for the
  components WeiDU no longer lists: 1,499 of 1,499 identical on 109 tp2s. Measured against
  WeiDU 251's own `--list-components` on 103 real mods: 9,889 of 9,889 names
  identical (`tools/tra_oracle.py`, `tools/tra_benchmark.py`,
  docs/TESTING.md). Paths in the tp2 are matched case-insensitively and never
  outside `--target`.

- **Update notice.** Each mod's newest known version is the newest any of
  three sources names: the latest GitHub release (krion64's
  `version_cache.json`), the BWS-NG database and krion64's records. Each
  source alone agrees with the mods' own tp2 VERSION for 42-67 of 90 mods;
  the newest of the three for 79 (`tools/version_benchmark.py`,
  docs/TESTING.md). `--list-mods` gains `installed`, `latest` (version,
  origin, date, release page) and `update_available` (null when the versions
  cannot be ranked - never a guess); with `-w`, a run prints which installed
  mods have a newer version. `--releases PATH`, read from the data cache by
  default; the cache's guard now also counts the releases.

- **Conflicts come with options, and `--decisions` applies yours**
  (ADR-0033). Every conflict-report finding lists the ways to clear it -
  deselect one side, reorder, install a missing prerequisite - each with a
  stable id, its cost in components, whether a plan can apply it, and whether
  the rules recommend it (only where they decide; never on a tie). A
  `decisions.json` (`schemas/decisions-v1.schema.json`) chooses an option or
  accepts a finding with a reason; `--decisions` applies it to the plan before
  `--resolve-conflicts`, re-checks the plan, and the report then shows the
  finding as fixed or accepted. A decision whose finding is gone is reported
  as stale, never applied elsewhere. RESOLUTION.json records `by: decision`.

- **BIO share codes in and out.** `--bio-code PATH` reads a
  `BIO-MODLIST-V1:` code (Born2BSalty's Infinity Orchestrator) as what is
  wanted, in place of `-w` or `--selection`; `--emit-bio-code PATH` writes any
  input as one. Nothing is lost: a code BIO made re-encodes to the same payload,
  byte for byte,
  and exporting an imported list keeps every field BIO put in it. Checked
  both ways against BIO's own encoder and decoder. `api.load_bio_code`,
  `api.bio_code_of`. The format only; no BIO code is used.

- **Project Infinity lists in.** `--pi-list PATH:GAME` reads a PI or
  Infinity Mod Forge list (`LABEL;description`, or `folder:number;...`) as
  what is wanted. LABELs come from the staged tp2s, else from krion64's
  records - which agree with the tp2s for 708 of 732 LABELs, so each entry
  resolved that way is reported; an unresolved entry stops the run, never
  matched by its description.
- **An author's `mod-forge.json`** in a staged mod adds its conflicts,
  dependencies (with their component numbers) and known issues to the
  check; numbers as text, a number or a list.

- **Engine limits** (ADR-0034). The conflict report shows, per install, the
  kits, spell states and spell ids per level the chosen components add, with
  who adds them: kits against 256 (WeiDU's ADD_KIT limit on every EE game; the
  game has 40), spell ids against 50 per level (WeiDU's ADD_SPELL). Spell
  states are shown but never warned on: krion64's counts include states a mod
  only reads. Values checked in WeiDU's, EEex's and IESDP's sources; Infinity
  Mod Forge's 320 kits has no source. Warnings only, for every game patch.
  **Measured in the game folder** when the WeiDU.log is in one: the last kit
  number in KITLIST.2DA, the spell slots ADD_SPELL would skip, the ids in
  SPLSTATE.IDS - read from override/ or the BIFFs, by WeiDU's own rules, and
  checked against the real WeiDU in CI. krion64's counts stand in only for
  what the game does not hold yet: its spell scanner misses ADD_SPELL (an
  audit of its method found it), so an estimate is labelled as one.

### Fixed
- **Reading a mod's text stays inside the mod**, on Windows too: a tp2 path
  with a drive (`C:`), a stream or an absolute part is refused, a FIFO is
  never opened, and the resolved path is checked against the mod folder.
- **LABELs after `REQUIRE_FILE` or a multi-line `REQUIRE_PREDICATE`** are read.
- **Malformed krion64 records or JSON files** are skipped instead of stopping
  the PI-list import.
- **The version a WeiDU.log records is read.** WeiDU 251 writes
  `Name: VERSION` - one colon, despite its header's `[ : Version]` - and the
  parser looked only for ` : `, so a real log never gave a version. The
  suffix is now taken when it looks like a version and every component of the
  mod shares it: 1,409 of 1,409 component lines with a version read right, no
  option text (`cdtweaks: Use BG2 values`) taken for one. Rules about mod
  versions (the staleness check) now see installed versions.
- BIO's prompt answers at the end of a log line (`// @wlb-inputs: C:\My
  Games\BG2`) are no longer read as the mod's version.
- **Version comparison:** `Version 6.1` is 6.1, `1.0` equals `1`, and across
  sources `v071`/`0.71`, `V19`/`1.9` and `v2.02`/`2.0.2` are one release;
  `pre-v6.0` sits between 5.0 and 6.0.
- **A mod database's name** in `--list-mods` is the project, not its folder:
  `BigWorldSetup-Next-Generation`, not `mods`.
- **A component named `%like this%`** was not seen at all, and every
  component after it was numbered one too low. WeiDU reads `%...%` as a plain
  string (`BEGIN %Literal Name%` lists as "Literal Name"; checked with WeiDU
  251); so does the parser now.
- `--describe-mods`: a pre-EE `.tra` in Windows-1252 keeps its punctuation
  (`Imoen’s`, not a control character); a file that cannot be read leaves its
  names unresolved instead of stopping the run; symbolic links are not
  followed.
- The text conflict report shows the id and option of an outstanding order
  finding too, so it can be written into `decisions.json`.
- **Component numbers without DESIGNATED** are the previous number + 1, as
  WeiDU numbers them, not their position. A tp2 that designates some
  components and not others (EEUITweaks) had its
  constraints attached to the wrong numbers. Also read now: FORCED_SUBCOMPONENT
  groups, and `BEGIN` with the name on the next line (LCA).

### Changed
- **What may go on BG2:EE before the EET core comes from BWS-NG.** Its
  `games/eet.json` (maintained, last changed 2026-02-24) orders the EE
  Fixpack, `correctfrbg2ee` and `bws-fr-fixpack` before `eet:0`; EET's readme
  names only the Fixpack. `--resolve-conflicts` now moves any of them that
  refuses EET before the core instead of dropping it. The file is read from
  the data cache, or `--eet-sequence PATH`; without it, EET's readme rule
  stands as before.
- **`--plan-order` no longer needs `--order-catalogue`**, and checks use the
  community rules without setup, once the cache holds them. A run that gave no
  rules may therefore now report findings; `--no-default-data` restores the
  previous behaviour.

### Build
- The nightly "upstream rule data still parses" job became
  `community-data.yml`: the real refresh against GitHub, twice (the second must
  fetch nothing), then the parse floors. It also runs on pull requests that
  change the refresh.
- **macOS is informational, not a gate.** The CI gate (`ci.yml`), which the
  release re-runs, is Linux and Windows; the macOS test jobs moved to
  `macos.yml`, which runs on every pull request and on `main` but blocks
  neither. macOS runners stopped being assigned to this repository on
  2026-10-21 and held this release; the owner decided they should not.

## [2.3.0] - 2026-10-21

The backend release (milestone M1 of `docs/GUI-AUDIT.md`): everything the
command line does is now a public API (`iemod_fetch.api`) that the PySide6 GUI
will call, and a choice of mods no longer needs a WeiDU.log. Mods can be listed
from the catalogues, every JSON output is versioned with stable ids, progress
is reported as events and a run can be cancelled. Measured: 784 → 857 tests;
five architecture contracts, one of them keeping the CLI free of logic. Only
additions to the CLI flags and JSON reports, so existing scripts keep working;
the one new behaviour to know is exit code 130 for a cancelled run.

### Changed
- **Releases are automatic.** Merging a release pull request (a new
  `## [X.Y.Z]` section and the matching `__version__`) builds, attests, tags
  `vX.Y.Z` on that merge and publishes the GitHub release, with the changelog
  section as its notes. Nobody tags by hand. An older version without a release
  is published with *Run workflow* and its `version`. PyPI publishing is opt-in
  through the `PYPI_PUBLISH` repository variable. This is the method of
  R-studioConf's ADR-0006, adapted (ADR-0027).
- **One run goes from nothing to a checked plan.** A run that downloads now
  checks the rules, plans the order and builds the conflict report *after* the
  downloads, so the mods' own tp2 constraints and languages are read from what
  it just staged. Before, they were read first, and a fresh selection needed a
  second run to be checked (M1). `--check-only` is unchanged.

### Added
- **selection.json** (`--selection`, `--emit-selection`): the mods, components
  and languages wanted, without a WeiDU.log. One install, or BGEE + EET for an
  EET setup, in install order. It converts to and from WeiDU.log without loss,
  so every mode (fetch, check, plan) accepts it. Validated strictly: unknown
  keys, unknown games and tp2 paths leaving their folder are refused. JSON
  Schema in `schemas/selection-v1.schema.json` (ADR-0030, milestone M1).
- **`--list-mods PATH`**: every mod the manifest, the lcc-docs catalogues and
  the BWS-NG/krion64 mod database know about, one entry per mod with games,
  categories, rating, status, last update, version, advisories and each
  source's URLs and sha256. No WeiDU.log needed, nothing downloaded; a
  catalogue alone is enough. Schema in `schemas/mods-v1.schema.json` (M1).
- **Versioned JSON reports with stable ids.** `--json-report`,
  `--conflict-report` and `RESOLUTION.json` carry `schema_version: 1`. Every
  rule finding (`rule-…`) and conflict finding (`conflict-…`) has an `id`
  derived only from what it is about, so the same conflict keeps its id across
  runs. What `--resolve-conflicts` removes or leaves to you names the
  `finding_id` it settles. Schemas in `schemas/` (ADR-0030, M1). Fields were
  only added; existing readers are unaffected.
- **Progress events and cancellation.** `--events PATH` (`-` for stdout)
  writes one JSON object per line as the run goes: `run_started`,
  `mod_started`, `download_progress` (bytes and total, every 256 KiB),
  `mod_finished`, `run_finished`. The same events reach a `Runner`'s
  `on_event` callback, and a `cancel` event stops the run: no new mod starts,
  a download in flight stops at its next chunk without leaving a file, the
  mods it reached are marked `cancelled`, and the exit code is 130. Ctrl-C now
  stops downloads in flight the same way instead of waiting for them. Schema
  in `schemas/events-v1.schema.json` (ADR-0030, M1).
- **Stable error codes.** Every error class has a `code` (`checksum_mismatch`,
  `not_an_archive`, `http_status`, `unresolved`, `cancelled`, ...), and each
  record of the JSON report carries `error_code` when the mod did not succeed
  (plus `filesystem` and `internal`). A front end decides what to show from the
  code instead of parsing the message. The codes are pinned by
  `tests/test_error_codes.py` (ADR-0030, M1).
- **A public API, `iemod_fetch.api`** (ADR-0029): `Settings` (one field per
  command-line option, same name and default), `run(settings, stream=None,
  on_event=None, cancel=None) -> Outcome` (exit code, run report, order plan,
  conflict report), `list_mods`, `load_selection`, `selection_of_logs`. The
  command line is now a thin client of it, and an import-linter contract
  keeps it that way: `cli.py` may not import the planners, the runner or the
  formats. The GUI will call the same functions. This completes milestone M1.
- **Weekly check of the pinned test toolchain** (`upstream-versions.yml`):
  WeiDU and mod_installer are compared with upstream, and an issue opens for
  each one behind, with how to bump it. Dependabot cannot see those two pins.
  Its GitHub Actions updates now come grouped in one pull request (ADR-0028).
- **Published release notes follow CHANGELOG.md.** Each push to `main`
  rewrites a release body whose changelog section has changed, keeping its
  verification block (`tools/release_notes.py`).
- **Back-fills from the workflow itself.** Versions listed in `BACKFILL` are
  released by the next automatic run once the newest version is tagged. A tag
  on an older commit needs the `RELEASE_TOKEN` secret; without it the run
  skips with a notice instead of failing.

### Fixed
- **The 2.2.0 notes lost the start of the `--simulate` entry** (a text edit
  cut it). The section is restored, `tests/test_changelog.py` now rejects such
  stumps and unpaired bold markers, and the release notes are read from the
  current CHANGELOG.md, so *Run workflow* with `version` = `2.2.0` republishes
  them corrected.
- **The release step was refused with 403** for both 2.2.0 and 2.1.0, after
  the build and attestation had passed. GITHUB_TOKEN cannot create a tag on a
  commit whose workflow files differ from main's. Now main's head is tagged
  when nothing shipped changed since the version commit, so 2.2.0 releases
  with no token. A back-fill such as 2.1.0 stops early with the two ways out:
  push the tag by hand and then run the workflow for that version, or add a
  `RELEASE_TOKEN` secret (docs/RELEASING.md).
- **The release build ran the wrong `build`.** `python -m build` in the
  repository root imports the repository's own `build.py` (the zipapp script)
  instead of PyPA's build, so no wheel or sdist was made and the first automatic
  release stopped at "cp: cannot create regular file 'dist/'". The workflow now
  calls `pyproject-build`; the whole build step was re-run locally on 46eb8cb.
- **The release workflow could never run.** It called `ci.yml` as a reusable
  workflow, but `ci.yml` had no `workflow_call` trigger. It also shared a
  concurrency group with main's own CI run, so either could cancel the other.

### Build
- **GitHub Actions updated by Dependabot** (#10), still pinned by commit SHA:
  checkout v4 → v7.0.1, setup-python v5 → v7.0.0, upload-artifact v4 → v7.0.2,
  download-artifact v4 → v8.0.2, attest-build-provenance v1 → v4.2.2,
  action-gh-release v2 → v3.0.3, codeql-action v3 → v4.39.0. This clears the
  Node 20 deprecation warnings. The release-only actions (download-artifact,
  attest-build-provenance, action-gh-release) are first exercised by a release
  run; a dry run is *Run workflow* with a released `version` and `dry_run`.
- **The release pipeline is rehearsed on pull requests** that change it: the
  gate, build and attestation run on the pull request's own commit, and nothing
  is tagged or published. A Dependabot bump of a release-only action is tested
  before it merges (ADR-0027).

### Documentation
- **GUI audit** (`docs/GUI-AUDIT.md`): what the CLI still lacks before a UI
  can sit on it, what BIO, BWS-NG, lcc-docs, krion64 and mod_installer do and
  what of it may be reused, and a plan in milestones with acceptance tests.
  Accepted: ADR-0029 (a phased wizard that ends by installing), ADR-0030
  (a versioned JSON contract) and ADR-0031 (a PySide6 desktop GUI, packaged
  apart from the dependency-free CLI).

## [2.2.0] - 2026-10-21

The install-time release: the plan is now checked the way WeiDU will run it,
against the games it will run on, and that check is itself checked by the real
WeiDU. Measured: 761 → 784 tests (3 of them run the real WeiDU 251 and
mod_installer); branch coverage 91% → 92%; on the mock EET install, refusals
WeiDU would hit 1 → 0, with EEFixPack kept instead of dropped.

### Added
- **`--bgee-dir` / `--bg2ee-dir`: the game folders, verified.** Each folder is
  identified exactly as WeiDU's GAME_IS does it (marker resources in override/
  and chitin.key); a swapped pair, the same folder twice, an already-EET game, a
  modded BG2:EE and a BG:EE without Siege of Dragonspear are refused; SoD still
  in its `sod-dlc` archive (GOG/Steam) requires DlcMerger in the plan. Never
  written to. Patch level is reported as not checked (ADR-0026).
- **The real WeiDU as test oracle** (`tests/test_real_weidu.py`, and a CI job):
  synthetic game folders - no game data - on which WeiDU v251 refuses exactly
  what `--simulate` predicts, installs the resolved plan to the last component,
  and the generated `install-eet.sh` runs through the real mod_installer into
  both games. The toolchain is pinned: WeiDU by sha256, mod_installer by commit.
- **`--simulate`: walk the plan the way WeiDU will run it.** Each component's
  own tp2 constraints (REQUIRE/FORBID_COMPONENT, GAME_IS, ENGINE_IS,
  GAME_INCLUDES, MOD_IS_INSTALLED, body-level `NOT GAME_IS … ABORT`) are checked
  in plan order on the game it lands on: the BGEE log on BGEE, the EET log on
  BG2EE turning into EET once the EET core is in. Every component WeiDU would
  refuse is listed with the flag that refuses it. `--check-only` exits 1 if
  anything would be refused (ADR-0025).
- **The staged mods' own tp2s as rules** (origin `mod tp2`): a REQUIRE orders
  the required component first and is a dependency; a one-sided FORBID orders
  the declaring component first and warns that coexistence is not stated; a
  mutual FORBID is an incompatibility. Loaded whenever mods are staged, with or
  without `--rules`.
- **EET's merge check**, read from the staged EET (`tbl/compatibility.tbl` and
  its wrong-option `PATCH_FAIL`s): a BG:EE mod EET cannot import is found
  before the install, not at the merge.
- **`--resolve-conflicts` removes what WeiDU would refuse**, with WeiDU's
  reason, including the BG:EE mods that would make EET refuse the merge. The
  EET core is never removed.
- **A mock EET install test** (`tests/data/eetmock`): verbatim tp2 excerpts of
  DlcMerger, EEFixPack, BG1UB, EET, EET_end, Tweaks Anthology, SCS, Ascension
  and UB at pinned commits, EET's real `compatibility.tbl`, and logs carrying
  the usual mistakes.

### Changed
- **A refusal an order can fix is fixed by the order.** EEFixPack in the EET
  log is moved before the EET core, where the game is still BG2:EE, instead of
  being removed - as EET's readme and BWS-NG's `games/eet.json` place it. The
  report lists it under "moved before the EET core"; `RESOLUTION.json` gains a
  `moved` list.

### Fixed
- **A `BEGIN` inside an inlined file was read as a component.** EET_end.tp2
  inlines a `.d` file reading `BEGIN ~%file%~`; it was counted as component #0,
  which renumbered the real ones and lost EET_end's REQUIRE on the EET core.
  Found by the real-WeiDU test on its first run.
- **The mock EET fixture staged EET_end where WeiDU 251 cannot run it**
  (`eet/EET_end/`); it is now at `EET_end/`, as the EET repository ships it.

## [2.1.0] - 2026-10-20

A correctness and hardening release. No flag or report field changed meaning;
two behaviours changed on purpose and are listed under *Changed*. Measured on
the same machine before and after: 586 tests with 1 failing → 713 passing;
branch coverage 88% → 90%; gate failures on a clean checkout 4 → 0; 11
defects fixed, each with a test written to fail first.

### Fixed
- **A transfer cut short was accepted as a complete download.** `http.client`
  returns a truncated body without raising, so a dropped connection produced a
  partial file whose first bytes carried the right magic number. Bytes received
  are now checked against `Content-Length` and a shortfall is retried. Found by
  the new loopback socket tests; no test double could have shown it.
- **`IncompleteRead` crashed the run as an "internal error"** instead of being
  retried: it is an `HTTPException`, not an `OSError`.
- **Damaged archives crashed the run as an "internal error".** A truncated or
  CRC-corrupt zip/tar raised `BadZipFile`/`zlib.error`/`EOFError`, which escaped
  every typed handler and skipped the catalogue-alternate retry. Reported now as
  "damaged or incomplete - usually a partial download".
- **Security (Windows): a server-chosen file name could escape the work
  directory.** `Content-Disposition: filename="..\..\x.zip"` (or `C:\x.zip`)
  was joined onto the staging path; `posixpath.basename` does not split on `\`.
  Reduced to one safe component at the sink (`naming.archive_filename`).
- **Security: rar/7z/exe archives skipped the member checks** that zip and tar
  get. Their 7-Zip listing is now held to the same traversal, entry-count and
  size limits before anything is written.
- **Hostile `Retry-After` crashed the retry loop.** `-1` or `NaN` reached
  `time.sleep`, which raises. Clamped to 0–300 s.
- **Every retried HTTP error leaked a connection** until garbage collection
  (a `ResourceWarning` on Python 3.14).
- **Local disk errors were retried** (disk full, permission denied, read-only
  file system), downloading the whole file again each time to fail the same way.
- **Old-style packages were staged as `<mod>/<mod>/...`.** An archive with
  `setup-<mod>.tp2` beside a `<mod>/` folder now installs as `<mod>/` with the
  tp2 inside, which is what WeiDU needs.
- **Root-level WeiDU log lines were dropped.** `~SETUP-X.TP2~ #0 #0` (an older mod
  whose tp2 sits in the game directory) was warned about and never planned or
  fetched; the mod is now named by WeiDU's own `setup-<mod>.tp2` rule and the
  line is kept verbatim.
- **A release with `win-`/`lin-`/`osx-` packages picked `lin-` on Windows**
  (shortest name won). WeiDU's platform-prefix convention now decides first.
- The `L9` characterization test failed on every Python ≥ 3.12 under `-W error`;
  it now pins the tar filter the legacy script was written against.
- Five lint failures from a newer ruff (`ISC004`), and a mypy configuration that
  mypy 2.x refuses.

### Changed
- **Order checking is component-correct.** "A before B" now means every named
  component of A precedes every one of B, by real log line. The old check used
  each mod's first component and a per-mod grouped line counter: on the real
  install 34 of its 46 order findings were false ("X before EET_end", with
  EET_end logged last), and 2 real ones were hidden.
- `--resolve-conflicts` no longer resolves a tie by taking the left side (a
  guess); ties go to the operator. Same-mod conflicts with an unequal split are
  resolved like cross-mod ones.
- BWS-NG-format rules keep an `evidenceLevel` / `source` when an entry carries
  one, so a speculative claim is never resolved automatically.
- README no longer says `pip install iemod-fetch`: the package is not on PyPI.
  It is `pip install git+https://github.com/gsamuele78/iemod-fetch`.
- A GitHub `403` with an exhausted quota now says so, with the reset time,
  instead of a bare "HTTP 403".
- Asset selection prefers a package for the running platform; a log line with
  no mod folder now produces a mod instead of a warning.

### Added
- **From WeiDU logs to a running game.** `--emit-installer` writes
  `install-eet.sh` + `install-eet.cmd` (or `install.sh`/`.cmd` for one game)
  beside the plan. They hand the planned logs to dark0dave's mod_installer +
  WeiDU: BGEE first, then the EET core with the BGEE path, the EET mods, EET_end
  last. Before anything runs they refuse a folder without `chitin.key`, a game
  that already has mods, a missing WeiDU/mod_installer, and on Linux mixed-case
  mod folders (mod_installer hands WeiDU lower-cased paths). Verified by running
  the generated script with the real mod_installer 16.0.0 binary. iemod-fetch
  never executes the scripts (ADR-0022).
- **Automatic conflict resolution, where the rules decide.**
  `--resolve-conflicts` removes from the plan the components an error-graded,
  non-speculative incompatibility rule pins (the remedy the conflict report
  already named), re-verifies the plan, and writes `RESOLUTION.json`. Whole-mod
  pairs, same-mod option groups, missing dependencies and warnings are listed
  for the operator, never decided (ADR-0021). Your own logs are never edited.
- **Component-level install order** (ADR-0023). A mod is split across the order
  where krion64 places a component in another category (`co[].cat`) or an
  order rule names specific components; a mod nothing distinguishes stays
  whole. A rule between two components of one mod is honoured. On the real
  install: 6 mods split, plan verified against 158 constraints.
- **Preferred installation language with fallback** (ADR-0024).
  `--language-preference it_IT,en_US` sets each mod's `#lang` from its own tp2
  LANGUAGE declarations, first preference it offers; BWS-NG's model.
- **WeiDU SUBCOMPONENT clashes** (two options of one `Group -> Option` group)
  are reported without any rule set, and resolved by keeping the last.
- `--game-language` for the installer scripts (default: the first preferred
  language, else `en_US`).
- README banner, contents, feature table and an end-to-end quick start; guide
  chapter 10 (Windows and Linux); ADR-0021 and ADR-0022.
- `tests/test_net_loopback.py`: the real HTTP stack against a stdlib server on
  `127.0.0.1` (technique adopted from Born2BSalty's Infinity Orchestrator).
- Python 3.14 in the CI matrix and classifiers.

### Build
- ruff and mypy pinned to a minor series (`~=`), and the pre-commit ruff
  revision aligned with CI: an unpinned linter turned a green `main` red with
  no code change.
- Every GitHub Action pinned to a commit SHA (zizmor: 37 high findings → 0),
  and zizmor itself pinned. The release-notes step no longer expands the tag
  name into script source (template injection).
- The stdlib-only CI job failed at start-up: a warning filter naming
  `hypothesis` is a config error when Hypothesis is absent. It is registered
  from `conftest.py` only when Hypothesis is installed.

### Repository readiness (unreleased since 2026-09-10, shipped here)

#### Added
- `docs/ARCHITECTURE.md`, `docs/TESTING.md`, `docs/SECURITY-MODEL.md`,
  `docs/RELEASING.md` and `docs/ROADMAP.md`.
- Property-based tests (Hypothesis) over the parsers, the safety predicates and
  the version comparator (ADR-0019).
- Architecture contracts enforced by `import-linter`: the functional core may
  not import the imperative shell, and the runtime may not import a third-party
  package (ADR-0020).
- `iemod_fetch/urls.py` — pure URL facts, extracted from `resolvers`.
- CI/CD: lint, typecheck, architecture, test matrix, coverage floor, security
  scanning, SBOM, build provenance and signed releases.

#### Fixed
- **Version comparison was not antisymmetric.** Two spellings of the same
  stability level (`master`/`main`, `alpha`/`a`, `rc`/`pre`) each compared as
  *newer than the other*, so `is_newer` was true in both directions and an
  upstream renaming its default branch could mark a rule stale on the rename
  alone. Found by property-based testing, not by any example test.
- Archive extraction no longer hands an unvalidated member list back to the
  standard library: entries are extracted one at a time and the resolved
  destination is re-checked before each write.
- A manifest invariant in the pinned-manifest generator was an `assert`, which
  `python -O` strips. It is a raised `ManifestError` now.
- Two tests leaked file handles, surfaced by promoting warnings to errors.
- `catalogues` no longer reaches into `resolvers` through a function-local
  import to dodge an import cycle.

## [2.0.0] - 2026-09-09

### Added
- Component-level conflict reporting: which component of which mod fights which
  component of which other mod, with the upstream's evidence grade and source,
  and the narrowest remedy (ADR-0018).
- Whole-install order planning: `--plan-order` writes a rule-compliant
  `WeiDU.log` + `WeiDU-BGEE.log` pair and verifies the result against the same
  rules that judged the input (ADR-0017).
- Install-order, incompatibility and dependency checking against BigWorldSetup
  Next-Generation and krion64 rule data, with staleness detection (ADR-0015,
  ADR-0016).
- `.iemod` / Project Infinity metadata parsing, and `.tp2` introspection for the
  installed version and supported games.
- INI configuration file with documented precedence, `expect_tp2` manifest
  override, trusted-owner release discovery, LCC catalogue enrichment,
  `--emit-pinned-manifest`, and a single-file `zipapp` build.

### Changed
- Complete rewrite of the original single-file script. The original is kept in
  `legacy/` so its defects stay reproducible (ADR-0001).

### Security
- HTTPS enforced including across redirects; the GitHub credential is never
  attached to a non-GitHub host; archives are size-, ratio- and traversal-checked
  before extraction; downloads are verified against a pinned `sha256` when the
  manifest carries one.
