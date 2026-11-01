"""The application: arguments, the QApplication and the main window."""
import argparse
import os
import sys

from iemod_fetch import api


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="iemod-fetch-gui",
        description="The iemod-fetch wizard. Its project folder holds the "
                    f"{api.PROJECT_FILE} the command line reads too.")
    parser.add_argument("--project", default=os.getcwd(),
                        help="project folder (default: the current folder)")
    parser.add_argument("--version", action="version",
                        version=f"iemod-fetch-gui {api.__version__}")
    parser.add_argument("--check", action="store_true",
                        help="open the window and close it at once: proves a build "
                             "starts, Qt included (exit 0, prints 'ok')")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    from PySide6.QtWidgets import QApplication

    from .pages.mods import wait_for_loaders
    from .window import MainWindow
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = MainWindow(os.path.abspath(args.project))
    # A download still running is cancelled first, so the wait below is short.
    app.aboutToQuit.connect(window.download.stop)
    app.aboutToQuit.connect(wait_for_loaders)
    window.show()
    if args.check:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, app.quit)
        code = int(app.exec())
        sys.stdout.write("ok\n" if code == 0 else f"exit {code}\n")
        return code
    return int(app.exec())
