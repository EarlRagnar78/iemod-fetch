"""
Which open-source extractor opens the RAR archives the catalogue links to
(GUI-AUDIT M6 item 40) - measured on the real archives, against the official
7-Zip as the reference, on the platforms iemod-fetch supports (Debian trixie
as the floor, Windows, macOS).

    python tools/rar_measure.py corpus --mods mods.json --dir rars [--max-mb 400]
    python tools/rar_measure.py reference --dir rars --seven-zip 7zz --json ref.json
    python tools/rar_measure.py compare --dir rars --ref ref.json \\
        --tool "bsdtar=bsdtar -xf {archive}" --tool "unar=unar -q -f -D {archive}" \\
        --json out.json [--summary out.md]

`corpus` downloads every distinct direct .rar link of lcc-docs' mods.json
(GitHub's /raw/ links through raw.githubusercontent.com). `reference` extracts
each with 7-Zip and records every file's SHA-256, the archive's own SHA-256,
its format (RAR4 or RAR5) and whether it is solid or encrypted. `compare`
extracts each archive whose SHA-256 matches the reference with each tool, in
an empty folder, and calls it identical only when the same files come out with
the same contents. Standard library only, and Python 3.13 (Debian trixie's).
"""
import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.request

RAR = re.compile(r"\.rar(\?|$)", re.IGNORECASE)
RAW = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/raw/(.+)$")


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def kind(path: str) -> str:
    with open(path, "rb") as fh:
        head = fh.read(8)
    if head.startswith(b"Rar!\x1a\x07\x01\x00"):
        return "RAR5"
    if head.startswith(b"Rar!\x1a\x07\x00"):
        return "RAR4"
    return "not RAR"


def tree(folder: str) -> dict[str, str]:
    """Every regular file under `folder`, by its path (lower case, /), to its SHA-256."""
    out = {}
    for root, _dirs, files in os.walk(folder):
        for name in files:
            path = os.path.join(root, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            out[os.path.relpath(path, folder).replace("\\", "/").lower()] = sha256(path)
    return out


def run(argv: list[str], cwd: str) -> int | str:
    try:
        return subprocess.run(argv, cwd=cwd, capture_output=True, timeout=600,  # noqa: S603
                              check=False).returncode
    except subprocess.TimeoutExpired:
        return "timeout"
    except OSError as exc:
        return f"error: {exc}"


def archives(folder: str) -> list[str]:
    return sorted(name for name in os.listdir(folder) if name.endswith(".rar"))


def corpus(args) -> int:
    with open(args.mods, encoding="utf-8") as fh:
        mods = json.load(fh)
    urls: list[str] = []
    for mod in mods:
        for url in mod.get("urls") or ():
            if isinstance(url, str) and RAR.search(url) and url not in urls:
                urls.append(url)
    names = {url: f"{n:03d}.rar" for n, url in enumerate(urls, 1)}
    if args.index:                          # the names another run gave: same archive, same name
        with open(args.index, encoding="utf-8") as fh:
            names = {entry["url"]: name for name, entry in json.load(fh).items()}
        urls = [url for url in urls if url in names]
    os.makedirs(args.dir, exist_ok=True)
    index, cap = {}, args.max_mb * 1_000_000
    for url in urls:
        name = names[url]
        target = os.path.join(args.dir, name)
        fetch = RAW.sub(r"https://raw.githubusercontent.com/\1/\2/\3", url)
        try:
            request = urllib.request.Request(fetch, headers={"User-Agent": "iemod-fetch rar_measure"})
            with urllib.request.urlopen(request, timeout=120) as response, \
                    open(target, "wb") as fh:  # noqa: S310 (the catalogue's own links)
                size = 0
                while block := response.read(1 << 20):
                    size += len(block)
                    if size > cap:
                        raise OSError(f"larger than {args.max_mb} MB")
                    fh.write(block)
        except (OSError, ValueError) as exc:
            if os.path.exists(target):
                os.remove(target)
            index[name] = {"url": url, "error": str(exc)[:200]}
            continue
        index[name] = {"url": url, "kind": kind(target)}
    with open(os.path.join(args.dir, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=1)
    got = sum("kind" in entry for entry in index.values())
    print(f"{len(urls)} distinct .rar links, {got} downloaded")
    return 0


def reference(args) -> int:
    seven_zip = os.path.abspath(args.seven_zip)   # each extraction runs in its own folder
    out = {}
    for name in archives(args.dir):
        path = os.path.abspath(os.path.join(args.dir, name))
        entry = {"sha256": sha256(path), "kind": kind(path)}
        if entry["kind"] != "not RAR":
            listing = subprocess.run([seven_zip, "l", "-slt", path],  # noqa: S603
                                     capture_output=True, text=True, errors="replace",
                                     check=False).stdout
            entry["solid"] = "Solid = +" in listing
            entry["encrypted"] = "Encrypted = +" in listing
            with tempfile.TemporaryDirectory() as work:
                entry["rc"] = run([seven_zip, "x", "-y", path], work)
                entry["files"] = tree(work)
        out[name] = entry
    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    usable = sum(1 for e in out.values() if e.get("rc") == 0 and e.get("files"))
    print(f"{len(out)} archives, {usable} extracted by the reference")
    for name, e in sorted(out.items()):     # why the others were not, one line each
        if not (e.get("rc") == 0 and e.get("files")):
            print(f"  not read: {name} {e['kind']} rc={e.get('rc')} "
                  f"encrypted={e.get('encrypted')} files={len(e.get('files') or {})}")
    return 0 if usable else 1                   # a reference that read nothing measures nothing


def compare(args) -> int:
    with open(args.ref, encoding="utf-8") as fh:
        ref = json.load(fh)
    tools = []
    reserved = {"archive", "kind", "solid", "encrypted", "files", "missing"}
    for spec in args.tool:
        label, _, command = spec.partition("=")
        if label in reserved or not command:
            raise SystemExit(f"--tool {spec!r}: give LABEL=COMMAND, LABEL not one of {sorted(reserved)}")
        tools.append((label, command))
    unrunnable = set()
    rows = []
    for name, expected in sorted(ref.items()):
        path = os.path.abspath(os.path.join(args.dir, name))
        if expected.get("rc") != 0 or not expected.get("files"):
            continue                        # the reference itself could not read it
        if not os.path.exists(path) or sha256(path) != expected["sha256"]:
            rows.append({"archive": name, "kind": expected["kind"], "missing": True})
            continue
        row = {"archive": name, "kind": expected["kind"], "solid": expected["solid"],
               "encrypted": expected["encrypted"], "files": len(expected["files"])}
        for label, command in tools:
            argv = [part.replace("{archive}", path) for part in shlex.split(command)]
            with tempfile.TemporaryDirectory() as work:
                rc = run(argv, work)
                got = tree(work)
            if isinstance(rc, str) and rc.startswith("error"):
                unrunnable.add(label)       # not measured, not "extracts nothing"
            want = expected["files"]
            wrong = sum(1 for path in got.keys() | want.keys() if got.get(path) != want.get(path))
            row[label] = ("identical" if got == want else
                          f"rc={rc} files={len(got)}/{len(want)} wrong={wrong}")
        rows.append(row)
    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=1)
    lines = [f"### RAR extraction on {args.platform}", "",
             "| tool | RAR4 | RAR5 | solid | all |", "|---|---|---|---|---|"]
    measured = [r for r in rows if not r.get("missing")]
    for label, _command in tools:
        def ok(subset, tool=label):
            return f"{sum(r[tool] == 'identical' for r in subset)}/{len(subset)}"
        lines.append(f"| {label} | {ok([r for r in measured if r['kind'] == 'RAR4'])} | "
                     f"{ok([r for r in measured if r['kind'] == 'RAR5'])} | "
                     f"{ok([r for r in measured if r['solid']])} | {ok(measured)} |")
    either = sum(any(r[label] == "identical" for label, _c in tools) for r in measured)
    missing = sum(1 for r in rows if r.get("missing"))
    lines += ["", (f"Any of them: {either}/{len(measured)}. Archives the reference read "
                   f"but this run could not download identically: {missing}."), "",
              "Not identical:", ""]
    lines += [f"- {r['archive']} ({r['kind']}{', solid' if r['solid'] else ''}, "
              f"{r['files']} files): " + "; ".join(f"{label} {r[label]}" for label, _c in tools)
              for r in measured if any(r[label] != "identical" for label, _c in tools)]
    text = "\n".join(lines) + "\n"
    print(text)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    if unrunnable:
        sys.stderr.write(f"could not start: {', '.join(sorted(unrunnable))}\n")
    return 0 if measured and not unrunnable else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("corpus")
    one.add_argument("--mods", required=True)
    one.add_argument("--dir", required=True)
    one.add_argument("--max-mb", type=int, default=400)
    one.add_argument("--index", help="name the archives as this index.json of another run does")
    two = sub.add_parser("reference")
    two.add_argument("--dir", required=True)
    two.add_argument("--seven-zip", required=True)
    two.add_argument("--json", required=True)
    three = sub.add_parser("compare")
    three.add_argument("--dir", required=True)
    three.add_argument("--ref", required=True)
    three.add_argument("--tool", action="append", required=True)
    three.add_argument("--json", required=True)
    three.add_argument("--summary")
    three.add_argument("--platform", default=sys.platform)
    args = parser.parse_args(argv)
    return {"corpus": corpus, "reference": reference, "compare": compare}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
