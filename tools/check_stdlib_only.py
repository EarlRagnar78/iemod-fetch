#!/usr/bin/env python3
"""
Fail if anything under `iemod_fetch/` imports a package that is neither in the
standard library nor one of the runtime's libraries (requirements/runtime.txt).

ADR-0043 lets the runtime take a library only when it fixes a measured defect,
pinned by hash and carried inside the .pyz. A stray `import requests` in a
rarely-taken branch would break that silently - the tests pass on a
developer's machine where the package happens to be installed.

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

STDLIB = sys.stdlib_module_names
# The runtime's libraries (ADR-0043): what requirements/runtime.txt pins.
RUNTIME = frozenset(
    line.split("==", 1)[0].strip().replace("-", "_").lower()
    for line in (ROOT / "requirements" / "runtime.txt").read_text(encoding="utf-8").splitlines()
    if "==" in line and not line.lstrip().startswith("#"))


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
            if name in STDLIB or name in RUNTIME or name == "iemod_fetch":
                continue
            offences.append(f"{path.relative_to(ROOT)}:{lineno}: imports {name!r}")

    if offences:
        print("The runtime imports the standard library and requirements/runtime.txt "
              "only (ADR-0043):",
              file=sys.stderr)
        for line in offences:
            print(f"  {line}", file=sys.stderr)
        print("\nIf this is developer tooling, it belongs in tools/ or tests/, "
              "not in iemod_fetch/.", file=sys.stderr)
        return 1

    print(f"stdlib and {sorted(RUNTIME)} only: {len(list(PACKAGE.rglob('*.py')))} "
          f"modules checked, clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
