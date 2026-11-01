"""
Phase 4, download and extraction, driven like a player drives it (M3,
GUI-AUDIT item 18, ADR-0039). The downloader is injected: it answers the way
api.download_selection answers, sending its events from other threads as the
run's worker pool does (test_download_selection.py checks the real one).
"""
import threading

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402

from iemod_fetch_gui.pages.download import DownloadPage  # noqa: E402
from iemod_fetch_gui.window import PHASES, MainWindow  # noqa: E402


def event(kind, **fields):
    return {"schema_version": 1, "event": kind, **fields}


def record(folder, status, detail="", size=0):
    return {"folder": folder, "status": status, "detail": detail, "url": None,
            "version": None, "bytes": size, "error_code": None}


class Fake:
    """Downloads `mods`; those in `failing` fail until `failing` is emptied."""

    def __init__(self, mods=("ub", "tweaks"), failing=(), progress=3, hold=False):
        self.mods, self.failing, self.progress = list(mods), set(failing), progress
        self.hold = hold                    # wait for cancel before finishing
        self.calls = []
        self.started = threading.Event()

    def __call__(self, folder, on_event, cancel, only):
        self.calls.append(list(only))
        mods = [m for m in self.mods if not only or m in only]
        records = []

        def pool():                         # the run's worker threads
            on_event(event("run_started", mods=len(mods)))
            for mod in mods:
                on_event(event("mod_started", folder=mod))
                self.started.set()
                if self.hold:
                    cancel.wait(5)
                if cancel.is_set():
                    records.append(record(mod, "cancelled", "stopped during the download"))
                    on_event(event("mod_finished", folder=mod, status="cancelled",
                                   detail="stopped during the download"))
                    continue
                for n in range(1, self.progress + 1):
                    on_event(event("download_progress", folder=mod, bytes=n * 1000,
                                   total=self.progress * 1000))
                if mod in self.failing:
                    records.append(record(mod, "failed", "HTTP 404"))
                    on_event(event("mod_finished", folder=mod, status="failed",
                                   detail="HTTP 404"))
                    continue
                on_event(event("mod_extracting", folder=mod))
                records.append(record(mod, "ok", f"installed {mod}.tp2", 3000))
                on_event(event("mod_finished", folder=mod, status="ok",
                               detail=f"installed {mod}.tp2"))
            on_event(event("run_finished", cancelled=cancel.is_set(), counts={}))
        thread = threading.Thread(target=pool)
        thread.start()
        thread.join()
        counts = {}
        for r in records:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        return {"records": records, "cancelled": cancel.is_set(), "counts": counts,
                "exit_code": 0 if all(r["status"] == "ok" for r in records) else 1}


def page(qtbot, tmp_path, fake):
    widget = DownloadPage(str(tmp_path), fake)
    qtbot.addWidget(widget)
    return widget


def run(qtbot, widget, only=None):
    with qtbot.waitSignal(widget.finished, timeout=5000):
        if only is None:
            widget.start_button.click()
        else:
            widget.retry_button.click()


def states(widget):
    return {folder: item.text(1) for folder, item in widget.rows.items()}


def test_nothing_is_downloaded_until_the_player_asks(qtbot, tmp_path):
    fake = Fake()
    widget = page(qtbot, tmp_path, fake)
    assert fake.calls == [] and not widget.is_complete()
    run(qtbot, widget)
    assert fake.calls == [[]]
    assert states(widget) == {"ub": "Done", "tweaks": "Done"}
    assert widget.is_complete() and not widget.retry_button.isEnabled()
    assert "2 done" in widget.summary.text()
    assert widget.rows["ub"].text(2) == "2.9 KiB"


def test_progress_reaches_the_window_at_most_ten_times_a_second(qtbot, tmp_path):
    fake = Fake(mods=["ub"], progress=2000)
    widget = page(qtbot, tmp_path, fake)
    shown = []
    widget._bridge.event.connect(lambda e: shown.append(e["event"]))
    run(qtbot, widget)
    # 2,000 chunks in well under a second: the first and the last one pass
    assert 2 <= shown.count("download_progress") < 50
    assert widget.rows["ub"].text(1) == "Done"


def test_a_failed_mod_can_be_retried_alone(qtbot, tmp_path):
    fake = Fake(failing=["tweaks"])
    widget = page(qtbot, tmp_path, fake)
    run(qtbot, widget)
    assert states(widget) == {"ub": "Done", "tweaks": "Failed"}
    assert widget.rows["tweaks"].text(3) == "HTTP 404"
    assert not widget.is_complete() and widget.retry_button.isEnabled()
    fake.failing.clear()
    with qtbot.waitSignal(widget.completeChanged, timeout=5000,
                          check_params_cb=lambda complete: complete):
        widget.retry_button.click()
    assert fake.calls[-1] == ["tweaks"]
    assert states(widget) == {"ub": "Done", "tweaks": "Done"}       # ub kept, not redone


def test_cancel_stops_the_run_and_says_so(qtbot, tmp_path):
    fake = Fake(hold=True)
    widget = page(qtbot, tmp_path, fake)
    with qtbot.waitSignal(widget.finished, timeout=5000):
        widget.start_button.click()
        assert fake.started.wait(5)
        assert widget.cancel_button.isEnabled() and not widget.start_button.isEnabled()
        widget.cancel_button.click()
    assert set(states(widget).values()) == {"Cancelled"}
    assert widget.summary.text().startswith("Cancelled")
    assert not widget.is_complete() and widget.start_button.isEnabled()


def test_a_download_that_cannot_start_is_shown_not_a_crash(qtbot, tmp_path):
    def broken(*_args):
        raise RuntimeError("no download source: no manifest")
    widget = page(qtbot, tmp_path, broken)
    run(qtbot, widget)
    assert "no download source" in widget.summary.text()
    assert not widget.is_complete() and widget.start_button.isEnabled()


def test_the_wizard_goes_on_once_every_mod_is_there(qtbot, tmp_path):
    assert PHASES[3:] == ["Download and extraction", "Installation"]
    fake = Fake()
    main = MainWindow(str(tmp_path), load=lambda game, project: [],
                      check=lambda *a: {"findings": [], "stale": [], "rules_checked": 0,
                                        "planned": False, "problem": None},
                      plan=lambda *a: {}, download=fake)
    qtbot.addWidget(main)
    main.stack.setCurrentIndex(3)
    main._refresh()
    assert main.pages[3] is main.download and not main.next.isEnabled()
    run(qtbot, main.download)
    assert main.next.isEnabled()


def test_a_new_selection_starts_the_phase_again(qtbot, tmp_path):
    # Review of #39: a complete download of the old selection let Next through
    # with a mod added since and never downloaded.
    widget = page(qtbot, tmp_path, Fake())
    widget.prepare(("EET", ("ub",)))
    run(qtbot, widget)
    assert widget.is_complete()
    widget.prepare(("EET", ("ub",)))                    # same selection: kept
    assert widget.is_complete()
    widget.prepare(("EET", ("ub", "tweaks")))            # another: start again
    assert not widget.is_complete() and widget.rows == {}
    assert widget.summary.text() == "Nothing downloaded yet."


def test_a_retried_mod_the_selection_no_longer_has_leaves_the_list(qtbot, tmp_path):
    fake = Fake(failing=["tweaks"])
    widget = page(qtbot, tmp_path, fake)
    run(qtbot, widget)
    fake.mods = ["ub"]                   # the run's plan no longer has tweaks
    run(qtbot, widget, only=True)
    assert fake.calls[-1] == ["tweaks"]
    assert set(widget.rows) == {"ub"} and widget.is_complete()
    assert not widget.retry_button.isEnabled()


def test_back_waits_for_a_running_download(qtbot, tmp_path):
    fake = Fake(hold=True)
    main = MainWindow(str(tmp_path), load=lambda game, project: [],
                      check=lambda *a: {"findings": [], "stale": [], "rules_checked": 0,
                                        "planned": False, "problem": None},
                      plan=lambda *a: {}, download=fake)
    qtbot.addWidget(main)
    main.stack.setCurrentIndex(3)
    main._refresh()
    assert main.back.isEnabled()
    with qtbot.waitSignal(main.download.finished, timeout=5000):
        main.download.start_button.click()
        assert fake.started.wait(5)
        assert not main.back.isEnabled() and not main.next.isEnabled()
        main.go_back()                                   # refused while it runs
        assert main.current == 3
        main.download.stop()
    assert main.back.isEnabled()


# ------------------------------------------- a newer GitHub release (item 59)
OFFER = {"version": "2.1.0", "installed": "v1.5 BETA", "repo": "Gibberlings3/Ascension",
         "date": "2025-05-18", "url": None}


class Offering(Fake):
    """`ascension` came from a forum post; GitHub has 2.1.0 until it is taken."""

    def __init__(self):
        super().__init__(mods=("ascension", "ub"))
        self.taken = []

    def __call__(self, folder, on_event, cancel, only, take_newer=None):
        self.taken.append(list(take_newer or []))
        result = super().__call__(folder, on_event, cancel, only)
        for rec in result["records"]:
            rec["newer"] = (dict(OFFER) if rec["folder"] == "ascension"
                            and "ascension" not in (take_newer or []) else None)
        return result


def test_a_newer_release_is_offered_and_taken_only_when_ticked(qtbot, tmp_path):
    fake = Offering()
    widget = page(qtbot, tmp_path, fake)
    run(qtbot, widget)
    row = widget.rows["ascension"]
    assert "2.1.0 (Gibberlings3/Ascension)" in row.text(4)
    assert "v1.5 BETA" in row.toolTip(4)
    assert row.checkState(4) == Qt.CheckState.Unchecked
    assert widget.rows["ub"].data(4, Qt.ItemDataRole.CheckStateRole) is None
    assert "GitHub has a newer release" in widget.summary.text()
    assert not widget.newer_button.isEnabled()        # nothing ticked, nothing taken

    row.setCheckState(4, Qt.CheckState.Checked)
    assert widget.newer_button.isEnabled()
    with qtbot.waitSignal(widget.finished, timeout=5000):
        widget.newer_button.click()

    assert fake.calls[-1] == ["ascension"] and fake.taken[-1] == ["ascension"]
    assert row.text(4) == "" and row.data(4, Qt.ItemDataRole.CheckStateRole) is None
    assert not widget.newer_button.isEnabled()


def test_a_plain_download_never_asks_for_a_newer_release(qtbot, tmp_path):
    fake = Offering()
    widget = page(qtbot, tmp_path, fake)
    run(qtbot, widget)
    assert fake.taken == [[]]


class TakeFails(Offering):
    """GitHub out of reach when the take is asked for: the core says manual."""

    def __call__(self, folder, on_event, cancel, only, take_newer=None):
        result = super().__call__(folder, on_event, cancel, only, take_newer)
        if take_newer:
            for rec in result["records"]:
                rec.update(status="manual", newer=None,
                           detail="--take-newer: GitHub could not give it; the copy on "
                                  "disk is kept")
        return result


def _ticked_take(qtbot, widget):
    row = widget.rows["ascension"]
    row.setCheckState(4, Qt.CheckState.Checked)
    with qtbot.waitSignal(widget.finished, timeout=5000):
        widget.newer_button.click()
    return row


def test_a_take_that_fails_leaves_the_mod_as_it_was(qtbot, tmp_path):
    """Review of #62: the row flipped to "No download found" and Next locked."""
    widget = page(qtbot, tmp_path, TakeFails())
    run(qtbot, widget)

    row = _ticked_take(qtbot, widget)

    assert row.text(1) == "Done" and widget.is_complete()
    assert "2.1.0" in row.text(4)                         # still offered, to retry
    assert "not installed" in row.text(3) and "GitHub could not" in row.text(3)
    assert not widget.retry_button.isEnabled()


def test_a_cancelled_take_leaves_the_mod_as_it_was(qtbot, tmp_path):
    fake = Offering()
    widget = page(qtbot, tmp_path, fake)
    run(qtbot, widget)
    widget.rows["ascension"].setCheckState(4, Qt.CheckState.Checked)
    fake.hold = True
    with qtbot.waitSignal(widget.finished, timeout=5000):
        widget.newer_button.click()
        fake.started.wait(5)
        widget.stop()

    row = widget.rows["ascension"]
    assert row.text(1) == "Done" and widget.is_complete()
    assert "2.1.0" in row.text(4)


def test_space_ticks_the_selected_rows_offer(qtbot, tmp_path):
    """Review of #62: the box in the last column was out of the keyboard's reach."""
    widget = page(qtbot, tmp_path, Offering())
    run(qtbot, widget)
    widget.table.setCurrentItem(widget.rows["ascension"])

    qtbot.keyClick(widget.table, Qt.Key.Key_Space)

    assert widget.rows["ascension"].checkState(4) == Qt.CheckState.Checked
    assert widget.newer_button.isEnabled()
    widget.table.setCurrentItem(widget.rows["ub"])        # no offer: nothing to tick
    qtbot.keyClick(widget.table, Qt.Key.Key_Space)
    assert widget.rows["ub"].data(4, Qt.ItemDataRole.CheckStateRole) is None
    assert widget.newer_button.accessibleName()


# ------------------------------------------- a download supplied by hand (item 68)
class Gated(Fake):
    """`ub` has no download (its page is gated) until the player supplies a file."""

    def __init__(self):
        super().__init__(mods=("ub", "tweaks"))
        self.supplied = []
        self.threads = []

    def __call__(self, folder, on_event, cancel, only, supplied=None):
        self.calls.append(list(only))
        self.threads.append(threading.current_thread())
        records = []
        for mod in [m for m in self.mods if not only or m in only]:
            if mod == "ub" and not supplied:
                records.append({**record(mod, "manual", "no download found"),
                                "url": "https://www.gibberlings3.net/mods/ub/"})
            elif supplied and mod in supplied:
                self.supplied.append((mod, supplied[mod]))
                records.append({**record(mod, "ok", "installed from the file you chose",
                                         3000), "url": "https://www.gibberlings3.net/mods/ub/"})
            else:
                records.append(record(mod, "ok", f"installed {mod}.tp2", 3000))
        counts = {}
        for r in records:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        return {"records": records, "cancelled": False, "counts": counts, "exit_code": 0}


def test_a_gated_mod_is_opened_in_the_browser_and_supplied_by_hand(qtbot, tmp_path):
    gated, opened, asked = Gated(), [], []
    widget = DownloadPage(str(tmp_path), gated,
                          choose_file=lambda _parent, mod: asked.append(mod) or "/dl/ub.zip",
                          open_url=lambda url: opened.append(url) or True)
    qtbot.addWidget(widget)
    widget.start()
    qtbot.waitUntil(lambda: not widget.running(), timeout=5000)
    assert not widget.is_complete()
    assert "supplied by hand" in widget.summary.text()
    # nothing selected, or a mod already there: neither button applies
    assert not widget.page_button.isEnabled() and not widget.supply_button.isEnabled()
    widget.table.setCurrentItem(widget.rows["tweaks"])
    assert not widget.supply_button.isEnabled()
    widget.table.setCurrentItem(widget.rows["ub"])
    assert widget.page_button.isEnabled() and widget.supply_button.isEnabled()
    widget.page_button.click()
    assert opened == ["https://www.gibberlings3.net/mods/ub/"]
    widget.supply_button.click()
    qtbot.waitUntil(lambda: not widget.running(), timeout=5000)
    assert asked == ["ub"] and gated.supplied == [("ub", "/dl/ub.zip")]
    # hashing and unpacking a file of hundreds of MB never on the window's thread
    assert threading.main_thread() not in gated.threads
    assert gated.calls[-1] == ["ub"]                    # only that mod, nothing else
    assert widget.rows["ub"].text(1) == "Done" and widget.is_complete()


def test_choosing_no_file_starts_nothing(qtbot, tmp_path):
    gated = Gated()
    widget = DownloadPage(str(tmp_path), gated, choose_file=lambda *_a: "",
                          open_url=lambda _url: True)
    qtbot.addWidget(widget)
    widget.start()
    qtbot.waitUntil(lambda: not widget.running(), timeout=5000)
    widget.table.setCurrentItem(widget.rows["ub"])
    widget.supply_button.click()
    assert not widget.running() and len(gated.calls) == 1 and gated.supplied == []


def test_a_row_with_no_page_has_nothing_to_open(qtbot, tmp_path):
    widget = page(qtbot, tmp_path, Fake(failing=("ub",)))
    widget.start()
    qtbot.waitUntil(lambda: not widget.running(), timeout=5000)
    widget.table.setCurrentItem(widget.rows["ub"])
    assert widget.supply_button.isEnabled() and not widget.page_button.isEnabled()


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)",
                                 "ftp://example.org/ub.zip", "C:\\Mods\\ub.zip"])
def test_only_a_web_page_is_ever_opened(qtbot, tmp_path, url):
    """Review of #108: a record's url is opened only when it is http(s)."""
    class Odd(Gated):
        def __call__(self, *args, **kwargs):
            result = super().__call__(*args, **kwargs)
            for r in result["records"]:
                if r["folder"] == "ub":
                    r["url"] = url
            return result
    opened = []
    widget = DownloadPage(str(tmp_path), Odd(), choose_file=lambda *_a: "",
                          open_url=lambda u: opened.append(u) or True)
    qtbot.addWidget(widget)
    widget.start()
    qtbot.waitUntil(lambda: not widget.running(), timeout=5000)
    widget.table.setCurrentItem(widget.rows["ub"])
    assert not widget.page_button.isEnabled()
    widget.open_page()                                  # even called directly
    assert opened == []
