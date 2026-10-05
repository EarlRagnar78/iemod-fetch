# Delivery plan

Three phases. Phase 1 is complete and its artefacts are in this directory;
Phases 2 and 3 need decisions from you (see the questions at the end).

---

## Phase 1 — Audit / assessment  ✅ complete

**Objective.** Establish what the script actually does, with evidence, before
changing anything.

| Step | Method | Result |
|---|---|---|
| Confirm the inputs | `md5sum` on both uploads | identical file, 683 lines |
| Profile the manifest | 148 entries: hosts, schemes, field coverage | 9 third-party hosts, 3 × `http://`, 0 integrity fields |
| Profile the WeiDU logs | 796 component lines, 148 mod folders | 0 version strings recorded |
| Join the two | folder ↔ catalogue key | 138 exact, 30 case-only, 10 name mismatches |
| Prove each defect | `tests/test_legacy_characterization.py` executes the original | 13/13 defects confirmed |

**Exit criterion (met).** Every finding in `AUDIT.md` maps to a passing
characterization test or a measurement over your real data. No finding rests on
reading the source alone.

**Pre-requisites that turned out to matter.** The audit changed materially once
the manifest and WeiDU logs arrived — S2-5 (40 mods installed under unusable
directory names) is invisible from the code alone.

---

## Phase 2 — Development / implementation

### 2a — Rewrite  ✅ complete

`iemod_fetch/` — stdlib-only package, 13 modules, ~1,500 lines.

| Module | Responsibility |
|---|---|
| `naming` | filesystem-name safety; **strict** tp2 identity |
| `weidu` | WeiDU.log parser → desired state |
| `manifest` | catalogue schema validation |
| `plan` | the join; alias resolution; suggestions |
| `net` | scheme policy, host-scoped credentials, size caps, checksums, retries |
| `auth` | credential resolution (env / file / `gh` / optional own-app device flow) |
| `archives` | magic-byte detection; contained extraction |
| `install` | staging, verification, atomic swap, backups, state file |
| `resolvers` | GitHub releases; landing pages — no guessing |
| `runner`, `report`, `cli` | orchestration, JSON/console reporting, argparse |

### 2b — Adopt it against your install  ← *your next action*

1. **Dry run, no writes:**
   ```bash
   python3 -m iemod_fetch -w WeiDU.log -w WeiDUBGEE.log \
       -m mod_downloads.json -t ./Mods --dry-run \
       --json-report plan.json
   ```
   Read `plan.json`. Expect ~10 unresolved before aliases.
2. **Apply the shipped aliases** (`aliases.json`, 9 entries, reviewed):
   `--aliases aliases.json` → 147/148 resolved.
3. **Decide on `HPS_PORTRAITS_PROJECT`** — no catalogue source exists; either add
   one to the manifest or drop it from the desired set.
4. **Real run** with `--allow-http` if you want the 3 cleartext entries, and
   `--allow-exe` only if a mod ships an SFX installer you trust.
5. **Hand `./Mods` to Infinity Mod Forge / Project Infinity** for installation.
   This tool deliberately stops at "verified mod folders on disk" — see the
   scope question below.

### 2c — Lock the versions  ✅ tooling complete, ← *you run it*

`--emit-pinned-manifest PATH` writes a catalogue with `release_tag`, `asset` and
`sha256` filled in from what the run actually fetched and verified. Run it once
on your machine (this environment's proxy blocks `api.github.com`, so I could not
produce the pinned file for you), commit the result, and pass it as `-m`
thereafter. A tampered or silently re-rolled release then fails the run instead
of installing — `test_a_pinned_digest_that_no_longer_matches_fails_the_run`.

```bash
python3 -m iemod_fetch -w WeiDU.log -w WeiDUBGEE.log \
    -m mod_downloads.fixed.json -t ./Mods --aliases aliases.json \
    --refresh --emit-pinned-manifest mod_downloads.pinned.json
```

### 2d — Catalogue corrections  ✅ complete

`tools/apply_corrections.py` + `tools/corrections.json` take the manifest from
three cleartext `http://` entries to zero, and fix `FowlWish`, whose URL pointed
at a GitHub user profile rather than a repository. Three of the four are
high-confidence repository migrations; the fourth (`haerdalisromance`) is only a
scheme change and is explicitly marked unverified — shsforums.net is unreachable
from this environment. Verify it locally.

### 2e — Single-file build  ✅ complete

`python3 build.py` produces a 34 KB dependency-free `iemod-fetch.pyz`, restoring
the original script's copy-one-file portability. The build compiles the package
and runs the archive before declaring success.

---

## Phase 3 — Testing / validation

### 3a — Automated (in place)

```
170 passed in 1.02s     # offline, no network, no 7z/unrar required
```

| Suite | Tests | Invariant |
|---|---|---|
| `test_legacy_characterization` | 13 | each original defect is real and reproducible |
| `test_naming` | 47 | traversal refused; strict matching identifies 148/148 real mods |
| `test_weidu` | 6 | real logs parse with zero warnings; colons are not versions |
| `test_manifest` | 10 | unsafe keys fatal; empty manifest fatal; http warned |
| `test_net_security` | 29 | credential scope, redirect stripping, caps, checksums, retries |
| `test_archives_security` | 15 | zip-slip, tar escape, symlinks, bombs, exe policy |
| `test_install` | 13 | verification strict; destination never destroyed |
| `test_plan` | 11 | real-data join; suggestion ≠ decision |
| `test_resolvers` | 22 | no search fallback; off-site links not auto-selected |
| `test_cli_end_to_end` | 8 | idempotence, exit codes, conflict protection |

Run: `python3 -m pytest -q`

### 3b — Manual acceptance, against your real install

These cannot be automated here because they need the network and the game:

1. **Dry-run diff.** `--dry-run --json-report` before and after `--aliases`;
   confirm 147 resolved and the one manual entry is the expected one.
2. **Cleartext gate.** Run without `--allow-http`; confirm the 3 pocketplane/SHS
   entries report `MANUAL` rather than downloading.
3. **Credential containment.** Run with a token and `tcpdump`/`mitmproxy` (or
   simply a token scoped to nothing) and confirm no `Authorization` header
   reaches `weaselmods`/`gibberlings3`/`shsforums`.
4. **Idempotence.** Run twice; the second run must download nothing and exit 0.
5. **Conflict safety.** Hand-edit a file in an installed mod, re-run without
   `--force`: the edit must survive and the mod must report `CONFLICT`.
6. **WeiDU acceptance.** Point Infinity Mod Forge at `./Mods` and confirm it
   resolves all 147 folders — in particular the 30 case-sensitive ones
   (`eet`, `eeex`, `BGGO`, `SOS`, …) which the old script got wrong on Linux.
7. **Restore drill.** Delete a mod folder, re-run, confirm clean re-install.

### 3c — CI

`python3 -m pytest -q` plus a nightly `--dry-run --allow-manual --json-report`
against the real manifest. The dry run is a link-rot canary: when a mod host
reorganises or a repo is renamed, resolution starts failing and you learn about
it before an install, not during one. Exit codes are meaningful now (0 ok,
1 failures/unresolved, 2 configuration), so this is a two-line pipeline.
