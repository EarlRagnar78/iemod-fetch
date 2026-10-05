#!/usr/bin/env python3
"""
Fail if anything under `iemod_fetch/` imports a package that is not in the
standard library.

ADR-0002 promises the operator that one `.pyz` runs against whatever Python
their gaming machine already has. That promise is broken by a single `import
requests` in a rarely-taken branch, and it is broken silently — the tests pass
on a developer's machine where the package happens to be installed.

`import-linter` enforces the same rule against a named list of packages. This
checks the complement — anything not in the standard library — so a dependency
nobody thought to ban is caught too. It parses the source rather than importing
it, so it is fast enough for a pre-commit hook and safe on unrunnable code.
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "iemod_fetch"

# `sys.stdlib_module_names` exists from 3.10. Below that, fall back to the set
# this package actually uses — enumerated, so a new import is still caught.
STDLIB = getattr(sys, "stdlib_module_names", None) or frozenset({
    "abc", "argparse", "ast", "base64", "collections", "configparser",
    "contextlib", "dataclasses", "datetime", "enum", "fnmatch", "functools",
    "glob", "hashlib", "html", "http", "io", "itertools", "json", "logging",
    "os", "pathlib", "posixpath", "random", "re", "shutil", "socket", "ssl",
    "string", "subprocess", "sys", "tarfile", "tempfile", "textwrap", "time",
    "typing", "urllib", "uuid", "warnings", "zipapp", "zipfile",
})


def top_level_imports(path: pathlib.Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            if node.level:          # relative: our own modules
                continue
            if node.module:
                yield node.lineno, node.module.split(".")[0]


def main() -> int:
    offences = []
    for path in sorted(PACKAGE.rglob("*.py")):
        for lineno, name in top_level_imports(path):
            if name in STDLIB or name == "iemod_fetch":
                continue
            offences.append(f"{path.relative_to(ROOT)}:{lineno}: imports {name!r}")

    if offences:
        print("The runtime must import the standard library only (ADR-0002):",
              file=sys.stderr)
        for line in offences:
            print(f"  {line}", file=sys.stderr)
        print("\nIf this is developer tooling, it belongs in tools/ or tests/, "
              "not in iemod_fetch/.", file=sys.stderr)
        return 1

    print(f"stdlib-only: {len(list(PACKAGE.rglob('*.py')))} modules checked, clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
