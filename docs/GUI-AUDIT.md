# GUI audit — from a CLI to a complete mod manager (2026-10-21)

The question: can iemod-fetch become a complete tool, a command line with a UI
on top where a player picks mods and components from tabs, checkboxes and
drop-downs, sees which mods are current, and gets the install order and the
component conflicts resolved? And what can be taken from the projects this one
already reads, and from Born2BSalty's Infinity Orchestrator (BIO)?

The answer in one line: **yes, but the CLI is not ready to carry a UI, and the
work to make it ready is most of the work.** The UI comes last. This document
is the audit (phase 1), the plan (phase 2) and the acceptance tests (phase 3).
The decisions are ADR-0029 to ADR-0031 in [ADR.md](ADR.md), accepted by the
owner on 2026-10-21. The answers to §1.1 changed two of the assumptions first
made: the wizard ends by installing, and the UI is a PySide6 desktop app like
BWS-NG.

---

## Phase 1 — Audit

### 1.1 Missing information, and the assumptions made instead

| Question | Answer (owner, 2026-10-21) or assumption |
|---|---|
| Should the UI also **install** (run WeiDU / mod_installer), or only plan, fetch and hand over? | **Install too**: a wizard in phases like BWS-NG, Forge/Runner and BIO, with installation as the last phase (ADR-0029). |
| Target users: only EET, or every Enhanced Edition game? | EET, BGEE and BG2EE first. IWDEE next, because BWS-NG and BIO already cover it. PST/IWD2 are out of scope. |
| Which UI toolkit? | **PySide6, like BWS-NG** (ADR-0031). The GUI is its own package and download; the CLI stays one dependency-free `.pyz`. |
| Will the BIO, BWS-NG or krion64 authors license their data for reuse? | No. Their data is read at run time as user-supplied input, never bundled. |
| Windows as the main platform? | Yes. CI already tests Windows, but no real Windows install has run yet. |

### 1.2 Where the CLI stands (v2.2.0)

Verified by reading the code. 803 tests pass, 4 are skipped, branch coverage
is at least 85%, and there are no TODO/FIXME markers.

**What it does well:**
- downloads with sha256 pinning and archive safety checks (magic bytes,
  extraction ratio, HTML-as-archive refusal);
- reads catalogues: `mod_downloads.json`, lcc-docs, the BWS-NG database and
  rules, and the krion64 order;
- builds a component-level install order and a conflict report, with automatic
  resolution where a rule decides;
- simulates the EET install, checks game folders, chooses languages;
- emits mod_installer input.

**What a UI needs and the CLI does not have:**

| Need | State | Evidence |
|---|---|---|
| Browse the available mods without a WeiDU.log | **no** | `cli.py:584-590` refuses to run without `-w`; nothing lists a catalogue |
| A selection made from scratch (mod + components + language) | **no** | the only selection format is WeiDU.log |
| Components with names, groups and choices | **partial** | `Tp2Component` (`tp2.py:201`) has numbers, SUBCOMPONENT, REQUIRE/FORBID; no name (no `.tra`), no LABEL/GROUP/DEPRECATED |
| "Newer version available" per mod | **no** | `resolvers.py:126` reads the latest release but never compares it with what is installed (roadmap E2) |
| A versioned JSON contract | **partial** | reports exist, but none has `schema_version` and findings have no stable id |
| Conflicts as choices a UI can offer | **partial** | `Finding` has both sides; `Unresolved` is free text; there is no `decisions` input |
| Progress and cancellation | **no** | one printed line per mod (`runner.py:330`); no byte progress; Ctrl-C only |
| A public library API | **partial** | the pieces can be imported, but the wiring is private in `cli.py:261-707` |
| Stable error codes | **partial** | typed exceptions, but per-mod failures become strings |
| One-run fetch then plan | **no** | planning reads the target folder before the downloads (`cli.py:604` vs `678`) |
| A stated scope that allows a GUI | **no** | ROADMAP 2.3 "Explicitly not planned": *A GUI*, *Running WeiDU* |

### 1.3 What the other projects do

| Project | License | Toolkit | Order | Conflicts | Updates | Integrity |
|---|---|---|---|---|---|---|
| **BIO** 1.0.3-beta | GPL-3.0 | Rust + egui | user drags; **no sort** | own tp2 line scan + 21 hand rules | GitHub API (releases, tags, forks), page scrapers | FNV-1a hash, **no sha256** |
| **BWS-NG** | GPL-3.0 | Python + PySide6 | 351 rules + per-game sequences | 254 incompatibility + 246 dependency rules | data bundle with a version file; mods bumped by hand | sha256 per file |
| **lcc-docs** | MIT | static site, vanilla JS | none | mod-level only | `last_update` by hand | none |
| **krion64 Forge** | MIT (data provenance uncertain) | React page | category × `ord` | hard/soft with evidence | weekly GitHub release scan | none |
| **mod_installer** 16.0.0 | GPL-3.0 | Rust CLI | follows the log | none | none | none |
| **Infinity Mod Runner** | MIT | Tauri + React | from Forge | from Forge | — | — |
| **Chriz Easy BG** (CEBG) 0.1.0-alpha.15 | MIT (one GPL-3.0 EET excerpt) | Rust + Tauri, Windows only | one captured WeiDU.log, not computed | 61 choice groups + 11 by hand | pinned recipe, by hand | **sha256 + size + redirect hosts** |
| **iemod-fetch** 2.2.0 | MIT | Python CLI, stdlib only | **sorted**, component level | tp2 + rules, auto-resolution | partial | **sha256 + attestation** |

What follows from that:

- **BIO's code and data cannot be taken.** BIO is GPL-3.0 and its prompt
  parser is AGPL-3.0, so nothing is copied or bundled. Its *formats* can be
  read and written. Its share code is `BIO-MODLIST-V1:` + base64url(zlib(JSON)),
  containing the WeiDU.logs, pinned sources and mod configs. That gives
  iemod-fetch access to the modlists BIO users exchange on Discord.
- **BWS-NG is the UI model players already know.** It is a PySide6 wizard:
  - a category column;
  - a tree of mod → component → choice with tri-state checkboxes;
  - `muc` groups shown as radio buttons and `sub` prompts as drop-downs;
  - a violations panel with one-click fixes;
  - EET order as per-phase tabs.
  iemod-fetch already reads its rule syntax.
- **lcc-docs is the only browse list that may legally be reused as-is.**
  It is MIT and covers 2,151 mods with status, safe, games, categories and
  `last_update`. It has no component data.
- **mod_installer is a poor engine to drive from a UI.** It produces only log
  text, its prompts arrive on stdin, and its automatic EET path answer works
  on Linux only. A UI that installs would either work around this or drive
  WeiDU itself, as BWS-NG and Infinity Mod Runner do.
- **CEBG is the nearest in kind, the narrowest in reach** (read at 508256a,
  2026-10-31). It is an installer, not a list: pinned downloads checked by
  size and sha256, WeiDU run directly (not mod_installer), resume from a
  ledger, one curated EET collection of 434 components. It has no computed
  order or conflicts, runs on Windows only, in English, on Steam 2.7.3 games.
  Its install loop is harder than ours in places worth learning from (M8
  items 62-71); its order and selection are one player's curation, not taken.
- **iemod-fetch already does better than all of them** at the parts a UI cannot
  replace: verified downloads, a computed order, automatic resolution and
  running headless. That is the argument for building the UI on top of this
  core rather than adopting one of theirs.

### 1.4 Risks, stated plainly

- **`.tra` resolution is the hardest single item.** Component names live in
  translation files with `@n` references, per language, sometimes generated at
  install time. Without names a component tree is a list of numbers. Size L.
- **The scope grows.** "Also install" makes this a fifth installer in a small
  community. The plan keeps installing optional and late.
- **Data is borrowed, not owned.** Order and conflict quality depends on
  BWS-NG and krion64 data that this project may not bundle. If either goes
  stale, the UI looks wrong, not the code.
- **No real-game CI.** Everything is checked against synthetic game folders
  (roadmap F5/F9). A UI invites players who will find what synthetic folders
  do not.
- **Stale roadmap line.** The 2026-09 open item about the v2.1.0/v2.2.0 tags
  is done: both releases are published (ADR-0027).

---

## Phase 2 — Plan

A milestone is entered only when the previous one passes its tests in phase 3.

### M1 — The CLI becomes a backend (v2.3) — must have, no UI yet

*Done on 2026-10-21* in #14 (selection.json), #15 (`--list-mods`), #16
(versioned reports, finding ids), #17 (events, cancellation), #18 (error codes,
fetch then check in one run) and the API pull request (`iemod_fetch.api`).

| # | Item | Size |
|---|---|---|
| 1 | **ADR-0029** accepted: the scope changes (UI yes, installing opt-in later) | S |
| 2 | `iemod_fetch.api`: public functions (`list_mods`, `describe_mod`, `plan`, `check`, `resolve`, `fetch(items, on_event, cancel)`) with `__all__`. `cli.py` becomes a thin user of it, and filesystem reads move out of the core | M |
| 3 | `selection.json` v1 (game, mods, components, language, choices) as an alternative to WeiDU.log; both turn into the same internal objects | M |
| 4 | `iemod-fetch mods --json`: the merged catalogue (manifest + lcc-docs + mod DB) with games, categories, status, safe and sources | S-M |
| 5 | `schema_version`, stable finding ids and JSON Schema files for every JSON output, with tests that validate them | S-M |
| 6 | `--events jsonl`: per-mod and per-chunk progress, plus cancellation through a `threading.Event` | M |
| 7 | Fetch and plan in one run (planning reads what was just staged) | S |
| 8 | A stable `code` on every error, carried on each record | S |

### M2 — Components and choices (v2.4)

*Done on 2026-10-21* in #23-#29 and released as 2.4.0. Beyond the plan: the
engine limits of each install (ADR-0034), measured in the game folder by
WeiDU's own rules after krion64's counts were audited and found to miss
ADD_SPELL.

| # | Item | Size |
|---|---|---|
| 9 | `iemod-fetch describe MOD --json`: components with names resolved through `.tra` for the chosen language, plus SUBCOMPONENT/GROUP/LABEL/DEPRECATED. The `muc`/`sub` vocabulary is taken as an idea from BWS-NG. **Done**: names (`--describe-mods`, 9,889/9,889 against WeiDU 251's `--list-components`) and SUBCOMPONENT, FORCED, GROUP, LABEL, DEPRECATED (1,499/1,499 against its `--list-components-json`) | L |
| 10 | Conflicts as **options** (drop a side, move before or after, each with its cost), and a `decisions.json` input that is applied and re-checked. **Done** (ADR-0033): every finding of the mock EET plan has options, and each applicable one clears it (`tests/test_decisions.py`) | M |
| 11 | Freshness: installed vs latest per mod, from a cached weekly release scan (roadmap E2/E4). **Done**: krion64's daily release cache plus BWS-NG and krion64 versions, the newest of the three (79/90 against tp2 VERSION); `installed`, `latest`, `update_available` in `--list-mods` | M |
| 12 | BIO share-code **import/export** (format only). **Done**: `--bio-code`, `--emit-bio-code`; a BIO-made code round-trips to the same payload byte for byte, and BIO decodes ours | S-M |
| 13 | Read Project Infinity `weidu-log.csv` and krion64 `mod-forge.json`. **Done**: `--pi-list` (LABELs from the tp2s, krion64 as a reported fallback: 708/732 agree) and staged `mod-forge.json` read as rules (none of 103 measured mods ships one yet) | S |

### M3 — The wizard up to download (v3.0) — released in 3.0.0

ADR-0031: `iemod_fetch_gui`, PySide6, importing only `iemod_fetch.api`. The
phases are BWS-NG's order. Each phase saves a file the CLI also reads, so a
run can be stopped and resumed, or finished from the command line.

| # | Phase / item | Size |
|---|---|---|
| 14 | **Done**: `iemod_fetch_gui`, the `gui`/`guitest` extras and the `iemod-fetch-gui` command, two contracts (the tool never imports the GUI; the GUI imports only `api`, with a test keeping the list complete), and a CI job running pytest-qt offscreen on Linux and Windows. Package skeleton: `iemod_fetch_gui`, `[gui]` extra, import-linter contract (core never imports gui; gui imports only `api`), pytest-qt offscreen in CI | M |
| 15 | **Done**: the phase checks the folders as GAME_IS does while they are typed, and Next saves the project's `iemod-fetch.ini`, which the CLI reads. **1. Game and folders**: game type (EET, BGEE, BG2EE), BGEE/BG2EE folders checked with `gamedir`, language | S |
| 16 | **Done** except prompts (ADR-0033/0035/0036): categories, search, filters "chosen only / conflicts only / updates", the mod -> component tree with tri-state boxes and exclusive SUBCOMPONENT choices, a details pane, `selection.json` on Next; components from the staged tp2, else krion64 (1,471/1,529 against WeiDU); a conflicts tab checked in the background with one-click options (deselect, choose a missing prerequisite, accept to `decisions.json`, the ids `--decisions` matches). Drop-downs for prompts move to M4: only BWS-NG describes prompts as data, for 4 components, and a selection carries no answers yet. **2. Mod selection**: category column, search, filters "selected only / conflicts only / updates", mod → component → choice tree with tri-state checkboxes, radio buttons for exclusive groups, drop-downs for prompts, details pane, conflicts panel with one-click options | L |
| 17 | **Done** (ADR-0038): one tab per install - for EET the BG:EE phase and EET, split by krion64's categories in the saved selection too - in the run's planned order; bold where a rule places a mod, red where an order rule still objects, with the rule; drag to reorder, saved as `install-order.txt` (Project Infinity Sorting Order) and named in the project's ini, so the CLI plans the same order (checked by a test). **3. Install order**: one tab per EET phase, drag to reorder, entries the rules place marked (bold, still movable: a move that breaks a rule is shown), violations marked | M |
| 18 | **Done** (ADR-0039): one page, "Download and extraction" - one step per mod in the engine - with a row per mod (downloading, bytes of total, extracting, done, failed, no download found, cancelled), cancel, resume, "Retry the failed"; it runs the CLI's own run in the project (`api.download_selection`), and with no manifest lcc-docs is the download source (138 of 145 mods of the supplied log have a candidate). Phase 5 is now Installation (M4). **4. Download** and **5. Extraction**: progress per mod and in bytes from the event stream, cancel, retry of the failed ones | M |
| 19 | **Done**: *Load preset...* and *Save preset...* on the mod selection page; a preset is a selection.json byte for byte as the project's (a test compares them), and a WeiDU.log, a BIO share code or a Project Infinity list loads too, told apart by what the file holds and matched to the list ignoring case and `setup-`; what the list lacks is named, never guessed (`api.import_selection`, `api.export_selection`). Presets: save and load `selection.json`, import from WeiDU.log, BIO code and PI csv | S |
| 20 | **Done** (ADR-0040): `packaging/gui_bundle.py`, a `gui` job in the release workflow - Linux and Windows; macOS by `release-macos.yml`, attached after the release when its runner starts - one folder (Qt replaceable, LGPL-3.0), started once offscreen with `--check`, zipped deterministically, attested and in SHA256SUMS, with the LGPL/GPL texts and `NOTICE-Qt.txt`; in the 3.0.0 release the Linux zip is 83 MB and the Windows one 48 MB (60 MB measured locally: the runner's PySide6 wheel is bigger). PyInstaller build per OS in the release workflow, attested, with the Qt LGPL notice | M |

### M4 — Backup and installation (v3.x)

| # | Phase / item | Size |
|---|---|---|
| 21 | **Backup and restore in the tool: done** (ADR-0042: `iemod_fetch/backup.py`, `api.backup_game` / `plan_restore` / `restore_backup`, `--backup`, `--verify-backup`, `--restore-backup [--apply]`); the wizard's page is next. **Backup** phase before installing: copy or zip of the game folder's override, dialogs and WeiDU state, with a restore action | M |
| 22 | **Done** (22a, 22b, 22c) (ADR-0045, amends ADR-0022: the owner's decision, the wizard runs mod_installer): `iemod_fetch/install_run.py` starts mod_installer - the scripts' command, after their checks - as a child in a process group of its own, reads its output line by line (`prompts.py`, pure: the batch started, a question once the output goes quiet) and answers WeiDU's questions: EET's BG:EE folder question with that folder, then the planned log's `// @wlb-inputs:` for the batch (BIO's format), then the player; Cancel terminates the whole group, then kills it (WeiDU must not go on writing). `api.start_install`. Tested against a stand-in that prints and asks as mod_installer 16.0.0 does, and against the **real mod_installer 16.0.0 driving the real WeiDU v251** (a test mod asking two questions, answered from the log; in CI's real-weidu job). **22b done** (ADR-0046): mod_installer 16.0.0 is compiled into the wizard's bundle (`packaging/mod_installer.py`; upstream's only release, v12.1.1, stops after the first component on Linux), and `iemod_fetch/toolchain.py` finds it - the player's path, else the bundle's, else PATH; WeiDU likewise, else its official v251 release downloaded on the player's word (sha256 before unpacking, safe extraction, the program's own sha256 checked again at every use, a per-user tools folder). `--download=false` keeps mod_installer from downloading a missing mod itself. Measured on CI's Windows runner: a folder answer reaches the real WeiDU even outside the ANSI code page ("Игры ゲーム"), so #83's refusal is lifted. Review of #86: PATH lookups skip the current folder (Windows' `shutil.which` tries it first), mod_installer gets none of its 29 option variables from the player's environment, and a silent WeiDU on Apple silicon names Rosetta 2. **22c done**: phase 5, `iemod_fetch_gui/pages/install.py` - the programs (problems in their own words; a program chosen by hand; WeiDU downloaded only after a confirmation naming its URL, version and licence), a backup of each game folder before *Install* is offered, then a last confirmation; the phase-3 order is written to `PROJECT/install-plan/` (`api.write_install_plan`, the same plan the order page shows, with the project's languages) and `api.start_install` runs in a worker thread: output live, a question asked in a dialog (Cancel there stops it), *Cancel* any time, the outcome and how to start again (the backup). Back is locked while a backup, download or install runs. Review of #87: a backup counts only if it is of that folder and restoring it would change nothing (`plan_restore`, checked in a thread); the plan is written from the selection at that moment, then the confirmation names what the order still breaks (*Install anyway*). Tested with pytest-qt against the stand-in mod_installer through the real `start_install`, and the backup check against a real backup and a changed game file. Original ask: drives mod_installer (EET mode) or WeiDU directly, streams the output into the window, recognises prompts and answers them only from a recorded answer file (`@wlb-inputs` style); otherwise it asks the player | L |
| 23 | **Done** (ADR-0045, item 23): `iemod_fetch/resume.py` (pure) reads each game's WeiDU.log against its planned log - resumed when it is the plan's beginning (tp2 path, language and component, in order), refused otherwise with each diverging line named, and refused when the next component was stopped half-way (its WeiDU uninstall record in the game: measured, WeiDU would back up the leftovers as the originals) - and `api.start_install(resume=True)` hands mod_installer only the rest (`install-plan/resume/`); EET: BG:EE unfinished - the eet run with its rest and the whole EET log; finished - the EET game alone, as a normal install. mod_installer runs with `--skip-installed=false`: 16.0.0 reads `weidu.log` in lower case, and on Linux reinstalled the first component (measured). `api.install_progress` says where it stands; the wizard shows "N of M components are in, next X", resumes on *Install*, and keeps the backup from before the stopped install. Tested on the stand-in mod_installer (EET both ways) and the real mod_installer and WeiDU (only the rest installed; a Cancel inside a component refused; a WeiDU failure undone and resumed). Original ask: resume after a failure or cancel; the WeiDU.log is the state | M |
| 24 | A real Windows end-to-end CI job (roadmap F) and live GitHub API contract tests (item A) | M |

Infinity Mod Runner (MIT) has solved most of M4 in a shipped installer, and
is the reference to measure against before each item is designed: per-game
backups with a verify step (21); per-batch Retry / Skip / Stop, checkpoints,
pause and resume, EET's two phases, per-mod timeouts (22, 23); a
reconciliation of WeiDU's exit code with WeiDU.log after every batch that
catches components that "succeeded" without being logged; READLN default
answers kept as configuration; and the File Guard above. Its ideas, and its
MIT data with attribution, may be used; its code is Rust and TypeScript and
is not copied into a Python project.

### M5 — The order and the selection by kind of mod (after 3.0.0)

Asked for on 2026-10-23: use the generic kind of each mod (interface,
graphics, portraits and sound, quests, NPCs and banter, items and spells,
kits, AI and tactics, tweaks, maps, after EET_end...) in the selection and in
the order, as Project Infinity, krion64 and BWS-NG classify them, with the
exceptions where one component must go elsewhere.

What exists in 3.0.0: the order **is** already by kind where krion64 knows
the mod - its 26 categories, in install order (`PRE EET BGEE MODS`, `ENGINE`,
`INTERFACE`, `GRAPHICS`, ... `TACTICAL MODS`, `PORTRAITS`, `EET FINALIZATION`,
`POST EET`), with its position inside the category, and a mod split where
krion64 files one component elsewhere (ADR-0038). Rules then move it: BWS-NG's,
the authors' metadata inis, the player's Sorting Order. Measured gaps:

- krion64 places 813 mods; lcc-docs lists 1,148 for the EE games (2,151 in
  all). A mod krion64 does not know keeps the place of the mod before it in
  the input - from the wizard, a place that depends on the selection's order,
  not on what the mod is.
- lcc-docs has its own 17 categories (Gameplay 403, Kit 262, recruitable NPC
  232, spells and items 225, quest 225, portrait and sound 172, ...) and the
  selection page filters by them; they are not install phases and are not
  mapped to krion64's.
- BWS-NG's and Project Infinity's classifications are not read yet; their
  shape has to be measured first (the session sandbox cannot reach them; a
  workflow can).
- **Infinity Mod Runner** (Anprionsa, MIT, a Tauri/Rust installer, beta
  1.0.2, "1,675 components installed in 12.2 h") and the **Infinity Mod
  Forge** it reads. **krion64's site is the Infinity Mod Forge** (its README:
  "Infinity Mod Forge", formerly "EET Mod Forge"), the data this tool has
  read since M2. The Runner's default address for it,
  `anprionsa.github.io/infinity-mod-forge`, answers GitHub Pages' "Site not
  found" (checked 2026-10-23); the live Forge is `krion64.github.io`. One
  source, counted once; the Runner adds no classification of its own.

| # | Item | Size |
|---|---|---|
| 25 | **Done** (ADR-0041, `tools/order_sources_benchmark.py`): measured on the real files - krion64 is the Forge; BWS-NG's per-component EET sequence (3,232 components) is the second order, disagreeing with krion64 on 21% of pairs and placing 26 mods krion64 does not; lcc-docs classifies 546 EE mods krion64 does not place; the supplied log is the Forge's output. **Audit, measured on GitHub's runners**: every source's classification (krion64's (the Infinity Mod Forge's) categories and per-component `c`, lcc-docs' categories, BWS-NG's, Project Infinity's), how many mods each covers, a mapping from each to krion64's install phases, and where they disagree. On the supplied 145-mod EET log: how many mods have no krion64 place, and how far the order by kind is from the order the player actually installed. ADR-0041 decides from these numbers. | M |
| 26 | **Done**: `iemod_fetch/kinds.py` maps lcc-docs' French labels and BWS-NG's codes onto one vocabulary; `--list-mods` carries `kinds`, `kinds_by_source`, `kind_disagreement`, and krion64's `install_category` and `tags` beside them (never mapped). Phase 2 lists kinds down the left, has a "Kind" column (marked where sources disagree, which source says what in its tooltip and the details), and a "Kinds disagree" filter. Measured on the 2026-10-23 data: 1,843 mods with a kind, 1 disagreement (turnabout). **Selection by kind**: one "kind" filter and column in phase 2, from the mapping, each mod showing which source says what; a disagreement is shown, never settled silently. | M |
| 27 | **Done** (ADR-0041): `kinds.place` maps a kind to a krion64 category only where it decides (interface, cosmetic, kit, recruitable and one-day NPC, smith; quests by their games), every kind of the mod agreeing; the mod goes after krion64's own mods there - a preference under the player's Sorting Order, the authors' inis and BWS-NG's rules - in any install but the BG:EE phase before an EET conversion. A mod with no place keeps where it was chosen, even behind one its kind moved. The plan summary, `api.selection_plan` (`placed_by`, `no_place`, carried to every part of a split mod) and the order page ("(by kind)", the source in the tooltip; superseded when the player's own order applies; counted once per mod) say it. Measured: of the 1,071 mods with a kind that krion64 does not place, 451 get a place - 15 by BWS-NG's sequence, 436 by kind, once 2a came first - and 620 say why not (a mod no source classifies says nothing); on the 397 krion64 places, the kind agrees for 351 (88%). **Decision 2a done too**: before the kind, BWS-NG's EET sequence (`games/eet.json`, bg2ee) places such a mod after the nearest component before it that krion64 places (`ordering.bws_sequence`, `_place_by_sequence`) - a neighbour counting only in its mod's first run, the one after asked too, nothing placed from before the EET core; "(by BWS-NG)" on the order page, its own section in the summary, `placed_from` in the JSON. Measured on BWS-NG's ids: of the 26 mods after the core krion64 does not place, 16 by the sequence, 3 by kind (neighbours disagree), 7 say why not; where a kind would also place one (9), they agree on 8. | M |
| 28 | **Done as measured** (ADR-0033 amended): (a) the per-component split by krion64's `co[].cat` already places 242 components apart (6 mods, 12 parts on the 146-mod log); BWS-NG has no kind per component - its per-component data is the EET sequence, item 27's 2a. (b) A conflict graded below `error` now offers "keep both, X installed last" each way round (`conflicts.KEEP_BOTH`); chosen, it becomes an order rule of the plan (`resolution.keep_both_rules`, `api._plan_with_decided_order`), on the command line and in the wizard, and the finding is accepted with that reason; a contradiction with another rule is reported, never hidden. (c) File Guard is M4's. **Exceptions per component**: a component whose kind differs from its mod's (a tweak pack's portraits, a tactical mod's kits, what goes after EET_end) is split and placed by its own kind, from krion64's and BWS-NG's per-component data; two chosen components known to overwrite the same thing (BWS-NG and krion64 conflict records, `mod-forge.json`) are reported with their order as an option, as conflicts are today. Static analysis of what a tp2 copies is not promised: WeiDU's language can compute any path. What can be measured is what an install really overwrote: Infinity Mod Runner's *File Guard* snapshots the override folder's md5s after each batch and flags a change outside an allowlist of files several mods legitimately write (`guard_allowlist.json`); the same check belongs to M4's installation, and its findings feed this item. | L |
| 29 | **Done**: `tools/places_check.py`, nightly in the community-data workflow on the live data (and on a pull request touching `kinds.py` or the tool), fails on a category `kinds.py` does not map, a krion64 category a kind places into gone, an `eet.json` that lost its bg2ee sequence, or a count under its floor (mutations of the real data: krion64 renaming QUEST MODS BG2, lcc-docs renaming its `categories` key - both caught), and prints what places the 1,071 mods with a kind krion64 does not place (15 by sequence, 436 by kind, 620 none); against BWS-NG's sequence the 146-mod log's plan orders 9,380 of 123,753 pairs the other way round (7.6%), the same with and without the places - the log is the Forge's, and the check says so. The mock EET job installs a plan reordered by kind with the real WeiDU. Fixtures in BWS-NG's shape are made up (GPL, not bundled). | M |

### M5b — Editing the order by component (asked for on 2026-10-23)

The player chooses and drops parts of mods, reorders by hand, and the tool
checks the order again and offers fixes. Measured against BWS-NG (GPL, ideas
only), Infinity Mod Runner (MIT) and Project Infinity (docs and wiki) on their
real code: BWS-NG is the reference for component-level ordering (one row per
component, incremental re-check of only the rules a move touches, a per-row
violation panel, "ignore" that comes back on a new break); Infinity Mod
Runner only runs an order made elsewhere; Project Infinity orders mods, and
components through its Sorting Order file. **None of the three re-sorts or
offers a fix after a manual move**; this tool's planner already computes the
smallest moves, so it can.

| # | Item | Size |
|---|---|---|
| 30 | **Done**: *Split into components* on the order page turns the selected mod into one row per component; the order is saved with `tp2 n` lines and planned again, and the planner splits the mod where the lines name its components. *Join the parts* undoes one split, keeping the other moves; split and join wait while a plan is under way, and the split rows are in the list before they are saved, so a drag meanwhile keeps them (review of #74). A part is marked moved or wrong on its own, not the whole mod. Test on the real path: the run's planner, Split on eefixpack, #1 dragged after the EET core, then `--plan-order` - row for row (`test_split_and_drag_on_the_real_planner_agree_with_the_command_line`). **Left**: a part dragged above the EET core, or before an earlier component of its own mod, is not warned about before the download (it shows once planned). **Split a mod and move one component** on the order page (expand a mod into its components); saved as Sorting Order `tp2 n n` lines, which the CLI already reads. Test: the GUI order and `--plan-order` agree after a split and a move. | M |
| 31 | **Done**: a drop marks at once the rules it breaks - only those the moved row is in are checked again (`ordering.broken_after_move`, from the plan's own rule edges, `after` per unit in `api.selection_plan`), only the rows whose mark changes are painted; the full plan follows in the background and replaces the marks; a drop right after a split or a join, whose parts still share the mod's node, is left to the plan ("Checked when the plan comes back."). A hypothesis property test: after random orders, rules and moves, the incremental answer always equals the full check (`tests/test_properties.py`; dropping either half of it fails); `tests/test_selection_plan.py` checks the real planner hands each unit its `after`. Measured (`tools/order_check_benchmark.py`, 2026-10-23): the check after a drop, p50/p95, 0.015/0.026 ms on the 146-mod log (152 units, 157 rule edges) and 0.26/0.45 ms on a synthetic 3,000-unit order (4,507 edges), against 0.8/1.4 ms for the full check; the order page to its marks, 3,000 rows offscreen, 3.7/7.1 ms. **Incremental check after a drop** (BWS-NG's technique: re-check only the rules touching what moved, at once; the full re-plan stays in the background). Measured: time to the marks after a drop, p50/p95, on the 146-mod / 780-component log and on a synthetic 3,000-component order; a property test that the incremental result always equals the full check. | M |
| 32 | **Done**: "Fix..." on a red row of the order page - "move it just after X" (the last unit a rule puts before it, if below it), "just before Y" (the first a rule puts after it, if above it), "plan it again by the rules, keeping your other moves" (its line left out of `install-order.txt`, offered when the order is the player's), "turn it off" (its components unticked on the mods page). Each is previewed: the moves at once against the plan's rule edges (`ordering.order_fixes`), the other two by the real planner in the background on a hand order or selection written to a temporary file (`api.preview_install_order`, which adds the blocking findings that are not about order). Only a fix that mends its rule, breaks no other and adds no error is applied; the preview names what it would break. Tests: a hypothesis property test - every offered move mends a pair and the pairs left are a strict subset, other rows untouched (`tests/test_properties.py`); the preview equals the plan and writes nothing, and dropping a component another needs shows that one new error (`tests/test_order_fixes.py`); each fix driven on the page, and one that adds an error, breaks another rule or leaves the row red not applied (`tests/gui/test_order.py`). Left: the preview of a turn-off judges the selection's rules, not what the mods page would untick with it (item 34). | M |
| 33 | **Done**: under the order list, the selected row's panel lists every order rule on it (not the player's own order) - "must come after / before X", the rule as written, its source and severity - red where it is broken now, dimmed where it names a whole mod rather than components (`OrderPlan.edge_rules`, `selection_plan`'s `rules` and `broken` per unit). **Ignore...** asks why and keeps the row's broken rules as the player's call in `decisions.json`'s new `ignored_order` (ADR-0033 amendment: an `accept` cannot hold it, a rule broken only by the hand order has no finding). An ignored row is grey with its reason while it stays just after the same row and breaks nothing new; dragging it forgets the ignore, and a rule it newly breaks shows it red again; "Stop ignoring" removes it. The command line checks the key and does nothing else with it. Tests: the format and its schema, `holds` (`tests/test_decisions.py`); the real planner's rules, an ignore in another place or with a new broken rule not holding (`tests/test_selection_plan.py`); the panel, ignore, drag and stop on the real planner (`tests/gui/test_order.py`); 7 mutations caught. | S |
| 34 | **Done**: unticking a component that chosen ones need asks first - *untick those too* (and what needs them, transitively), *keep it*, or *untick it alone*; a mod unticked whole asks once. "Need" is the mod's own `requires` and every dependency rule the last check found satisfied (`selection_conflicts`' new `needs`: the dependent's chosen pairs and each alternative's), so a component another alternative still covers asks nothing. **Resolve for this component** (BWS-NG's auto-resolve, narrower): first its missing prerequisites - the finding's install option, one alternative of an "any one of", never every target as BWS-NG does - then *keep this* against the **error** incompatibilities naming it, deselecting their other side; a warning is left to the player (ADR-0033: never auto-resolved). What it would do is shown and done only on OK. A deselect the player chose on the conflicts panel or the order page is not asked about again; what it breaks is the next check's finding. Tests: `needs` on the mock and with an "any one of" rule (`tests/test_selection_conflicts.py`); the guard, transitivity, a cycle of `requires`, alternatives, a whole mod, the real `selection_conflicts` on the mock install, and resolve with an error, a warning and nothing to do (`tests/gui/test_mods.py`). **Left**: a prerequisite chosen by Resolve may need others in turn; the next check shows them, a second Resolve chooses them. | M |
| 35 | **Done**: the order page selects several rows (Shift, Ctrl) and drags them together - a block dropped is checked at once row by row; **Ctrl+Up / Ctrl+Down** move the selected rows one place, saved and planned once; **Find** selects the rows of the tab shown that match, ready to move. On the mods page a mod ticked whole takes one option per SUBCOMPONENT group - the one already chosen, else the group's first; measured before, Qt's cascade left the *last* (the mod's row now settles the cascade once it ends); unticking the only option of a **FORCED_SUBCOMPONENT** group while the tp2 keeps other components puts it back and says why, and the group goes with its mod. `api.selection_digest` (game, chosen, labels, the project's ini / install-order.txt / decisions.json, the data cache's `sources.json` and `mod-metadata.json`, and the mods staged in the target folder two levels deep - their tp2s and own inis (review of #82) - by size and time): the conflicts check is not run again, nor the order planned again on coming back, when it has not changed. Tests: each part on the page, the digest on its own (`tests/test_selection_plan.py`); 9 mutations caught. | M |

### M6 — One Python, and the libraries that earn their place (4.0.0; ADR-0043)

Decided by the owner on 2026-10-23: one Python version for everything,
chosen the way Debian chooses a kernel. Audited twice, on PyPI's metadata and
by running the candidates.

| # | Item | Size |
|---|---|---|
| 36 | **Done** (`.python-version`, the workflows, pyproject, `iemod_fetch.PYTHON`; the CLI bundle: `packaging/cli_bundle.py`, built and run once unzipped on Linux (Ubuntu 24.04, glibc 2.41 at most, then run in `debian:trixie` - until 2026-10-31 Ubuntu 22.04, 2.35 and `debian:12`), Windows and macOS in the release workflows; programs it starts get the system's library path, `childenv.py`; review of #70). **The platform**: `.python-version` (3.14) read by every workflow instead of 20 literal versions in 10 workflows, two test matrices and four settings in `pyproject.toml`; `requires-python = ">=3.14"`; ruff, mypy and the classifiers on it; tests on it, on Linux and Windows (macOS informational). The CLI also ships as a PyInstaller bundle beside the wizard, so a player needs no Python of their own. Breaking: 4.0.0, with a migration note. | M |
| 37 | **Done** (`tools/upstream_versions.py`). **The weekly check** (ADR-0028's `upstream-versions.yml`): the newest stable from actions/python-versions' manifest, and every place that names the version compared; an issue when they disagree or a newer Python is out, and the move made by hand once a full build - wizard and CLI bundles, all tests - passes on the newer one (a pull request opened by a workflow's token would start no CI to prove it). Dependabot cannot do it (verified in dependabot-core: it never touches `python-version`). Next candidate: 3.15, after its build is green - it makes UTF-8 the default on Windows (PEP 686). | S |
| 38 | **Done**. **Mechanical modernisation**, alone in its PR: ruff `UP` rewrites about 890 `Optional`/`List`/... annotations (522 UP006 and 371 UP045 at py314) and 140 typing imports; `hashlib.file_digest`; `datetime.fromisoformat`; tarfile's data filter without the fallback; `PySide6>=6.11`. | S |
| 39 | **Done.** publicsuffixlist (net.py) and filelock 4.2.4 (datasync.py; 3.32.7 until CVE-2026-112940, see the ADR-0043 amendment of the same day: the measured defect was two refreshes sharing `<source>.new` - one failed, the manifest saved last forgot the other's update; `tests/test_datalock.py`: two threads on one folder fail before; a second process holding the lock checks that `--update-data` waits, an ordinary run does not, and fresh data needs no lock - review of #66), both carried in the .pyz and the bundles and pinned in `requirements/runtime.txt`; ADR-0043 amendments. **Libraries adopted**, each with a test that fails before it, pinned by hash, scanned by pip-audit: **filelock** (MIT: a lock around the shared data folder, which the GUI and the CLI both write) and **publicsuffixlist** (MPL-2.0, unmodified, licence shipped: `a.github.io` and `b.github.io` are different sites, which the offsite check gets wrong today). **urllib3** only if keep-alive is measured to matter. | M |
| 40 | **Done** (ADR-0047). Measured first (`tools/rar_measure.py`, the `RAR extractors` workflow; 105 RAR archives of lcc-docs): libarchive opened 95 on Debian trixie, Windows and macOS alike, Homebrew's unar 103, trixie's unar 94 (no RAR5), Debian's 7zip 1 (the dfsg build, no RAR code). So nothing is bundled: `.rar` goes to bsdtar (Windows' own `tar.exe`), then unar, then the player's own 7-Zip or WinRAR - used when installed, never shipped (the unRAR licence is not open source). Each tool extracts into a folder of its own: before, Debian's 7z wrote every file wrong and unar extracted over it, and the result was reported as extracted. Two solid RAR4 archives (027, 030) no open-source tool opens. | S |

Rejected, with the measurement: charset-normalizer (it reads short Cyrillic
`.tra` text as cp1125 and Western text as big5), tenacity and requests-cache
(neither fixes our retry or caching gaps), packaging (mod versions are not
PEP 440), rapidfuzz (difflib is enough), tldextract, vdf, atomicwrites,
keyring, py7zr (LGPL, compiled dependencies, no RAR).

### M7 — Defects the audits found, fixed in the standard library (except the offsite check: publicsuffixlist, item 39)

| # | Defect, reproduced | Fix |
|---|---|---|
| 41 | **Done** (item 39). **Security**: `same_site("https://modder.github.io/m/", "https://attacker.github.io/x.zip")` is true (`registrable_suffix` reduces both to `github.io`), so a link to another user's page escapes the offsite gate. | item 39 |
| 42 | **Done**. **Order**: a stuck sort reports every remaining unit as the cycle and forces the top one even outside it; with A<->B, "C after A" is broken. Measured on the old code with units C, D, A, B (in that priority): the order came out C, D, A, B - C and D both ahead of A - and two cycles were reported, all four units and then A, B. Now: the real cycle (a strongly connected component nothing outside it holds back, Tarjan's algorithm) is reported once, and the unit released is taken from inside it. `graphlib` was not used: `TopologicalSorter` stops at the first cycle (`CycleError`) and cannot release a unit or keep the priority order the plan needs | the real cycle, released from inside it; each cycle reported once; rules outside it hold (3 tests, each failing before) |
| 43 | **Done**. **tp2**: `~Use "smart" AI~` is read as `Use `; `~~~~~` strings are not read. Measured further on the 119 tp2s of 103 real mods: `parse_tp2`'s LANGUAGE regex took code (`iconv_path =`, `reload_array = ... LANGUAGE`) for declarations and lost bare directories (SCS's `ENGLISH`); 12 lists disagreed with WeiDU 251's `--list-languages`, and 11 mods got a wrong WeiDU language number for at least one of 8 common languages. | `tra.py`'s scanner moved to `weidu_lex.py` and used by `parse_tp2` for LANGUAGE and VERSION; the other strings close on their own mark. Measured: 119 of 119 agree with `--list-languages` (107 before); a keyword is a word of code, not a line start or a word in a string (review of #57); 7 tests |
| 44 | **Done**. **.tra**: non-UTF-8 Russian, Polish, Japanese and Chinese text decoded as cp1252 (or latin-1), silently. Measured on 103 real mods: 2,286 Russian, 721 Simplified Chinese and 767 Polish/Czech .tra files are not UTF-8. | after UTF-8, the code page of the language folder, by WeiDU 251's infer_charsets table (`weidu_lex.legacy_charset`); measured, all 2,286 and 721 then decode to Cyrillic and CJK (0 before); the innermost language folder decides, cp1252 languages included, so `prussian_guard/english/` stays English (review of #58); 21 tests |
| 45 | **Done**. **GitHub**: a 403 secondary limit is not retried; an HTTP-date `Retry-After` is ignored; no ETag, so repeat runs spend the rate limit. | Done: a 403/429 from GitHub that says it is the secondary limit (Retry-After, or its words in the body) is waited out as GitHub's REST docs say (Retry-After, else 60 s then doubling, capped at 300 s); `email.utils` reads an HTTP-date Retry-After; the waits end on Cancel, a Retry-After over 300 s stops rather than retrying early, a 429 with the quota spent is not retried (review of #61); 12 tests. Part 2: `iemod_fetch/etagcache.py` keeps GitHub API answers with their ETag in `<data dir>-http`; `get_json` asks with If-None-Match and a 304 reuses the kept body. Measured on GitHub: X-RateLimit-Remaining 14985 -> 14984 for a 200, unchanged for the 304 (authorized; unauthorized 304s still count, per GitHub's docs - not measurable here, the sandbox proxy authorizes); a git tree named by its commit is not kept, so the folder does not grow by a whole tree per upstream commit (review of #64); 12 tests |
| 46 | **Done**. Nine hand-written atomic writes: seven with one fixed temp name, two with an fsync. Counted again: eight file writes (seven `<file>.tmp`, the config with `mkstemp`) and one fsync, the install state's; the ninth was the download's `.part`, which streams, resumes and fsyncs on its own and stays. | one helper, `iemod_fetch/atomic.py`: a temp of its own per write, removed on failure, mode kept; the review of #55 added the `--conflict-report` writer, which was not atomic at all. **Left**: a temp left by a power cut now has a name of its own, so such leftovers are not overwritten by the next write; nothing sweeps them yet. 8 tests |
| 54 | **Done** (one turn per source - a source, not the URL it resolves to: a review of #52 found a link signing a new URL on each probe downloaded forever). **Catalogue fallback**: with the catalogue alone (`-m ''`, ADR-0039) and GitHub out of reach, the Beamdog threads lcc-docs lists gave 8 of the 145 mods of the supplied EET log a file that is not the mod: a save game (Foundling), two `.debug` logs (ntotsc), a compatibility patch (IHateUndead), another mod (A7-GolemConstruction ships SoDGolemFix). The .tp2 check refused each one, and the retry probed the catalogue again and got the same file, so the author's page the same entry lists was never tried. (First recorded as lcc-docs' own direct links; none of these files is in lcc-docs - the threads are.) | every source of the entry gets its turn, each downloaded once, the same check on each. Measured: 2 of the 8 now install (Foundling, GAHESH from WeaselMods); the other 6 go to their repository, whose tree has the right tp2 (`git ls-tree`), not measured through the API |
| 55 | **Done.** **baldurs-gate.de**: a XenForo resource's `/download` answers 301 to `github.com/<owner>/<repo>/releases`, an HTML page, so 5 mods (AC_QUEST, bgqe, c#solaufein, JA#BGT_AdvPack, c#brage) fail "did not return an archive" or 403. | a landing page or a download that ends on a GitHub repository's page hands that repository to the GitHub resolver - named by the author's site, not guessed - once, with the same tp2 check (`Resolution.github`, `NotAnArchive.final_url`). Tested offline on both paths (manifest `/download`, catalogue resource page); the real redirect, measured as a 301 with its `Location`, ends in the audit sandbox's 403 for GitHub, so the take is to be measured where GitHub is reachable |
| 56 | **Withdrawn: not lcc-docs data.** Dark Tidings' dead `.rar` (`baldurs-gate.de/acifer/Dark_Tidings.rar`, 404) was scraped from a baldurs-gate.de thread (`index.php?threads/45508/`), ArtisansKitpack's `.rar` holding one `HIT_07.wav` from a Beamdog thread; neither is in lcc-docs' `mods.json`. | a XenForo thread is now told as a forum post (`index.php?threads/`), so it comes last (item 58); nothing to report upstream |
| 57 | **Measured where GitHub answers; Cloudflare's three sites from a workstation.** The audit's sandbox refused third-party GitHub repositories and Cloudflare challenges Gibberlings3, SHS and Nexus from any datacenter. The download-sources workflow, on GitHub's runners with a token (2026-10-23): with the catalogue alone 135 of 145 planned (86 release assets, 28 source snapshots, 20 page links, 1 direct), 139 with the manifest; 20 real downloads, 16 installed with their tp2 and 4 over the 300 MB cap (BGGO 1.4 GB, Autumn's Twilight, Classic Movies, Aura) - no wrong archive; the misses are the three Cloudflare sites and mods no source lists. premeta's live check (mod-metadata workflow): all 5 cases as expected. | the workflow takes `real=all` by hand (every planned mod, not 20) and its summary says what the player was told (forum-post copies, newer releases offered, links that led to GitHub); `tools/measure_workstation.py` runs the same steps from a home connection, Gibberlings3 and SHS included, into one folder with `summary.md` to paste back. **Measured** (the owner's `real=all` run, 2026-10-23, run 39963699443): of 135 planned, 124 installed with their tp2, 9 over the 300 MB cap, 2 failed with no tp2 in the archive (item 60); 5 newer releases offered, 2 of them wrong and fixed (item 59: a GitHub snapshot; the same number with a word added - `v04ru`, RoxanneSHS's suffix for The-Rune); no forum-post copy and no GitHub redirect taken - with GitHub reachable neither path is needed for this log. **Left**: the workstation run (Gibberlings3, SHS, Nexus) |
| 58 | **Done.** **A forum's file, silently old**: real downloads of all 145 mods (7-Zip and unar installed) with GitHub out of reach installed Ascension from a Beamdog thread as v1.5 BETA (its repository: 2.1.0) and Finch as v4.0 (v6.0), with nothing to say so - the tp2 check cannot tell an old copy from a new one. Without a token, 115 GitHub mods exceed the 60 requests an hour, so a player can meet this. | a forum thread or attachment (`urls.is_forum_post`) is tried after the entry's direct links, repository and other pages, and installing from one adds an advisory with the post and the declared version (ADR-0039 amendment, the owner's decision). Measured: both now carry it |
| 59 | **Done.** **A newer release, offered**: a copy from anywhere but GitHub (a forum post, an author's site) said nothing when its repository had a newer release - Ascension v1.5 BETA against 2.1.0. | the run compares the copy's tp2 VERSION with krion64's latest release of the repository called like the mod (`compare_published`; nothing when unrankable, never a fork's), puts it in the record as `newer` and beside the mod, and `--take-newer FOLDER`/`all` installs that release over the copy (kept in `.backup/`), or leaves the copy if GitHub cannot give it. Measured: Ascension offered 2.1.0 (Gibberlings3/Ascension), finchnpc nothing (its only scanned repository, RoxanneSHS/Finch, is not named like the mod). Follow-ups of #52's review: a plain newer release only (`versions.newer_release`: no rc/beta over a stable copy, no date-like tag over a version), the exact repository name first, its spelling kept, GAME_IS read on a take; a dotless tag whose readings disagree (`V19` against `2.0`) is not offered. The wizard's download page shows each offer under "Newer release" with a box; "Install the ticked newer releases" runs `api.download_selection(take_newer=...)` for the ticked mods only (each record now carries `newer`) |
| 60 | **Two release archives without a tp2** (real=all run): impasylum (Spellhold-Studios/Improved-Asylum, whose tree has `impasylum/setup-impasylum.tp2`) and Romance_Expanded (Otherwisely/BG2-Romance-Expanded, whose tree has no tp2 at all) - the archive the release gives is not the WeiDU package. The tp2 check refused both, as it must. | **Open**: look at the two releases' assets (the audit sandbox cannot reach GitHub's pages) and pin the right asset in the manifest, or teach the resolver what they ship. Until then both fail with no tp2 in the archive, as they must |
| 61 | **Done** (ADR-0058). **What the bundles still lacked** (reviews of #70). *2026-10-31 (ADR-0043 amendment):* both Linux zips built on `ubuntu-24.04`, held to Debian trixie's glibc 2.41 and started inside `debian:trixie`. *2026-11-01 (ADR-0058):* on Windows a child the bundle starts no longer inherits its DLL folder - `childenv.popen`/`run` clear PyInstaller's `SetDllDirectoryW` under one lock while the child is created and put it back, measured by a PyInstaller probe in cli_bundle.py on Windows and a unit test; GNU Readline (GPL-3.0) is excluded from both bundles; every library a Linux bundle takes from the build system ships with its Debian/Ubuntu package's copyright file, the common licences those files name (`licenses/system/common-licenses/`) and the address of that exact version's source (NOTICE-system-libraries.txt), and a library with no owning package, a named licence with no text or a Linux build with no dpkg stops the build; the wizard carries Python's LICENSE.txt too. Read from the 4.1.0 zips: the Linux CLI had 11 system libraries and the wizard about 90 (GTK 3 among them, through Qt's gtk3 theme), none with a text. **Left**: whether to drop Qt's gtk3 platform theme (and GTK with it) is the owner's call; the macOS zip's system libraries were not measured | `SetDllDirectoryW(None)` before starting a child on Windows, tested on Windows; the third-party texts in both bundles |

### M8 — What the other projects do and this tool does not (feature audit)

Read on their code and data (Infinity Mod Runner, the Forge, BWS-NG, Project
Infinity; Chriz Easy BG for items 62-71). Ranked by value to a player
installing a large EET setup.

| # | Item | From | Size |
|---|---|---|---|
| 47 | **Known-issue classifier** for install output: the Forge's 37 general patterns and per-mod `ki` matched against WeiDU's output and WSETUP.DEBUG (today only their descriptions are shown, before installing). Measured on a labelled corpus. | IMR, Forge (MIT) | M |
| 48 | **In progress** (ADR-0049): `iemod_fetch/readln.py` reads every READLN a component reaches, keyed by its .tra string, its text in the project's language; measured on 105 mods, 88% reached, the question known for 93% of those - 25 .tra strings, 17 fixed texts (`tools/readln_census.py`). Recorded-answer coverage: `api.install_questions` (per component none / answered / maybe / partial / unanswered / unknown, and an unattended forecast); the questionnaire before Install (phase 5) puts every question that can be answered beforehand to the player in one window, keeps the answers in `install-answers.json` by question key and writes them into the planned logs (`api.write_install_answers`); the confirmation lists the components that may still ask. Measured: only 3 of the corpus' asking questions are answerable by their place in the log (most sit under a condition), so during the install a question is recognised by its expected text and answered by its key (`prompts.match_question`, measured with the real mod_installer), and the window offers every question whose text is known. mod_installer only asks questions with its choice words: 11 of the corpus' 42 known questions have none and would wait for its 3-hour timeout (a parser config could add them). Left: the Forge's manual-step notes, the questions mod_installer does not ask (a parser config), the watchdog's threshold from real installs' silences (built, provisional 10 minutes; each run records them in results.json). **Prompts known before installing**: every `ACTION_READLN` in the staged tp2s plus the Forge's manual-step notes, and whether an answer is recorded. Never IMR's "answer 1 after 30 s" (ADR-0005). | IMR | S |
| 49 | **Done** (ADR-0055): **preflight warnings**. `api.install_readiness(games, mods_dir, weidu, backups_dir)` warns and never refuses, about three things. The backup's room is exact: `backup.size`, what `create()` copies, against the free space where backups go. The install's room on each game's drive is an upper estimate, said as one: the staged mods plus what a backup copies. WeiDU's `--version` is checked against the one this program is tested with (25100) and against the highest `WEIDU_VER >= N` in a staged tp2, tpa or tph. There is no change to `install_run.preflight`; the install page reads them on the plan's worker thread and lists them in the confirmation, under "Before installing, check" (the backup's room is not asked there: the page makes the backups first). Known limits: the estimate covers the whole plan also on a resume, and the whole download folder, unselected mods included. Not measured: how many mods test `WEIDU_VER` (no unpacked corpus here). | IMR, BWS-NG | S |
| 50 | **Done, compatibilities not shown beside it** (ADR-0044 amendment; lcc-docs' `requires`/`conflicts` are already rules). **Update signal from lcc-docs' dates**: between 30 and 55 of the supplied 149 mods, depending on how they are matched, have no GitHub release krion64 can see, only an lcc-docs date. Now a copy this tool fetched before lcc-docs' date is "maybe updated" in the wizard's mod selection (version column, a "Maybe updated" filter, the details with both dates and the page) - never "update available". The copy's day is install.State's `installed_at`, not the tp2's mtime: measured, a zip unpacks with today's date and a tar with the archive's; compared by day; no record, no mark; a record counts only while its folder is there and its tp2 VERSION unchanged (review of #122). Not measured: how many of the 30-55 a real project marks (needs its fetched copies) | lcc-docs | S |
| 51 | **Done** (ADR-0059). Release notes and activity (`body`, `pushed`, `archived`) and krion64's notes (`no`, `rq`, `ic`, `eet_compat`) in the mod's details in the selection, as escaped text cut to a fixed length - never a link or markup - each line naming krion64 and the day of its data ("according to krion64, data of ..."). On the local data: 502 of 1,045 mods with what the scan saw of their repository (456 with notes, 7 archived), 689 with krion64's notes. **Left out, measured rare**: `in` (17 of 814 records) and `rec` (10) | Forge | S |
| 52 | An opt-in set of community patches for known mod bugs (IMR's 62, idempotent), with sha256 before and after; needs its own ADR - it changes mod content. | IMR (MIT data) | M |
| 53 | `AT_EXIT` scripts kept beside a mod's folder (to be checked first); install-time estimate and slow-component notice; a post-install report and a diagnostic bundle with paths removed; a translated wizard. | IMR, BWS-NG | M |
| 62 | **Withdrawn: measured, the ceilings already let them through** (2026-10-31). The proposal took a 300 MB default for `--max-bytes`; that was one measuring run's setting (item 57), the default is 2 GiB (`net.DEFAULT_MAX_BYTES`). The unpacked ceiling is 2 GiB too (`archives.MAX_TOTAL_BYTES`), with a ratio guard over 200:1 on members above 8 MiB. Read from the zips' central directories by HTTP Range requests (100-540 KB fetched each, nothing extracted): BGEE Graphics Enhanced 0.2.0, 1,864,005,883 bytes, 927 entries, unpacks to 1.744 GiB; BGGO 3.5, 1,386,261,605 bytes, unpacks to 1.366 GiB; BGGO 3.6, 1,459,899,654 bytes, 1.457 GiB. No member trips the ratio guard (BGGO's 518:1 is a 51 KB BMP). Left: BGEE Graphics Enhanced is within 13% of the unpacked ceiling - a later release may cross it, and the refusal would then say so. | measured here (CEBG's idea, item 62 as proposed) | - |
| 63 | **Withdrawn as proposed; moved to item 48** (ADR-0045, item 63). Four independently reviewed rounds on #98 showed that from mod_installer's window (WeiDU's last 10 lines with each question, shared by a batch's components) neither which question nor which component can be told, nor which answers a question takes - Tweaks Anthology #3210 takes 0 outside its "between 6 and 15"; every rule on the text refused right answers of real mods. Kept: recorded answers in order, as before; `install-plan/answers.json` records what each install answered (never read back); the stand-in mod_installer sends the real window. Answering by question comes with item 48's expected texts. Original proposal: send an answer only after its question (CEBG's `PromptMatcher`) | CEBG `engine/src/weidu/runner.rs`, `PromptMatcher` (L666 on) and its use at L385-480 (MIT, idea only) | S-M |
| 64 | **Real prompts as test cases for item 48**: Bardic Wonders 1008 ("Please select 1 or 2", 2 = No, since Artisan's Kitpack 99001 makes Garrick a Troubadour); Item Randomiser 510 (a percentage from the player) and 1100 ("y" only with Xan's or Rescue & Revise 12); Warlock 0, whose hidden prompt has no unattended answer. Facts, credited. | CEBG `manifest/mods/randomiser.toml` L16/L53, `recipes/curated-full-current/mods/bardicwonders.toml` L40, `manifest/curation-map.toml` L240-243 (MIT) | S |
| 65 | **Done** (ADR-0045, item 65). `install_run.known_issues`: on Windows, with EET planned and its core not yet in the EET game, the raw registry value of Documents (`Personal`, unexpanded) holding a space and the EET copy still cutting at it, the confirmation says so - "Install despite a known issue", not a refusal. What the cut does, read in EET's source at c26a11a (not run on Windows): the core most likely finishes, writing EET's settings (Baldur.lua: language, campaign) to `<cut>\Baldur's Gate - Enhanced Edition Trilogy`, a folder the game never reads (it finds Documents itself); saves are not affected; the message names that folder. A user name with a space is not this case (`%USERPROFILE%` is expanded after the cut). EET's file is not patched (item 52). Original proposal: warn before EET core | CEBG `engine/src/weidu/eet_compat.rs`, `docs/handover.md` L138-142 (idea); EET (GPL-3.0, not copied) | S (warn) / M (patch) |
| 66 | **Done** (ADR-0050). `atomic.retried`: on Windows, a rename refused because another program holds the file (winerror 5, 32, 33) is tried again, 10 ms doubling to 1 s - up to about 5.3 s off the GUI's thread, 0.15 s for `write_text`, which the window also calls; a permanent access denial (an existing target folder, a read-only file) at once. All 11 renames go through `atomic.replace`/`rename`/`move` - one more than counted, `archives.py`'s - and an extracted mod moves in one rename, its old copy put back if that fails; a test fails on a new direct one. The hold is simulated in tests, not measured with an antivirus. Original proposal: retry renames on Windows | CEBG `fs_retry.rs` (MIT, idea) | S |
| 67 | **Done** (ADR-0051): **the game not running**. `gamelock.problems` runs before the install and before a resume, and refuses in two cases: a running program whose executable is in a game folder (Linux `/proc`, macOS `ps`, Windows `K32EnumProcesses`), or, on Windows, a `dialog*.tlk` that will not open with no sharing after a short retry; a game under Wine or Proton is found by its command line, and each refusal names the program and pid, or the file, and says to close it and try again (review of #105). **Not before each batch, as proposed**: mod_installer logs a batch and starts its WeiDU right after (16.0.0 `installers.rs` L144, `runner.rs` L198), so nothing can hold a batch back. At each batch the programs are listed again, and one found is said once as a warning; the install is not stopped. Not seen: another account's or an elevated process, and a macOS .app whose executable is outside the folder given. | CEBG `engine/src/preflight.rs` L399, L735 (MIT, idea) | S |
| 68 | **Done** (ADR-0052): **a gated download supplied by hand**. In the download phase, a row not yet there gets *Open the mod's page*, which opens the page the record names, and *Choose the saved file...*. The file goes to `api.supply_download`, which runs `download_selection(only=[mod], supplied={mod: path})`. The runner checks it as it checks a download (a regular file, under the byte ceiling, an archive by its magic bytes, the manifest's pinned sha256 when there is one), then installs it with `install_from_archive`, which needs this mod's tp2. A copy already there is replaced and kept in `.backup/`. The state records `origin: supplied`, the sha256 and the file's name. Only the file chosen is read; no folder is scanned or watched. **Not as proposed**: "size and sha256 match the pinned ones" needs a pin, and pins exist only for release assets (pinning.py) or a manifest's own `sha256`; a Gibberlings3, SHS or Nexus mod usually has none. Without one, the tp2 check is what holds the file, as it holds every download. Not on the command line. | CEBG `engine/src/acquire/manual.rs` and its hosting research note (MIT, idea) | M |
| 69 | **Done** (ADR-0053; shown on the install page: the components that need a look listed in the output, all counted in the summary): **a result per component**. `results.py` (pure) reads WeiDU's verdicts from WSETUP.DEBUG: each run's block, its `--force-install-list`, `Installing [Name]`, and SUCCESSFULLY INSTALLED / INSTALLED WITH WARNINGS / NOT INSTALLED DUE TO ERRORS. It holds them to the game's WeiDU.log before and after the run, and where the two disagree the log wins, with a note. `InstallRun` snapshots each game's WeiDU.log and the debug file's size before the run, then reads only what the run appended: mod_installer 16.0.0 passes `--logapp --autolog --log-extern` by default, measured with the real binaries. The results go in `Outcome.results` and `install-plan/results.json`; `Outcome.ok` stays the exit code. | CEBG `engine/src/weidu/verify.rs`, `log.rs` L136-140 (MIT, idea) | S |
| 70 | **Done, for the facts our data holds** (2026-10-31). `tests/test_ordering_facts.py` runs the planner, opt-in with `IEMOD_FACTS_DATA`, on the community data the community-data workflow has just fetched. Each test gives a log in the wrong order and checks both the planned order and that the rule or place it rests on is still in the data. **Held by BWS-NG's order rules:** BG1NPC before EET_end; Ascension before Spell Revisions and SCS; Bubb's Spell Menu after LeUI, Dragonspear UI++ and EET_gui. **Held only by krion64's places, not by a rule:** Yeslick (NEW NPC MODS) before Crossmod (NPC CROSSMOD); Artisan's Kitpack (KIT & CLASS MODS) after Item Revisions (ITEM ADDITION MODS). **Not in our data, so not made into tests:** Artisan's 20101/12012/7203 at component level (krion64 has no component slots for them); DLC Merger 3 failing with 32-bit WeiDU (a toolchain fact, item 49); DLC Merger v2.1's 10 duplicating 1 (a component conflict, no rule). | CEBG `docs/curation/components/*.md` (MIT, credited) | S |
| 71 | **Done** (ADR-0054; the install page says it after a successful install, for the game that is played - in EET the EET game's log, never BG:EE's): `launch.launch_advice` (pure) and `api.install_launch_advice(plan_dir)` find EEex's main component (`EEex.tp2` #1, which copies its loader) in the planned logs. They say once per log to start InfinityLoader.exe (EEex.exe before v0.9), never the game's own program, which crashes. Off Windows they add that EEex runs only with the Windows game, through Proton or Wine on Linux and CrossOver on macOS. Read in Bubb13/EEex v1.3.1 (a6d21ab): its tp2 and README. **Left**: mods that need EEex and do nothing without it (BGEE Graphics Enhanced, BG2 HD) are not flagged, since their tp2 names were not checked. | CEBG `EEEX.md` L28-29; G3 thread 40143; Bubb13/EEex README | S |

Items 62-71 come from reading Chriz Easy BG and the Gibberlings3 thread on an
HD remaster (41637), 2026-10-31. **Read, not measured here**: each states what
CEBG's code or notes do at 508256a (file and lines given, checked against a
clone) or what the thread's posts and the mods' own files say; none was run.
Item 62 was then measured, and withdrawn. Item 65's bug is read in EET's code at 74e91d72; whether EET has
fixed it since is open. Each item is to be measured before it is built, like
the others in M8. From the thread, nothing joins the catalogue:
every installable HD mod is already known to lcc-docs, BWS-NG or krion64
(BGGO, BGEE Graphics Enhanced, the AI Denoised Areas mods, Infinity UI++).
BG2 HD is unreleased, rewrites `Baldur.exe` and targets BG2:EE alone; Project
IE 4K converts assets for GemRB and is not a mod. What the thread changes for
this tool is EEex (item 71); its sizes pass today's ceilings (item 62, measured).

**Explicitly not planned:**
- Copying any BIO, BWS-NG, mod_installer or CEBG code; CEBG's order and selection (one player's curation).
- Bundling GPL data.
- A web or Tauri front end. The API allows one later, but none is planned.

---

## Phase 3 — Validation

| Milestone | Done when |
|---|---|
| M1 | A test builds a selection from `mods --json` alone, plans and fetches it in **one** run with no WeiDU.log, and validates every output against its JSON Schema.<br>`--events jsonl` emits progress for every byte range, and a cancel stops the run within one chunk.<br>`cli.py` contains no planning logic: `lint-imports` gets a contract that only `cli` and `ui` import `api`.<br>Every existing test still passes. |
| M2 | `describe` gives the right component names in English and one other language for a fixture set of real tp2/tra pairs (EET, SCS, BG1NPC).<br>Every conflict in the fixture EET plan has at least one option, and applying it leaves the plan free of that conflict.<br>A BIO share code goes through import and export without losing anything. |
| M3 | A pytest-qt test, run offscreen on Windows, Linux and macOS, goes through phases 1-5 on a fixture EET selection: picks components, resolves a conflict, reorders, downloads from a local fixture server, cancels and resumes.<br>The `selection.json` it saves is byte-identical to the CLI's for the same choices.<br>The window never blocks for more than 100 ms during a download.<br>The `.pyz` stays standard-library only, and the PyInstaller build starts on all three OSes. |
| M4 | The mock EET plan installs end to end from the GUI on Windows and Linux runners with the real WeiDU and mod_installer.<br>Cancelling mid-install, then resuming, finishes with the same WeiDU.log as an uninterrupted run.<br>A prompt without a recorded answer stops and asks; it is never answered by guess.<br>Restoring the backup gives back the game folder as it was. |
| M5 | Every mod of the 146-mod log has a place from krion64, BWS-NG's sequence or a decisive kind, with its source named, or is marked as having none; none is placed silently (ADR-0041).<br>The plan's disagreements with BWS-NG's sequence (independent of krion64; the supplied log is the Forge's own output) are measured and published, and shown to the player.<br>Each source's classification is read from its real files by a weekly workflow, and a change in its shape fails that workflow, not a player's run.<br>A plan reordered by kind installs with the real WeiDU in the mock EET job. |
| M5b | After a split and a move in the wizard, the GUI's order and `--plan-order`'s agree; the incremental check equals the full one after random sequences of moves (property test), and its time after a drop is measured on the 146-mod log and a 3,000-component order; every offered fix leaves its rule satisfied and adds no error. |
| M6 | One `.python-version` names the version every workflow, `requires-python`, ruff, mypy and the classifiers use, and the weekly check fails when one disagrees; the CLI and the wizard bundles start on a machine with no Python; each adopted library has a test that failed without it, is pinned by hash and passes pip-audit. |
| M7 | Each defect has a test reproducing it, red before its fix and green after; the tp2 one is checked against the real WeiDU. |
| M8 | Each item ships with its own measurement: the classifier's precision and recall on a labelled corpus, the prompts found against the prompts met in a real-WeiDU run, the update signals on the supplied logs. |

**M3, as released in 3.0.0.** `tests/gui/test_m3_end_to_end.py` drives the real main window,
offscreen, through phases 1-4 on a fixture EET selection: the project's ini,
components chosen and a conflict resolved, a mod reordered, then the real
download from a loopback `http.server`, cancelled while a mod is still
arriving (the page says so, nothing half-installed is in the target) and
resumed (only what was not done is fetched again). The catalogue, the
conflict check and the planner are injected there - the real ones fetch
community data - and tested against the command line on their own. Phase 5 is installation
now (item 18), so it belongs to M4. What each criterion stands at:

- Phases 1-4 offscreen: CI's GUI job runs it on Linux and Windows (a gate),
  and `macos.yml`'s GUI job on macOS (informational, as all of macOS is since
  its runners stopped starting on 2026-10-21).
- `selection.json` byte-identical to the CLI's: **met** - the wizard's file
  equals what `iemod-fetch --emit-selection` writes from WeiDU.logs that
  install the same components under the same names (asserted in the same
  run). A real log that spells a tp2 in capitals gives that spelling, not
  the catalogue's, so the two then differ in case only.
- Never blocked for 100 ms during a download: **met on Linux** - the longest
  gap of a 10 ms timer during both downloads is 11-16 ms, 32 ms with every
  core busy. **Not yet on Windows every time**: the CI runs passed, but the
  release gate of 4.0.0 (2026-10-31, same commit as a passing CI run)
  measured one gap of 240 ms on windows-latest. The `GUI latency` workflow
  (docs/TESTING.md) found the cause: every new HTTP client built a TLS
  context, and on Windows that reads the certificate store holding the GIL.
  Fixed by ADR-0048 (one context per process, built before the window is
  drawn); the limit stays 100 ms.
- The `.pyz` standard-library only: kept by the `stdlib-only` CI job until 4.0.0; since ADR-0043 it carries its runtime libraries inside, checked by the same job.
- The PyInstaller build starts on all three OSes: **met** (item 20,
  ADR-0040). In #42's CI the Linux and Windows bundles were built, unzipped
  and started with `--check` by the release rehearsal, and the macOS one by
  `release-macos.yml`'s.

Gates that apply throughout: pytest, ruff, mypy, import-linter, bandit,
actionlint, zizmor, and the real-WeiDU job. A UI change is the same pull
request process as any other.

## Sources

- [BIO](https://github.com/Born2BSalty/Born2BSaltys_Infinity_Orchestrator) (read at 33800cc)
- [BigWorldSetup-Next-Generation](https://github.com/Selphira/BigWorldSetup-Next-Generation) (f7befca)
- [lcc-docs](https://github.com/RiwsPy/lcc-docs) (6d73f77)
- [mod_installer](https://github.com/dark0dave/mod_installer) (3b6827a)
- [krion64 Forge](https://github.com/krion64/krion64.github.io) (a8d17c4)
- [Infinity Mod Runner](https://github.com/Anprionsa/infinity-mod-runner)
- [WeiDU Install Tool](https://github.com/InfinityTools/WeiduInstallTool)
- [Chriz Easy BG (chriz-bg-collection)](https://github.com/Chrizhermann/chriz-bg-collection) (508256a, MIT)
- [Gibberlings3: "Baldur's Gate True HD Edition" remaster, how feasible](https://www.gibberlings3.net/forums/topic/41637-baldur%E2%80%99s-gate-%E2%80%9Ctrue-hd-edition%E2%80%9D-remaster-how-feasible-would-it-be-today/) (read 2026-10-31, one page)
