# Architecture Decision Records

Format: context → decision → consequences. One record per decision that a future
maintainer would otherwise be tempted to reverse.

---

## ADR-0001 — Keep it stdlib-only, but stop being a single file

**Context.** The original is one 683-line script with no dependencies. The
portability is genuinely valuable: it runs on a fresh Windows box next to the
game install with nothing but CPython. But it is untestable as written — network,
filesystem and policy are interleaved in every function.

**Decision.** Keep the zero-runtime-dependency constraint. Split into a package
of small modules with injectable seams (`HttpClient`, `sleep`, `client`) so every
policy decision is unit-testable offline. `pytest` is a *test-time* dependency
only.

**Consequences.** Deployment is a directory instead of a file (or `python -m
zipapp` for a single `.pyz`). In exchange, 170 tests run in ~1 s with no network.
Anyone who insists on one file can `zipapp` it; nobody has to fork it to test it.

---

## ADR-0002 — One name, three jobs: split them

**Context.** The manifest's `tp2` field was used simultaneously as catalogue id,
install directory name, and identity check. Your real data proves those are
different strings: 30 differ by case, 10 differ outright. Fuzzy matching was
introduced to bridge the gap and then leaked into verification, where it made
every check pass (`find_tp2_in_dir` ends in `return True`).

**Decision.** Three separate concepts:

| Job | Source of truth | Matching |
|---|---|---|
| Install directory | the WeiDU log folder, verbatim | none — it *is* the name |
| Catalogue lookup | manifest `tp2` key | exact → explicit alias file → suggestion |
| Identity check | `.tp2` inside the artefact | strict: `<f>.tp2` or `setup-<f>.tp2` |

Fuzzy matching may **propose**; it may never **decide**. Suggestions are printed
and written to the JSON report; applying them requires `--accept-suggestions` or
an `aliases.json` under version control.

**Consequences.** 10 mods need a one-time human decision instead of being
silently mis-installed. `aliases.json` (shipped, 9 entries) reduces that to 1 —
`HPS_PORTRAITS_PROJECT`, which genuinely has no source. Strictness is free: it
identifies 148/148 real mods correctly.

---

## ADR-0003 — Credentials are scoped to an exact host allowlist

**Context.** The token was attached to every request, reaching 9 third-party
hosts (3 over cleartext). Redirect stripping used a substring test that a
lookalike host defeats.

**Decision.** `headers_for(url)` attaches the credential only when the host is
exactly `api.github.com` or `github.com`. Not a suffix test, not a substring
test. On redirect, the credential is dropped for any host outside that set —
including GitHub's own `objects.githubusercontent.com`, which rejects it anyway.
Non-https is refused unless `--allow-http`, and a redirect may never downgrade.

**Amendment (ADR-0005a) — restoring automatic acquisition without the impersonation.**
Removing the device flow removed the convenience along with the problem. Two
providers put it back using credentials the machine already has, minted by
tools the user already trusts: `gh auth token`, and `git credential fill`
against git's configured helper (Git Credential Manager on Windows holds a
GitHub token after any HTTPS push). The credential-helper probe is forced
non-interactive on every channel — `credential.interactive=false`,
`credential.guiPrompt=false`, `GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`
— because a mod download must never trigger an auth prompt, and the value is
accepted only if it matches a GitHub token shape, so a stored username/password
is never sent as a bearer.

**Consequences.** The three `http://` entries in your manifest now need an
explicit `--allow-http`. That is the correct friction: you should know you are
fetching mods over cleartext.

---

## ADR-0004 — Integrity is the manifest's job; the tool makes it possible and records it

**Context.** Your manifest has no `sha256`, no `release_tag`, no version. Your
WeiDU logs record no versions either. Nothing downstream can verify that today's
download is what was installed last time, and "latest" drifts.

**Decision.** The tool cannot invent trust it doesn't have, so it does three
things instead of pretending:

1. **Honours** optional `sha256`, `release_tag` and `asset` fields when present —
   a pinned download is verified before extraction and rejected on mismatch.
2. **Records** what it actually fetched — sha256, resolved URL, release tag, tp2
   filename — into `Mods/.iemod-fetch-state.json` on every run.
3. **Reports** the same in `--json-report`.

**Consequences.** Run once, commit the state file, and you have a lockfile you
can promote into the manifest as `sha256`/`release_tag`. This is the only path
from "it worked on my machine in September" to a reproducible install. Until you
do that, every run is best-effort and the tool says so rather than implying
otherwise.

---

## ADR-0005 — Resolution never guesses

**Context.** On failure the script mutated repo names and finally installed the
top hit of a GitHub code search — a name anyone can register.

**Decision.** Exact repository, or an honest `MANUAL` with the reason and the
URL. No name mutation, no search fallback, no "first plausible link on the page"
across hosts. Landing-page links must be same-site to be auto-selected.

**Consequences.** More mods land in the manual bucket than before. That number
was always the truth; the old script hid it behind guesses. The manual list is
actionable: reason, URL, target directory, and suggested catalogue entry.

---

## ADR-0006 — Extraction is contained, and never executes anything

**Context.** `extractall()` on both zip and tar with no validation; `.exe`
handled as an archive.

**Decision.** Validate every member before writing (traversal, absolute paths,
symlinks, special files), enforce entry-count / total-size / compression-ratio
ceilings, use `filter="data"` for tar, and re-audit the extracted tree for
escaping symlinks. A `.exe` is never run — it is only *read* by `7z`/`unar`, and
only when `--allow-exe` is given. A missing unpacker is an explicit error naming
the package to install, never a silent skip.

**Consequences.** Some exotic archives will be refused rather than extracted. A
refusal you can read beats a traversal you cannot see.

---

## ADR-0007 — The destination directory is never deleted

**Context.** `shutil.rmtree(mod_dest_dir, ignore_errors=True)` ran on every error
path, including for directories the script had not created.

**Decision.** Extract to `Mods/.staging/<folder>-<uuid>/`, verify the strict
`.tp2` is present, and only then move into place. An existing destination is a
`CONFLICT` unless `--force`; `--force` *moves* it to
`Mods/.backup/<folder>.<timestamp>`. Failure at any stage leaves the destination
byte-for-byte unchanged.

**Consequences.** `.backup/` accumulates and is yours to prune. Disk cost is
bounded and recoverable; deleted hand-edits are not.

---

## ADR-0008 — Release discovery scoped to trusted owners

**Status.** Accepted; amends ADR-0005 ("resolution never guesses").

**Context.** 38 of the 148 catalogue entries have no `github` field, and the
supplied manifest contains stale pointers — five entries name
`SpellholdStudios`, the account Spellhold Studios abandoned in 2022 when its
owner disappeared, whose mods now live in `Spellhold-Studios`. Every one of
these lands in the manual bucket, which is correct but not helpful.

ADR-0005 removed the legacy global search
(`api.github.com/search/repositories?q=<name>+in:name` → install `items[0]`).
The objection to it was never "searching"; it was the **trust boundary**: the
search space was the whole of GitHub, a namespace anyone can register in, and
the top hit was installed with nothing standing between it and the game
directory.

**Decision.** Add discovery with a different boundary and a gate.

* **Bounded search space.** An explicit owner allowlist, defaulting to the
  shipped modding houses plus every owner the manifest already depends on. An
  owner your catalogue already trusts is one you have already accepted;
  `--trusted-owners` replaces the list, `--trusted-owner` extends it.
* **A hit is a candidate, not a decision.** The artefact still has to contain
  `<folder>.tp2` or `setup-<folder>.tp2` to be installed. A wrong repository
  inside a right owner fails verification and is reported — asserted by
  `test_a_discovered_repo_with_the_wrong_tp2_is_not_installed`.
* **Catalogue always wins.** Discovery runs only after the manifest entry fails
  to resolve; a working entry never triggers an index build.
* **A guess becomes a fact.** Every discovered source is printed under
  "DISCOVERED SOURCES" as a ready-to-paste `"github"` value and recorded in the
  JSON report, so the next run is deterministic.
* **Bounded cost.** Owner listings are paginated and cached to disk for 24 h —
  roughly one API call per owner, against 148 per-mod calls.

**Consequences.** Mods whose catalogue entry rotted become installable again
without hand-editing, and the SHS migration resolves itself. The residual risk
is a compromised trusted owner, or a fork inside a trusted owner carrying a
matching `.tp2` — forks and archived repos are ranked down, and the answer to
both is pinning (ADR-0004): once discovered, pin the sha256 and the question
stops being reopened. `--no-discovery` restores strict ADR-0005 behaviour.

This is the one place where the tool searches rather than looks up, so the
default is loud: it says what it found, why, and what to write down.

---

## ADR-0009 — Supplementary catalogues

**Status.** Accepted; extends ADR-0008.

**Context.** `mod_downloads.json` gives one URL per mod and no integrity or
health metadata. 41 of the 148 entries had no resolvable repository, and one
WeiDU folder had no catalogue entry at all.

The community maintains far richer databases. The La Couronne de Cuivre list
(<https://github.com/RiwsPy/lcc-docs>, MIT, descended from FreddyGwendo's and
JohnBob's lists) publishes `db/mods.json`: ~2,100 WeiDU mods with tp2 name,
every known download URL, a maintenance status and a 0/1/2 quality rating, all
CI-validated against a pydantic schema. Measured against the supplied data it
covers **142 of the 148** installed mods.

**Decision.** Accept a supplementary catalogue as a *second* source of
resolution and as a source of advisories — never as an authority.

* **Order.** Manifest entry → supplementary catalogue → trusted-owner discovery
  → manual. Curated data outranks name similarity; the manifest outranks both.
* **Same gate.** A catalogue hit is a candidate. The archive still has to
  contain `<folder>.tp2`. `Vampire_World` resolves to
  `Spellhold-Studios/Miscellaneous`, a collection repository — exactly the case
  the gate exists for.
* **Advisories, not vetoes.** `safe` and `status` become warnings in the run
  report. The catalogue's opinion that a mod is beta or obsolete is worth
  surfacing; it is not grounds for refusing to fetch something you asked for.
* **Never bundled, never auto-fetched.** It is third-party data with its own
  licence and cadence. You pass `--catalogue PATH`. Only a 16-entry sample is
  vendored, as a test fixture, with attribution.
* **Prefer baking it in.** `tools/enrich_from_lcc.py` writes the resolved
  repositories into the manifest with provenance in `notes`, so the lookup
  happens once and ends up in a reviewable diff.

**Correction (measured after the fact).** An earlier reading of this data
concluded the catalogue held no direct download URLs. That was wrong: it holds
**269 across 262 mods** (~12%), which its own model flags as `is_direct_archive`
and its page renders with a padlock. The zero was an artefact of looking only at
the 142 mods in one install, none of which happened to have one but `vampire_world`.
Resolution order inside a catalogue entry is therefore: **direct archive URL →
repository → landing page**. A direct URL needs no API call and leaves no doubt
about which asset is meant. `vampire_world` is the case that proves it: its
repository is `Spellhold-Studios/Miscellaneous`, a collection whose release
assets are other mods, while the catalogue's direct link points straight at
`Vampire_world_mod_v.0.56_EET.zip`.

**Consequences.** Entries needing a landing-page scrape drop from 41 to 26 on
the supplied data, and a mod absent from the manifest entirely becomes
resolvable. The 21 WeaselMods entries stay — WeaselMods self-hosts and is not
on GitHub, which no catalogue can change. A stale catalogue can point at a dead
repository; that fails resolution and falls through to discovery, which is the
same path as any other rotted URL.

---

## ADR-0010 — Health advisories are printed, and judged per game

**Status.** Accepted; extends ADR-0009.

**Context.** Two questions about the catalogue metadata: should a mod's
obsolete/problem status be shown even when the download succeeds, and can the
`games` tags catch mods that do not belong in an EET build?

Measuring first. Across the 148 installed mods the catalogue lists 322 URLs:
116 GitHub repository or release pages, 206 forum and landing pages, and
**zero direct archive links**. That settles what a catalogue is good for — see
the consequences below.

**Decision.**

* **Advisories are printed, not filed.** A health warning appears indented
  under the mod as it is installed, and again in a `MOD HEALTH WARNINGS` block
  at the end. Previously they were warnings in the JSON report, which is where
  you look after something has gone wrong rather than before.
* **They never block.** The catalogue's opinion that a mod is beta or
  "may cause problems" is information; it is not grounds for refusing to fetch
  something you asked for. Only verification failures stop an install.
* **Compatibility is judged per log, never globally.** Each WeiDU log gets its
  own game. EET is inferred from the log itself (a log that installs the `eet`
  mod is an EET install); anything else stays unknown unless you write
  `-w WeiDUBGEE.log:BGEE`. An unknown game produces **no** warnings.

That last point is the whole reason this is per-log. `bg1ub` is tagged
BG/Tutu/BGT/BGEE/SoD and not EET — but it lives in the BGEE log, where it is
entirely correct. A global EET check would have flagged it, and one confident
false positive on a 148-mod install teaches you to ignore the other twelve.
Judged per log, the supplied data yields exactly two real flags:
`BloodiedStingsOfBarovia` (BG2EE only) and `impasylum` (BG2/BGT only).

**Consequences.** Thirteen of the 148 mods now carry a visible warning. The
catalogue's `games` list can lag reality — a mod may work under EET before the
list says so — so these are advisories, not verdicts, and they say which
catalogue said it. `conflicts` data exists in the schema but is sparse (zero
records touch this install), so it is captured and exposed but not yet
surfaced as a warning; promoting it would mean promising a completeness the
data does not have.

---

## ADR-0011 — A navigation link is not a download

**Status.** Accepted. Written after the first real run.

**Context.** Twenty mods — every WeaselMods entry in the install — downloaded the
same file. `SotSC`, `TotDG`, `Innershade`, `ISNF`, `Ooze`, `Yvette`, `VerrBG2`,
`Foundling`, `GAHESH`, `WhinHill`, `Bristlelick` and the rest all resolved to
`downloads.weaselmods.net/download/alabaster-sands/`.

The cause was arithmetic. A link matching `/download/…/` scored 20 for looking
download-ish. On a site whose sidebar lists every mod it hosts, twenty links
scored 20, no link scored more, and the sort is stable — so the alphabetically
first entry won, for every mod on the site. This is legacy defect L12 wearing a
different hat: the tool guessed, and guessed consistently wrong.

**Decision.**

* **A minimum score to be used unattended.** `_MIN_LINK_SCORE = 40`, deliberately
  above the 20 that "looks download-ish" earns. A `wpdmdl=` link scores 90, a
  `do=download` link 80, a direct archive 100. A bare nav entry cannot clear the
  bar on its own.
* **Sibling pages are rejected outright.** `/download/alabaster-sands/` reached
  from `/download/shades-of-the-sword-coast/` shares a parent and differs in the
  last segment: it is another entry in the same listing, so it is another mod.
  This holds even when the sibling is a real `.zip` — another mod's archive is
  still another mod's archive.
* **A link carrying this page's own slug is preferred** (+30).
* **Forum interstitials are unwrapped.** `…/leaving?target=<url>` yields its
  target rather than the wrapper page.
* **Nothing is better than something wrong.** When no link clears the bar the
  mod is reported, with an explanation and an instruction to pin the URL.

**Consequences.** Some pages that previously "resolved" now report instead. That
number was always the truth. The alternative is twenty copies of the wrong mod
installed under twenty right names — the failure mode this whole rewrite exists
to prevent.

---

## ADR-0012 — The mod's own .tp2 is the authority

**Status.** Accepted; supersedes part of AUDIT.md and amends ADR-0004 and ADR-0010.

**Context.** `AUDIT.md` states that this install "cannot be reproduced from these
files", because no WeiDU log line carries a version and the manifest pins
nothing. That was true of the two input files and wrong as a conclusion: a
WeiDU mod declares its own version, and after installing we are holding it.

```
VERSION ~v9.2.1~
REQUIRE_PREDICATE GAME_IS ~bgee sod bg2ee eet~ @2
```

**Decision.** After a successful install, read the mod's `.tp2` (`iemod_fetch/tp2.py`)
and use what it says over what anything else guessed:

* **Version.** Recorded in the state file and shown in the report, preferred over
  the GitHub release tag. Mods fetched from a forum page — which have no tag at
  all — now have a recorded version for the first time.
* **Compatibility.** `GAME_IS` / `GAME_INCLUDES` / `ENGINE_IS` is what the mod
  itself requires, so it settles disagreements with the catalogue: it withdraws a
  false alarm (the catalogue's `games` list lags reality) or raises a
  better-founded one. A tp2 that declares nothing has no opinion — silence means
  "installs anywhere", never "incompatible".
* **Names.** The catalogue's `tp2` field is the mod's real tp2 name, which is how
  `Reflections` (WeiDU log) is matched to `Reflections_of_Destiny.tp2` (archive)
  with no manual configuration. Values that are plainly display names — "NSC
  Portraits" — are rejected: a tp2 has no spaces.

When a mod is accepted under a name other than the WeiDU folder, it is installed
under the name the **archive** uses, because that is what WeiDU requires, and the
rename is reported.

**Consequences.** `expect_tp2` remains in the manifest as an explicit override for
cases no catalogue knows, but is rarely needed. The parsing follows
`scripts/manager/tp2.py` in lcc-docs (MIT); its `GAME_IS` exclusion is anchored
with `.*` under DOTALL, so a single `? 1 : 0` anywhere in a file suppresses every
match in it — re-implemented here with the exclusion restricted to the adjacent
idiom, and a test pinning that.

---

## ADR-0013 — Checking the install, not just fetching it

**Status.** Accepted.

**Context.** The tool answered "can I obtain these mods?" but not "is this
install sound?" — and `WeiDU.log` already contains everything needed to answer
the second question offline: every component, in install order.

Two data sources exist for the rules:

* **The mods themselves.** A Project Infinity `[Metadata]` ini carries
  `Before=` / `After=` lists of tp2 names (`modmeta.py`). A mod shipping one
  needs no external data at all.
* **Community rule sets** in the BigWorldSetup-Next-Generation shape —
  `order.json`, `incompatibilities.json`, `dependencies.json`, ~850 rules,
  themselves largely harvested from those ini files. Syntax:
  `modA(-):modB(100)|modC(1,2)` with a direction and a severity, where `(-)`
  means any component.

**Decision.** Add a checker (`rules.py`) that reports and changes nothing.

* **One log is one game install.** Two logs — an EET game and a BGEE game — are
  never merged before checking. Merging them compared positions across separate
  installs and invented order violations that cannot exist; the first run
  against the real data produced two such false alarms.
* **Errors and warnings stay distinct.** A missing dependency or a known
  conflict is an error and sets a non-zero exit; an ordering rule is a warning,
  because ordering advice is heuristic and a knowingly unusual order is a
  legitimate choice.
* **An unparseable component list widens the rule** rather than dropping it. One
  real entry reads `(3183.4.1)`; a rule that is hard to read is not a rule that
  should be ignored.
* **`--check-only` touches no network at all** — logs plus rules, nothing else.
  It is the fast pre-flight before a long fetch, and it works on a machine with
  no connectivity.

**Consequences.** Against the supplied logs this finds 6 errors and 12 warnings,
including two the manifest could never have surfaced: `eet` is installed without
`EET_end` (EET installs in two parts), and `TDDz` is installed without `TDD`.
The rule sets are third-party data with their own cadence and are neither
bundled nor fetched — you pass `--rules`. Nothing is reordered or uninstalled:
WeiDU order is the user's to change, and a tool that silently rewrote an install
order would be far more dangerous than one that points at it.

---

## ADR-0014 — Rules go stale; say so rather than pretending otherwise

**Status.** Accepted; amends ADR-0013.

**Context.** A community rule set is a snapshot. If a mod author fixes a conflict
and ships a new version, the rule stays and the checker starts crying wolf. The
rule files carry no version qualifier — their keys are `rule`, `direction`,
`severity`, `description`, `translations` and occasionally `source_url` — so a
rule cannot say "fixed in v5.1". Left alone this decays into noise, and a
checker people learn to ignore is worse than no checker.

**Decision.** Four mechanisms, in descending order of reliability.

1. **A mod's own `[Metadata]` ini wins on ordering.** It travels inside the
   version you downloaded, so it cannot be stale about itself: a developer who
   fixes an ordering problem and updates the ini ships the correction with the
   next release. Community *ordering* rules for a mod that carries its own ini
   are dropped. This is the only genuinely self-updating channel — and it covers
   ordering only, because the PI ini format expresses `Before`/`After` and
   nothing about conflicts.

2. **Version-baseline staleness.** The rules' companion mod database records the
   version each mod was at when the rules were written; the installed mod
   declares its own version in its `.tp2` (ADR-0012). When the installed version
   is **newer** than the baseline, the finding is reported but **not counted** —
   it cannot gate an exit code — and is labelled with both versions and told to
   check the changelog. On the supplied install this correctly withholds two
   findings about `HiddenGameplayOptions` (v5.2 installed, rules written against
   5.0).

3. **Recorded verifications.** `--suppress` takes a JSON file of rules you have
   checked, each with a reason, a date, and optionally a `verified_version` that
   only takes effect once you are actually on the fixed release. Reviewable in a
   diff, like `aliases.json` and `corrections.json`.

4. **Visible age.** The rule set's own date is printed, and past 180 days it says
   so.

**Consequences.** Some real problems will be withheld because the mod moved on
without the rule being wrong. That is the correct trade: a false "not counted"
costs a line of output, a false error costs the user's trust in every other
finding. Version comparison refuses to rank pairs it cannot (`vEAOB.9` against
`Alpha 3`), and an unrankable pair never claims staleness.

**Deliberately not done.** Parsing a mod's readme or changelog for "fixed the
conflict with X". That is free prose; extracting a compatibility claim from it
would be exactly the guessing this project exists to remove. The tool points at
the mod and the two versions and lets a human read one changelog.

---

## ADR-0015 — Two rule sources, and where an unreleased build sits

**Status.** Accepted; extends ADR-0013 and ADR-0014.

**Context.** A second community data set exists (krion64.github.io): 814 per-mod
JSON files carrying `conflicts` and `dependencies` inline, ~1,020 conflict and
135 dependency entries, plus an `ord` install-order category and a version per
mod. It overlaps BigWorldSetup-Next-Generation but is not a duplicate of it.

Run against the supplied install the two disagree instructively. BWS-NG raises
18 findings; krion64 raises **none** by default. Neither is broken: BWS-NG rules
mostly say `(-)` — *any* component of mod A conflicts with *any* of mod B —
while krion64 names exact components (`#1500 #1510`). The precise rules correctly
decline to fire because those particular components are not installed. Coarse
rules catch more and cry wolf more; precise rules do the opposite.

**Decision.**

* **Load both, auto-detecting the shape.** `--rules` accepts either a rule-list
  file or a directory of per-mod records; the format is detected per file.
* **Optional integrations are off by default.** krion64 marks 96 dependencies
  `soft` — "Alternate portraits for X" is an enhancement, not a prerequisite.
  Eleven of those buried the one real missing prerequisite in the first run, so
  they need `--include-optional`.
* **An order-sensitive pair with no direction is counted, not guessed.** 375
  entries say two mods are order-sensitive without recording which way round.
  The count is reported; a direction is never invented.
* **`evidenceLevel` is carried into the message** so `mechanism-verified` reads
  differently from an unsourced claim.

**Version ordering for unreleased builds.** A repository that publishes no
release is fetched as a snapshot of its default branch, and the branch name is
recorded as the version (ADR-0011). The ordering is

    branch snapshot  <  alpha  <  beta  <  rc  <  a numbered release

This is a *stability* order, not a chronological one — `master` is usually newer
code than the last tag. Ranking it lowest is deliberate and conservative: under
ADR-0014 a newer installed version withholds a finding as possibly stale, so
treating a snapshot as "newer" would silently suppress real conflicts. A
snapshot never suppresses anything.

**Consequences.** Running both sources gives coarse coverage plus precise
detail, and their disagreements are visible rather than averaged away. Neither
is bundled; you pass the paths.

---

## ADR-0016 — Keeping conflict and install-order data current: BWS-NG rules, krion64 evidence

**Status**: accepted
**Date**: 2026-09-09

### Context

Two community databases describe the same problem space and neither is a superset
of the other.

**BWS-NG** (`Selphira/BigWorldSetup-Next-Generation`, `data/rules/*.json`) is a
*curated rule set*: 851 pairwise statements in one grammar —
`order.json` (`direction: before|after`), `incompatibilities.json`,
`dependencies.json`. Its strength is that a rule is a decision somebody made and
can be argued with. Its weakness is that a rule carries no version qualifier, so
it cannot say "true before v5.1, fixed since", and nothing in the file records
when it was last looked at.

**krion64** (`krion64/krion64.github.io`, `data/mods/*.json`) is an *evidence
database*: 814 mod records, 1,020 conflicts, 135 dependencies, each conflict
carrying `severity`, `reason`, `source`, `evidenceLevel`
(`mechanism-verified` / `speculative`), the affected component numbers
(`myComps` / `theirComps`), and often a date. It also carries the install-order
skeleton the rules do not: 26 ordered categories in `data/categories.json` plus a
per-mod `c` (category) and `ord` (position within it).

Its README states how it is built: six sources merged — the `install-EET-4`
guide (~3,400 component entries), the EET Mod Install Order Guide sheet,
real `WeiDU.log` files, k4thos's EET compatibility list, Endarire's Infinity
Insanity guide, and `EE-Mod-Setup`'s 168 component conflict rules and 105
dependency rules lifted from the EET `Game.ini`. On top of that sit its
`scripts/`: `tp2_to_modjson.py` and `scan_subcomponents.py` derive components
from the tp2 itself, `scan_versions.py` tracks versions, and
`audit_tp2_drift.py` / `drift_scan_all.py` re-read each mod's extracted tp2 and
flag every component whose name has moved since the record was written.

That last mechanism is the important one, and it is the honest answer to "how
does anyone keep this current?". Nobody re-reads 1,020 conflicts by hand. What
you *can* automate is detecting that a rule's subject has changed underneath it.

### Decision

Use both, in the roles each is actually good at, and never merge them into one
undifferentiated blob.

1. **BWS-NG is the constraint source.** Its `direction`ed order rules are what
   the planner turns into edges. They are terse, unambiguous, and already in a
   grammar the solver can consume.
2. **krion64 is the ordering skeleton and the second opinion.** Its
   `categories.json` + `c`/`ord` supply the *global* reference order that BWS-NG
   has no equivalent for — pairwise rules can only say "A before B", never
   "engine mods before tweaks before tactical". Its conflicts load through the
   same `RuleSet` as a second rule source (ADR-0015), with `evidenceLevel:
   speculative` and soft dependencies demoted so they advise rather than block.
3. **Drift, not age, decides whether a rule is still true.** `--mod-db` already
   records the version each rule was written against; `tp2.py` already reads the
   version and component list out of the installed mod. A rule whose subject has
   moved on gets `stale_risk` and stops blocking. This is the same idea as
   krion's `audit_tp2_drift.py`, applied at check time to the mods the operator
   actually has rather than at build time to a maintainer's extraction tree.
4. **A developer's own metadata outranks both.** `.iemod` / `.ini` `Before` and
   `After` come from the person who fixed the incompatibility, so
   `add_metadata_order()` folds them into the same `RuleSet`. When a mod ships
   ordering metadata, third-party rules about it are the older claim.
5. **Suppressions are the escape hatch of last resort**, and they are a file the
   operator writes and dates, not a flag.

### Consequences

* No single upstream has to be right. A rule that only BWS-NG knows still
  constrains the plan; a conflict that only krion knows still warns.
* The refresh procedure is "git pull both repositories" — neither is vendored,
  both are passed by path. Rules are data, never code.
* What this does **not** give you: a guarantee that a rule is current. A conflict
  quietly fixed in a mod that changed neither its version nor its component names
  is undetectable by any of the above, and will keep warning until somebody
  updates the upstream or writes a suppression. Saying otherwise would be a lie
  about what automated drift detection can see.

---

## ADR-0017 — Rewriting the WeiDU logs as an install plan

**Status**: accepted
**Date**: 2026-09-09

### Context

Checking reports 19 order violations across an install of 796 components. A
report is not an answer to "so what order *should* I use?", and hand-sorting 146
mods against 851 rules is not work a person should do.

### Decision

`--plan-order DIR` re-sorts the components already in the logs and writes a fresh
`WeiDU.log` + `WeiDU-BGEE.log` pair, with these boundaries:

* **Rules are constraints, the catalogue is a preference.** Kahn's algorithm over
  the order-rule edges, ties broken by krion's `(category rank, ord)`. The result
  is the closest thing to the reference order that satisfies every rule — not the
  reference order with rules applied afterwards.
* **A dependency is not an ordering constraint.** BWS-NG records both
  `EET: EET_end` and `EET_end: EET`; read as ordering that is a cycle, and the
  first implementation duly pushed the EET core to the end of the install. Only
  `order` rules become edges. Dependencies are checked, never sorted on.
* **The tp2, not the folder, is a mod's identity.** `eet\EET.TP2` and
  `eet\EET_end\EET_end.tp2` share a folder and sit at opposite ends of the
  install. Keying by folder made every `EET_end` rule silently match nothing.
* **Nothing is invented, dropped, or reworded.** Output lines are input lines,
  reordered. A test asserts the multiset of 796 lines is identical.
* **An unknown mod keeps its place**, inheriting the priority of the last ranked
  mod before it, instead of being swept to the end.
* **The phase is not changed silently.** Moving a mod between the two logs
  changes which game it installs onto. It is reported; `--reassign-phase` acts.
* **An incompatibility is not resolved.** Reordering does not change which mods
  are present. Which one to lose is the operator's decision.
* **The output is checked against the rules it claims to satisfy**, and reports
  `NOT COMPLIANT` with the surviving findings when the rules contradict
  themselves, rather than shipping a file with a compliance claim on it.

### Consequences

* On the real install: 6 mods out of place, 0 cycles, plan verified against 132
  constraints; 4 incompatibilities and 1 missing prerequisite reported as things
  reordering cannot fix.
* **A rewritten log is an install plan for a FRESH install**, consumable by
  mod_installer or Project Infinity. WeiDU installs in file order, so an already
  installed game has to be reinstalled for the new order to mean anything.
  The tool says this in its own output; it is the single most important caveat.
* Ordering is at mod granularity, as Project Infinity's sorting order is. A rule
  that constrains one component of a mod against another component of the same
  mod cannot be expressed by reordering and is reported instead.

---

## ADR-0018 — Component-level conflict reporting

**Status**: accepted
**Date**: 2026-09-09

### Context

Ordering answers "in what sequence". It does not answer the question that
follows: *which component of which mod fights which component of which other mod
— or of itself — and what is the smallest thing I can change?*

The raw material is there. BWS-NG writes `cdtweaks(1251,1252):cdtweaks(1257)`.
krion64 records `myComps` / `theirComps` per conflict, grades each claim
`mechanism-verified` or `speculative`, names its `source`, and carries 58 per-mod
known issues (`ki`) that no pairwise rule can express — a 256-entry `SPLSTATE.IDS`
limit, an EEex build tied to an engine version, two `cdtweaks` components that
cost frame rate under EEex. None of that was reaching the operator: the checker
flattened `evidenceLevel` into a prose string, ignored `advisories` and `ki`
entirely, and reported findings as "mod A and mod B are incompatible".

### Decision

A separate `conflicts.py` builds a component-level report from the same
violations, with four rules of its own.

1. **Report the component intersection, not the rule.** A rule's component list
   is a claim about a version of the mod; what matters is which of those
   components you installed. On the real install, 84 (mod-pair, install) pairs
   carry a conflict rule and 79 are clear once intersected. A report that fired
   on all of them would be worse than none.
2. **Name the components, using the operator's own log.** WeiDU already writes
   `// Allow Thieving in Heavy Armor` next to `#2100`. That is a better source
   than any catalogue: it describes *their* install, not some version of the mod.
   Catalogue names are the fallback for components a rule names but nobody has.
3. **Keep provenance structured.** `evidence`, `source`, `workaround` and the
   upstream's own severity word are fields on `Rule`, not text folded into a
   message. A `speculative` finding renders as `SPECULATIVE: not verified, judge
   it yourself`. krion's `advisories` channel loads at `note` severity and is
   withheld unless `--show-advisories` is passed: reading it at conflict weight
   would bury the verified findings, and not reading it discards thousands of
   real component-level observations.
4. **Give the narrowest remedy.** "infinity_ui and stratagems are incompatible"
   is not actionable; "deselect stratagems #4115 (alternative: drop infinity_ui)"
   is. Where a rule pins one side to components and condemns the other
   wholesale, the pinned side is always the cheaper fix. Where it pins neither,
   the report says the rules do not narrow it — rather than inventing a
   preference.

Findings the ordering plan already resolves are marked `FIXED by --plan-order`
instead of being listed as outstanding work; on the real install that turns all
46 order findings from complaints into confirmations.

The report also prints how much was examined — rules evaluated, pairs where both
mods are installed, pairs cleared by the component intersection, order-sensitive
pairs upstream never gave a direction for (439 of them). Without those numbers
"no conflicts found" is unfalsifiable: it reads identically whether the install
is clean or the rule set matched nothing.

### Consequences

* On the real 796-component install: 4 incompatibilities, 1 missing prerequisite,
  13 known issues, 46 order findings all fixed by the plan. Every one names the
  exact components and, where upstream recorded it, the forum thread it came from.
* `--conflict-report PATH` writes the whole thing as JSON, including the findings
  the terminal truncates.
* **What it still cannot do**: `translations.en_US` is preferred over
  `description`, but many BWS-NG rules carry only a French `description`. Those
  reasons print in French. Translating them would be inventing content; the
  alternative is showing nothing. Upstream is the place to fix it.
* A rule whose severity upstream never graded defaults to `warning`, never to
  `error`. Blocking an install on an ungraded claim is not a decision this tool
  gets to make.

---

## ADR-0019 — Testing beyond TDD: properties, mutation, and static analysis

**Status**: accepted
**Date**: 2026-09-10

### Context

561 example-based tests, written test-first, and every defect that actually hurt
this project was a case nobody thought to write: a `? 1 : 0` anywhere in a tp2
suppressing every `GAME_IS` match; twenty mods resolving to the same URL because
a nav link scored just high enough; `EET_END.json` sorting before `eet.json` in
ASCII and claiming the EET core's ordering slot.

TDD gives a test for every case you imagined. It cannot give you the one you did
not, and "write more tests" does not change the shape of that limitation.

### Decision

Four techniques added, each aimed at a class of defect examples cannot reach.
`docs/TESTING.md` is the full account; the decisions are:

1. **Property-based testing (Hypothesis) where a law exists.** Not everywhere —
   most functions have no law worth stating. But the safety predicates are
   total, `normalize_key` is idempotent, version comparison is a strict weak
   ordering, and every parser is total over arbitrary text. Those are laws, and
   Hypothesis searches for counterexamples and shrinks them.

   It skips rather than fails when Hypothesis is absent, because ADR-0002
   promises `python3 -m pytest` works with nothing installed.

2. **Architecture contracts (import-linter) as a CI gate.** A layering diagram
   in a document drifts from the code within two refactors. Four contracts
   instead: the core imports nothing from the shell, the runtime imports no
   third-party package, nothing imports the CLI, and the stack holds.

3. **Static analysis as a gate, not a suggestion.** `mypy` (a subset that
   catches bugs rather than missing annotations), `ruff` with an explicitly
   chosen rule set, `bandit` with every skip carrying its reason in-file, and
   `-W error` in pytest so a stdlib `DeprecationWarning` is the earliest
   possible notice that a future Python breaks this.

4. **Mutation testing, nightly, reporting and never gating.** Coverage says a
   line ran; mutation testing says the tests would have noticed if it were
   wrong, which is what coverage is routinely mistaken for. It reports because a
   surviving mutant is a question, not a defect, and sometimes "it does not
   matter" is the right answer.

### Consequences

Turning them on found four defects the same day:

| Found by | Defect |
|---|---|
| Hypothesis, first run | `compare("master","main")` and `compare("main","master")` both returned 1 — `is_newer` true in both directions, so a default-branch rename could mark a rule stale |
| bandit (B202, high) | `extractall` was handed a member list after validation: the names validated and the paths the library resolves were two separate facts |
| bandit (B101) | a manifest invariant was an `assert`, which `python -O` strips |
| import-linter | `catalogues → resolvers` via a function-local import to dodge a cycle — a pure function trapped in an impure module, now `urls.py` |

Plus 16 typing defects, one of which was a live `NameError` in the extraction
path, and two tests leaking file handles.

**The cost, stated honestly:** four more tools in the developer toolchain, a
slower nightly, and a set of ignore-lists that must carry their reasons or they
rot. The properties took longer to write than the equivalent examples would
have. The first one paid for all of it.

**What is still not covered:** the live GitHub API has never been exercised from
CI. Everything about it is tested against a hand-written double encoding what I
believe the API does. That is the largest untested surface and it is item A on
the roadmap.

---

## ADR-0020 — Functional core, imperative shell — and no pattern apparatus

**Status**: accepted
**Date**: 2026-09-10

### Context

Making the project repository-ready invited the question of whether it should
adopt a recognised architecture — clean architecture, hexagonal, a service
layer, dependency injection, repository interfaces.

### Decision

No. The structure is **functional core / imperative shell**, plus "parse, don't
validate" at the boundaries, typed errors, and dataclasses as values. That is
the entire paradigm budget, and each item is there because a specific failure
argued for it.

The argument against the alternatives is not that they are bad ideas; it is that
this codebase does not have the problems they solve. There is no database to
abstract, one delivery mechanism, and no plausible second implementation of
anything. A `ManifestRepository` with exactly one implementation, an abstract
resolver factory, or a service layer wrapping a pure function would each add a
file, an indirection and a test double, and would prevent no defect that has
ever occurred here. Indirection you cannot point at a failure for is cost
without benefit.

What HAS caused defects is a decision that cannot be tested without a mock, and
a pure function trapped inside an impure module. The core/shell split addresses
both, and `import-linter` makes it a gate rather than an intention.

### Consequences

- Every parser, comparator, rule check, order solve and report render is a
  function of its inputs, testable with no network, no temporary directory and
  no clock. 582 tests run offline in about thirteen seconds.
- Dependency injection happens by passing an argument. `Runner` takes a client;
  `OrderIndex.load` takes a path. There is no container, and the "interfaces"
  are two `Protocol`s introduced only where the checker needed one.
- The contract is falsifiable: `lint-imports` says which import broke it.
- **The honest cost:** the shell is thin but not tested as thoroughly as the
  core, because testing it well needs a network. That is the trade — the
  interesting logic is where the tests are strongest, and the untested part is
  the part with the least logic in it.
