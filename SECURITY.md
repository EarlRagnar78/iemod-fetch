# Security Policy

## Reporting a vulnerability

Use GitHub's **private vulnerability reporting** on this repository
(Security → Report a vulnerability). Please do not open a public issue for
anything that would let someone else exploit an operator before there is a fix.

Expect an acknowledgement within a week. This is a hobby project maintained by
one person: I will tell you honestly whether and when I can fix something rather
than leave you waiting on a service-level promise I cannot keep.

## What this tool does with untrusted input

It downloads archives from the internet and extracts them onto a gaming machine.
That is the whole threat model, and `docs/SECURITY-MODEL.md` sets it out in
full. In short, the boundaries that must hold:

| Boundary | Guarantee | Enforced in |
|---|---|---|
| Transport | HTTPS only, including across every redirect | `net.py` |
| Credential | the GitHub token is attached to `api.github.com` / `github.com` and nowhere else | `net.py` |
| Content | magic-byte sniff, size ceiling, and `sha256` verification when the manifest pins one | `net.py` |
| Archive | no member escapes the extraction root; no symlinks; entry-count, total-size and compression-ratio ceilings; extraction one member at a time with the resolved path re-checked | `archives.py` |
| Names | one path component, no traversal, no absolute paths, no NUL, no Windows reserved names | `naming.py` |
| Execution | nothing downloaded is ever executed; `.exe` is unpacked only with `--allow-exe`, never run | `archives.py` |
| Destination | an existing mod directory is never deleted; `--force` moves it to `.backup/` | `install.py` |

Each of these has tests that assert the boundary **rejects**, in
`tests/test_net_security.py` and `tests/test_archives_security.py`.

## What is explicitly out of scope

- **The mods themselves.** A `.tp2` is a program and WeiDU runs it. This tool
  stages files; it does not sandbox, review or vouch for mod content. If you
  install a malicious mod, nothing here stops it.
- **Upstream rule data.** BigWorldSetup Next-Generation and krion64 data are
  read as data, never executed, and every value from them is treated as a string
  — but their *claims* are theirs, not mine.
- **Cleartext-HTTP mods behind `--allow-http`.** The flag exists because a few
  archives genuinely have no HTTPS host. Using it is a decision you are making.

## Supported versions

The latest tagged release. Given the size of the project, backporting fixes to
older tags is not something I can promise.
