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

## Cutting one

```bash
# 1. The changelog. Move Unreleased into a dated version heading.
$EDITOR CHANGELOG.md

# 2. The version, in one place.
$EDITOR iemod_fetch/__init__.py     # __version__
$EDITOR pyproject.toml              # [project] version

# 3. Everything green, locally, before the tag exists.
make check && make cover && make audit && make build

# 4. Tag and push.
git commit -am "Release 2.1.0"
git tag -a v2.1.0 -m "2.1.0"
git push origin main --follow-tags
```

The release workflow then, in order: re-runs the entire CI gate (a tag does not
get a shortcut past the tests); checks that the tag and
`iemod_fetch.__version__` agree and fails loudly if they do not; builds the
sdist, the wheel and the `.pyz`; records `SHA256SUMS`; generates a CycloneDX
SBOM; attests build provenance through Sigstore keyless signing; opens a
**draft** GitHub release with notes extracted from the changelog section for
that version; and publishes to PyPI through OIDC trusted publishing, gated on a
manual approval of the `pypi` environment.

Then a human reads the draft and publishes it.

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
