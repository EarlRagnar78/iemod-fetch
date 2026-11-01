"""
What each component of an install came to (GUI-AUDIT M8 item 69, ADR-0053):
not mod_installer's exit code alone, but WeiDU's own word on each component,
and WeiDU.log before and after.

Measured with the real mod_installer 16.0.0 and WeiDU v251: mod_installer
starts WeiDU with `--logapp --autolog --log-extern` (its default
`--weidu-log-mode`), so every WeiDU run of an install appends to one
WSETUP.DEBUG in the game folder. Each run is a block that opens with
`WeiDU v NNNNN Log` and the command line (`... mod/mod.tp2
--force-install-list 0 1 ...`), and has for each component
`Installing [Name]` and, once done, one of:

    SUCCESSFULLY INSTALLED      Name
    INSTALLED WITH WARNINGS     Name
    NOT INSTALLED DUE TO ERRORS Name

WeiDU.log is the authority on what is in the game: a component it lists is
installed, whatever the debug file says, and one it does not list is not.
The debug file adds why: with warnings, or not installed because of errors.

Pure: it reads texts; install_run reads the files.
"""
import re
from dataclasses import dataclass

from .prompts import Key, tp2_name

OK, WARNINGS, ERRORS = "installed", "installed with warnings", "not installed (errors)"
NOT_REACHED = "not reached"
_VERDICTS = {"SUCCESSFULLY INSTALLED": OK, "INSTALLED WITH WARNINGS": WARNINGS,
             "NOT INSTALLED DUE TO ERRORS": ERRORS}

_BLOCK = re.compile(r"^WeiDU v \d+ Log\s*$")
_COMMAND = re.compile(r"\s(?P<tp2>\S+\.tp2)\s.*?--force-install-list\s+(?P<numbers>[\d\s]+)",
                      re.IGNORECASE)
_INSTALLING = re.compile(r"^Installing \[(?P<name>.*?)\]")
_SKIPPING = re.compile(r"^SKIPPING: \[(?P<name>.*?)\]")       # REQUIRE_PREDICATE false
_VERDICT = re.compile(r"^(?P<verdict>SUCCESSFULLY INSTALLED|INSTALLED WITH WARNINGS|"
                      r"NOT INSTALLED DUE TO ERRORS)\s+(?P<name>.*?)\s*$")
# "Saving This Log:" - a component this run installed carries its name
_SAVED = re.compile(r"^(?P<tp2>\S+\.tp2)\s+\d+\s+(?P<number>\d+)\s+Installed\s+~(?P<name>.*)~\s*$",
                    re.IGNORECASE)
_LOG_LINE = re.compile(r"^\s*~(?P<path>[^~]+)~\s+#\d+\s+#(?P<number>\d+)")


@dataclass
class Result:
    key: Key                       # (tp2 file name, component number)
    name: str                      # as WeiDU names it, "" when not known
    status: str                    # OK | WARNINGS | ERRORS | NOT_REACHED
    note: str = ""                 # where the two sources disagree

    def as_dict(self) -> dict:
        return {"tp2": self.key[0], "component": self.key[1], "name": self.name,
                "status": self.status, "note": self.note}


def debug_verdicts(text: str) -> dict[Key, tuple[str, str]]:
    """{(tp2, number): (status, name)} from a WSETUP.DEBUG text.

    In each WeiDU run, its command line's components are taken in order by
    its `Installing [Name]` and `SKIPPING: [Name]` lines (measured: a
    component whose REQUIRE_PREDICATE fails gets `SKIPPING`, no verdict),
    and each verdict goes to the component it names. The `Installed ~Name~`
    lines WeiDU saves give the number of each one it installed exactly; where
    the order and those disagree - a component passed over without a word -
    only those exact numbers are kept, and a failure is left to the log
    (review of #109). A run cut short leaves its last component with no
    verdict."""
    out: dict[Key, tuple[str, str]] = {}
    block: list[str] = []

    def close() -> None:
        tp2, numbers = None, []
        taken: list[tuple[int, str, bool]] = []       # (number, name, installing)
        verdicts: list[tuple[str, str]] = []
        exact: dict[str, int] = {}
        for line in block:
            if tp2 is None and (command := _COMMAND.search(line)):
                tp2 = tp2_name(command["tp2"])
                numbers = [int(n) for n in command["numbers"].split()]
            elif (step := _INSTALLING.match(line)) or (step := _SKIPPING.match(line)):
                if len(taken) < len(numbers):
                    taken.append((numbers[len(taken)], step["name"],
                                  line.startswith("Installing")))
                else:
                    numbers = []                         # more steps than components
            elif ruling := _VERDICT.match(line):
                verdicts.append((ruling["verdict"], ruling["name"]))
            elif (saved := _SAVED.match(line)) and tp2 and tp2_name(saved["tp2"]) == tp2:
                exact[saved["name"]] = int(saved["number"])
        if tp2 is None:
            return
        ordered = bool(numbers) and all(exact.get(name, number) == number
                                        for number, name, _ in taken)
        pending = [(number, name) for number, name, installing in taken if installing]
        for verdict, said in verdicts:
            status = _VERDICTS[verdict]
            match = next((p for p in pending if p[1] == said), None) if ordered else None
            if match is not None:
                pending.remove(match)
                out[(tp2, match[0])] = (status, said)
            elif said in exact and status != ERRORS:
                out[(tp2, exact[said])] = (status, said)

    for line in text.splitlines():
        if _BLOCK.match(line):
            close()
            block = []
        else:
            block.append(line)
    close()
    return out


def log_keys(text: str) -> list[Key]:
    """The components a WeiDU.log lists, in order."""
    return [(tp2_name(m["path"]), int(m["number"]))
            for line in text.splitlines() if (m := _LOG_LINE.match(line))]


def results(planned: list[Key], log_before: str, log_after: str,
            debug_text: str) -> list[Result]:
    """
    What each planned component came to. WeiDU.log decides whether it is
    in: added since `log_before` and in `log_after`. The debug text says
    with warnings, or not installed because of errors; where it disagrees
    with the log, the log wins and the note says so.
    """
    before = set(log_keys(log_before))
    after = set(log_keys(log_after))
    verdicts = debug_verdicts(debug_text)
    out = []
    for key in planned:
        status, name = verdicts.get(key, ("", ""))
        if key in after and key not in before:
            if status == ERRORS:
                out.append(Result(key, name, OK, "WeiDU.log lists it, though the debug "
                                                 "file says it failed"))
            else:
                out.append(Result(key, name, status or OK,
                                  "" if status else "no word on it in the debug file"))
        elif key in before:
            out.append(Result(key, name, OK, "already installed before this run"))
        elif status in (OK, WARNINGS):
            out.append(Result(key, name, ERRORS, "the debug file says it went in, but "
                                                 "WeiDU.log does not list it"))
        elif status == ERRORS:
            out.append(Result(key, name, ERRORS))
        else:
            out.append(Result(key, name, NOT_REACHED))
    return out
