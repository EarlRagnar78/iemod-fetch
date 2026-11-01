"""
Text that is not ours, shown as text (review of #123).

Qt decides by itself whether a string is rich text (Qt::mightBeRichText): a
tooltip, a QLabel left at its default (AutoText) or a QMessageBox renders
catalogue text, a mod's name, a path or an error message as HTML when it
looks like HTML. Here:

- `plain_tip` makes a tooltip of any text, escaped whole: tooltips have no
  plain-text switch, so the text is escaped and handed over as rich text
  that holds no markup but line breaks;
- `critical`, `question` and `information` are QMessageBox's static
  functions with the same arguments, the text shown as plain text;
- `get_text` is QInputDialog.getText with its prompt as plain text;
- a QLabel showing such text is set to Qt.TextFormat.PlainText where it is
  made.
"""
import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QInputDialog, QLabel, QMessageBox, QWidget


def plain_tip(text: str) -> str:
    """A tooltip that shows `text` exactly as written, its spaces too."""
    if not text:
        return ""
    return ('<qt style="white-space:pre-wrap">' + html.escape(str(text)).replace("\n", "<br>")
            + "</qt>")


def get_text(parent: QWidget | None, title: str, label: str) -> tuple[str, bool]:
    """QInputDialog.getText with its prompt shown as plain text: a mod's
    question ("Enter the kit for <name>:") keeps its words (review of #124)."""
    dialog = QInputDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setLabelText(str(label))
    for child in dialog.findChildren(QLabel):
        child.setTextFormat(Qt.TextFormat.PlainText)
    ok = dialog.exec() == QDialog.DialogCode.Accepted
    return dialog.textValue(), ok


def _box(parent: QWidget | None, icon: QMessageBox.Icon, title: str, text: str,
         buttons: QMessageBox.StandardButton) -> QMessageBox.StandardButton:
    box = QMessageBox(icon, title, str(text), buttons, parent)
    box.setTextFormat(Qt.TextFormat.PlainText)
    return QMessageBox.StandardButton(box.exec())


def critical(parent: QWidget | None, title: str, text: str) -> QMessageBox.StandardButton:
    return _box(parent, QMessageBox.Icon.Critical, title, text,
                QMessageBox.StandardButton.Ok)


def information(parent: QWidget | None, title: str, text: str) -> QMessageBox.StandardButton:
    return _box(parent, QMessageBox.Icon.Information, title, text,
                QMessageBox.StandardButton.Ok)


def question(parent: QWidget | None, title: str, text: str) -> QMessageBox.StandardButton:
    return _box(parent, QMessageBox.Icon.Question, title, text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
