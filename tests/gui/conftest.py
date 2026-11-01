"""GUI tests: PySide6 and pytest-qt, with no screen (QT_QPA_PLATFORM=offscreen).
They are skipped where the GUI extra is not installed - except in CI's GUI job,
which sets IEMOD_REQUIRE_GUI so a missing Qt fails instead of skipping."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.environ.get("IEMOD_REQUIRE_GUI"):
    import PySide6  # noqa: F401
    import pytestqt  # noqa: F401


try:
    import pytest
    from iemod_fetch_gui.pages.mods import wait_for_loaders
except ImportError:                     # no Qt here: the GUI tests skip themselves
    wait_for_loaders = None


if wait_for_loaders is not None:
    @pytest.fixture(autouse=True)
    def _threads_end_with_their_test():
        """A loader or a conflict check a test left running must not outlive it:
        the application waits for them on quit, and so does each test."""
        yield
        wait_for_loaders(10000)
