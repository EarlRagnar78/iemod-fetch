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

None of those would have been written as an example. Six techniques are used
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
Hypothesis is absent, because the runtime is standard library only and
`python3 -m pytest` must work with nothing installed.

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
| Tests | 586 |
| Branch coverage | 88% (floor: 85%) |
| Architecture contracts | 4, all kept |
| mypy | clean, 27 modules |
| ruff | clean |
| bandit | 0 high, 0 medium |
| Runtime dependencies | 0 |
