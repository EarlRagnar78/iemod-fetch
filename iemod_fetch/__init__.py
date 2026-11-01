"""Safe, reproducible asset fetcher for Infinity Engine mods (WeiDU / Project Infinity)."""
import sys

__version__ = "4.1.0"

# The one Python this tool is built and tested on (ADR-0043); .python-version,
# requires-python, ruff, mypy and the classifiers name the same, and a test
# holds them together. Checked here, before any module of the tool is read, so
# an older Python gets this sentence instead of a syntax error.
PYTHON = (3, 14)
if sys.version_info < PYTHON:
    raise SystemExit(
        f"iemod-fetch needs Python {PYTHON[0]}.{PYTHON[1]} or newer; this is "
        f"{sys.version.split()[0]}. Install it from python.org (or with uv: "
        f"`uv python install 3.14`), or use the wizard's release bundle, which carries "
        f"its own Python.")
