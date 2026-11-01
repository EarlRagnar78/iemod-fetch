# Security model

## What this tool actually is

A program that downloads archives from the internet and unpacks them onto a
gaming machine, guided by a JSON file and a log file the operator edits by hand.
Every interesting security question follows from that sentence.

## Trust boundaries

```
  operator's manifest ─┐
  WeiDU logs ──────────┼──► [ parse, validate ]──► typed values
  INI config ──────────┘         naming.py
                                 manifest.py            ← boundary 1
  ───────────────────────────────────────────────────────────────
  the internet ────────────► [ net.py ]
     HTTPS only, redirects checked, credential scoped,
     size ceiling, magic bytes, sha256                  ← boundary 2
  ───────────────────────────────────────────────────────────────
  downloaded archive ──────► [ archives.py ]
     every member checked, extracted one at a time,
     destination re-resolved before each write          ← boundary 3
  ───────────────────────────────────────────────────────────────
  staging directory ───────► [ install.py ]
     verified tp2, atomic move, never deletes           ← boundary 4
  ───────────────────────────────────────────────────────────────
  rule / catalogue JSON ───► read as DATA, never executed
     (BWS-NG, krion64, LCC — other people's repositories)
```

## Boundary 1 — operator input

The manifest is validated on load, not on use. A `ModSource` that exists cannot
hold an unsafe folder name, because `parse_manifest` refuses to construct one.
That is "parse, don't validate": the type system carries the guarantee, so no
downstream code has to remember to check.

`naming.safe_component` is the predicate, and it rejects: the empty string, `.`
and `..`, anything containing `/` or `\`, absolute paths, NUL, Windows reserved
device names (`CON`, `NUL`, `LPT1`…), and names ending in a dot or a space —
Windows silently strips those, so `evil.` and `evil` are the same file there.

A property test asserts that anything it accepts, joined onto a root, stays
under that root.

**A shared list is a stranger's text.** A BIO share code (`--bio-code`) arrives
pasted from a chat and was written by someone else. Its size is capped before
and after decompression (a zlib bomb stops at 32 MiB), and every tp2 path in
its WeiDU logs goes through `selection.json`'s own checks before anything
uses it: `~../../evil.tp2~` is refused, because WeiDU would otherwise run a
tp2 from outside the mods folder. Project Infinity lists (`--pi-list`) take
their tp2 paths from the staged mods or from krion64's records, and go through
the same checks. An author's `mod-forge.json` is read as data, size-capped,
and only into the rule set.

**A game folder is read, never written, by the limit check.** When a WeiDU.log
sits beside a `chitin.key`, KITLIST.2DA, SPELL.IDS, ADD_SPELL.IDS and
SPLSTATE.IDS are read from override/ or from the BIFF the key names. Each read
is size-capped (64 MiB key, 16 MiB resource), only uncompressed `BIFFV1` is
parsed, and a BIFF path from the key with a `..`, a drive or a stream part is
not followed - the key is the game's, but a damaged one must not make the
tool read elsewhere.

## Boundary 2 — the network

| Control | What it stops |
|---|---|
| HTTPS enforced, including on **every** redirect | a downgrade to cleartext mid-chain, which a redirect-following client does silently |
| The credential is attached to `api.github.com` and `github.com` only | a redirect to an attacker's host arriving with the operator's token in the header |
| A browser `User-Agent` for non-GitHub hosts, the honest tool UA for the API | not a security control — Gibberlings3 and SHS answer 403 to an unknown agent; recorded here so nobody mistakes it for one |
| Size ceiling, default 2 GiB, configurable | a response that never ends filling the disk |
| Magic-byte sniff after download | an HTML error page saved as `mod.zip` and unpacked |
| `sha256` verified when the manifest pins one | a changed asset behind an unchanged URL |
| Download to `.part`, verify, then `os.replace` | a half-written file being mistaken for a complete one |

`--allow-http` exists because a small number of mods genuinely have no HTTPS
host. It is off by default and using it is an explicit decision.

## Boundary 3 — archive extraction

This is where a mod downloader gets people owned, so it is the most defended
part of the code.

| Control | Attack |
|---|---|
| Every member name run through `safe_component` semantics | zip-slip: `../../../../etc/cron.d/x` |
| Symlink members rejected outright, both zip and tar | a link that points outside the root and is then written through |
| Special files (device, fifo) rejected in tar | |
| Entry-count ceiling | a million-entry archive as a denial of service |
| Uncompressed-total ceiling (2 GiB) | a decompression bomb |
| Per-member compression-ratio ceiling (200:1, above a floor) | a bomb hiding inside a plausible-sized archive |
| `tarfile` `filter="data"` where the runtime has it | the standard library's own hardened path — better than anything written here |
| **Extraction one member at a time, with the resolved destination re-checked before each write** | the gap between "the name I validated" and "the path the library resolved" |
| A post-extraction sweep for symlinks escaping the root | anything the per-member checks missed |
| Nothing downloaded is ever executed; `.exe` is *unpacked* only with `--allow-exe` | the obvious one |

That last-but-one control is the one worth explaining. `extractall` re-reads the
member list internally, so validating the list and then calling it means the
names you approved and the paths the library writes are two separate facts.
Extracting one entry at a time and re-resolving keeps them the same fact, and
costs nothing measurable.

External tools are used for `.rar` and `.7z` (ADR-0047): libarchive's bsdtar
(Windows' own `System32\tar.exe`), unar, and a 7-Zip or WinRAR the player has
installed - none is shipped. They are invoked with an argument **list**, never
a shell string. Each one extracts into a scratch folder of its own, deleted
when it fails, so a tool that wrote and then failed leaves nothing for the
next; only a tool that exits 0 has its files moved into place, and the result
is walked by the same audit as everything else. Since 2.1.0 the archive is first **listed** with `7z l -slt` and held to
the zip/tar rules — member names, entry count, total size — before the
unpacker writes anything. Without 7-Zip there is no listing, and the
post-extraction audit is what remains.

The archive's own file name is remote input too (a `Content-Disposition`
header, or a URL path). It is reduced to one safe path component, splitting on
both `/` and `\`, before it is joined onto the work directory; anything else
becomes `<folder>.bin`, which is harmless because the type is identified by
magic bytes.

## Boundary 4 — writing to disk

- An existing mod directory is **never deleted**. `--force` moves it to
  `.backup/`, and the report says where it went.
- The staged tree must contain `<folder>.tp2` or `setup-<folder>.tp2` — or the
  exact name the manifest's `expect_tp2` field states — before anything is
  moved into place. There is deliberately no "the archive has one `.tp2`, so it
  must be right" heuristic; that is the class of guessing ADR-0005 forbids.
- The move into place is atomic where the filesystem allows it.
- The wizard writes one file: `iemod-fetch.ini` in the project folder the user
  chose, only known options, written whole and swapped in (`config.write_values`).
  Other options and sections in that file are kept; comments are not.

## Credentials

The token is read from, in order: `--token-file`, `GH_TOKEN`/`GITHUB_TOKEN`,
`gh auth token`, the git credential helper, and finally an OAuth device flow
with an **empty scope** — the token it obtains can read public data and nothing
else.

It is never written to disk by this tool, never logged, never included in a
report, and never included in an error message. The git credential helper is
invoked with interaction disabled (`credential.interactive=false`,
`GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`) and a timeout, so a
misconfigured helper hangs the helper and not the run.

## What is out of scope, stated plainly

**The mods themselves.** A `.tp2` is a program and WeiDU executes it. This tool
stages files; it does not sandbox, review, or vouch for mod content. Everything
above protects the *fetching*. If you install a malicious mod, none of it helps.

**The installer scripts.** `--emit-installer` writes `install-eet.sh` /
`.cmd`; iemod-fetch never runs them, nor WeiDU, nor mod_installer. They are
short and meant to be read before running. Running one executes every `.tp2`
in the plan through WeiDU, with your user's rights, on the game folders you
name — the same trust you extend to any mod you install by hand. mod_installer
is a third-party binary (GPL-3.0); obtain it from its own releases page.

**Upstream rule data.** BWS-NG, krion64 and LCC JSON is read as data and every
value is coerced to a string before use. But their *claims* are theirs. The
conflict report prints the upstream's own evidence grade precisely so that a
`speculative` claim does not read like a verified one.

**The operator's own manifest.** If you pin a URL, it is fetched. The tool
verifies the transport, the size, the type and the digest; it does not have an
opinion about whether you should trust that host.

## Reporting a vulnerability

See `SECURITY.md` in the repository root.
