"""
WeiDU's prompts in an install mod_installer runs (GUI-AUDIT M4 item 22,
ADR-0045): what it asks, and the answers recorded for it.

mod_installer (dark0dave, GPL-3.0, read at 16.0.0 and 12.1.1) installs a
WeiDU.log in batches of consecutive components of one mod (12.1.1: one
component at a time), logging each before it starts:

    [2026-10-24T00:00:00Z INFO  mod_installer::installers] Installing mod
    WeiduBatchedComponents([WeiduComponent { tp_file: "EET.TP2", name: "EET",
    lang: "0", component: "0", ... }])

When WeiDU waits for an answer it logs `User Input required`, `Question is`
and the question, then reads one line from its own standard input and gives
it to WeiDU. Only EET's question for the BG:EE folder is answered by
mod_installer itself, and only 16.0.0 on Linux.

The answers a player recorded ride on the component's line of the WeiDU.log,
as Born2BSalty's Infinity Orchestrator writes them (GPL-3.0; the format read
at 33800cc, no code copied):

    ~SOMEMOD\\SETUP-SOMEMOD.TP2~ #0 #10 // Confirm install: v1.0 // @wlb-inputs: y,,c

left to right, `,,` an empty answer (Enter). An answer cannot hold a comma.

This module only reads: the log's answers, and mod_installer's output, line
by line, into events. Running mod_installer is install_run.py's.
"""
import re
from collections import deque
from dataclasses import dataclass, field

TAG = "// @wlb-inputs:"
# What EET asks for the BG:EE folder (mod_installer's own `eet_auto_fill`).
EET_FOLDER_QUESTION = "enter the full path to your bg:ee+sod installation"

_LOG_LINE = re.compile(r"^\s*~(?P<path>[^~]+)~\s+#(?P<lang>\d+)\s+#(?P<number>\d+)")
_RECORD = re.compile(r"^\[\S+\s+(?P<level>[A-Z]+)\s+(?P<target>[\w:]+)\]\s?(?P<text>.*)$")
# 16.0.0: `WeiduBatchedComponents([WeiduComponent { ... }, ...])`, a batch;
# 12.1.1: `Component { ... }`, one component at a time
_COMPONENT = re.compile(r'(?:Weidu)?Component \{ tp_file: "(?P<tp2>[^"]*)", name: "[^"]*", '
                        r'lang: "[^"]*", component: "(?P<number>\d+)"')
# 12.1.1 logs a growing row of dots while WeiDU works, one record a tick
_TICK = re.compile(r"\.*")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

Key = tuple[str, int]          # (tp2 file name, lower-cased; component number)


def tp2_name(path: str) -> str:
    """`EET\\EET.TP2`, `eet/eet.tp2` -> `eet.tp2`: how both sides name a tp2."""
    return path.replace("\\", "/").rsplit("/", 1)[-1].lower()


def wlb_inputs(line: str) -> list[str] | None:
    """The answers a WeiDU.log component line records, None if it has none."""
    at = line.find(TAG)
    if at < 0:
        return None
    return [answer.strip() for answer in line[at + len(TAG):].strip().split(",")]


def recorded_answers(log_text: str) -> dict[Key, list[str]]:
    """Every component line's recorded answers in a WeiDU.log, by component."""
    out: dict[Key, list[str]] = {}
    for line in log_text.splitlines():
        match = _LOG_LINE.match(line)
        answers = wlb_inputs(line) if match else None
        if match and answers is not None:
            out[(tp2_name(match["path"]), int(match["number"]))] = answers
    return out


@dataclass
class Event:
    kind: str                  # "line" | "batch" | "question" | "answer" | "watchdog"
    text: str = ""
    batch: tuple[Key, ...] = ()


@dataclass
class OutputReader:
    """
    mod_installer's output, one line at a time, as events. A question has
    no end of its own - mod_installer logs it and waits - so it is collected
    until `question()` is called, when the output has gone quiet.
    """
    _asking: list[str] | None = None        # a question's lines, once announced
    _announced: bool = False                # "User Input required" seen
    batch: tuple[Key, ...] = ()

    def feed(self, raw: str) -> list[Event]:
        line = _ANSI.sub("", raw).rstrip("\r\n")
        events = [Event("line", line)]
        record = _RECORD.match(line)
        if record is None:
            if self._asking is not None:
                self._asking.append(line)          # the question goes on
            return events
        if self._asking is not None and self._asking:
            # a new record after a question: WeiDU answered it itself
            self._asking = None
        text = record["text"]
        if _TICK.fullmatch(text):
            return []                              # waiting, nothing said
        if text.startswith("Installing mod "):
            self.batch = tuple((tp2_name(m["tp2"]), int(m["number"]))
                               for m in _COMPONENT.finditer(text))
            events.append(Event("batch", text, self.batch))
        elif text == "User Input required":
            self._announced = True
        elif text == "Question is" and self._announced:
            self._announced = False
            self._asking = []
        elif self._asking is not None:
            self._asking.append(text)
        return events

    @property
    def asking(self) -> bool:
        """A question is being collected."""
        return self._asking is not None

    def question(self) -> Event | None:
        """The question collected so far, once the output went quiet."""
        if self._asking is None:
            return None
        text = "\n".join(self._asking).strip("\n")
        self._asking = None
        return Event("question", text, self.batch)


@dataclass
class Answers:
    """
    The recorded answers of a log, handed out batch by batch, in order. With
    `keys` ({component: its questions' keys, in the order its files ask
    them}), each recorded answer also knows the question it was given for,
    so an answer given by question (take) leaves the others in step.
    """
    recorded: dict[Key, list[str]]
    keys: dict[Key, list[str]] = field(default_factory=dict)
    _queue: deque = field(default_factory=deque)
    _batch: tuple[Key, ...] = ()

    def start(self, batch: tuple[Key, ...]) -> None:
        """A batch starts: its components' answers, in the batch's order."""
        self._batch = batch
        self._queue = deque()
        for key in batch:
            names = self.keys.get(key, [])
            for i, answer in enumerate(self.recorded.get(key, ())):
                self._queue.append((key, names[i] if i < len(names) else None, answer))

    def next(self) -> str | None:
        """The next recorded answer of the batch, None when there is none."""
        return str(self._queue.popleft()[2]) if self._queue else None

    def keyed(self, component: Key) -> bool:
        """This component's recorded answers know their questions."""
        return bool(self.keys.get(component))

    def take(self, component: Key, question: str) -> str | None:
        """The recorded answer for this component's question, taken out of
        the queue wherever it is; None when none is recorded for it."""
        for entry in self._queue:
            if entry[0] == component and entry[1] == question:
                self._queue.remove(entry)
                return str(entry[2])
        return None


# A question is recognised by its text only when that text says enough:
# "y/n?" alone would match the end of too many questions (ADR-0049).
MIN_TEXT = 12
_VARIABLE = re.compile(r"%[^%\s]+%")


def _expected_pattern(text: str) -> re.Pattern | None:
    """The question's text as it ends WeiDU's output: any run of white space
    for white space, a %variable% as anything on its line (WeiDU fills it in),
    starting a word. None when the text says too little to be told apart:
    fewer than MIN_TEXT characters besides its variables, or ending in a
    variable (anything after its last words would match; review of #111)."""
    words = text.split()
    literal = _VARIABLE.sub("", " ".join(words))
    if len(literal.replace(" ", "")) < MIN_TEXT or not words:
        return None
    if not _VARIABLE.sub("", words[-1]).strip(".,:;!?()[]\"'"):
        return None
    parts = [_VARIABLE.sub(lambda _m: "\x00", word) for word in words]
    # white space between words as any white space (mod_installer's window
    # puts its own indented blank lines between WeiDU's lines); the text
    # starts the window or a word
    body = r"\s+".join(re.escape(part).replace("\x00", r"[^\n]*?") for part in parts)
    return re.compile(r"(?<!\w)" + body + r"\s*\Z")


def recognisable(text: str) -> bool:
    """match_question can tell this question apart by its text at all."""
    return bool(text) and _expected_pattern(text) is not None


# What mod_installer 16.0.0 takes for a question (src/config/parser_config.rs,
# string_looks_like_question): it puts nothing else to anyone - WeiDU waits
# until its timeout (ADR-0049, measured).
_CHOICE_WORDS = frozenset({"choice", "choose", "select", "enter"})
_CHOICE_PHRASES = ("do you want", "would you like", "answer [y]es or [n]o.", "is this correct?",
                   "[y]es or [n]o", "please select", "please enter", "enter a new",
                   "leave blank", "[a]ccept, [r]etry, [c]ancel", "[y]es, [n]o, [c]ancel")


def mod_installer_asks(text: str) -> bool:
    """mod_installer would put this text to the player as a question: a
    choice phrase or word, or a bell, and not a progress word."""
    line = text.strip().lower()
    if "\x07" in line:
        return True
    if "installing" in line or "creating" in line:
        return False
    if any(phrase in line for phrase in _CHOICE_PHRASES):
        return True
    return any("".join(c for c in word if c.isalpha()) in _CHOICE_WORDS
               for word in line.split())


def match_question(window: str, expected: list[tuple[Key, str, str]]) -> tuple[Key, str] | None:
    """
    Which expected question mod_installer's window ends with (item 48,
    ADR-0049): `expected` is (component, question key, question text) for
    the batch's components, the texts read from their files in the language
    the log installs them in. The longest text that ends the window wins (a
    shorter one may be its tail); None when none does, or when two different
    questions are as likely - never a guess.
    """
    best: list[tuple[int, Key, str]] = []
    for component, key, text in expected:
        pattern = _expected_pattern(text) if text else None
        if pattern is None or not pattern.search(window):
            continue
        best.append((len(_VARIABLE.sub("", " ".join(text.split()))), component, key))
    if not best:
        return None
    top = max(length for length, _c, _k in best)
    winners = {(c, k) for length, c, k in best if length == top}
    if len({k for _c, k in winners}) != 1 or len(winners) != 1:
        return None
    return next(iter(winners))


def question_line(text: str) -> str:
    """The last line of what mod_installer sends, kept as what was asked
    (GUI-AUDIT M8 item 63). It sends WeiDU's last `lookback` lines before
    the question too, 10 by default (src/parser.rs; measured with the real
    16.0.0): WeiDU's version, "Installing [Mod] [v30]", copy lines, an
    earlier question, and the lines printed after it. Which of them is the
    question, and which component asked it, is not known from that text:
    item 48's expected texts will say."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def writable(answer: str) -> bool:
    """An answer a log line can carry: no comma (the format's separator), and
    nothing str.splitlines() breaks a line at - not only \\r and \\n but \\x0b,
    \\x0c, \\x1c-\\x1e, \\x85, U+2028/2029 - or the line would be cut where the
    log is read back (review of #107)."""
    return "," not in answer and len(f"x{answer}x".splitlines()) == 1


def set_inputs(log_text: str, inputs: dict[Key, list[str]]) -> str:
    """
    `log_text` with each listed component's recorded answers set to `inputs`
    (phase-5 questionnaire, ADR-0049): the `// @wlb-inputs:` tag of its line
    replaced, or added at its end; an empty list removes it. Lines of other
    components, and every other line, are kept as they are. An answer
    cannot hold a comma (the format's separator): ValueError.
    """
    out = []
    for line in log_text.splitlines(keepends=True):
        match = _LOG_LINE.match(line)
        key = (tp2_name(match["path"]), int(match["number"])) if match else None
        if key is None or key not in inputs:
            out.append(line)
            continue
        answers = inputs[key]
        if not all(writable(answer) for answer in answers):
            raise ValueError(f"{key[0]} #{key[1]}: an answer cannot hold a comma or a line break")
        body = line.rstrip("\r\n")
        end = line[len(body):]
        at = body.find(TAG)
        if at >= 0:
            body = body[:at].rstrip()
        if answers:
            body += f" {TAG} " + ",".join(answers)
        out.append(body + end)
    return "".join(out)
