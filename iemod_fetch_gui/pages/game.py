"""
Phase 1 - game and folders (GUI-AUDIT item 15).

Which game is being built (EET, BGEE or BG2EE), where its folders are, and the
languages to install in. The folders are checked as WeiDU's GAME_IS sees them
(api.check_game_folders) while they are typed, and Next stays disabled until
they are what the game needs. Leaving the phase saves the project's
iemod-fetch.ini, which the command line reads too.
"""
import html

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QRadioButton, QVBoxLayout, QWidget)

from iemod_fetch import api

GAMES = {
    "EET": "Enhanced Edition Trilogy: BG:EE with Siege of Dragonspear, merged into BG2:EE",
    "BGEE": "Baldur's Gate: Enhanced Edition",
    "BG2EE": "Baldur's Gate II: Enhanced Edition",
}
NEEDS = {"EET": ("bgee", "bg2ee"), "BGEE": ("bgee",), "BG2EE": ("bg2ee",)}
CHECK_DELAY_MS = 250      # typing a path re-checks once the typing stops


class FolderRow(QWidget):
    """A path field with a Browse button."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = title
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("the folder that holds chitin.key")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit, 1)
        layout.addWidget(browse)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self.title, self.edit.text())
        if folder:
            self.edit.setText(folder)

    def path(self) -> str | None:
        return self.edit.text().strip() or None


class GamePage(QWidget):
    completeChanged = Signal(bool)

    def __init__(self, project_dir: str) -> None:
        super().__init__()
        self.project_dir = project_dir
        self.result: dict = {"ok": False, "problems": [], "notes": []}
        self.load_problem: str | None = None

        self.game_buttons = QButtonGroup(self)
        games = QGroupBox("Game")
        games_layout = QVBoxLayout(games)
        self.radios: dict[str, QRadioButton] = {}
        for code, text in GAMES.items():
            radio = QRadioButton(f"{code} - {text}")
            self.radios[code] = radio
            self.game_buttons.addButton(radio)
            games_layout.addWidget(radio)
            radio.toggled.connect(self._game_changed)

        self.bgee = FolderRow("The BG:EE game folder")
        self.bg2ee = FolderRow("The BG2:EE game folder")
        self.folders = QGroupBox("Game folders")
        self.folder_form = QFormLayout(self.folders)
        self.folder_form.addRow("BG:EE folder", self.bgee)
        self.folder_form.addRow("BG2:EE folder", self.bg2ee)
        for row in (self.bgee, self.bg2ee):
            row.edit.textChanged.connect(self._schedule_check)

        self.preferred = QComboBox()
        self.fallback = QComboBox()
        self.fallback.addItem("(none)", None)
        for language in api.languages():
            label = f"{language['name']} ({language['code']})"
            self.preferred.addItem(label, language["code"])
            self.fallback.addItem(label, language["code"])
        languages = QGroupBox("Languages")
        languages_form = QFormLayout(languages)
        languages_form.addRow("Install in", self.preferred)
        languages_form.addRow("else in", self.fallback)
        hint = QLabel("A mod that offers neither keeps the language its list names, "
                      "and is reported.")
        hint.setWordWrap(True)
        languages_form.addRow(hint)

        self.findings = QLabel()
        self.findings.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>1. Game and folders</h2>"))
        layout.addWidget(games)
        layout.addWidget(self.folders)
        layout.addWidget(languages)
        layout.addWidget(self.findings)
        layout.addStretch(1)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(CHECK_DELAY_MS)
        self.timer.timeout.connect(self.check)
        self._load()

    # ------------------------------------------------------------ state
    def game(self) -> str | None:
        return next((code for code, radio in self.radios.items() if radio.isChecked()),
                    None)

    def language_preference(self) -> list[str]:
        out = [self.preferred.currentData()]
        if self.fallback.currentData() and self.fallback.currentData() not in out:
            out.append(self.fallback.currentData())
        return out

    def is_complete(self) -> bool:
        return bool(self.game()) and bool(self.result.get("ok"))

    def _load(self) -> None:
        project = api.load_project(self.project_dir)
        self.load_problem = project.get("problem")
        self.radios[project["game"] or "EET"].setChecked(True)
        self.bgee.edit.setText(project["bgee_dir"] or "")
        self.bg2ee.edit.setText(project["bg2ee_dir"] or "")
        wanted = project["language_preference"] or ["en_US"]
        self._select(self.preferred, wanted[0])
        self._select(self.fallback, wanted[1] if len(wanted) > 1 else
                     ("en_US" if wanted[0] != "en_US" else None))
        self.check()

    @staticmethod
    def _select(combo: QComboBox, code: str | None) -> None:
        index = combo.findData(code)
        combo.setCurrentIndex(max(index, 0))

    def save(self) -> str:
        game = self.game() or "EET"
        return api.save_project(self.project_dir, game, self.bgee.path(),
                                self.bg2ee.path(), self.language_preference())

    # ----------------------------------------------------------- checks
    def _game_changed(self, checked: bool) -> None:
        if not checked:
            return
        needs = NEEDS[self.game() or "EET"]
        self.folder_form.setRowVisible(self.bgee, "bgee" in needs)
        self.folder_form.setRowVisible(self.bg2ee, "bg2ee" in needs)
        self._schedule_check()

    def _schedule_check(self) -> None:
        # What was checked no longer holds: Next waits for the new check.
        self.result = {"ok": False, "problems": [], "notes": []}
        self.completeChanged.emit(False)
        self.timer.start()

    def check(self) -> dict:
        """Check the folders now; the result decides whether Next is enabled."""
        self.timer.stop()
        game = self.game() or "EET"
        self.result = api.check_game_folders(game, self.bgee.path(), self.bg2ee.path())
        e = html.escape                       # paths and the folders' own names
        lines = [f"<b>Problem:</b> {e(problem)}" for problem in self.result["problems"]]
        if self.result["ok"]:
            lines.insert(0, f"<b>The folders are what {game} needs.</b>")
        if self.load_problem:
            lines.append(f"<b>The project's {api.PROJECT_FILE} could not be read</b> "
                         f"({e(self.load_problem)}). The command line reads the same file: "
                         f"fix it there.")
        lines += [f"Not checked: {e(note)}" if note.startswith(("the patch", "whether"))
                  else f"Note: {e(note)}" for note in self.result["notes"]]
        self.findings.setText("<br>".join(lines))
        self.completeChanged.emit(self.is_complete())
        return self.result
