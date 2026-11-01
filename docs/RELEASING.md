# Releasing

## What a release is

A git tag `vX.Y.Z`, and everything else is automated. The tag is the only manual
step, and there is no release script anyone has to run on a laptop with the
right credentials.

## Versioning

Semantic versioning, where **the public surface is the CLI** — its flags, its
exit codes, and the schema of `--json-report` and `--conflict-report`. The
Python API is internal and can change in a patch release.

- **Major** — a flag is removed or changes meaning; a JSON field is removed or
  its type changes; the tool starts refusing something it used to accept.
- **Minor** — a new flag, a new report section, a new catalogue format read.
- **Patch** — a fix, with no change to what a correct invocation produces.

A rule-data change is never a version bump: rule data lives in other people's
repositories and is refreshed with `git pull`.

## Cutting one — there is no tagging step

A release is a pull request. Nobody tags by hand (ADR-0027):

```bash
# 1. The changelog: move Unreleased into a dated heading, `## [2.4.0] - YYYY-MM-DD`.
# 2. The version, in two places that must agree:
$EDITOR iemod_fetch/__init__.py     # __version__ = "2.4.0"
$EDITOR pyproject.toml              # [project] version
# 3. Green locally, then open the pull request as usual.
make check && make cover && make audit && make build
```

Merging it is the release. The push to `main` changes `CHANGELOG.md`, so the
release workflow runs `tools/release_plan.py`. It reads the newest `## [X.Y.Z]`
section, and if `vX.Y.Z` does not exist yet it picks the commit to release: the
main-line merge where `__version__` first became X.Y.Z, so the pull request's
review fixes are in and nothing merged later is. Then, in order:

1. re-runs the entire CI gate (Linux and Windows), including the real-WeiDU
   job; macOS runs in `macos.yml` and is informational, not part of the gate;
2. builds that commit: sdist, wheel and `.pyz`, after checking that its
   `__version__` matches the tag; records `SHA256SUMS`; writes a CycloneDX SBOM;
   and builds the wizard without Python (ADR-0040): a PyInstaller folder on
   Linux and Windows, started once unzipped with `--check`,
   zipped as `iemod-fetch-gui-<os>-<arch>.zip` and added to `SHA256SUMS`; the
   command line the same way, run once unzipped with `--version` and `--help`,
   as `iemod-fetch-cli-<os>-<arch>.zip` (`packaging/cli_bundle.py`; job `cli`).
   Its Linux zip is built on `ubuntu-24.04`, refused if any file in it needs a
   glibc newer than 2.41 (Debian trixie, the minimum platform), and started
   once more inside `debian:trixie`; the wizard's Linux zip is held to the same
   glibc and started there with `--check`, after Qt's system libraries. The
   macOS bundles are `release-macos.yml`'s, each built and attached only when
   the release lacks it, which the release starts for its tag
   (job `macos-bundle`): usually minutes later, else at its six-hourly check, it
   is built from the tag, attested and attached with its own `.sha256`;
3. attests build provenance through Sigstore keyless signing;
4. **creates the tag `vX.Y.Z` and publishes the GitHub release**. The notes are
   that changelog section plus the verification commands;
5. publishes to PyPI through OIDC trusted publishing. This step is opt-in: it
   runs only once the repository variable `PYPI_PUBLISH` is `true`, and it is
   still gated by the `pypi` environment.

The workflow creates the tag itself, with its own `GITHUB_TOKEN`. A tag pushed
with that token starts no workflow, so creating the tag elsewhere would leave
nothing to build it. A version that is already tagged is skipped, which makes
re-runs and edits to old changelog sections harmless.

**When nothing shipped has changed** since the version commit (only CI, docs,
tests), the head of `main` is tagged instead: the artifacts are identical, and
it is the one commit `GITHUB_TOKEN` is always allowed to tag.

**An older version without a release** (v2.1.0 was merged before this
existed) sits on a commit whose workflow files differ from `main`'s, and
`GITHUB_TOKEN` can never create such a tag (it cannot hold the `workflows`
permission). The workflow stops at the planning step and says so. Two ways
out, either is enough:

```bash
# A. push the tag yourself...
git tag -a v2.1.0 -m "2.1.0" 0173b5d && git push origin v2.1.0
```

...then *Actions → Release → Run workflow* with `version` = `2.1.0`: an
existing tag named explicitly is released on its own commit with today's
workflow. (The tag push itself starts the workflow file of the tagged commit,
which for 0173b5d is the old one that cannot run; that run fails and can be
ignored.)

B. Or add a repository secret `RELEASE_TOKEN` (a fine-grained token with
*Contents* and *Workflows* write on this repository only), then *Actions →
Release → Run workflow* with `version` = `2.1.0`. Either way it is not marked
"latest".

**A tag pushed by hand** still works: that exact commit is released.

**Correcting published notes**: fix the section in CHANGELOG.md and merge.
On every push to `main` the workflow's `notes` job compares each released
section with its release and rewrites a body that no longer matches. It keeps
the release's "Verify this download" block, because that digest belongs to the
artifacts. Editing a release creates no tag, so no extra token is needed.

**Back-fills listed in the workflow** (`BACKFILL`, now `2.1.0,4.0.0`) are
released by the automatic run once the newest version is tagged, one per run.
Each one needs a working `RELEASE_TOKEN` (below); until GitHub accepts one the
run skips it with a warning, not a failure. Renewing the secret starts
nothing by itself: the back-fill happens at the next automatic run (a merge to
`main` that changes CHANGELOG.md or `iemod_fetch/__init__.py`, after the
newest version is tagged) or at once with *Actions → Release → Run workflow*
and that version.

### RELEASE_TOKEN

**When it is needed.** Only to tag a commit whose `.github/workflows` differ
from `main`'s - a back-fill, or a release whose commit was followed by a
workflow change (4.0.0: `gui-latency.yml` was added after it). GitHub never
lets the run's own `GITHUB_TOKEN` create such a ref. Every other release is
tagged with the run's own token, and `RELEASE_TOKEN` may be absent.

**How the workflow checks it.** Only a release that needs the secret uses it,
and only then is it checked: the first job (`What to release, and which
commit`) asks GitHub for this repository with it. HTTP 200: it tags and
publishes. 401 ("Bad credentials": expired or revoked) or no answer: a
`RELEASE_TOKEN rejected` warning, it is not used, and the run stops there - an
automatic run with a warning, a run started by hand with an error - instead of
failing at the publish step after the build. What the check cannot see: the
repository is public, so any live token gets a 200, also one made for another
repository or without *Contents*/*Workflows* write; such a token still fails
at the publish step. Give it exactly the permissions below. A release that
does not need it never uses it, so a wrong secret cannot break it.

**Creating or renewing it** (the repository owner, on github.com):
1. *Settings (of your account) → Developer settings → Personal access tokens
   → Fine-grained tokens → Generate new token*.
2. *Resource owner*: the account that owns this repository; *Repository
   access*: *Only select repositories* → this repository only.
3. *Repository permissions*: **Contents: Read and write** and **Workflows:
   Read and write**. Metadata (read) is added by GitHub. Nothing else.
4. *Expiration*: the shortest that suits you (90 days is a common choice);
   note the date - an expired token is what stopped 4.0.0.
5. Copy it once, then in this repository: *Settings → Secrets and variables →
   Actions → Repository secrets → `RELEASE_TOKEN`* → *Update* (or *New
   repository secret*). Never paste it anywhere else - not in an issue, a
   commit, a chat.
6. Release: *Actions → Release → Run workflow* with the version (for 4.0.0:
   `4.0.0`). That run plans again with today's state: which commit, and
   whether it is "Latest". **Do not use *Re-run failed jobs* on an old failed
   run** once a newer version is out: a re-run reuses that run's plan,
   including "Latest", so 4.0.0's run of 2026-10-31 re-run after 4.0.1 would
   make 4.0.0 the Latest release. (A run stopped by the check has nothing to
   re-run anyway: nothing was built.)

**Without a token.** Push the tag by hand: `git tag -a vX.Y.Z -m X.Y.Z
<commit> && git push origin vX.Y.Z`. The push starts the *tagged commit's
own* release workflow; when that one can run (4.0.0's can), it publishes the
release - do not then also *Run workflow*, which would publish it a second
time. An older workflow judges "Latest" from its own commit's changelog, so a
back-fill published this way may be marked Latest. Today's workflow judges
"Latest" from `main`'s changelog, also on a tag push.

**A back-fill's tag starts a second run.** The tag a back-fill creates with
`RELEASE_TOKEN` starts the *tagged commit's own* release workflow (a tag
pushed with a personal token starts workflows; one pushed with GITHUB_TOKEN
does not). That run rebuilds and republishes the same release, and an older
workflow marks it Latest - 4.0.0's tag run did so over 4.0.1 on 2026-10-31.
It can be cancelled (*Actions → Release*, the run on the tag) once the
back-fill is published. If it is not, "Latest" is put back on the newest
release by `tools/release_notes.py latest`: by release-latest.yml every six
hours, and by release.yml's notes job at the next push to `main` that changes
CHANGELOG.md or the version. It reads every release in one call and fails,
changing nothing, when GitHub does not answer. By hand: the newer release's page, *Edit → Set as the latest release*.

**Dry run**: *Run workflow* with `dry_run` checked builds and attests but
publishes nothing.

**Rehearsal on a pull request**: a pull request that changes
`release.yml`, `tools/release_plan.py` or `tools/release_notes.py` runs the
same pipeline on its own commit, under the version its `__version__` says:
the CI gate, the build, the tag-matches-version check and the attestation.
The notes, tag, release and PyPI jobs never run on a pull request. This is
how a Dependabot bump of an action used only by releases is tested before it
merges. A fork's pull request is skipped, since it may not sign an
attestation. The attestation is real: it records that the pull request's
workflow built those bytes, and nothing is published with it.

## Pinned test toolchain

The real-WeiDU job in `ci.yml` installs the mock EET plan with tools pinned
there. Dependabot cannot update them:

| Tool | Pin | How it is checked |
|---|---|---|
| WeiDU | `WEIDU_URL` (release v251.00) and `WEIDU_SHA256` | `sha256sum -c` before it runs |
| mod_installer | `MOD_INSTALLER_REV` (commit) and `MOD_INSTALLER_VERSION` | built from that commit |

**The wizard's mod_installer** (ADR-0046) is the same commit, compiled by
`packaging/mod_installer.py` in the wizard's bundle builds (release.yml,
release-macos.yml) and in the real-WeiDU job. It needs git and rustup (the
script installs the pinned Rust and target), plus `musl-tools` on Linux.
Bumping it means changing `REV` and `VERSION` in that script and the two
`MOD_INSTALLER_*` values in ci.yml; a test fails while they differ.

`upstream-versions.yml` compares them with upstream every Monday. It opens an
issue per tool that is behind ("WeiDU 252.00 is available (pinned 251.00)"),
and the run turns red until the pin is bumped. To bump: download the new WeiDU
zip yourself and compute its `sha256sum`. For mod_installer, pick the commit
whose Cargo.toml has the new version and read its changes. Then update the
pins and let CI prove the mock EET plan still installs.

**Python itself** (ADR-0043) is pinned in `.python-version`, which every
workflow reads. The same Monday run compares it with the newest stable Python
setup-python can install (actions/python-versions' manifest) and opens "Python
3.15 is available (pinned 3.14)"; it also opens an issue when any place that
names the version - requires-python, ruff, mypy, the classifiers,
`iemod_fetch.PYTHON`, a literal `python-version:` in a workflow - disagrees
with `.python-version` (`tests/test_upstream_versions.py` fails on it too).
To move: change them together, CI green on Linux and Windows, the wizard's
bundle built and started, PySide6 and PyInstaller wheels for the new version,
and its What's New read for changed defaults. Dependabot never touches
`python-version`.

Everything else (the developer tools in `pyproject.toml`, the pinned actions)
is Dependabot's: one grouped pull request per week for each.

## What the operator can verify

Every release carries the three things needed to check that the download matches
the source:

```bash
# The digest, against SHA256SUMS in the release.
sha256sum iemod-fetch.pyz

# The provenance: which workflow, at which commit, produced these bytes.
gh attestation verify iemod-fetch.pyz --repo gsamuele78/iemod-fetch

# And the build is reproducible, so it can be checked from scratch.
git checkout v2.1.0 && python3 build.py && cmp iemod-fetch.pyz <downloaded>
```

The wizard zips are checked the same way by digest and attestation
(`gh attestation verify iemod-fetch-gui-linux-x86_64.zip --repo ...`). They are
not reproducible from scratch: a PyInstaller build embeds compiled bytecode and
the runner's Qt wheel, so only the zip's layout and timestamps are fixed.

That last one is why CI builds twice and compares. Reproducibility is what turns
a signature from "someone signed something" into "this artifact is that source".

## No long-lived secrets

There is no PyPI token in the repository settings and no signing key anywhere.
PyPI is reached with a short-lived OIDC token minted for that one workflow run,
and the signing identity *is* the workflow. Nothing exists to be exfiltrated
from a compromised action, which is the point.

## If a release is wrong

Yank it and cut a new patch. Do not move a tag: somebody has already downloaded
the artifact it pointed at, and an attestation that no longer matches its tag is
worse than a bad release.
