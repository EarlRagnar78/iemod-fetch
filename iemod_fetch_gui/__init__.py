"""
iemod-fetch's desktop wizard (ADR-0031, milestone M3 of docs/GUI-AUDIT.md).

A PySide6 front end for the same tool the command line drives. It reaches the
tool only through `iemod_fetch.api` - import-linter refuses anything else - and
every phase saves a file the CLI also reads, so a run can be stopped, resumed,
or finished from the command line.

    pip install "iemod-fetch[gui]"
    iemod-fetch-gui [--project FOLDER]
"""
__all__ = ["main"]


def main(argv=None) -> int:
    from .app import main as run
    return run(argv)
