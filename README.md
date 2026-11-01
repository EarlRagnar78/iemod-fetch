<p align="center">
  <img src="docs/assets/banner.svg" alt="iemod-fetch: Infinity Engine mods for EET, BGEE and BG2EE, fetched, verified, ordered, conflict-checked and installed, without guessing" width="100%">
</p>

<p align="center">
  <a href="https://github.com/gsamuele78/iemod-fetch/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/gsamuele78/iemod-fetch/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://github.com/gsamuele78/iemod-fetch/actions/workflows/security.yml"><img alt="Security" src="https://github.com/gsamuele78/iemod-fetch/actions/workflows/security.yml/badge.svg"></a>
  <a href="https://www.python.org/downloads/"><img alt="Python 3.14" src="https://img.shields.io/badge/python-3.14-blue"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-green"></a>
  <a href="docs/ARCHITECTURE.md"><img alt="Runtime dependencies: 0" src="https://img.shields.io/badge/runtime%20dependencies-0-brightgreen"></a>
  <img alt="Platforms" src="https://img.shields.io/badge/platforms-Windows%20%7C%20Linux%20%7C%20macOS-informational">
  <img alt="Games" src="https://img.shields.io/badge/games-EET%20%7C%20BGEE%20%7C%20BG2EE-8a5a2b">
</p>

<p align="center">
  <b><a href="#from-weidu-logs-to-a-running-eet-game">Quick start</a></b> ·
  <a href="docs/GUIDE.md">User guide</a> ·
  <a href="#what-it-guarantees">Guarantees</a> ·
  <a href="docs/ADR.md">Design decisions</a> ·
  <a href="CHANGELOG.md">Changelog</a> ·
  <a href="docs/ROADMAP.md">Roadmap</a>
</p>

# iemod-fetch

Turns two `WeiDU.log` files (what you want installed) and a `mod_downloads.json`
catalogue (where to get it) into a **running EET, BGEE or BG2EE install**. It
downloads and verifies every mod, plans a rule-compliant install order, removes
the components the community rule sets say must go, and writes one script that
installs everything with WeiDU on Windows or Linux. It never guesses: whatever
the evidence does not decide is reported to you, with the reason.

The standard library at runtime, plus two libraries that earn their place
(publicsuffixlist, MPL-2.0: the Public Suffix List; filelock, MIT: one refresh
of the community data at a time; ADR-0043), carried inside the one file -
nothing to install but Python 3.14.

**Current release: 4.1.0** - the install learns what it will meet before it
starts: the questions the mods will ask, put to you in one window and answered
by question when they come (ADR-0049); the game closed (ADR-0051); room on
the drives and WeiDU's version (ADR-0055); EET's Documents-path fault; then
what each component came to and how to start the game (ADR-0053, ADR-0054),
and a watchdog that warns, never stops. A mod no source can download is
supplied by hand (ADR-0052). 4.0.1 stopped the wizard's window freezing on
Windows (ADR-0048). 4.0.0 brought one Python version,
3.14, and the wizard that
installs (milestones M5, M5b, M6, and M4 but for its item 24, a real
end-to-end job on Windows). The wizard now goes from game and
folders to a finished install: mod selection with conflicts and presets, the
order - by kind for what krion64 does not place (ADR-0041), and edited by
component, with fixes after a manual move - download and extraction, then a
backup checked against the game as it is, mod_installer run with WeiDU's
questions answered, and a stopped install resumed from the games' WeiDU.log.
Both the wizard and the command line come as programs that need no Python,
for Linux (Debian trixie, the minimum, and Ubuntu 24.04), Windows and macOS.
4.0 breaks: Python 3.14 for the `.pyz` and pip, RAR archives through the
system's tools (ADR-0047) - see *Upgrading from 3.x* in the changelog. Next
in the plan: M4's item 24, defects to fix (M7) and what the other projects do that this
tool does not (M8, which since 2026-10-31 also holds ten ideas read in Chriz
Easy BG, an MIT installer for one curated EET collection: items 62-71, of which 62 was measured and withdrawn and 63, 65-71 shipped in 4.1.0; 64 is left)
([`docs/GUI-AUDIT.md`](docs/GUI-AUDIT.md)). What changed in each
release is in [`CHANGELOG.md`](CHANGELOG.md).

| Step | What happens | Flag |
|---|---|---|
| **Share** | reads and writes BIO share codes (`BIO-MODLIST-V1:`), keeping every field BIO put in them | `--bio-code` `--emit-bio-code` |
| **Import** | reads a Project Infinity / Infinity Mod Forge list (`LABEL;description`), each LABEL resolved from the mods' own tp2s | `--pi-list list.txt:EET` |
| **Choose** | every mod lcc-docs, BWS-NG and krion64 know, with games, status, quality and the newest version any of them names; with a WeiDU.log, which installed mods have an update | `--list-mods PATH` |
| **Name** | each staged mod's components named exactly as WeiDU names them, in your language, from its tp2 and `.tra` files | `--describe-mods PATH` |
| **Fetch** | resolves each mod from its catalogue entry, GitHub release or trusted owner; refuses an HTML page served as an archive | *(default)* |
| **Verify** | magic bytes, size and ratio limits, path-traversal checks, the mod's own `.tp2`, pinned `sha256` | *(always)* |
| **Order** | sorts every component against the BWS-NG and krion64 rule data, then re-checks the result | `--plan-order DIR` |
| **Order** at component level | splits a mod across the install where krion64 or a component rule places its parts apart | *(with `--plan-order`)* |
| **Resolve** | removes the components an error-graded incompatibility rule pins, and the earlier of two options of one WeiDU subcomponent group; lists the rest for you | `--resolve-conflicts` |
| **Limits** | kits (256), spell states and spell ids per level (50), per install, against the limits WeiDU and the engine actually have - measured in the game folder when the log is in one, else estimated from krion64; warnings, never a block | *(with the conflict report)* |
| **Decide** | every conflict comes with its options (drop a side, reorder, install what is missing) and their cost; your choice, by option id, is applied to the plan and re-checked | `--decisions decisions.json` |
| **Simulate** | walks the plan as WeiDU will: each mod's own tp2 REQUIRE/FORBID/GAME_IS, the game turning into EET, EET's merge allow-list; lists every refusal | `--simulate` |
| **Game folders** | identifies BG:EE / BG2:EE / EET the way WeiDU does; refuses a modded BG2:EE, missing SoD, swapped folders | `--bgee-dir` `--bg2ee-dir` |
| **Language** | each mod in the first of your languages it offers, read from its own tp2 | `--language-preference it_IT,en_US` |
| **Install** | `install-eet.sh` / `.cmd`: hands both logs to [mod_installer](https://github.com/dark0dave/mod_installer) + WeiDU, BGEE first, then EET | `--emit-installer` |

## Contents

- [From WeiDU logs to a running EET game](#from-weidu-logs-to-a-running-eet-game)
- [Install](#install) · [The wizard (GUI)](#the-wizard-gui)
- [Checking the install](#checking-the-install) · [Backing up the game folder](#backing-up-the-game-folder)
- [Making it reproducible](#making-it-reproducible)
- [Supplementary catalogues](#supplementary-catalogues)
- [Community data, kept current](#community-data-kept-current)
- [Sharing a list with BIO](#sharing-a-list-with-bio)
- [Lists from Project Infinity and Infinity Mod Forge](#lists-from-project-infinity-and-infinity-mod-forge)
- [Choosing mods: names and updates](#choosing-mods-names-and-updates)
- [Planning the install order](#planning-the-install-order)
- [What it guarantees](#what-it-guarantees) · [What it deliberately does not do](#what-it-deliberately-does-not-do)
- [Development](#development) · [Documentation](#documentation)

## From WeiDU logs to a running EET game

```bash
# 0. nothing to clone: lcc-docs, BigWorldSetup-NG and krion64 are fetched into a
#    cache and kept current automatically when a run starts (ADR-0032)

# 1. fetch and verify every mod the logs name
python3 -m iemod_fetch -m mod_downloads.json \
    -w WeiDU.log:EET -w WeiDUBGEE.log:BGEE -t ./Mods

# 2. plan the order, resolve what the rules decide, write the installer
python3 -m iemod_fetch --check-only -m mod_downloads.json \
    -w WeiDU.log:EET -w WeiDUBGEE.log:BGEE -t ./Mods \
    --plan-order ./plan --resolve-conflicts --simulate --emit-installer \
    --bgee-dir ~/games/BGEE --bg2ee-dir ~/games/EET \
    --language-preference it_IT,en_US          # optional: Italian, else English

# 3. install onto CLEAN copies of both games (needs WeiDU + mod_installer)
BGEE_DIR=~/games/BGEE BG2EE_DIR=~/games/EET sh ./plan/install-eet.sh
#   Windows:  set BGEE_DIR=... & set BG2EE_DIR=... & plan\install-eet.cmd
```

Step 3 refuses a folder that is not a game, a game that already has mods, and
(on Linux) mixed-case mod folders, before anything runs. `DRY_RUN=1` prints the
command instead of running it. One game only? Pass one log and run
`install.sh` / `install.cmd` with `GAME_DIR`. The full walk-through, including
what to download and what is not guaranteed, is
[chapter 10 of the guide](docs/GUIDE.md#10-from-plan-to-a-running-game-eet-bgee-or-bg2ee-on-windows-or-linux).

It replaces `fetch_mod_extended_final_complete_ultimo4.py`. See `docs/AUDIT.md`
for why, `docs/ADR.md` for the design decisions, `docs/GUIDE.md` to use it.

## Install

Python **3.14** (ADR-0043: one version, the one in `.python-version`; an
older Python is told so and stops). Where the system's Python is older
(Debian trixie's is 3.13, Ubuntu 24.04's 3.12, macOS's own `python3` 3.9),
take a release bundle, which carries its own: `iemod-fetch-cli-<os>-<arch>.zip`
for the command line (Linux x86_64: Debian trixie, the minimum platform, where
each release is started before it is published, and Ubuntu 24.04, where it is
built; not Debian 12 or Ubuntu 22.04, whose glibc is too old - Windows x86_64,
macOS on Apple silicon), `iemod-fetch-gui-...` for the wizard. Unzip it and run
`iemod-fetch` inside the folder; it is attested and in `SHA256SUMS` like the
other assets, and not signed by a publisher (see below). On macOS, a zip
downloaded with a browser is quarantined: `xattr -dr com.apple.quarantine
iemod-fetch` once, in the folder you unzipped it to.

```bash
# One file, its one library inside — on Python 3.14.
python3 build.py            # -> ./iemod-fetch.pyz
./iemod-fetch.pyz --help    # POSIX;  py iemod-fetch.pyz --help  on Windows

# Or as a package, straight from the repository (it is not on PyPI yet).
pip install git+https://github.com/gsamuele78/iemod-fetch   # then: iemod-fetch --help
```

**RAR and 7z archives** (about half of the catalogue's direct downloads are
.rar, .7z or .exe) are opened with tools of the system, never shipped
(ADR-0047): libarchive's bsdtar first - built into Windows 10 and 11 as
`tar.exe` and into macOS; on Debian and Ubuntu `apt install libarchive-tools
unar` - then unar, then a 7-Zip or WinRAR you have installed. Debian's own
`7zip` package cannot read RAR. Measured on the catalogue's 105 RAR archives,
libarchive opens 95, with unar 100 to 103; two archives need the official
7-Zip or WinRAR.

### The wizard (GUI)

A desktop wizard on the same tool (milestone M3, released in 3.0.0; ADR-0031): a
PySide6 app that reaches the tool only through `iemod_fetch.api`, in BWS-NG's
phases. It is separate from the CLI, which stays one standard-library file.

```bash
pip install "iemod-fetch[gui] @ git+https://github.com/gsamuele78/iemod-fetch"
iemod-fetch-gui --project ~/eet-build      # the folder that keeps the project
```

**Without Python** (ADR-0040): from 3.0.0, each GitHub release
carries `iemod-fetch-gui-<os>-<arch>.zip` for Linux and Windows; a macOS zip
is added minutes later, once GitHub's macOS runner built it. Unzip it (with
`unzip` or your desktop's archive tool, which keep its links) and run
`iemod-fetch-gui` inside; it is
attested and listed in `SHA256SUMS` like the other assets. It is one folder,
not one file, so Qt's libraries stay separate and replaceable (Qt is
LGPL-3.0; the licence texts and `NOTICE-Qt.txt` are in the folder, and on
Linux `NOTICE-system-libraries.txt` names each library taken from the build
system with its licence and source, ADR-0058). It is not
signed by a publisher: Windows SmartScreen warns, and macOS refuses it until
you allow it (System Settings, Privacy & Security, Open Anyway). `iemod-fetch-gui --check` opens the window and closes it
at once - the release's own test that a build starts.

On Linux the zip uses the system's graphics, font and window libraries
(ADR-0056). A desktop install usually has them; a minimal one may not, and
the wizard then stops with `libGL.so.1: cannot open shared object file`.
Measured in fresh containers on 4.0.1, everything it may need:

```bash
# Debian 13, Ubuntu 24.04 and later
sudo apt install libegl1 libgl1 libx11-6 libdbus-1-3 libfontconfig1 libfreetype6 \
  libglib2.0-0t64 libxkbcommon0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
  libxcb-keysyms1 libxcb-render-util0 libxcb-render0 libxcb-shape0 libxcb-util1 \
  libxcb-xkb1 libxkbcommon-x11-0 libwayland-cursor0
# Fedora (44)
sudo dnf install libglvnd-egl libglvnd-glx libX11 dbus-libs fontconfig freetype \
  libxkbcommon xcb-util-cursor xcb-util-wm xcb-util-image xcb-util-keysyms \
  xcb-util-renderutil xcb-util libxkbcommon-x11 libwayland-cursor
# Arch
sudo pacman -S libglvnd libx11 fontconfig freetype2 libxkbcommon xcb-util-cursor \
  xcb-util-wm xcb-util-image xcb-util-keysyms xcb-util-renderutil xcb-util \
  libxkbcommon-x11
```

The `libxcb-*`/`xcb-util-*` packages are what opens the window on an X11 or
XWayland desktop (Qt 6.5 and later need `libxcb-cursor`); the rest is what
the wizard needs to start at all. The command-line zip needs none of them.
The `bundles-distros` workflow measures each release again on these
distributions.

**Testing on a real machine**: [`docs/GUIDA-TEST-REALE.md`](docs/GUIDA-TEST-REALE.md)
(in Italian) walks through a real install on Debian trixie, Ubuntu 24.04+,
Bazzite and CachyOS with the games from GOG or Steam - working copies, the
system packages measured per distribution, two test rounds, what to collect
and send back.

**Phase 1, game and folders**: choose EET, BG:EE or BG2:EE, point
at the game folders - checked as WeiDU's GAME_IS sees them while you type, so
swapped folders, an EET-converted BG2:EE or a BG:EE without Siege of
Dragonspear are named before you go on - and the languages to install in.
Next saves `iemod-fetch.ini` in the project folder, the file the CLI reads:
`iemod-fetch` run there uses the same folders and languages, so the command
line can carry on where the wizard stops.

**Phase 2, mod selection**: categories down the left, search and filters
(chosen only, conflicts only, updates available, maybe updated - lcc-docs
lists a change after the day your copy was fetched, a date and never a
version, ADR-0044 - and kinds disagree) above a
mod -> component tree, details on
the right - with krion64's notes on the mod and, from its daily scan, the
repository's last push, whether it was archived and the release notes, as
plain text with the day of krion64's data (ADR-0059). The list loads in a background thread and works offline from the
last good community data. Components come from the mod's own tp2 once it is
downloaded, else from krion64's records - which have 1,471 of the 1,529
components WeiDU lists for 105 real mods (ADR-0035) - and each mod says which.
Choosing one of a SUBCOMPONENT's options clears the others, and a component
brings the ones it needs; unticking one that chosen ones need asks first -
untick those too, keep it, or untick it alone. *Resolve for this component*
chooses what it is missing (one alternative of an "any one of") and keeps it
against the errors that name it, after showing what it would do; warnings stay
yours. A mod ticked whole takes one option of each SUBCOMPONENT group (the one
already chosen, else the first), and keeps one of a FORCED_SUBCOMPONENT group.
A mod whose components nobody describes cannot be
chosen yet, and says so. Next writes `selection.json`, which the CLI reads
with `--selection`.

**Presets**: *Save preset...* keeps the choice as a selection.json, the
same file the project keeps (`--selection` reads it); *Load preset...*
chooses what a selection.json, a WeiDU.log, a BIO share code or a Project
Infinity list chooses, matched to the list whatever its case or `setup-`
spelling. Components the list does not have are named, not guessed.

The **Conflicts** tab checks the selection against the same rules a run uses,
in the background, shortly after each change: every conflict with its options
as buttons. *Deselect* unchooses that side in the tree (for EET, the tp2 the
rule names, not every tp2 in the folder); *Choose* adds a missing prerequisite
when the list knows its components; *Accept...* (you give the reason) is
written to `decisions.json` in the project, which the CLI applies with
`--decisions` - the ids are the ones a planned run reports, even before the
order data is downloaded, so the wizard and the command line agree on what was
decided. An order conflict the planned order could not settle is explained,
not offered as a choice. A
conflict the planned install order already settles is counted, not listed as
work; the filter *Conflicts only* shows the mods still to decide. Decisions
that no longer match any conflict (the mod is gone, or an older build saved
them) are counted, and *Forget them...* removes them from `decisions.json`
after asking.

**Phase 3, install order**: the chosen components in the order the run will
install them, planned by the same planner as `--plan-order`, one tab per
install - for EET, *BG:EE before the conversion* and *EET*, as krion64's
categories place each component (the selection is saved as those two
installs). A mod a rule places is shown in bold; one an order rule still finds
in the wrong place is red, with the rule below. Drag a mod to move it: the
whole order is saved as `install-order.txt`, a Project Infinity Sorting Order
file, and the project's ini names it (read relative to the ini), so
`iemod-fetch --config PROJECT/iemod-fetch.ini --selection PROJECT/selection.json
--plan-order PLAN` plans the same order. Your order goes on top of the rules;
where it contradicts one, that is shown, not silently won. *Split into
components* turns the selected mod into one row per component, so one of them
can be dragged on its own (saved as `tp2 n` lines); *Join the parts* puts
them back in one row, keeping your other moves. A drop is checked at once against the
rules the moved row is in, and marked red before the plan comes back. *Fix...* on a red
row offers what mends it - just after or just before the mod the rule names, planned
again with your other moves kept, or turned off - each previewed, and applied only if
it breaks no other rule and adds no error. Under the list, the selected row's rules -
red where broken, dimmed where they name a whole mod; *Ignore...* keeps a red row as your
call, with why, in `decisions.json`, until it is dragged or breaks another rule. Several
rows can be selected and dragged together, moved with Ctrl+Up / Ctrl+Down, or found by
name. *Use the computed order* forgets it. WeiDU's prompts are answered at install
(phase 5): from a log's `// @wlb-inputs:` answers, else by asking you; what each
question got is recorded in `install-plan/answers.json` (ADR-0045), and what
each component came to in `install-plan/results.json` (ADR-0053): installed,
installed with warnings, not installed because of errors, or not reached.
These come from WeiDU's own `WSETUP.DEBUG`, checked against the game's
WeiDU.log before and after the run. Where the two disagree, the log wins.
Only BWS-NG describes prompts as data, for 4 components (ADR-0036).

**Phase 4, download and extraction** (ADR-0039): *Download* fetches every mod
of the selection, checks it, unpacks it and checks it holds the tp2 it must,
then puts it in the project's mod folder (`Mods`, or the ini's `target`). A
row per mod says where it is: downloading (bytes of total), extracting, done,
already there, failed, no download found. *Cancel* stops at the next chunk;
what finished stays, and running again skips every mod already there and
verified. *Retry the failed* runs only those. It is the command line's own run,
`iemod-fetch --config PROJECT/iemod-fetch.ini --selection PROJECT/selection.json`
in the project folder, so either can carry on from the other. With no
`manifest` in the project's ini, mods are found through the lcc-docs catalogue
in the data cache: on the supplied 145-mod EET log, 138 have a candidate there
(114 a GitHub repository, 23 only a landing page, the weakest), and 7 do not,
because lcc-docs names them otherwise. A `manifest` in the ini still comes
first. The command line does the same in the project when no
`mod_downloads.json` is there (a manifest named with `-m` must exist).
Back is locked while a download runs, and a changed selection starts the
phase again. On Windows a file an antivirus holds for a moment is waited for (up to about
5 s) rather than failing the download or the extraction, and a mod moves into
the mods folder whole or not at all (ADR-0050).
A mod this tool cannot download, because its page is behind Cloudflare,
a JavaScript button or a login (Gibberlings3, SHS, Nexus), can be supplied
by hand (ADR-0052). Select its row, then *Open the mod's page* and save the
file in your browser, then *Choose the saved file...*. The file is checked
as a download is checked: it must be an archive under the byte ceiling,
holding this mod with its tp2, and must match the manifest's sha256 when
one is pinned. Only the file you choose is read; no folder is scanned or
watched.

**Phase 5, installation** (ADR-0045, ADR-0046): the install itself, in three
steps that are each yours.
1. *The programs*: mod_installer (the wizard's bundle carries 16.0.0) and WeiDU,
   found where you point, in the bundle, on PATH, or - WeiDU only - downloaded
   from its official release after a confirmation naming its source and licence
   (GPL-2.0), checked against its sha256. What is wrong with one is said as is.
2. *A backup of each game folder* (ADR-0042): *Back up now*, or one made before.
   Without it, *Install* stays off.
3. *Install*, after a last confirmation - which also names a known upstream fault
   the install will meet, without refusing it (today: EET's core and a Documents
   folder registered with a space, on Windows - EET's settings would go to a folder the
   game never reads; ADR-0045): the order of phase 3 is written to
   `PROJECT/install-plan/` (as `--plan-order` writes it) and mod_installer runs
   over it. Before that, the questions the mods will ask are put to you in one
   window (ADR-0049): those whose place in the order is sure - not under a
   condition, not printed from a variable, none after a question asked until
   valid, and none after a component of the same mod that may still ask -
   and, during the install, every other question whose text is known: it is
   recognised when mod_installer shows it and answered by question.
   mod_installer itself only shows a question holding one of its choice
   words ("enter", "choose", "do you want"...), so each install gives it a
   parser config of its own (`install-plan/mod_installer-config/`, never your
   own settings) that adds the plan's known questions, each from a line as
   WeiDU prints it (ADR-0057): of the 37 known question texts of 105 mods,
   11 had none of those words and would wait 3 hours; each now gets a phrase
   (checked with the real mod_installer on synthetic mods, not yet on those
   11 mods themselves). Measured on 105 mods, that is still few questions (most sit
   under a condition): the others are asked during the install, as before,
   until a question can be recognised when it comes. Your answers are kept in `PROJECT/install-answers.json`, so the
   next install does not ask again, and written into the planned logs as
   `// @wlb-inputs:`; the confirmation lists the components that may still stop
   to ask. Its output shows as it comes; a question no recorded answer covers
   is asked in a dialog; *Cancel* stops it and everything it started. At the
   end, the components that need a look (warnings, errors, not reached) are
   listed and all are counted, and if EEex is in the game played, how to start
   it (InfinityLoader.exe) is said. Ten minutes without output and no
   question is said, once per silence, with the last lines, and nothing is stopped
   (ADR-0049); each run records each batch's longest silence in
   `install-plan/results.json`. The confirmation also says when a game's drive
   may lack room for the install (an estimate) or WeiDU is older than tested or
   than a mod requires - a warning, never a refusal (ADR-0055). Nothing is
   undone by itself: to start again, restore the backup
   (`iemod-fetch --restore-backup`). The command line still runs nothing: its
   scripts are for you to run (ADR-0022). The game must be closed (ADR-0051):
   a program running from a game folder, or on Windows a `dialog.tlk` held
   open, stops *Install* before it starts. One started during the install is
   said once in the output, but mod_installer starts each batch itself, so it
   is not stopped.
4. *Resume* after a failure or a Cancel: each game's own WeiDU.log says what went
   in. When it is the plan's beginning, the page says "N of M components are in"
   and *Install* runs only the rest - nothing in is installed again (mod_installer's
   own skip reads `weidu.log` and, on Linux, would). When it is not, the page names
   the lines that differ and installs nothing: restore the backup. The same when a
   Cancel stopped a component half-way: its files are in the game but not in the
   log, and WeiDU installing it again would keep them as the originals.

### Verifying a release download

```bash
sha256sum iemod-fetch.pyz                                        # against SHA256SUMS
gh attestation verify iemod-fetch.pyz --repo gsamuele78/iemod-fetch
```

The build is reproducible, so you can also check the artifact against the source
yourself: `git checkout vX.Y.Z && python3 build.py && cmp` — see
[`docs/RELEASING.md`](docs/RELEASING.md).

Copy that one file next to your game install. Or run from source with
`python3 -m iemod_fetch`. Both are the same code; the tests run against the
source tree and `tests/test_build_zipapp.py` runs against the built archive.

**New here? Read `docs/GUIDE.md`** — a step-by-step runbook for the real
workflow (prepare catalogue → dry run → fetch → pin → hand to IMF).

## Fetching only (for Infinity Mod Forge / Project Infinity)

```bash
# 1. see what would happen - writes nothing
python3 -m iemod_fetch -w WeiDU.log -w WeiDUBGEE.log \
    -m mod_downloads.json -t ./Mods --dry-run --json-report plan.json

# 2. resolve the 9 known name mismatches, then fetch
python3 -m iemod_fetch -w WeiDU.log -w WeiDUBGEE.log \
    -m mod_downloads.json -t ./Mods --aliases aliases.json \
    --json-report run.json

# 3. hand ./Mods to Infinity Mod Forge / Project Infinity
```

## Checking the install

```bash
python3 -m iemod_fetch --check-only -w WeiDU.log -w WeiDU-BGEE.log:BGEE \
    --rules ~/bws-ng/data/rules
```

Reports known incompatibilities, missing dependencies and install-order problems
by reading your WeiDU logs — offline, changing nothing. Errors exit non-zero;
ordering advice is a warning. Rules come from a mod's own Project Infinity
`[Metadata]` ini and/or a community rule set in the
[BigWorldSetup-Next-Generation](https://github.com/Selphira/BigWorldSetup-Next-Generation)
shape.

## Backing up the game folder

```bash
python3 -m iemod_fetch --backup ~/Games/BG2EE                 # into ~/Games/BG2EE-iemod-backups/
python3 -m iemod_fetch --verify-backup ~/Games/BG2EE-iemod-backups/<name>
python3 -m iemod_fetch --restore-backup ~/Games/BG2EE-iemod-backups/<name>          # shows the plan
python3 -m iemod_fetch --restore-backup ~/Games/BG2EE-iemod-backups/<name> --apply  # does it
```

Before an install, copy what WeiDU changes (`override/`, `lang/*/dialog*.tlk`,
the folder's root files) with their sha256, and list every other file. A
restore **deletes nothing**: files added since, and the current version of
each file put back, are moved into the backup's `displaced-<time>/`; what it
cannot put back (a listed, not copied, file that changed) is named, and the
exit code is 1. It writes only into a game folder, and only into the one
backed up unless `--restore-to` names another. Offline; see [ADR-0042](docs/ADR.md). Back up BG2:EE *before*
EET's conversion: the converted `override/` is large.

## Configuration

Put repeated options in `iemod-fetch.ini` (see `iemod-fetch.ini.example`). A flag
beats the file; the file beats the default. Sizes accept units: `max_bytes = 2GiB`.

## Making it reproducible

Your manifest pins nothing and your WeiDU logs record no versions, so a plain
run fetches whatever is "latest" today. To fix that, pin what a real run
actually fetched:

```bash
python3 -m iemod_fetch -w WeiDU.log -w WeiDUBGEE.log \
    -m mod_downloads.json -t ./Mods --aliases aliases.json \
    --emit-pinned-manifest mod_downloads.pinned.json
```

`mod_downloads.pinned.json` is the same schema with `release_tag`, `asset` and
`sha256` filled in. Commit it and use it as `-m` from then on: every future run
verifies each download byte-for-byte and refuses anything that changed. Add
`--refresh` to also pin mods already installed.

The tool also reads each installed mod's own `.tp2` and records the `VERSION` it
declares — so mods fetched from a forum page, which have no release tag, still
end up with a recorded version. That is also where the compatibility check comes
from: `GAME_IS` in the mod itself outranks any catalogue's guess.

## When Infinity Mod Forge regenerates the catalogue

Regeneration is expected, not a problem — nothing in the tool hardcodes a mod,
a repository or a count (`tests/test_manifest_evolution.py` pins the behaviour
for each way a regenerated file can differ). Two things do **not** survive
regeneration, because IMF rewrites the file from scratch: your `sha256` pins
and the manifest corrections. Re-apply both in one step:

```bash
python3 tools/apply_corrections.py \
    -i mod_downloads.json \
    --merge-pins-from mod_downloads.pinned.json \
    -o mod_downloads.ready.json
```

What changes safely: reordered entries, added mods, removed mods, changed URLs
or repos, new unknown fields (warned, not fatal). What breaks loudly with exit
2 and nothing written: a missing/empty `mods` array, duplicate or unsafe `tp2`
keys, a malformed `sha256`. What needs a human: a **renamed `tp2` key**, which
breaks the join and any alias pointing at it — reported as unresolved, with the
renamed entry offered as a suggestion.

## Finding mods the catalogue no longer points at

38 entries have no `github` field, and five point at `SpellholdStudios` — the
account SHS abandoned in 2022 (the mods moved to `Spellhold-Studios`). When a
catalogue entry fails to resolve, the tool looks for the mod in an allowlist of
**trusted owners**: the shipped modding houses plus every owner your manifest
already uses.

This is not the global GitHub search the old script used. The search space is
bounded to owners you already trust, and a hit is still only a candidate — it
is installed only if it actually contains `<folder>.tp2`. Whatever it resolves
is printed as a ready-to-paste `"github"` value so you can promote it into the
manifest and stop guessing:

```
 DISCOVERED SOURCES - promote these into your manifest
   "tp2": "arath", "github": "Spellhold-Studios/Arath_NPC"
```

`--no-discovery` turns it off; `--trusted-owner OWNER` extends the allowlist;
`--trusted-owners FILE` replaces it.

## Supplementary catalogues

`mod_downloads.json` knows one URL per mod. The community keeps richer lists —
the La Couronne de Cuivre database (<https://github.com/RiwsPy/lcc-docs>, MIT)
has ~2,100 WeiDU mods with every known URL, a maintenance status and a quality
rating, and it covers 142 of the 148 mods in the supplied logs.

It is in the data cache every run keeps current (see *Community data, kept
current* below), so it is used as a fallback and advisory source with no flag.
To bake its results into your manifest once:

```bash
python3 tools/enrich_from_lcc.py -i mod_downloads.json \
    -c "$(python3 -c 'from iemod_fetch.datasync import *; print(data_paths(default_data_dir()).catalogue)')" \
    -o mod_downloads.enriched.json
```

On the supplied manifest that fills in 12 missing repositories — including
`haerdalisromance` → `Spellhold-Studios/HaerDalis-Romance` — taking entries that
need a landing-page scrape from 41 down to 26. It also copies the catalogue's
health warnings into the report, so a mod marked beta, archived or obsolete says
so during the run.

Within a catalogue entry the order is **direct archive URL → repository →
landing page**. About 12% of the catalogue's mods carry a URL that *is* the
archive (its page marks them with a padlock); those need no API call and leave
no ambiguity about which release asset is meant.

A catalogue hit is still only a candidate: it is installed only if the archive
contains the right `.tp2`. The catalogue is never bundled: it comes from the
data cache (or the path you pass).

Each community source is used for what it measures best (ADR-0036, measured on
2026-10-22 with `tools/download_sources_benchmark.py --bws ... --probe`):

| What | From | Why |
|---|---|---|
| where a mod lives | lcc-docs | 1,148 EE mods; where it and krion64 disagree, krion64's repository is gone in 27 of 113, lcc-docs' in none |
| the exact file and its sha256 | BWS-NG | 409 exact files, 335 with their sha256; 279 of 280 pinned release tags still exist - but the pinned version is older than the newest in 48 of 228 comparable mods |
| components before download | krion64 | 1,047 of 1,089 WeiDU components on the 67 mods all three know, BWS-NG 1,023 |
| conflicts and install order | krion64 and BWS-NG | as before |

BWS-NG is also the only source that describes WeiDU prompts as data, for 4
components; the wizard's install answers prompts from the logs or asks (ADR-0045).

### Health warnings

With a catalogue loaded, mods the community marks beta, archived, obsolete or
"may cause problems" are printed as they install, and collected at the end:

```
[+] eefixpack: installed SETUP-EEFIXPACK.TP2 (1,234,567 bytes, v9.2)
    ^ mods.json rates this mod 'may cause problems'
    ^ mods.json status: beta (last updated 2026-08-14)
```

They never block a download — they are information, not a verdict.

### Per-game compatibility

Compatibility is judged **per WeiDU log**, because a mod that is wrong for one
install is right for another. EET is detected automatically (a log that installs
the `eet` mod is an EET install); name the others yourself:

```bash
python3 -m iemod_fetch -w WeiDU.log -w WeiDUBGEE.log:BGEE \
    -c ~/lcc-docs/db/mods.json -t ./Mods
```

An unknown game produces no warnings at all — a confident false positive is
worse than silence. On the supplied logs this yields two real flags
(`BloodiedStingsOfBarovia`, `impasylum`) and correctly stays quiet about
`bg1ub`, which is BGEE-only and lives in the BGEE log.

## Manifest corrections

`tools/corrections.json` records reviewed fixes to the catalogue - each with a
reason, its evidence and a confidence level - and `tools/apply_corrections.py`
applies them:

```bash
python3 tools/apply_corrections.py -i mod_downloads.json -o mod_downloads.fixed.json
```

Currently: three mods migrated to GitHub (`SirinesCall`, `FishingForTrouble`,
`FowlWish` - the last had a URL pointing at a user profile, so it could never
resolve) and one URL switched to https. That takes the catalogue from three
cleartext `http://` entries to zero. **Review `tools/corrections.json` before
trusting it** - a repository found by search is a strong hint, not proof it is
the same mod your log installed.

Exit codes: `0` success · `1` failures or unresolved mods · `2` bad configuration.

## What it guarantees

* The credential goes only to `api.github.com` / `github.com`, never to a mod
  forum, and never survives a redirect off those hosts.
* A value from git's credential helper is used only if it has the shape of a
  GitHub token (including 2026's stateless `ghs_` installation tokens), so a
  stored password is not mistaken for one - and a credential only ever goes to
  GitHub itself.
* Nothing is extracted until it has been identified by magic bytes, kept under a
  size ceiling, and (when the manifest pins a `sha256`) verified.
* No archive member can be written outside its staging directory.
* An existing mod directory is never deleted — conflicts are reported, and
  `--force` moves the old copy to `.backup/`.
* A mod is "installed" only if the extracted tree contains `<folder>.tp2` or
  `setup-<folder>.tp2`. Nothing else counts.
* Re-runs are idempotent; every fetch is recorded in `Mods/.iemod-fetch-state.json`.

## What it deliberately does not do

* **Guess.** No repo-name mutation, no GitHub search fallback, no first-plausible-
  link-on-the-page. Unresolvable mods are reported with a reason and a suggestion.
* **Run installers.** `.exe` files are unpacked only with `--allow-exe`, and are
  never executed.
* **Run WeiDU itself.** It produces verified mod folders, the order to install
  them in and — with `--emit-installer` — a script that hands both to
  mod_installer. You read the script and run it; iemod-fetch never executes
  WeiDU, mod_installer or the script (ADR-0022).
* **Fix an installed game.** `--plan-order` writes an install plan for a FRESH
  install. WeiDU installs in file order; changing the order after the fact means
  reinstalling.
* **Pick a side it was not told to.** `--resolve-conflicts` removes only the
  components an error-graded, non-speculative rule pins. "Not both" with no
  side named, same-mod option groups, missing dependencies: reported, your call
  (ADR-0021). Your own logs are never edited — only the plan.

## Layout

```
iemod_fetch/     the tool
iemod_fetch_gui/ the PySide6 wizard (optional; imports only iemod_fetch.api)
legacy/          the original script, kept so its defects stay reproducible
tests/           ~1,000 offline tests: characterization, example, property-based, loopback, script execution
tests/data/      your real manifest and WeiDU logs, used as fixtures
aliases.json     the 9 reviewed folder -> catalogue-key mappings
docs/            INDEX.md, GUIDE.md, ARCHITECTURE.md, TESTING.md,
                 SECURITY-MODEL.md, ADR.md, AUDIT.md, PLAN.md,
                 ROADMAP.md, RELEASING.md
```

## Tests

The CI gate - what a pull request and a release must pass - runs on Linux and
Windows, on the one Python of `.python-version` (3.14). macOS runs the same suite in a separate,
informational workflow: it is reported, never blocking.

```bash
python3 -m pytest -q      # 2,095 collected; a few skip (platform/opt-in; the GUI tests need .[guitest]), no network
```

Some measurements need the network and run as their own workflows: which
open-source tool extracts the catalogue's RAR archives as 7-Zip does, on
Debian trixie (the minimum platform), Windows and macOS, is
`tools/rar_measure.py` in the `RAR extractors` workflow (docs/TESTING.md).
What holds the wizard's window during a download, on Linux and Windows, is
traced by the `GUI latency` workflow (`tools/gui_latency_summary.py`).
Which questions the mods of a build ask while installing is measured by
`tools/readln_census.py` on their WeiDU files (ADR-0049).

## Community data, kept current

The order, the conflicts and the list of mods come from lcc-docs,
BigWorldSetup-NG and krion64. Nothing is cloned: each run refreshes a per-user
cache first, at most once a day, fetching only the files the tool reads and
only those that changed, and uses it wherever `--catalogue`, `--rules`,
`--mod-db`, `--order-catalogue`, `--eet-sequence` or `--releases` was not
given (ADR-0032).

Every update passes a guard before it replaces the last good copy: each file
must be valid JSON, the copy must parse with the tool's own readers, and no
count (mods, rules, order entries) may be zero or fall below half of the last
good copy's - what a format change upstream looks like. A refused update is
reported, the last good copy stays, and that commit is not fetched again. An
accepted one is reported with what changed. For example (illustrative numbers):

```
$ python3 iemod-fetch.pyz --update-data
  data        : lcc-docs: updated to 1a2b3c4 (2026-11-02), 3 file(s) fetched, 0 removed
                mods 1834 -> 1838; 4 added, 0 removed, 2 changed
                added: newmod1, newmod2, newmod3, newmod4
                oldmod: stable (2019-01-01) -> obsolete (2019-01-01)
  data        : krion64: update REFUSED by the guard - 9f8e7d6 refused: rules collapsed
                from 859 to 12; a format change upstream is the likely cause; keeping a8d17c4 (2026-10-19)
```

`--no-update-data` stays offline, `--no-default-data` uses only the flags,
`--data-dir` moves the cache. The wizard and the CLI share it: a refresh
with something to do holds `<data dir>/.lock`. While another program holds
it, `--update-data` waits (up to five minutes) and an ordinary run goes on at
once with the last good copy, saying so. The lock goes with the program that
held it. The pinned WeiDU and mod_installer used by the
test suite are watched the same way, weekly, by `upstream-versions.yml`.

GitHub's answers (each mod's latest release, the data's HEAD) are kept beside
the cache, in `<data dir>-http`, with their ETag: the next run asks
"changed since?", and an unchanged answer comes back empty. With a token
(`GH_TOKEN`) such an answer does not count against GitHub's hourly limit;
without one it still counts, and saves only the download. One small file is
kept per question asked; the data's file lists, which change with every
commit, are not kept. Deleting the folder is always safe.

## Sharing a list with BIO

A mod list shared from [Born2BSalty's Infinity Orchestrator](https://github.com/Born2BSalty/Born2BSaltys_Infinity_Orchestrator)
is one line, `BIO-MODLIST-V1:...`. Save it in a file and use it in place of the
WeiDU logs, or turn any list into one:

```bash
python3 iemod-fetch.pyz --bio-code shared.bio -m mod_downloads.json        # fetch what it lists
python3 iemod-fetch.pyz -w WeiDU.log:EET -w WeiDUBGEE.log:BGEE \
    --emit-bio-code mylist.bio --check-only                                # share yours
```

Nothing is lost either way: a code BIO made decodes and re-encodes to the
same payload, byte for byte, and exporting an imported list keeps its name, author, download
overrides, pinned refs and mod configs. Tested against BIO's own encoder and
decoder (docs/TESTING.md). Only the format is implemented; no BIO code is used.

## Lists from Project Infinity and Infinity Mod Forge

```bash
python3 iemod-fetch.pyz --pi-list install-EET.txt:EET --emit-selection selection.json --check-only
```

A PI list names each component by its WeiDU LABEL. The LABEL is looked up in
the staged mods' own tp2s, read the way WeiDU reads them; for a mod not
fetched yet, in krion64's records, which agree with the tp2s for 708 of 732
LABELs - so each entry resolved that way is listed, and the tp2 always wins
once the mod is there - a staged tp2 without the LABEL is an error, not a
fallback to krion64. An entry neither resolves is an error naming the line,
never a guess from its description.

A mod that ships its own `mod-forge.json` (Infinity Mod Forge's format for
authors) has its conflicts, dependencies and known issues read into the
check once it is staged. Component numbers may be written as `"#0 #1"`, a
number or a list; a malformed entry is skipped, never a crash. None of the 103 mods measured ships one yet.

## Choosing mods: names and updates

```bash
# every mod there is to choose from, as JSON - and, given your log, what to update
python3 iemod-fetch.pyz --list-mods mods.json -w WeiDU.log:EET

# the components of the mods staged in ./Mods, named as WeiDU names them
python3 iemod-fetch.pyz --describe-mods components.json --language-preference it_IT,en_US
```

A run with `-w` also prints which installed mods have a newer version:

```
  updates     : 2 of 41 installed mods with a version have a newer one
    eet                      v14.0 -> v14.1 (github release, 2025-04-07)
    SirinesCall              v16.5.1 -> 16.5.2 (BigWorldSetup-Next-Generation)
```

Both are measured, not assumed (docs/TESTING.md):

* **Component names** match WeiDU 251's own `--list-components` on 9,889 of
  9,889 lines from 103 real mods. A name WeiDU itself cannot resolve is shown
  as WeiDU shows it (`UNDEFINED STRING:   @N`) and flagged. Each component's
  subgroup, groups, labels, forced and deprecated flags match WeiDU's
  `--list-components-json` on 1,499 of 1,499 components.
* **The newest version** is the newest of the mod's latest GitHub release
  (krion64's release cache), BWS-NG and krion64. Against the mods' own tp2
  VERSION that agrees for 79 of 90 mods; any one source alone, 42 to 67.
  The installed version is read from WeiDU.log lines as WeiDU 251 writes
  them (`Name: VERSION`): 1,409 of 1,409 right, none wrong.
* `update_available` is `null`, never a guess, when two versions cannot be
  ranked. Known blind spot: a release tagged without bumping the tp2 VERSION
  (EET's v14.1 tag carries VERSION v14.0) still shows as an update after it is
  installed.
* **A mod's kind** is what lcc-docs and BWS-NG say, mapped onto one
  vocabulary (`kinds`, and `kinds_by_source` for who says what), with
  krion64's `install_category` and `tags` beside it, never mapped. Where two
  sources share no kind, `kind_disagreement` is `true` and nothing is chosen:
  on the 2026-10-23 data, 1 of 1,843 mods (all 15 BWS-NG codes and 17
  lcc-docs labels are mapped).

The formats are `schemas/mods-v1.schema.json` and
`schemas/components-v1.schema.json`; the GUI reads the same through
`iemod_fetch.api` (`list_mods`, `describe_mods`).

### A copy from elsewhere, a newer release on GitHub

When a mod comes from somewhere other than GitHub - an author's site, a forum
post - and krion64's release scan names a newer release of the repository
called like the mod, the run says so beside the mod and in its JSON record
(`newer`), and takes nothing unasked:

```
[+] ascension: installed Setup-Ascension.tp2 (4,128,497 bytes, v1.5 BETA)
    ^ GitHub has a newer release: 2.1.0 (Gibberlings3/Ascension, 2025-05-18);
      this copy declares v1.5 BETA. To install it instead: --take-newer ascension
```

`--take-newer FOLDER` (repeatable, or `all` for every one offered) installs
that release over the copy on disk, which is kept in `.backup/`. Only that
release, asked for by its tag: if GitHub cannot give it, the mod is left as
it is. Only when one is offered: naming a mod whose copy is as new or newer
does nothing, so `take_newer` can stay in the ini without replacing the mod
on every run. It passes the
same tp2 check as any download. No offer is made when the versions cannot be
ranked, or from a repository named otherwise than the mod - a fork, or a
maintainer's copy the tool cannot tell from one.

In the wizard, the download page shows each offer under *Newer release* with
a box to tick; *Install the ticked newer releases* runs the same take for the
ticked mods only.

## Planning the install order

```bash
python3 -m iemod_fetch --check-only \
  -m mod_downloads.json \
  -w WeiDU.log:EET -w WeiDUBGEE.log:BGEE \
  --plan-order ./plan        # rules and order catalogue: from the data cache
```

Writes `plan/WeiDU.log` and `plan/WeiDU-BGEE.log`: the same components you have,
sorted so every order rule is satisfied, and then checked against those rules
before the claim is made. Add `--resolve-conflicts` to drop the components the
rules decide must go, and `--emit-installer` for the install scripts (see
[the quick start](#from-weidu-logs-to-a-running-eet-game)).
`--reassign-phase` also moves a mod between the two
logs when the catalogue says it belongs to the other install phase — off by
default, because that changes which game the mod installs onto.

**The authors' own order** (ADR-0037). Many mods ship Project Infinity's
metadata ini, whose `Before`/`After` say what the author wants around it. The
tool always read it from a downloaded mod; `--fetch-metadata` now fetches it
for the planned mods not downloaded yet - one small text file per mod, from the
repository the catalogue names, found whatever its case, cached for a week in
the data cache; offline it backs off rather than slowing every check - and the
wizard does so for what you choose. The search, including its case-insensitive
listing, is checked weekly against the real GitHub (`mod-metadata.yml`). Measured on 85 real inis
(`tools/pi_metadata_benchmark.py`): of the 314 order pairs they state, krion64's
order agrees with 239 and a rule already covers 34 more, but 19 are known only
to the author - 7 of them contradicting krion64 (Region of Terror after IWD1_EET
and IWD2_EET, Kivan before Adrian, Deities of Faerun before Tome and Blood,
...). `--sorting-order FILE` reads a Project Infinity "Sorting Order" file
(`Ascension *`, `Ascension 101 102`) as order rules on top of the others.

The same run prints a **component conflict report**: which component of which
mod fights which component of which other mod (or of itself), with the upstream's
own evidence grade and source, and the narrowest fix — "deselect stratagems
#4115", not "these two mods conflict". Order findings the plan already resolves
are marked fixed rather than repeated. Add `--conflict-report conflicts.json`
for the full machine-readable version, `--show-advisories` for the unverified
observations withheld by default.

The report ends with the **engine limits** of each install: how many kits,
spell states and spell ids per level the chosen components add, and who adds
them. When the WeiDU.log sits in its game folder (beside `chitin.key`), the
tables are **measured** there, by WeiDU's own rules - the last kit number in
KITLIST.2DA, the spell slots ADD_SPELL would skip, the ids in SPLSTATE.IDS -
and checked against the real WeiDU in CI; krion64's counts then only cover
what the game does not have yet. Without a game folder they are krion64's
estimates, and the report says what they miss: its spell scanner does not see
ADD_SPELL, so a level can be fuller than shown. The limits are the ones in WeiDU's and the engine's own sources - 256
kits (WeiDU refuses ADD_KIT past it on every EE game), 50 wizard or priest
spells per level - not Infinity Mod Forge's 320 kits, which no source
supports. They are warnings, for every game patch. Spell states are shown but
not warned on, because the community counts include states a mod only reads
(ADR-0034).

Every outstanding finding is printed with its id and the options that clear
it, the one the rules recommend marked `*` (none on a tie):

```
          id: conflict-1887f4d4f9f06816; options:
             option-2d0badec446ba437  deselect stratagems: #4100 ...  [cost 1]
             option-a8395462ca46c2a6  deselect cdtweaks: #2370 Tweak  [cost 1]
```

Write the ones you choose into `decisions.json` - `{"finding": ..., "choose":
option-id}`, or `"accept": "why"` to keep both - and pass `--decisions
decisions.json`: your choices are applied to the plan before
`--resolve-conflicts`, which never overrides them, and the plan is re-checked.
A decision about a finding that no longer exists is reported and not applied.

See ADR-0016 for why both databases are used, ADR-0017 for what the plan does and
does not promise, ADR-0018 for how conflicts are narrowed to components,
ADR-0021 for what is resolved automatically, ADR-0022 for the installer,
ADR-0023 for component-level order, ADR-0024 for languages, ADR-0025 for the
install simulation and ADR-0026 for game folders and the real-WeiDU test.

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements/runtime.txt   # the pinned runtime, first
pip install -e ".[dev]"
pre-commit install

make check      # ruff · mypy · import-linter · pytest — exactly what CI gates on
make cover      # with the branch-coverage floor
make audit      # bandit · pip-audit
```

| Gate | State |
|---|---|
| Tests | 2,095, offline, ~30 s; the mock EET install and the engine-limit measurement also run against the **real WeiDU and mod_installer**, and the wizard under pytest-qt, in CI |
| Branch coverage | 92% (floor 85%) |
| mypy | clean, 74 source files |
| ruff | clean, with pyupgrade (`UP`) on the Python of `.python-version` |
| bandit | 0 high, 0 medium |
| Architecture contracts | 7, all kept |
| Runtime dependencies | 0 |

Testing here is not only TDD — property-based tests, architecture contracts,
static analysis and nightly mutation testing each exist for a class of defect the
others cannot see, and each has found one. [`docs/TESTING.md`](docs/TESTING.md)
says which, with the defects named.

[`CONTRIBUTING.md`](CONTRIBUTING.md) has the one rule: a change that makes the
tool guess is rejected, however convenient it is.

## Documentation

[`docs/INDEX.md`](docs/INDEX.md) — guide, architecture, testing strategy,
security model, decision records, audit, roadmap, release process.
