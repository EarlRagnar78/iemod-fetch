"""
selection.json: what a player chose, as an alternative to WeiDU.log (ADR-0030).

A WeiDU.log is a record of an install that happened, and it is the only input
the planners read. A UI starts from nothing: it needs to write down a choice
of mods, components and languages before anything is installed. That choice is
a selection, and it says exactly what a WeiDU.log says, so it converts to and
from one without loss - every planner reads a selection through that
conversion and none of them has to learn a second format.

    {"schema_version": 1,
     "installs": [
       {"game": "BGEE", "components": [
          {"tp2": "eefixpack/setup-eefixpack.tp2", "component": 0,
           "language": 0, "label": "Core Fixes"}]},
       {"game": "EET", "components": [...]}]}

One install, or two for EET: the pre-EET BGEE phase and the EET game. Each
install's components are in install order, like the lines of a log. `label`
is optional and kept as the log comment. Unknown keys are refused: a typo in
a hand-edited selection should fail loudly, not be ignored.
"""
import json
from dataclasses import dataclass, field
from collections.abc import Iterable

from .errors import ConfigError, UnsafeName
from .naming import safe_component
from .weidu import KNOWN_GAMES, ParsedLog

SCHEMA_VERSION = 1
_GAMES = {game.upper(): game for game in KNOWN_GAMES}
_TOP = {"schema_version", "installs"}
_INSTALL = {"game", "components"}
_COMPONENT = {"tp2", "component", "language", "label"}


@dataclass(frozen=True)
class Choice:
    tp2: str                 # folder/setup-mod.tp2, forward slashes
    component: int
    language: int = 0
    label: str = ""


@dataclass(frozen=True)
class RenderedLog:
    game: str
    name: str                # a file name for it: WeiDU-<game>.log
    text: str


@dataclass
class Install:
    game: str
    components: list[Choice] = field(default_factory=list)

    def weidu_log(self) -> RenderedLog:
        lines = ["// Log of Currently Installed WeiDU Mods",
                 "// The top of the file is the 'oldest' mod",
                 "// ~TP2_File~ #language_number #component_number // [Subcomponent Name -> ] Component Name [ : Version]",
                 f"// Written by iemod-fetch from selection.json ({self.game})"]
        for choice in self.components:
            line = f"~{choice.tp2.replace('/', chr(92))}~ #{choice.language} #{choice.component}"
            if choice.label:
                line += f" // {choice.label}"
            lines.append(line)
        return RenderedLog(self.game, f"WeiDU-{self.game}.log", "\n".join(lines) + "\n")


@dataclass
class Selection:
    installs: list[Install] = field(default_factory=list)

    def weidu_logs(self) -> list[RenderedLog]:
        return [install.weidu_log() for install in self.installs]

    def as_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION,
                "installs": [{"game": i.game,
                              "components": [_choice_dict(c) for c in i.components]}
                             for i in self.installs]}


def _choice_dict(choice: Choice) -> dict:
    out = {"tp2": choice.tp2, "component": choice.component,
           "language": choice.language}
    if choice.label:
        out["label"] = choice.label
    return out


def _unknown(obj: dict, allowed: set, where: str) -> None:
    extra = sorted(set(obj) - allowed)
    if extra:
        raise ConfigError(f"{where}: unknown key(s) {', '.join(extra)}")


def _int(value, where: str, name: str) -> int:
    # bool is an int in Python; `true` is not a component number.
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{where}: {name} must be a whole number, got {value!r}")
    return value


def _tp2(value, where: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{where}: tp2 must be a string, got {value!r}")
    parts = value.replace("\\", "/").split("/")
    try:
        for part in parts:
            if "~" in part:
                raise UnsafeName(f"'~' cannot appear in a WeiDU.log path: {part!r}")
            safe_component(part)
    except UnsafeName as exc:
        raise ConfigError(f"{where}: tp2 path {value!r} is unsafe: {exc}") from None
    if not parts[-1].lower().endswith(".tp2"):
        raise ConfigError(f"{where}: tp2 path {value!r} does not name a .tp2 file")
    return "/".join(parts)


def tp2_problem(value: str) -> str | None:
    """Why selection.json would refuse `value` as a tp2 path, or None."""
    try:
        _tp2(value, "tp2")
    except ConfigError as exc:
        return str(exc)
    return None


def one_line_label(text: str) -> str:
    """A component's name as selection.json can keep it: one line, no '~'."""
    return " ".join(text.replace("~", "-").split())


def _choice(obj, where: str) -> Choice:
    if not isinstance(obj, dict):
        raise ConfigError(f"{where}: a component is an object, got {obj!r}")
    _unknown(obj, _COMPONENT, where)
    for key in ("tp2", "component"):
        if key not in obj:
            raise ConfigError(f"{where}: missing {key}")
    label = obj.get("label", "")
    if not isinstance(label, str) or "~" in label or "\n" in label or "\r" in label:
        raise ConfigError(f"{where}: label must be one line of text without '~'")
    return Choice(tp2=_tp2(obj["tp2"], where),
                  component=_int(obj["component"], where, "component"),
                  language=_int(obj.get("language", 0), where, "language"),
                  label=label.strip())


def _install(obj, where: str) -> Install:
    if not isinstance(obj, dict):
        raise ConfigError(f"{where}: an install is an object, got {obj!r}")
    _unknown(obj, _INSTALL, where)
    game = _GAMES.get(str(obj.get("game", "")).upper())
    if game is None:
        raise ConfigError(f"{where}: unknown game {obj.get('game')!r}; "
                          f"one of {', '.join(KNOWN_GAMES)}")
    components = obj.get("components")
    if not isinstance(components, list):
        raise ConfigError(f"{where}: components must be a list")
    return Install(game, [_choice(c, f"{where}.components[{n}]")
                          for n, c in enumerate(components)])


def parse_selection(text: str, source: str = "selection.json") -> Selection:
    """Read and validate a selection. Every refusal names where and why."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ConfigError(f"{source}: not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{source}: the top level is an object")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ConfigError(f"{source}: schema_version {data.get('schema_version')!r} "
                          f"is not supported; this version reads {SCHEMA_VERSION}")
    _unknown(data, _TOP, source)
    installs = data.get("installs")
    if not isinstance(installs, list) or not installs:
        raise ConfigError(f"{source}: installs must list at least one install")
    if len(installs) > 2:
        raise ConfigError(f"{source}: at most two installs (the pre-EET BGEE "
                          f"phase and the EET game)")
    selection = Selection([_install(obj, f"{source}: installs[{n}]")
                           for n, obj in enumerate(installs)])
    if len(selection.installs) == 2:
        games = sorted(i.game for i in selection.installs)
        if games != ["BGEE", "EET"]:
            raise ConfigError(f"{source}: two installs are an EET setup: one BGEE "
                              f"and one EET, got {', '.join(games)}")
    return selection


def selection_to_json(selection: Selection) -> str:
    return json.dumps(selection.as_dict(), indent=2) + "\n"


def selection_from_logs(logs: Iterable[tuple[str | None, ParsedLog]]) -> Selection:
    """A selection saying what these logs say: (game, parsed log) per install."""
    installs = []
    for game, parsed in logs:
        name = game or parsed.game or parsed.detect_game()
        if name is None:
            raise ConfigError("which game a log installs is needed for a selection: "
                              "name it, e.g. -w WeiDU.log:BG2EE")
        choices = sorted((c for mod in parsed.mods.values() for c in mod.components),
                         key=lambda c: c.line)
        installs.append(Install(_GAMES[name.upper()], [
            Choice(tp2=(c.path or f"{c.folder}/{c.tp2_file}").replace("\\", "/"),
                   component=c.index, language=c.language, label=c.comment)
            for c in choices]))
    return Selection(installs)
