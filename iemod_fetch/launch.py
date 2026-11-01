"""
How to start the game once the plan is installed (GUI-AUDIT M8 item 71,
ADR-0054): a mod that replaces how the game starts is told to the player,
with the program to start and why.

Today one does: EEex. Its main component (`EEex.tp2` #1, LABEL
`B3-EEex-Main`) copies its loader into the game folder (`COPY ~EEex/loader~
~.~`), and its README says the game must then be started with
InfinityLoader.exe (EEex.exe before v0.9) - "any attempt to start the game
using the vanilla executable will result in a crash". It runs natively on
Windows, through Proton or Wine on Linux and through CrossOver on macOS
(its README's support table). Read at Bubb13/EEex a6d21ab, v1.3.1
(MIT); Chriz Easy BG's `docs/curation/components/EEEX.md` L28-29 says the
same. Its quick-menu core, #0, installs no loader and asks for nothing.

Pure: it reads planned logs' texts.
"""
import re

_LINE = re.compile(r"^\s*~(?P<path>[^~]+)~\s+#\d+\s+#(?P<number>\d+)")

# tp2 file name (lower case) -> (the components that change how the game
# starts, what to start, why)
LOADERS = {
    "eeex.tp2": (frozenset({1}), "InfinityLoader.exe",
                 ("EEex is installed: start the game with InfinityLoader.exe in the game "
                  "folder (EEex.exe for EEex before v0.9), never with the game's own "
                  "program, which crashes once EEex is in.")),
}
# What EEex says of systems other than Windows
ELSEWHERE = {
    "linux": "On Linux EEex runs only with the Windows game, through Proton or Wine: "
             "the native Linux game cannot start it.",
    "darwin": "On macOS EEex runs only with the Windows game, through CrossOver: the "
              "native macOS game cannot start it.",
}


def _tp2(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1].lower()


def launch_advice(logs: dict[str, str], platform: str) -> list[dict]:
    """
    For each planned log ({label: text}) that installs a component which
    changes how the game starts: {"log", "tp2", "component", "program",
    "why", "platform_note"}. `platform` is sys.platform's value; a note is
    added off Windows.
    """
    out = []
    for label, text in logs.items():
        seen = set()
        for line in text.splitlines():
            match = _LINE.match(line)
            if not match:
                continue
            tp2, number = _tp2(match["path"]), int(match["number"])
            loader = LOADERS.get(tp2)
            if loader is None or number not in loader[0] or tp2 in seen:
                continue
            seen.add(tp2)
            note = next((text for prefix, text in ELSEWHERE.items()
                         if platform.startswith(prefix)), "")
            out.append({"log": label, "tp2": tp2, "component": number,
                        "program": loader[1], "why": loader[2], "platform_note": note})
    return out
