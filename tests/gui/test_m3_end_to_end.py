"""
The M3 validation run (GUI-AUDIT, Phase 3 - Validation): the real main window
driven through phases 1-4 on a fixture EET selection, as a player drives it.

1. EET, with synthetic BG:EE and BG2:EE folders; Next saves iemod-fetch.ini.
2. Components chosen, a conflict resolved with its one-click option; Next
   saves selection.json, byte for byte what the command line writes
   (`--emit-selection`) from WeiDU.logs that install the same components
   under the same names.
3. A mod dragged to another place; Next.
4. The real download (api.download_selection, the real HttpClient) from an
   http.server on 127.0.0.1: cancelled while one mod is still arriving -
   the page says so and nothing half-installed is in the target - then
   resumed: every mod ends done with its tp2, and what was done before is not
   downloaded again. Meanwhile the event loop is never held for 100 ms.

The catalogue, the conflict check and the planner are injected, as in the
other GUI tests: the real ones fetch community data. Nothing but 127.0.0.1 is
reached; a guard makes any other connection fail the test.
"""
import faulthandler
import gc
import http.server
import json
import os
import random
import socket
import threading
import time
import zipfile

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QModelIndex, Qt, QTimer  # noqa: E402

from iemod_fetch import api  # noqa: E402
from iemod_fetch.cli import main as cli_main  # noqa: E402
from iemod_fetch.config import load_config  # noqa: E402
from iemod_fetch_gui.window import MainWindow  # noqa: E402
from test_project import bg2ee, bgee  # noqa: E402

UB = "bg1ub/setup-bg1ub.tp2"
EET = "eet/EET.tp2"
TW = "cdtweaks/setup-cdtweaks.tp2"
SCS = "stratagems/setup-stratagems.tp2"
SLOW = "cdtweaks"                       # the mod still arriving when the player cancels
MIB = 1024 * 1024
MAX_GAP_S = 0.1                         # "never blocks for more than 100 ms"


# ------------------------------------------------------------ the catalogue
def component(number, name):
    return {"number": number, "name": name, "subgroup": "", "exclusive": "",
            "groups": [], "requires": [], "forced": False}


def mod(key, path, components, category):
    return {"key": key, "name": key, "games": ["EET"], "categories": [category],
            "status": [], "advisories": [],
            "tp2s": [{"tp2": path, "origin": "krion64", "key": key,
                      "components": [component(n, name) for n, name in components]}]}


MODS = [mod("bg1ub", UB, [(0, "Restored Elfsong Tavern"), (10, "Edie the Merchant")],
            "Pre-EET"),
        mod("eet", EET, [(0, "EET core")], "Core"),
        mod("cdtweaks", TW, [(100, "Remove Helmet Animations"), (200, "Romance Tweaks")],
            "Tweaks"),
        mod("stratagems", SCS, [(1000, "Smarter mages"), (5900, "Improved Sarevok")],
            "Tactics")]


def load(game, project):
    assert game == "EET" and project["game"] == "EET"
    return json.loads(json.dumps(MODS))


def check(game, chosen, labels, project_dir):
    """api.selection_conflicts' answer: bg1ub #10 and cdtweaks #200 clash."""
    findings = []
    if (UB, 10) in chosen and (TW, 200) in chosen:
        def side(key, path, number):
            return {"mod": key, "components": [number], "whole_mod": False, "key": key,
                    "chosen": [[path, number]]}

        def deselect(oid, key, path, number):
            return {"id": oid, "action": "deselect", "mod": key, "key": key,
                    "components": [number], "whole_mod": False, "cost": 1,
                    "applicable": True, "recommended": False,
                    "description": f"deselect {key} #{number}", "chosen": [[path, number]]}
        findings.append({
            "id": "conflict-00000000000000aa", "kind": "incompatible", "severity": "error",
            "fixed_by_plan": None, "evidence": "", "workaround": "", "decision": None,
            "reason": "both patch the same dialogue", "left": side("bg1ub", UB, 10),
            "right": side("cdtweaks", TW, 200),
            "options": [deselect("option-00000000000000a1", "cdtweaks", TW, 200),
                        deselect("option-00000000000000a2", "bg1ub", UB, 10)]})
    return {"findings": findings, "stale": [], "rules_checked": 1, "planned": True,
            "problem": None}


def plan(game, chosen, labels, folder):
    """api.selection_plan's answer: BG:EE mods first, then EET - the order the
    page saved when there is one."""
    def unit(path):
        name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        return {"node": f"x|{name}|0", "name": name, "tp2": path,
                "key": name.lower().replace("setup-", ""), "part": 0, "split": False,
                "category": "", "constrained": False, "moved": False, "flagged": False,
                "components": [[p, n, ""] for p, n in chosen if p == path]}
    paths = list(dict.fromkeys(p for p, _n in chosen))
    order = os.path.join(folder, api.INSTALL_ORDER_FILE)
    custom = os.path.isfile(order)
    if custom:
        with open(order, encoding="utf-8") as fh:
            names = [line.split()[0].lower() for line in fh
                     if line.strip() and not line.startswith("//")]
        paths.sort(key=lambda p: names.index(unit(p)["key"]))
    return {"phases": [{"role": role, "title": role, "units": [unit(p) for p in group]}
                       for role, group in (
                           ("BG:EE before the conversion", [p for p in paths if p == UB]),
                           ("EET", [p for p in paths if p != UB]))],
            "cycles": [], "violations": [], "planned": True, "custom": custom}


# ------------------------------------------------------------ the server
def archive(directory, folder, tp2, size):
    """A mod's zip: its tp2 and `size` bytes that do not compress."""
    path = os.path.join(directory, f"{folder}.zip")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(tp2, "BACKUP ~x~\nAUTHOR ~m3~\n")
        zf.writestr(f"{folder}/data.bin", random.Random(folder).randbytes(size))
    with open(path, "rb") as fh:
        return fh.read()


class Mods(http.server.BaseHTTPRequestHandler):
    """Serves server.files; the first answer for server.slow trickles, as a
    slow mirror does, until the client hangs up or the test ends."""

    protocol_version = "HTTP/1.1"

    def do_GET(self):  # noqa: N802 - the stdlib's name
        name = self.path.lstrip("/")
        server = self.server
        with server.lock:
            server.hits.append(name)
            slow = name == server.slow and server.hits.count(name) == 1
        body = server.files.get(name)
        if body is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            if not slow:
                self.wfile.write(body)
                return
            half = len(body) // 2
            self.wfile.write(body[:half])
            for start in range(half, len(body), 16 * 1024):
                if server.stopping.wait(0.02):
                    break
                self.wfile.write(body[start:start + 16 * 1024])
                self.wfile.flush()
        except OSError:                     # the client hung up: it cancelled
            pass
        self.close_connection = True

    def log_message(self, *_args):
        pass


@pytest.fixture
def server(tmp_path, monkeypatch):
    for var in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy",
                "ALL_PROXY", "GITHUB_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    zips = tmp_path / "zips"
    zips.mkdir()
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Mods)
    httpd.daemon_threads = True
    httpd.hits, httpd.lock, httpd.slow = [], threading.Lock(), f"{SLOW}.zip"
    httpd.stopping = threading.Event()
    httpd.files = {
        "bg1ub.zip": archive(zips, "bg1ub", UB, 4 * MIB),
        "eet.zip": archive(zips, "eet", EET, 4 * MIB),
        "cdtweaks.zip": archive(zips, "cdtweaks", TW, 16 * MIB),
        "stratagems.zip": archive(zips, "stratagems", SCS, 4 * MIB)}
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.stopping.set()
    httpd.shutdown()
    httpd.server_close()
    thread.join(5)


@pytest.fixture
def loopback_only(monkeypatch):
    """Any connection but to 127.0.0.1 fails the test."""
    connect = socket.socket.connect

    def guarded(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        assert host in ("127.0.0.1", "::1", "localhost"), f"network access to {address}"
        return connect(sock, address)
    monkeypatch.setattr(socket.socket, "connect", guarded)


class Latency:
    """The event loop's longest wait between two 10 ms ticks.

    With IEMOD_LATENCY_TRACE set to a file, the run also writes when each gap
    ended, every garbage collection with its length, each event of the
    download stamped when its thread sent it, and when the window took each
    in - what tools/gui_latency_summary.py lines up to say what held a long
    gap (measured on the Windows runner, where one gap reached 240 ms)."""

    STALL_S = 0.04          # a traced run dumps every thread's stack past this

    def __init__(self, stacks=None):
        self.gaps, self._last = [], None
        self.ends: list[float] = []
        # faulthandler's watchdog is a C thread that needs no GIL: re-armed at
        # every tick, it fires only while the loop is held, and writes what
        # each thread was running at that moment
        self.stacks = stacks
        self.timer = QTimer()
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self._tick)

    def _tick(self):
        now = time.perf_counter()
        if self._last is not None:
            self.gaps.append(now - self._last)
            self.ends.append(now)
        self._last = now
        if self.stacks is not None:
            faulthandler.dump_traceback_later(self.STALL_S, file=self.stacks)

    def start(self):
        self._last = None
        self.timer.start()

    def stop(self):
        self.timer.stop()
        if self.stacks is not None:
            faulthandler.cancel_dump_traceback_later()


# ------------------------------------------------------------ the run
def states(page):
    return {folder: item.text(1) for folder, item in page.rows.items()}


def test_the_wizard_goes_from_the_game_folders_to_every_mod_downloaded(
        qtbot, tmp_path, monkeypatch, server, loopback_only, request):
    data = tmp_path / "data"                 # krion64 files bg1ub before the conversion
    (data / "krion64" / "data" / "mods").mkdir(parents=True)
    (data / "krion64" / "data" / "categories.json").write_text(json.dumps(
        {"categories": {"PRE EET BGEE MODS": {}, "TWEAKS": {}}}))
    (data / "krion64" / "data" / "mods" / "bg1ub.json").write_text(json.dumps(
        {"t": "setup-bg1ub", "c": "PRE EET BGEE MODS", "ord": 1,
         "co": [{"wf": "bg1ub", "wp": "bg1ub\\setup-bg1ub.tp2"}]}))
    monkeypatch.setenv("IEMOD_DATA_DIR", str(data))
    project = tmp_path / "project"
    project.mkdir()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    (project / "mods.json").write_text(json.dumps({"mods": [
        {"name": name, "tp2": name, "url": f"{base}/{name}.zip"}
        for name in ("bg1ub", "eet", "cdtweaks", "stratagems")]}))
    # A project set up to fetch from that mirror only: one mod at a time, so
    # which are done when the player cancels is known.
    (project / api.PROJECT_FILE).write_text(
        "[iemod-fetch]\nmanifest = mods.json\nallow_http = true\nworkers = 1\n"
        "retries = 1\nno_update_data = true\nno_default_data = true\n"
        "no_discovery = true\nno_gh_cli = true\nno_git_credential = true\n")

    main = MainWindow(str(project), load=load, check=check, plan=plan)
    qtbot.addWidget(main)
    main.show()

    # 1. Game and folders --------------------------------------------------
    assert main.game.game() == "EET"
    first, second = bgee(tmp_path), bg2ee(tmp_path)
    main.game.bgee.edit.setText(first)
    main.game.bg2ee.edit.setText(second)
    main.game.check()
    assert main.next.isEnabled()
    with qtbot.waitSignal(main.mods.checked, timeout=5000):
        qtbot.mouseClick(main.next, Qt.MouseButton.LeftButton)
    assert main.current == 1
    values = load_config(explicit=str(project / api.PROJECT_FILE)).values
    assert values["bgee_dir"] == first and values["bg2ee_dir"] == second
    assert values["manifest"] == "mods.json" and values["allow_http"] is True

    # 2. Mod selection, and a conflict resolved ----------------------------
    with qtbot.waitSignal(main.mods.checked, timeout=5000):
        for key in [(UB, 0), (UB, 10), (EET, 0), (TW, 100), (TW, 200), (SCS, 1000)]:
            main.mods.items[key].setCheckState(0, Qt.CheckState.Checked)
    assert [f["id"] for f in main.mods.conflicts["findings"]] == ["conflict-00000000000000aa"]
    with qtbot.waitSignal(main.mods.checked, timeout=5000):
        main.mods.panel.buttons["option-00000000000000a1"].click()   # drop cdtweaks #200
    assert main.mods.conflicts["findings"] == []
    chosen = [(UB, 0), (UB, 10), (EET, 0), (TW, 100), (SCS, 1000)]
    assert main.mods.chosen() == chosen
    with qtbot.waitSignal(main.order.planned, timeout=5000):
        qtbot.mouseClick(main.next, Qt.MouseButton.LeftButton)
    assert main.current == 2
    saved = (project / api.SELECTION_FILE).read_bytes()
    labels = {(UB, 0): "Restored Elfsong Tavern", (UB, 10): "Edie the Merchant",
              (EET, 0): "EET core", (TW, 100): "Remove Helmet Animations",
              (SCS, 1000): "Smarter mages"}
    # The command line's own writer: --emit-selection from the WeiDU.logs that
    # install the same components, under the same names (review of #43: a
    # second api.save_selection compared the wizard's writer with itself).
    cli = tmp_path / "cli"
    cli.mkdir()
    for name, rows in (("WeiDU-BGEE.log", chosen[:2]), ("WeiDU.log", chosen[2:])):
        (cli / name).write_text(
            "// Log of Currently Installed WeiDU Mods\n"
            + "".join(f"~{tp2}~ #0 #{number} // {labels[(tp2, number)]}\n"
                      for tp2, number in rows), encoding="utf-8")
    monkeypatch.chdir(cli)                  # no project ini of the wizard's here
    assert cli_main(["-w", f"{cli / 'WeiDU-BGEE.log'}:BGEE", "-w", f"{cli / 'WeiDU.log'}:EET",
                     "-m", str(project / "mods.json"), "--emit-selection", str(cli / "cli.json"), "--check-only",
                     "--no-update-data", "--no-discovery", "--no-gh-cli",
                     "--no-git-credential", "-q"]) == 0
    assert saved == (cli / "cli.json").read_bytes()
    assert [i["game"] for i in json.loads(saved)["installs"]] == ["BGEE", "EET"]

    # 3. Install order ------------------------------------------------------
    eet = main.order.tabs.widget(1)
    assert [eet.item(r).text() for r in range(eet.count())] == [
        "EET", "setup-cdtweaks", "setup-stratagems"]
    with qtbot.waitSignal(main.order.planned, timeout=5000):
        eet.model().moveRow(QModelIndex(), 2, QModelIndex(), 1)     # SCS before tweaks
    eet = main.order.tabs.widget(1)
    assert [eet.item(r).text() for r in range(eet.count())] == [
        "EET", "setup-stratagems", "setup-cdtweaks"]
    assert (project / api.INSTALL_ORDER_FILE).is_file()
    assert main.next.isEnabled()
    qtbot.mouseClick(main.next, Qt.MouseButton.LeftButton)
    assert main.current == 3 and not main.next.isEnabled()

    # 4. Download: cancelled while cdtweaks arrives -------------------------
    page, mods_dir = main.download, project / "Mods"
    trace = os.environ.get("IEMOD_LATENCY_TRACE")
    if trace:       # the test has changed directory by now: relative to where pytest ran
        trace = os.path.join(str(request.config.invocation_params.dir), trace)
    collections: list[tuple[float, float, int]] = []
    sent: list[tuple[float, str, str]] = []         # when the download sent it
    handled: list[float] = []                       # when the window took it in
    if trace:
        started = {}

        def collected(phase, info):
            if phase == "start":
                started["t"] = time.perf_counter()
            elif "t" in started:
                collections.append((started.pop("t"), time.perf_counter(), info["generation"]))
        gc.callbacks.append(collected)
        request.addfinalizer(lambda: gc.callbacks.remove(collected))
        forward = page._forward             # start() takes it from the page

        def stamped(event):
            sent.append((time.perf_counter(), str(event.get("event")),
                         str(event.get("folder", ""))))
            forward(event)
        page._forward = stamped
        page._bridge.event.connect(lambda _event: handled.append(time.perf_counter()))
        stacks = open(trace + ".stacks.txt", "w", encoding="utf-8")  # noqa: SIM115
        request.addfinalizer(stacks.close)
        request.addfinalizer(faulthandler.cancel_dump_traceback_later)
    latency = Latency(stacks if trace else None)
    latency.start()
    with qtbot.waitSignal(page.finished, timeout=30000):
        qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: SLOW in page.rows and page.rows[SLOW].text(2) != "",
                        timeout=15000)
        assert not main.back.isEnabled() and page.cancel_button.isEnabled()
        qtbot.mouseClick(page.cancel_button, Qt.MouseButton.LeftButton)
    latency.stop()
    first_run = list(latency.gaps)
    assert page.summary.text().startswith("Cancelled")
    shown = states(page)
    assert shown[SLOW] == "Cancelled"
    done = {folder for folder, state in shown.items() if state == "Done"}
    assert done and SLOW not in done
    assert set(shown.values()) <= {"Done", "Cancelled"}
    # nothing half-installed: the finished mods only, and no leftover download
    on_disk = {p.name for p in mods_dir.iterdir() if not p.name.startswith(".")}
    assert on_disk == done
    staging = mods_dir / ".staging"
    assert not staging.exists() or not any(staging.iterdir())
    assert not main.next.isEnabled() and main.back.isEnabled()

    # ... and resumed: Download again --------------------------------------
    hits = list(server.hits)
    latency.start()
    with qtbot.waitSignal(page.finished, timeout=30000):
        qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    latency.stop()
    assert set(states(page)) == {"bg1ub", "eet", "cdtweaks", "stratagems"}
    assert set(states(page).values()) <= {"Done", "Already there"}
    assert {f for f, s in states(page).items() if s == "Already there"} == done
    again = server.hits[len(hits):]
    assert sorted(again) == sorted(f"{name}.zip" for name in shown if name not in done)
    for path in (UB, EET, TW, SCS):
        assert (mods_dir / path).is_file(), path
    assert main.next.isEnabled() and page.is_complete()

    gaps = latency.gaps                      # both runs: start() does not clear it
    second_run = gaps[len(first_run):]
    assert first_run and second_run          # the loop was measured in both runs
    worst = max(gaps)
    if trace:
        with open(trace, "w", encoding="utf-8") as fh:
            json.dump({"gaps": [[end, gap] for end, gap in zip(latency.ends, gaps,
                                                               strict=True)],
                       "collections": collections, "events": sent, "handled": handled}, fh)
    print(f"\nM3: {len(first_run)} + {len(second_run)} event-loop ticks during the "
          f"downloads, the longest gap {worst * 1000:.1f} ms; done before the cancel: "
          f"{sorted(done)}; requests: {server.hits}")
    assert worst < MAX_GAP_S, f"the window was blocked for {worst * 1000:.0f} ms"
