#!/usr/bin/env python3
"""
Build mod_installer for the wizard's bundle (GUI-AUDIT M4 item 22b, ADR-0046):
dark0dave's mod_installer (GPL-3.0) at the commit CI tests, compiled for this
system and checked to say its version.

    python packaging/mod_installer.py --out build/mod_installer

prints the program's path; gui_bundle.py --mod-installer puts it in the
bundle, with its licence and where its source is. Beside it lies SOURCE, the
source it was built from (`git archive` of REV): the release attaches it, so
the GPL-3.0's Corresponding Source is offered from the same place as the
program (section 6(d)), whatever happens upstream.

Why built: upstream's last release, v12.1.1, stops after the first component
on Linux (it reads `weidu.log`, WeiDU writes `WeiDU.log`), and nothing newer
is released. 16.0.0 - upstream's main branch, commit REV - is.

What it needs, and installs what it can:
* git and rustup (https://rustup.rs) on PATH - not installed here;
* Rust RUST with this system's target - installed with rustup;
* on Linux, musl's C compiler (Debian/Ubuntu: `apt install musl-tools`):
  the program is linked statically there, so it runs on any distribution.
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys

REPOSITORY = "https://github.com/dark0dave/mod_installer"
REV = "3b6827a039db43e342be19f7610ecdd680fe0a62"
VERSION = "16.0.0"                 # Cargo.toml at REV
RUST = "1.98.0"


def target(system: str | None = None, machine: str | None = None) -> str:
    """The Rust target this system's bundle carries."""
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64",
            "aarch64": "aarch64"}.get(machine)
    if arch is None:
        raise SystemExit(f"no mod_installer build for {system} {machine}")
    return {"Linux": f"{arch}-unknown-linux-musl",
            "Windows": f"{arch}-pc-windows-msvc",
            "Darwin": f"{arch}-apple-darwin"}[system]


SOURCE = f"mod_installer-{VERSION}-source.tar.gz"


def run(args: list[str], cwd: str | None = None, env: dict | None = None) -> None:
    sys.stderr.write("+ " + " ".join(args) + "\n")
    subprocess.run(args, cwd=cwd, check=True, env=env)  # noqa: S603 (the build's own tools)


def build_env(rust_target: str) -> dict | None:
    """Windows: the C runtime linked in. By default Rust's MSVC programs load
    VCRUNTIME140.dll (measured in upstream's v12.1.1 .exe), which a clean
    Windows lacks and which the bundle keeps under _internal, out of reach."""
    if rust_target.endswith("-windows-msvc"):
        flags = os.environ.get("RUSTFLAGS", "")
        return dict(os.environ, RUSTFLAGS=(flags + " -C target-feature=+crt-static").strip())
    return None


def needs_vc_runtime(program: str) -> bool:
    """The program names the Visual C++ runtime DLL it would load."""
    with open(program, "rb") as fh:
        return b"vcruntime140" in fh.read().lower()


def requirements(rust_target: str) -> None:
    """What the build needs: say what is missing, install what rustup can."""
    missing = [tool for tool in ("git", "rustup") if shutil.which(tool) is None]
    if rust_target.endswith("-linux-musl") and shutil.which("musl-gcc") is None:
        missing.append("musl-gcc (Debian/Ubuntu: apt install musl-tools)")
    if missing:
        raise SystemExit("to build mod_installer, install: " + ", ".join(missing))
    run(["rustup", "toolchain", "install", RUST, "--profile", "minimal",
         "--target", rust_target])


def fetch(source: str) -> None:
    """The source at REV exactly: a commit id names its content."""
    os.makedirs(source, exist_ok=True)
    if not os.path.isdir(os.path.join(source, ".git")):
        run(["git", "init", "-q"], cwd=source)
    run(["git", "fetch", "-q", "--depth", "1", REPOSITORY, REV], cwd=source)
    run(["git", "checkout", "-q", "--force", REV], cwd=source)


def version_of(program: str) -> str:
    done = subprocess.run([program, "--version"], capture_output=True, text=True,  # noqa: S603
                          timeout=60, check=False)
    return done.stdout.strip()


def build(out: str) -> str:
    """mod_installer built for this system in `out`; its path."""
    rust_target = target()
    requirements(rust_target)
    source = os.path.join(out, "source")
    fetch(source)
    run(["cargo", f"+{RUST}", "build", "--release", "--locked", "--target", rust_target],
        cwd=source, env=build_env(rust_target))
    name = "mod_installer" + (".exe" if platform.system() == "Windows" else "")
    program = os.path.join(out, name)
    shutil.copy2(os.path.join(source, "target", rust_target, "release", name), program)
    shutil.copy(os.path.join(source, "license"), os.path.join(out, "LICENSE"))
    run(["git", "archive", "--format=tar.gz", f"--prefix=mod_installer-{VERSION}/",
         "-o", os.path.join(out, SOURCE), REV], cwd=source)
    if needs_vc_runtime(program):
        raise SystemExit(f"{program} needs VCRUNTIME140.dll: it would not start on a "
                         "Windows without the Visual C++ runtime")
    said = version_of(program)
    if said != f"mod_installer {VERSION}":
        raise SystemExit(f"{program} says {said!r}, not mod_installer {VERSION}")
    return program


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=os.path.join("build", "mod_installer"))
    args = parser.parse_args(argv)
    sys.stdout.write(build(os.path.abspath(args.out)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
