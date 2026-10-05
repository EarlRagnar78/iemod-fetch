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
python3 -m pytest -q                 # 290 passed - confirms the copy is sound
python3 build.py                     # -> ./iemod-fetch.pyz  (34 KB, no deps)
```

Optional but recommended — the community catalogue that fills catalogue gaps
and provides health warnings:

```bash
git clone --depth 1 https://github.com/RiwsPy/lcc-docs ~/lcc-docs
```

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
git clone --depth 1 https://github.com/Selphira/bigworldsetup-next-generation ~/bws-ng
git clone --depth 1 https://github.com/krion64/krion64.github.io ~/krion

python3 -m iemod_fetch --check-only \
    -w WeiDU.log -w WeiDU-BGEE.log:BGEE \
    --rules ~/bws-ng/data/rules --rules ~/krion/data/mods \
    --mod-db ~/bws-ng/data/mods
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
| `no unpacker is installed` | `apt install p7zip-full` (or `unar`). |
| `only off-site links found` | The landing page's download link leaves the site. Review it, then pin it in the manifest, or `--accept-offsite`. |
| A mod resolves to the wrong repo | Pin it: add `"github"` and `"asset"` to its manifest entry. |
| Run is slow | `-j 8`. Owner listings cache for 24h in `Mods/.owner-index.json`. |
| `Content-Length … exceeds … byte ceiling` | Raise `max_bytes` in the config file. The default is 2 GiB. |
| `is a rar archive and no unpacker was found` | `winget install 7zip.7zip` (Windows) or `apt install p7zip-full`. The standard Windows install directories are searched, so 7-Zip need not be on `PATH`. |
| `no download link … scored high enough` | The page only offered navigation links to other mods. Open it, find the real download, and pin it as the entry's `url`. |
| `archive contains .tp2 files […] but none of them is …` | The archive is a different mod — or the mod renamed itself. If the archive is right, add `"expect_tp2": "<the name shown>"` to its manifest entry. With `-c` a catalogue usually supplies this automatically. |
| `the mod now ships as 'X' (your log says 'Y')` | Not an error. The mod renamed its folder; it was installed under the new name because that is what WeiDU needs. |
| `did not contain this mod; installed from … instead` | The manifest's download was wrong and the catalogue's URL was used. Promote that URL into your manifest. |

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
* **Install mods.** WeiDU ordering and component selection stay with Infinity
  Mod Forge.

---

## Reference

## 9. Planning a rule-compliant install order

### 9.1 Get the two databases

```bash
git clone --depth 1 https://github.com/Selphira/BigWorldSetup-Next-Generation.git
git clone --depth 1 https://github.com/krion64/krion64.github.io.git
```

Neither is vendored. They are data, passed by path, and refreshed with
`git pull`. BWS-NG supplies the pairwise rules; krion64 supplies the 26-category
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
plan to mod_installer or Project Infinity and reinstall.

The plan is also mod-granular, like Project Infinity's own sorting order. A rule
that constrains one component of a mod against another component of the same mod
is reported, not solved.

---

* `README.md` — feature overview
* `docs/AUDIT.md` — what was wrong with the original script, with evidence
* `docs/ADR.md` — ADR-0001…0018, the design decisions and why
* `docs/PLAN.md` — three-phase audit / implementation / validation plan
* `python3 -m iemod_fetch --help` — full flag reference
