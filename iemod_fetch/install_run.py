"""
Running the install: mod_installer, as a child of this program (GUI-AUDIT M4
item 22, ADR-0045, amending ADR-0022).

The command line still only writes the scripts; this is what the wizard's
Installation phase runs, once the player has said so. It starts the same
mod_installer command the scripts start, after the checks the scripts make
(a game folder, a game with no mods yet, mixed-case mod folders on Linux),
reads its output line by line and passes each one on, and answers WeiDU's
questions: EET's question for the BG:EE folder with that folder, then the
answers the planned log records for the batch being installed
(`// @wlb-inputs:`), and anything else by asking the player. Nothing it
downloaded is started by this program: mod_installer starts WeiDU, and
WeiDU runs the mods' tp2s - which is what installing them means.

Cancelling stops mod_installer and everything it started - WeiDU above all,
which would otherwise go on writing into the game folder: mod_installer runs
in a process group of its own (a session on POSIX, a new process group on
Windows), which is terminated, then killed after a grace period (POSIX:
killpg; Windows: `taskkill /T /F`). The WeiDU.log in the game folder says
what was installed: resuming from it is item 23.
"""
import contextlib
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from . import gamelock, mi_parser, resume
from . import results as verdicts
from .atomic import write_text
from . import childenv
from .childenv import child_env
from .errors import ConfigError
from .prompts import (EET_FOLDER_QUESTION, Answers, Event, Key, OutputReader,
                      match_question, question_line, recorded_answers)

# What the planned logs are called (ordering.PRE_EET_LOG, EET_LOG)
PRE_EET_LOG, EET_LOG = "WeiDU-BGEE.log", "WeiDU.log"
QUIET_S = 0.5            # no output for this long after a question: it is complete
GRACE_S = 10.0           # terminate, then kill after this long
DRAIN_S = 2.0            # its output still open this long after it ended: stop the rest
# No output for this long and no question: said, never acted on (ADR-0049
# point 4). Provisional: no real install's silences were measured yet - each
# run records its longest per batch (results.json "silences") to set it.
SILENT_S = 600.0


@dataclass
class Answered:
    question: str
    answer: str
    source: str           # "EET" | "recorded" | "by question" | "player"


@dataclass
class Outcome:
    returncode: int | None
    cancelled: bool = False
    answered: list[Answered] = field(default_factory=list)
    # what each planned component came to, by WeiDU.log and WeiDU's debug
    # file (item 69, ADR-0053); `ok` stays mod_installer's exit code
    results: list[verdicts.Result] = field(default_factory=list)
    # the longest stretch without output in each batch, in seconds (the
    # watchdog's measurement, ADR-0049 point 4)
    silences: list[tuple[tuple, float]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.cancelled


ASKED_FILE = "answers.json"


RESULTS_FILE = "results.json"
PARSER_DIR = "mod_installer-config"   # ADR-0057, beside the plan
DEBUG_FILE = "WSETUP.DEBUG"     # WeiDU's --autolog, appended to (--logapp)


def save_results(path: str | None, found: list,
                 silences: Sequence[tuple[tuple, float]] = ()) -> None:
    """What each component came to (item 69), for the player and a bug
    report; written on every run, like answers.json. `silences`: each
    batch's longest stretch without output (the watchdog's measurement)."""
    if path:
        data: dict = {"v": 1, "components": [r.as_dict() for r in found]}
        if silences:
            data["silences"] = [{"batch": [f"{tp2} #{number}" for tp2, number in batch],
                                 "seconds": round(seconds, 1)} for batch, seconds in silences]
        with contextlib.suppress(OSError):
            write_text(path, json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def phases(plan_dir: str, games: dict[str, str]) -> list[tuple[str, str]]:
    """(planned log, game folder) for each game mod_installer installs into,
    as command() gives them to it."""
    if "EET" in games and "BGEE" in games:
        return [(os.path.join(plan_dir, PRE_EET_LOG), games["BGEE"]),
                (os.path.join(plan_dir, EET_LOG), games["EET"])]
    if len(games) != 1:
        raise ConfigError(f"one game, or BG:EE and EET, are installed into; not "
                          f"{', '.join(games) or 'none'}")
    (game, folder), = games.items()
    log = PRE_EET_LOG if game == "BGEE" and not os.path.isfile(
        os.path.join(plan_dir, EET_LOG)) else EET_LOG
    return [(os.path.join(plan_dir, log), folder)]


def _read(path: str, start: int = 0) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(start)
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


class _Phase:
    """One game's WeiDU.log and debug file as they were before the run, to
    read what the run added (item 69)."""

    def __init__(self, plan_log: str, folder: str) -> None:
        self.planned = verdicts.log_keys(_read(plan_log))
        self.log = os.path.join(folder, "WeiDU.log")
        self.debug = os.path.join(folder, DEBUG_FILE)
        self.log_before = _read(self.log)
        self.debug_from = _size(self.debug)

    def results(self) -> list[verdicts.Result]:
        # appended to: what this run wrote starts where it ended; a file
        # that shrank was replaced, and is read whole
        start = self.debug_from if _size(self.debug) >= self.debug_from else 0
        return verdicts.results(self.planned, self.log_before, _read(self.log),
                               _read(self.debug, start))


def save_answered(path: str | None, answered: list) -> None:
    """What this install answered, for the player and a bug report (item 63):
    each question's last line, the answer, where it came from. Written on
    every run, empty too, so a run that answered nothing does not leave an
    earlier run's record; on a resume it holds the resumed part only. A
    record only: nothing reads it back to decide."""
    if path:
        data = {"v": 1, "answered": [
            {"question": question_line(a.question), "answer": a.answer, "source": a.source}
            for a in answered]}
        with contextlib.suppress(OSError):
            write_text(path, json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def _has_mods(game_dir: str) -> str:
    """The WeiDU.log of a game that already has mods installed, else ''."""
    for name in ("WeiDU.log", "weidu.log"):
        path = os.path.join(game_dir, name)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                if any(line.startswith("~") for line in fh):
                    return path
        except OSError:
            continue
    return ""


# mod_installer reads each of its options from an environment variable too
# (clap's `env`, read from its 16.0.0 source: config/args.rs and options.rs).
# One the command line does not set would come from the player's environment
# - NEW_EET_DIR or OVERWRITE change what the install does - so none reaches it
# (review of #86). Its OCAMLRUNPARAM option is WeiDU's memory tuning.
MOD_INSTALLER_ENV = (
    "ABORT_ON_WARNINGS", "BATCH_MODE", "BATCH_SIZE", "BATCH_SKIP", "BG1_GAME_DIRECTORY",
    "BG1_LOG_FILE", "BG2_GAME_DIRECTORY", "BG2_LOG_FILE", "CASEFOLD", "CHECK_LAST_INSTALLED",
    "DEPTH", "DOWNLOAD", "FETCH_WEIDU_BINARY", "GAME_DIRECTORY", "GENERATE_DIRECTORY",
    "LOG_FILE", "LOOKBACK", "MOD_DIRECTORIES", "NEVER_ABORT", "NEW_EET_DIR",
    "NEW_PRE_EET_DIR", "OCAMLRUNPARAM", "OVERWRITE", "SKIP_INSTALLED", "STRICT_MATCHING",
    "TICK", "TIMEOUT", "WEIDU_BINARY", "WEIDU_LOG_MODE")


def version_of(program: str, config_dir: str) -> str:
    """The version `program --version` says (mod_installer 16.0.0 prints
    "mod_installer 16.0.0"), "" when it says none: the parser config is
    written only for the version whose defaults it carries (ADR-0057).
    mod_installer loads, and on a mismatch rewrites, its parser config before
    it reads its arguments (src/main.rs): it is pointed at `config_dir`, the
    install's own folder, never the player's (review of #120)."""
    try:
        out = childenv.run([program, "--version"], capture_output=True,  # noqa: S603
                           text=True, encoding="utf-8", errors="replace", timeout=20,
                           check=False, stdin=subprocess.DEVNULL,
                           env={**mod_installer_env(),
                                **mi_parser.environment(config_dir)}).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    words = out.split()
    return words[1] if len(words) >= 2 and words[0] == mi_parser.APP else ""


def mod_installer_env() -> dict[str, str]:
    """The child's environment (childenv) without mod_installer's options,
    logging at info so its batches and questions are seen."""
    env = child_env({"RUST_LOG": "info"}) or dict(os.environ)
    drop = {name.upper() for name in MOD_INSTALLER_ENV}
    return {key: value for key, value in env.items() if key.upper() not in drop}


def _program(path: str) -> bool:
    """A file this system runs: executable on POSIX; on Windows, where every
    file reads as executable, by its extension (PATHEXT)."""
    if not os.path.isfile(path):
        return False
    if sys.platform == "win32":
        known = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").lower().split(";")
        return os.path.splitext(path)[1].lower() in known
    return os.access(path, os.X_OK)


def preflight(games: dict[str, str], mods_dir: str, mod_installer: str, weidu: str,
              allow_existing: bool = False,
              in_use: Callable[[dict[str, str]], list[str]] = gamelock.problems) -> list[str]:
    """What stops the install before it starts, in words; [] when nothing.
    `in_use`: what says a game is running (gamelock, item 67)."""
    problems = []
    for name, folder in games.items():
        if not os.path.isdir(folder):
            problems.append(f"{name}: {folder} is not a folder")
        elif not os.path.isfile(os.path.join(folder, "chitin.key")):
            problems.append(f"{name}: no chitin.key in {folder} - not a game folder")
        elif not allow_existing and (installed := _has_mods(folder)):
            problems.append(f"{name}: {folder} already has mods installed "
                            f"({installed}); the plan is for a fresh game - "
                            "restore its backup first")
    if not os.path.isdir(mods_dir):
        problems.append(f"the mods folder {mods_dir} does not exist - download first")
    elif sys.platform.startswith("linux"):
        # mod_installer hands WeiDU lower-cased paths (ADR-0022)
        mixed = next((entry for entry in sorted(os.listdir(mods_dir))
                      if entry != entry.lower() and not entry.startswith(".")), None)
        if mixed:
            problems.append(f"mods must be lower-case on Linux: {mixed} in {mods_dir}")
    # An accented BG:EE folder is not refused: EET is told it through WeiDU's
    # input, as UTF-8, and the real WeiDU v251 opens it so on Windows too
    # (measured in CI, item 22b; ADR-0046).
    for name, path in (("mod_installer", mod_installer), ("WeiDU", weidu)):
        if not _program(path):
            problems.append(f"{name} is not a program here: {path}")
    problems += in_use({name: folder for name, folder in games.items()
                        if os.path.isdir(folder)})
    return problems


def command(plan_dir: str, games: dict[str, str], mods_dir: str, mod_installer: str,
            weidu: str, language: str = "en_US") -> list[str]:
    """mod_installer's command for a planned install, as the scripts write it
    but for --download.
    `games` is {"BGEE": ..., "EET": ...} for EET, else one game."""
    # --download=false: a mod missing is an error, not mod_installer asking for
    # a URL and downloading it itself (ADR-0046) - the generated scripts leave
    # that to the player at their terminal. --skip-installed=false: its skip
    # reads `weidu.log` in lower case (16.0.0), so on Linux it skips nothing
    # while elsewhere it would; what is left to install is worked out here
    # (resume.py), the same on every system (item 23)
    tail = ["--mod-directories", mods_dir, "--weidu-binary", weidu, "--language", language,
            "--download=false", "--skip-installed=false"]
    if "EET" in games and "BGEE" in games:
        return [mod_installer, "eet",
                "--bg1-game-directory", games["BGEE"],
                "--bg1-log-file", os.path.join(plan_dir, PRE_EET_LOG),
                "--bg2-game-directory", games["EET"],
                "--bg2-log-file", os.path.join(plan_dir, EET_LOG), *tail]
    (game, folder), = games.items()
    log = PRE_EET_LOG if game == "BGEE" and not os.path.isfile(
        os.path.join(plan_dir, EET_LOG)) else EET_LOG
    return [mod_installer, "normal", "--game-directory", folder,
            "--log-file", os.path.join(plan_dir, log), *tail]


class InstallRun:
    """
    One run of mod_installer. `on_event` gets every line, batch and answer;
    `ask(question, batch)` is called for a question nothing recorded answers,
    from the thread that called run(), and returns the answer - None cancels.
    """

    def __init__(self, argv: list[str], logs: list[str], cwd: str,
                 ask: Callable[[str, tuple], str | None],
                 on_event: Callable[[Event], None] = lambda _event: None,
                 bgee_dir: str | None = None, quiet_s: float = QUIET_S,
                 grace_s: float = GRACE_S, drain_s: float = DRAIN_S,
                 silent_s: float = SILENT_S,
                 games: dict[str, str] | None = None, tools: tuple[str, ...] = (),
                 running: Callable[[], list[gamelock.Running] | None] = gamelock.running_executables,
                 asked_file: str | None = None,
                 phases: list[tuple[str, str]] | None = None,
                 results_file: str | None = None,
                 expected: dict[Key, list[tuple[str, str]]] | None = None,
                 by_key: dict[Key, dict[str, str]] | None = None,
                 row_keys: dict[Key, list[str]] | None = None,
                 parser_dir: str | None = None,
                 raw_texts: dict[tuple[Key, str], str] | None = None) -> None:
        recorded: dict = {}
        for path in logs:
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    recorded.update(recorded_answers(fh.read()))
            except OSError:
                continue
        self.argv, self.cwd, self.ask, self.on_event = argv, cwd, ask, on_event
        self.bgee_dir = bgee_dir
        self.asked_file = asked_file          # what was answered, recorded (item 63)
        # item 69: each game's log and debug file as they were before
        self._phases = [_Phase(log, folder) for log, folder in phases or []]
        self.results_file = results_file
        # item 67: a game started during the run is said at the next batch
        self.games, self.tools, self.running = games or {}, tools, running
        self._said: set[str] = set()
        # item 48 (ADR-0049): each component's questions, (key, text) in the
        # order its files ask them, and the player's answers by key
        self.expected = expected or {}
        self.by_key = by_key or {}
        self._given: set[tuple[Key, str]] = set()      # answered by key in this batch
        # the question of each recorded answer, only for the rows this program
        # wrote in that order (an Orchestrator log records them as asked)
        self.answers = Answers(recorded, row_keys or {})
        self.quiet_s, self.grace_s, self.drain_s = quiet_s, grace_s, drain_s
        self.silent_s = silent_s
        # ADR-0057: mod_installer's parser config for this install, with the
        # expected questions it would not ask; the phrases added
        self.parser_dir = parser_dir
        # each expected question as WeiDU prints it, by (component, key): its
        # lines and spaces, which the phrase is taken from; else its text
        self.raw_texts = raw_texts or {}
        self.parser_phrases: list[str] = []
        self._cancel = threading.Event()
        self._process: subprocess.Popen | None = None
        self._job = _Job()

    def _raw(self) -> list[str]:
        """Every expected question as WeiDU prints it - never the text with
        its spaces collapsed, whose phrase may match no line (review of #120)."""
        return [raw for raw in self.raw_texts.values() if raw]

    def cancel(self) -> None:
        """Stop the install, from any thread."""
        self._cancel.set()

    def run(self) -> Outcome:
        outcome = Outcome(None)
        # Its own process group (POSIX) or job (Windows): cancelling, or its
        # end, must reach WeiDU and whatever else it started too.
        group: dict = {"start_new_session": True}
        if sys.platform == "win32":
            group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        env = mod_installer_env()
        # only the mod_installer whose defaults the file carries uses it
        if self.parser_dir and version_of(self.argv[0], self.parser_dir) == mi_parser.VERSION:
            try:
                extra, self.parser_phrases = mi_parser.write(self.parser_dir, self._raw())
                env.update(extra)
            except OSError:
                self.parser_phrases = []   # its defaults: as without the config
        try:
            process = childenv.popen(  # the player's own mod_installer
                self.argv, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, env=env,
                text=True, encoding="utf-8", errors="replace", bufsize=1, **group)
        except OSError:
            # it never started: an earlier run's record must not stay (review of #98)
            save_answered(self.asked_file, [])
            save_results(self.results_file, [])
            raise
        self._process = process
        self._job = _Job.holding(process)
        try:
            self._pump(process, outcome)
        finally:
            save_answered(self.asked_file, outcome.answered)
            # Only standard input is closed here: the output belongs to the
            # thread reading it, which closes it at its end. Closing it from
            # here while that thread waits on it would wait as long as anything
            # mod_installer started keeps it open (review of the tree kill).
            with contextlib.suppress(OSError):
                if process.stdin is not None:
                    process.stdin.close()
            outcome.returncode = process.wait()
            self._job.close()
            outcome.results = [r for phase in self._phases for r in phase.results()]
            save_results(self.results_file, outcome.results, outcome.silences)
        return outcome

    def _pump(self, process: subprocess.Popen, outcome: Outcome) -> None:
        """Read the output until it ends, answering and cancelling as it goes."""
        lines: queue.Queue[str | None] = queue.Queue()
        stdout = process.stdout

        def read() -> None:
            if stdout is not None:
                with stdout:
                    for line in stdout:
                        lines.put(line)
            lines.put(None)
        threading.Thread(target=read, daemon=True).start()
        reader = OutputReader()
        exited_at: float | None = None
        last_output, warned = time.monotonic(), False
        recent: list[str] = []                       # the last lines, for a warning
        batch: tuple = ()
        longest = 0.0

        def close_batch(up_to_now: bool = True) -> None:
            """Record the batch's longest silence; `up_to_now`: count the one
            still going (not when the player was the one being waited on)."""
            if batch:
                now = time.monotonic() - last_output if up_to_now else 0.0
                outcome.silences.append((batch, max(longest, now)))

        def watch() -> None:
            """The silence so far, measured and said once past the threshold:
            on every pass, so dots arriving faster than the queue's wait do not
            keep it from being looked at (second review of #115)."""
            nonlocal longest, warned
            silent = time.monotonic() - last_output
            longest = max(longest, silent)
            if not warned and not reader.asking and silent >= self.silent_s:
                warned = True
                self.on_event(Event("watchdog", self._silence_text(silent, recent, batch),
                                    batch))
        while True:
            if self._cancel.is_set():
                self._stop(process)
                outcome.cancelled = True
                close_batch()
                return
            if exited_at is None and process.poll() is not None:
                exited_at = time.monotonic()
            if exited_at is not None and time.monotonic() - exited_at > self.drain_s:
                # mod_installer has ended and something it started still holds
                # its output (review of #83): what is left would go on writing
                # into the game folder, alone - it is stopped, and said so.
                self._stop(process)
                self.on_event(Event("line", "mod_installer ended, but what it started "
                                            "was still running: stopped"))
                close_batch()
                return
            try:
                line = lines.get(timeout=self.quiet_s if reader.asking
                                 else min(self.quiet_s, 0.1))
            except queue.Empty:
                question = reader.question() if reader.asking else None
                if question is not None:
                    if not self._answer(process, question, outcome):
                        self._stop(process)
                        outcome.cancelled = True
                        close_batch(up_to_now=False)    # the player's time is not silence
                        return
                    # answered: alive; its window is not the last output any
                    # more (a silence after it is not that question waiting)
                    last_output, warned, recent = time.monotonic(), False, []
                    continue
                watch()
                continue
            if line is None:
                longest = max(longest, time.monotonic() - last_output)
                close_batch()
                return
            events = reader.feed(line)
            if events:
                # a line that says something; mod_installer 12.1.1's rows of
                # dots (no events) are not output - they come exactly while
                # WeiDU is silent (review of #115)
                longest = max(longest, time.monotonic() - last_output)
                last_output, warned = time.monotonic(), False
                if line.strip():
                    recent = (recent + [line.rstrip()])[-5:]
            for event in events:
                if event.kind == "batch":
                    close_batch()
                    batch, longest = event.batch, 0.0
                    self.answers.start(event.batch)
                    self._given = set()
                self.on_event(event)
                if event.kind == "batch":
                    self._game_started(event.batch)
            if not events:
                watch()                            # a dot: still silent

    def _silence_text(self, silent: float, recent: list[str], batch: tuple) -> str:
        """What the watchdog says (ADR-0049 point 4): how long, what it may
        be, the last lines - and the question mod_installer did not put to
        anyone when the last line is one the batch's mods ask."""
        minutes = f"{silent / 60:.0f} minute(s)" if silent >= 60 else f"{silent:.1f} s"
        expected = [(component, key, text) for component in batch
                    for key, text in self.expected.get(component, ())]
        window = "\n".join(recent)
        found = match_question(window, expected) if expected and window else None
        asked = {(c, k): t for c, k, t in expected}
        if found is not None and not mi_parser.asked(
                self.raw_texts.get(found) or asked.get(found, ""), self.parser_phrases):
            what = ("WeiDU seems to be waiting for an answer to a question mod_installer "
                    "does not put to anyone (it asks only questions with words such as "
                    "\"enter\" or \"choose\"): it will wait until mod_installer's timeout. "
                    "Cancel and install that mod by hand, or wait.")
        else:
            what = ("WeiDU may be working without a word (some components take long), or "
                    "waiting for an answer mod_installer did not recognise. Nothing is "
                    "stopped.")
        last = "\n".join(f"    {line}" for line in recent) or "    (no output yet)"
        return f"No output for {minutes}. {what} The last lines:\n{last}"

    def _game_started(self, batch: tuple) -> None:
        """Say once each program found running from a game folder at a
        batch: mod_installer has started this batch's WeiDU already, so it
        cannot be held back - only explained if WeiDU then fails (ADR-0051)."""
        if not self.games:
            return
        for line in gamelock.running_in(self.games, self.running(), ignore=self.tools):
            if line not in self._said:
                self._said.add(line)
                self.on_event(Event("line", f"warning: {line} is running from the game "
                                            "folder while it is installed into - WeiDU "
                                            "fails if it cannot write dialog.tlk; close "
                                            "it", batch))

    def _answer(self, process: subprocess.Popen, question: Event, outcome: Outcome) -> bool:
        """Answer `question`; False when the player cancelled instead."""
        text = question.text
        if self.bgee_dir and EET_FOLDER_QUESTION in text.lower():
            answer, source = self.bgee_dir, "EET"
        else:
            known = self._by_question(text, question.batch)
            if known is not None:
                answer, source = known
            else:
                given = self.ask(text, question.batch)
                if given is None:
                    return False
                answer, source = given, "player"
        try:
            if process.stdin is None:
                raise OSError("no standard input")
            process.stdin.write(answer + "\n")
            process.stdin.flush()
        except OSError:
            return True                   # it ended meanwhile: its exit code says how
        outcome.answered.append(Answered(text, answer, source))
        self.on_event(Event("answer", f"{answer}  ({source})", question.batch))
        return True

    def _by_question(self, text: str, batch: tuple) -> tuple[str, str] | None:
        """
        The answer to give without asking, and where it came from. A question
        recognised by its expected text (match_question) is answered by its
        key - the player's answer for it, else the log's recorded answer for
        that very question - and when neither has one it is asked: a
        recorded answer meant for another question is never given to it.
        One not recognised takes the next recorded answer, as ADR-0045 does.
        """
        expected = [(component, key, question) for component in batch
                    for key, question in self.expected.get(component, ())]
        found = match_question(text, expected) if expected else None
        if found is None:
            recorded = self.answers.next()
            return (recorded, "recorded") if recorded is not None else None
        component, key = found
        positional = self.answers.take(component, key)       # kept in step
        stored = self.by_key.get(component, {}).get(key)
        if (component, key) in self._given:
            # asked again in this batch: a loop refusing the answer, or a
            # question asked on purpose several times - the player answers
            # (review of #111: never the same stored answer forever)
            return (positional, "recorded") if positional is not None else None
        if stored is not None:
            self._given.add((component, key))
            return stored, "by question"
        if positional is None and not self.answers.keyed(component):
            # another tool's row (answers as asked): in order, as before
            positional = self.answers.next()
        return (positional, "recorded") if positional is not None else None

    def _stop(self, process: subprocess.Popen) -> None:
        """Stop mod_installer and what it started: terminate, then kill."""
        if process.poll() is None:
            self._signal(process, kill=False)
            deadline = time.monotonic() + self.grace_s
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
        # WeiDU may outlive mod_installer: the group goes, whatever is left of it
        self._signal(process, kill=True)

    def _signal(self, process: subprocess.Popen, kill: bool) -> None:
        """Terminate (or kill) mod_installer's process group, or its job."""
        if sys.platform == "win32":
            if kill:
                # the job holds every process it started, living parent or not
                self._job.terminate()
            elif process.poll() is None:
                process.send_signal(signal.CTRL_BREAK_EVENT)
            return
        with contextlib.suppress(ProcessLookupError, PermissionError):   # gone already
            os.killpg(process.pid, signal.SIGKILL if kill else signal.SIGTERM)


class _Job:
    """
    Windows: a Job Object holding mod_installer and every process it starts
    (they inherit it), killed together whatever order they die in - taskkill
    /T walks the tree from a living parent, and finds nothing once
    mod_installer is gone (review of #83). It is also killed when this
    program ends (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE). Elsewhere it does
    nothing: the process group does this.
    """

    def __init__(self, handle: int | None = None) -> None:
        self.handle = handle

    @classmethod
    def holding(cls, process: subprocess.Popen) -> _Job:
        return cls(_new_job(process)) if sys.platform == "win32" else cls()

    def terminate(self) -> None:
        if self.handle and sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            ctypes.WinDLL("kernel32").TerminateJobObject(wintypes.HANDLE(self.handle), 1)

    def close(self) -> None:
        if self.handle and sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            ctypes.WinDLL("kernel32").CloseHandle(wintypes.HANDLE(self.handle))
        self.handle = None


def _new_job(process: subprocess.Popen) -> int:
    """A kill-on-close Job Object, `process` in it (Windows only)."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic),
                        ("IoInfo", ctypes.c_ulonglong * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000   # KILL_ON_JOB_CLOSE
        ok = kernel32.SetInformationJobObject(
            wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))
        ok = ok and kernel32.AssignProcessToJobObject(
            wintypes.HANDLE(job), wintypes.HANDLE(int(process._handle)))  # noqa: SLF001
        if not ok:
            error = ctypes.get_last_error()
            kernel32.CloseHandle(wintypes.HANDLE(job))
            process.kill()
            raise OSError(error, "mod_installer could not be put in a job")
        return job
    raise OSError("Job Objects are Windows'")


RESUME_DIR = "resume"


def _game_log(folder: str) -> str:
    """The game's own WeiDU.log ("" when it has none), whatever its case."""
    for name in ("WeiDU.log", "weidu.log", "WEIDU.LOG"):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
    return ""


def _phases(plan_dir: str, games: dict[str, str]) -> list[tuple[str, str]]:
    """(planned log, game folder) for each log the install runs, in order."""
    if "EET" in games and "BGEE" in games:
        pairs = [(PRE_EET_LOG, games["BGEE"]), (EET_LOG, games["EET"])]
    else:
        (game, folder), = games.items()
        log = PRE_EET_LOG if game == "BGEE" and not os.path.isfile(
            os.path.join(plan_dir, EET_LOG)) else EET_LOG
        pairs = [(log, folder)]
    return [(log, folder) for log, folder in pairs
            if os.path.isfile(os.path.join(plan_dir, log))]


def _in_folder(base: str, relative: str) -> str | None:
    """`relative` under `base`, each part matched whatever its case (WeiDU
    and the mods mix them; Linux does not); None when it is not there."""
    path = base
    for part in relative.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == ".." or not os.path.isdir(path):
            return None
        exact = os.path.join(path, part)
        if os.path.exists(exact):
            path = exact
            continue
        found = [name for name in os.listdir(path) if name.lower() == part.lower()]
        if not found:
            return None
        path = os.path.join(path, found[0])
    return path


_BACKUP = re.compile(r"^\s*BACKUP\s+(?P<q>[~\"])(?P<dir>[^~\"]+)(?P=q)", re.MULTILINE)


def _left_half_way(folder: str, tp2: str, number: int) -> str | None:
    """
    The uninstall record a component stopped half-way leaves in the game:
    WeiDU keeps <its BACKUP folder>/<n>/UNINSTALL.<n> from the component's
    start, and writes its WeiDU.log line only at its end. Measured with
    WeiDU 251, a Cancel inside a component: the files it had copied stay in
    the game, the record lists them, the log does not.
    """
    tp2_path = _in_folder(folder, tp2)
    backup = None
    if tp2_path is not None and os.path.isfile(tp2_path):
        with open(tp2_path, encoding="utf-8", errors="replace") as fh:
            match = _BACKUP.search(fh.read())
        backup = match["dir"].strip() if match else None
    folder_of_mod = os.path.dirname(tp2.replace("\\", "/"))
    if backup is None:
        backup = folder_of_mod + "/backup"
    # `BACKUP ~%MOD_FOLDER%/backup~`, a frequent form (review of #89)
    backup = re.sub(r"%MOD_FOLDER%", lambda _m: folder_of_mod, backup, flags=re.IGNORECASE)
    record = _in_folder(folder, f"{backup}/{number}/UNINSTALL.{number}")
    return record if record is not None and os.path.isfile(record) else None


# EET's core finds the Documents folder with a batch file (EET/lib/macros.tph,
# GET_USER_DIRECTORY, upstream since 38db44c): `for /f "tokens=3,*"` over
# `reg query ... /v Personal`, then `set DOC_DIR=` the first of the two
# variables - the third token only, so a value with a space is cut at it.
# Matched, not copied (EET is GPL-3.0): any variable letter, "tokens=3*"
# without the comma, and a `do (set ...)` are the same cut.
_EET_DOCUMENTS_CUT = re.compile(
    r'^\s*@?for\s+/f\s+"tokens=3,?\*"\s+%%(\w)\s+in\b[^\n]*/v\s+Personal\b[^\n]*\bdo\s*'
    r'(?P<open>\()?\s*set\s+"?DOC_DIR=%%\1"?\s*(?P<close>\))?\s*$', re.IGNORECASE | re.MULTILINE)
_COMMENT = re.compile(r"^\s*(?:@?rem\b|::|//)", re.IGNORECASE)


def _depth_change(line: str) -> int:
    """How many blocks a batch line opens less how many it closes: its `(`
    and `)` outside double quotes and not escaped with `^`."""
    change, quoted, escaped = 0, False, False
    for char in line:
        if escaped:
            escaped = False
        elif char == "^" and not quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted and char == "(":
            change += 1
        elif not quoted and char == ")":
            change -= 1
    return change


def _fixed_in_block(text: str, cut: re.Match) -> bool:
    """A cut that opens a block - `do (set DOC_DIR=%%a` - and sets the whole
    path within it before the block closes (`set "DOC_DIR=%%a %%b"`): the one
    way a later line fixes it (review of #100). Comments do not count. A
    block nested inside it (`if ... (` over lines, `) else (`) does not
    close it; a set inside such a block depends on its condition and does
    not count either (review of #100's merge)."""
    if not cut.group("open") or cut.group("close"):
        return False
    var = cut.group(1)
    whole = re.compile(r'^\s*set\s+"?DOC_DIR=%%' + var + r"\s+%%\w", re.IGNORECASE)
    depth = 1
    for line in text[cut.end():].splitlines():
        if not line.strip() or _COMMENT.match(line):
            continue
        if depth == 1 and whole.match(line):
            return True
        depth += _depth_change(line)
        if depth <= 0:
            return False
    return False


_SHELL_FOLDERS = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"


def _documents_value() -> str | None:
    """The Documents folder as the registry holds it, before %VARIABLES% are
    expanded - what EET's batch file reads; None off Windows or unreadable."""
    if sys.platform == "win32":
        import winreg  # noqa: PLC0415 (Windows only)
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _SHELL_FOLDERS) as key:
                value, _kind = winreg.QueryValueEx(key, "Personal")
            return str(value)
        except OSError:
            return None
    return None


def _eet_core_in(folder: str) -> bool:
    """EET's core is already in this game's WeiDU.log: past the cut."""
    for name in ("WeiDU.log", "weidu.log", "WEIDU.LOG"):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                return re.search(r"^\s*~[^~]*\beet\.tp2~\s+#\d+\s+#0\b", fh.read(),
                                 re.IGNORECASE | re.MULTILINE) is not None
    return False


def _shown(path: str) -> str:
    """`%USERPROFILE%\\x` as the player knows it, for the message only."""
    return re.sub(r"%(\w+)%", lambda m: os.environ.get(m[1], m[0]), path)


def known_issues(games: dict[str, str], mods_dir: str,
                 documents: Callable[[], str | None] | None = None) -> list[str]:
    """
    Known upstream faults this install will meet, in words; [] when none.
    Not refusals: the player decides, knowing (GUI-AUDIT M8 item 65).

    EET's core and a Documents folder whose registry value has a space
    (OneDrive's "OneDrive - Company\\Documents", "D:\\My Documents"): its
    batch file keeps the path up to the first space, and the core goes on
    with it - it creates a settings folder there and writes Baldur.lua
    (language, campaign, EET's state) into it (EET.tp2 L1091-1157, read at
    c26a11a; WeiDU's MKDIR makes the missing folders). The game finds its
    own Documents folder (engine.lua's engine_name) and never reads that
    one: the settings are lost to it, the saves are not affected (second
    review of #100). Read in the source, not run on Windows. A user name
    with a space is not this: the value is `%USERPROFILE%\\Documents`,
    expanded after the cut. Not said once EET's core is in the EET game (a
    resume past it).
    """
    issues = []
    if "EET" in games and not _eet_core_in(games["EET"]):
        value = ((documents or _documents_value)() or "").strip()
        macros = _in_folder(mods_dir, "EET/lib/macros.tph")
        if value and " " in value and macros and os.path.isfile(macros):
            with open(macros, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            cut = _EET_DOCUMENTS_CUT.search(text)
            if cut and not _fixed_in_block(text, cut):
                first = _shown(value.split(" ", 1)[0])
                wrong = first + "\\Baldur's Gate - Enhanced Edition Trilogy"
                issues.append(
                    f"EET's core will write the game's settings (Baldur.lua: language, "
                    f"campaign...) to '{wrong}' instead of your Documents folder, and the "
                    f"game will not see them - it may start in its default language and "
                    f"settings - or it may fail there. Your Documents folder is registered "
                    f"as '{value}', and EET's installer (EET/lib/macros.tph, "
                    f"GET_USER_DIRECTORY) keeps it only up to the first space. A known EET "
                    f"bug on Windows; your saves are not affected. Until EET fixes it, a "
                    f"Documents folder whose path has no space avoids it.")
    return issues


def resume_state(plan_dir: str, games: dict[str, str]) -> resume.Resume:
    """How far the planned install went in the games: each game's WeiDU.log
    against its planned log (resume.py), and whether the component it
    stopped in was left half-way."""
    state = resume.Resume()
    for log, folder in _phases(plan_dir, games):
        with open(os.path.join(plan_dir, log), encoding="utf-8", errors="replace") as fh:
            phase = resume.progress(fh.read(), _game_log(folder))
        if phase.problem is None and phase.done < phase.total:
            tp2, _language, number = phase.planned[phase.done]
            record = _left_half_way(folder, tp2, number)
            if record is not None:
                phase.problem = resume.half_way(phase.next or tp2, record)
        state.phases[log] = phase
    return state


def _write_rest(plan_dir: str, games: dict[str, str],
                state: resume.Resume) -> tuple[str, dict[str, str]]:
    """The logs of what is left, in plan_dir/resume/, and the games to run
    them on. EET: BG:EE not finished - the eet run with BG:EE's rest and the
    whole EET log (its game must have nothing yet); finished - the EET game
    alone with its rest, as a normal install."""
    rest_dir = os.path.join(plan_dir, RESUME_DIR)
    os.makedirs(rest_dir, exist_ok=True)
    for stale in (PRE_EET_LOG, EET_LOG):
        with contextlib.suppress(FileNotFoundError):
            os.remove(os.path.join(rest_dir, stale))
    pre, eet = state.phases.get(PRE_EET_LOG), state.phases.get(EET_LOG)
    if "EET" in games and "BGEE" in games and pre is not None and eet is not None:
        if pre.finished:
            write_text(os.path.join(rest_dir, EET_LOG), eet.rest())
            return rest_dir, {"EET": games["EET"]}
        # EET's game is fresh here: Resume.problem refuses it otherwise
        write_text(os.path.join(rest_dir, PRE_EET_LOG), pre.rest())
        write_text(os.path.join(rest_dir, EET_LOG), eet.rest())
        return rest_dir, games
    for log, phase in state.phases.items():
        write_text(os.path.join(rest_dir, log), phase.rest())
    return rest_dir, games


def start(plan_dir: str, games: dict[str, str], mods_dir: str, mod_installer: str,
          weidu: str, ask: Callable[[str, tuple], str | None],
          on_event: Callable[[Event], None] = lambda _event: None,
          language: str = "en_US", allow_existing: bool = False,
          resume_install: bool = False,
          expected: dict[Key, list[tuple[str, str]]] | None = None,
          by_key: dict[Key, dict[str, str]] | None = None,
          row_keys: dict[Key, list[str]] | None = None,
          raw_texts: dict[tuple[Key, str], str] | None = None, **timing) -> InstallRun:
    """
    An install ready to run, after the checks; ConfigError says what stops
    it. `resume_install`: go on where the games' WeiDU.logs say it stopped
    (resume.py) - only the rest is installed; a game whose log is not the
    plan's beginning is refused.
    """
    asked_file = os.path.join(plan_dir, ASKED_FILE)   # beside the plan, not its rest
    results_dir = plan_dir
    # EET's core asks for BG:EE's folder: known from the games as given, also
    # when a resume runs the EET game alone (review of #89)
    bgee_dir = games.get("BGEE") if "EET" in games else None
    if resume_install:
        state = resume_state(plan_dir, games)
        if state.state == "mismatch":
            raise ConfigError(f"cannot resume: {state.problem} - restore the backup to "
                              f"start again")
        if state.state == "finished":
            raise ConfigError("nothing to resume: every planned component is installed")
        if state.state == "partial":
            plan_dir, games = _write_rest(plan_dir, games, state)
            allow_existing = True
    problems = preflight(games, mods_dir, mod_installer, weidu, allow_existing)
    if problems:
        raise ConfigError("; ".join(problems))
    argv = command(plan_dir, games, mods_dir, mod_installer, weidu, language)
    logs = [os.path.join(plan_dir, name) for name in (PRE_EET_LOG, EET_LOG)]
    return InstallRun(argv, logs, cwd=mods_dir, ask=ask, on_event=on_event,
                      bgee_dir=bgee_dir, games=games, tools=(mod_installer, weidu),
                      asked_file=asked_file, phases=phases(plan_dir, games),
                      results_file=os.path.join(results_dir, RESULTS_FILE),
                      expected=expected, by_key=by_key, row_keys=row_keys,
                      parser_dir=os.path.join(os.path.dirname(asked_file), PARSER_DIR),
                      raw_texts=raw_texts,
                      **timing)
