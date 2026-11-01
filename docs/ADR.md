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

*Note (2026-10-23).* GitHub App installation tokens (`ghs_`) became stateless
in 2026: a JWT after the prefix, about 520 characters, with two dots and `-`.
The shape refused them, so such a token in the credential helper was dropped
in silence and the run went anonymous. The shape now takes `ghs_` followed by
three non-empty base64url segments (at least 36 characters after `ghs_`); the classic
shapes are unchanged. Tokens from the environment, `--token-file` and `gh` were
never shape-checked and were not affected - the workflows' `GITHUB_TOKEN`
kept working.

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

---

## ADR-0021 — Conflict resolution: only what the rules decide, only in the plan

**Status**: accepted (amends ADR-0017's "an incompatibility is not resolved")
**Date**: 2026-10-20

### Context

ADR-0018 made every finding name its narrowest remedy — "deselect stratagems
#4115 (alternative: drop infinity_ui)". Operators then did by hand, for every
finding, exactly what the report told them. Where the rule itself decides which
side goes, that manual step adds nothing but typos. Where it does not, an
automatic choice would be a guess with a delete key.

The Infinity Orchestrator draws the same line: kinds such as `included`,
`mismatch` and `not_compatible` disable a component automatically; `conflict` is
only flagged. BWS-NG's own UI does the same.

### Decision

`--resolve-conflicts` (opt-in, requires `--plan-order`) removes components from
the **plan** — never from the operator's logs — for a finding that is:

1. an incompatibility,
2. graded `error` by its rule set,
3. not graded `speculative`,
4. between two different mods,
5. pinned to components on at least one side.

The side removed is the one the report already names as cheaper (a pinned side
is always cheaper than a wholesale one; between two pinned sides, the fewer
components). Exactly the components the rule named and the plan contains are
removed; a mod left with none leaves the plan.

Everything else — whole mod vs whole mod, same-mod option groups, missing
dependencies, warnings, speculative claims — is listed under "left for you to
decide" with the reason, and the plan is re-verified afterwards. The decision
record is written beside the plan as `RESOLUTION.json`.

### Consequences

- The input check still reports the conflict and still exits non-zero: the
  operator's install has not changed. The plan has.
- A mod key that names two tp2s in one folder (`eet`: EET and EET_end) is
  refused rather than resolved, because which one the rule meant is ambiguous.
- Tested both ways: each class of refusal has a test that it removes nothing.

---

## ADR-0022 — Installing the plan: generate scripts for mod_installer, never run them

**Status**: accepted
**Date**: 2026-10-20

### Context

The tool stopped at a planned `WeiDU.log` pair. Turning that into an installed
EET game means running WeiDU against two game directories in order, batching
consecutive components, answering prompts, and handing EET's core the BGEE
path — then doing the same on Windows and Linux.

That is solved. dark0dave's
[mod_installer](https://github.com/dark0dave/mod_installer) (GPL-3.0) takes
exactly such a log pair: `mod_installer eet -1 <BGEE> -y <bgee log> -2 <BG2EE>
-z <eet log>`. Born2BSalty's Infinity Orchestrator builds no WeiDU command line
of its own; it writes the logs and runs mod_installer. Reading mod_installer's
source showed one hard requirement: it recognises the EET core by the log
comment `EET core (resource importation)`, and only then passes the BGEE path.

### Decision

`--emit-installer` writes `install-eet.sh` + `install-eet.cmd` (or `install.sh`
+ `install.cmd` for a single game) next to the plan. Each script:

- refuses a directory without `chitin.key`, and a game that already has mods
  (`ALLOW_EXISTING=1` overrides) — a plan is for a fresh install (ADR-0017);
- resolves mod_installer and WeiDU, or says which one is missing;
- makes one mod_installer call, with `DRY_RUN=1` to print it instead.

At generation time the plan is checked for what would otherwise fail forty
minutes in: the EET core's comment, EET_end last, and every mod folder present
in the staging directory.

**iemod-fetch never executes the scripts, WeiDU or mod_installer.** ADR-0006
("nothing downloaded is executed") stays literally true; the operator reads and
runs a 40-line script. mod_installer is invoked, never vendored, so its GPL
does not reach this MIT repository.

### Consequences

- The full path is: fetch → `--plan-order --resolve-conflicts --emit-installer`
  → run one script → play. Same artefacts on Windows and Linux.
- The shell script is executed in the test suite against a stand-in
  mod_installer; the `.cmd` script is executed on the Windows CI runners.
- Verified against the real thing: the generated `install-eet.sh` was run with
  the mod_installer 16.0.0 binary built from source and a stand-in WeiDU that
  records its calls. mod_installer installed the BGEE log in the BGEE folder,
  then the EET core, the EET mods and EET_end in BG2EE — and passed WeiDU
  lower-cased paths (`eet/eet.tp2`). That last fact is why the Linux script
  refuses mixed-case mods before anything runs, unless `--casefold` is passed.
- **What is not verified here:** a real WeiDU install against real game data.
  That needs the games, which no CI runner has.
- mod_installer marks its EET mode BETA. That is its maturity, inherited
  honestly, and the guide says so.

**Amendment (2026-10-21) — ties, same-mod conflicts, WeiDU subcomponents.**
A tie (both sides pin the same number of components) is no longer resolved by
taking the left side: that was a guess, and it is now left to the operator. A
same-mod conflict with an unequal split is resolved like a cross-mod one (the
group with fewer components goes). Two options of one WeiDU SUBCOMPONENT group
(`// Group -> Option` in the log) are detected without any rule set and resolved
by keeping the last one — what WeiDU itself ends with, since installing the
second uninstalls the first. On the real install: 3 resolved, 1 tie left.

---

## ADR-0023 — Component-level install order

**Status**: accepted (closes ROADMAP 2026-09 item C)
**Date**: 2026-10-21

### Context

A mod is not one thing. krion64 files stratagems #1500 under SPELL MODS and
#4100 under POST EET (`co[].cat`); BWS-NG's curated EET order splits stratagems
into four separate runs; rules name components
(`stratagems(5900):cdtweaks`). The planner sorted whole mods, so none of that
could be honoured. And the checker judged "A before B" on the *first* component
of each — and numbered components by the parser's per-mod grouping rather than
by log line, so a mod's components always looked adjacent.

### Decision

- **The checker** judges every named component: "A before B" means the last of
  A's named components precedes the first of B's, by real log line.
- **The planner** splits a mod into contiguous parts where the catalogue
  (`co[].cat`) or a component-naming order rule distinguishes its components.
  A mod nothing distinguishes stays one unit, exactly as before. Parts share the
  mod's catalogue position and are tie-broken by log line, so they keep their
  original order unless a rule says otherwise. A rule between two components of
  the same mod is honoured when they fall in different parts.
- Like krion64's own export, a moved component takes its new category and the
  MOD's `ord`; the component `ord` field, which krion64 does not read, is not
  read here either.

### Consequences

- On the real install the old checker's 46 order findings included **34 false
  positives** ("X should be installed before EET_end", with EET_end logged
  last); the fixed checker reports 14, two of them new and real. The plan
  splits 6 mods and verifies against 158 constraints.
- The plan still contains exactly the input lines (tested).
- mod_installer installs whatever order the log gives, batching consecutive
  components of one mod, so a split plan needs nothing new downstream.

---

## ADR-0024 — Preferred installation language, with fallback

**Status**: accepted
**Date**: 2026-10-21

### Context

A log line's `#lang` is an index into that mod's own LANGUAGE declarations:
1 is Italian in one mod and French in the next. mod_installer passes it
through unchanged. The community tools differ: krion64 uses one language then
English; BIO one locale then English, probing `--list-languages`; BWS-NG keeps
an ordered preference list, takes the first a mod offers, and reads the tp2's
LANGUAGE declarations through an alias table.

### Decision

BWS-NG's model. `--language-preference it_IT,en_US` (names work too) rewrites
each planned line's `#lang` to the first preferred language the staged mod's tp2
declares, matched on the declaration's language directory and then the first
word of its display name, through an alias table — without BWS-NG's
"dutch → German" slip. The index is the declaration's position, duplicates
included. The game language passed to mod_installer defaults to the first
preference.

### Consequences

- A mod offering none of the preferences keeps its logged index and is listed
  with what it does offer; a mod not staged yet is listed too. Nothing guessed.
- It needs the mods fetched first (it reads their tp2), so it belongs to the
  planning step after the fetch, as the guide's chapter 10 orders it.

---

## ADR-0025 — The mods' own tp2 constraints, and an install simulation

**Status**: accepted
**Date**: 2026-10-21

### Context

A plan that passes every community rule can still stop mod_installer halfway:
WeiDU itself refuses a component whose own tp2 says no. A mock EET install
built from verbatim upstream tp2 excerpts (`tests/data/eetmock`) shows the
traps: DlcMerger aborts on anything but BGEE; EEFixPack declares
`!GAME_IS ~eet~`; a Tweaks component installed on BGEE makes EET refuse the
merge (`tbl/compatibility.tbl` is an allow-list of 27 BG:EE mods, and EET.tp2
also fails on two wrong options); Tweaks #4010 is BG2EE-only and stops holding
the moment the EET core turns BG2EE into EET; Ascension FORBIDs SCS #5900.

The community handles this metadata in two ways. BWS-NG copies it by hand into
`order.json` / `incompatibilities.json` (SCS's `FORBID_COMPONENT` against
Tweaks #2370 becomes `stratagems(4100):cdtweaks(2370,2372,4020)`), which lags
behind the mod version actually downloaded. The Infinity Orchestrator parses
`REQUIRE_COMPONENT`/`FORBID_COMPONENT` from the tp2 and puts a required
component first. Neither simulates the install.

### Decision

1. **Read the staged tp2s** (`constraints.py`): per component, REQUIRE_COMPONENT,
   FORBID_COMPONENT and the simple REQUIRE_PREDICATE forms (GAME_IS, ENGINE_IS,
   GAME_INCLUDES, MOD_IS_INSTALLED, negated), plus a body-level
   `ACTION_IF NOT GAME_IS … ABORT`. Compound predicates are counted as unread,
   never guessed.
2. **Turn them into rules**, origin `mod tp2`:
   * REQUIRE → the required component first (the Orchestrator's reading), plus
     a dependency; both error.
   * one-sided FORBID → the declaring component first (WeiDU checks a FORBID
     only against what is already installed), error; plus a *warning*
     incompatibility, because the tp2 does not say whether the two coexist
     (EET's means "install me first", SCS's against Tweaks means "never
     together" per BWS-NG). A warning is never auto-resolved; a community rule
     graded error decides.
   * mutual FORBID → an incompatibility, error: no order installs both.
3. **Read EET's merge check from the staged EET** (`compatibility.tbl` and the
   `COUNT_REGEXP_INSTANCES … PATCH_FAIL` blocks).
4. **Simulate** (`simulate.py`, `--simulate`): walk the plan in order; the BGEE
   log on BGEE (+SoD), the EET log on BG2EE that becomes EET after `eet #0`.
   BGEE-phase mods do not count for MOD_IS_INSTALLED on EET: EET.tp2 copies the
   BG:EE log to `WeiDU-BGEE.log`, not into `WeiDU.log`.
5. **`--resolve-conflicts` drops what WeiDU would refuse**, with WeiDU's reason,
   re-simulating until nothing is refused (8 rounds at most). For a refused EET
   merge it drops the BG:EE mods outside the table, or the wrong option. The EET
   core is never dropped: any other refusal of it is left for the operator.

### Consequences

- The mock EET install goes from "EET refuses the merge" to "0 would be
  refused", each removal explained; the generated installer is then run
  against a stand-in mod_installer.
- Only what WeiDU's flags express is checked. A mod that fails inside its own
  body for a reason no flag states is not caught; compound predicates are
  counted, not evaluated. Mods not staged are reported as unchecked.
- EET's M flag (merge anyway) is not modelled as an option: the plan never
  depends on overriding the author's check.

---

## ADR-0026 — Verified game folders, reorder before removing, and the real WeiDU as the test oracle

**Status**: accepted
**Date**: 2026-10-21

### Context

ADR-0025's simulator was checked only against itself. Four questions remained:
are the game folders the plan installs onto really BG:EE and a clean BG2:EE;
when WeiDU would refuse a component, is removing it the right fix or is there
an order that keeps it; can the result be tested against the real WeiDU without
copyrighted game data; and which tool and mod versions does the plan assume.

Primary sources: WeiDU's `src/tppe.ml` (PE_GameIs) identifies a game by marker
resources — `oh1000.are` BG:EE, `oh6000.are` BG2:EE, `eet.flag` EET — looked up
in override/ and chitin.key. EET's readme: the core needs "a clean BG2:EE
installation with latest patch (currently v2.6.6.0) and (optionally) the
Enhanced Edition Fixpack", and BG:EE with SoD (checked through
`movies/sodcin05.wbm`); GOG/Steam ship SoD as a DLC archive DlcMerger must merge
first. EET.tp2:2797 writes `override/EET.flag`. BWS-NG's `games/eet.json`
orders `eefixpack:0-2` before `eet:0` in its bg2ee sequence, and lists the mods
allowed on the BG:EE side.

### Decision

1. **Game folders** (`gamedir.py`, `--bgee-dir` / `--bg2ee-dir`): identify each
   folder with WeiDU's own rule, reading chitin.key; refuse a swapped pair, the
   same folder twice, an already-EET game, a modded BG2:EE, and a BG:EE without
   SoD; require DlcMerger in the plan when SoD is still a `sod-dlc` archive.
   Read only, never written. The patch level and the integrity of the game data
   are reported as not checked.
2. **Reorder before removing.** A refusal that a documented order fixes is fixed
   by that order: EEFixPack refused on EET moves before the EET core, where the
   game is still BG2:EE. The list of what may precede the core is EET's own
   (EEFixPack), confirmed by BWS-NG; nothing is moved on inference. Everything
   else WeiDU would refuse is still removed with its reason.
3. **The real WeiDU is the oracle** (`tests/test_real_weidu.py`): two synthetic
   game folders — an empty chitin.key, an empty dialog.tlk, the marker file —
   are enough for WeiDU to evaluate GAME_IS, REQUIRE and FORBID. The mock mods
   run from their verbatim excerpts (complete one-line flags only). Asserted:
   real WeiDU refuses exactly what the simulator says on the raw logs; it
   installs the resolved plan to the last component; and the generated
   `install-eet.sh` runs through the real mod_installer into both games, the EET
   core writing `EET.flag` between them. A CI job runs it on every push.
4. **Pinned toolchain.** WeiDU v251.00 (official Linux release, sha256
   recorded); mod_installer at commit `3b6827a` (Cargo 16.0.0 — its tags stop
   at v12.1.1, so a commit, not a tag, is the pin). Mods: a release tag plus
   sha256 through `--emit-pinned-manifest`; a mod without releases is pinned by
   the archive's sha256. "Latest" or a branch head is never a pin. The games:
   v2.6.6.0, as EET requires; not verifiable from the folder, so stated.

### Considered and not adopted

- **GemRB** (an open-source reimplementation of the Infinity Engine). Its
  KEY/BIFF readers and its free demo data are the community's answer to "tests
  without game data". But WeiDU, not the engine, decides what installs; booting
  the result in GemRB would test GemRB's engine, not the install, and needs the
  same game data. The synthetic-folder approach tests the real installer instead.
- **BWS-NG's per-game order lists** as the source of truth: hand-maintained,
  they lag behind the downloaded mods. Read as rules (ADR-0017), cross-checked
  against each mod's own tp2 (ADR-0025).

### Consequences

- Two fixture bugs and one parser bug were found by real WeiDU on the first run:
  a `BEGIN` inside an inlined file (`<<<<<<<< … >>>>>>>>`) counted as a
  component, which hid EET_end's requirement on the EET core; and EET_end
  staged where WeiDU 251 does not look for it.
- Still not covered: real game data (patch level, the merge itself, mods whose
  bodies fail on content). That needs a self-hosted runner with owned copies
  (ROADMAP F5).

---

## ADR-0027 — Releases are tagged and published by the merge, not by a person

**Status**: accepted
**Date**: 2026-10-21

### Context

The release process (RELEASING.md) ended with "tag and push", a step done by
hand on a machine with push rights. It was never done for 2.1.0 or 2.2.0, so the
releases existed only in the changelog. The workflow behind it had never run:
it called `ci.yml`, which was not reusable.

Two approaches in the maintainer's own repositories: R-studioConf (ADR-0006)
tags and releases from the newest CHANGELOG.md section on every push to main;
Proxmox_biome_log_collector releases on a pushed tag, plus a manual trigger for
tags made before the workflow existed. Elsewhere, release-please and
semantic-release derive the version from commit messages. This project already
writes its changelog by hand and reviews it in the pull request.

### Decision

R-studioConf's model, plus Proxmox_biome_log_collector's manual trigger:

- the newest `## [X.Y.Z]` section of CHANGELOG.md is the release; an existing
  tag means it is done;
- the commit released is the first main-line commit where `__version__` says
  X.Y.Z, which is the merge of the release pull request (`tools/release_plan.py`,
  tested on a scratch repository);
- the release workflow creates the tag together with the release. A tag pushed
  with GITHUB_TOKEN would start no workflow, so it cannot be a separate step;
- releases are published, not left as drafts: the notes were reviewed in the
  pull request. PyPI stays opt-in (`PYPI_PUBLISH`) and keeps its environment
  gate.

release-please and semantic-release are not adopted. They would replace a
hand-written, reviewed changelog with one generated from commit messages.

### Consequences

- Merging a version bump is the release; there is no step left to forget.
- A changelog section whose `__version__` never reached main makes the workflow
  fail and say so, instead of tagging the wrong commit.
- The CI gate a release re-runs is main's current code. A back-filled older
  version, such as 2.1.0, relies on the CI its own pull request passed.
- GITHUB_TOKEN cannot create a tag on a commit whose workflow files differ from
  main's; it can never hold the `workflows` permission. Seen on the first runs:
  403 at the release step for both 2.2.0 and 2.1.0. So when nothing shipped
  (`iemod_fetch/`, `pyproject.toml`, `build.py`, README, LICENSE) changed since
  the version commit, main's head is tagged, which gives the same artifacts. A
  true back-fill stops at planning with the two ways out: a tag pushed by hand
  and then released by a manual run naming that version (a tag push alone runs
  the tagged commit's own, older workflow), or an optional `RELEASE_TOKEN`
  secret.
- No step needs a person except creating that secret. Corrected notes reach
  their release on the next push to main; editing a release creates no ref.
  Listed back-fills are released by the automatic run once the secret exists.
  The session that maintains this repository can merge but cannot start a
  workflow or push a tag, so everything after a merge has to happen inside the
  workflow.
- For the same reason a change to the pipeline is rehearsed on its own pull
  request (gate, build, attestation; never notes, tag or publish): a manual dry
  run is not available to that session, and an action bump used only at
  release time would otherwise first run on a real release.

**Amendment (2026-10-31): `RELEASE_TOKEN` is checked, not trusted.** 4.0.0's
run passed its gate, built and attested, then its publish step met "Bad
credentials": the secret had expired, and `secrets.RELEASE_TOKEN ||
github.token` takes any non-empty secret. Now only a release that needs the
secret (workflow files differ from `main`'s) uses it, and the first job asks
GitHub for the repository with it; only an HTTP 200 makes it the publishing
token. A rejected one stops that release in the first job, in seconds; every
other release uses the run's own token, whatever the secret. The check proves
the token is live, not that it may write here (the repository is public).
"Latest" is judged against `main`'s changelog, also on a tag pushed by hand,
so a back-fill never displaces a newer release. How to renew the token, and
why an old failed run must not be re-run: docs/RELEASING.md, "RELEASE_TOKEN".

---

## ADR-0028 — Dependencies: Dependabot for what it sees, an issue for what it cannot

**Status**: accepted
**Date**: 2026-10-21

### Context

Dependabot was configured for the developer tools (pip) and the pinned actions,
but had never opened a pull request. On a fork its version updates stay off
until they are switched on in the repository's settings. The CI logs warn that
the pinned actions still run on Node 20. The test toolchain added in ADR-0026
(a WeiDU release zip with a sha256, a mod_installer commit) is invisible to
Dependabot in any case. The tool itself ships with no dependencies (ADR-0002).

### Decision

- Dependabot keeps the pip and github-actions ecosystems. Action updates are
  grouped into one weekly pull request, the same way the developer tools are.
  It is switched on in the repository settings; that is a setting, not code.
- `upstream-versions.yml` (`tools/upstream_versions.py`) compares the pinned
  WeiDU and mod_installer with upstream every week. For WeiDU that is the newest
  release tag, excluding nightlies and release candidates. For mod_installer it
  is the Cargo.toml version, because its tags stop at v12.1.1. One issue opens
  per tool behind, and the run stays red until the pin moves. This is the
  method of Proxmox_biome_log_collector.
- No automatic pull request for those two, and no auto-merge. A new digest is
  only as trustworthy as whoever verified it. Auto-merge without required
  status checks on main would merge before CI finished.
- The supported Python versions are a product decision, not a dependency:
  Dependabot does not move them. CI keeps testing the floor and the newest
  release. Raising the floor from 3.9 is roadmap item E6, a major version.

### Consequences

- Updates arrive as reviewable pull requests or issues. None of them is a
  release on its own: a release still needs a changelog section (ADR-0027).
- A person switches Dependabot on once, and verifies each new WeiDU digest.

---

## ADR-0029 — A UI on top of the CLI: a phased wizard that ends by installing

**Status**: accepted
**Date**: 2026-10-21

### Context

ROADMAP 2.3 ruled out a GUI ("Project Infinity is the GUI") and running WeiDU
(ADR-0003). The owner now wants a complete tool in the style of
BigWorldSetup-NG, Infinity Mod Forge/Runner and BIO: pick mods and components,
see updates, get the order and conflicts resolved, then install. The audit in
[GUI-AUDIT.md](GUI-AUDIT.md) found the core strong (verified downloads, a
computed order, automatic resolution) and the CLI not yet usable as a backend.

### Decision

- A UI is in scope. It is a client of a public API (`iemod_fetch.api`) and has
  no logic of its own. The CLI is the other client, and everything the UI can
  do the CLI can do too.
- The UI is a wizard in phases, the order BWS-NG uses: **game and folders →
  backup → mod selection → install order → download → extraction →
  installation**. Each phase can be left and resumed, and each one writes a
  file the CLI also accepts (`selection.json`, the order, the staged folder).
- **Installing is in scope, as the last phase.** It replaces ADR-0003's "never
  runs WeiDU". It comes last in delivery (M4), after selection, order,
  conflicts and download are complete and tested, and it starts only on an
  explicit action, after a backup of the game folder has been offered.
- The CLI is made complete first (M1 and M2), and the UI starts only when
  their acceptance tests pass.
- No code or bundled data from GPL projects (BIO, BWS-NG, mod_installer).
  Their formats are read and written for interoperability.

### Consequences

- ADR-0003 is superseded on one point: the tool may run WeiDU or
  mod_installer, in the install phase only.
- `cli.py` loses its private orchestration to `api`. That refactor touches
  every entry point and needs the full test suite green throughout.
- Installing brings new failure modes (a half-installed game, WeiDU prompts,
  Windows paths). M4 has its own acceptance tests and real-WeiDU CI.

---

## ADR-0030 — A versioned JSON contract: selection in, reports and events out

**Status**: accepted
**Date**: 2026-10-21

### Context

The only selection format is WeiDU.log, the JSON reports carry no schema
version, and progress is printed text. A UI, or any other front end, needs a
contract it can depend on.

### Decision

- `selection.json` (`schema_version: 1`): game, mods, components, language and
  subcomponent choices. It turns into the same internal objects as a WeiDU.log.
- Every JSON output gets `schema_version`, and every finding a stable id.
  JSON Schema files are published in the repository, and tests validate the
  outputs against them.
- `--events jsonl` streams progress events (one JSON object per line). It is
  the same stream the API delivers to an `on_event` callback.
- Error records carry a stable `code`.
- A breaking change to any schema is a major version (the CLI's public surface
  already includes the JSON report, as CHANGELOG says).

### Consequences

- Front ends in any language can drive the tool through the CLI alone.
- Schemas become something to maintain and to version with care.

---

## ADR-0031 — The UI is a PySide6 desktop app, packaged apart from the CLI

**Status**: accepted
**Date**: 2026-10-21

### Context

ADR-0002 keeps the shipped tool to the standard library in one `.pyz`. The
options compared in the audit were Tkinter, PySide6/Qt, a local web page,
Textual, and a separate Tauri/egui front end. The owner chose the BWS-NG model:
a desktop wizard in PySide6, the UI the community already knows.

### Decision

- The GUI is a separate package, `iemod_fetch_gui`, in this repository. It
  depends on PySide6 (LGPL-3.0, used unmodified and dynamically linked, which
  an MIT application may do) and imports only `iemod_fetch.api`.
- The CLI is unchanged: still standard library only, still one `.pyz`.
  ADR-0002 holds for the CLI. `iemod_fetch` may never import the GUI, and
  import-linter enforces it.
- The GUI ships as its own download per OS, built with PyInstaller in the
  release workflow, attested like the `.pyz`, together with Qt's LGPL notice.
  `pip install iemod-fetch[gui]` also works.
- Screens follow BWS-NG's patterns as ideas, not code: a category column; a
  mod → component → choice tree with tri-state checkboxes, radio buttons for
  exclusive groups and drop-downs for prompts; search and "selected only /
  conflicts only / updates" filters; a details pane; a conflicts panel with
  one-click options; EET order as one tab per phase with drag to reorder.
- Long work (download, extraction, install) runs in a worker thread and reaches
  the UI through the ADR-0030 event stream, so the window never blocks and
  every phase can be cancelled.

### Consequences

- The GUI download is large (roughly 100-200 MB per OS). The `.pyz` stays small
  for those who want only the CLI.
- CI grows: GUI tests under pytest-qt with `QT_QPA_PLATFORM=offscreen`, and a
  PyInstaller build per OS at release time.
- Dependabot watches PySide6 and PyInstaller like the other dev tools; a Qt
  security update means a GUI release.

---

## ADR-0032 — The community data is refreshed automatically when a run starts

**Status**: accepted
**Date**: 2026-10-21
**Amends**: ADR-0009 (catalogues were read from a path and "never fetched
automatically")

### Context

Install order and conflicts are decided from three community databases:
lcc-docs (the mod list, status, rating), BigWorldSetup-NG (rules, per-mod
records) and krion64 (order categories, per-mod conflicts, release scan). Until
now each was a `git clone` the user had to make, pass by path and remember to
`git pull`. A clone nobody pulls goes stale silently, and every order and
conflict decision goes stale with it. The owner asked for this problem to be
solved for good: the data refreshed by itself when the program starts.

Measured: the files the tool reads are about 25 MB in total (lcc-docs
`db/mods.json` 2.4 MB; BWS-NG `data/` 3.4 MB; krion64 `data/` 14 MB, in a
487 MB repository that is mostly images).

### Decision

- A per-user cache (`$IEMOD_DATA_DIR`, else `%LOCALAPPDATA%\iemod-fetch\data`,
  `~/Library/Caches/iemod-fetch/data` or `~/.cache/iemod-fetch/data`) holds the
  three sources, each pinned to the commit it came from (`sources.json`).
- Every run refreshes it first, at most once per `--data-max-age` hours
  (default 24): one API call for the current commit; if it moved, one for its
  file list; then only the `.json` files under the paths the tool reads, and
  only those whose git blob hash changed, from raw.githubusercontent.com at
  that commit. Each file is checked against the hash GitHub listed before it is
  kept; the new copy is assembled beside the old one and swapped in whole.
- Offline, rate-limited or refused, a source keeps its last good copy and the
  run says how old it is. A refresh never stops a run.
- The cache stands in for `--catalogue`, `--rules`, `--mod-db` and
  `--order-catalogue` whenever those are not given. An explicit flag always
  wins. `--no-default-data` turns the stand-in off, `--no-update-data` (or
  `IEMOD_NO_UPDATE_DATA=1`) the network, and `--update-data` refreshes now and
  stops.
- Cached files carry the upstream commit date as their modification time, so
  the rule-staleness warnings judge upstream's age, not the download's.
- Still never bundled. The data keeps its licence (lcc-docs and krion64 MIT,
  BWS-NG GPL-3.0); the user's own run fetches it and the tool reads it as data.

### Consequences

- `--plan-order` no longer needs `--order-catalogue`, and a check uses the
  community rules without any setup. A run that passed with no rules given may
  now report findings: that is the point, and `--no-default-data` restores the
  old behaviour.
- A run makes up to six GitHub API calls a day; anonymous use allows 60 an hour.
  The first refresh downloads about 1,200 small files; later ones download what
  changed.
- The refresh trusts GitHub for the listing: the hash proves the file is the
  one GitHub listed at that commit, not who wrote it. The files are data read
  by size-limited parsers, never executed; paths that would leave the cache
  are refused.
- `.github/workflows/community-data.yml` runs the real refresh against GitHub
  on every pull request that changes it and every night.
- Every update is guarded before it is swapped in: valid JSON, readable by the
  tool's own parsers, and no count (mods, rules, order entries) at zero or
  below half of the last good copy's. A refused commit is remembered and not
  fetched again until upstream moves. An accepted update records what changed
  (counts, mods added and removed, versions and statuses), so an update that
  changes the advice the tool gives is never silent.

---

## ADR-0033 — Conflicts are answered with options; the player's answer wins

**Status**: accepted
**Date**: 2026-10-21

### Context

`--resolve-conflicts` applies the rules' own remedy only where they decide
(ADR-0021). Everything else - a tie, a warning, a whole mod against a whole
mod - is "left for you to decide", and until now deciding meant editing the
plan's WeiDU.log by hand and re-running without the flag. A GUI cannot do
that, and neither can a player who wants the same choice next time.

### Decision

- Every finding carries **options**: deselect one side (its cost is the
  number of chosen components lost), reorder (what the plan already does), or
  install a missing prerequisite (not applicable to a plan: it needs a fetch).
  Each has a stable id derived from the finding's id. `recommended` marks what
  `--resolve-conflicts` would do, and only where the rules decide.
- A **decisions.json** (schema v1) records the player's answers: `choose` an
  option, or `accept` a finding with a reason.
- `--decisions` applies them to the plan **before** `--resolve-conflicts`, which
  skips every decided finding. The plan is re-checked afterwards; the report
  marks a chosen finding fixed by the plan and an accepted one suppressed,
  with the reason.
- A decision whose finding is no longer in the report is **stale**: reported,
  never re-targeted. An option id that belongs to another finding is an error.

### Consequences

- The "left for you to decide" list becomes a set of buttons for the GUI and a
  file the CLI can replay; the WeiDU logs are still never edited.
- Ids are stable for the same selection. Changing the selection can make a
  decision stale; that is reported, and the player decides again.
- A player can accept a conflict the rules grade `error`. The report keeps it
  visible as accepted, with the reason they gave, rather than hiding it.

**Amended 2026-10-22 (M3 phase 2, the wizard's conflicts panel).**
`api.selection_conflicts` judges a selection before anything is downloaded,
with the rules, the staged tp2s and the planned order a run uses, and returns
the run's findings with their ids; the panel turns each option into a button
(deselect a side, choose a missing prerequisite the list knows, or write an
install-order choice or an acceptance to `decisions.json`). Building it found
that the run's own `--conflict-report` named each install by its log's file
name while `--decisions` names it by the plan's role, so any log not already
named `WeiDU.log` (EET) or `WeiDU-BGEE.log` - every `--selection` run - got
report ids no decision could match. The report now uses the plan's names when
there is a plan, and shows each log's own file name. Ids of a plain
`-w WeiDU.log:EET` run are unchanged. The panel always names installs by role,
so a decision saved before the order data arrives still matches a planned
run. A reorder is not offered as a decision on a finding the plan could not
settle: `--decisions` applies a reorder only by sorting, which already failed
for it, so recording it would mark the finding settled and change nothing.

**Amended 2026-10-23 (GUI-AUDIT item 28, the owner's decision): keep both,
one installed last.** Two components that touch the same thing, where no rule
says they must not coexist, had only "deselect one side". An incompatibility
graded below `error` - krion64's partial and soft conflicts, its overlap
advisories, BWS-NG's warnings - now also offers, each way round, "keep both,
X installed last (its changes win)" (`conflicts.KEEP_BOTH`; the schema's
action enum gains `keep-both`). Never for an `error`: a hard incompatibility
is not an overwrite an order can settle. Never between components of one mod.

Context: `--decisions` applied a choice only by removing components; an
order chosen by the player had nowhere to go, because a run plans before it
reads the decisions. Decision: a chosen "keep both" becomes an order rule
(`resolution.keep_both_rules`, origin `decisions.json`): the winner after the
loser, component for component as the finding names them. The run plans,
builds the conflict report, turns the chosen options into rules, plans again
with them on top of the rule set (`api._plan_with_decided_order`), and only
then applies the rest of the decisions; finding ids do not depend on the
order, so they still match. The finding is then recorded as accepted, with
the option's own words as the reason, and is no longer outstanding. The
wizard does the same: `selection_plan` and `selection_conflicts` read the
project's `decisions.json`.

Not offered both ways where a rule already says which way (review of #72):
a tp2's one-sided FORBID_COMPONENT makes an error order rule and a warning
incompatibility, so only the forbidden side may go last; and a pair an error
incompatibility also covers (BWS-NG hard where krion64 is soft) is not an
overwrite to order, so it offers none. A decision for a way round that is
not offered goes back to the player with the reason.

Consequences: a "keep both" that contradicts another rule is not hidden -
the plan reports the contradiction (a cycle, or a rule it could not keep),
and a kept order the plan could not keep is left to the player, never
recorded as accepted. The decided rules are the player's, like the Sorting
Order: a mod's own ini does not set them aside. Not every incompatibility
below error is an overwrite (stacked experience, a script bug); "its changes
win" is then only the order, which is the player's to judge - and two
decisions are not checked against each other. A command-line run applies
them with `--decisions`; the project's ini does not name the file. The rule is re-made every run from the
current findings; a decision whose finding is gone makes no rule and is
reported stale, as before. What "its changes win" means is WeiDU's own
semantics - the later install's copy of a shared file stays - not a merge;
whether that is what the player wants is theirs to judge, which is why it is
an option and never a recommendation.

**Amendment (2026-10-23, GUI-AUDIT M5b item 33) — ignoring a broken order
rule on a row of the install order.** `decisions.json` gains an optional
top-level `ignored_order`: one entry per row of the wizard's install order,
`{"unit": the planner's node (log|key|part), "after": the row just above it
("" for the first), "rules": the broken rules ignored, as the plan words them,
"why": the player's reason}`.

Context: the order page marks a row red when an order rule the plan could
not keep names it, and the player may know better (a pair tested together, a
rule that is stale). Recording that as an `accept` was the obvious way, and
does not work: a finding is judged on the selection's own order, and a rule
broken only by the order the player set by hand (`install-order.txt`) has no
finding at all - it exists only as the plan's residual violation, which has
no stable id.

Decision: the ignore names the row, its place and the rules, and holds only
while all three still match (`IgnoredOrder.holds`): the row just after the
same row, breaking no rule beyond those ignored, and breaking at least one.
Dragging the row also forgets the ignore at once (the page removes it), so a
row moved and planned back to the same place is shown again too. The wizard
shows an ignored row grey, with the reason, instead of red; "Stop ignoring"
removes the entry. `save_decisions` keeps the entries it is not given, so the
conflicts page, which never shows them, does not drop them.

Consequences: the command line reads and checks `ignored_order` and does
nothing else with it - a run's plan still reports the rule as it is; the
ignore is the wizard's display, not a decision the run applies. A file with
the key is refused by an iemod-fetch older than this change (the reader
refuses unknown keys, as it should); `schema_version` stays 1 because a file
without the key reads as before. The place is "the row just above it": a row
dragged in between, or the row above moved away, shows it again too - on the
side of showing a broken rule rather than hiding one. Nodes carry the part
number of a split mod, so splitting or joining it shows the row again.

---

## ADR-0034 — Engine limits are checked against primary sources, and warned on, never blocked

**Status**: accepted
**Date**: 2026-10-21

### Context

Big EE installs run out of three engine tables: kits, spell states and spell
ids per level. Infinity Mod Forge warns on them with constants (320 kits, 37
taken; 256 spell states, 128 taken; 50 spells per level) and per-component
counts from krion64's records. The owner asked to verify those values in the
original projects and forums, and not to tie anything to one game patch
(players are on 2.6.x and 2.7.x).

What the sources say (checked 2026-10-21):

- **Kits: 256.** WeiDU's ADD_KIT fails above kit number 256 on every EE game
  ("The game requires ToBEx or GemRB to support more than 256 kits",
  `src/tpaction.ml`; `check_enhanced_engine ... allow_bgee=false`). No source
  for 320 was found. BG2:EE's KITLIST.2DA has 40 kits (IESDP), not 37.
- **Spell states: ids 0-255** without EEex (EEex `EEex_Stats_Patch.lua`);
  about 133 are the game's (IESDP's BG:EE list). The limit is on id values,
  not on a count.
- **Spells: 50 per type and level** is WeiDU ADD_SPELL's allocation
  (`add_spell.tpa`, `tb#max_spell = 50`); 99 for innate and class spells.
- **No source says patch 2.5, 2.6 or 2.7 changed any of them**, and WeiDU
  treats every EE game alike.
- krion64's spell-state counts include ids a mod only reads: EE Fixpack is
  counted 19 and only looks existing states up (`IDS_OF_SYMBOL`). Summed over
  a real 148-mod EET install that plays, they reach 257/256.

Forum statements (a crash past kit row 256, a Beamdog developer on 256
spell states) could only be seen through search summaries here; they are
cited as reported, not verified.

krion64's method, audited before adopting it (its scripts, and its records
against 103 mod repositories):

- **Spells per level** come from `scripts/scan_spell_ids.js`, which reads only
  literal `APPEND spell.ids` lines. ADD_SPELL - WeiDU's own way, which picks
  a free slot - is not seen: NWNForBG adds 6 wizard spells with it and
  Region of Terror 4; krion64 records 0 for both. Entries with variables are
  left for "manual review", and the scan is per mod folder.
- **Spell states** (`ss`) count references, as above.
- **Kits** (`k`) are "the number of ADD_KIT calls", entered by hand; most
  mods add kits through function libraries (fl#add_kit_ee, Argent77's
  ADD_KIT_EX), which no scanner of theirs follows. Argent77's library has the
  same 256 limit, and exempts multiclass kits on EE 2.0+.
- Its records also join a mod folder's tp2s: EET and EET_end share `eet/`
  and component #0.

None of the three is exact, and a static scan of our own would not be either:
ADD_SPELL reuses an identifier SPELL.IDS already has, and conditions decide
which calls run. What is exact is the game folder itself.

### Decision

- `limits.py` counts, per install: kits against 256 with the game's 40;
  spell states against 256 with the game's 133; spells per type and level
  against 50 with the game's own count. Each table names its source, and
  where Infinity Mod Forge uses another number, that number too.
- Warnings only, never a refusal: a warning at 90% of a table, an error past
  its end. Nothing depends on the game's patch version.
- The spell-state table is shown and never warned on: its counts are an
  upper bound. With EEex installed its range is lifted.
- A mod krion64 has no counts for is named, and the totals read "at least".
- **Measured, not estimated, wherever the game folder is known**: a WeiDU.log
  beside a chitin.key is a game. Its tables are read by WeiDU's own rules,
  from override/ first, then from the BIFF chitin.key names: the last kit
  number in KITLIST.2DA (`get_next_kit_number`); a spell slot as taken when
  ADD_SPELL would skip it - an id in SPELL.IDS or ADD_SPELL.IDS, or an
  SPWI/SPPR file already there (`TB#ADD_SPELL_FIND_SLOT`); the ids 0-255 in
  SPLSTATE.IDS. krion64's counts then only add the chosen components the
  game's WeiDU.log does not list. A measured spell-state table is warned on.
- The measurement is tested against the real WeiDU (CI,
  `tests/test_real_weidu_limits.py`): on a synthetic BG2:EE with a real KEY
  and BIFF, ADD_KIT gives kit N+1 after N measured and refuses past 256, and
  ADD_SPELL takes exactly the slots measured as free.

### Consequences

- The conflict report (text and JSON, `engine_limits`) shows the three tables
  with who fills them, for the GUI's selection screen.
- A player told "kits 231/256" by this tool may see a different number in
  Infinity Mod Forge; the report says why.
- For an installed game the tables are exact; for a selection not installed
  yet they are krion64's estimates, labelled so: spell levels can be fuller
  than shown (ADD_SPELL is missed), spell states are an upper bound.
- A game whose BIFFs are compressed (BIFC, classic games), whose tables are
  XOR-encrypted (classic games) or damaged, falls back to the estimate, and says so by not being
  marked measured. Reading the game is read-only, size-capped, and a BIFF
  path from chitin.key that would leave the game folder is not followed.

---

## ADR-0035 — Components are chosen from the mod's own tp2, else from krion64's records

**Status**: accepted
**Date**: 2026-10-21

### Context

The wizard's mod selection (GUI-AUDIT item 16) offers components before
anything is downloaded, as BWS-NG does. The only exact list of a mod's
components is its tp2, read the way WeiDU reads it (`tra.describe`: 9,889 of
9,889 names identical to WeiDU's). A mod not yet downloaded has no tp2 here.
The catalogues the tool already reads differ: lcc-docs lists mods, not
components; krion64's per-mod records list components with WeiDU numbers
(`wc`), SUBCOMPONENT groups (`g`, named by `scn`), same-mod requirements
(`rd`) and removed components (`gone`).

Measured against WeiDU 251's own `--list-components` on 105 real mods
(`tools/krion_components_benchmark.py`): of 1,529 components WeiDU lists,
krion64 has 1,471 under the same number; 58 are missing from it (7 of them it
marks as removed though the tp2 still offers them), 13 it lists are not in the
tp2, and 85 mods are identical. 14 of the mods have no krion64 record.

### Decision

- `choices.py` gives each mod's components per tp2 and says where they came
  from: `tp2` - the staged mod's own tp2, which alone decides once the mod is
  staged - else `krion64`. A component removed (`gone`) or hidden
  (DEPRECATED) is not offered.
- `api.mod_choices(game, ...)` is list_mods' entry plus `tp2s`, filtered to
  the game (a mod whose games are unknown is kept), from the same community
  data cache a run uses.
- A mod with no known components cannot be chosen yet: a selection names
  components, and they are not guessed. Its row says so.
- The choice is `selection.json` (ADR-0030), written by `api.save_selection`
  through selection.json's own checks; the CLI reads it with `--selection`.

### Consequences

- About 4% of components are not offered before download, and a few offered
  ones no longer exist. A choice made from krion64's records is checked again
  against the tp2 once the mod is staged (the plan's own checks).
- The selection screen works offline from the last good data, and needs no
  download to start.

## ADR-0036 — Each community source is used for what it measures best

**Status**: accepted
**Date**: 2026-10-22

### Context

Three community projects describe the same mods, and the tool already reads
all three (ADR-0032): lcc-docs (the mod list, every known URL, a status and a
rating), krion64 (components, conflicts, install order, a scan of each
repository's latest release) and BigWorldSetup-NG (rules, and per mod an exact
file with size, platform and often a sha256, components, and the answers to
some WeiDU prompts). The question was whether downloads, and the wizard's
choices, should come from more than one of them, and from which for what.

Measured on 2026-10-22 over the mods for BGEE, SoD, BG2EE or EET (hidden and
absorbed ones left out), with `tools/download_sources_benchmark.py --bws ...
--probe` and `tools/krion_components_benchmark.py ORACLE KRION BWS`. Data:
lcc-docs 6d73f777df (last commit 2026-10-17), krion64 a8d17c4d5e
(2026-10-19), BWS-NG f7befca607 (2026-02-24, eight months old).

| | lcc-docs | krion64 | BWS-NG |
|---|---:|---:|---:|
| mods | 1,148 | 813 | 412 |
| with a GitHub repository | 852 | 651 | - |
| an exact file, and its sha256 | 11 direct archives without a repository | - | 409, 335 |

**Repositories** (lcc-docs and krion64, 665 mods both know): 428 name the
same one, 113 differ. Of those, krion64's is gone in 27 and lcc-docs' in
none; 23 are one repository under two names (a rename GitHub redirects); of
the 63 different live ones lcc-docs' has the newer last commit in 51,
krion64's in 11, one ties. The usual pattern is SHS's move from
`SpellholdStudios` to `Spellhold-Studios`. 148 mods only krion64 knows, 95 of
them with a repository. One krion64 record names a repository that cannot exist
(`...Lanthornhttps:`) while its URLs name the live one, so a record's `gh` is
read through the same URL check as any other URL.

**Exact files** (BWS-NG; tools with no tp2, such as WeiDU itself, left out):
279 of the 280 GitHub release tags it pins still exist (one repository is
gone). Against krion64's latest scanned release, the version it pins is the
same for 177 mods, older for 48 and newer for 3; 7 are spelled so they cannot
be compared ("8" against "v8_EE"), 35 are branch archives (always the newest)
and 142 have no scanned release.

**Components**, against WeiDU 251's own `--list-components` (ADR-0035): on
the 67 mods all three know (1,089 components), krion64 has 1,047 and BWS-NG
1,023; their union has 1,057 and brings 8 the tp2 does not have. Over every mod
it has a record for, krion64 has 1,471 of 1,529 (105 mods).

**Prompts**: only BWS-NG describes WeiDU prompts as data (`sub` components with
options and a default), for 4 components across its Enhanced Edition mods
(printed by the download tool).

### Decision

- **Where a mod is found** (repository, landing page): the manifest, then
  lcc-docs, as today. krion64's URLs are not added: on disagreement they are
  dead or older far more often.
- **Which file, and its checksum**: BWS-NG's exact file and sha256 verify the
  version they pin (as today). In the wizard's download phase BWS-NG's file
  becomes a candidate only when its version is the newest known; otherwise
  the repository's newest release wins and the BWS-NG checksum does not apply.
- **Components before download**: krion64, as ADR-0035. BWS-NG is not merged
  in: the union would add 10 of 1,089 components (0.9%) and 8 the mod does not
  offer.
- **Prompts**: BWS-NG is the only structured source, and covers 4 components.
  Drop-downs for prompts are built with M4, where recorded answers are used
  to install; a selection does not carry answers yet.
- **Rules and order**: BWS-NG's rules, krion64's records and order, as today.
- The 148 mods only krion64 knows are the case for using its repository as a
  third download candidate later, checked as any other (the archive must
  contain the right tp2).

### Consequences

- No behaviour change now. The measurements are reproducible with the two
  tools and go stale with the data; they are re-run before the download phase
  relies on them.
- 27 mods would resolve to a dead repository if krion64's URL were preferred,
  and 48 of the 228 comparable BWS-NG pins (one in five) would install an
  older release than the newest; both are avoided.
- BWS-NG's age (eight months at the time of writing) is reported by the data
  cache like any source's; it is a reason to prefer it for checksums of what it
  pins, not for what is newest.

---

## ADR-0037 — The authors' own install order is read before download

**Status**: accepted
**Date**: 2026-10-22

### Context

Project Infinity (PI, github.com/ALIENQuake/ProjectInfinity, 0.10.7; its wiki
pages "Adding metadata for mod", "Sorting Order feature", "Install Order
Groups") brings three ideas to install order:

1. A **metadata ini** beside the tp2 (`<tp2 name>.ini`, `[Metadata]`): identity
   and links, `LabelType`, and the author's own `Before`/`After` - other mods'
   tp2 names. It has no field for component conflicts.
2. A **Sorting Order** file the player writes: `Ascension *`, `Ascension 101
   102` - it sorts only what is chosen, and a component named on its own line
   leaves its mod's `*` line.
3. **Install Order Groups** the player arranges by hand: krion64's categories
   already play that part.

The tool read the metadata ini only from a staged mod (modmeta.py, ADR-0016).
But the order is planned, and the wizard judges conflicts, before anything is
downloaded; then only the community rule sets speak. LABELs are already read
(pi.py), so `LabelType` adds nothing.

Measured with `tools/pi_metadata_benchmark.py` on the 103 mods of the real
install (krion64 a8d17c4, BWS-NG f7befca): 85 ship a metadata ini; they state
314 order pairs. krion64's order agrees with 239; a rule (BWS-NG or krion64)
already covers 34 of the others; 22 span the two EET game phases; **19 are
known only to the author**: 7 contradict krion64's order (Region of Terror
after IWD1_EET and IWD2_EET; Kivan before Adrian; Deities of Faerun before
Tome and Blood; Homeward Bound before Crossmod BG2; JA#BGT AdvPack and
Transitions before Baldur's Seatower) and 12 name mods krion64 does not place.
Two of those name a mod by its display name ("Coran in BG2") and order nothing.

### Decision

- `premeta.py` fetches a planned mod's metadata ini before download: from the
  repository lcc-docs names (ADR-0036), else krion64's, at its default
  branch: beside the tp2, named after it with or without `setup-`, ignoring
  case. PI runs where case does not matter and GitHub does not: Region of
  Terror ships `RoT/rot.ini` beside `setup-RoT.tp2`, Deities of Faerun
  `Deitiesoffaerun.ini` beside `DeitiesOffaerun.tp2`, and a WeiDU log may spell
  `ASCENSION/ASCENSION.TP2`. The likely spellings are tried on
  raw.githubusercontent.com (no API quota); on a miss the folder is listed
  once (GitHub's contents API) and matched ignoring case, and only a listing
  records "no ini". At most 1 MiB, read as text with the same parser as a
  staged ini, never executed. Found and not-found are cached in the data
  cache, by mod and repository, for a week; an ini cached from another
  repository than the catalogue names today is not used.
- A network error is the network's, not the file's: nothing more is asked in
  that run, every mod still to ask backs off for an hour, and what was found
  before is kept. Requests are tried once with a short timeout, so the
  wizard's check, which asks after every change, costs seconds offline.
- `--fetch-metadata` asks for it in a run; the wizard's conflicts check asks
  for what is chosen. A fetched ini is used by every run once cached - its
  `Before`/`After` become order rules keyed by the tp2 name, with the
  author's file named as their origin - for the mods not staged; a staged
  mod's own ini wins. With `--no-default-data` the cache is used only when
  the run asked for it.
- `--sorting-order FILE` reads a PI Sorting Order file as order rules between
  consecutive lines of what is chosen; what is not chosen is skipped, nothing
  is added, and a component already placed by an earlier line stays there.
  It is the player's own: a staged mod's ini replaces the community's order
  rules about that mod, never these. A contradiction with another rule is
  reported as any order conflict is, not silently won.
- Install Order Groups and `LabelType` add nothing here and are not adopted.

### Consequences

- 19 order pairs per 314 (6%) reach the plan and the conflicts check before
  download; the 7 that contradict krion64 move mods where their authors put
  them.
- Per planned tp2, once a week: up to 8 small requests to
  raw.githubusercontent.com (the likely spellings; usually the first hits),
  and when none hits - an ini spelled otherwise, or no ini at all, the common
  case - a listing on GitHub's API of the root and of each level of the tp2's
  folder (two or three for the usual paths). That
  API allows 60 requests an hour without a credential (the tool's GitHub
  credential is used when it has one), so a large selection without one fills
  in over several hours: the quota is treated as the network being down, and
  what is left backs off for an hour. Offline, the cache is used; without it,
  the plan is what it was.
- One folder can hold several tp2s (EET's holds EET.tp2 and
  EET_end/EET_end.tp2); each has its own ini, wanted, cached and keyed by its
  own tp2 name. An error of one repository (a 451, a file over the cap) backs
  that tp2 off for an hour and keeps what it found before; it never stops the
  others. A 401 (a credential GitHub refuses) and a 403 or 429 (GitHub's
  quotas, the secondary one included) stop the run like a network failure.
  *Amendment (2026-10-23, GUI-AUDIT item 45):* a secondary limit is first
  waited out in `net.py`, as GitHub's docs prescribe (Retry-After, else one
  minute and then longer, over the run's retries - three by default); only
  one that outlasts them reaches here and stops the run. A Retry-After over
  five minutes is not waited out but stops at once (retrying sooner than
  GitHub asks prolongs the limit), and every wait ends when the run is
  cancelled.
- An author's ini can be wrong or old, like any rule source; its order rules
  carry the file as their origin, so a finding says whose claim it is.
- Component conflicts get nothing from PI: its format has no such field.
- *Amendment (2026-10-22).* The case-insensitive listing is checked against
  the real GitHub by `mod-metadata.yml` (`tools/premeta_live_check.py`), on
  pull requests that touch the fetch and weekly; until then it had been tested
  only with fake clients.

---

## ADR-0038 — The wizard's install order is the run's plan, and the player's order is a Sorting Order file

**Status**: accepted
**Date**: 2026-10-22

### Context

Phase 3 of the wizard (GUI-AUDIT item 17) shows the install order and lets
the player change it. Two things had to hold: what the page shows is what the
run will install, and a change the player makes reaches the command line too.

An EET build is two installs: mods for BG1 go on BG:EE before the conversion,
the rest on the EET game. The wizard saved one EET install, so the plan could
only report the BG1 mods as "in the wrong log", and splitting them later
would have renamed every finding's install - and with it every id a
decisions.json holds (ADR-0033).

### Decision

- **The selection is split where it is made.** For EET, `save_selection`,
  the conflicts check and the plan all build two installs - BGEE with the
  components krion64 files under a pre-EET category (per component where it
  places one apart), EET with the rest. Without krion64's data, one install,
  as before. The same selection is judged the same way everywhere.
- **The page is the plan.** `api.selection_plan` runs the planner a run with
  `--selection --plan-order` runs, on the same data, and returns each
  install's units in order: rule-placed ones marked (`constrained`), those an
  order rule still objects to marked (`flagged`), cycles and violations as
  text. A cycle names every unit left when it was broken, so it is reported,
  not marked.
- **The player's order is a Sorting Order file.** Dragging writes the whole
  order shown as `install-order.txt` in Project Infinity's format (ADR-0037)
  - `tp2 *`, or `tp2 N N` for a mod split across the order - and names it in
  the project's ini as `sorting_order` (read relative to the ini), so a run
  with that ini, `--selection selection.json` and `--plan-order` plans the
  same order. A test checks the page's order against the run's written logs.
  The ini is written first, so a project whose ini cannot be written keeps
  no order the command line would not see. The conflicts check of phase 2
  judges the same order. A rule-placed unit is one an order rule other than
  the player's own places: the hand order ties every unit to the next. It goes on top of the rules; a contradiction is shown as a
  violation or a cycle. "Use the computed order" deletes the file and the
  ini entry.
- Moving a mod between installs is not offered: which game it goes on is
  krion64's category, not a preference.

### Consequences

- The order the player sees, the order the CLI writes and the order PI would
  apply from the same file are one order.
- A hand order fixes every unit's place relative to its neighbours, so later
  rule changes show up as contradictions rather than silent moves; using the
  computed order again is one click.
- An EET selection.json now holds two installs; the selection page reads both
  back (a BGEE install alone is a BG:EE build, not EET's first phase).
- A finding's id names its install, so decisions saved by the unreleased
  phase-2 panel for mods of the BG:EE phase are reported stale once and must
  be made again. The panel offers to forget stale decisions (asked first;
  amendment, 2026-10-22), so they do not stay in the file for ever - only
  those the current, finished check calls stale, and none when no rule was
  checked (with no community data every decision would look stale).

---

## ADR-0039 — The wizard downloads through the command line's run, and with no manifest the community catalogue is the source

**Status**: accepted
**Date**: 2026-10-22

### Context

Phases 4 and 5 of the wizard (GUI-AUDIT item 18) are BWS-NG's Download and
Extraction. Two facts shaped them.

1. In the engine they are **one step per mod**. `Runner._attempt` downloads
   one archive, checks its sha256, unpacks it to a staging folder, checks it
   holds the tp2 it must, and only then moves it into the target. Extraction
   cannot start before its download ends and is not done for a mod apart from
   its download.
2. **A run needed a manifest** (`mod_downloads.json`). A wizard user has none:
   they chose mods from the catalogue, not from a file. Every mod the manifest
   lacks went to `unresolved`. With a catalogue the runner did try those mods
   through it (ADR-0009), but the run still refused to start without a
   manifest file.

A measurement found a third fact. lcc-docs records a mod that ships several
tp2s in one field, `EET;EET_end;EET_gui`, and the catalogue reader took that
as one name. **EET itself was never found in the catalogue**, by the
command line either.

### Decision

- **One page, "Download and extraction".** Each mod's row says which step it
  is at: downloading (bytes of total), extracting, done, already there,
  failed, no download found, cancelled. Splitting it into two pages would
  show a sequence the engine does not have. The phase list becomes Game and
  folders, Mod selection, Install order, Download and extraction,
  Installation (M4).
- **A new progress event**, `mod_extracting`, is emitted when a download is
  complete and verified and its archive is being unpacked. It is additive to
  events schema v1: a consumer that ignores unknown events is unaffected.
- **`api.download_selection(folder, on_event, cancel, only)`** is the run
  `iemod-fetch --config FOLDER/iemod-fetch.ini --selection
  FOLDER/selection.json` makes in FOLDER. `api.project_settings(folder)`
  builds those settings. The project ini's values go over the defaults, and
  its paths (target, manifest, catalogue, rules, ...) are read relative to the
  project. The selection is what is wanted: a WeiDU log or a list named in
  the ini is ignored. It is always a real download, never `check_only` or
  `dry_run`.
- **With no manifest, the community catalogue is the download source.**
  `Settings.manifest = None` (a project ini without `manifest`) gives an
  empty manifest, and every mod is found through lcc-docs from the data
  cache, then trusted-owner discovery. A candidate must still contain the
  right tp2. With neither a manifest nor a catalogue, the run stops with
  "no download source". The command line's default `mod_downloads.json`
  becomes optional in the same way: when that file is absent and a
  catalogue is present, the catalogue is the source, so the wizard and the
  command line agree in the same project. A manifest named on purpose
  (`-m FILE`) must exist; a typo is an error, never a silent switch. (Typing
  `-m mod_downloads.json` is the default itself, and is read the same way.)
- **What only a plan uses** (`language_preference`, `bgee_dir`,
  `bg2ee_dir`, `decisions`, ...) is refused without `--plan-order` only when
  given on the command line with a value the config file does not hold. An
  EET plan given one game folder warns that the folders were not checked.
  The wizard's project ini holds the game folders
  and languages for every run in the project, and a BG:EE or BG2:EE project
  names one folder. Before this, every command-line run in a wizard project,
  and the wizard's own download, stopped on them. The download clears them,
  and the ini's `all_manifest_entries` and `only`: the selection is what is
  fetched.
- **A multi-tp2 catalogue record is found by each of its tp2s.** When several
  records share a tp2, the one whose repository is named after the mod wins
  (EET over EET_Android).
- **Nothing starts until the player clicks Download**, because it uses the
  network and the disk.
  - **Cancel** stops the downloads at their next chunk; what finished stays.
  - **Running again resumes**: a mod already there and verified is skipped.
  - **"Retry the failed"** runs `only` those mods.
  - **Next** is enabled once every mod is done or already there.
  - **Back** is locked while a download runs.
  - A **new selection** starts the phase again; a mod added since was never
    downloaded.
- **The run's events** come from its worker threads. They reach the page
  through a queued Qt signal, and each mod's byte count at most ten times a
  second, so a fast network cannot flood the window. Quitting cancels a
  running download before the application waits for its threads.

### Consequences

- The wizard and the command line fetch the same mods from the same sources
  into the same folder. Stopping in one and carrying on in the other works,
  because the state is the target folder.
- Measured on the supplied 145-mod EET WeiDU.log against lcc-docs alone
  (2026-10-22):
  - 138 mods have a candidate: 114 a GitHub repository, 1 a direct archive
    link, 23 only a landing page.
  - 7 have none. Their WeiDU folder is named otherwise in lcc-docs
    (`questpack` / `d0questpack`, `Reflections` / `Reflections_of_Destiny`,
    a typo `Brislelick`), or their record carries no URL.
  - Before the multi-tp2 fix, EET was among the misses.
  - The supplied manifest covers 135.
  - How many candidates hold the right mod can only be measured by
    downloading them. That needs the GitHub API and the mod sites, which a
    session sandbox cannot reach: its proxy refuses every repository the
    session was not given, and the forum hosts. `download-sources.yml` makes
    the measurement on GitHub's runners. Its first run (2026-10-22):
    - **catalogue only**: 135 of 145 mods resolved to a candidate (86 a
      release asset, 28 a branch snapshot, 20 a landing-page link, 1 a
      direct archive); 10 not: 5 that lcc-docs names otherwise, 2 records
      with no URL, 3 landing pages that answer 403 to a script
      (gibberlings3.net, shsforums.net, nexusmods.com);
    - **with the manifest**: 139 of 145;
    - **20 real downloads** of the catalogue's candidates: 14 installed, each
      archive holding the tp2 it must; 4 were over the run's 300 MB cap
      (BGGO, Autumn's Twilight, Classic Movies, Aura: big, not wrong); 2
      failed because downloads.weaselmods.net answered its download link with
      an HTML page, not the archive. About 20 of the log's mods are
      WeaselMods'; that is the next defect to fix, with the manifest too.
  - *Amendment (2026-10-23).* `tools/landing_probe.py`, run by the workflow
    on the real pages, showed why: WeaselMods runs WordPress Download
    Manager, which draws the button by script, and the page's own link to
    itself was taken for the file. `?wpdmdl=<post id>` on the package page
    answers the zip (Alabaster Sands: `AlabasterSands-v2.0.zip`, 16 MB); the
    resolver now gives that, and never a link to the page itself. Measured
    after the fix: 135 of 145 resolve through lcc-docs alone, the 20
    landing-page candidates now WeaselMods' real files; of 20 real downloads
    16 installed - Alabaster Sands and The Bloodied Stings of Barovia among
    them, each holding its tp2 - and 4 were over the run's size cap.
  - Measuring in the sandbox anyway found three defects, fixed here: a mod
    the catalogue could not resolve said only "entry has no url and no
    github repository"; a link typed with accents crashed the mod; a bare
    403 was called a rate limit.
  - *Amendment (2026-10-23, the owner's decision) - a forum's file comes
    last.* Real downloads of all 145 mods, with 7-Zip and unar installed,
    with GitHub out of reach, found the Beamdog threads lcc-docs lists to be
    the weakest source of all: the files scraped from them were not the mod
    for 8 mods (a save game, `.debug` logs, a sound file, a patch, another
    mod), and the two that were came years behind their authors - Ascension v1.5 BETA for 2.1.0, Finch v4.0
    for v6.0 - with nothing to say so; the tp2 check cannot tell an old
    copy from a new one. A forum thread or a file attached to one
    (`urls.is_forum_post`: a `forums.` host, a `topic`, `discussion` or
    `threads` path segment, `viewtopic.php`, XenForo's `index.php?threads/`)
    is now tried after the entry's own direct links, its
    repository and its other pages, and a mod installed from one carries an
    advisory naming the post and the version the mod declares. It is not
    refused: for some mods a forum post is the only copy left, and the same
    tp2 check still gates it. When a downloaded archive is not the mod, each
    of the entry's other sources gets its turn (GUI-AUDIT M7 items 54, 58).
    And a copy from anywhere but GitHub is compared with the latest release
    krion64's daily scan names for the repository called like the mod (a
    repository named otherwise is never offered); when that release is plainly
    newer by `versions.newer_release` - never on versions it cannot rank, a
    release candidate over a release, or a date over a version - the
    record carries it as `newer` and the run tells the player to re-run
    with `--take-newer FOLDER` (or `all`). Offered, not taken: the player
    decides, as ADR-0005 wants, and a front end can make it a button. Taken,
    it is that release or nothing: the catalogue's other sources would only
    bring back the copy being replaced (item 59).
- Landing pages are the weakest source: a scrape can find no archive. Those
  mods come back as "No download found", which the player can retry or fix
  with a manifest entry.
- `--list-mods` now lists EET, EET_end and EET_gui separately. Before, they
  appeared as one key that no tp2 had.

## ADR-0040 — The wizard ships as a PyInstaller folder per OS, zipped, attested, with Qt's LGPL notice

**Status**: accepted
**Date**: 2026-10-23

### Context

GUI-AUDIT item 20: a player should run the wizard without installing Python
or PySide6. Three constraints shaped it.

1. **Qt and PySide6 are LGPL-3.0-only.** Distributing them is allowed when
   they stay dynamically linked, the user can replace them with their own
   build (LGPL-3.0 section 4), the licence text travels with them, and their
   source is offered.
2. **The command line stays standard-library only** (ADR-0001, the `.pyz`).
   The wizard bundle must not change what the `.pyz` holds or needs.
3. **Runners.** GitHub's macOS runners started no job from 2026-10-21 to
   2026-10-23; the owner made macOS informational in CI. A release must not
   wait on them.

### Decision

- `packaging/gui_bundle.py` builds with PyInstaller **one folder**
  (`--onedir --windowed`), never one file: Qt's libraries stay separate files
  under `_internal/PySide6`, which a user can replace. A one-file build
  unpacks to a temporary folder on every start, which makes replacing them
  impractical.
- The folder carries `LICENSE` (MIT), `licenses/LGPL-3.0-only.txt` and
  `licenses/GPL-3.0-only.txt` (the SPDX texts), and `NOTICE-Qt.txt`, written
  at build time with the Qt, PySide6, PyInstaller and Python versions really
  bundled and where their source is.
- The zip is unpacked again, as a player would, and the program in it is
  started once with `--check`, offscreen: it opens the main window, quits
  through the normal shutdown path and prints `ok`. A build or a zip that
  cannot start fails the release, not a player's machine.
- The zip, `iemod-fetch-gui-<os>-<arch>.zip`, is deterministic (sorted
  entries, fixed timestamps): the same folder gives the same bytes. Symbolic
  links stay links (a `.app`'s frameworks, Linux's names for Qt's libraries):
  as copies they made the Linux zip 89 MB instead of 60 MB and left two files
  to replace for one library. `unzip` and desktop archive tools restore them;
  Python's `zipfile.extractall` does not, and the program then fails to load
  Qt. Windows builds hold no links.
- The release workflow builds it, PyInstaller pinned, in a `gui` job on
  **ubuntu-latest and windows-latest**. **macOS is a workflow of its own**,
  `release-macos.yml`: a runner that never starts leaves a job queued, not
  failed, and a queued job in `release.yml` kept its run - and with it the
  `release` concurrency group, so the next release too - waiting;
  `continue-on-error` does not help. Every six hours it looks at the latest
  release and, when that has no macOS bundle and its tag has the packaging
  script, builds it from the tag, attests it and attaches it with its own
  `.sha256`; `workflow_dispatch` does it for a named release. A schedule, not
  `workflow_run`: nothing from another run is trusted. The zips are attested with the other
  assets (build provenance), listed in `SHA256SUMS` and attached to the
  GitHub release. They are not uploaded to PyPI.
- On macOS the build is a `.app`; its Qt frameworks hold symbolic links
  (`Versions/Current`), which the zip keeps as links, not copies. The licence
  files go into `Contents/Resources` after PyInstaller signed the app, so it
  is signed again, ad hoc, and the signature verified. The M3
  criterion "the PyInstaller build starts on all three OSes" is met where
  the runners run; a release with no macOS bundle says so by its absence,
  and macOS players can always `pip install "iemod-fetch[gui]"`.

### Consequences

- The Linux zip measured 60 MB locally and 83 MB in the 3.0.0 release (the
  runner's PySide6 wheel is bigger); the Windows one 48 MB. Qt modules the
  wizard does not use are excluded to keep them there.
- A macOS bundle reaches a release up to six hours after it, or never while
  the runners do not start; the release says so in its notes.
  - *Amendment (2026-10-23).* `release.yml` now starts `release-macos.yml`
    for the new tag (`macos-bundle`, `workflow_dispatch` with the run's own
    token, `actions: write` on that job only), so the bundle normally arrives
    minutes after the release. The dispatch only queues the run - nothing
    waits for a macOS runner - and the six-hourly check remains for a run
    that fails or never starts. A dispatch from this session's GitHub
    integration was refused (403), which is why the release does it itself.
    The dispatched, scheduled and hand-started runs share one concurrency
    group and never run at once, and the upload asks again for a macOS
    bundle first: a published one is never replaced (review of #46: two
    runs could each build and upload, leaving a zip and a `.sha256` from
    different builds). Only a zip counts as attached, and it is uploaded
    before its `.sha256`; a zip whose `.sha256` failed to upload gets it back
    at the next check from the digest GitHub records for the asset, without
    a rebuild or a download.
- The bundles carry no publisher signature and the macOS app is not
  notarized: Windows SmartScreen warns, and macOS refuses the downloaded app
  until the player allows it (System Settings, Privacy & Security, Open
  Anyway). Signing needs certificates the project does not have.
- The Linux bundle needs the system's X11/Wayland and font libraries that
  any desktop has; it is built on the runner's Ubuntu, so a much older
  distribution may lack a newer glibc.
- `--check` is a supported flag of `iemod-fetch-gui`, tested in CI
  (`tests/gui/test_check.py`); the bundle helpers are tested without
  PyInstaller (`tests/test_gui_bundle.py`).

## ADR-0041 — A mod's install place by its kind: measured, and only where the sources agree

**Status**: accepted
**Date**: 2026-10-23

### Context

GUI-AUDIT M5 asks for the kind of a mod (interface, graphics, quests, NPCs,
kits, AI, portraits, after EET_end...) in the selection and in the order.
`tools/order_sources_benchmark.py` measured every source on its real files
on 2026-10-23 (krion64 at its HEAD, BWS-NG at its HEAD, lcc-docs' db):

- **krion64 is the Infinity Mod Forge** (its README), so the Forge and
  Infinity Mod Runner add no source. Its 813 mod records (846 tp2 names) sit
  in 26 install categories, in install order, with a position inside each; 240 components
  are filed in a category of their own (`cat`, already used to split a mod).
  Its free tags (npc 250, story 217, tweak 124, ...) are descriptive only.
- **BWS-NG** classifies 426 mods (430 files; WeiDU and three helpers have
  no tp2) in 15 categories (quest, gameplay, kit, npc, npcx, smith, spell,
  portrait, ui, ...) - lcc-docs' taxonomy - and, more useful, keeps a
  **complete install sequence per component** for EET's BG2 phase: 3,232
  components of 364 mods. iemod-fetch has used only its 34-entry BG1 (SoD)
  phase, for what goes before the EET core (M2).
- **lcc-docs** classifies 1,290 mods for the EE games in 16 categories; 546 of
  them krion64 does not place. **Project Infinity**'s metadata ini carries a
  `Type`, which lcc-docs reads into its categories; PI adds nothing of its own.
- Overlap by tp2: krion64 and BWS-NG 381 mods, krion64 and lcc-docs 744.
  BWS-NG's sequence places only **26** mods krion64 does not (its files name
  45, 19 of them outside the sequence); 7 of the 26 are portrait packs.
- **The two orders disagree on 21% of pairs**: of the 3,082 components both
  BWS-NG's sequence and krion64 place, 992,309 of 4,747,821 pairs go the other
  way round - 21.5% leaving out the 129,148 pairs krion64 ties (it gives every
  component of a mod one place, so order within a mod is not compared). Two
  curated orders, both installed by many players.
- **The supplied log (146 mods, 780 components) is the Forge's own output** (its header: "Infinity
  Mod Forge v4.1.0"): krion64 disagrees with it on 47 of 298,378 pairs
  (0.02%), BWS-NG on 7.6%. It is not an independent player's order, and M5's
  criterion "inversions against the player's order" measured nothing.
- How decisively a category maps onto krion64's install categories, over the
  mods both classify (lcc-docs / BWS-NG):

  | Kind | Share to the top krion64 category |
  |---|---|
  | interface / ui | 92% / 100% INTERFACE |
  | cosmetic | 90% / 92% GRAPHICS |
  | kit | 87% / 87% KIT & CLASS MODS |
  | recruitable NPC, one-day NPC | 85-97% NEW NPC MODS |
  | smith and merchant | 85% / 89% ITEM ADDITION MODS |
  | quest | 56% / 59% QUEST MODS BG2 (the rest BG1, ToB) |
  | portrait and sound | 58% / 64% PORTRAITS (the rest MUSIC & AUDIO) |
  | spells and items | 52% / 48% ITEM ADDITION (the rest SPELL MODS) |
  | NPC (other), NPC expansion | 66% / 55% NPC EXPANSIONS |
  | gameplay | 34% / 30% POST-TACTICAL TWEAKS (24 / 11 PRE-TACTICAL) |
  | conversion | 50% / 50% POST-TACTICAL QUESTS |
  | tactics, patch, utility | under 50% |

### Decision

1. **Precedence unchanged**: the player's Sorting Order, then the authors'
   inis, then BWS-NG's rules, then krion64's place. Nothing below overrides
   them.
2. **A mod krion64 does not place** takes, in this order:
   - its place in **BWS-NG's sequence**, carried onto krion64's order: right
     after the nearest component before it that krion64 also places
     (26 mods today);
   - else its **kind**, only where the mapping is decisive - interface,
     cosmetic, kit, recruitable and one-day NPCs, smith - and quests split by
     the games the source lists (a BG1-only quest to QUEST MODS BG1); the
     share of the measured mapping is shown with it;
   - else no place: it stays where the selection has it, and is marked "no
     place: its kind does not decide one" (gameplay, tactics, patches,
     utilities, conversions, mixed spell-and-item mods). Never a guess.
   Each placed mod names its source in the order page, the plan summary and
   the JSON plan.
   *Done for the kind (GUI-AUDIT item 27):* `kinds.PLACES`, the table
   above re-measured on the 2026-10-23 data; a quest split by its games is
   right for 97 of 132 (73%). Of 1,071 classified mods krion64 does not
   place, 445 are placed and 626 are not; on the 397 krion64 places, the
   kind names krion64's own category for 351 (88%). *BWS-NG's sequence,
   first, done too:* krion64 places a whole mod, not its components, so
   "the nearest component before it" is read as the nearest one in its
   mod's first run of the sequence, and the one after is asked too - where
   the two are in different categories, or there is none after, the
   sequence decides nothing. Of the 26 mods after the EET core krion64
   does not place (30 in the bg2ee sequence, 4 before the core), 16 are
   placed by the sequence, 3 by kind, 7 say why not; where a kind would
   also place one of the 16 (9), the two agree on 8. Measured on BWS-NG's
   ids, not on logs.
3. **The 21% disagreement is shown, not settled**: where the plan orders two
   chosen components the other way round from BWS-NG's sequence, and no rule
   decides, the order page marks the pair "BWS-NG installs these the other
   way round" - information for the player, no reorder.
4. **The selection** gets a kind filter: lcc-docs' and BWS-NG's categories,
   with krion64's install category and tags beside them; a disagreement
   between sources is shown.
   *Done (GUI-AUDIT item 26):* `iemod_fetch/kinds.py` maps both spellings
   onto one vocabulary (all 15 BWS-NG codes on 430 records, lcc-docs' 17
   labels - the 16 above for the EE games, and GemRB), looked up ignoring
   case and Unicode composition; a label it does not know is shown as it
   is and makes no disagreement. On the 2026-10-23 data, 1,843 mods have a
   kind and one disagrees (turnabout: lcc-docs quest, BWS-NG gameplay).
5. **M5's validation** is restated: the plan's places are compared with
   BWS-NG's sequence (independent of krion64), not with a Forge-written log;
   and a plan placed by kind installs with the real WeiDU in the mock EET job.
   *Done (GUI-AUDIT item 29):* `tools/places_check.py`, nightly in the
   community-data workflow, fails on a category the tables do not map or a
   sequence that lost its shape, and measures the 146-mod log against
   BWS-NG's sequence (9,380 of 123,753 pairs the other way round, 7.6%, with
   and without the places - the log is the Forge's own); the mock EET job
   installs a plan reordered by kind with the real WeiDU.

### Consequences

- Measuring found a bug: a tp2 name with dots of its own
  (`www.urstuff2athkatla.tp2`) was keyed `www`, because the catalogue stripped
  an extension from a name that had none left, so such a mod was never
  placed. Names without `.tp2` (catalogue titles, folders, Sorting Order
  lines) now go through `ordering.name_key`.
- The mapping table is data in the repository (`iemod_fetch/kinds.py`,
  item 26). It is checked every night against the live sources
  (`tools/places_check.py` in the community-data workflow, item 29): an
  unmapped category, a krion64 category a kind places into gone, a
  `games/eet.json` without its bg2ee sequence, or a count under its floor
  fails that workflow, not a run. In a run a new label shows as it is and
  makes no disagreement.
- BWS-NG's data is GPL-3.0 and is read at run time from the user's data cache,
  as the rest of it already is (ADR-0036); nothing of it is bundled, and test
  fixtures are written by hand to its schema.
- Measured figures go stale; the workflow's summary keeps them current, and
  this ADR records the day they were taken.

## ADR-0042 — A game folder's backup before installing, and a restore that deletes nothing

**Status**: accepted
**Date**: 2026-10-23

### Context

GUI-AUDIT M4 item 21: before mods are installed, the game folder is backed up,
and the backup can be restored. Until now the tool never wrote into a game
folder: it plans, fetches into `Mods/` and writes installer scripts for
mod_installer (ADR-0006, ADR-0022). A restore is the first operation that
changes a game folder, so it is held to ADR-0007's rule: nothing is deleted.

Infinity Mod Runner (MIT, a shipped Tauri installer) was read first. Its
selective backup copies `override/`, the root's `.ids`/`.bcs` and `chitin.key`
and the WeiDU logs; it records the top-level entries that existed, so a
restore can remove the side folders a mod creates; its restore deletes what
was added; its verification compares the file count and the total size, not
the contents. The EE games' `lang/*/dialog*.tlk`, which WeiDU changes, are
handled apart.

### Decision

- **What is copied** is what WeiDU changes: `override/`, every
  `lang/*/dialog*.tlk`, and every file at the folder's root (`chitin.key`, an
  older game's `dialog.tlk`, `WeiDU.log`, `weidu.conf`, the executable). Each
  copy's size and **sha256** are in the backup's manifest.
- **Everything else is listed** - every file's path and size, every folder
  (empty ones too) and every link - so a restore knows what an install ADDED
  anywhere (a mod folder, a new BIFF in `data/`) and what it CHANGED that was
  not copied.
- **Links are never followed, and nothing leading elsewhere is entered**: a
  symbolic link, a Windows junction or mount (a reparse point), a mount point
  - also a bind mount of the same disk, read from Linux's mount table - or
  another drive. Where a copied file or folder should be (`override/`, `lang/`,
  a root file) one stops the backup: it would be silently incomplete. Others
  are listed, left alone and reported; a restore that would have to move or
  write through one - on, above or below a path to put back - stops before
  changing anything (exit 1, also when only the plan is shown). Files mounted
  over a file count too.
- **Moves never use `shutil.move`**: across drives, or onto a mount, it copies
  a folder and then deletes the source tree - which emptied a mounted folder
  outside the game in the third review. A restore moves only files and links;
  across drives a file is copied, its size checked, and only then removed, and
  a copy whose source cannot be removed, or that fails part-way, is taken
  back. A folder where the backup has a file is emptied by the moves above
  it; its subfolders, empty by then, are moved aside as empty folders, and
  it goes.
- **Reparse points count as "elsewhere" only when they name another place**
  (the name-surrogate tag: junctions, mounts, links); a OneDrive placeholder
  or a deduplicated file holds its own content and is backed up.
- **Folders are compared by identity, not spelling** (device and inode of each
  parent): on macOS `~/games/bg2ee` is `~/Games/BG2EE`, and an alias or a
  mount of the game folder - or of any folder in it - is that folder, so a
  backup cannot be put inside it under another name.
- **A name is what the disk says.** Files found on disk are moved by their own
  path, whatever letters they hold (`\` and `:` are ordinary on Linux and
  macOS: a mod unpacked from a Windows-made zip, a save named "Chapter 2:
  ..."); only the manifest's names are checked, and on Windows those letters
  are refused there. A backup is checked as readable, and as holding one file
  per copy (a case-insensitive backups drive merges `X.ITM` and `x.itm`),
  before it is renamed into place.
- A backup is written as `<name>.partial` and renamed when complete: a backup
  that exists is whole. It may not be inside the game folder.
- **A restore deletes nothing.** It verifies the backup first (every sha256,
  and the manifest's shape and paths: relative, no `..`, no drive, no
  backslash - a damaged backup restores nothing), then MOVES what is in the
  way - files and links added since, and the current version of each file it
  puts back - into a `<backup>/displaced-<time>/` folder that restore made for
  itself (never shared, nothing in it replaced), then copies the backup's
  files back and checks each against its sha256. A folder is removed only
  when the moves - this run's, or those of a run cut short, recorded one path
  per line, before each move, in a journal of its own for each game folder
  (`restore-in-progress-<hash of the folder's path>.jsonl` in the backup: by
  path, since a drive plugged in again may change its device number), and
  counted only if the file is in one of the backup's `displaced-` folders now
  - left it empty and the backup did not have it: an empty folder made since,
  or the target's own, stays.
- **Names match exactly**: on a case-sensitive system a mod's `x.itm` beside a
  backed-up `X.ITM` is moved aside. A listed, uncopied file whose name only
  changed case counts as present, so it is never moved away for want of a copy.
- **It writes only into a game folder** (one with `chitin.key`), and only into
  the one backed up unless the caller names another (`--restore-to`).
- **What cannot be restored is said**: a listed, not copied, file that is
  missing or of another size is named, and the command line exits 1, both when
  it shows the plan and when it restores.
- **A restore cut short is finished by running it again**: the plan is made
  from what is on disk, and the empty folders the cut run left are removed.
- On the command line, `--restore-backup` shows the plan and changes nothing
  without `--apply`. `--backup`, `--verify-backup` and `--restore-backup` run
  one at a time (two together, or `--apply` without `--restore-backup`, is a
  configuration error), before anything else, and never reach the network.
  `--apply`, `--restore-to` or `--backup-to` without their action is a
  configuration error (exit 2) before anything runs. A damaged or unreadable
  backup - found before the plan is even shown - a full disk, a stop or
  Ctrl-C exits 1 with a message.

An independent review of #48 found, before merging, a restore losing a
displaced file (two restores in one second shared a folder), a hand-edited
manifest writing outside the game folder, a restore emptying a folder that was
not a game, a case-only name never moved aside, and empty folders the backup
had being removed. A second review found a restore that could never finish (a
`\` in a mod's file name), a backup written inside its game under another
spelling of the folder, a bind mount entered, empty folders made since being
removed, and exit codes that disagreed with this record. Each has a test in
`tests/test_backup.py`. Not testable here, and left as limits: a backup made
on Linux holding `A.ITM` and `a.itm` restored onto a case-insensitive drive,
and a name stored in one Unicode form returned in another by macOS's HFS+.
A third review found a mount on a path to put back emptied through
`shutil.move`, a backups folder mounted from a game folder, file mounts, a
non-UTF-8 mount table, and a journal trusted too far; each has a test or was
re-run against real bind mounts. Left as a limit, failing loudly: a mount
shadowed by a later mount over its parent can make a real folder look like a
mount, and the backup is then refused. A fourth review found a folder with
subfolders where the backup has a file never restored, a journal of one game
folder used in another, a part copy left behind, and the overlap refused only
by `--apply`; each has a test. Flagged, not testable here: on btrfs
subvolumes mounted with `subvol=` the mount table's device may differ from
`st_dev`, so a same-disk bind mount there may go unseen. A fifth review found
one journal per backup overwritten when two folders were cut, a journal lost
when a drive came back with another device number, and a listed file's case
twin kept inside a folder that had to become a file again; none lost data,
each kept a rerun from finishing, and each has a test. Accepted, and left as a
limit: a journal follows the folder's path, so after a restore is cut and
the game is reinstalled at the same path, the rerun may remove empty folders
the reinstall made under paths the cut run had emptied - only empty folders,
never a file. Journals whose folder moved stay in the backup, small and
unread, for the player to prune with it.

### Consequences

- `displaced-*` folders grow inside the backup folder and are the player's to
  prune, as `Mods/.backup/` is (ADR-0007).
- A backup made after EET's conversion holds its large `override/`; the
  guide recommends backing up the BG2:EE folder before the conversion.
- A changed file outside the copied set (a mod writing into `data/` or
  `movies/`) is detected by its size, not its content: a same-size change is
  not seen. The copied set is where WeiDU writes; widening it is a measured
  change, not a guess.
- The wizard's Backup phase (item 21's page) uses `api.backup_game`,
  `api.plan_restore` and `api.restore_backup`; that page is the next step.

## ADR-0043 — One Python version, chosen like a distribution's kernel, and the libraries that earn their place

**Status**: accepted (the owner's decision, 2026-10-23); carried out in 4.0.0
**Supersedes**: ADR-0001's zero-runtime-dependency constraint (cited
elsewhere as ADR-0002), ADR-0028's Python-version bullet, ADR-0029's "still
standard library only" for the CLI, the M3 validation row's "the `.pyz` stays
standard-library only", and ROADMAP E6
**Date**: 2026-10-23

### Context

3.0.0 supports Python 3.9 to 3.14; the tools run on 3.12, written out in 20
places across all 10 workflows, plus two test matrices and four settings in
`pyproject.toml`. 3.9 has been out of support since October 2025,
3.10 since 2026-10-01 (PEP 619); 3.15.0 shipped on 2026-10-09 (PEP 790).
Two audits of the code against the libraries the community uses (PyPI
metadata, and the candidates run, 2026-10-23) found:

- what kept them out, besides the standard-library-only rule, was mostly
  Python 3.9: the current releases of urllib3,
  filelock, platformdirs, tenacity, rapidfuzz and jsonschema need 3.10 or
  3.11;
- the defects found (M7: the sort's cycle handling, tp2 strings, `.tra`
  code pages, GitHub's limits, the offsite check) are fixed in the standard
  library - except the offsite check, which needs the Public Suffix List;
- one candidate is worse than the code it would replace: charset-normalizer
  reads short Cyrillic `.tra` text as cp1125.

PySide6 6.12 announces "initial support" for 3.15, PyInstaller 6.21 supports
it; a wizard build on 3.15 has not been run.

### Decision

- **One Python version for everything** - development, CI, tools, release
  builds and `requires-python` - chosen as Debian chooses a kernel: the
  newest stable that the whole toolchain already supports, not the newest
  released. **3.14** now; 3.15 when a full build of both bundles and every
  test passes on it.
- **One place names it**: `.python-version`, read by every workflow
  (`python-version-file`). The weekly upstream check (ADR-0028) compares it
  with actions/python-versions' manifest and with every other place that names
  a version, and proposes the move as a reviewed change, like WeiDU's.
  Dependabot does not update `python-version` (verified in dependabot-core);
  no second bot is added.
- **The CLI ships as a bundle too**, beside the wizard, so a player does not
  need that Python; installing with pip needs it. (Done: `packaging/cli_bundle.py`,
  `iemod-fetch-cli-<os>-<arch>.zip`, one PyInstaller folder - not one file,
  which unpacks itself on every start and is what Windows antivirus software
  flags most - run with `--version` and `--help` once unzipped. Its Linux zip
  is built on the oldest supported runner, ubuntu-22.04, because a Python
  built on a newer system needs that system's glibc: the build OS decides
  which systems the bundle reaches, and a check refuses anything above 2.35.)
- **A library is adopted when it fixes a measured defect or a measured cost**:
  a test fails before it, it is pinned by hash, pip-audit scans it, its licence
  is permissive or file-level copyleft kept unmodified. First: filelock (a
  lock on the shared data folder) and publicsuffixlist (MPL-2.0; distinct
  `*.github.io` sites). urllib3 waits for keep-alive to be measured worth it.

### Consequences

- 4.0.0 is breaking: Python 3.14 or the bundle. Ubuntu 24.04 (3.12), Debian
  12 and 13, and macOS's `/usr/bin/python3` (3.9.6) users take the bundle.
- One version tested, on Linux and Windows: a defect that only an older
  Python would show is no longer looked for, on purpose.
- The code can drop its 3.9 forms (about 890 `Optional`/`List` annotations,
  tarfile's filter fallback) in one mechanical change.
- Moving to 3.15 is a measured step: it makes UTF-8 the default encoding on
  Windows (PEP 686), which a green build has to show is harmless here.
- Bundled libraries make their security fixes ours to ship.

### Amendment (2026-10-23): filelock adopted, at 3.x

The defect, measured first (`tests/test_datalock.py`, fails on main): two
refreshes of one data folder - the wizard at start and `--update-data` - shared
the `<source>.new` staging folder. The second wiped the first's download (the
first failed with `No such file or directory`), and the first, saving its
manifest last, erased the entry the second had just written: the folder held
a copy the manifest no longer named.

**Decision**: a refresh that has something to do holds
`filelock.FileLock(<data dir>/.lock)` from reading the manifest to saving it.
When every source is fresh it writes nothing and takes no lock. When another
program holds it, `--update-data` waits up to 300 s; the automatic refresh at
the start of a run does not wait (review of #66: it stalled an ordinary run
for five minutes behind `--update-data`) - the other program is updating the
data already, and the last good copy is used. Either way the sources not
refreshed report `failed` with the reason. filelock is imported only then:
it brings asyncio and sqlite3, about 0.2 s on each start. Readers take no
lock: a source is swapped in by two renames, so a run reading at that instant
can miss that source for this run, or meet half of krion64's per-mod files;
measured as possible, not seen, and left as it was before.
**filelock 3.32.7**, the last 3.x (2026-09-16), not 4.x: 4.0.0 came out the
next day and had eighteen releases in its first thirty days, so Dependabot
holds the major version until it settles. MIT, pure Python, standard library
imports only.

**Alternatives**: `fcntl.flock` and `msvcrt.locking` by hand - twenty lines,
but two code paths to test where only one runs in CI's Linux job, and the
Windows half (byte-range locks; `LK_LOCK` retries ten times a second apart, no timeout of one's choosing) is the part
filelock exists to get right. Rejected for the reason this ADR adopts
libraries at all.

**Consequences**: one more library in the .pyz and the bundles (its MIT
licence file shipped; no source offer needed, unlike MPL's). `--update-data`
can wait for another one, at most five minutes. Not covered: the metadata
cache (`mod-metadata.json`), saved outside the lock - two runs at once can
lose one side's new entries, which costs only fetching them again. On a file
system without `flock`, filelock falls back to a marker file that a crash on
another machine leaves behind.

### Amendment (2026-10-23, later): filelock 4.2.4, for CVE-2026-112940

**Context**: CVE-2026-112940 (CVSS 3.1 7.1, fixed in 4.2.1; first seen here
when pip-audit failed on 2026-10-23) is in filelock 3.20.4-4.2.0: `ReadWriteLock` and
`AsyncReadWriteLock`, the SQLite reader/writer locks, let another local user
who can create or rename entries in the lock's directory make SQLite write into, create
or unlink the lock user's files. iemod-fetch uses only `FileLock`, so the path
is not reached; but the .pyz and the bundles carry the vulnerable module, and
pip-audit failed every pull request that still pinned 3.32.7 (#77). No release carried 3.32.7: it came
in after 3.0.0.

**Decision**: filelock 4.2.4 (the latest, 2026-10-19), `>=4.2.1,<5` in
pyproject, not `--ignore-vuln`: a known-vulnerable module in what players
download is reported by every scanner they may run, and an exception would
have to be re-argued at each new advisory. The hold on 4.x is lifted earlier
than planned. It was there because 4.x was changing fast, not because of a
known defect. The one incompatible change in 4.0.0 is `SoftReadWriteLock`'s
on-disk protocol, also unused here. Measured on 3.14: the suite and
`tests/test_datalock.py` (two refreshes on one folder; a second process
holding the lock) pass unchanged; `import filelock` takes 37 ms instead of
79 ms, since 4.2 loads the lock types other than `FileLock` on first use.
Dependabot's version updates hold the next major version for a move by
hand, in both of its pip entries: the root one reads pyproject's
dependencies too, and had no hold - it opened #68 (3 -> 4.2.4) two minutes
after #66 changed dependabot.yml. #76 (3 -> 4.2.1, the first fixed version,
outside the weekly schedule and the runtime group) came from the
`/requirements` entry despite its hold: evidently a security update, which
that hold does not stop.

**Consequences**: Python 3.11 or newer for filelock, below the 3.14 the
project requires. A later 4.x is a Dependabot pull request like any other
runtime library.

### Amendment (2026-10-31): Debian trixie is the minimum platform

The maintainer set Debian trixie (13) as the minimum platform: "not older
versions". The Python stays 3.14 - trixie's own is 3.13, so there the bundles
(which carry their Python) are the way in, and the `.pyz` or pip need a 3.14
the player installs (uv, python.org). What changes is what the Linux bundles
are held to and tested on:

- **glibc ceiling 2.41, trixie's** (`cli_bundle.MAX_GLIBC`, was 2.35 for
  Ubuntu 22.04 and Debian 12). A bundle needing more stops the build.
- **Both Linux bundles are built on `ubuntu-24.04`**, pinned: the command
  line's leaves `ubuntu-22.04`, a runner GitHub is retiring (GUI-AUDIT row
  61); the wizard's leaves `ubuntu-latest`, which would move to a newer
  glibc on its own.
- **Both are started inside `debian:trixie`** before release: the command
  line with `--version` and `--help`, as before on `debian:12`; the wizard -
  never started on an older system until now - with `--check` offscreen,
  after installing the Qt system libraries a player installs.
- Debian 12, Ubuntu 22.04 and older are no longer what a release is checked
  against. A bundle may still start there; nothing says so.

---

## ADR-0044 — lcc-docs' dates as a second update signal, never as a version

**Status**: accepted
**Date**: 2026-10-23

### Context

Updates are found from krion64's `version_cache.json`: a GitHub release tag
per repository. lcc-docs (`db/mods.json`, 2,151 mods, kept by hand every two
or three days) has no version numbers; it has `last_update` (2,142 mods),
`status` (stable, beta, obsolete 75, archived 66, missing 60...), `safe` and
`compatibilities` ("EE version >= 2.5"). Measured on the supplied logs (149
mods), with the data of 2026-10-23, matching each tp2 to krion64's mod
records (`t` -> `gh`) and to lcc-docs' `tp2`: 90 have both, **52 only an
lcc-docs date** - no tagged GitHub release krion64 can see: mods hosted
elsewhere (Weasel Mods, Gibberlings3's site, baldurs-gate.de) and GitHub
repositories without releases (gibberlings3/ee_fixpack, gitjas/toa...) - 4
only a krion64 release, 3 neither; for 9, the lcc-docs date is newer than
krion64's latest release. The numbers move with the matching: through the
manifest's `github` field, 87 / 55 / 4 / 3 and 7 newer; through krion64's
mods index, 112 / 30 / 3 / 4. Between 30 and 55 mods, then.

### Decision

- The version stays krion64's: a tag compared with the installed one.
- lcc-docs adds a **date**: when it is newer than the copy the player has, the
  mod is marked "maybe updated", with the page's link - never "update
  available", since a date cannot tell a release from an edited page.
- lcc-docs' `status` and `compatibilities` are shown with it.
- When the two disagree, both are shown.

### Consequences

The 30 to 55 mods with no GitHub release get a signal they lack today. Some marks will be
pages edited without a new release; the wording says so. A test pins that a
date is never presented as a version.

### Amendment (2026-11-01, GUI-AUDIT item 50): which date is "the player's copy"

- **Measured: the tp2's mtime cannot be used.** Through `archives.safe_extract`,
  a tp2 dated 2019-05-04 in a zip came out dated the day it was unpacked
  (2026-11-01), while the same tp2 in a tar.gz kept 2019-05-04. Python's
  zipfile does not restore the time; tar and 7-Zip do. The same mod would
  be marked or not depending on its archive format.
- **The date used is the day this tool fetched the copy**: `installed_at`
  in the mods folder's `.iemod-fetch-state.json` (install.State, UTC),
  written when a download or a supplied file is placed. A copy fetched on
  day D holds whatever was published by D, so an lcc-docs date after D
  means the page changed since.
- **Compared by day.** lcc-docs gives a day with no time or zone, so both
  dates are cut to the day. The same day is not newer, which leans toward
  not marking. A missing or unreadable date marks nothing.
- **A copy with no record says nothing.** That covers a folder put there
  by hand, or a mod only named by a WeiDU.log. Nothing is guessed.
- **A record counts only while its copy is still there** (review of #122).
  The folder must exist, and where the record keeps the tp2's VERSION, the
  tp2 must still say it. A release unpacked by hand over a fetched folder,
  or a deleted folder, keeps its old record, because the runner skips a
  folder it finds verified. A stale record can still mark a copy replaced
  by hand with the same VERSION, or one whose tp2 has no VERSION.
- **The day boundary is UTC.** `installed_at` is UTC, and lcc-docs' day
  has no zone. Near midnight, the fetch day can be a day off from the
  player's local date. Equal days do not mark, so the error is one day
  of silence, never a false mark.
- **The page** is lcc-docs' first link that is not a direct archive (114
  of 2,134 entries list an archive first). An address that is not https
  (69 entries) is shown as text, not followed.
- **compatibilities**: its `requires` and `conflicts` are already read as
  rules (catalogues.py, the conflict check). They are not shown again
  beside the date.
- **Shown in the wizard only.** Mod selection gets "(maybe updated)" in
  the version column, a "Maybe updated" filter, and in the details
  lcc-docs' date, the fetch day and the page. The CLI's mods-v1 document
  is unchanged, since no fetch day is known there. lcc-docs' status was
  already shown.

---

## ADR-0045 — The wizard runs mod_installer, on the player's word (amends ADR-0022)

**Status**: accepted (the owner's decision, 2026-10-24)
**Date**: 2026-10-24

### Context

ADR-0022 made the command line write two scripts for mod_installer and run
none of them: the operator reads and runs them. GUI-AUDIT M4 item 22 asks the
wizard's Installation phase to drive the install itself - its output in the
window, WeiDU's questions answered from a recorded answer, otherwise asked.
Asked whether to run it, keep generating scripts, or drive WeiDU directly,
the owner chose to run mod_installer; mod_installer and WeiDU come from paths
the player gives, else from a pinned download the player confirms (item 22b).

Read on mod_installer 16.0.0's source (GPL-3.0, invoked, never vendored):

- it installs a WeiDU.log in batches of consecutive components of one mod,
  logging `Installing mod WeiduBatchedComponents([WeiduComponent { tp_file,
  name, lang, component, ... }])` before each;
- when WeiDU waits for input it logs `User Input required`, `Question is` and
  the question, then reads **one line from its own standard input** and
  gives it to WeiDU - so whoever starts it can answer;
- it answers EET's question for the BG:EE folder itself, on Linux only.

Answers recorded for later live on the component's own WeiDU.log line in
Born2BSalty's Infinity Orchestrator's format (GPL-3.0, read at 33800cc, no
code copied): `// @wlb-inputs: a,b,c`, left to right, `,,` an empty answer.
The logs this tool writes already carry them through (`weidu.py` reads a
version up to the tag).

### Decision

- The command line is unchanged: `--emit-installer` writes scripts and runs
  nothing.
- The wizard's Installation phase runs `mod_installer` - the command the
  scripts run, after the checks they make (a game folder, a game with no mods
  yet, lower-case mod folders on Linux, both programs there) - as a child
  process, **only after the player confirms**, and only after the game's
  backup (ADR-0042). It starts nothing else: no WeiDU of its own, no mod's
  `setup-*.exe`.
- Its output is read line by line (`iemod_fetch/prompts.py`, pure: the batch
  started, a question once the output goes quiet) and shown. A question is
  answered, in this order: EET's BG:EE folder question with that folder;
  the next answer the planned log records for the batch being installed;
  else the player is asked. Every answer is shown with where it came from.
- Cancel terminates mod_installer, and kills it after a grace period - it
  and everything it started: its own process group on Linux and macOS
  (killpg), a Job Object on Windows (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`,
  terminated whole). The job, not `taskkill /T`, because a tree walk starts
  from a living parent and finds nothing once mod_installer is gone, and a
  pid may meanwhile be someone else's. The game's WeiDU.log says what went
  in; resuming from it is item 23.
- When mod_installer ends, whatever it started and left holding its output
  is given two seconds, then stopped the same way, and the player is told:
  left alone it would go on writing into the game folder, and the run would
  wait on it.

### Consequences

- **ADR-0006's "nothing downloaded is executed" is now narrower, and said
  so**: this program still never starts anything it downloaded. It starts
  mod_installer and, through it, WeiDU - which run the mods' tp2 scripts:
  that is what installing a mod is. Downloading, extracting, planning and
  the command line stay as before.
- A question no recorded answer covers stops the install until the player
  answers it; one answered wrongly is WeiDU's to judge, as in a terminal.
- A recorded answer cannot hold a comma (the format's limit). Answers are
  matched to a batch, not a single question: a mod that asks a different
  number of questions than the log recorded gets the wrong answers from the
  next one on - the same as BIO.
- What is verified: the run against a stand-in mod_installer that prints and
  asks as the real one does (every test run), and against the real
  mod_installer 16.0.0 driving the real WeiDU v251 on synthetic game folders,
  a test mod asking two questions (opt-in, `IEMOD_MOD_INSTALLER`). Not
  verified: a real install on real game data - no runner has the games.
- **Answers are written as UTF-8, and on Windows an accented BG:EE folder
  is refused** (until measured - item 22b measured it and lifted the
  refusal; ADR-0046, "the folder answer on Windows"). mod_installer reads its input with Rust's `read_line` into a
  `String` (`utils::get_user_input`, 16.0.0): anything but UTF-8 is an error
  there, so no other encoding can be chosen. It passes the line to WeiDU's
  input as those bytes (`runner.rs`, `write_all`). How WeiDU v251 on Windows
  opens a path it is given so is not measured (no Windows runner here has
  the real chain), and an ANSI reading would name another, missing folder.
  So the one answer known to carry a path - EET's BG:EE folder - must be
  plain ASCII on Windows; preflight says so before anything starts. Linux
  needs no answer (mod_installer fills it itself), macOS is UTF-8 throughout.
  A recorded answer with accents is written as it is, unmeasured likewise.
  The game folders on the command line are not affected: they reach WeiDU
  through its arguments, as with the generated scripts (ADR-0022).
- On Windows, mod_installer runs a moment before it is put in its job; a
  process it started in that moment would be outside it. mod_installer
  starts WeiDU only after reading its logs, well after that moment, so this
  is accepted rather than started suspended (which needs the Win32 process
  API, not subprocess). The Windows tests run the stop against a child that
  ignores a polite stop, so only the job's kill passes them.

### Item 22c: the wizard's page

- **The plan the install runs is written to `PROJECT/install-plan/`.**
  `api.write_install_plan` makes the same plan the order page shows (its
  install-order.txt, decisions.json), applies the project's language
  preference, and writes it as `--plan-order` writes it. Until now the
  wizard only planned in a temporary folder. Each install writes it again,
  so what runs is what the order page showed at that moment.
- **The order of steps is fixed:** the programs, then a backup of each game
  folder the project names, then the plan is written, then a confirmation
  that names the folders, the backups and what the order still breaks.
  Without a backup, *Install* is not offered.
- **A backup counts only if it is of that folder as it is now** (review of
  #87). It must be of that very folder (the manifest's `game_dir`), and
  restoring it must change nothing: `plan_restore` against the game finds
  no file to put back, displace or lose. That check hashes the game, so it
  runs in a thread of its own when the page is entered. Otherwise the page
  says so ("the game changed after the backup, N files differ"), and
  *Back up now* makes a backup that counts.
- **What the order breaks is named before anything runs.** The written
  plan carries the order rules it breaks and its cycles, as the order page
  shows them in red. The confirmation lists them (ten, then a count) and
  becomes *Install anyway*. Saying no installs nothing; the plan stays
  written.
- **A question no recorded answer covers is asked in a dialog** on the
  page's thread, while the install's thread waits. Cancelling the dialog,
  or *Cancel* at any time, stops the install and everything it started.
- **Nothing is undone by itself.** A failed or cancelled install leaves the
  game as WeiDU left it, and the page names the backup to restore. Restoring
  is the player's call, not an automatic step.

### Item 23: resuming a stopped install

- **The state is each game's own WeiDU.log.** WeiDU writes a component's
  line there once the component is in. An install resumes when that log is
  its planned log's beginning: the same components in the same order, each
  the same tp2 (its path compared without case and with `\` as `/`, since
  WeiDU writes `EET\EET.TP2` on Windows), the same language number and the
  same component number (`iemod_fetch/resume.py`, pure). A component in
  another language is another install. Anything else is not resumed - a
  component the plan lacks, another order, one missing in the middle - and
  each diverging line is named ("line 2: the game has X where the plan has
  Y", five at most and a count of the rest); the backup is how to start
  again.
- **A component stopped inside is not resumed (measured).** With the real
  mod_installer 16.0.0 and WeiDU 251 on Linux, a Cancel inside a component
  that had copied two files - one new, one over a file of the game's - left
  both in the game. WeiDU.log did not list the component, while
  `<mod>/backup/<n>/` held `UNINSTALL.<n>` listing both files, and the game's
  original of the replaced one. Installing that component again, WeiDU
  backed up the files it had left as if they were the game's:
  `MAPPINGS.<n>` then pointed at the mod's copy, so uninstalling it would
  have put the mod's file back and kept the new one, and the game's
  original would no longer be restored. So `install_run` looks for the next
  component's uninstall record (the tp2's `BACKUP` folder, case aside) and,
  when it is there, refuses to resume: the page says the component stopped
  half-way and that restoring the backup is the way. The tp2's `BACKUP`
  folder is read with `%MOD_FOLDER%` as the mod's folder, else
  `<mod>/backup`. As a net under that check, a resume after a Cancel names
  the components the cancelled run was in, and says that restoring the
  backup is the safe way if they left files. `weidu --uninstall`
  cannot help, since it works from WeiDU.log lines and the component has
  none. A failure WeiDU reports itself is not this case: WeiDU undoes the
  component it was installing, and leaves no record behind.
- **Only the rest is handed to mod_installer** (`install-plan/resume/`),
  with the game's existing mods allowed and `--skip-installed=false`.
  mod_installer's own skip is not relied on: 16.0.0 reads `game/weidu.log`
  in lower case (`weidu/batched_components.rs`). Measured with the real
  programs on Linux: one component installed, then a plan of two, gave
  "Number of mods to be installed: 2", the first one again. On Windows,
  whose names ignore case, it would skip. Turning it off makes every system
  run the same, worked-out rest. Reinstalling is slow for most mods and
  harmful for some, such as EET's core import. The scripts the tool writes
  for the player's terminal keep mod_installer's defaults.
- **EET resumes in the mode its state needs.** Its two logs go in order: an
  EET game holding components while BG:EE's part is unfinished is not this
  plan's install, and is refused before anything runs. If BG:EE's part is
  unfinished, the eet run takes BG:EE's rest and the whole EET log. If it is
  finished (its log is the whole pre-EET plan), the EET game is installed
  alone with its rest, as a normal install. EET's core may still be in
  that rest (a failure WeiDU undid), so its BG:EE folder question is still
  answered from the BG:EE game as given, not asked of the player (review of
  #89).
- **The backup made before the stopped install keeps counting** while
  resuming. The game changed since, but those changes are the components
  the log lists, and restoring that backup goes back to before them.
- **A wrong state is never repaired by guessing.** The resume refuses
  whatever does not prove itself a prefix of the plan, and the backup stays
  the way back.
- **Upstream.** The lower-case `weidu.log` in mod_installer (its skip, and
  `get_last_installed`, fatal before 14.5.0) is worth reporting to
  dark0dave/mod_installer. Whether to report it is the maintainer's call;
  nothing has been opened.

### GUI-AUDIT M8 item 63: no answer is held back on its question's text; what was answered is recorded

- **Context.** The log's `// @wlb-inputs:` answers are sent in order, one per
  question, whatever the question. A mod whose prompts changed between the
  version a log was recorded on and the one installed shifts them silently.
  Chriz Easy BG (MIT, read at 508256a) sends each answer only after its
  expected question text appears (`engine/src/weidu/runner.rs`,
  `PromptMatcher`); its recipe authors that text. Our logs come from players
  and BIO, and hold answers only.
- **What mod_installer sends (measured; reviews of #98).** When a line looks
  like a question (its choice words and phrases,
  `src/config/parser_config.rs`), mod_installer copies in WeiDU's last
  `lookback` lines, 10 by default (`src/parser.rs`), then collects until the
  output goes quiet. With the real 16.0.0 and WeiDU 251: WeiDU's version
  line, "Installing [First] [v30]", "Copying 1 file ...", the question; an
  earlier question stays in the window when it is near, and a menu printed
  after the question follows it - the parser may fire on an option line.
  With 16.0.0's batches, several components share one window's history.
- **What was tried, and dropped - four rounds, each independently reviewed.**
  (1) Identity: the question an answer was given for, kept per component and
  place, a changed one refused, the player's answers kept and given again.
  With several components in a batch the answers were kept under the wrong
  one; a conditional question skipped made the next one's right answer
  refused; short prompts dragged game paths into the identity; kept answers
  never expired. (2) A rule on the text alone - an answer not among the
  choices a plain question names is held back. Real mods refute it: Tweaks
  Anthology #3210 asks "Select a minimum STRENGTH value, between 6 and 15, or
  0 for no minimum:" and takes 0 (its tp2's `(s < 6) AND (s != 0)` decides,
  not its text); "Choose 1-3, or 0 to cancel", "Choose 1 or 2, or 3 for
  both", "Overwrite? (Y/N/A)", "[Y]es or [N]o or [C]ancel", "press Return
  for the default" were all refused wrongly. A rule that refuses what it
  does not recognise fails closed, the opposite of what is safe here.
  Which answers a question takes is in the mod's tp2, not in the window's
  text.
- **Decision.** No answer is held back on its question's text. Recorded
  answers go in order, exactly as before; a question with no recorded
  answer is asked of the player, who sees mod_installer's whole window.
  `install-plan/answers.json` records what each install answered - each
  question's last line, the answer, recorded/player/EET, under `"v": 1` -
  written on every run (empty too, so an earlier run's record is not left),
  for the player and for a bug report. Nothing reads it back to decide.
  On a resume the record holds the resumed part only: the run before it
  wrote its own, which the resume replaces. Which question it is, and which component's - and with them answers by
  question rather than by place - come with item 48's expected texts (each
  component's READLNs resolved from its .tra, `readln.py`, ADR-0049), not
  from the window.
- **Consequences.** A log whose answers shifted against a mod's changed
  prompts still installs with them shifted, as before; the record says what
  went where. The stand-in mod_installer now sends WeiDU's last 10 lines with
  each question, as the real one does, and tests with the real mod_installer
  and WeiDU show a yes/no then "select 1 or 2" installed from a recorded
  "y,2", and a menu printed after "Which portraits?" taking its recorded "1".

### GUI-AUDIT M8 item 65: a known upstream fault is said before installing

Kept in ADR-0045 on purpose: it is part of what the wizard says before it
runs mod_installer.

- **Context.** EET's core finds the Documents folder with a batch file
  (`EET/lib/macros.tph`, `GET_USER_DIRECTORY`, upstream since 38db44c): `for
  /f "tokens=3,*"` over `reg query ... User Shell Folders /v Personal`, then
  `set DOC_DIR=` the first variable - the third token only. A registered
  value with a space is cut at it. What follows, read in EET's source at
  c26a11a (2026-10-29) and not run on Windows (reviews of #100): the core
  builds a settings folder from the cut path (`<cut>\Baldur's Gate -
  Enhanced Edition Trilogy`), WeiDU's MKDIR makes the missing folders, and
  `Baldur.lua` - language, active campaign, EET's installation state - is
  copied or written there, with an empty `save` folder (EET.tp2
  L1091-1157). The game finds its own Documents folder through
  `engine.lua`'s `engine_name` and never reads that one. So the core most
  likely finishes; the saves stay where they belong; EET's settings, and
  the `Baldur.lua` carried over from BG2:EE with its language, never reach
  the real folder - a player not playing in English may start in the
  default language and settings - and a stray folder is left at the cut
  path. Chriz Easy BG met it ("the community EET failure",
  `docs/handover.md` L138-142) and patches EET's copy (MIT, 508256a). The
  value is read before `%VARIABLES%` are expanded, so the usual
  `%USERPROFILE%\Documents` has no space even when the user name has one;
  a folder moved by OneDrive ("OneDrive - Company\Documents") or chosen by
  hand ("D:\My Documents") has.
- **Decision.** `install_run.known_issues` (api `install_known_issues`)
  says it before installing, on Windows, when the plan has EET, EET's core
  is not yet in the EET game (a resume past it is not warned), the raw
  `Personal` value (`winreg`, unexpanded) has a space, and the EET copy in
  the mods folder still has that shape of line at a line's start - any
  variable letter, "tokens=3*", "do (set ...)" - unless it opens a block
  that sets the whole path before closing - the one way a later line fixes
  it; comments do not count, a block nested in it (`if (` over lines,
  `) else (`, a `)` in quotes or after `^`) does not close it, and a set
  inside a nested block depends on its condition and does not count
  (matched, not copied - EET is GPL-3.0). The
  message names the registered value and the folder EET will write its
  settings to (a `%VARIABLE%` in it shown expanded). The wizard puts it in
  the confirmation, "Install despite a known issue"; it is not a refusal:
  the player decides, knowing. EET's file is not patched: changing a mod's
  content needs item 52's ADR.
- **Consequences.** A player whose EET settings and language would have
  gone to a folder the game never reads - or whose core would have failed -
  with no word of why is told before, with the registered value and where
  EET will write. An EET release that keeps the whole path no longer
  matches, and the warning goes by itself. The claim about the outcome is
  read in the source; no Windows run confirms it. Reporting the bug to EET
  is the maintainer's call; nothing has been opened.

---

## ADR-0046 — mod_installer 16.0.0, built from source into the wizard's bundle, until upstream releases it

**Context.** The wizard runs mod_installer (ADR-0045), so the player needs
one (GUI-AUDIT M4 item 22b). The maintainer first chose dark0dave's latest
stable tag, v12.1.1. Measuring it changed the choice:

- **It stops after the first component on Linux.** After every component it
  opens `weidu.log` in the game folder (`utils::get_last_installed`,
  unconditionally), and WeiDU writes `WeiDU.log`. Measured with the real
  WeiDU v251 on a synthetic game: v12.1.1 exits 1 after the first component;
  16.0.0, same input, exits 0. Windows and macOS file systems ignore case,
  so those systems are not affected.
- **Its published binaries are not what their names say.** The
  "x86_64-apple-darwin" one is arm64; the "x86_64-unknown-linux-musl" one
  links glibc.
- **It works differently.** It logs its batches in another form
  (`Component { ... }`, one at a time) and never fills EET's BG:EE folder by
  itself.
- **16.0.0 has none of these problems, and upstream has nothing newer.**
  16.0.0 is upstream's main branch: commit 3b6827a, which CI's real-weidu
  job tests. It has no release, and there is no newer commit or tag (checked
  2026-10-24).

**Decision.** The maintainer's choice: 16.0.0 on every system, compiled as
part of this project's build, until an upstream stable release includes it.

- **`packaging/mod_installer.py` builds it.** It:
  - fetches the commit by its id with git (the id names the content);
  - installs the pinned Rust (1.98.0) and the system's target with rustup;
  - builds with the commit's own Cargo.lock;
  - checks that the program says `mod_installer 16.0.0`.

  The targets are:
  - Linux: static (musl), so it runs on any distribution;
  - Windows: x86_64, with the C runtime linked in (`+crt-static`). By
    default Rust's MSVC programs load VCRUNTIME140.dll (measured: upstream's
    v12.1.1 .exe names it). A clean Windows lacks that DLL, and the bundle
    keeps its own copy under `_internal`, where mod_installer does not look.
    The build fails if the program still names it.
  - macOS: Apple silicon, the runner's architecture. This is the wizard's
    own bundle's architecture too (README): no Intel Mac either way.

  It installs what rustup can. It names what it cannot install: git, rustup,
  and on Linux musl-gcc (Debian/Ubuntu: `musl-tools`, which the workflows
  install).
- **The wizard's bundle carries it.** `gui_bundle.py --mod-installer` puts
  it beside the wizard's own program, with its GPL-3.0 text and a NOTICE
  giving the source at that commit. The unzipped copy runs it once. The
  release workflows (Linux, Windows, macOS) build it for every new tag; a
  tag made before the script existed is built as it was.
- **Its source is published from the same place as the program.** The
  script also writes `mod_installer-16.0.0-source.tar.gz` (`git archive` of
  the commit; the same bytes on every run). release.yml attaches it to each
  release whose bundles carry the program, lists it in SHA256SUMS and covers
  it with the attestation. This is the GPL-3.0 section 6(d) way, served by
  this repository rather than by a third party's server: upstream may
  rewrite or delete its history, and our release still holds the source.
  The bundle's NOTICE names that file first and upstream second.
- **Which version: the newest, measured against its neighbours** (asked
  again by the maintainer). Upstream tags stop at v12.1.1. After it, main
  holds 129 commits and "prep" commits for 13.2.1, 14.1 to 14.5.2, 15.0.0,
  15.0.1 and 16.0.0, none of them tagged or released. The weidu.log bug
  (`get_last_installed(...)?`) became harmless in 14.5.0, where a log that
  cannot be read no longer stops the install; 16.0.0 still opens
  `weidu.log` but carries on. 14.5.2, 15.0.1 and 16.0.0 were built here and
  each passed the real-install tests on Linux (8 tests, the real WeiDU v251).
  14.5.2 reports "config 1.2.0" to `--version`, so it cannot be recognised.
  16.0.0 adds, over 15.0.1, closing its input properly (#325), passing
  WeiDU's OCaml memory settings down against crashes on large installs
  (#324) and better batching (#326). It stays the pin, and is the version
  CI tests on Linux and Windows.
- **Its Rust libraries are not vendored.** They are named, with their
  checksums, in the commit's Cargo.lock, and served by crates.io. They are
  MIT and Apache-2.0, not GPL. A `cargo vendor` archive would be the
  strictest reading of "Corresponding Source", at tens of megabytes per
  release; it is left for the maintainer to decide, and this is where the
  choice is recorded.
- **CI tests the same binary.** ci.yml's real-weidu job builds mod_installer
  with the same script, so the program tested is the program shipped. Its
  `mod-installer-windows` job builds the Windows .exe on every change, with
  the guard against VCRUNTIME140.dll, because the release builds the bundles
  only for a release. macOS is built by release-macos.yml on every change
  to packaging. A
  test keeps the commit and version in the script and in ci.yml equal.
- **The command line is unchanged.** The generated scripts run the player's
  own mod_installer, at their terminal.

**Consequences.**

- **This project now ships a third party's program.** It ships as a
  separate executable (aggregation, not linking), with its licence and its
  exact source named in the bundle. The bundle's build provenance covers it.
  A wrong build is ours to answer for.
- **Builds are slower, and need what Rust needs.** The bundle builds take
  about two minutes longer. Building locally needs git, rustup and, on
  Linux, musl-tools; the script says which is missing.
- **Players without the bundle get no mod_installer from us.** For the
  zipapp, pip, or a system the bundle does not exist for, the player gives
  the path of their own (item 22b checks its version).
- **Retirement.** When upstream releases a version with the fix, the pin
  moves to that release and this build may go. The weekly upstream check
  opens that issue.

### Item 22b: finding the programs, and WeiDU's download

**Decision.**

- **mod_installer** is found where the player says, else beside the
  wizard's own program (the bundle's), else on PATH. It is never downloaded,
  because no upstream release is fit for it.
  - One older than 16 is refused on Linux, where it stops after the first
    component.
  - Any version not tested here is used, with a note.
- **WeiDU** is found where the player says, else on PATH, else as its
  official v251 release. That release is downloaded only on the player's
  word: `api.tool_download` names what would be fetched and its licence
  (GPL-2.0) for the confirmation.
  - The download goes through `net.HttpClient` (https, size cap), and the
    zip's sha256 is checked before anything is unpacked.
  - `archives.safe_extract` unpacks it.
  - The program is checked against its own sha256 and made executable for
    the user only.
  - It lives in a per-user tools folder beside the data cache.
  - Each later lookup checks that sha256 again, so a program swapped there
    is not run.

  The pins were measured from WeiDUorg's zips: the Linux binary is static,
  the Mac binary is x86_64 (Rosetta on Apple silicon). A test keeps them
  equal to the digests CI verifies.
- **PATH means PATH's folders.** `shutil.which` on Windows tries the
  current folder first, even when given `path=` (read in Python 3.14's
  shutil), so a stray weidu.exe in the folder the wizard was started from
  would be run. `toolchain.on_path` looks only in PATH's folders.
- **On Apple silicon, a WeiDU that does not answer** is told apart from a
  wrong program: the Mac build is x86_64 and needs Rosetta 2
  (`softwareupdate --install-rosetta`), and the message says so.
- **None of mod_installer's options comes from the environment.** Its clap
  arguments each read an environment variable too: 29 of them in 16.0.0's
  `config/args.rs` and `options.rs`, such as NEW_EET_DIR, OVERWRITE and
  DOWNLOAD. Any the command line does not set would be the player's, so
  `install_run.mod_installer_env` drops them all (case-insensitively, for
  Windows). What mod_installer still reads from the player: its per-user
  parser configuration (confy, in the system's config folder, used when its
  version matches). That holds the strings it recognises questions by. It
  is the player's mod_installer configuration, as for the generated
  scripts, and is left alone.
- **The wizard runs mod_installer with `--download=false`.** Otherwise, for
  a mod not found, 16.0.0 and 12.1.1 both log "Please provide mod url" and
  download what the next line of their input names. That bypasses the
  project's download path (ADR-0003, ADR-0006) and its question parser.
  Measured: with the flag, a missing mod is "Failed to find mod".

**The folder answer on Windows.** #83 refused an accented BG:EE folder on
Windows until the path could be measured. `tests/test_real_mod_installer.py`
now measures it: a test mod asks for a folder, the planned log answers with
a folder name, and the answer travels through mod_installer to WeiDU, which
checks `FILE_EXISTS` on a file inside it. Three names:
- an ASCII name, the control (a missing file makes the test fail);
- `città – über`, which fits Windows' ANSI code page (cp1252);
- `Игры ゲーム`, which does not.

A program that opened paths through the ANSI API would pass the second name
and fail the third (review of #86), so the third is the one that says
something. On CI's Windows runner (run 40079746900), the official WeiDU v251
for Windows and the bundle's own mod_installer 16.0.0 build found the file
under all three names: 4 real tests passed, none skipped
(`IEMOD_REQUIRE_REAL=1`). WeiDU opens paths through the wide API.

The refusal is lifted. What stays unmeasured: real game data, and EET's own
tp2 rather than a test mod that reads a path the same way.

---

## ADR-0047 — RAR and 7z archives: the system's libarchive, then unar, then the player's own 7-Zip or WinRAR; none shipped

**Context.** About half of lcc-docs' direct download links (150 of 290) are
.rar, .7z or .exe. GUI-AUDIT item 40 planned "7-Zip in the bundles, after a
licence review of the unRAR clause". The review: 7-Zip's RAR code carries
the unRAR licence, which forbids using it to recreate the RAR compressor and
is not an open-source licence; Debian removes it (its `7zip` package is the
"dfsg" build). The maintainer asked for open-source tools that can be
included, and set Debian trixie as the minimum platform.

So the candidates were measured before anything was chosen
(`tools/rar_measure.py`, the `RAR extractors` workflow, docs/TESTING.md):
every distinct .rar link of lcc-docs, extracted by each tool and compared
file by file (SHA-256) with the official 7-Zip 26.00. Of 130 downloads, 105
are RAR (98 RAR4, 7 RAR5, 7 solid); the other 25 are not archives at all.

| Platform | libarchive (bsdtar) | unar | Debian's 7zip (dfsg) | Any |
|---|---|---|---|---|
| Debian trixie | 95 | 94 (RAR5: 0 of 7) | 1 | 100 |
| Windows (`tar.exe`) | 95 | - | - | 95 |
| macOS (system bsdtar, Homebrew unar) | 95 | 103 | - | 103 |

Every tool that did not extract an archive identically also exited non-zero
on it (the measurement records both), so the exit code tells success.

The measurement also found a defect in what shipped. 7-Zip was tried
first, and on Debian and Ubuntu `7z` is the dfsg build: it writes every file
of a RAR with the wrong contents and exits 2. unar then extracted into the
same folder - without `-f`, renaming its files beside the wrong ones - and
the result was reported as extracted. Run on real archives in this
repository's sandbox (Ubuntu's 7zip, bsdtar 3.7.2, unar 1.10.1), the old
order gave a tree different from 7-Zip's for every archive tried, with no
error.

**Decision.**

- **Nothing is bundled.** libarchive is part of Windows 10 and 11
  (`System32\tar.exe`) and of macOS, and one `apt install libarchive-tools
  unar` on Debian and Ubuntu; it opens 95 of the 105 on every system.
- **The order for .rar: bsdtar, unar, 7z, 7za, unrar.** unar (LGPL-2.1+)
  opens most of what libarchive cannot - solid RAR4 - and, from 1.10.8
  (Homebrew's), RAR5. Then a 7-Zip or WinRAR the player installed: used
  when there, never shipped, so their licences are the player's. Their
  standard Windows install folders are searched, as before.
  For .7z: 7z, 7za, bsdtar, unar (7-Zip's own format, and Debian's 7zip
  reads it). For a self-extracting .exe (`--allow-exe`): 7z, 7za, unar.
- **On Windows, bsdtar is `%SystemRoot%\System32\tar.exe`**, not `tar` from
  PATH, which may be Git's GNU tar (it reads no RAR).
- **unar runs with `-D` and `-f`**: the archive's own layout, as the
  measurement compared it, with no folder of unar's own around it.
- **Each tool extracts into a folder of its own** beside the destination,
  deleted when the tool fails, read-only folders included; only a tool that
  exits 0 has its files moved into place, then audited as before (ADR-0003).
  A move that fails (on Windows, an antivirus holding a file) counts as that
  tool's failure: what it moved is taken back and the next tool is tried. The 7z listing, when
  7-Zip can read the archive, still holds it to the zip/tar rules first.
- **When no tool is installed, the message says what to install per
  system** - and that Debian's 7zip cannot read RAR. It no longer suggests
  `p7zip-full`.

**Consequences.**

- On Debian and Ubuntu a RAR is extracted right or not at all: the silent
  wrong extraction is gone. `tests/test_archive_tools.py` pins the order,
  the fresh folder per tool (a tool that writes then fails leaves nothing),
  Windows' tar.exe, unar's flags, a failed move, a read-only leftover and
  the message; each failed before.
- Two solid RAR4 archives (027 and 030 in the measurement) no open-source
  tool opens; on trixie a solid RAR5 (023) too - bsdtar refuses its
  dictionary size and trixie's unar reads no RAR5, Homebrew's does. Those
  need the official 7-Zip or WinRAR, and the error names every tool tried.
- Windows without 7-Zip opens 95 of the 105: unar has no maintained Windows
  build. With 7-Zip installed - common there - the rest open.
- The bundles stay as they are; this is no new dependency. The measurement
  workflow can be re-run when libarchive or unar change.

## ADR-0048 — One TLS context per process, built by the wizard before its window is drawn

**Context.** The release gate of 4.0.0 failed on the M3 test's limit: the
wizard's window waited 240 ms during a download on windows-latest. The
`GUI latency` workflow (docs/TESTING.md) measured it: 30 runs per OS,
ubuntu-latest worst 13.8 ms, windows-latest worst 64 ms. Every Windows gap
over 50 ms came before the download had sent its first event, with no
garbage collection in it. A faulthandler watchdog, which needs no GIL and
dumps every thread's stack when the loop has been held 40 ms, caught the
download's thread each time in `ssl._load_windows_store_certs`, called from
`HttpClient.__init__` → `urllib.request.build_opener` →
`ssl.create_default_context`. urllib builds a new TLS context for every
opener, and on Windows building one reads every certificate of the system
store and parses it while the GIL is held, so no other thread runs, the
window's included. Every `HttpClient` paid it: every download, catalogue
update and conflict check started from the wizard.

**Decision.** `net.https_context()` builds the default verifying context
once per process, under a lock, as http.client builds its own (through
`ssl._create_default_https_context`, so the PEP 476 hook a site may set is
honoured; ALPN http/1.1; post-handshake auth on), and every `HttpClient` passes it to its opener's
`HTTPSHandler`. An `SSLContext` may serve connections from several threads.
`api.prepare_https()` builds it ahead of time; `MainWindow` calls it in its
constructor, before anything is drawn. If building fails there (an
`SSLKEYLOGFILE` that cannot be opened, a broken trust store), the wizard
still opens and nothing is kept: the first HTTPS client builds it again and
reports the error as that run's failure, as before. The 100 ms limit of the M3 test
stays.

**Consequences.**
- The trust store is read once per process, not once per client. The
  wizard pays it at start-up, before its window appears; the command line
  pays it once at its first HTTPS client.
- What is accepted does not change: the same default context, certificate
  and hostname verification required, the system's trust store (the HTTP
  layer's policy in docs/SECURITY-MODEL.md).
  A trust store changed while the process runs is seen at the next start,
  not the next download.
- Measured after the change: windows-latest median 10.9 ms, worst 11.8 ms
  over 30 runs of the M3 test (before: 15.5 and 63.9 ms).
- Tests: `tests/test_https_context.py` (one build, shared, still
  verifying, the PEP 476 hook honoured, built by `prepare_https`, a failed
  early build left to the first run) and the wizard's test that the
  constructor builds it. The `GUI latency` workflow re-measures it.

## ADR-0049 — Every question a mod asks is known before the install starts; never answered by a timer

**Status**: accepted (the owner's decisions, 2026-10-31)
**Date**: 2026-10-31

### Context

A large EET install meets WeiDU questions (`ACTION_READLN`): a menu, a
yes/no, a number, a path. ADR-0045 answers them from the planned log's
recorded answers (`@wlb-inputs`), else asks the player, and never guesses.
That is safe but not deterministic: a question no answer covers stops the
install until someone answers it, possibly hours in. The owner asked for
deterministic installs, using what the other projects learned, without
reinventing the wheel. What they do, read on their code (GUI-AUDIT M8):

- Infinity Orchestrator/BIO: answers per component, in order, on the log line
  (`@wlb-inputs`, adopted by ADR-0045). The order shifts when a mod's
  questions change.
- Chriz Easy BG: an answer is sent only when its question appears
  (`PromptMatcher`; item 63, PR #98).
- Infinity Mod Runner: default answers as configuration, and "1" sent after
  30 s of silence. Rejected: a timer answers questions nobody read
  (ADR-0005), and a wrong menu choice installs quietly.
- BWS-NG describes questions as data for 4 components; the Forge has
  free-text notes of manual steps.

Measured (`tools/readln_census.py`, 2026-10-31) on the WeiDU files of 105 of
the reference build's 108 GitHub mods (3 did not clone): 8 mods hold a
READLN, 51 READLNs in all. Read lexically, 45 (88%) are reached from a
component - in its body, a function or macro it launches, a file it
includes, its ALWAYS block, with `%COMPONENT_NUMBER%`, the preamble's
constants and inlined files followed. The question is known for 42 of those
(93%): 25 are a .tra string, shown in the player's language, and 17 a fixed
text in the code (English whatever the language); 3 are printed from a
variable set elsewhere (LCA's `%xa_prompt%`), unknown. Of the 6 not reached,
5 are SCS's, behind paths its SFO library builds while installing
(`%sfo_loc%`), and 1 follows a `FAIL` (TDDz) and is never asked.

### Decision

1. **Before installing, the questions are known** (item 48,
   `iemod_fetch/readln.py`, pure): for each chosen component, every READLN
   it may reach, with its question's text in the project's language,
   whether it sits under a condition (may not be asked) or in a loop (asked
   until valid), and what could not be followed (`unread`). A question is
   keyed by its .tra reference (`@n`) - not by its text, which changes with
   the language and arrives inside mod_installer's ten-line window
   (ADR-0045, item 63) - else by its text.
2. **The player answers them in one place, before Install** (the coverage
   is `api.install_questions`: per component, its questions and the answers
   the log records, and an unattended forecast; the wizard's planned logs
   carry no answers until the questionnaire in phase 5, next, writes them):
   the answers are kept with their key,
   the mod's version and the component, and a preflight says whether the
   install can run unattended, listing what is still uncovered.
3. **Never a timed answer.** A question with no answer stops and asks, as
   ADR-0045 says; a timer never answers (owner, 2026-10-31).
4. **A watchdog that only warns** (owner, 2026-10-31): it tells "waiting for
   an answer" (mod_installer's `User Input required`), "slow but alive"
   (output still coming) and "silent for longer than the threshold" apart,
   and on the last one warns, with the last window of output. It never
   stops the install: a component working silently would be killed half
   done, an error this tool would cause. The threshold is measured first on
   real components' longest silences.
5. **What was asked and answered is written back** - the log's
   `@wlb-inputs` and the project's answers - so the same project installs
   again without a question.

### Consequences

- An unknown question (printed from a variable) is keyed by where it is asked
  and by which component - file, line, variable, component - never by an
  empty key. One component calling one asking function twice (LCA's
  `xa_determine_quantity` asks what its caller passes) still shares it, so an
  unknown question is never answered from a stored answer: it is asked.
- WeiDU's keywords are read case-sensitively (`SET end = 5` is a variable);
  a READLN after FAIL or ABORT in its block is never asked, except in a TRY's
  handlers, which run because the body failed.
- The component cuts are tp2.py's: a line `BEGIN` followed by a line opening
  with a string (`ACTION_DEFINE_ARRAY x` / `BEGIN` / `~a~`) would be taken
  for a component; no tp2 of the corpus has one. A question printed inside a
  function and read in its caller is found without its text.
- A lexical reading misses what runs at install time: a path built from a
  variable set while installing (SCS's SFO library), a question inside a
  program the mod starts, a condition on an earlier component. A first
  install of a mod never seen may still stop once; the second does not
  (point 5). The census says how much is missed, per mod.
- Whether WeiDU really asks a reached READLN takes a real install, which no
  runner has the game data for: `conditional` says it may not be. The real
  prompts credited in item 64 (Bardic Wonders 1008, Item Randomiser 510 and
  1100, Warlock 0) are the external check still to make - their repositories
  were not found under the names tried.
- Item 63 (PR #98) can recognise the question being asked from the texts
  read here instead of from the window's last line.

### Amendment (2026-10-31): the questionnaire, points 2 and 5

Built in phase 5. The planned log's answers are handed out in order, one per
question, batch by batch (ADR-0045), so an answer written ahead lands on the
right question only while every question before it is surely asked once.
`api.install_questions` marks a question `beforehand` while that holds,
from the component's first question:

- the run stops **before** a question under a condition: if it were not
  asked, its answer would go to the next question;
- it stops **before** a question whose key came already in the component:
  two questions that read alike would share one answer;
- it ends **after** a question asked until valid: an answer it refused would
  go to the next question, while with nothing left WeiDU's next try is
  asked of the player;
- a component whose reading could not follow a path, or with a question
  whose text is unknown (status `unknown`), has none at all;
- **in a batch** - mod_installer 16.0.0 runs consecutive components of one
  mod together and `prompts.Answers` hands their answers out from one
  queue - a component has none unless every component before it in the
  batch can be answered in full (every question beforehand, none asked
  until valid): else a question of an earlier one, left to the player,
  would take this one's answer (independent review of #107, reproduced).
  A batch is taken to be consecutive components of one tp2 file; whether
  mod_installer groups by tp2 or by mod folder was not confirmed - two
  installable tp2s in one folder, back to back, would be one real batch but
  two here (no such mod is known).

Before *Install*, the questions marked `beforehand` that have no kept answer
are put to the player in one window, under their component, with the kept
answers filled in. The answers are kept in `PROJECT/install-answers.json` as
{"tp2#number": {question key: answer}} and written into the planned logs as
`// @wlb-inputs:`, up to each component's first question with no answer
(`api.write_install_answers`). The confirmation then names the components
that may still stop to ask. Cancel in the window installs nothing. An answer
cannot hold a comma, the format's separator, nor anything Python's
`str.splitlines()` breaks a line at (`prompts.writable`); the window
refuses both, and a kept answer holding one (a file edited by hand) is not
loaded, so it is asked again instead of failing every install. The mods'
files are read for the questions on the worker thread that writes the plan,
not on the window's.

Not done here, and still to come:
- the mod's version beside the answers (point 2): a mod whose questions
  change between versions keeps the old answers under the same key;
- the questions after a condition, which are still asked during the install
  until item 63 can recognise a question by its expected text;
- the watchdog (point 4).

**Measured** (the 105-mod corpus of point 1, the same scan, 2026-10-31): 159
components reach a question, 1,187 questions counted per component (one
question reached by several components counts for each). Only **3** are
answerable beforehand under this rule, counted per component (the batch rule
can only lower it: the corpus has no install order) (DLC Merger, EET's mod converter, EEUI
Tweaks: 1 each), and 1 component has all its questions answerable. Without
SCS, whose 1,144 are its SFO library's, reached by every component and
unread or conditional: 3 of 43. What stops the first question of each
asking component (SCS left out, 16 components): a path that could not be
followed, 8 (EET's core: `%MOD_FOLDER%/lib/bgee_dir.tph`; TDDz); a
condition, 4 (Tweaks Anthology 3176, BP-BGT Worldmap's travel times - both
skip the question when a preset answers it); asked until valid, 3 (answered,
but nothing after it); unknown text, 1 (LCA). So the order of the log alone
answers little: most questions sit under a condition that is usually true on
a fresh install. Answering those safely needs the question recognised when
it comes - by its expected text, which point 1 knows - and answered by its
key, not by its place: the next step (item 48), after which the window can
offer the questions under a condition too.

### Amendment (2026-10-31): answered by question during the install

`api.start_install` now takes the questions (`install_questions`) and the
player's answers (`load_install_answers`). When mod_installer puts a question
to this program, `prompts.match_question` looks for the batch's expected
question texts - read from the mods' files in the log's language - at the
**end** of mod_installer's window, starting a word: white space read
loosely, a `%variable%` as anything on its line (WeiDU fills it in); never a
text with fewer than 12 characters besides its variables, nor one ending in
a variable (anything after its words would match); the longest matching text
winning (a shorter one may be its tail), and two different questions
matching equally meaning no match. A stored answer is given **once per
question per batch**: asked again - a loop refusing it, or a question asked
on purpose several times - the player answers (independent review of #111,
reproduced with the real binaries: a refused answer had been given again
16 times in 40 s). A recorded answer knows its question only on a row this
program wrote (`write_install_answers`); another tool's row - answers as
asked, skipped ones left out - is handed out in order, as before. Recognised, the question is answered by its key: the player's
answer, else the log's recorded answer for that very question (taken out
of the queue wherever it is, so the others stay in step); with neither, it
is asked - a recorded answer meant for another question is never given to
it. Not recognised, it takes the next recorded answer, as before: nothing
changes for a question the texts do not cover.

So the questionnaire now offers every question answerable by question
(`install_questions`' `by_question`): its text known and recognisable as
above, one mod_installer puts to anyone at all (its choice words, below),
and no other component of its batch asking the same - also those under a
condition, after one asked until valid, or after a component that may still
ask. A component whose every question has an answer, by its place or by
question, counts as answered; no other question counts. A field left empty
is asked during the install (kept as such, so it is not offered again) -
so an answer that is just Enter (a default) cannot be given beforehand any
more; one kept as "" from before still is, until the window saves that field
again. The log's `@wlb-inputs` still carries only the answers
whose place is sure (the rules above), for other tools that read it.

**Measured with the real mod_installer 16.0.0 and WeiDU v251**
(`tests/test_real_mod_installer.py`): a question under a condition is
recognised in the real window and answered by question; when the condition
skips it, the next question gets its own answer.

**Measured, a limit of mod_installer that this does not lift**: it puts a
question to this program only when its window holds one of its choice words
or phrases (`src/config/parser_config.rs`: "choose", "select", "enter", "do
you want", "[y]es or [n]o", "is this correct?"...) or a bell character. A
question with none is never put to anyone: WeiDU waits until mod_installer's
timeout per mod, 3 hours by default, and the install then fails. Of the 42
distinct READLNs of the corpus whose text is known, **11** have none: 8 are
SCS's SFO library pausing ("press a key to continue", in its debugging
paths), 2 EET's mod converter (a developer tool), 1 DLC Merger's "Try again
(y/n)?" after a DLC it could not find. mod_installer reads its words from a
parser config (`confy`, `parser.toml` in its own configuration folder);
adding the expected texts there would make it ask them - on Linux and macOS
through the child's configuration folder, on Windows only in the player's own
folder (the known-folder API ignores the environment). That is a decision
still to take (the warn-only watchdog, point 4, will at least say it).

### Amendment (2026-10-31): the watchdog, point 4

Built in `InstallRun._pump`. It tells apart a question being put to the
player (the loop waits on the answer: nothing is said), output still coming
(alive), and **no output for longer than `SILENT_S`** with no question: then
it says so once - an `Event("watchdog")`, shown on the install page with
`!!` and in the status line - with the last five lines of output, and goes on
waiting. It never stops the install. When the last lines end with a question
the batch's mods ask (`match_question`) that has none of mod_installer's
choice words, it says that WeiDU seems to wait for an answer mod_installer
does not put to anyone, and that it will wait until mod_installer's timeout
(the limit measured above). mod_installer 12.1.1's rows of dots, which come
exactly while WeiDU is silent, are not output; an answered question's window
is no longer the last output (independent review of #115, both reproduced).

**The threshold is provisional: 10 minutes.** No real install's silences
could be measured here (no runner has the game data, and the corpus is files,
not runs). So each run measures them: the longest stretch without output in
each batch goes into `install-plan/results.json` (`"silences"`), and the
threshold is to be set from the longest ones real installs record, with a
margin. Until then a component that works silently for more than 10 minutes
(SCS's big components, EET's core on a slow disk) is said, not harmed.

---

## ADR-0050 — A rename waits out a file Windows holds for a moment

**Status:** accepted (2026-10-31). GUI-AUDIT M8 item 66.

**Context.** On Windows a file another program holds open - an antivirus
scanning what was just written or extracted, the search indexer - cannot be
renamed or replaced until it lets go: `os.replace` fails with
ERROR_SHARING_VIOLATION (32), ERROR_LOCK_VIOLATION (33) or ERROR_ACCESS_DENIED
(5), and the download, the extraction or the backup stops with it. Chriz Easy
BG met it and retries such renames (`engine/src/fs_retry.rs`, MIT, read at
508256a: 12 attempts, 10 ms doubling to 1 s, about 5.3 s). Here 11 places
renamed: 8 `os.replace`/`os.rename` (`atomic.py`, `archives.py`, `backup.py`
x2, `datasync.py` x2, `net.py`, `toolchain.py`) and 3 `shutil.move` in
`install.py`: a tp2 folded into its folder, the old copy moved to
`.backup/`, and the mod's entries moved into the mods folder one by one.
Those were worse than a refusal: when Windows refuses the rename,
`shutil.move` copies and then deletes, and a held file split the mod.

**Decision.**
- `atomic.retried(operation, budget_s=...)`: on Windows, a `PermissionError`
  whose `winerror` is 5, 32 or 33 is tried again, waiting 10 ms doubling to
  1 s, up to 12 attempts and at most `budget_s` in all; any other error, and
  every error on other systems, is raised at once. CEBG's measure, its idea;
  no code taken.
- Two budgets (review of #102). `PATIENT_S`, 5.3 s, for what runs off the
  GUI's thread: downloads, extraction, backups, data refreshes. `BRIEF_S`,
  0.15 s, for `atomic.write_text`: it also runs on the GUI's thread (the
  order page's drag, Save, the decisions), where a held file must not freeze
  the window for seconds; small files are let go quickly.
- An ERROR_ACCESS_DENIED no wait ends is raised at once: the target is a
  folder that is already there (a leftover `.old`, a backup name taken
  within one second) or a read-only file (review of #102).
- `atomic.replace`, `atomic.rename` and `atomic.move` use it, and every
  rename in the tool and the wizard goes through them. `atomic.move` renames;
  it falls back to `shutil.move` only across file systems (EXDEV), never
  because a file is held.
- A mod's folder moves from the staging folder in **one** rename (the
  staging folder is under the mods folder: one file system), never entry by
  entry. If that rename fails, the copy it replaced (moved to `.backup/`) is
  put back; if that fails too, one error says the install failed and where
  the old copy is kept. `install.py` now has 4 `atomic.move`s: the tp2
  fold, the old copy aside, the mod in, the old copy back.
- The folder keeps the mode the unpacker gave it; one its owner cannot
  write (some unpackers restore 0555) is made writable by its owner while
  it is still in staging, before the move: on POSIX a folder its owner
  cannot write cannot be renamed into another folder (the rename rewrites
  its `..`), and WeiDU must create `<mod>/backup/` in it (second and third
  reviews of #102; the test runs as a non-root user to show it).
- A test walks the tool and the wizard and fails on any `os.replace`,
  `os.rename`, `os.renames` or `shutil.move` - called, or imported by name -
  outside `atomic.py`.

**Consequences.**
- A file held for under about 5 s no longer stops a download, an
  extraction, a backup or a data refresh on Windows; one held longer still
  does, with Windows' own error. A project file written from the window
  waits at most 0.15 s, then fails as before.
- A mod is installed whole or not at all: the old copy stays or comes back.
- Measured on the test suite only: the hold is simulated (a fake operation
  raising the Windows errors); no antivirus was run.

---

## ADR-0051 — The game is closed before an install starts; a game started meanwhile is said, not stopped

**Status:** accepted (2026-10-31, GUI-AUDIT M8 item 67)

### Context

When a game, a launcher or another WeiDU is running from the game folder
while a mod is installed into it, the install can fail. The game opens
`dialog.tlk`, and WeiDU writes that file at the end of a component. On
Windows a program holding `dialog.tlk` open makes that write fail. Another
WeiDU can also write the same files at the same time.

Chriz Easy BG makes two checks (`engine/src/preflight.rs` L399, L735, MIT;
the idea only, nothing is copied):

- no running executable under the target folder;
- the talk tables open exclusively.

It makes them before the install and again before each batch. It can do so
because it starts WeiDU itself, one batch at a time.

This program does not start WeiDU: mod_installer does. Read in its 16.0.0
source, mod_installer logs `Installing mod ...` and starts that batch's WeiDU
right after it (`installers.rs` L144, `runner.rs` L198). This program learns
of a batch only from that log line, when WeiDU is already starting. There is
no point between two batches at which it could hold mod_installer back.

### Decision

1. **Before the install and before a resume**, `gamelock.problems` refuses
   to start in two cases:
   - a running program's executable is under one of the games' folders. The
     listing comes from `/proc/*/exe` on Linux, `ps -o comm=` on macOS, and
     `K32EnumProcesses` + `QueryFullProcessImageNameW` on Windows.
   - on Windows, a `dialog*.tlk` (at the root, or in `lang/*/`) cannot be
     opened for reading and writing with no sharing.

   The two refusals are told apart. "The game is running" names the
   program and its pid; "is open in another program" names the talk table.
   Each says to close it and try again, and the ConfigError carries it,
   like the other preflight refusals. There is no "install anyway": what
   stops the install is closed by the player (review of #105).
   - **Wine and Proton (Linux)**: for a Windows program, `/proc/<pid>/exe`
     is Wine's loader (`wine64-preloader`), not the game. When the loader
     is a wine binary or the command line names an `.exe`, the command
     line's first two words are read as well. A `Z:\...` path is `/...`;
     another drive is resolved through the process's `WINEPREFIX` (else
     `~/.wine`) `dosdevices` link. The working folder is not used: Wine's
     own helpers (services.exe, explorer.exe) may inherit the game's
     folder and outlive the game.
   - **A talk table held for a moment** (an antivirus, the indexer) is
     tried again, 5 times about 30 ms apart, before it is refused.
2. **At each batch during the run**, only the programs are listed again. A
   program found there is said once, as a warning in the install's output,
   and the install goes on. The warning names the program and says why
   WeiDU may fail. It cannot stop the batch, which has already started.
   Stopping would cut a component in half, which is worse than the failure
   it would prevent. The talk tables are not checked during the run: WeiDU
   itself holds them then.
3. This install's own mod_installer and WeiDU are ignored when they sit in
   the game folder. So is this program itself, by its pid and
   `sys.executable`: the Windows zip or the GUI unpacked beside Baldur.exe
   would otherwise refuse every install, naming a program the player cannot
   close because it is the one asking (review of #105).

### Consequences

- What is not seen:
  - a process this user may not inspect: another account's, which `/proc`
    refuses with EACCES and which is skipped without an error, or an
    elevated one on Windows;
  - a Wine game started through a launcher whose command line names
    neither the game's `.exe` nor a path under its folder;
  - on macOS, a game whose executable is outside the folder given, when the
    folder is an .app's `Contents/Resources` and its executable is in
    `Contents/MacOS`.
- A listing that fails refuses nothing. It is treated as nothing found,
  because refusing on a listing error would block an install with no way
  round it.
- Elsewhere than Windows nothing locks a file against WeiDU, so the
  talk-table check is Windows only.
- Item 67 as proposed asked for a check *before* each batch. That is not
  possible while mod_installer drives WeiDU, and would need this program to
  start WeiDU batch by batch itself. That is outside this item; until then,
  what item 67 still lacks is that check.

---

## ADR-0052 — A mod this tool cannot download is supplied by hand, held to a download's checks

**Status:** accepted (2026-10-31, GUI-AUDIT M8 item 68)

### Context

Some mods are published only on pages this tool cannot download from:
- Gibberlings3, Spellhold Studios and Nexus answer a datacenter with a
  Cloudflare challenge (item 57);
- weaselmods and others put the file behind a JavaScript button or a login.

The download phase marks these mods "No download found" or "Failed". The
player then had to unpack the file into the mods folder by hand, which
skipped every check made on a download.

Chriz Easy BG (`engine/src/acquire/manual.rs`, MIT; the idea only) opens
the page, lets the player pick the saved file, and takes it only if its
size and sha256 match pinned values. It neither scans nor watches a folder.

### Decision

1. **In the wizard**, a row not yet there gets two buttons:
   - *Open the mod's page* opens the URL the run's record names (http/https
     only) in the browser;
   - *Choose the saved file...* opens a file dialog.

   Nothing else is read: no Downloads folder is scanned or watched.
2. **`api.supply_download(project, mod, path)`** runs
   `download_selection(only=[mod], supplied={mod: path})`. This is the same
   run as a download (`api.run(..., supplied=)` and `Options.supplied`), so
   the mod gets the same plan entry, the same tp2 expectation (manifest
   override, then the catalogue's), the same advisories, the same state
   file and the same report. A mod no source names (an unresolved item) is
   moved into the run's items for it.
3. **The runner's `_supply` checks the file as a download is checked**
   (`_local_file`):
   - a regular file;
   - under the byte ceiling (`--max-bytes`);
   - an archive by its first bytes, so a saved Cloudflare page is refused
     as `not_an_archive`;
   - the manifest's pinned `sha256` when there is one (`checksum_mismatch`).

   `install_from_archive` then requires this mod's tp2 where WeiDU looks.
   The file is read where it is, never moved or changed. A copy already
   there is replaced and kept in `.backup/`, because the player asked for
   this mod.
4. **The state records** `origin: supplied`, the sha256 and the file's name
   (`supplied_file`). The record keeps the page as its `url`. A later run
   counts the mod as installed and verified.

### Consequences

- **The size-and-sha256 match as proposed needs a pin.** Pins exist for
  GitHub release assets (`--emit-pinned-manifest`) and for a manifest's own
  `sha256`. A Gibberlings3, SHS or Nexus mod usually has neither, so for it
  the tp2 check is what holds the file, as it holds every download. The
  sha256 it had is recorded, so a pinned manifest made after it holds the
  next install to it.
- **The recorded sha256 is trust on first use**, and is never a pin. A
  pin lives in the manifest, and a supplied file never changes it: a file
  that differs is refused with "this file is not the one pinned for this
  mod" and both hashes. The state's sha256 is a record. It becomes a pin
  only when the player writes a pinned manifest (`--emit-pinned-manifest`),
  which takes it for an entry with none and keeps an existing one: a
  supplied file that reached the state matched that pin. Until then, a
  later supply of another file for the same mod is checked by its tp2
  again, not against the first file.
- **An installer `.exe`** (some SHS and Nexus mods) is refused by
  `safe_extract`, unless the project allows self-extracting archives
  (`allow_exe`). It is never run. The GUI opens a page only for an
  `http`/`https` URL: never `file:`, `javascript:` or another scheme.
- **The hashing and the unpacking run in the page's worker thread**, as a
  download does, never on the window's thread (ADR-0048).
- **The command line has no flag for it.** It is the wizard's.
- **Not run against the gated sites**: no runner reaches them. The tests use
  a stub transport and real archives, checking that nothing is fetched and
  that the chosen file is left as it was.

---

## ADR-0053 — What each component came to: WeiDU's verdicts, held to WeiDU.log

**Status:** accepted (2026-10-31, GUI-AUDIT M8 item 69)

### Context

An install ended with mod_installer's exit code: 0, or not. That code does
not say which component failed, which went in with warnings, or which were
never reached. Items 47 (the known-issue classifier) and 53 (the
post-install report) both need that per component.

Chriz Easy BG (`engine/src/weidu/verify.rs`, `log.rs` L136-140, MIT; the
idea only) reads WeiDU's own verdicts and WeiDU.log before and after.

Measured with the real mod_installer 16.0.0 and WeiDU v251:
- mod_installer's default `--weidu-log-mode` is `autolog,logapp,log-extern`
  (`config/log_options.rs`), so it starts WeiDU with `--logapp --autolog
  --log-extern`;
- WeiDU therefore appends every run of an install to one `WSETUP.DEBUG` in
  the game folder;
- each WeiDU run is a block that opens with `WeiDU v NNNNN Log` and the
  command line (`... mod/mod.tp2 --force-install-list 0 1 ...`);
- in each block, every component has `Installing [Name]` and, when it ends,
  one of `SUCCESSFULLY INSTALLED`, `INSTALLED WITH WARNINGS` or `NOT
  INSTALLED DUE TO ERRORS` followed by the name.

### Decision

1. **`results.py` (pure, core layer) parses the debug text.** In each
   block, the command line's component numbers are taken in order by its
   `Installing [Name]` and `SKIPPING: [Name]` lines. Measured with the real
   WeiDU: a component whose REQUIRE_PREDICATE fails gets `SKIPPING: [Name]`
   and no verdict, so it does not shift the others (review of #109). Each
   verdict goes to the component it names.
   - The `Installed ~Name~` lines WeiDU saves give the exact number of each
     component it installed.
   - Where the order contradicts them (a component passed over without a
     word), only those exact numbers are kept, and a failure is left to the
     log.
   - A run cut short leaves its last component with no verdict.
2. **WeiDU.log is the authority on what is in the game.** A planned
   component added to the log during the run is installed; the debug file
   only adds "with warnings". Where the two disagree, the log wins and a
   note says so:
   - the log lists a component the debug file says failed;
   - the debug file says a component went in, but the log does not list it.

   A component in the log before the run is "already installed". One in
   neither is "not reached", or "not installed (errors)" when the debug file
   says so.
3. **`InstallRun` reads the files, never `results.py`.** Before the run, for
   each game mod_installer installs into (`phases()`, as `command()` gives
   them), it records the planned keys, the game's WeiDU.log and the debug
   file's size. After the run it reads only what was appended past that
   size, so an earlier install's debug file is never taken for this one. A
   debug file that shrank was replaced, and is read whole.
4. **The results go in `Outcome.results`** and in
   `install-plan/results.json` (`{"v": 1, "components": [...]}`), written on
   every run, empty when mod_installer cannot start. `Outcome.ok` stays the
   exit code.

### Consequences

- A component that failed, one that went in with warnings, and the ones the
  run never reached are now told apart; items 47 and 53 can build on them.
- The debug file name depends on the log mode, so it is mod_installer's
  default that this relies on. A player's own `--weidu-log-mode log X`
  cannot reach it, because this program clears mod_installer's options from
  the environment (ADR-0045). With another file, no verdicts are found and
  the log alone decides, which the note says.
- Measured with the real binaries on Linux; the WeiDU verdict strings are
  the same on every system.
- The install page lists the components that need a look (with warnings,
  errors, not reached, the two sources disagreeing) and counts them all; a
  note that says nothing went wrong ("no word on it in the debug file",
  "already installed before this run") is not listed.

---

## ADR-0054 — A mod that changes how the game starts is told, with the program to start

**Status:** accepted (2026-10-31, GUI-AUDIT M8 item 71)

### Context

Once EEex is installed, the game must be started through its loader. The
game's own program crashes. A player who starts the game as before blames
the install. The wizard does not say so today.

Read in Bubb13/EEex at a6d21ab (v1.3.1, MIT):
- the main component, `BEGIN @1 LABEL ~B3-EEex-Main~` (number 1), copies
  the loader into the game folder (`COPY ~EEex/loader~ ~.~`);
- the quick-menu core, #0, copies no loader;
- the README: "The game must be started using InfinityLoader.exe / EEex.exe
  after installation; any attempt to start the game using the vanilla
  executable will result in a crash";
- InfinityLoader replaces EEex.exe from v0.9.0;
- the support table: Windows native, Linux "via Proton / Wine", macOS
  "via CrossOver".

Chriz Easy BG's `docs/curation/components/EEEX.md` L28-29 says the same.

### Decision

1. **`launch.py` (pure, core layer) keeps a table of loaders**, keyed by
   tp2 file name and the components that install one. Today it has one
   entry: `eeex.tp2` component 1 → InfinityLoader.exe.
2. **`launch_advice({log: text}, platform)` reads the planned logs.** For
   each log that installs such a component it gives, once:
   - the program to start;
   - why;
   - off Windows, what EEex needs there: the Windows game through Proton
     or Wine on Linux, or through CrossOver on macOS, because the native
     Linux and macOS games cannot start it.
3. **`api.install_launch_advice(plan_dir, platform=None)`** reads
   `plan_dir`'s planned logs and returns those entries. It writes nothing.
   The install page says them after a successful install, for the game that
   is played (in EET the EET game's log), and only when this run did not
   report the loader's component as not installed or not reached.

### Consequences

- A player who installs EEex is told, after the install, which
  program starts the game, and on Linux or macOS what that requires.
- Only EEex is listed, because only it was read. Mods that need EEex and do
  nothing without it (BGEE Graphics Enhanced, BG2 HD; G3 thread 40143) are
  not flagged: their tp2 names were not checked. They are left for item 53's
  report.
- The table follows EEex's numbering; if upstream renumbers its main
  component, the entry must follow.

---

## ADR-0055 — Room and the right WeiDU are checked before installing, as warnings

**Status:** accepted (2026-10-31, GUI-AUDIT M8 item 49)

### Context

An install can stop half-way for reasons that could have been seen
beforehand:
- the disk fills up;
- the backup does not fit;
- the WeiDU in use is older than a mod requires.

Infinity Mod Runner and BWS-NG check room before they start. Nothing here
did: `install_run.preflight` refuses a wrong game folder or a missing
program, but says nothing of space or WeiDU's version.

### Decision

`readiness.findings` (shell layer, under the runner) and
`api.install_readiness(games, mods_dir, weidu, backups_dir=None)` return
warnings in words. They never refuse: the player decides.

1. **The backup's room is exact.** `backup.size(game_dir)` is what
   `create()` copies: the files at the root, `override/` and the talk
   tables. A test holds the two equal. If the free space where backups go
   (`shutil.disk_usage`, on the nearest folder that exists) is less, the
   warning names both sizes.
2. **The install's room is an upper estimate, said as one.** On each game's
   drive the estimate is the staged mods' bytes (what WeiDU may copy into
   the game) plus what a backup copies (what WeiDU may back up before it
   overwrites, into each mod's backup folder in the game).
2b. **What lands on one drive is added up** (review of #114). In EET,
   BG:EE, EET and the backups folder are often on one drive. The needs
   (each game's install estimate, the backup) are grouped by device
   (`os.stat(...).st_dev` of the nearest existing folder) and their sum is
   compared with that drive's free space. The staged mods are counted once
   per drive, because each mod goes into one game. The warning lists what
   lands there. The backup part is exact. The game part counts only what a
   backup copies: the root files, `override/` and the talk tables, never
   `data/` or `movies/`. It therefore overestimates by at most the size of
   `override/` and the talk tables, not by the size of the game.
3. **WeiDU's version.** `--version` (toolchain.version_of) is compared with
   the version this program is tested with (`toolchain.VERIFIED`, 25100),
   and with the highest `WEIDU_VER >= N` (or `> N`, as N + 1) found in a
   staged tp2, tpa or tph. The warning names the file. A WeiDU that does
   not answer gets no warning, since `toolchain.find` reports it already.
4. **`install_run.preflight` is not changed**, so it stays clear of the
   other session's watchdog work. The install page shows these warnings
   next to `install_known_issues`.

### Consequences

- A full disk or an old WeiDU is said before the install, not discovered
  half-way through.
- It walks each game folder and the mods folder: measured at 0.9 s for
  40,000 files in `override/` (Linux, folder cached); a cold disk or
  Windows is slower. A window calls it off its own thread (ADR-0048).
- A drive whose free space cannot be read is not measured. That covers a
  network path, a drive letter that is not there (the walk up to the
  nearest existing folder ends at its root), and an `OSError` from
  `disk_usage`. Nothing is said about such a drive, and it is never an
  error.
- The install's room is only an estimate. WeiDU can need more (a mod that
  unpacks archives into the game) or much less (most copy a few files).
  The warning says it is an estimate.
- "The newest WeiDU" is the one this program is tested with, not the
  latest release: no network call is made here.
- How many mods test `WEIDU_VER` was not measured (no unpacked corpus in
  this session). The check reads WeiDU's own variable, as mods use it.

---

## ADR-0056 — The Linux bundles are measured on the distributions players run, after each release

**Status:** accepted (2026-11-01)

### Context

The wizard's and the command line's Linux zips are built on ubuntu-24.04,
held to Debian trixie's glibc, and started once inside debian:trixie
(ADR-0043 amendment). Players also run Fedora Atomic (Bazzite), Arch
(CachyOS) and newer Ubuntus.

The CI and release workflows install five system libraries for Qt
(`libgl1 libegl1 libxkbcommon0 libfontconfig1 libdbus-1-3`) on an
ubuntu-24.04 runner, which has the rest already; the README named none.
Those cover the offscreen start that CI checks. Read with `ldd` on the 4.0 bundle on an Ubuntu 24.04 host,
Qt's xcb plugin (the one an X11 or XWayland desktop uses) needed eight
libraries that list leaves out: `libxcb-cursor`, `-icccm`, `-util`,
`-image`, `-keysyms`, `-render-util`, `-xkb` and `libxkbcommon-x11`. No
check had measured what a desktop start needs, or what each distribution
calls it.

### Decision

1. **`tools/distro_libs.sh`** runs as root in a fresh container of a
   distribution:
   - it reads with `ldd` the libraries the bundle's Qt links to and the
     system lacks, for a headless start (offscreen), an X11/XWayland
     desktop (xcb) and a native Wayland session;
   - it asks the distribution's own package index which package ships each
     one (`apt-file`, `dnf repoquery --whatprovides`, `pacman -F`), and
     installs them;
   - it starts the wizard offscreen (`--check`), before and after;
   - it runs the command line's `--version` and `--help`.

   Nothing comes from a hand-written list: the output names each missing
   soname and the package that filled it.
2. **`.github/workflows/bundles-distros.yml`** runs the script on a
   published release's Linux zips. release.yml dispatches it for each tag
   it publishes (its publish uses `github.token`, whose `release` event
   starts no workflow); it also runs on a release published by hand, on a
   pull request that changes it or the script (measuring the latest
   release), and by hand for any tag. It runs in fedora:latest, archlinux:latest, ubuntu:24.04,
   ubuntu:latest and debian:trixie. A job fails if the wizard does not
   start offscreen once its packages are in, or if the command line does
   not answer. A desktop (xcb) library still missing after its package is
   a warning.
3. **It is a workflow of its own, not a job of release.yml.** It measures
   five systems whose images change under it, and a library one of them
   renames must not hold a release back. release.yml keeps gating the
   floor, Debian trixie, as before.

### Consequences

- The per-distribution package list in the README and docs/GUIDA-TEST-REALE.md
  comes from a measurement of the published bundles, and is measured again
  for every tag release.yml publishes.
- What runs in a container is not a desktop. The xcb and Wayland sets are
  measured by `ldd` (every library resolves) but not started: the first
  real window on each distribution is the real-test guide's to confirm.
- Images on Docker Hub and the ECR mirror limit anonymous pulls. A job that
  cannot pull fails, named, and runs again by hand.

---

## ADR-0057 — mod_installer is told the plan's questions through its parser config

**Status:** Accepted (2026-11-01). Amends ADR-0049's measured limit.

### Context

mod_installer 16.0.0 puts a line of WeiDU's output to this program only when
the line looks like a question to it (`src/config/parser_config.rs`,
`string_looks_like_question`, read from the release's source). It checks
**each line on its own**, ASCII-lowercased and trimmed:

- a bell character makes it a question;
- otherwise a progress word ("installing", "creating") makes it not one;
- otherwise one of its choice phrases or words does.

WeiDU waits on a question with none of these until mod_installer's
timeout, 3 hours per mod, and then the install fails. Lines that are not
UTF-8 are dropped before this check (`src/raw_reciever.rs`).

mod_installer reads these words from a parser config. confy 2.0.0 loads it
as `parser.toml` from an app folder resolved by etcetera 0.10. It uses the
file only when `metadata.mod_installer_version` equals its own version;
otherwise it writes its defaults over the file.

ADR-0049 said that on Windows the folder could only be the player's own,
because the known-folder API ignores the environment. That was wrong. Read
from etcetera's source: its Windows strategy reads `APPDATA` from the
environment first, and asks the known-folder API only when it is unset.

### Decision

1. **One config per install, never the player's.** `install_run.start`
   writes the file under `PROJECT/install-plan/mod_installer-config/`
   (`mi_parser.write`). Only mod_installer's environment points at it:
   - Linux and macOS: `XDG_CONFIG_HOME` (etcetera uses its Xdg strategy on
     macOS too), so the file is `<dir>/mod_installer/parser.toml`;
   - Windows: `APPDATA`, so the file is
     `<dir>/mod_installer/config/parser.toml`.

   `HOME` is left alone. The player's own `parser.toml`, if they have one,
   is neither read nor changed.
2. **Contents.** The file holds mod_installer 16.0.0's defaults, copied from
   its source and compared in a test with the file the real binary writes.
   To them it adds one choice phrase for each expected question
   (ADR-0049's texts) that mod_installer would not ask. The phrase
   (`mi_parser.phrase`) comes from the question **as WeiDU prints it**
   (`readln.Prompt.raw`: its lines and spaces as written; the `text` the
   questionnaire shows has its spaces collapsed, and a phrase taken from it
   matched no printed line when the question had two lines or two spaces -
   review of #120, reproduced with the real binaries). Any line starts
   mod_installer collecting the question (`src/parser.rs`: the lines after
   it are appended until the output is quiet), so the phrase is the longest
   piece of the **last** line that has a piece of at least `MIN_TEXT` (12)
   letters. A rule or heading line ("*****", "=====") is never chosen while
   a later line says more: a phrase that mod_installer meets in other output
   makes that output a question too (second review of #120). A piece lies
   between the line's `%variables%` and any non-ASCII character (an NBSP
   before "?" in a UTF-8 text is left out), ASCII-lowercased as Rust's
   `to_ascii_lowercase` does. A line holding a progress word gives no
   phrase.
3. **Version.** The file carries `mod_installer_version = "16.0.0"`, the
   version the bundle carries. A different mod_installer would write its own
   defaults over it (measured), so `install_run.version_of` asks the
   program first (`--version`) and writes nothing for another version: the
   install then counts no phrase as added. mod_installer loads, and on a
   mismatch rewrites, its parser config **before** it reads its arguments
   (`src/main.rs`, measured): `--version` itself is run against the
   install's folder (`install_run.version_of`) or a scratch folder
   (`toolchain.version_of`, which `toolchain.find` and readiness use and
   which, before this, touched the player's own file).
4. **What counts as asked.** `mi_parser.asked` replaces the whole-text
   check in two places, the questionnaire's `by_question` (api) and the
   watchdog's "a question mod_installer does not put to anyone". A question
   counts as asked when one of its lines looks like a question to
   mod_installer, with variables left out, or when its phrase is in the
   install's config.

### Measured

- **The real binary.** mod_installer 16.0.0 was built from the release's
  source tarball:
  - it loads the generated file and leaves it unchanged;
  - with `15.0.0` in the file, it replaces the file with its defaults.
- **A real install** with WeiDU v251 (`tests/test_real_mod_installer.py`).
  A mod asks "How many extra kits should be installed?", which has no
  choice word:
  - with the config, the question reaches this program and is answered by
    its key;
  - with the phrase removed, the install waits until the test cancels it
    after 120 s.
- **A real install, three forms** of that question: one line, a heading line
  before it, two spaces inside it. Each is answered by its key; before the
  review's fix the last two waited.
- **The corpus** (105 mods, `tools/readln_census.py`, which now records the
  raw text). It has 37 distinct known question texts, 19 of them on more
  than one line. 11 have none of mod_installer's words on any line:
  - 8 "press a key to continue" lines from SCS's SFO library;
  - 2 questions from EET's converter (menus: the phrase is the last option
    line with 12 letters, not the bare "2. Yes");
  - DLC Merger's "Try again (y/n)?" (the phrase is the piece before
    `%dlc_name%`).

  Each of the 11 gets a phrase from one of its printed lines: the 8 SFO
  lines ("... press a key to continue") whole; for EET's two
  menus, the last option line with enough letters ("1. no (skips usually
  unneeded changes)", "2. yes (add evaluate_buffer everywhere ...)"); for
  DLC Merger, `could not find dlc "`. That each one then stops the real mod
  (SCS, EET, DLC Merger) is **not** measured: the real test runs synthetic
  mods. ADR-0049 counted 42 distinct texts; this
  count dedups differently.

### Consequences

- A known question no longer waits 3 hours just because of its wording.
  Unknown texts (a `%variable%` printed whole, text not resolved) are still
  not covered; the watchdog still reports them.
- **False positives.** A line printed elsewhere that holds a phrase is sent
  to this program as a question when the output goes quiet. If no expected
  text ends that window, it is put to the player - or, where the log still
  holds unused recorded answers, given the next one, which WeiDU (not
  reading) keeps for its next READLN: a wrong answer to a later question.
  Phrases hold at least 12 letters and come from the last line that says
  enough, never a rule or heading before it; the config holds the whole
  plan's phrases for every batch. Not measured on a real install.
- **Inherited variable.** WeiDU, and whatever a mod runs, inherits
  `XDG_CONFIG_HOME` or `APPDATA`. No mod in the corpus was checked for
  reading it. A tool started by a mod that keeps settings there would find
  an empty folder. This is not measured.
- **Version lock.** The defaults are pinned to 16.0.0. A new mod_installer
  needs its defaults compared again; the test against the real binary's
  file is what catches a change. The questionnaire (`by_question`) assumes
  the phrases will be in place, as they are with the mod_installer the
  bundle carries: with another, or when the file cannot be written, the
  install writes none and the watchdog says so, but the questionnaire has
  already offered those questions.
- **Charset.** mod_installer drops a whole output line that is not UTF-8
  (`src/raw_reciever.rs`). When WeiDU prints a mod's text in another
  charset (a cp1252 .tra and no HANDLE_CHARSETS: mostly the original games,
  not the Enhanced Editions), a line with an accented letter never reaches
  the check, whatever its phrase: such a question still waits, and the
  questionnaire still counts it. Not covered. For UTF-8 text the ASCII
  piece is matched; a question with no ASCII piece of 12 letters gets
  none.

---

## ADR-0058 — A bundle's children do not see its libraries, and its libraries ship with their licences

**Status:** accepted (2026-11-01)

### Context

GUI-AUDIT item 61 left two gaps in the bundles (reviews of #70).

1. **The DLL folder on Windows.** PyInstaller's bootloader calls
   `SetDllDirectoryW` with the bundle's `_internal`. A process the bundle
   creates (git, gh, 7-Zip, unrar, mod_installer, the browser) inherits
   that DLL directory and can load the bundle's OpenSSL or libffi instead of
   its own. `childenv` already did the same job on Linux and macOS, where
   the bootloader's change is in the environment (`LD_LIBRARY_PATH`). On
   Windows it is not in the environment, and it belongs to the whole
   process, not one thread.
2. **Licence texts.** The texts of the libraries the bundles carry were
   missing. They were read from the published 4.1.0 zips:
   - the Linux command line carries 11 libraries from the Ubuntu 24.04
     build system: libssl and libcrypto (Apache-2.0), libffi, libbz2,
     liblzma, libsqlite3, libz, libzstd, libuuid, libtinfo, and
     **libreadline (GPL-3.0)**;
   - the Linux wizard carries about 90, among them GTK 3 and its stack
     (pulled in by Qt's gtk3 platform theme), krb5, libgcrypt (LGPL),
     libsystemd and readline;
   - neither Linux zip had a text for any of them. The wizard did not even
     have Python's licence;
   - on Windows, python.org's LICENSE.txt (676 lines) already carries the
     third-party texts (bzip2, libffi, the Apache License, zstd...), and
     the command line shipped it; the wizard did not.

### Decision

1. **`childenv.popen` and `childenv.run`** create every child under one
   process-wide lock:
   - on Windows, in a bundle, the DLL directory is cleared just while the
     child is created, then put back at once;
   - the wizard's own loading (Qt's plugins, Python's extension modules)
     sees the DLL directory as before. Clearing it for good would have
     changed that loading, which was not measured;
   - outside a Windows bundle, `run` is `subprocess.run` itself;
   - every call site uses them: auth, archives, toolchain, and
     mod_installer's start in install_run. The wizard's "open the page"
     runs under `api.starting_program()`.
2. **Measured in the real bundle.** On Windows, cli_bundle.py builds a
   probe with PyInstaller and runs it. A child started through childenv
   must see no DLL directory, and the bundle must keep its own; otherwise
   the build stops. This runs in release.yml's bundle jobs, which also run
   (publishing nothing) on every pull request that touches `packaging/**`,
   as #121 did. On that run (job 124812676391) the measurement was:
   - the parent's DLL directory: `...\probe\_internal`;
   - a plain child: the same `_internal`, so the child inherits it;
   - a child started through childenv: an empty DLL directory;
   - the parent afterwards: its own `_internal` again.

   A unit test on Windows CI measures the inheritance itself, both ways.
3. **readline is excluded from both bundles.** It is GPL-3.0 and serves an
   interactive prompt neither program has; without the module, the library
   is not collected. Each bundle's check stops a build that still carries
   `libreadline*` or `libgdbm*`.
4. **Every library taken from the build system ships with its licence.**
   `add_system_licences`, used by both bundles:
   - lists the shared libraries outside Python's own and outside the
     wheels' folders. PySide6's Qt and ICU are covered by NOTICE-Qt.txt,
     including the links to them;
   - asks dpkg which package installed each one, and copies that package's
     `/usr/share/doc/<package>/copyright` into `licenses/system/`;
   - writes NOTICE-system-libraries.txt with each library, its package's
     exact version, and where that version's source is (Launchpad for
     Ubuntu, sources.debian.org for Debian). That source address is what
     the GPL and LGPL ask for;
   - copies the common licences those copyright files name
     (`/usr/share/common-licenses/<X>`) into
     `licenses/system/common-licenses/`. Debian's copyright files point at
     them without their text (review of #121): Apache-2.0, GPL-2,
     LGPL-2.1, MPL-1.1 and 9 more in the wizard's local build;
   - stops the build when a library has no owning package, no copyright
     file or a named licence with no text, and when a Linux build finds
     libraries but has no dpkg to ask. It does not ship without a
     licence;
   - finds each library's package through the path the loader resolves it
     to (`ldconfig -p`, where PyInstaller took it), then by name.
5. **Both bundles carry Python's LICENSE.txt**, the wizard's too.

### Consequences

- The libraries, versions and copyright files are the **build system's**:
  ubuntu-24.04, the release runner. They are not the player's
  distribution's. What a player's system must add for the bundle to
  start is ADR-0056's measurement; this record is what the zip itself
  carries.
- Measured locally (Ubuntu 24.04, a standalone Python 3.14): the wizard's
  bundle carries copyright files for 70 packages and no readline. The
  dpkg strictness caught Qt's and ICU's links on its first run; they are
  now recognised as the wheel's.
- The macOS zip has no dpkg. Python's LICENSE.txt is its record, as
  before; what that build carries from macOS itself was not measured.
- GTK 3 still ships in the Linux wizard, now with its licences. Leaving
  Qt's gtk3 platform theme out would drop it (tens of MB), but that
  changes how the wizard looks on GNOME, so it is the owner's call and not
  done here.
- The lock is held only while a child is created. For a program started
  with Popen that is milliseconds. For the browser it is as long as
  `QDesktopServices.openUrl` takes, which goes through ShellExecute:
  hundreds of milliseconds, possibly seconds. During that time another
  thread waits to start its child. A Qt plugin the main thread loads in
  that window would see no DLL directory; this has not been observed.
- The LGPL and GPL source is offered as an address: Launchpad or
  sources.debian.org, at the exact version shipped. It is not attached to
  the release as mod_installer's is, because for about 70 packages that
  would add hundreds of MB to every release. Attaching it is the owner's
  call if a distribution host is not enough.

---

## ADR-0059 — What krion64 saw of a mod is shown as its words, with its source and its day

**Status:** accepted (2026-11-01)

### Context

GUI-AUDIT item 51. krion64's data carries two kinds of text that the
wizard did not show.

- **Its daily repository scan**, `version_cache.json`, gives every
  repository a few fields. Measured live on 2026-11-01, it covers 690
  repositories:
  - `body`: the release notes, the release author's markdown;
  - `pushed`: the day of the last push;
  - `archived`;
  - `release_name`.
- **Its per-mod records** carry notes. Measured on 814 records (local copy
  of 2026-10-22):
  - `no` (notes) in 813;
  - `rq` (requirements) in 21;
  - `ic` (incompatibilities, in words) in 46;
  - `eet_compat` ({ver, place}) in 84;
  - `in` in 17 and `rec` in 10.

All of it is third-party text, typed by hand. The scan is also a snapshot:
"archived" is true as of the day krion64 scanned, not necessarily today.

### Decision

1. **Text, never markup.** Release notes and krion64's notes are read as
   strings:
   - control characters other than newlines and tabs are removed, as
     are the bidirectional marks and overrides (U+200E/F, U+202A-202E,
     U+2066-2069); a lone CR becomes a newline;
   - the tag and the release date go through the same filter, with a
     length cap;
   - release notes are cut at 1,500 characters, notes at 1,000, with " ...";
   - in the mod's details they are HTML-escaped whole, newlines kept;
   - no link and no image is ever made from them. The details panel opens
     no links either (`setOpenLinks(False)`, as before).

   A test passes `<a href>`, `<img src>` and `javascript:` through both,
   and they come out as literal text.
2. **Every line names its source and its day.**
   - For what the scan saw of a repository (archived, last push, release
     notes), the day is that entry's own `checked`: "Archived on GitHub,
     according to krion64's scan of 2026-03-14". It can be months before
     the cache's commit. In the live data, 52 of 690 entries were last
     checked in March 2026 and 1 in May, against a commit of October
     (review of #123).
   - For krion64's notes (no, rq, ic, EET), the day is the commit the
     community-data cache fetched (`sources.json`).
   - When the data is not the cache's, or the cache has no record, the line
     says the day is not known.
   - The "krion64" label is about where the data comes from. A caller that
     passes its own `mod_db` or releases to `mod_choices` gets the label
     with no day; the wizard never does this.
3. **Shown:** notes, requirements, incompatibilities, EET (version and
   place), and of the repository the last push, "archived", and the release
   notes with their release's name and date.
4. **Not shown:** `in` and `rec` are left out. They appear in only 17 and
   10 of 814 records, too rare to rely on.
5. **The wizard only.** These go into `mod_choices`' entries. The CLI's
   mods-v1 document is unchanged.

### Consequences

- On the local data (1,045 mods, the EET list), 502 mods show what the
  scan saw of their repository: 456 with release notes, 7 archived. 689
  show krion64's notes.
- The notes are krion64's and the release authors' words. The wizard
  shows them; it neither checks nor follows them.
- A long changelog is cut. The full text is on the release's page, which
  the wizard does not link from that text.
- The same rule covers the rest of the wizard (follow-up of #123). The
  helpers are in `iemod_fetch_gui/text.py`:
  - `plain_tip` for tooltips, spaces kept;
  - `critical`, `question` and `information` for message boxes, in plain
    text;
  - QLabels that show names or messages are set to `PlainText`.

  A test fails on a tooltip that is neither a fixed string nor
  `plain_tip`, in every page. pages/install.py follows the same rule:
  - WeiDU's question to the player, the mod's own text, goes through
    `get_text`, a QInputDialog whose prompt is plain text (review of #124);
  - the confirmation (known issues, readiness, mods' names, paths) and the
    prerequisites tooltip go through `question` and `plain_tip`;
  - its labels were already plain text, except two that show only our own
    names.
