"""
A stand-in for mod_installer 16.0.0, for tests/test_install_run.py: it reads
the same arguments, prints what the real one logs (env_logger's format, read
from its source) and asks WeiDU's questions the way it does - `User Input
required`, `Question is`, the question, then one line read from its standard
input. No WeiDU runs: each component is "installed" by a line appended to the
game's WeiDU.log.

FAKE_QUESTIONS: JSON {"tp2.tp2#n": ["question", ...]} asked for a component.
FAKE_TRANSCRIPT: a file every answer is appended to, one per line.
FAKE_FAIL: "tp2.tp2#n" - that component fails, exit status 1.
FAKE_SLOW: seconds slept after each batch starts (to cancel meanwhile).
FAKE_GRANDCHILD: a file the pid of a sleeping child is written to - WeiDU's
  place - started with the first batch, never waited for.
FAKE_EXIT_EARLY: with FAKE_GRANDCHILD, exit 0 right after starting it,
  leaving it to hold the output.
FAKE_ECHO_ENV: the name of a variable whose value is logged at the start.
FAKE_VERSION: the mods' version WeiDU prints ("Installing [x] [v30]").

A question is sent as the real one sends it (src/parser.rs; review of #98):
the last LOOKBACK lines of WeiDU's output before it - its version, the
"Installing" line, earlier questions of the batch - then the question.
"""
import json
import os
import subprocess
import sys
import time

LOOKBACK = 10                     # mod_installer's default --lookback

IGNORING = """
import signal, time
for name in ("SIGTERM", "SIGBREAK", "SIGINT"):
    if hasattr(signal, name):
        signal.signal(getattr(signal, name), signal.SIG_IGN)
time.sleep(120)
"""


def log(level, target, text):
    print(f"[2026-10-24T00:00:00Z {level:<5} mod_installer::{target}] {text}", flush=True)


def components(path):
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.startswith("~"):
                continue
            tp2_path = line.split("~")[1]
            tp2 = tp2_path.replace("\\", "/").split("/")[-1]
            folder = tp2_path.replace("\\", "/").split("/")[0]
            lang, number = line.split("~")[2].split("//")[0].split()
            out.append((tp2, folder, lang.strip("#"), number.strip("#"), line.rstrip("\n")))
    return out


def install(game, log_file, questions, transcript, fail, slow):
    batches = []
    for item in components(log_file):
        if batches and batches[-1][0][0] == item[0]:
            batches[-1].append(item)
        else:
            batches.append([item])
    for batch in batches:
        listed = ", ".join(
            f'WeiduComponent {{ tp_file: "{tp2}", name: "{folder}", lang: "{lang}", '
            f'component: "{number}", component_name: "", sub_component: "", version: "" }}'
            for tp2, folder, lang, number, _line in batch)
        log("INFO", "installers", f"Installing mod WeiduBatchedComponents([{listed}])")
        pidfile = os.environ.get("FAKE_GRANDCHILD")
        if pidfile and not os.path.exists(pidfile):
            # it shrugs off a polite stop, the way a busy WeiDU may: only a
            # real kill of the whole tree ends it
            child = subprocess.Popen([sys.executable, "-c", IGNORING])
            with open(pidfile, "w", encoding="utf-8") as fh:
                fh.write(str(child.pid))
            if os.environ.get("FAKE_EXIT_EARLY"):
                return 0
        time.sleep(slow)
        version = os.environ.get("FAKE_VERSION", "v1")
        weidu = ["[weidu] WeiDU version 25100", "    "]        # one WeiDU per batch
        for tp2, _folder, _lang, number, line in batch:
            key = f"{tp2.lower()}#{number}"
            weidu += [f"    Installing [{tp2} component {number}] [{version}]",
                      "    Copying 1 file ...", "    "]
            for question in questions.get(key, []):
                log("INFO", "runner", "User Input required")
                log("INFO", "runner", "Question is")
                window = weidu[-LOOKBACK:] + [f"    {question}"]
                log("INFO", "runner", "\n".join(window))
                weidu += [f"    {question}", "    "]
                answer = sys.stdin.readline()
                if not answer:
                    log("ERROR", "main", "standard input closed")
                    return 1
                with open(transcript, "a", encoding="utf-8") as fh:
                    fh.write(answer)
            if key == fail:
                log("ERROR", "installers", f"{tp2} #{number} not installed due to errors")
                return 1
            with open(os.path.join(game, "WeiDU.log"), "a", encoding="utf-8") as fh:
                fh.write(line.split(" // @wlb-inputs:")[0] + "\n")
        log("INFO", "installers", f"Installed mod WeiduBatchedComponents([{listed}])")
    return 0


def main(argv):
    # mod_installer (Rust) reads its standard input as UTF-8 on every system
    sys.stdin.reconfigure(encoding="utf-8")
    pairs = [arg for arg in argv[1:] if "=" not in arg]      # --download=false stands alone
    args = dict(zip(pairs[::2], pairs[1::2], strict=False))
    questions = json.loads(os.environ.get("FAKE_QUESTIONS", "{}"))
    transcript = os.environ.get("FAKE_TRANSCRIPT", os.devnull)
    fail, slow = os.environ.get("FAKE_FAIL", ""), float(os.environ.get("FAKE_SLOW", "0"))
    echo = os.environ.get("FAKE_ECHO_ENV")
    if echo:
        log("INFO", "main", f"{echo}={os.environ.get(echo, '')}")
    if argv[0] == "eet":
        log("INFO", "installers", "Beginning pre eet install process")
        status = install(args["--bg1-game-directory"], args["--bg1-log-file"], questions,
                         transcript, fail, slow)
        if status:
            return status
        log("INFO", "installers", "Beginning eet install process")
        return install(args["--bg2-game-directory"], args["--bg2-log-file"], questions,
                       transcript, fail, slow)
    log("INFO", "installers", "Beginning normal install process")
    return install(args["--game-directory"], args["--log-file"], questions, transcript,
                   fail, slow)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
