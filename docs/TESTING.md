# Testing strategy

## The problem with "we do TDD"

TDD gets you a test for every case you thought of. Every defect that has
actually hurt this project was a case nobody thought of:

- a `? 1 : 0` **anywhere** in a `.tp2` suppressing every `GAME_IS` match;
- twenty WeaselMods mods all resolving to `alabaster-sands`, because a bare
  navigation link scored just high enough;
- `EET_END.json` sorting before `eet.json` in ASCII, so a folder claim put the
  EET core in "EET FINALIZATION" and sent it to the end of the install;
- `compare("master", "main")` returning 1 — and `compare("main", "master")`
  returning 1 as well.

None of those would have been written as an example. Seven techniques are used
here, each aimed at a class of defect the others cannot see.

## 1. Characterization tests — pinning the original's behaviour

`tests/test_legacy_characterization.py`, 13 tests, running against
`legacy/fetch_mods_original.py`, which is kept **verbatim** (ADR-0001).

They assert the original's *defects*: that it mutates repository names, that it
takes the first hit of a code search, that it accepts an archive whose `.tp2`
does not match. A rewrite that claims to fix something has to be able to show
the thing being fixed. Delete the legacy file and the evidence goes with it.

## 2. Example tests — the ordinary TDD layer

~540 example tests across 26 files, one per module. Offline, no network, no mocking
framework: the test doubles are small hand-written classes, and where the real
code raises `HttpStatusError` the double raises `HttpStatusError` too. (It did
not, once. The double raised a bare `NetworkError`, and a retry path that only
existed for typed errors went untested.)

Fixtures are **real files**: the operator's actual 148-entry manifest and their
796-component WeiDU logs, in `tests/data/`. Synthetic fixtures only ever contain
what the author imagined.

## 3. Property-based tests — laws, not examples

`tests/test_properties.py`, using Hypothesis. Skipped, not failed, when
Hypothesis is absent, because `python3 -m pytest` must work with nothing
installed but the runtime's own libraries (`requirements/runtime.txt`).

A property states something that must hold for **every** input, and Hypothesis
searches for a counterexample and then *shrinks* it to the smallest input that
still fails. The properties are chosen where a law genuinely exists:

| Property | Why it must hold |
|---|---|
| `safe_component` is total | a path-traversal guard that itself raises is a denial of service in the guard |
| what `safe_component` accepts can never traverse | the security boundary, stated as a law rather than as twelve examples |
| `normalize_key` is idempotent | it is applied at several layers; a second application must not change the answer |
| `tp2_key` agrees with `normalize_key` | two normalisations mean rules that silently match nothing |
| `compare` is reflexive, antisymmetric, transitive | otherwise it is not a strict weak ordering and `sorted()` over releases is undefined |
| `is_newer` agrees with `compare` | one of them is used to decide staleness, the other to pick a release |
| a release tag always beats a branch snapshot | the operator's stated stability ordering |
| every parser is total over arbitrary text | a log or a catalogue is attacker-adjacent input |
| a well-formed log round-trips | reading and writing are inverse |
| `_minimum_moves` is empty for an unchanged order, and 1 for one rotation | the metric that stopped the planner claiming 146 mods were out of place when one was |

**This has already paid.** On its first run the antisymmetry property found that
`master` and `main` — both rank −6 — each compared as *newer than the other*, so
`is_newer` was true in both directions and an upstream renaming its default
branch could mark a rule stale on the rename alone. Six hundred example tests
had not noticed. Shrunk counterexample: `compare('MASTER', 'MAIN')`.

The pull-request run uses 300 examples so it stays fast; the nightly job gives
the same properties 20,000.

## 4. Architecture tests — the layering as a gate

`.importlinter`, four contracts, run in CI. The design in `docs/ARCHITECTURE.md`
is not a diagram that drifts away from the code: an import that crosses a
boundary fails the build.

**This has already paid too.** The purity contract refused
`catalogues → resolvers`, which existed as a function-local
`from .resolvers import repo_from_url` written specifically to dodge an import
cycle — the standard sign that a pure thing is trapped in an impure module. The
fix was `urls.py`, and the catalogue layer is honestly pure now.

## 5. Static analysis — the checks that need no test

| Tool | The class of defect it catches |
|---|---|
| `mypy` | `Optional` reaching somewhere that cannot handle it; a wrong attribute; a function returning `Any` where the signature promises a type. Caught a genuine `NameError` I had just introduced in the extraction path — before any test ran. |
| `ruff` | mutable default arguments, loop-variable capture, blind `except`, dead code, shadowed builtins |
| `bandit` | the security-shaped mistakes: `assert` used for a real check (stripped by `python -O`), permissive file modes, unvalidated extraction |
| `tools/check_stdlib_only.py` | any non-stdlib import in the runtime, including one nobody thought to ban |
| `zizmor` | the workflows themselves: over-broad tokens, persisted credentials |
| `-W error` in pytest | a `DeprecationWarning` from the stdlib is the earliest possible notice that a future Python breaks this. It also found two tests leaking file handles the day it was switched on. |

## 6. Mutation testing — does the suite actually assert anything?

Nightly, `mutmut`, reported and never gating.

Coverage says a line *ran*. It does not say the tests would have **noticed** if
that line were wrong, and the two are routinely confused. Mutation testing
changes an operator, deletes a branch, swaps a constant, and asks whether any
test goes red. A surviving mutant is a question — "is this behaviour actually
asserted, or merely executed?" — and sometimes the honest answer is "it does not
matter", which is why it reports rather than blocks.

This is also why the coverage floor is 85 and not 100. A number above what the
code honestly reaches turns into tests written to touch lines.

## 7. Loopback socket tests — the real HTTP stack

`tests/test_net_loopback.py` runs a stdlib `http.server` on `127.0.0.1` and
points the real client at it: real `urllib`, real `http.client`, real sockets.
Still offline — nothing leaves the loopback interface.

Every other network test uses a hand-written double, and a double encodes what
its author *believes* the library does. The first loopback run disproved one
such belief: `http.client`'s `read(n)` does **not** raise on a body cut short
of its `Content-Length` — it returns what arrived, then `b""`. A connection
dropped mid-transfer was being accepted as a complete download whose first
bytes even carried the right magic number. No double would have shown it,
because the double was written to raise `IncompleteRead`.

Borrowed from the download tests of Born2BSalty's Infinity Orchestrator, which
serve fixtures over a loopback TCP listener for the same reason.

**The wizard end to end.** `tests/gui/test_m3_end_to_end.py` is the M3
validation run: the real main window, offscreen, through phases 1-4 on a
fixture EET selection - the project's ini saved, components chosen and a
conflict resolved, `selection.json` compared byte for byte with what the
command line's `--emit-selection` writes from WeiDU.logs that install the
same components under the same names, a mod dragged, then the real
`api.download_selection` and `HttpClient` against a loopback `http.server`.
One mod trickles in as a slow mirror does; the player cancels it, the page
says so and the target holds only the mods that finished; Download again
fetches only the rest. A 10 ms timer measures the event loop during both
downloads and the test fails on a gap of 100 ms or more (11-16 ms on Linux,
32 ms with every core busy; once 240 ms on windows-latest, see "The event
loop on Windows" below). The catalogue, the conflict check and the planner
are injected (the real ones fetch community data), and a socket guard fails
the test on any connection but to 127.0.0.1.

**Against the real GitHub.** Two workflows go further and ask GitHub itself,
because a double of a third-party API is only what its author believes it
does. `community-data.yml` refreshes the three community sources from nothing.
`mod-metadata.yml` runs `tools/premeta_live_check.py`: premeta's metadata ini
search on real repositories whose ini only the contents-API listing finds
(Deities of Faerun ships `Deitiesoffaerun.ini` beside `DeitiesOffaerun.tp2`; a
WeiDU log may spell `ASCENSION/ASCENSION.TP2`), one raw.githubusercontent.com
finds directly, and one with no ini. Both run on a pull request that changes
the code they check and on a schedule. A quota or network failure is reported
as inconclusive, never as a pass. Writing the cases found a wrong belief of
our own: Ascension's `ascension.ini` looks like the mod's settings file, but
under the settings it carries a `[Metadata]` section that Project Infinity
reads, and premeta was right to take it.
`download-sources.yml` resolves the supplied 145-mod EET log with the
community catalogue only and with the manifest (dry runs), then downloads 20
of the mods the catalogue found, so the tp2 check of real archives is
measured too; the numbers go to the job summary (`tools/download_measure.py`).
A session sandbox cannot make this measurement: its proxy refuses
third-party repositories and the mod sites.

## 8. The real WeiDU as oracle — no game data needed

`tests/test_real_weidu.py` runs the mock EET install through the real WeiDU
(v251) and, when given, the real mod_installer. WeiDU identifies a game by
marker files (`oh1000.are`, `oh6000.are`, `eet.flag`), so a folder with an empty
`chitin.key`, an empty `dialog.tlk` and the marker is enough for it to enforce
GAME_IS, REQUIRE_COMPONENT and FORBID_COMPONENT. Three claims:

* on the raw logs, WeiDU refuses exactly the components `--simulate` refuses;
* WeiDU installs the resolved plan to the last component;
* the generated `install-eet.sh` drives mod_installer + WeiDU into both games.

`tests/test_real_mod_installer.py` (ADR-0045) runs the wizard's own install
(`api.start_install`) with the same two programs: a test mod whose tp2 asks
two questions (`ACTION_READLN`), the planned log recording their answers as
`// @wlb-inputs: hello,world`. mod_installer's question reaches the install,
both recorded answers go back in order, and WeiDU installs the component
with them. `tests/test_install_run.py` runs the rest - an answer from EET's
folder, from the log, from the player; cancel, which must also stop the
process mod_installer started; a failed component; folders with spaces and
accents - against a stand-in that prints and asks as mod_installer does.
It also measures a folder given as an answer - plain, and with accents -
reaching WeiDU through mod_installer (`FILE_EXISTS` in the test mod). CI runs
it on Linux (`real-weidu`) and on Windows (`mod-installer-windows`, the
official WeiDU for Windows and the bundle's own mod_installer build): the
measurement that lifted #83's refusal of an accented BG:EE folder (ADR-0046).
`tests/test_toolchain.py` covers where the programs come from and WeiDU's
pinned download: a tampered byte, a zip reaching out of its folder, a
program swapped after the download - each refused, nothing left behind.

Its first run found two bugs no self-consistent test could: a parser bug and a
fixture placed where WeiDU does not look. Opt in locally with
`IEMOD_WEIDU=/path/to/weidu` (and `IEMOD_MOD_INSTALLER`); CI's `real-weidu` job
downloads both pinned and sets `IEMOD_REQUIRE_REAL=1`, so a missing tool fails
instead of skipping; so does the Windows job.

### Ordering facts on the live data (GUI-AUDIT item 70)

`tests/test_ordering_facts.py` gives the planner logs in the wrong order and
checks the order it plans for facts from Chriz Easy BG's curation notes that
our community data holds, and that the BWS-NG rule or krion64 place each
rests on is still there. It needs a data cache: opt in with
`IEMOD_FACTS_DATA=<data dir>` (as `iemod-fetch --update-data` fills it).
The community-data workflow runs it nightly on what it has just fetched.

### Components before download: krion64 against WeiDU

The wizard offers a mod's components before it is downloaded from krion64's
records (ADR-0035). `tools/krion_components_benchmark.py` compares them with
WeiDU 251's own `--list-components` (the `tools/tra_oracle.py` output, 105
mods both know): of 1,529 components WeiDU lists, 1,471 are in krion64 under
the same number; 58 are missing (7 of them marked removed though the tp2 still
has them), 13 krion64 lists are not in the tp2, and 85 mods are identical.
Hence each component says where it came from, and the staged tp2 replaces
krion64 for its mod.

### Community sources: lcc-docs, krion64 and BWS-NG against each other

`tools/download_sources_benchmark.py LCC_MODS_JSON KRION_DATA --bws
BWS_MODS --probe` measures where a mod is downloaded from (ADR-0036). On
2026-10-22 over the Enhanced Edition mods: lcc-docs knows 1,148, krion64 813,
BWS-NG 412. Of the 113 mods for which lcc-docs and krion64 name different
repositories, krion64's is gone in 27 and lcc-docs' in none; 23 are one
repository under two names; of the 63 different live ones lcc-docs' has the
newer last commit in 51. BWS-NG pins exact files: 279 of its 280 pinned GitHub
release tags still exist, and against the newest scanned release its pinned
version is the same for 177 mods, older for 48 and newer for 3. `tools/krion_components_benchmark.py ORACLE KRION
BWS` adds BWS-NG's components: on the 67 mods all three know, krion64 has
1,047 of WeiDU's 1,089, BWS-NG 1,023, their union 1,057.

### The authors' own order: Project Infinity metadata inis

`tools/pi_metadata_benchmark.py MODS_DIR KRION_DATA RULES...` reads every mod's
metadata ini (from git, so sparse clones do) and compares its `Before`/`After`
with krion64's order and the order rules (ADR-0037). On 103 real mods: 85 inis,
314 order pairs; krion64's order agrees with 239, a rule covers 34 of the rest,
22 span the two EET game phases, and 19 are known only to the author - 7
contradicting krion64. Two of the 19 name a mod by its display name ("Coran in
BG2"), which matches no tp2 and so orders nothing.

### The kind of a mod and its place: every source against the others

`tools/order_sources_benchmark.py KRION_DATA BWS_DATA LCC_MODS_JSON [--log
WeiDU.log]` reads krion64's (the Infinity Mod Forge's), BWS-NG's and
lcc-docs' real files (ADR-0041). On 2026-10-23: BWS-NG's per-component EET
sequence (3,232 components) and krion64's order disagree on 21% of the pairs
both place (21.5% without the pairs krion64 ties: order within a mod is not
compared); the sequence places 26 mods krion64 does not; lcc-docs classifies 546 EE mods krion64 does not place; a
category maps onto one krion64 install category for 85-100% of its mods only
for interface, cosmetic, kit, NPC and smith mods. The supplied log is the
Forge's own output (its header), so krion64 agrees with it on all but 0.02%
of pairs: it cannot judge krion64.

### Engine limits, measured as WeiDU measures them

`tests/test_real_weidu_limits.py` checks the game-folder measurement of
`limits.py` (ADR-0034) against the same WeiDU. The synthetic BG2:EE has a real
`chitin.key` and BIFF (built byte by byte), KITLIST.2DA and SPELL.IDS inside
the BIFF, and the other tables ADD_KIT appends to in override/:

* with 254, 255 and 256 kits measured, WeiDU's ADD_KIT gives kit 255 and 256,
  then refuses with its own "more than 256 kits" - so the measured number is
  WeiDU's, and 256 is a hard limit on BG2:EE;
* with 2101 and 2102 in SPELL.IDS, SPWI103 in override/ and SPWI105 in the
  BIFF, ADD_SPELL takes 2104 then 2106, and reuses 2101 for an identifier
  SPELL.IDS already has - exactly the slots measured as free.

krion64's counts, which stand in when no game folder is known, were audited
the same day: its spell scanner (`scan_spell_ids.js`) reads only literal
`APPEND spell.ids`, so of the 103 repositories NWNForBG (6 ADD_SPELL) and
Region of Terror (4) are recorded with 0; `k` is entered by hand; `ss` counts
references. Hence the estimate is labelled as one, and the measurement wins.

### Component names, measured against WeiDU itself

`iemod_fetch/tra.py` names components without running WeiDU. Its claim is
"the same text WeiDU prints", and it is measured, not argued:
`tools/tra_oracle.py` runs `weidu --nogame --list-components` for every tp2
and every language of a set of real mod repositories, and
`tools/tra_benchmark.py` compares, byte for byte.

```bash
python3 tools/tra_oracle.py /path/to/weidu MODS_DIR oracle.json
python3 tools/tra_benchmark.py oracle.json --min 99.9
```

On 103 repositories (lcc-docs and BWS-NG mods, cloned 2026-10-21) and WeiDU
251: 551 runs, 9,889 component lines. The parser went from 65.70% to 100.00%
exact, each step a form WeiDU accepts and the parser did not - bare-word
LANGUAGE names (SCS), `%WEIDU_OS%`, FORCED_SUBCOMPONENT, `BEGIN` alone on its
line, undesignated numbering as previous + 1, a bare-word .tra value,
`%MOD_FOLDER%` taken from BACKUP (LCA). Each became a unit test in
`tests/test_tra.py` or `tests/test_tp2_components.py`.

The same run records `--list-components-json` for language 0, and the
benchmark checks the rest of WeiDU's view against it: which components are
listed at all (a DEPRECATED one is not: Might and Guile #145), and each one's
title, subgroup, groups, labels and forced flag - 109 of 109 lists and 1,499 of
1,499 components on every field. It also found that the JSON drops a line
break inside a name where the text output prints a space; `name` follows the
text, `title` and `subgroup` the JSON.

The same LABELs measure krion64's: of 732 LABELs both krion64's records
(`co[].pi`) and the tp2s name, 708 point at the same tp2 and component; 24 do
not, some at another mod altogether (`cd_tweaks_drab_commoners`: cdtweaks
#100 in the tp2, iwdification #20 in krion64). That is why `--pi-list` takes
the tp2's answer whenever the mod is staged and reports every entry it took
from krion64.

Read the 100% honestly: it is the set the parser was fixed against, so it is a
training score. A new mod can still use a form not seen here; the next run of
the oracle on a wider set is the real test. Names built by code at install
time (an `OUTER_SPRINT` then `BEGIN %name%`) are out of reach by design and
are reported unresolved, not guessed.

### Versions: what is installed, and what is newest

Two rules decide the update notice, and both are measured with
`tools/version_benchmark.py` against what the mods themselves say:

```bash
python3 tools/version_benchmark.py oracle.json krion64/data BWS-NG/data/mods MODS_DIR
```

* **The version in a WeiDU.log line** (`weidu.log_version`). WeiDU 251 writes
  `Name: VERSION`, checked by installing a test mod with it, and names have
  colons too. On the oracle's 1,533 component lines: 1,409 versions read
  right, 0 wrong, 0 missed, 124 lines rightly without one. Taking whatever
  follows the last `: ` would have been wrong 111 times.
* **The newest version** (`freshness.latest`). Against the tp2 VERSION at HEAD
  of 90 mods, each source alone: GitHub release 67 the same, krion64 60,
  BWS-NG 42; the newest of the three, 79 (5 older, 6 newer, none unknown).
  The truth is imperfect: most "newer" are real releases whose author did not
  bump the tp2, so a right answer counts against the rule.

### BIO share codes, checked against BIO itself

`iemod_fetch/bio.py` implements the `BIO-MODLIST-V1:` format from reading
BIO's source (33800cc); it uses none of BIO's code. Whether it really speaks
the format is checked with BIO, built from that commit with one test added
outside this repository that calls BIO's own `encode_share_payload_text` and
`decode_share_payload` + `share_preview`:

* `tests/data/bio/eet-mock.bio` was **encoded by BIO** from the mock EET
  install (with a `// @wlb-inputs:` answer, BIO's extras, non-ASCII text).
  `tests/test_bio.py` decodes it, re-encodes it to the same JSON payload byte
  for byte, and round-trips it through a selection keeping every field. With
  classic zlib the code itself comes out identical; Python 3.14 on Windows
  ships zlib-ng, whose deflate stream differs while inflating to the same bytes
  (the first CI run showed it), so the test compares the payload.
* Codes **written by this tool** - a fresh export and an export over the
  imported code - were decoded and previewed by BIO, which read the same game,
  install mode, entry counts and name.

To repeat it: append `tools/bio_interop_test.rs` to BIO's
`src/core/app/modlist_share.rs`, then
`IEMOD_CODE_IN=ours.bio cargo test --lib iemod_interop -- --nocapture`.

### Kinds and install places, on the live data (GUI-AUDIT item 29)

`tools/places_check.py DATA_DIR [--log WeiDU.log]` runs every night in the
community-data workflow, on the data it has just fetched:

* it **fails** when lcc-docs or BWS-NG use a category `iemod_fetch/kinds.py`
  does not map (it would show raw and place nothing), when krion64 loses a
  category a kind places into, when BWS-NG's `games/eet.json` no longer has a
  bg2ee sequence with the EET core, or when a count falls under its floor
  (more than 1,500 mods with a kind, 300 placed by kind, one by the
  sequence). Mutated copies of the real data - krion64 renaming QUEST MODS
  BG2, lcc-docs renaming its `categories` key - fail it; the job summary is
  written on the night it fails, with the upstream text escaped;
* it counts what places the mods with a kind that krion64 does not place.
  On the 2026-10-23 data: 1,071 such mods; 15 by BWS-NG's sequence, 436 by
  kind, 620 with no place (each with its reason);
* with the 146-mod log it plans the EET install without and with those
  places, and counts the pairs of components ordered the other way round
  from BWS-NG's sequence - the independent judge ADR-0041 decision 5 names:
  9,380 of 123,753 (7.6%) both times. The log is the Forge's, so krion64
  places all of it but one portrait pack no source classifies: the places
  change nothing there, and the check says so rather than claiming a gain.

The mock EET job installs a plan reordered by kind with the real WeiDU
(`test_real_weidu_installs_a_plan_reordered_by_kind`): ub and ascension,
which the test catalogue does not place, become BG2 quests, ub moves ahead of
stratagems and cdtweaks, and WeiDU installs every component. BWS-NG's files
are GPL and never bundled: the fixtures written in its shape are made up
(`tests/test_places_check.py`, `tests/test_place_by_kind.py`).

### The check after a drop, timed (GUI-AUDIT item 31)

`tools/order_check_benchmark.py [--data DATA_DIR --log WeiDU.log] [--gui]`
drops random rows and times the order page's check after each, limited to
the moved row, against the full check - and counts where they disagree,
which `tests/test_order_check.py` proves never happens (a hypothesis
property over random orders, rules and moves). On 2026-10-23, p50/p95:

| Order | After a drop | Full check |
|---|---|---|
| 146-mod log, EET install (152 units, 157 rule edges) | 0.015 / 0.026 ms | 0.025 / 0.045 ms |
| Synthetic, 3,000 units, 4,507 rule edges | 0.26 / 0.45 ms | 0.8 / 1.4 ms |

`--gui` times the page itself, offscreen, to its marks on 3,000 rows: 3.7 /
7.1 ms (reading the rows dominated it, 39 ms at p50, until the node was
stored on each row as a string and only the rows whose mark changes were
painted again). No test asserts a time: a shared runner would make it flaky.

### The questions a mod asks, read before installing (GUI-AUDIT item 48)

`tools/readln_census.py CORPUS` runs `iemod_fetch/readln.py` over checkouts of
real mods (their .tp2, .tpa, .tph, .tpp, .tpc and .tra files) and compares the
READLNs it attributes to a component with every READLN in the mod's files.
Measured on 2026-10-31 on 105 of the reference build's 108 GitHub mods (3
did not clone; sparse checkouts of the WeiDU files only): 8 mods hold a
READLN, 51 in all; 45 reached from a component (88%). The question is known
for 42 of those (93%): 25 a .tra string in the player's language, 17 a fixed
English text in the code; 3 are printed from a variable set elsewhere. Of the
6 not reached, 5 are SCS's, in its SFO library, behind `%sfo_loc%` paths
built while installing - said `unread`, not guessed - and 1 (TDDz) follows a
`FAIL` and is never asked. "Reached" counts a READLN some component reaches,
not which one. Getting there took four fixes the census showed:
`%COMPONENT_NUMBER%` in include paths (Tweaks Anthology's
`comp_%COMPONENT_NUMBER%_prompts.tpa`), the preamble's `OUTER_SPRINT`
constants (EEUITweaks' `%PKGNAME%`), BACKUP under `weidu_external`, and a
tp2 kept below its mod folder (EET's modConverter); and the review of #101
eight more: `LAF ... END`, `ACTION_MATCH`/`ACTION_TRY ... END` (an END with no
BEGIN - 4,714 of 7,601 function bodies were cut at their first LAF), FAIL,
`ACTION_BASH_FOR`, lines after a block comment, a question printed from a
variable, a path that is one variable, functions in `.tpc` files. What it cannot say:
whether WeiDU really asks a reached READLN on a given install (a condition may
skip it) - that takes a real install, which no runner has the games for.
`tests/test_readln.py` holds each shape as a case.

### RAR archives, extracted against 7-Zip (GUI-AUDIT item 40)

`tools/rar_measure.py corpus | reference | compare` downloads the distinct
.rar links of lcc-docs' `mods.json`, extracts each with the official 7-Zip
(the reference: it alone implements every RAR version) and then with each
candidate, in an empty folder, and calls an archive identical only when the
same files come out with the same SHA-256. The `RAR extractors` workflow runs
it inside `debian:trixie` (bsdtar, unar, 7zip-dfsg: the floor's own packages)
and on Windows and macOS runners (their system bsdtar, Homebrew's unar).
On 2026-10-24 (CI): of lcc-docs' 131 distinct .rar links, 130 downloaded and
the reference extracted 105 (98 RAR4, 7 RAR5; 7 solid); the other 25 are not
RAR at all (the link serves something else). Archives each tool
extracted to the same files:

| Platform | bsdtar (libarchive) | unar | 7zip (dfsg) | Any |
|---|---|---|---|---|
| Debian trixie | 95 | 94 (RAR5: 0 of 7) | 1 | 100 |
| Windows (`tar.exe`) | 95 | - | - | 95 |
| macOS (system bsdtar, Homebrew unar) | 95 | 103 | - | 103 |

bsdtar fails mostly on solid RAR4 archives (5 of 7 solid); trixie's unar on
every RAR5 one, Homebrew's on none. Two solid RAR4 archives (027, 030) no
open-source tool extracts. The numbers decide the extractor (an ADR); no
test asserts them.

### The event loop on Windows, traced (GUI-AUDIT M3)

The release gate of 4.0.0 failed on one assertion: the M3 test measured a
240 ms gap on windows-latest, where the CI run of the same commit had passed
(Linux: 11-16 ms when M3 was validated, 11-20 ms in local runs on
2026-10-31). A gap that size can be the garbage collector holding the GIL,
the worker thread holding it in pure-Python code, or the runner not
scheduling the window's thread at all. With `IEMOD_LATENCY_TRACE=<file>`
(relative to where pytest runs) the test writes when every gap ended, every
collection with its generation and length (`gc.callbacks`), every event of
the download stamped in its own thread when sent, and when the window took
each in. `tools/gui_latency_summary.py` lines them up: for each gap over
50 ms, which collection overlapped it, what the download sent just before and
during it, and how many events the window handled during it. When the loop
is held past 40 ms, `faulthandler.dump_traceback_later` - a C watchdog that
needs no GIL, re-armed at every tick - writes every thread's stack at that
moment beside the trace, and the summary shows it. The `GUI
latency` workflow runs the test 30 times on ubuntu-latest and windows-latest
and publishes that summary.

First measurement (#96, 30 runs each, 2026-10-31): ubuntu-latest median
11.1 ms, worst 13.8 ms; windows-latest median 15.5 ms, worst 63.9 ms, none
over 100 ms. The three Windows gaps over 50 ms (58-64 ms) had no collection
in them and came before the download had sent any event: between the click
on Download and the run's first event. The 240 ms of the release gate is not
reproduced in 30 runs. The stack dumps of the next 30 named it: each time
the download's thread was in `ssl._load_windows_store_certs`, building a
TLS context for a new `HttpClient` - Windows' certificate store read and
parsed with the GIL held. The fix is ADR-0048: one context per process,
built by the wizard before its window is drawn; the limit stays 100 ms.
With it, windows-latest measured median 10.9 ms, worst 11.8 ms over 30 runs
(before: 15.5 and 63.9 ms) - what ubuntu-latest measures.

### The Linux bundles on the target distros (ADR-0056)

`.github/workflows/bundles-distros.yml` takes a published release's Linux
zips and starts them inside fedora (Bazzite's base), archlinux (CachyOS's
base), ubuntu 24.04 and latest, and debian trixie. `tools/distro_libs.sh`,
run as root in each fresh container, measures four things:
- which libraries the bundle's Qt links to and the system lacks, read with
  `ldd`, for three sets: a headless start (offscreen), an X11/XWayland
  desktop (xcb) and a native Wayland session;
- which package ships each library, asked of the distro's own index
  (`apt-file`, `dnf repoquery`, `pacman -F`), then installs them;
- whether the wizard starts offscreen (`--check`), before and after;
- whether the command line answers `--version` and `--help`.

Each job's summary lists what was missing and the package that filled it,
which is what the README and docs/GUIDA-TEST-REALE.md tell a player to install.
release.yml dispatches it for each tag it publishes (its own `release`
event, made with `github.token`, starts no workflow). It also runs on a
release published by hand, on a pull request that changes the workflow or
the script (on the latest release), and by hand on any tag.

## What is deliberately not done

**No network in the test suite, ever.** Not even against a local server. The
suite runs on an aeroplane and gives the same answer.

**No mocking framework.** `unittest.mock` makes it easy to assert that a
function was called, which is a test of the implementation rather than of the
behaviour. Hand-written doubles are more work and stay honest.

**No snapshot testing of the reports.** The renderers are asserted on the facts
that matter ("the plan says FRESH install", "the remedy names the cheaper
side"), not on their whole output. A snapshot test of a 40-line report fails on
every wording change and teaches people to re-bless it without reading.

**No fuzzing harness yet.** It is on the roadmap for `archives.py` and the
parsers, where the input is genuinely hostile. Hypothesis already covers the
parsers as far as structured generation goes; a real fuzzer would go further on
the zip and tar readers.

## Running it

Install the runtime's pinned libraries first (`pip install --require-hashes -r
requirements/runtime.txt`), then the extras: the extras' loose ranges would
else pull a newer release than the pin, and the zipapp tests build from the
pinned versions. CI installs them in that order.

```bash
make check            # ruff, mypy, import-linter, pytest — what CI gates on
make cover            # with the branch-coverage floor
make audit            # bandit and pip-audit
make mutants          # slow; the nightly job runs this

python3 -m pytest -q                              # the suite, ~13s
python3 -m pytest tests/test_properties.py -q     # the properties alone
python3 -m pytest -k "security" -q                # the boundary tests
```

## Current numbers

| | |
|---|---|
| Tests | 2,095 collected (25 run the real WeiDU, 198 drive the GUI with pytest-qt; both opt-in) |
| Branch coverage | 92% (floor: 85%) |
| Architecture contracts | 7, all kept |
| mypy | clean, 64 modules |
| ruff | clean |
| bandit | 0 high, 0 medium |
| Runtime dependencies | 0 |
