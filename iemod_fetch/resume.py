"""
Resuming an install that stopped (GUI-AUDIT M4 item 23, ADR-0045): the
game's own WeiDU.log is the state.

WeiDU writes a component's line into the game's WeiDU.log once it is in, so
after a failure or a Cancel the log holds what went in, in order. An install
can go on from there when that is the planned log's beginning - the same
components, in the same order: the same tp2 (its path, case and separators
aside: WeiDU writes `EET\\EET.TP2` on Windows, `EET/EET.TP2` elsewhere), the
same language number and the same component number. A component installed
in another language is another install. Then only the rest is handed to
mod_installer. Its own skip (--skip-installed) is not relied on:
16.0.0 reads `weidu.log` in lower case, so on Linux it skips nothing and
installs everything again (measured).

Anything else - a component the plan does not have, another order, an
installed one missing in the middle - is not resumed. What is in the game
is then not what the plan says, and the backup is how to start again. Nor
is a component stopped half-way (install_run finds WeiDU's uninstall record
of it): installing it again, WeiDU backs up its leftovers as the game's own.

Pure: it reads texts and returns words and lines, no file is touched.
"""
import re
from dataclasses import dataclass, field

# ~path~ #language #component, the start of a WeiDU.log component line
_LINE = re.compile(r"^\s*~(?P<path>[^~]+)~\s+#(?P<lang>\d+)\s+#(?P<number>\d+)")
SHOWN = 5                        # divergent lines named, the rest counted

Line = tuple[str, int, int]      # (tp2 path normalised, language, component)

HEADER = ("// Log of Currently Installed WeiDU Mods\n"
          "// The top of the file is the 'oldest' mod\n"
          "// ~TP2_File~ #language_number #component_number // "
          "[Subcomponent Name -> ] Component Name [ : Version]\n")


@dataclass
class Progress:
    """How far one planned log went in its game."""
    planned: list[Line]
    lines: list[str]                  # the planned log's component lines
    installed: list[Line]
    problem: str | None = None        # why it cannot be resumed; None when it can
    done: int = 0                     # planned components already in, from the top

    @property
    def total(self) -> int:
        return len(self.planned)

    @property
    def fresh(self) -> bool:
        return not self.installed

    @property
    def finished(self) -> bool:
        return self.problem is None and self.done == self.total

    @property
    def next(self) -> str | None:
        """The first planned component still to install, by tp2 and number."""
        if self.problem is not None or self.done >= self.total:
            return None
        path, _language, number = self.planned[self.done]
        return f"{path} #{number}"

    def rest(self) -> str:
        """The planned log's lines still to install, as a log mod_installer reads."""
        return HEADER + "".join(line + "\n" for line in self.lines[self.done:])


def _path(path: str) -> str:
    """`EET\\EET.TP2`, `./eet/eet.tp2` -> `eet/eet.tp2`."""
    path = path.strip().replace("\\", "/").lower()
    while path.startswith("./"):
        path = path[2:]
    return path


def components(log_text: str) -> list[tuple[Line, str]]:
    """Each component line of a WeiDU.log, in order, with what identifies it."""
    out = []
    for line in log_text.splitlines():
        match = _LINE.match(line)
        if match:
            out.append(((_path(match["path"]), int(match["lang"]), int(match["number"])),
                        line))
    return out


def _name(key: Line) -> str:
    return f"{key[0]} #{key[1]} #{key[2]}"


def _diverging(installed: list[Line], planned: list[Line]) -> list[str]:
    """Each line where the game and the plan differ, in the game's words."""
    out = []
    for n, key in enumerate(installed):
        if n >= len(planned):
            out.append(f"line {n + 1}: the game has {_name(key)} where the plan has nothing")
        elif key != planned[n]:
            out.append(f"line {n + 1}: the game has {_name(key)} where the plan has "
                       f"{_name(planned[n])}")
    return out


def progress(plan_text: str, installed_text: str) -> Progress:
    """The game's log (`installed_text`, "" when it has none) against the plan."""
    planned = components(plan_text)
    installed = [key for key, _line in components(installed_text)]
    keys, lines = [key for key, _ in planned], [line for _, line in planned]
    found = Progress(keys, lines, installed)
    diverging = _diverging(installed, keys)
    if diverging:
        more = len(diverging) - SHOWN
        found.problem = ("the game is not this plan's install - "
                         + "; ".join(diverging[:SHOWN])
                         + (f"; and {more} more line(s)" if more > 0 else ""))
        return found
    found.done = len(installed)
    return found


def half_way(component: str, record: str) -> str:
    """Why a component stopped inside is not resumed: WeiDU installing it
    again backs up the files it left as if they were the game's own, so
    uninstalling it later would put the mod's files back, not the game's
    (measured with WeiDU 251)."""
    return (f"{component} stopped half-way: its files are in the game but not in "
            f"WeiDU.log ({record}); installing it again would make WeiDU keep them as "
            f"the originals")


@dataclass
class Resume:
    """The install's state across its logs, and how to go on."""
    phases: dict[str, Progress] = field(default_factory=dict)   # log name -> progress, in order

    @property
    def problem(self) -> str | None:
        """Why it cannot be resumed. The phases go in order (EET: BG:EE's log,
        then EET's), so a later one holding components while an earlier one
        is not finished is not this plan's install either."""
        for name, phase in self.phases.items():
            if phase.problem:
                return f"{name}: {phase.problem}"
        unfinished = None
        for name, phase in self.phases.items():
            if unfinished is not None and not phase.fresh:
                earlier, left = unfinished
                return (f"{name}: the game has {len(phase.installed)} component(s) while "
                        f"{earlier} is not finished ({left.done} of {left.total} in): the "
                        f"game is not this plan's install")
            if unfinished is None and not phase.finished:
                unfinished = (name, phase)
        return None

    @property
    def state(self) -> str:
        """'fresh', 'partial', 'finished' or 'mismatch'."""
        if self.problem:
            return "mismatch"
        if all(phase.fresh for phase in self.phases.values()):
            return "fresh"
        if all(phase.finished for phase in self.phases.values()):
            return "finished"
        return "partial"

    @property
    def done(self) -> int:
        return sum(phase.done for phase in self.phases.values())

    @property
    def total(self) -> int:
        return sum(phase.total for phase in self.phases.values())
