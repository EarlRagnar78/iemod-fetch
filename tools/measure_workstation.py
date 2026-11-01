"""
The download-sources measurement, from a player's own computer (GUI-AUDIT M7
item 57). The download-sources workflow runs it from GitHub's runners, where
Gibberlings3, SHS and Nexus answer every request with Cloudflare's 403; from a
home connection they usually do not, and that is what is left to measure.

    python tools/measure_workstation.py [--log tests/data/WeiDU.log]
        [--real all|N] [--max-bytes BYTES] [--out DIR]

Runs, each step's output kept in DIR (default: measure-<date> here, new or
empty): the community data, fetched into DIR/data so the player's own cache is
left alone; a dry run with the catalogue alone and one with the manifest; a
real download of the planned mods (`--real`, default all; each over
--max-bytes, default 300 MB, is counted, not fetched); premeta's live check;
and what the Gibberlings3 and SHS pages give. Then DIR/summary.md: the same
tables the workflow writes, to be pasted back. A step that leaves no report
stops the run with its output shown and a non-zero exit. A GitHub token makes
the GitHub part work at 5,000 requests an hour instead of 60: `gh auth login`,
or GH_TOKEN set. Nothing is installed into a game; the mods land in DIR/mods.
"""
import argparse
import datetime as dt
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from iemod_fetch.atomic import write_text  # noqa: E402

# The pages the runners cannot read (download-sources workflow, 2026-10-23).
CLOUDFLARED = (
    "https://www.gibberlings3.net/files/file/702-a-mod-for-the-orderly/",
    "https://www.gibberlings3.net/mods/quests/cliffette",
    "https://www.shsforums.net/topic/57927-mod-the-picture-standard-for-bgee-1-2/",
)
MEGABYTE = 1024 * 1024


class Failed(Exception):
    """A step that leaves nothing to measure."""


def step(title, argv, log, env):
    """Run one step, its output appended to the log; returns its exit code."""
    print(f"-- {title}", flush=True)
    with open(log, "a", encoding="utf-8") as out:
        out.write(f"\n## {title}\n$ {' '.join(argv)}\n")
        out.flush()
        done = subprocess.run(argv, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT,
                              env=env, check=False)
        out.write(f"(exit {done.returncode})\n")
    return done.returncode


def produced(title, path, log):
    """The report a step must leave; a run with planned or manual mods exits 1."""
    if not os.path.isfile(path):
        raise Failed(f"{title} wrote no {os.path.basename(path)}: see {log}")
    return path


def capture(argv, env):
    """A helper script's output; its error, shown, is a failure."""
    done = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, env=env,
                          check=False)
    if done.returncode:
        raise Failed(f"{' '.join(argv[1:2])} failed:\n{done.stderr.strip()}")
    return done.stdout


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--log", default=os.path.join(ROOT, "tests", "data", "WeiDU.log"),
                        help="the WeiDU.log whose mods are measured")
    parser.add_argument("--manifest", default=os.path.join(ROOT, "tests", "data",
                                                           "mod_downloads.json"))
    parser.add_argument("--real", default="all", metavar="all|N",
                        help="how many planned mods to download for real")
    parser.add_argument("--max-bytes", type=int, default=300 * MEGABYTE)
    parser.add_argument("--out", default=f"measure-{dt.date.today():%Y-%m-%d}")
    args = parser.parse_args(argv)
    if args.real != "all" and not args.real.isdigit():
        parser.error("--real is a number or 'all'")
    # every step runs in the repository: a path given here is read from here
    weidu_log, manifest = os.path.abspath(args.log), os.path.abspath(args.manifest)
    for path in (weidu_log, manifest):
        if not os.path.isfile(path):
            parser.error(f"no such file: {path}")
    out = os.path.abspath(args.out)
    if os.path.isdir(out) and os.listdir(out):
        parser.error(f"{out} is not empty: an earlier run's reports would be read "
                     f"as this one's; give another --out")
    os.makedirs(out, exist_ok=True)

    log = os.path.join(out, "steps.log")
    py = sys.executable
    env = {**os.environ, "IEMOD_DATA_DIR": os.path.join(out, "data")}
    tool = [py, "-m", "iemod_fetch", "--no-update-data", "-q"]
    dry = os.path.join(out, "dry-catalogue.json")
    dry_manifest = os.path.join(out, "dry-manifest.json")
    real = os.path.join(out, "real.json")
    try:
        if step("community data", [py, "-m", "iemod_fetch", "--update-data"], log, env):
            raise Failed(f"the community data could not be fetched: see {log}")
        step("dry run, catalogue only", [*tool, "-w", weidu_log, "-m", "", "--dry-run",
                                         "--no-discovery", "-t", os.path.join(out, "mods-a"),
                                         "--json-report", dry], log, env)
        produced("the catalogue-only dry run", dry, log)
        step("dry run, with the manifest",
             [*tool, "-w", weidu_log, "-m", manifest, "--dry-run", "--no-discovery",
              "-t", os.path.join(out, "mods-b"), "--json-report", dry_manifest], log, env)
        produced("the dry run with the manifest", dry_manifest, log)
        picks = capture([py, os.path.join("tools", "download_measure.py"), dry,
                         "--pick", args.real], env).split()
        if picks:
            only = [a for folder in picks for a in ("--only", folder)]
            step(f"real download of {len(picks)} mods",
                 [*tool, "-w", weidu_log, "-m", "", "--no-discovery", *only,
                  "-t", os.path.join(out, "mods"), "--max-bytes", str(args.max_bytes),
                  "--json-report", real], log, env)
            produced("the real download", real, log)
        step("premeta live check", [py, os.path.join("tools", "premeta_live_check.py")],
             log, env)
        step("the pages GitHub's runners cannot read",
             [py, os.path.join("tools", "landing_probe.py"), *CLOUDFLARED], log, env)
        summary = capture([py, os.path.join("tools", "download_measure.py"), dry,
                           dry_manifest, *(["--real", real] if picks else [])], env)
        if not summary.strip():
            raise Failed("the summary came out empty")
    except Failed as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return 1
    write_text(os.path.join(out, "summary.md"), summary)
    print(summary)
    print(f"Everything is in {out}: summary.md to paste back, steps.log for the detail.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
