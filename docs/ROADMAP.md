# Roadmap and revision plan

Three phases, in the order this project's own delivery discipline requires:
**assess what is actually true, then build, then prove it.** Each item says what
"done" means, because a roadmap entry without a completion test is a wish.

Status as of the repository-readiness revision (2026-09-10).

---

## Phase 1 — Audit and assessment

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
- **Running WeiDU.** ADR-0003. The tool stages and plans; installation is
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
