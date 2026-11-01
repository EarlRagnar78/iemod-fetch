# Roadmap and revision plan

Three phases, in the order this project's own delivery discipline requires:
**assess what is actually true, then build, then prove it.** Each item says what
"done" means, because a roadmap entry without a completion test is a wish.

Status as of the 2.2.0 install-time revision (2026-10-21). The 2.1.0 and
2026-09-10 revisions follow it, unchanged, as the record of how it got here.

---

# Revision 2026-10-21 — v2.2.0

## Phase 1 — Audit: what an EET install actually needs

Checked against primary sources, not memory:

| Question | Source | Answer |
|---|---|---|
| How does WeiDU know the game? | WeiDU `src/tppe.ml` | marker resources: `oh1000.are` BG:EE, `oh6000.are` BG2:EE, `eet.flag` EET (override/ or chitin.key) |
| Does everything end up on the BG2:EE engine? | EET readme, EET.tp2 | yes: the EET core imports BG:EE+SoD into the BG2:EE folder, writes `override/EET.flag`, and from then on WeiDU calls that game EET; everything after the core installs there |
| What may come before the EET core? | EET readme; BWS-NG `games/eet.json` | a clean BG2:EE, optionally EEFixPack |
| What does the BG:EE side need? | EET readme; DlcMerger README | BG:EE + SoD v2.6.6.0; on GOG/Steam DlcMerger first; only mods in EET's `compatibility.tbl` |
| Is the plan's check right? | the real WeiDU v251 on synthetic folders | it was not, in two places: see *Fixed* in the 2.2.0 changelog |

## Phase 2 — Development (done in 2.2.0)

- Game folders verified (`--bgee-dir`, `--bg2ee-dir`) — ADR-0026
- A refusal an order fixes is fixed by the order (EEFixPack before the core)
- `tests/test_real_weidu.py` and a CI job with the pinned WeiDU and mod_installer

### Still open, highest value first

| ID | What remains | Done when |
|---|---|---|
| F5 | **Real game data.** The synthetic folders prove WeiDU's flags, not the merge itself, the patch level, or mod bodies that fail on content. | a self-hosted runner with owned BG:EE+SoD and BG2:EE v2.6.6.0 runs the mock plan nightly (DlcMerger, EEFixPack, EET, EET_end are the minimum) |
| F7 | **Patch level** is not read from the folder (EET needs v2.6.6.0). | a version source the engine itself writes is identified and tested on real installs; until then it stays "not checked" |
| F8 | **Compound tp2 predicates** (`A AND (B OR C)`) are counted, not evaluated. | an evaluator for the WeiDU predicate grammar, checked against real WeiDU on synthetic folders |
| F9 | **Mod bodies** can still fail for reasons no flag states (a missing resource, a `FAIL` deep in a function). | only real game data finds these (F5) |
| F10 | **The EET merge check** (`compatibility.tbl`) is simulated, not run by WeiDU in the test: it reads the BG:EE `WeiDU.log` through EET's interactive path. | the excerpt EET drives that path non-interactively in the real-WeiDU test |
| F11 | **A plan moved to another machine** keeps working only through env vars; the verified folders are not recorded with it. | `RESOLUTION.json` records the verified folders and the installer warns when run against different ones |

Unchanged from 2.1.0: F1–F4, F6 (now partly done: CI pins mod_installer by
commit; the emitted script does not yet verify the binary), E1–E6.

## Phase 3 — Validation for v2.2.0

- [x] Each new behaviour has a test seen failing first; both bugs above were
      found by the real-WeiDU test before any fix
- [x] Real WeiDU v251 + mod_installer (Cargo 16.0.0, commit `3b6827a`) install
      the resolved mock plan end to end
- [x] Gates: ruff, mypy (33 modules), import-linter (4 contracts), bandit, zizmor
- [x] CI green on the pull request, 3-OS matrix plus the real-WeiDU job
- [ ] Tags `v2.1.0` and `v2.2.0` pushed; the draft releases published by a human

---

# Revision 2026-10-20 — v2.1.0

## Phase 1 — Audit

### 1.1 Measured, before and after

Same machine, same commands (`make check`, `make cover`, `make audit`), plus
the suite on Python 3.9 and 3.14 via `uv`:

| | Before | After |
|---|---|---|
| Tests | 586, **1 failing** | 713, all passing (1 Windows-only) |
| Branch coverage | 88% | 90% |
| ruff | **5 errors** (ISC004, new rule) | clean |
| mypy | **config refused** by mypy 2.x (`python_version = 3.9`) | clean |
| Python 3.14 (newest release, not in CI) | **4 failures** | passing, now in CI |
| Python 3.9 | passing | passing |
| bandit / architecture contracts | clean / 4 kept | clean / 4 kept |
| Defects open that this revision found | 11 | 0 |

**The honest reading:** the September revision ticked "every gate passes from a
clean clone". A clean clone a month later failed four gates without a line of
code changing — an unpinned linter, a type checker dropping a Python version,
and an interpreter (3.12+) whose new warning met `-W error`. "Green" is a
statement about a toolchain on a date, not about the code.

### 1.2 What the comparison found

Compared against Born2BSalty's
[Infinity Orchestrator](https://github.com/Born2BSalty/Born2BSaltys_Infinity_Orchestrator)
(Rust, the closest tool in this domain) and the maintainer's own repositories.

- **The Orchestrator is weaker where iemod-fetch is strongest.** It picks the
  archive format from the extension, has no decompression-bomb limits and skips
  bad member names silently. Nothing to port from its extraction code.
- **It is stronger on packaging reality**, and four of its ideas were adopted
  in this revision as fixes: folding a root-level `setup-<mod>.tp2` into its
  folder; WeiDU's `win-`/`lin-`/`osx-` asset prefixes; naming GitHub rate-limit
  exhaustion; and loopback socket tests — which immediately found the most
  serious defect of the revision (a truncated download accepted as complete).
- **The maintainer's other repositories** (`AiAgentInfrastructure`,
  `linux-file-librarian`, `biological-data-validator`) have a weaker CI than
  this one. The one practice worth taking is `AiAgentInfrastructure`'s scheduled
  functional job against the real network — which is item 2.2-A below, already
  planned.

### 1.3 Assumptions

- Python 3.9 stays supported although it is past end-of-life (October 2025):
  the operator's game machine decides, not the developer's. Dropping it is a
  major-version decision (see 2.3).
- 7-Zip-dependent behaviour was verified against 7-Zip 23.01 on Linux; the
  Windows `7z.exe` listing format is assumed identical (same codebase).

## Phase 2 — Implementation

### 2.1 Done in this revision

See `CHANGELOG.md` § 2.1.0 — the defects, each with a test that failed first,
and two features that close the path from logs to a running game:

- **`--resolve-conflicts`** (was 2026-09-10 item E, `--fix-conflicts`): applied
  to the plan, only where the rules decide, re-verified (ADR-0021).
- **`--emit-installer`**: sh + cmd scripts handing the plan to mod_installer +
  WeiDU, EET in one run (ADR-0022). Checked by executing the generated script
  with the real mod_installer 16.0.0 binary and a recording stand-in WeiDU.

### 2.1b Done on 2026-10-21 — component level and languages

- Component-level order (ADR-0023, closes 2026-09 item C), WeiDU SUBCOMPONENT
  clashes, tie handling in resolution (ADR-0021 amendment), preferred language
  with fallback (ADR-0024).
- The order checker's 34 false positives on the real install, found by
  measuring before and after against the real BWS-NG and krion64 data.

**Community comparison** — what each tool does, and whether iemod-fetch adopts it:

| Capability | BWS-NG | krion64 | Infinity Orchestrator | mod_installer | iemod-fetch |
|---|---|---|---|---|---|
| Split a mod across the order | hand-curated per-game list of `mod:comp` (stratagems in 4 runs) | per-component `co[].cat` | by hand (drag blocks) | installs the log as given | **automatic**, from krion `co[].cat` + component rules; adopted krion's data, re-verified |
| Conflict handling | blocks; the user unselects | advisory (hard/partial/soft) | flags | none | report always; opt-in auto-resolve only where a rule pins the side; ties/whole-mod to the user — **more automatic than any of them, by design narrower** |
| Mutually exclusive options | `MUC` component type | — | — | — | detected from the log's `Group -> Option`, keep the last |
| Mod metadata (tp2 REQUIRE/FORBID) | copied by hand into the rule files | — | parsed from the tp2; required component first | WeiDU enforces it at install time | **parsed from the staged tp2** (Orchestrator's reading) + FORBID as order, warned; mutual FORBID incompatible |
| Install simulation / EET merge check | — | — | — | stops at the first refusal | **`--simulate`**: game switches BG2EE→EET at the core, EET's `compatibility.tbl` read; refusals reordered when EET documents the order, else removed |
| Game folder check | required files (`chitin.key`, `Baldur.exe`; SoD: its exe or a `sod-dlc` archive) + `engine_mode` in `engine.lua` | n/a (catalogue) | not checked here | none found in its source | **WeiDU's own GAME_IS markers** (what decides the install) + EET's needs: clean BG2:EE, SoD merged or DlcMerger planned, no EET.flag yet |
| Testing against the real WeiDU | not found in its repository | n/a | not checked here | its own unit tests | **real WeiDU + mod_installer on synthetic folders, in CI** |
| Language | ordered list, first match; tp2 LANGUAGE + alias map | one language, then English | one locale, then English; probes `--list-languages` | passes the log's `#lang` | **BWS-NG's model adopted**: ordered list, tp2 LANGUAGE, alias map (minus its dutch→German bug) |



| ID | Defect | Done when |
|---|---|---|
| F1 | WeiDU writes `// Name: v17.1` (unspaced colon); only the IMF spelling `Name : v17.1` yields a version. No consumer reads it today, so a heuristic parse would add risk for nothing. | a consumer exists **and** the tail is matched against a strict version grammar with negative fixtures from the real logs (`Margarita for BG: Enhanced Edition`, `Main Portraits: Vanilla`) |
| F2 | No download resume: a 1.5 GB mod cut at 95% restarts from zero (up to 3×). | `Range` resume with `If-Range` on the ETag, falling back to a full fetch on `200`; covered by a loopback test |
| F3 | Two WeiDU folders served by one URL are downloaded twice, concurrently. | downloads are keyed by URL; one transfer, N installs |
| F4 | `--force` moves the old folder to `.backup/` and the user's `stratagems.ini`/`cdtweaks.ini` stay behind. | an explicit per-mod `config_files` manifest list is carried over (never inferred) |
| F5 | The installer path has never run real WeiDU against real game data in CI (no runner owns the games). | a self-hosted nightly job with legally owned BGEE/BG2EE installs a 5-mod EET plan and checks both `WeiDU.log` files against the plan |
| F6 | mod_installer is a manual download. | `--emit-installer` names the pinned release and its sha256, and the script verifies the binary it is given |

### 2.3 Next — enhancements, highest value first

| ID | Enhancement | Source | Never-guess check |
|---|---|---|---|
| E1 | **Archive cache keyed by sha256.** Archives are deleted after install; a failed run or `--refresh` re-downloads everything. Keep them, reuse only on a recorded or pinned hash. | Orchestrator `archive_skip.rs` | reuse by name alone is forbidden |
| E2 | **Staleness probe** for landing-page and direct links (HEAD, then `Range: bytes=0-0`; compare ETag → Last-Modified → size). | Orchestrator `probe_remote_file` | facts from the server, not inferred |
| E3 | **Ordered `asset_prefer` list** in the manifest, for releases the platform prefix does not disambiguate. | Orchestrator `pkg_windows`/`pkg_linux` | explicit, per mod |
| E4 | **Cache GitHub release lists** with a TTL, to stay under the 60/h anonymous quota on a 148-mod run. | Orchestrator `github_release_list.rs` | — |
| E5 | **`AGENTS.md`** stating the never-guess rule, with a test that it exists and names `CONTRIBUTING.md`. AI-assisted contributions are now the norm. | `AiAgentInfrastructure/tests/agents-md` | — |
| E6 | **Drop Python 3.9** - superseded by ADR-0043 (2026-10-23): one Python version, 3.14, for 4.0.0; the CLI ships as a bundle too (GUI-AUDIT M6). | — | decided by the owner |

The 2026-09-10 items below (A–F) remain open and keep their priority; A (live
GitHub API contract tests) is still the largest untested surface.

## Phase 3 — Validation

### 3.1 How this revision was validated

- Every fix: the test was written first and **observed failing** for the stated
  reason before the code changed (the 7z preflight additionally against a real
  7-Zip 23.01, because a header line in its listing would have rejected every
  legitimate 7z).
- Full suite on Python 3.9, 3.13 and 3.14; ruff, mypy, import-linter, bandit.
- One regression introduced and caught inside the revision: the connection-leak
  fix called `HTTPError.close()`, which raises on Python 3.9 for an error built
  without a body. The 3.9 run caught it before commit.

### 3.2 Acceptance for v2.1.0

- [x] All gates green on 3.9, 3.13, 3.14
- [x] Each `Fixed` entry in the changelog has a test that was seen failing first
- [x] No runtime dependency added (ADR-0002)
- [ ] CI green on the pull request across the 3-OS matrix (Windows is where the
      `..\` file-name fix matters most)
- [ ] Tag `v2.1.0` pushed after merge, release attestation verified

---

# Revision 2026-09-10 — repository readiness


## Phase 1 — Audit and assessment (2026-09-10)

### 1.1 What was measured

| | Result |
|---|---|
| Tests | 586, offline, ~13 s |
| Branch coverage | 88% (floor 85%) |
| mypy | clean across 27 modules |
| ruff | clean |
| bandit | 0 high, 0 medium (was 2 high) |
| Architecture contracts | 4, all kept (1 was broken) |
| Runtime dependencies | 0 |
| Real-install validation | 148 mods, 796 components, two WeiDU logs |

### 1.2 What the assessment found

Four defects that the existing 561-test suite did not catch, each found by a
technique the suite did not have:

1. **`compare` was not antisymmetric** — `master` vs `main`, `alpha` vs `a`,
   `rc` vs `pre` each compared as *newer than the other*. `is_newer` was true in
   both directions, so an upstream renaming its default branch could mark a rule
   stale on the rename alone. *Found by:* property-based testing, first run.
2. **`extractall` was handed a member list after validation** — the names
   validated and the paths the standard library resolves were two separate
   facts. *Found by:* bandit, as B202 high.
3. **A manifest invariant was an `assert`** — stripped by `python -O`, so the
   pinned-manifest generator could emit a manifest its own loader rejects.
   *Found by:* bandit, as B101.
4. **`catalogues` reached into `resolvers` through a function-local import** to
   dodge a cycle — a pure function trapped in an impure module. *Found by:*
   the architecture contract.

Plus two test-hygiene failures (leaked file handles) surfaced by promoting
warnings to errors, and 16 typing defects, one of which was a live `NameError`
in the extraction path introduced minutes earlier.

**The honest reading:** the test suite was good at the behaviour it was written
for and blind to whole classes of defect. Adding techniques mattered more than
adding tests.

### 1.3 Pre-conditions and assumptions

Stated because they shape everything below:

- The repository is **new and separate** from `rumblingstone`; the tool shares
  no domain with that campaign repository.
- The maintainer is one person. Every process below has to be worth its cost to
  one person, which is why mutation testing reports and does not gate.
- The runtime stays standard-library-only. This is a promise to an operator
  running the tool on a Windows gaming machine, not a preference.
- Rule data stays in upstream repositories, never vendored.
- Live GitHub API behaviour has **never been verified from CI** — the
  development sandbox cannot reach `api.github.com`. This is the single largest
  untested surface.

---

## Phase 2 — Development and implementation

### 2.1 Done in this revision

| Item | Done means |
|---|---|
| Packaging | `pip install -e ".[dev]"` works; `iemod-fetch` is on `PATH`; wheel and sdist build |
| Licence, changelog, conduct, contributing, security policy | present and specific to this project, not boilerplate |
| Issue and pull-request templates | the resolution-failure template asks for the output that makes a test writable |
| `pyproject.toml` tool configuration | every ignored rule carries the reason it is ignored |
| Architecture contracts | 4 contracts in `.importlinter`, enforced in CI |
| Property-based tests | 19 properties over parsers, predicates and the comparator |
| CI | lint, types, architecture, 3 OSes × 2 Pythons, coverage floor, stdlib-only run, reproducible build |
| Security workflow | bandit, pip-audit, CodeQL, zizmor |
| Release workflow | SBOM, Sigstore provenance, draft release, PyPI via OIDC — no stored secret |
| Nightly workflow | mutation testing, 20k-example property run, upstream rule-data drift |
| `docs/` | ARCHITECTURE, TESTING, SECURITY-MODEL, RELEASING, ROADMAP alongside the existing AUDIT, ADR, PLAN, GUIDE |

### 2.2 Next — highest value first

**A. Live GitHub API contract tests.** *(largest real risk)*
A nightly job with a read-only token that resolves ten known mods against the
real API and asserts the resolver's assumptions: the release-asset shape, the
404 on `releases/latest` for a repository with no releases, the zipball
redirect. Everything about GitHub is currently tested against a hand-written
double that encodes what I *believe* the API does.
*Done when:* the job runs nightly, is allowed to fail without blocking anyone,
and a shape change opens an issue automatically.

**B. Fuzzing `archives.py` and the parsers.**
Hypothesis generates structured input; a real fuzzer (Atheris, or
`hypothesis.binary()` against the zip and tar readers) generates malformed
bytes, which is what a hostile archive is.
*Done when:* a corpus is committed, the nightly job runs it for a fixed budget,
and any crash becomes a regression fixture.

**C. Component-level ordering.**
The planner sorts at mod granularity, as Project Infinity's sorting order does.
A rule constraining one component of a mod against another component of the same
mod is reported and not solved.
*Done when:* the solver accepts component-level constraints and the plan splits
a mod's components across the order where a rule requires it — or an ADR records
that WeiDU's own installation model makes this impossible, which is a real
possibility.

**D. Tighten mypy module by module.**
`disallow_untyped_defs` is off because turning it on across 27 modules at once
is a 130-signature mechanical diff that hides real changes.
*Done when:* the core modules are strict, with a per-module override list that
only shrinks.

**E. `--fix-conflicts` (dry-run only).**
The conflict report names the narrowest remedy. It could emit the *edited* pair
of logs with those components removed — as a proposal to review, never applied.
*Done when:* the output is a diff against the plan, and nothing is written
without the operator naming the file.

**F. Windows end-to-end job.**
The matrix runs the suite on Windows; nobody has run a real install there in CI.
*Done when:* a job stages three mods into a temporary directory on a Windows
runner and asserts the tree.

### 2.3 Explicitly not planned

- **A GUI.** Project Infinity is the GUI. This is the thing that feeds it.
  *Withdrawn 2026-10-21:* a PySide6 wizard that ends by installing is now in
  scope, after the CLI is complete. See [GUI-AUDIT.md](GUI-AUDIT.md) and
  ADR-0029 to ADR-0031.
- **Running WeiDU.** ADR-0003, superseded by ADR-0029 for the install phase
  of the GUI (milestone M4). The tool stages and plans; installation is
  someone else's job and mixing the two makes both harder to reason about.
- **Vendoring rule data.** A rule inside this repository is a rule nobody can
  update.
- **A runtime dependency, for any reason.**
- **Async.** The work is embarrassingly parallel I/O; a thread pool is the right
  size of tool.

---

## Phase 3 — Testing and validation

### 3.1 The gates, and what each one is for

| Gate | Runs | Blocks a merge | The class of defect it exists for |
|---|---|---|---|
| `ruff` | every push | yes | mutable defaults, dead code, shadowed builtins |
| `mypy` | every push | yes | `Optional` where it cannot be handled; wrong attribute |
| `import-linter` | every push | yes | layering violations, third-party creep |
| pytest, 3 OSes × 2 Pythons | every push | yes | behaviour |
| Branch coverage ≥ 85% | every push | yes | untested regions |
| Stdlib-only run | every push | yes | the ADR-0002 promise, checked as the operator experiences it |
| Reproducible build | every push | yes | the artifact matching the source |
| bandit, pip-audit, CodeQL, zizmor | push + weekly | no | security-shaped mistakes, advisories |
| Mutation testing | nightly | no | tests that execute without asserting |
| 20k-example properties | nightly | no | the rare counterexample |
| Upstream rule-data drift | nightly | no | someone else's schema change |

### 3.2 Acceptance criteria for the repository being "ready"

- [x] Every gate passes from a clean clone with `pip install -e ".[dev]"`
- [x] The suite runs with **nothing** installed but `pytest`
- [x] Two builds of one commit are byte-identical
- [x] No secret is required by any workflow that runs on a pull request
- [x] Every ignored lint and skipped security rule carries its reason in-file
- [x] The architecture document describes what `import-linter` enforces
- [x] `SECURITY.md` describes boundaries that have tests asserting they reject
- [ ] A release has actually been cut and its attestation verified end to end
- [ ] The live GitHub API has been exercised from CI at least once

The last two cannot be honestly ticked from a development sandbox that has no
network access to `api.github.com` and no repository to release into. They are
the first two things to do after the first push.

### 3.3 How to tell if this is working

Six months from now, the questions worth asking:

- Did a defect reach an operator that one of these gates could have caught? If
  so, which gate was missing, and was it missing on purpose?
- Is the mutation report being read, or has it become a file nobody opens? A
  gate nobody reads should be deleted, not left to rot.
- Has anyone added a runtime dependency? If the contract held under pressure, it
  was worth having.
- Did the nightly rule-data job give useful notice of an upstream change, or
  only noise?
