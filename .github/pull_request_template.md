## What this changes

<!-- One or two sentences. What behaviour is different after this? -->

## What made it necessary

<!-- The failure, the report, the counterexample. If a test found it, say which
     test and what input it shrank to. -->

## How it is verified

- [ ] `make check` passes locally (ruff, mypy, import-linter, pytest)
- [ ] A test fails without this change and passes with it — named here:
      `tests/...::test_...`
- [ ] No new runtime dependency outside `requirements/runtime.txt`, and none added there without a test that fails first (ADR-0043)
- [ ] The layering holds (`lint-imports`)

## If this touches a design decision

- [ ] `docs/ADR.md` records it, or an existing ADR is amended
- [ ] `CHANGELOG.md` has an entry under `Unreleased`
- [ ] `README.md` describes the change (new flags, outputs, numbers)

## If this touches a security boundary

<!-- Transport, credential handling, archive extraction, path construction. -->

- [ ] There is a test asserting the boundary **rejects**
- [ ] `docs/SECURITY-MODEL.md` still describes reality

## Anything left undone

<!-- Say so here rather than leaving it to be discovered. -->
