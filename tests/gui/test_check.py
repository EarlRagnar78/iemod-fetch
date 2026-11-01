"""
`iemod-fetch-gui --check` (GUI-AUDIT item 20, ADR-0040): the release build
starts the program once this way before zipping it. Run as a player's shell
would, in a process of its own.
"""
import os
import subprocess
import sys

import pytest

pytest.importorskip("PySide6")


def test_check_opens_the_window_and_says_ok(tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               IEMOD_DATA_DIR=str(tmp_path / "data"))
    done = subprocess.run([sys.executable, "-m", "iemod_fetch_gui", "--check",
                           "--project", str(tmp_path)],
                          env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().splitlines()[-1] == "ok"
