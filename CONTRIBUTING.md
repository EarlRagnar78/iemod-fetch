# Contributing

Thanks for looking. This project exists because a single-file downloader was
guessing, and everything below is in service of one property: **it never guesses,
and when it does not know, it says so.**

## The one rule

> A change that makes the tool guess is rejected, however convenient it is.

No repository-name mutation, no "search GitHub and take the first hit", no
"the archive has exactly one `.tp2`, so it must be the right one", no inferring a
mod's game from its name. Every one of those was in the original script, every
one produced a wrong result on real data, and `docs/AUDIT.md` has the evidence.
An unresolvable entry is reported with a reason and a suggestion. That is
slower, and it is correct.

## Before you open a pull request

```bash
python3 -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pre-commit install

make check          # or, without make:
ruff check . && mypy && lint-imports && python3 -m pytest -q
```

CI runs exactly these, plus the test matrix and the security scans. Nothing in
CI is a surprise you cannot reproduce locally.

## What a change needs

**A test that fails without it.** Not "a test"; a test that goes red when you
revert the code. If you cannot write one, say so in the pull request and explain
why — sometimes that is the honest answer, and it is better than a test that
passes either way.

**The right kind of test.** `docs/TESTING.md` says which:

| The change is… | Write… |
|---|---|
| a bug fix | a regression test naming the defect, in the module's own test file |
| a parser or comparator change | a **property** in `tests/test_properties.py` — a law, not an example |
| a security boundary | a test that the boundary *rejects*, in `test_*_security.py` |
| new CLI behaviour | an end-to-end test in `test_cli_end_to_end.py`, offline |
| a design decision | an **ADR** in `docs/ADR.md`, and the code that follows from it |

**No new runtime dependency.** The runtime is standard library only (ADR-0002)
and `.importlinter` enforces it. An operator downloads one `.pyz` and runs it
with whatever Python their game machine has. Developer tooling is free to depend
on whatever it likes.

**Layering respected.** The functional core (parsers, rules, ordering,
reporting) may not import the imperative shell (network, subprocess,
filesystem). `lint-imports` will tell you before CI does.

## Writing style in the code

The comments in this codebase explain **why**, and usually name the real
incident that made the code look like that — "this returned 1 for both orders,
so a default-branch rename marked rules stale". Keep that. A comment restating
what the line does is noise; a comment naming the failure it prevents is the
only documentation that survives a refactor.

## Adding a mod that will not resolve

Do not add a special case in the resolver. In order of preference:

1. Pin the real URL in your manifest entry.
2. If the archive genuinely ships a different `.tp2` than the WeiDU folder, use
   the `expect_tp2` field — a per-mod, explicit, reviewable override.
3. If a whole hosting site is unreachable by design (MediaFire is behind
   JavaScript), document it in `docs/GUIDE.md` under the known limits and leave
   it manual.

## Rule and catalogue data

BigWorldSetup Next-Generation, krion64 and LCC data are **never vendored**. They
are passed by path and refreshed with `git pull`. If a rule is wrong, fix it
upstream; if you cannot, write a dated entry in your suppressions file. A rule
hardcoded into this repository is a rule nobody can update.

## Commit messages and pull requests

State what changed and what made it necessary. If a test found the bug, say
which test and what input it shrank to — that is the most useful sentence in the
whole message.
