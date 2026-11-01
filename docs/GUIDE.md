# iemod-fetch — operator's guide

Written against your actual data: 148 mods, `WeiDU.log` (EET) + `WeiDUBGEE.log`,
`mod_downloads.json` from Infinity Mod Forge v4.1.0.

The tool does one job: **turn a WeiDU.log into verified mod folders on disk.**
It downloads, verifies and stages. It does not install — Infinity Mod Forge /
Project Infinity still does the WeiDU ordering and component selection.

---

## 0. One-time setup

```bash
tar xzf iemod-fetch.tar.gz && cd iemod-fetch
python3 -m pytest -q                 # all pass (GUI tests skip without Qt) - the copy is sound
python3 build.py                     # -> ./iemod-fetch.pyz  (about 200 KB, no deps)
```

The community catalogue that fills catalogue gaps and provides health
warnings (lcc-docs), and the rule databases (BigWorldSetup-NG, krion64), need
no setup: the first run fetches them into a cache and later runs keep it
current (§9.1).

### GitHub credential

Optional, but anonymous GitHub allows only 60 API requests/hour and your
manifest needs ~110, so without one you will be rate-limited part-way through.

The tool looks in this order, stopping at the first hit — **all but the last are
automatic**:

1. `--token-file PATH`
2. `$GH_TOKEN` / `$GITHUB_TOKEN`
3. **`gh auth token`** — if you have GitHub CLI logged in
4. **git's credential helper** — on Windows, Git Credential Manager already
   holds a GitHub token if you have ever pushed over HTTPS
5. anonymous

**On Windows with git but no gh, #4 covers you and there is nothing to set up.**
Check what it picked with the startup banner:

```
  credential  : token from git credential helper (5000 requests/hour)
```

If it says `anonymous` and you want a token, pick whichever suits you:

```powershell
# a) install GitHub CLI (also gives you gh auth token)
winget install --id GitHub.cli
gh auth login

# b) prime Git Credential Manager by pushing/cloning once over HTTPS,
#    then it is picked up automatically thereafter

# c) a fine-grained PAT with NO repository permissions (public read is enough)
setx GH_TOKEN "github_pat_..."        # new terminals only; or use --token-file
```

Whatever it finds is sent **only** to `api.github.com` and `github.com`, and is
dropped on any redirect that leaves those hosts — including GitHub's own asset
CDN. The credential-helper lookup can never prompt you or open a browser
(`credential.interactive=false`, `credential.guiPrompt=false`,
`GIT_TERMINAL_PROMPT=0`), and a stored value is only used if it actually looks
like a GitHub token, so an old username/password is never sent as a bearer.
Disable the probes with `--no-gh-cli` / `--no-git-credential`.

---

## 1. Prepare the catalogue

Two transformations, both re-runnable and both producing a reviewable diff.

```bash
# (a) apply the reviewed URL corrections: 3 cleartext http:// entries and
#     FowlWish, whose url pointed at a user profile rather than a repository
python3 tools/apply_corrections.py \
    -i mod_downloads.json -o mod_downloads.fixed.json

# (b) fill missing repositories from the community catalogue
python3 tools/enrich_from_lcc.py \
    -i mod_downloads.fixed.json -c ~/lcc-docs/db/mods.json \
    -o mod_downloads.ready.json
```

Expected on your data: 4 corrections, then 12 entries gain a GitHub repository.
Entries needing a landing-page scrape drop from 41 to 26.

**Read `tools/corrections.json` before trusting step (a).** Three of its four
entries are high-confidence repository migrations; `haerdalisromance` is only a
scheme change and is marked unverified.

---

## 2. Dry run — nothing is written

```bash
python3 -m iemod_fetch \
    -w WeiDU.log -w WeiDUBGEE.log:BGEE \
    -m mod_downloads.ready.json \
    --aliases aliases.json \
    -c ~/lcc-docs/db/mods.json \
    -t ./Mods --dry-run --json-report plan.json
```

Read `plan.json` before going further. You should see 147 of 148 resolved and
one manual (`HPS_PORTRAITS_PROJECT` — no source exists anywhere).

Note `WeiDUBGEE.log:BGEE`. EET is detected automatically from `WeiDU.log`;
naming the second log's game stops `bg1ub` being wrongly flagged as
EET-incompatible.

---

## 3. The real run

```bash
python3 -m iemod_fetch \
    -w WeiDU.log -w WeiDUBGEE.log:BGEE \
    -m mod_downloads.ready.json \
    --aliases aliases.json \
    -c ~/lcc-docs/db/mods.json \
    -t ./Mods \
    --allow-http \
    --json-report run.json \
    --emit-pinned-manifest mod_downloads.pinned.json
```

`--allow-http` is only needed if you skipped step 1(a); after the corrections
nothing in the catalogue is cleartext.

Then point Infinity Mod Forge at `./Mods`.

---

## 4. Lock it down

`mod_downloads.pinned.json` now records the exact release tag, asset name and
sha256 of everything fetched. **Commit it**, and use it as `-m` from then on:

```bash
python3 -m iemod_fetch -w WeiDU.log -w WeiDUBGEE.log:BGEE \
    -m mod_downloads.pinned.json --aliases aliases.json -t ./Mods
```

From this point a mod author re-rolling a release, or a hijacked download,
fails the run instead of being installed. Without this step every run fetches
"latest" and your install drifts.

Add `--refresh` once to also pin mods already on disk.

---

## 5. When Infinity Mod Forge regenerates the manifest

IMF rewrites `mod_downloads.json` from scratch, which **silently discards your
pins and corrections**. One command puts both back:

```bash
python3 tools/apply_corrections.py \
    -i mod_downloads.json \
    --merge-pins-from mod_downloads.pinned.json \
    -o mod_downloads.ready.json
```

Then re-run step 1(b) and you are back where you were.

Regeneration is otherwise safe: added mods, removed mods, reordering, changed
URLs and new unknown fields all work. The one thing that needs you is a
**renamed `tp2` key** — it breaks the join and any alias pointing at it, and is
reported as unresolved with the renamed entry offered as a suggestion.

## 6. Without a WeiDU.log: selection.json

A selection lists the mods, components and languages you want, one install or
two for EET (`BGEE` then `EET`), in install order. It says exactly what a
WeiDU.log says, and it is what the future GUI saves (ADR-0030). The format is
`schemas/selection-v1.schema.json`.

```json
{"schema_version": 1,
 "installs": [
   {"game": "BGEE", "components": [
      {"tp2": "eefixpack/setup-eefixpack.tp2", "component": 0, "language": 0}]},
   {"game": "EET", "components": [
      {"tp2": "EET/EET.tp2", "component": 0, "language": 0,
       "label": "EET core (resource importation)"}]}]}
```

```bash
# Use it instead of -w, for every run mode (fetch, --check-only, --plan-order):
python3 iemod-fetch.pyz --selection selection.json -t ./Mods
# Turn existing logs into one, without fetching anything:
python3 iemod-fetch.pyz -w WeiDU.log:EET -w WeiDUBGEE.log:BGEE \
    --emit-selection selection.json --check-only
```

To see what there is to choose from, `--list-mods` merges every source given -
the manifest, each `--catalogue` (lcc-docs) and `--mod-db` (BWS-NG or krion64)
- into one entry per mod: games, categories, quality rating, status, last
update, version, advisories, and each source's URLs and sha256. It needs no
WeiDU.log and downloads nothing. The format is `schemas/mods-v1.schema.json`.

```bash
python3 iemod-fetch.pyz --list-mods mods.json \
    -c lcc-docs/db/mods.json --mod-db BigWorldSetup-Next-Generation/data/mods
```

With the full lcc-docs catalogue and the BWS-NG database that is about 1,800
mods in under a second. `-` writes to standard output.

Each mod also carries `latest`: the newest version any source names - the
mod's latest GitHub release (krion64's `version_cache.json`, `--releases`,
from the data cache by default), the BWS-NG database, krion64's records - with
which source named it. Give `-w WeiDU.log` too and each installed mod says
`installed` and `update_available`; a normal run with `-w` prints the same as
a short notice:

```text
  updates     : 2 of 41 installed mods with a version have a newer one
    eet                      v14.0 -> v14.1 (github release, 2025-04-07)
    SirinesCall              v16.5.1 -> 16.5.2 (BigWorldSetup-Next-Generation)
```

`update_available` is `null`, not `false`, when either version is unknown or
the two cannot be ranked (`EAOB.9` against `v1_Beta260923`). A notice can be
wrong in one known way: an author who tags a release without bumping the
tp2's VERSION (EET's v14.1 tag, VERSION v14.0) is reported as having an
update after installing it.

For a progress bar, `--events events.jsonl` (or `-` for standard output,
best with `-q`) writes one JSON object per line as the run goes -
`run_started`, `mod_started`, `download_progress`, `mod_extracting` (the
download is complete and verified; the archive is being unpacked and checked),
`mod_finished`, `run_finished` - in the format of `schemas/events-v1.schema.json`. Ctrl-C stops
the downloads in flight at their next chunk; the mods reached are reported as
`cancelled` and the exit code is 130.

Once mods are staged, `--describe-mods components.json` lists every tp2 under
`--target` with its languages and its components, named exactly as WeiDU names
them in `--list-components` and WeiDU.log (`Group -> Name: VERSION`), in the
first `--language-preference` the mod offers. It reads the tp2 and its `.tra`
files and runs no WeiDU. A name WeiDU itself could not resolve is printed as
WeiDU prints it (`UNDEFINED STRING:   @N`) and marked `"resolved": false`.
Each component also says what a selection screen needs to group and constrain
it, with WeiDU's own names: `subgroup` (its SUBCOMPONENT: options that exclude
each other), `forced` (one of them must be chosen), `groups` (the categories
the mod files it under), `labels` (names that survive renumbering; Project
Infinity uses them) and `deprecated` (WeiDU no longer offers it). The format is
`schemas/components-v1.schema.json`.

```bash
python3 iemod-fetch.pyz --describe-mods - --target Mods --language-preference it_IT,en_US -q
```

A list shared from Born2BSalty's Infinity Orchestrator (BIO) works the same
way. Save the `BIO-MODLIST-V1:...` code in a file and pass it with
`--bio-code`: its WeiDU logs become what is wanted (BGEE then EET for an EET
list). `--emit-bio-code` writes any input - `-w`, `--selection` or a BIO code -
back as a code BIO imports; a code that came from BIO keeps its name, author,
download overrides, pinned refs and mod configuration files, which this tool
does not use but does not drop either.

```bash
python3 iemod-fetch.pyz --bio-code shared.bio --emit-selection selection.json --check-only
python3 iemod-fetch.pyz -w WeiDU.log:EET -w WeiDUBGEE.log:BGEE --emit-bio-code - --check-only -q
```

A Project Infinity list, or the `install-EET.txt` Infinity Mod Forge exports,
works the same way with `--pi-list list.txt:GAME`. Each line is
`LABEL;description` or `folder:number;description`; the LABEL is found in the
staged mods' tp2s first and in krion64's records (from the data cache) second.
Fetch the mods once with the list's krion64 resolution, then run again: the
second run resolves every LABEL from the tp2s themselves. A line nothing
resolves stops the run with the line number - the description is never used
to guess. The whole list is one install; for EET, `--reassign-phase` moves
the BG:EE mods to the BGEE log.

`--selection`, `--bio-code`, `--pi-list` and `-w` are never given together. A wrong file is refused with
where and why: an unknown key, a game that is not one, a tp2 path that leaves
its folder, or `schema_version` other than 1.

---

## Reading the output

```
[+] eefixpack: installed SETUP-EEFIXPACK.TP2 (1,234,567 bytes, v9.2)
    ^ mods.json rates this mod 'may cause problems'
    ^ mods.json status: beta (last updated 2026-08-14)
```

| Glyph | Status | Meaning |
|---|---|---|
| `[+]` | ok | downloaded, the correct `.tp2` was found, installed |
| `[-]` | skipped | already on disk and verified; nothing fetched |
| `[.]` | planned | `--dry-run` only |
| `[!]` | manual | could not resolve without guessing — reason given |
| `[!]` | conflict | destination exists; `--force` to replace (old copy kept) |
| `[x]` | failed | download, extraction or verification error |

`^` lines are health advisories from the catalogue. They never block a
download — they are information, not a verdict. On your install 13 of 148 carry
one: 11 quality/status, plus `BloodiedStingsOfBarovia` and `impasylum`, which
the catalogue does not list as EET-compatible.

A **DISCOVERED SOURCES** block lists mods resolved by catalogue or trusted-owner
lookup rather than by your manifest, as paste-ready `"github": "..."` values.
Paste them in — the guess becomes a fact and the next run is deterministic.

Exit codes: **0** success · **1** failures or unresolved mods · **2** bad
configuration. `--allow-manual` makes a partially-manual run exit 0.

---

## Checking install order and compatibility

`WeiDU.log` records every component in install order, so the soundness of the
build can be checked offline — no network, no downloads:

```bash
python3 -m iemod_fetch --check-only -w WeiDU.log -w WeiDU-BGEE.log:BGEE
# the rules (BWS-NG + krion64) and the mod database come from the data cache;
# --rules / --mod-db with your own paths still win
```

Two community sources are understood and the format is detected per file:
BWS-NG's rule lists, and krion64's per-mod records. They are worth running
together — BWS-NG's rules mostly say "any component of A conflicts with any of
B", while krion64 names exact components, so one catches more and the other is
more precise. Add `--include-optional` to also see optional integrations
("alternate portraits for X"), which are off by default.

It reports three things and changes none of them:

| | |
|---|---|
| **incompatible** | two installed components known to conflict — *error* |
| **dependency** | a component installed without its prerequisite — *error* |
| **order** | installed in an order the community advises against — *warning* |

Errors set exit code 1, warnings do not: ordering advice is heuristic and a
deliberate unusual order is a legitimate choice. Add `--rules` to a normal run
and the same section appears in the report and the JSON.

Each WeiDU log is checked **separately** — one log is one game install, so a mod
in your BGEE game is never ordered against a mod in your EET game.

Mods that ship a Project Infinity `[Metadata]` ini contribute their own
`Before=`/`After=` lists, so a mod carrying one needs no external rule at all.

### When a rule is out of date

A rule set is a snapshot, and mod authors fix things. Point the checker at the
rules' companion mod database and it will notice:

```bash
python3 -m iemod_fetch --check-only -w WeiDU.log \
    --rules ~/bws-ng/data/rules --mod-db ~/bws-ng/data/mods
```

```
 NOT COUNTED - the rule may no longer apply
   ?  infinity_ui and HiddenGameplayOptions are incompatible
      this rule may be out of date - HiddenGameplayOptions v5.2 installed,
      rules written against 5.0. Check the mod's changelog before acting on it.
```

That works because the mod declares its version in its own `.tp2` and the
database records the version the rules were built against. Findings withheld
this way never set a non-zero exit.

Three other defences: a mod's own ini overrides community **ordering** rules for
that mod (it ships with the version you downloaded, so it cannot be stale about
itself); the rule set's age is printed and flagged past 180 days; and
`--suppress suppressions.json` records rules you have checked yourself — see
`suppressions.example.json`. Note the ini channel covers ordering only: the
format says nothing about conflicts, so an incompatibility rule can only be
retired by the rule set being updated, or by you.

## Configuration file

Anything you would otherwise repeat on the command line goes in `iemod-fetch.ini`,
looked for in the working directory, the `--target` directory, `%APPDATA%`, then
`~/.config` (or wherever `--config PATH` says). Copy `iemod-fetch.ini.example`
and delete what you do not need.

```ini
[iemod-fetch]
manifest  = mod_downloads.ready.json
aliases   = aliases.json
catalogue = lcc-docs/db/mods.json
target    = Mods
max_bytes = 2GiB          ; bytes, or 512MiB / 1.5GB / 2G
workers   = 4

weidu_log =
    WeiDU.log
    WeiDU-BGEE.log:BGEE
```

**An explicit flag always beats the file; the file always beats the built-in
default.** For repeatable options the CLI *replaces* the file's list rather than
adding to it. Unknown keys warn and are ignored.

The default ceiling is 2 GiB because real mods reach it — BGGO is 1.4 GB.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `HTTP 403` on every GitHub mod | Anonymous rate limit (60/h). Set `GH_TOKEN`. |
| `refusing http URL (https required)` | A cleartext entry. Run the corrections, or pass `--allow-http`. |
| `already exists; re-run with --force` | You have a mod directory the tool did not create. `--force` moves it to `Mods/.backup/<folder>.<timestamp>` — it is never deleted. |
| `archive contains .tp2 files [...] but none of them is 'X.tp2'` | The download is not the mod you asked for. Working as intended — do not override it; find the right source. |
| `is a Windows executable ... never run` | A self-extracting installer. `--allow-exe` unpacks it with 7z/unar; it is never executed. |
| `no unpacker is installed` | `apt install libarchive-tools unar` (Debian/Ubuntu), `brew install unar` (macOS). |
| `only off-site links found` | The landing page's download link leaves the site. Review it, then pin it in the manifest, or `--accept-offsite`. |
| A mod resolves to the wrong repo | Pin it: add `"github"` and `"asset"` to its manifest entry. |
| Run is slow | `-j 8`. Owner listings cache for 24h in `Mods/.owner-index.json`. |
| `Content-Length … exceeds … byte ceiling` | Raise `max_bytes` in the config file. The default is 2 GiB. |
| `is a rar archive and no unpacker was found` | Debian/Ubuntu: `apt install libarchive-tools unar` (Debian's own `7zip` package cannot read RAR); macOS: `brew install unar`; Windows 10 and 11 have `tar.exe` built in. An installed 7-Zip (`winget install 7zip.7zip`) or WinRAR is tried last; their standard install folders are searched, so they need not be on `PATH`. |
| `no download link … scored high enough` | The page only offered navigation links to other mods. Open it, find the real download, and pin it as the entry's `url`. |
| `archive contains .tp2 files […] but none of them is …` | The archive is a different mod — or the mod renamed itself. If the archive is right, add `"expect_tp2": "<the name shown>"` to its manifest entry. With `-c` a catalogue usually supplies this automatically. |
| `the mod now ships as 'X' (your log says 'Y')` | Not an error. The mod renamed its folder; it was installed under the new name because that is what WeiDU needs. |
| `did not contain this mod; installed from … instead` | The manifest's download was wrong and the catalogue's URL was used. Promote that URL into your manifest. A `; <url>: <reason>` after it names a source refused for another reason, such as a path escaping the target folder. |

---

## Files it writes under `--target`

| Path | Purpose |
|---|---|
| `<Folder>/` | the installed mod, named exactly as WeiDU expects |
| `.iemod-fetch-state.json` | what was fetched: sha256, url, tag, tp2 file |
| `.backup/<folder>.<ts>/` | directories displaced by `--force` — prune when happy |
| `.owner-index.json` | cached owner repository listings (24h) |
| `.staging/` | transient; removed on exit |

---

## What it deliberately will not do

* **Guess.** No repo-name mutation, no global GitHub search, no
  first-plausible-link-on-a-page. Unresolvable mods are reported with a reason.
  Discovery is bounded to owners you already trust, and every hit is still gated
  by the strict `.tp2` check.
* **Run installers.** `.exe` files are unpacked only with `--allow-exe`, never
  executed.
* **Delete your work.** A destination directory is never removed; conflicts are
  reported and `--force` moves the old copy aside.
* **Run WeiDU itself.** It plans the order and, with `--emit-installer`,
  writes a script that hands the plan to mod_installer (chapter 10). You read
  the script and run it; iemod-fetch never executes it.
* **Pick a side it was not told to.** `--resolve-conflicts` removes only what
  an error-graded rule pins to components; every other conflict is listed for
  you to decide, with its options, and `--decisions` applies your choice.

---

## Reference

## 9. Planning a rule-compliant install order

### 9.1 The databases: kept current for you

Since 2.4 nothing needs cloning. Each run refreshes a cache of the three
community databases before it starts, at most once a day (ADR-0032), and uses
it for every source flag you did not give:

| Cached source | Stands in for |
|---|---|
| lcc-docs `db/mods.json` | `--catalogue` |
| BWS-NG `data/rules`, krion64 `data/mods` | `--rules` |
| BWS-NG `data/mods` | `--mod-db` |
| krion64 `data/` | `--order-catalogue` |
| BWS-NG `data/games/eet.json` | `--eet-sequence` (what may precede the EET core; with `--plan-order`, the place of a mod krion64 does not place) |

```bash
python3 iemod-fetch.pyz --update-data        # refresh now and stop; shows each commit
python3 iemod-fetch.pyz ... --no-update-data # stay offline; use the cache as it is
python3 iemod-fetch.pyz ... --no-default-data # only what the flags say
```

Only the files the tool reads are fetched (about 25 MB the first time, then
only what changed), each checked against the git hash GitHub lists for it.
Before an update replaces the last good copy it must pass a guard: valid JSON,
readable by the tool's own parsers, and no count (mods, rules, order entries)
at zero or below half of the last good copy. A refused update is reported and
that commit is not fetched again; an accepted one is reported with what
changed (counts, mods added and removed, versions and statuses that moved).
`api.data_status()` keeps the full list for the GUI.
Offline, the last good copy is used and the header says how old it is. A
GitHub token (see *GitHub credential*) is not required: a day's refresh is six
API calls. An explicit path still wins, so a clone you maintain yourself works
as before. BWS-NG supplies the pairwise rules; krion64 supplies the 26-category
install-order skeleton plus a second, component-precise conflict database.

### 9.2 Check first, then plan

```bash
py iemodfetch.pyz --check-only   -m mod_downloads.json   -w WeiDU.log:EET -w WeiDUBGEE.log:BGEE   --rules BigWorldSetup-Next-Generation/data/rules   --rules krion64.github.io/data/mods   --mod-db BigWorldSetup-Next-Generation/data/mods   --order-catalogue krion64.github.io   --plan-order .\plan
```

You get `plan\WeiDU.log` and `plan\WeiDU-BGEE.log`, plus a report:

```
INSTALL ORDER PLAN
  WeiDU-BGEE.log      4 mods,   16 components
  WeiDU.log         146 mods,  780 components
  a plan for a FRESH install (mod_installer / Project Infinity);
  WeiDU installs in file order, so an installed game needs reinstalling.
  VERIFIED: the planned order satisfies every order rule checked (132 constraint(s)).

  out of place (6):
    cdtweaks                          117 -> 134  (WeiDU.log)
    ...
  wrong install phase (1) — NOT moved; pass --reassign-phase to act:
    Margarita                        WeiDU.log -> WeiDU-BGEE.log
  reordering CANNOT fix these (4) — the mods must not coexist; drop one side:
    [WeiDU.log] infinity_ui and stratagems are incompatible
```

### 9.3 Reading the report

| Section | What it means | What to do |
|---|---|---|
| `VERIFIED` | the emitted plan was re-checked against the same rules and passes | nothing |
| `NOT COMPLIANT` | the rules contradict each other; the plan breaks the cycle arbitrarily | read the named rules, suppress the wrong one |
| `out of place` | the minimum set of mods that has to move | this is your reinstall order |
| `wrong install phase` | the catalogue says the mod belongs to the other game | decide, then re-run with `--reassign-phase` |
| `contradictory rules` | a cycle in the order rules | file it upstream; suppress locally |
| `reordering CANNOT fix these` | an incompatibility | drop one of the two mods |
| `missing prerequisites` | a required mod is simply absent | add it, or drop the dependent |
| `not in the catalogue` | neither database knows this mod | it kept its current place; verify by hand |
| `placed by BWS-NG's EET sequence` | krion64 does not place the mod; BWS-NG's EET order does - right after the component before it there that krion64 places | check it; a rule or your Sorting Order still wins |
| `placed by kind` | krion64 does not place the mod; lcc-docs' or BWS-NG's kind decides its category (interface, cosmetic, kit, NPC, smith, a quest by its games), after krion64's own mods there | check it; a rule or your Sorting Order still wins |
| `no place: ...` (under `not in the catalogue`) | its kind decides nothing (gameplay, tactics, ...) or its kinds disagree | it kept its current place; verify by hand |

### 9.4 The component conflict report

`--plan-order` fixes order. What it cannot fix is two components that must not
coexist. That is the second half of the same run:

```
COMPONENT CONFLICT REPORT
  1710 rule(s) and 58 known issue(s) evaluated; 84 pair(s) where both mods are
  installed and a conflict rule exists, 79 cleared because the named components
  are not installed
  439 order-sensitive pair(s) upstream never said which way round - not checked

  INCOMPATIBLE COMPONENTS (4 outstanding of 4):
    !! [WeiDU.log] infinity_ui (whole mod)
          vs stratagems: #4115 Thieves assign skill points in multiples of five
          fix: deselect stratagems: #4115  (alternative: drop infinity_ui)
    !! [WeiDU.log] cdtweaks: #1251 Move Alora, #1252 Move Eldoth, ... 
          vs (same mod) cdtweaks: #1257 Move all six
          fix: deselect one of the two groups of cdtweaks above - 6 vs 1 component(s)

  KNOWN ISSUES FOR COMPONENTS YOU INSTALLED (13 outstanding of 13):
    !! [WeiDU.log] stratagems (whole mod)
          why: SPLSTATE.IDS has a 256-entry limit. SCS adds ~40 entries...
          verified: someone traced the mechanism
          workaround: Reduce the number of kit mods...

  ORDER-SENSITIVE COMPONENTS (0 outstanding of 46):
     ! [WeiDU.log] cdtweaks (whole mod) vs EET_end (whole mod)
          FIXED by --plan-order: install cdtweaks before EET_end
```

| Marker | Meaning |
|---|---|
| `!!` | error — the upstream graded this `hard` / `critical` |
| ` !` | warning — graded `partial`, or ungraded (never promoted to error) |
| ` ~` | advisory — nobody traced it; hidden unless `--show-advisories` |
| `verified:` | krion64 `mechanism-verified`: someone followed the mechanism |
| `SPECULATIVE:` | krion64 `speculative`: an observation, not a diagnosis |
| `FIXED by --plan-order` | the new logs already resolve this |

Add `--conflict-report conflicts.json` for the full machine-readable version,
including the findings the terminal truncates.

Two numbers in the header exist so the report can be disbelieved: if
`pair(s) where both mods are installed` is 0, the rules matched nothing and a
clean report means nothing. If `cleared because the named components are not
installed` is large, component precision is doing its job — those would all be
false alarms in a mod-level checker.

### 9.5 The caveat that matters

The plan is an **install order for a fresh install**. WeiDU applies changes in
file order, so a game already installed does not become correctly ordered by
overwriting its log — that would only make the log lie about the game. Feed the
plan to mod_installer or Project Infinity and reinstall — chapter 10
generates the script that does it.

The plan is also mod-granular, like Project Infinity's own sorting order. A rule
that constrains one component of a mod against another component of the same mod
is reported, not solved.

---

## 10. From plan to a running game: EET, BGEE or BG2EE, on Windows or Linux

This chapter is the whole path for a **fresh** install: mods fetched, order
planned, the conflicts the rules decide resolved, and one script that installs
both games of an EET setup.

### 10.1 What you need

| | Where | Why |
|---|---|---|
| BGEE and BG2EE, **clean copies** | your store's install folder, copied | EET merges BGEE into BG2EE; the BG2EE copy becomes the EET game. Keep the originals |
| SoD (optional) | part of BGEE | DlcMerger in the BGEE plan merges it first |
| WeiDU | <https://github.com/WeiDUorg/weidu/releases> | the installer every mod uses |
| mod_installer | <https://github.com/dark0dave/mod_installer/releases> (GPL-3.0) | runs WeiDU in plan order, both EET phases, answers prompts |
| the two rule databases | chapter 9.1 | order + conflicts |

**Linux: lower-case the mods.** mod_installer hands WeiDU lower-cased paths
(`eet/eet.tp2`), so on a case-sensitive file system a mod shipped as `EET.TP2`
is "not found" partway through the install. The script refuses mixed-case mods
before anything runs. Either lower-case them as the last step before installing:

```bash
find Mods -depth -mindepth 1 -name '*[[:upper:]]*' -exec sh -c \
  'for p; do d=${p%/*}; b=${p##*/}; mv -- "$p" "$d/$(printf %s "$b" | tr "[:upper:]" "[:lower:]")"; done' sh {} +
```

or, on an ext4 file system created with case-folding, pass
`MOD_INSTALLER_ARGS=--casefold` and mod_installer marks the folders it copies
case-insensitive. The game folders themselves need the usual WeiDU-on-Linux
preparation (lower-case file names). Windows and macOS (case-insensitive by
default) need neither.

### 10.2 Fetch, plan, resolve, emit

```bash
# 1. fetch every mod your logs name into ./Mods (chapters 2-4)
python3 -m iemod_fetch -m mod_downloads.json \
    -w WeiDU.log:EET -w WeiDUBGEE.log:BGEE -t ./Mods

# 2. plan the order, apply the conflict remedies the rules decide, write scripts
python3 -m iemod_fetch --check-only -m mod_downloads.json \
    -w WeiDU.log:EET -w WeiDUBGEE.log:BGEE -t ./Mods \
    --rules BigWorldSetup-Next-Generation/data/rules \
    --rules krion64.github.io/data/mods \
    --order-catalogue krion64.github.io \
    --plan-order ./plan --resolve-conflicts --simulate --emit-installer \
    --language-preference it_IT,en_US
```

`--simulate` walks the plan the way WeiDU will run it, reading each staged
mod's own tp2: the BGEE log on BGEE, the EET log on BG2EE, which becomes EET as
soon as the EET core is in. It prints an `INSTALL SIMULATION` block listing
every component WeiDU would refuse and the flag that refuses it:

```text
INSTALL SIMULATION (each component's own tp2 constraints, in plan order)
  14 component(s) would install, 1 would be refused, 0 unchecked (no tp2 read)
  WOULD REFUSE - mod_installer stops at the first of these:
    [WeiDU.log] eet #0: EET refuses the merge: BG:EE mod(s) cdtweaks not in EET's compatibility.tbl (EET's M flag overrides this, at your own risk)
```

(That is the test suite's mock EET install, `tests/data/eetmock`, as handed
over. While the EET core is refused the game stays BG2EE in the simulation, so
the traps that only exist on EET show up once the merge is fixed;
`--resolve-conflicts` re-simulates until nothing is refused, and on the mock
ends at `12 component(s) would install, 0 would be refused`.)

The usual EET traps it catches: a BGEE-only mod (DlcMerger) in the EET log; a
mod that refuses EET (EEFixPack's `!GAME_IS ~eet~`) after the core; a BG2EE-only
component after the core; a BG:EE mod EET cannot import (not in EET's
`tbl/compatibility.tbl`), which makes the merge - and everything after it -
fail; a REQUIRE whose component comes later; a FORBID whose component is
already in. With `--resolve-conflicts` those components are removed from the
plan, each with WeiDU's reason, until nothing is refused; the EET core itself
is never removed. The mods' REQUIRE/FORBID also order the plan, with or without
`--rules`.

`--language-preference` is optional: each mod is set to the first listed
language it offers (read from its own tp2, so the mods must be fetched first);
a mod offering none keeps the language its log had and is listed. The game
language handed to mod_installer follows the first preference unless
`--game-language` says otherwise.

The plan is component-level: where krion64 places a component in another
category, or a rule names specific components, a mod is split across the order
(the summary says how many). Conflicts are resolved at component level too,
including two options of one WeiDU subcomponent group (the last one is kept).

After the conflicts, the report shows each install's **engine limits**: kits
against WeiDU's 256 (the game has 40), spell ids per wizard or priest level
against WeiDU's 50, and spell states for information only - with the
components that use them up. A mod krion64 has no counts for is named, and the
totals then mean "at least". See ADR-0034 for where each number comes from.

Point `-w` at the WeiDU.log **inside your game folder** and the tables are
measured from the game itself instead (the header says `measured in ...`):
the kits, spell slots and spell states it already holds, exactly as WeiDU
will find them, plus krion64's estimate for what you chose that is not
installed yet. Nothing in the game folder is changed.

`./plan/` now holds:

| File | What it is |
|---|---|
| `WeiDU-BGEE.log` | what installs on BGEE before the merge, in order |
| `WeiDU.log` | EET core first, then every EET mod, EET_end last |
| `RESOLUTION.json` | every component `--decisions` and `--resolve-conflicts` removed and why (`by`: `decision` or `rules`), what was accepted, and what is left for you |
| `install-eet.sh` / `install-eet.cmd` | the installer for Linux/macOS and for Windows |

Read the `CONFLICT RESOLUTION` block in the output. "Left for you to decide"
means the rules say two things must not coexist but not which one goes. The
conflict report lists, for each finding, its `id` and the options that clear
it, with their cost; write your answer in a `decisions.json`
(`schemas/decisions-v1.schema.json`) and re-run step 2 with `--decisions`:

```json
{"schema_version": 1,
 "decisions": [
   {"finding": "conflict-1887f4d4f9f06816", "choose": "option-a8395462ca46c2a6"},
   {"finding": "conflict-d8821540fb81dfcd", "accept": "tested together, works"}]}
```

`choose` removes exactly that option's components from the plan - unless the
option is a `keep-both`: offered for a conflict graded below `error`
(two components touching the same thing), it keeps both and installs the one
it names last, so what they share is left as that one makes it; the plan is
made again with that order, and a rule it contradicts is reported. `accept`
keeps both sides and the report shows the finding as accepted, with your
reason. Decisions are applied before `--resolve-conflicts`, which never
overrides them, and the plan is re-checked afterwards. A decision whose finding
is no longer in the report (the selection changed) is listed as stale and not
applied. Your WeiDU logs are never touched.

For a single game (BGEE-only or BG2EE-only) pass one log; you get `install.sh`
and `install.cmd`, which take `GAME_DIR`.

### 10.3 Run it

Linux / macOS:

```bash
BGEE_DIR="$HOME/games/BGEE-clean" BG2EE_DIR="$HOME/games/EET" \
WEIDU="$HOME/bin/weidu" MOD_INSTALLER="$HOME/bin/mod_installer" \
DRY_RUN=1 sh ./plan/install-eet.sh       # prints the command; drop DRY_RUN to install
```

Windows (`cmd`):

```bat
set "BGEE_DIR=D:\Games\BGEE-clean"
set "BG2EE_DIR=D:\Games\EET"
set "WEIDU=D:\Tools\weidu.exe"
set "MOD_INSTALLER=D:\Tools\mod_installer.exe"
plan\install-eet.cmd
```

Before anything runs, the script refuses: a folder without `chitin.key`; a game
that already has mods (`ALLOW_EXISTING=1` if you mean it); a missing WeiDU or
mod_installer. Then mod_installer installs the BGEE log onto BGEE and the EET
log onto BG2EE, handing EET's core the BGEE path, and stops at the first error.

| Variable | Default | |
|---|---|---|
| `BGEE_DIR`, `BG2EE_DIR` / `GAME_DIR` | none | required |
| `WEIDU` | `weidu` on PATH | |
| `MOD_INSTALLER` | `mod_installer` on PATH | |
| `MODS_DIR` | the `-t` directory, relative to the plan | |
| `LANGUAGE` | `--game-language` (en_US) | |
| `DRY_RUN=1` | off | print, do not run |
| `ALLOW_EXISTING=1` | off | install over a modded game |
| `ALLOW_MIXED_CASE=1` | off | skip the Linux lower-case check |
| `MOD_INSTALLER_ARGS` | none | passed through, e.g. `--casefold` |

### 10.4 Check the game folders before installing

Pass the two folders to the planning step and they are checked before a script
is written - read only, nothing is changed:

```bash
python3 -m iemod_fetch --check-only ... --plan-order ./plan --resolve-conflicts \
    --simulate --bgee-dir "$HOME/games/BGEE" --bg2ee-dir "$HOME/games/BG2EE"
```

Each folder is identified the way WeiDU itself does it - by marker files in
`override/` and `chitin.key` (`oh1000.are` BG:EE, `oh6000.are` BG2:EE, `eet.flag`
EET) - and held to what EET's readme asks for:

| Refused | Why |
|---|---|
| the two folders swapped, or the same folder twice | EET needs both games, separately |
| BG2:EE already EET (`override/EET.flag`) or already modded | the EET core needs a clean BG2:EE |
| BG:EE without Siege of Dragonspear | EET needs BG:EE + SoD (`movies/sodcin05.wbm`) |
| SoD still a `sod-dlc` archive and no DlcMerger in the plan | GOG/Steam ship SoD as a DLC WeiDU cannot see until DlcMerger merges it |

Not checked, and printed as such: the patch level (EET wants v2.6.6.0 of both
games) and whether the game data is intact.

**Does everything end up in BG2:EE?** Yes. The EET core imports BG:EE + SoD into
the BG2:EE folder and marks it `override/EET.flag`; from then on WeiDU calls
that game EET and every later mod installs there. The BG:EE folder is only read.
Before the core, BG2:EE must stay clean - EEFixPack is the one mod EET allows
there, and `--resolve-conflicts` moves it there if your log has it after the core.

### 10.5 Which versions to use

| Component | Use | Why |
|---|---|---|
| BG:EE + SoD, BG2:EE | v2.6.6.0 | what EET states it supports |
| WeiDU | v251.00 or newer (EET: "newer than v248") | the version CI tests with, pinned by sha256 |
| mod_installer | the version CI pins (commit `3b6827a`, Cargo 16.0.0) | no release tag past v12.1.1 |
| each mod | a release tag + sha256 via `--emit-pinned-manifest` | "latest" changes under you; a pin refuses anything that changed |

A mod with no releases: fetch it once, then pin the archive's sha256 the same
way. Never install from a branch head you did not pin.

### 10.6 What is and is not guaranteed

* The plan satisfies every order rule it was checked against, or says
  `NOT COMPLIANT`; the script then carries an `UNRESOLVED` warning at its top.
* The script's arguments match mod_installer v16's command line, checked
  against its source **and by running the generated script with the real
  mod_installer 16.0.0 binary**, a stand-in WeiDU recording every call: the BGEE
  log installed in the BGEE folder first, then the EET core, the EET mods and
  EET_end in BG2EE. The shell script is executed by the test suite; the `.cmd`
  script on the Windows CI runners.
* **Verified with the real WeiDU, without game data:** on two synthetic game
  folders (an empty `chitin.key`, an empty `dialog.tlk`, WeiDU's marker file)
  the real WeiDU v251 refuses exactly what `--simulate` predicts, installs the
  resolved mock EET plan to the last component, and the generated
  `install-eet.sh` runs through the real mod_installer into both folders. CI
  does this on every push (`tests/test_real_weidu.py`).
* **Not verified here:** an install against real game data - the merge itself,
  mods whose bodies fail on content, the patch level. No CI runner owns the
  games. The minimum for that test is BG:EE + SoD and BG2:EE v2.6.6.0 with
  DlcMerger, EEFixPack, EET and EET_end. mod_installer labels its EET mode BETA.
* A conflict no rule database knows about is not found. The databases are
  community work; report what you find upstream.

---

* `README.md` — feature overview
* `docs/AUDIT.md` — what was wrong with the original script, with evidence
* `docs/ADR.md` — ADR-0001…0028, the design decisions and why
* `docs/PLAN.md` — three-phase audit / implementation / validation plan
* `python3 -m iemod_fetch --help` — full flag reference
