"""
The pages' worker threads hand their result back to the thread that started
them: a page's widgets are changed only there (found by item 23's tests: a
plain function connected to the worker's signal ran in the worker).
"""
import threading

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from iemod_fetch_gui.pages.mods import _in_thread  # noqa: E402


def test_the_result_and_the_end_arrive_in_the_starting_thread_in_order(qtbot):
    here, seen = threading.get_ident(), []
    _in_thread(lambda: 42, lambda result: seen.append(("done", result, threading.get_ident())),
               lambda message: seen.append(("failed", message, threading.get_ident())),
               lambda: seen.append(("finished", None, threading.get_ident())))
    qtbot.waitUntil(lambda: len(seen) == 2, timeout=10000)
    assert seen == [("done", 42, here), ("finished", None, here)]


def test_a_failure_arrives_in_the_starting_thread(qtbot):
    here, seen = threading.get_ident(), []

    def broken():
        raise ValueError("unreadable")

    _in_thread(broken, lambda result: seen.append("done"),
               lambda message: seen.append((message, threading.get_ident())),
               lambda: seen.append("finished"))
    qtbot.waitUntil(lambda: len(seen) == 2, timeout=10000)
    assert seen == [("unreadable", here), "finished"]


def test_a_result_for_a_page_closed_meanwhile_is_dropped(qtbot):
    from PySide6.QtWidgets import QLabel

    from iemod_fetch_gui.pages.mods import wait_for_loaders
    release, seen = threading.Event(), []
    page = QLabel()
    _in_thread(lambda: release.wait(5), lambda result: seen.append("done"),
               lambda message: seen.append("failed"), lambda: seen.append("finished"),
               owner=page)
    page.deleteLater()
    qtbot.wait(50)                          # the page is gone; its thread is not
    release.set()
    wait_for_loaders(5000)
    qtbot.wait(50)
    assert seen == []
