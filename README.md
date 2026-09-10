# iemod-fetch

[![CI](https://github.com/gsamuele78/iemod-fetch/actions/workflows/ci.yml/badge.svg)](https://github.com/gsamuele78/iemod-fetch/actions/workflows/ci.yml)
[![Security](https://github.com/gsamuele78/iemod-fetch/actions/workflows/security.yml/badge.svg)](https://github.com/gsamuele78/iemod-fetch/actions/workflows/security.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Runtime dependencies: 0](https://img.shields.io/badge/runtime%20dependencies-0-brightgreen)](docs/ARCHITECTURE.md)

Downloads and stages Infinity Engine mods for WeiDU / Project Infinity, driven by
a `WeiDU.log` (what you want installed) and a `mod_downloads.json` catalogue
(where to get it) — then plans a rule-compliant install order and reports which
component fights which. Standard library only at runtime.

It replaces `fetch_mod_extended_final_complete_ultimo4.py`. See `docs/AUDIT.md`
for why, `docs/ADR.md` for the design decisions, `docs/GUIDE.md` to use it.

## Install

```bash
# One file, no dependencies — the way most people should use it.
python3 build.py            # -> ./iemod-fetch.pyz
./iemod-fetch.pyz --help    # POSIX;  py iemod-fetch.pyz --help  on Windows

# Or as a package.
pip install iemod-fetch     # then: iemod-fetch --help
```

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

## Quick start

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

```bash
git clone --depth 1 https://github.com/RiwsPy/lcc-docs ~/lcc-docs

# use it at run time as a fallback + advisory source
python3 -m iemod_fetch -w WeiDU.log -t ./Mods -c ~/lcc-docs/db/mods.json

# or, better, bake the results into your manifest once
python3 tools/enrich_from_lcc.py -i mod_downloads.json \
    -c ~/lcc-docs/db/mods.json -o mod_downloads.enriched.json
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
contains the right `.tp2`. The catalogue is never bundled and never fetched
automatically — you pass the path.

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
* **Install mods.** It produces verified mod folders, and — with `--plan-order` —
  the order to install them in. Running WeiDU stays with Infinity Mod Forge or
  mod_installer.
* **Fix an installed game.** `--plan-order` writes an install plan for a FRESH
  install. WeiDU installs in file order; changing the order after the fact means
  reinstalling.
* **Resolve an incompatibility.** Reordering cannot make two mods that must not
  coexist coexist. Those are reported; which one to drop is your call.

## Layout

```
iemod_fetch/     the tool
legacy/          the original script, kept so its defects stay reproducible
tests/           586 offline tests: characterization, example, property-based
tests/data/      your real manifest and WeiDU logs, used as fixtures
aliases.json     the 9 reviewed folder -> catalogue-key mappings
docs/            INDEX.md, GUIDE.md, ARCHITECTURE.md, TESTING.md,
                 SECURITY-MODEL.md, ADR.md, AUDIT.md, PLAN.md,
                 ROADMAP.md, RELEASING.md
```

## Tests

```bash
python3 -m pytest -q      # 586 passed, no network, ~14s
```

## Planning the install order

```bash
git clone --depth 1 https://github.com/Selphira/BigWorldSetup-Next-Generation.git
git clone --depth 1 https://github.com/krion64/krion64.github.io.git

python3 -m iemod_fetch --check-only \
  -m mod_downloads.json \
  -w WeiDU.log:EET -w WeiDUBGEE.log:BGEE \
  --rules BigWorldSetup-Next-Generation/data/rules \
  --rules krion64.github.io/data/mods \
  --order-catalogue krion64.github.io \
  --plan-order ./plan
```

Writes `plan/WeiDU.log` and `plan/WeiDU-BGEE.log`: the same components you have,
sorted so every order rule is satisfied, and then checked against those rules
before the claim is made. `--reassign-phase` also moves a mod between the two
logs when the catalogue says it belongs to the other install phase — off by
default, because that changes which game the mod installs onto.

The same run prints a **component conflict report**: which component of which
mod fights which component of which other mod (or of itself), with the upstream's
own evidence grade and source, and the narrowest fix — "deselect stratagems
#4115", not "these two mods conflict". Order findings the plan already resolves
are marked fixed rather than repeated. Add `--conflict-report conflicts.json`
for the full machine-readable version, `--show-advisories` for the unverified
observations withheld by default.

See ADR-0016 for why both databases are used, ADR-0017 for what the plan does and
does not promise, and ADR-0018 for how conflicts are narrowed to components.

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pre-commit install

make check      # ruff · mypy · import-linter · pytest — exactly what CI gates on
make cover      # with the branch-coverage floor
make audit      # bandit · pip-audit
```

| Gate | State |
|---|---|
| Tests | 586, offline, ~13 s |
| Branch coverage | 88% (floor 85%) |
| mypy | clean, 27 modules |
| ruff | clean |
| bandit | 0 high, 0 medium |
| Architecture contracts | 4, all kept |
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
