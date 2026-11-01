"""
The conflicts panel of phase 2 (GUI-AUDIT item 16, ADR-0033).

What fights what in the current selection, each with the ways to clear it as
buttons. A button does one of four things, never more:

* **deselect** - unchoose the components of that side in the tree;
* **install** - choose the missing prerequisite's components, when the
  catalogue knows them;
* **keep both** - for two components that touch the same thing, where no
  rule says they must not coexist: write to decisions.json which one is
  installed last; the planned order then puts it after the other (item 28);
* **accept** - write the player's answer, with the reason, to decisions.json,
  which the command line applies with --decisions.

A **reorder** is shown, not offered: the planned order applies it by itself
where it can, and a finding listed here is one it could not settle, so
recording it would change nothing (ADR-0033).

A finding the planned install order already settles is counted, not listed as
work. Everything shown is third-party text (rules, mod names), so it is set as
plain text, never as markup.
"""
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
                               QMessageBox, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from iemod_fetch_gui import text as qtext

SEVERITY = {"error": "Error", "warning": "Warning", "note": "Note"}
ACTIONS = {"deselect": "Deselect", "install": "Choose", "reorder": "Install order:"}


def plain(text: str) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def side_text(side: dict | None) -> str:
    if not side:
        return ""
    if side.get("whole_mod") or not side.get("components"):
        return f"{side['mod']} (whole mod)"
    shown = ", ".join(f"#{n}" for n in side["components"][:6])
    more = len(side["components"]) - 6
    return f"{side['mod']} {shown}" + (f", +{more} more" if more > 0 else "")


def open_findings(result: dict) -> list[dict]:
    """The findings that are still the player's: not settled by the plan, not decided."""
    return [f for f in result.get("findings") or []
            if not f.get("fixed_by_plan") and not f.get("decision")]


class ConflictsPanel(QWidget):
    deselect = Signal(list)          # [[tp2, number], ...] to unchoose
    choose = Signal(str, list)       # mod key, component numbers to choose
    decide = Signal(str, str, str)   # finding id, option id or "", why or ""
    undo = Signal(str)               # finding id
    forget = Signal(list)            # decided finding ids no finding has any more
    check = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.result: dict = {}
        # Set by the page: whether the list can choose these components of a mod.
        self.can_choose: Callable[[str, list[int]], bool] = lambda _key, _numbers: False
        self.summary = plain("Not checked yet.")
        self.again = QPushButton("Check again")
        self.again.clicked.connect(self.check.emit)
        top = QHBoxLayout()
        top.addWidget(self.summary, 1)
        top.addWidget(self.again)
        self.body = QWidget()
        self.rows = QVBoxLayout(self.body)
        self.rows.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.body)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(scroll, 1)
        self.buttons: dict[str, QPushButton] = {}     # option id (or "accept:" id) -> button

    def busy(self) -> None:
        self.summary.setText("Checking the selection against the rules...")

    def failed(self, message: str) -> None:
        self.clear()                    # no button may act on a result that no longer holds
        self.summary.setText(f"The conflicts could not be checked: {message}")

    def clear(self) -> None:
        self.result = {}
        self.buttons.clear()
        while self.rows.count() > 1:
            item = self.rows.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.summary.setText("Not checked yet.")

    def show_result(self, result: dict) -> None:
        self.clear()
        self.result = result
        findings = result.get("findings") or []
        settled = sum(1 for f in findings if f.get("fixed_by_plan"))
        decided = [f for f in findings if f.get("decision") and not f.get("fixed_by_plan")]
        waiting = open_findings(result)
        parts = [f"{len(waiting)} conflict(s) to decide"]
        if decided:
            parts.append(f"{len(decided)} decided")
        if settled:
            parts.append(f"{settled} settled by the install order")
        if not result.get("planned"):
            parts.append("no install order to judge by (no krion64 data)")
        if not result.get("rules_checked"):
            parts = ["No rules to check against: the community data is not here yet."]
        self.summary.setText("; ".join(parts) + ".")
        if result.get("problem"):
            self.rows.insertWidget(self.rows.count() - 1, plain(
                f"decisions.json could not be read, and is not used: {result['problem']}"))
        elif result.get("stale") and result.get("rules_checked"):
            self.rows.insertWidget(self.rows.count() - 1, self._stale(list(result["stale"])))
        order = sorted(waiting, key=lambda f: ("error", "warning", "note").index(
            f["severity"]) if f["severity"] in ("error", "warning", "note") else 3)
        for finding in order + decided:
            self.rows.insertWidget(self.rows.count() - 1, self._row(finding))

    def _stale(self, ids: list[str]) -> QWidget:
        """The decisions no finding of this selection has, and a way to drop them."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(plain(f"{len(ids)} decision(s) in decisions.json no longer match "
                               f"a conflict of this selection; they are not applied."), 1)
        forget = QPushButton("Forget them...")
        forget.setToolTip("Remove them from decisions.json. A decision about a mod you "
                          "only unticked for now is removed too.")
        forget.clicked.connect(lambda _c=False, i=ids: self._forget(i))
        self.buttons["forget:"] = forget
        layout.addWidget(forget)
        return row

    def _forget(self, ids: list[str]) -> None:
        answer = qtext.question(
            self, "Forget decisions",
            f"Remove {len(ids)} decision(s) from decisions.json?\n\n" + "\n".join(ids[:10])
            + ("\n..." if len(ids) > 10 else ""))
        if answer == QMessageBox.StandardButton.Yes:
            self.forget.emit(ids)

    def _row(self, finding: dict) -> QGroupBox:
        title = SEVERITY.get(finding["severity"], finding["severity"].title())
        box = QGroupBox(f"{title}: {finding['kind']}")
        layout = QVBoxLayout(box)
        what = side_text(finding["left"])
        if finding.get("right"):
            what += ("  needs  " if finding["kind"] == "depends" else "  vs  ") + \
                side_text(finding["right"])
        layout.addWidget(plain(what))
        for text in (finding.get("reason"), finding.get("workaround")):
            if text:
                layout.addWidget(plain(text))
        if finding.get("evidence") == "speculative":
            layout.addWidget(plain("Speculative: nobody has verified this. Judge it yourself."))
        buttons = QHBoxLayout()
        decision = finding.get("decision")
        if decision:
            chosen = decision.get("choose")
            text = (next((o["description"] for o in finding["options"]
                          if o["id"] == chosen), chosen) if chosen
                    else f"accepted: {decision.get('accept')}")
            layout.addWidget(plain(f"Your decision: {text}"))
            undo = QPushButton("Undo")
            undo.clicked.connect(lambda _c=False, f=finding["id"]: self.undo.emit(f))
            buttons.addWidget(undo)
        else:
            for option in finding["options"]:
                buttons.addWidget(self._option(option, finding["id"]))
            accept = QPushButton("Accept...")
            accept.setToolTip("Keep both sides; you give the reason, and the report "
                              "keeps it visible as accepted.")
            accept.clicked.connect(lambda _c=False, f=finding: self._accept(f))
            self.buttons["accept:" + finding["id"]] = accept
            buttons.addWidget(accept)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return box

    def _option(self, option: dict, finding: str) -> QPushButton:
        label = option["description"]
        if option.get("recommended"):
            label += "  (recommended)"
        button = QPushButton(label)
        self.buttons[option["id"]] = button
        action = option["action"]
        if action == "deselect":
            pairs = option.get("chosen") or []
            button.setEnabled(bool(pairs))
            button.clicked.connect(lambda _c=False, p=pairs: self.deselect.emit(p))
        elif action == "keep-both":
            button.setToolTip("Keep both; this one is installed after the other, so "
                              "what they both change is left as it makes it. Saved in "
                              "decisions.json: the wizard's install order follows it, "
                              "and a command-line run with --decisions.")
            button.clicked.connect(lambda _c=False, f=finding, o=option["id"]:
                                   self.decide.emit(f, o, ""))
        elif action == "install":
            key = option.get("key", "")
            numbers = list(option["components"])
            if self.can_choose(key, numbers):
                button.clicked.connect(lambda _c=False, k=key, n=numbers: self.choose.emit(k, n))
            else:
                button.setEnabled(False)
                button.setToolTip("Not in the list for this game with these components: "
                                  "it has to be added to the catalogue or fetched first.")
        else:
            # Reorder: sorting the plan is what applies it, and this finding is
            # one the planned order did not settle (a cycle, or no order data).
            # Recording it would change nothing, so it is not offered as a choice.
            button.setEnabled(False)
            button.setToolTip("The install order applies this by itself where it can; "
                              "here it could not (no krion64 order data, or the rules "
                              "contradict each other). Deselect a side or accept it.")
        return button

    def _accept(self, finding: dict) -> None:
        why, ok = QInputDialog.getText(self, "Accept this conflict",
                                       "Why is it acceptable? (kept in decisions.json)")
        if ok and why.strip():
            self.decide.emit(finding["id"], "", why.strip())
