# Architecture

## The shape, in one sentence

A **functional core** that parses, compares and decides, wrapped in an
**imperative shell** that talks to the network, the filesystem and other
processes — and a gate in CI that stops the two mixing.

## Why this shape and not "clean architecture"

The honest answer first: this codebase would be *worse* with the usual pattern
apparatus. It has no database to abstract, one delivery mechanism, and no
plausible second implementation of anything. A `ManifestRepository` interface
with exactly one implementation, an `AbstractResolverFactory`, or a service
layer wrapping a pure function would each add a file, a level of indirection and
a test double, and would prevent no defect that has ever occurred here.

What has caused defects is different, and it is what the structure defends
against:

| The defect class | What defends against it |
|---|---|
| A decision that depends on the network, so it can only be tested with a mock that encodes the author's assumptions | The decision lives in the core and takes data |
| A pure helper trapped inside an impure module, reached by a function-local import to dodge a cycle | `import-linter`, which found exactly this and produced `urls.py` |
| A third-party import in a rarely-taken branch, breaking a single-file artifact on someone else's machine | `import-linter` plus `tools/check_stdlib_only.py` |
| A rule matched against the wrong key, silently matching nothing | One naming function, `naming.normalize_key`, and a property test that the ordering key and the rule key agree |

So: functional core / imperative shell, "parse, don't validate" at the
boundaries, typed errors, dataclasses as values. That is the whole paradigm
budget, and each item is there because a real failure argued for it.

## The layers

`.importlinter` is the source of truth; this is the readable version of it.

```
                          cli
                           │
                         runner
                           │
        ┌──────────────────┼──────────────────┐
    resolvers          install            orgindex          ← imperative
        └──────────────────┼──────────────────┘
                          net
                           │
                archives  ·  auth
─────────────────────────────────────────────────────────
                  plan  ·  report                          ← functional
                       conflicts
                        ordering
                         rules
             manifest · catalogues · moddb
        weidu · tp2 · modmeta · versions
                        urls
                       naming
                       errors
```

Four contracts are enforced, and CI fails on a violation:

1. **The core imports nothing from the shell.** Every module below the line is
   testable with no network, no temporary directory and no clock.
2. **The runtime imports no third-party package** (ADR-0002).
3. **Nothing imports `cli`** except the entry point.
4. **The stack above holds**, layer by layer.

## What each module is for

### The core

| Module | Responsibility | Why it is pure |
|---|---|---|
| `errors.py` | the typed error vocabulary | a failure's *kind* is a value, so callers branch on the type rather than on a message |
| `naming.py` | `safe_component`, `normalize_key`, `matches_tp2` | the path-safety predicate is the security boundary for every filename that reaches the disk |
| `urls.py` | repository from URL, forum interstitials, Dropbox `dl=1` | URL *facts*, extracted from `resolvers` when the architecture gate refused the import |
| `versions.py` | version parsing and comparison, returning `None` for unrankable pairs | the ordering must be a strict weak ordering or `sorted()` is undefined |
| `weidu.py` | the WeiDU log: the statement of desired state | attacker-adjacent input; every unreadable line becomes a warning, never an exception |
| `tp2.py` | the installed mod's own version and supported games | the mod is the authority on itself |
| `modmeta.py` | `.iemod` / Project Infinity `[Metadata]` | the developer's own ordering claims outrank any third-party rule |
| `manifest.py` | the download catalogue, validated on load | "parse, don't validate": a `ModSource` cannot hold an unsafe folder name |
| `catalogues.py`, `moddb.py` | LCC, BWS-NG and krion64 records | other people's JSON, read as data, never executed |
| `rules.py` | order / incompatibility / dependency rules and the checker | one rule vocabulary, three upstream formats |
| `ordering.py` | the install-order solver and the log writer | a topological sort is a function of its inputs |
| `conflicts.py` | component-level findings with provenance and remedy | takes an `Install`, returns findings |
| `plan.py` | which manifest entry serves which WeiDU folder | matching, not fetching |
| `report.py` | the run report and its renderers | formatting is not I/O |
| `config.py` | the INI file and the precedence rules | |
| `pinning.py` | turning an actual run into a pinned manifest | |

### The shell

| Module | Responsibility | The boundary it owns |
|---|---|---|
| `net.py` | HTTP, retries, streaming download | HTTPS-only including redirects; the credential goes to GitHub hosts and nowhere else; size ceiling; `sha256`; magic-byte sniff |
| `archives.py` | detect and extract | no member escapes the root; no symlinks; entry, size and ratio ceilings; one member at a time with the resolved path re-checked |
| `auth.py` | find a GitHub credential | environment, `gh`, git credential helper, device flow — never echoes a token |
| `install.py` | stage a verified mod directory | never deletes an existing directory; `--force` moves it aside |
| `orgindex.py` | trusted-owner repository listing | a disk cache with a TTL |
| `resolvers.py` | one manifest entry to one URL | refuses to guess; reports what it found instead |
| `runner.py` | orchestration and concurrency | |
| `cli.py` | argument parsing, config precedence, wiring | the only place that writes to a stream |

## Things worth knowing before changing something

**`normalize_key` is load-bearing.** Rules, catalogues, manifests and logs all
name mods slightly differently. Every one of those names is folded by the same
function, and a property test asserts the ordering key agrees with it. Two
normalisations would mean rules that silently match nothing — the defect that
made every `EET_end` rule invisible before ADR-0017.

**A mod's identity is its `.tp2`, not its folder.** `eet\EET.TP2` and
`eet\EET_end\EET_end.tp2` share a folder and sit at opposite ends of the
install.

**One WeiDU log is one game install.** Merging an EET log with a pre-EET BGEE
log invents order violations between mods that never met. `check_all` and
`plan_order` take a list of installs, never a merged one.

**`Optional` means unknown, not equal.** `versions.compare` returns `None` for
pairs it cannot rank, and every caller must treat that as "I do not know". A
caller that reads `None` as `0` will silently decide that a snapshot and a
release are the same version.

## Concurrency

A thread pool in `runner.py`, sized by `-j`. Downloads are independent; the
shared state is the `State` file, written once at the end. There is no async,
no event loop and no shared mutable structure across workers — the parallelism
is embarrassingly parallel I/O, and anything more would be complexity looking
for a problem.

## Determinism

Two builds of one commit produce a byte-identical `.pyz`, and CI checks it. The
ordering solver breaks ties on an explicit key rather than on set or dict
iteration order, and `PYTHONHASHSEED=0` in CI would surface it if that ever
stopped being true. A tool whose output changes between runs cannot be verified
by the person downloading it.
