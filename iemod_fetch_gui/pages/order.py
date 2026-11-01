"""
Phase 3 - install order (GUI-AUDIT item 17, ADR-0038).

The chosen components as the run will install them: planned by the same
planner as --plan-order (krion64's categories, then every order rule, the
authors' own inis included), one tab per install - for EET, BG:EE before the
conversion and EET itself. A mod a rule places is marked; one an order rule
still finds wrong is marked in red, with the rule. A mod krion64 does not
place takes its place in BWS-NG's EET sequence, marked "by BWS-NG", else the
place its kind decides, marked "by kind" with its source, or says why it has
none (items 27 and 27a, ADR-0041).

Dragging a mod writes the whole order shown as `install-order.txt` in the
project - a Project Infinity Sorting Order file, which the command line reads
with --sorting-order (the project's ini names it) - and plans again: the
player's order goes on top of the rules, and where it contradicts one the
contradiction is shown, never silently won either way. "Use the computed
order" deletes the file. "Split into components" turns the selected mod into
one row per component, so a single component can be dragged on its own (M5b
item 30); its lines are written `tp2 n`, as the command line reads them.
"Fix..." on a red row offers what mends it (M5b item 32), each previewed
before it is applied: the row just after the mod a rule puts before it, or
just before the one a rule puts after it; the row planned again by the rules
with your other moves kept; or its components turned off. Only a fix that
mends its rule and adds no other broken rule and no new error is applied.
Under the list, the selected row's panel (M5b item 33): every order rule on
it - what it must come after or before, the rule as written and where it
comes from - red where it is broken now, dimmed where it names a whole mod
rather than components. "Ignore..." keeps a red row's broken rules as the
player's call, with why, in decisions.json: the row is shown grey, not red,
while it stays where it is and breaks no other rule; dragging it, or a rule
it newly breaks, shows it red again.

Rows are selected as in any list (Shift, Ctrl), dragged together, and moved
one place with Ctrl+Up / Ctrl+Down; "Find" selects the rows that match in the
tab shown, so they can be moved at once (M5b item 35). Coming back to the page
with nothing changed - selection, project files, community data - keeps the
plan shown rather than planning again.
"""
import html
import os
import time
from collections.abc import Callable

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QThread, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from iemod_fetch import api

from iemod_fetch_gui import text as qtext

from .mods import Key, _in_thread, _target, selection_digest

Planner = Callable[[str, list[Key], dict, str], dict]
# (game, chosen, labels, project folder, the order by hand or None) -> a plan
# with "errors" (api.preview_install_order); nothing is written
Previewer = Callable[[str, list[Key], dict, str, list | None], dict]
ROLE = Qt.ItemDataRole.UserRole
NODE = Qt.ItemDataRole.UserRole + 1
RED = QColor(176, 0, 32)
GREY = QColor(128, 128, 128)          # an ignored row; a rule naming a whole mod


def plan_selection(game: str, chosen: list[Key], labels: dict, project_dir: str) -> dict:
    """The real planner: the run's own, on the project's data and install-order.txt."""
    project = api.load_project(project_dir)
    return api.selection_plan(game, chosen, labels, folder=project_dir,
                              target=_target(project), fetch_metadata=True)


def preview_selection(game: str, chosen: list[Key], labels: dict, project_dir: str,
                      phases: list | None) -> dict:
    """The real preview: the planner on the project's data, with `phases` as
    the order by hand, writing nothing."""
    project = api.load_project(project_dir)
    return api.preview_install_order(game, chosen, labels, folder=project_dir,
                                     phases=phases, target=_target(project),
                                     fetch_metadata=True)


def _same_component(unit: dict) -> Callable[[Key], bool]:
    """Whether a chosen (tp2, number) is one of `unit`'s components."""
    mine = {(path.lower(), number) for path, number, _label in unit["components"]}
    return lambda key: (key[0].replace("\\", "/").lower(), key[1]) in mine


def _judged(unit: dict, out: dict) -> list[tuple[str, str, bool]]:
    """The planner's previews of a row's fixes, against the plan as it is:
    (kind, what the preview says, whether the fix may be applied)."""
    base = out["base"]
    mine = _same_component(unit)
    judged = []
    for kind in ("replan", "off"):
        result = out.get(kind)
        if result is None:
            continue
        broken = sorted(set(result.get("violations") or ())
                        - set(base.get("violations") or ()))
        errors = sorted(set(result.get("errors") or ()) - set(base.get("errors") or ()))
        lines, still = [], False
        if kind == "replan":
            for phase in result.get("phases") or ():
                rows = phase["units"]
                for n, other in enumerate(rows):
                    if not any(mine((c[0], c[1])) for c in other["components"]):
                        continue
                    still = still or other["flagged"]
                    after = rows[n - 1]["name"] if n else "the start"
                    lines.append(f"{other['name']} would go after {after} "
                                 f"({phase['title']}, row {n + 1} of {len(rows)}).")
            if still:
                lines.append("A rule still finds it in the wrong place.")
        else:
            lines.append(f"{unit['name']} is left out of the selection.")
        lines += [f"Newly broken: {text}" for text in broken]
        lines += [f"New error: {text}" for text in errors]
        ok = not (broken or errors or still)
        lines.append("It mends the rule and breaks nothing else." if ok
                     else "So it is not applied.")
        judged.append((kind, "\n".join(lines), ok))
    return judged


def _plain(text: str) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class FixDialog(QDialog):
    """
    The fixes of one red row, each previewed before it is applied (M5b item
    32). A move is checked at once against the plan's rules; planning the row
    again and turning it off are previewed by the planner, in the background.
    """
    previewed = Signal()

    def __init__(self, parent: QWidget, unit: dict, fixes: list[dict]) -> None:
        super().__init__(parent)
        name = unit["name"]
        self.setWindowTitle(f"Fix {name}")
        # one per click: freed once closed (a preview still on its way is
        # then dropped by Qt with it)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.unit = unit
        self.fixes = fixes
        self.options = QListWidget()
        for fix in fixes:
            self.options.addItem(fix["label"])
        self.preview = _plain("")
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.apply = self.buttons.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.options.currentRowChanged.connect(lambda _row: self._show())
        layout = QVBoxLayout(self)
        layout.addWidget(_plain(f"{name} is in the wrong place for a rule. Choose a fix: "
                                "each is previewed here, and only one that mends the rule "
                                "without breaking another or adding an error is applied."))
        layout.addWidget(self.options)
        layout.addWidget(self.preview)
        layout.addWidget(self.buttons)
        self.options.setCurrentRow(0)
        self._show()

    def chosen(self) -> dict | None:
        row = self.options.currentRow()
        return self.fixes[row] if 0 <= row < len(self.fixes) else None

    # Slots of this object, so a worker thread's answer is handled in the
    # window's thread, never in the worker's.
    def planner_done(self, out: dict) -> None:
        """The planner's previews have come back."""
        for kind, text, ok in _judged(self.unit, out):
            self._previewed(kind, text, ok)
        self.previewed.emit()

    def planner_failed(self, message: str) -> None:
        for kind in ("replan", "off"):
            self._previewed(kind, f"No preview: {message}", False)
        self.previewed.emit()

    def planner_finished(self) -> None:
        pass

    def _previewed(self, kind: str, preview: str, ok: bool) -> None:
        for fix in self.fixes:
            if fix["kind"] == kind:
                fix.update(preview=preview, ok=ok)
        self._show()

    def _show(self) -> None:
        fix = self.chosen()
        self.preview.setText(fix["preview"] if fix else "")
        self.apply.setEnabled(bool(fix and fix["ok"]))


class OrderPage(QWidget):
    completeChanged = Signal(bool)
    planned = Signal()
    # the components a fix turns off, (tp2, number): the window unticks them
    # on the mods page and plans again
    turn_off = Signal(list)

    def __init__(self, project_dir: str, plan: Planner = plan_selection,
                 preview: Previewer = preview_selection) -> None:
        super().__init__()
        self.project_dir = project_dir
        self.plan = plan
        self.preview = preview
        self.fixing: FixDialog | None = None
        self.result: dict = {}
        self.wanted: tuple[str, list[Key], dict] | None = None
        self._planning: QThread | None = None
        self._again = False
        self._generation = 0
        self.last_check_ms = 0.0               # the last check after a drop (item 31)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(lambda _index: self._can_split())
        self.summary = _plain("The order is planned once the mods are chosen.")
        self.problems = _plain("")
        self.problems.setStyleSheet("color: #b00020")
        self.reset = QPushButton("Use the computed order")
        self.reset.setToolTip(f"Forget the order set by hand ({api.INSTALL_ORDER_FILE})")
        self.reset.clicked.connect(self._reset)
        self.split = QPushButton("Split into components")
        self.split.setToolTip("One row per component of the selected mod, to move "
                              "one of them on its own")
        self.split.setEnabled(False)
        self.split.clicked.connect(self._split)
        self.join = QPushButton("Join the parts")
        self.join.setToolTip("The selected mod's parts in this tab as one row again")
        self.join.setEnabled(False)
        self.join.clicked.connect(self._join)
        self.fix = QPushButton("Fix...")
        self.fix.setToolTip("What mends the selected red row, previewed before it is applied")
        self.fix.setEnabled(False)
        self.fix.clicked.connect(self._fix)
        self.ignore = QPushButton("Ignore...")
        self.ignore.setToolTip("Keep the selected red row where it is: its broken rules "
                               "are your call, kept in decisions.json with why")
        self.ignore.setEnabled(False)
        self.ignore.clicked.connect(self._ignore)
        self.panel = QLabel("")
        self.panel.setTextFormat(Qt.TextFormat.RichText)
        self.panel.setWordWrap(True)
        bar = QHBoxLayout()
        bar.addWidget(self.summary, 1)
        bar.addWidget(self.split)
        bar.addWidget(self.join)
        bar.addWidget(self.fix)
        bar.addWidget(self.ignore)
        bar.addWidget(self.reset)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>3. Install order</h2>"))
        layout.addWidget(_plain(
            "Drag a mod - or, split, one of its components - to change where it is "
            "installed. Bold: a rule places it. "
            "Red: a rule says it is in the wrong place. Your order is kept in "
            f"{api.INSTALL_ORDER_FILE}, which the command line uses too."))
        layout.addLayout(bar)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Find rows (they are selected: drag them, or "
                                     "Ctrl+Up / Ctrl+Down)")
        self.find.setClearButtonEnabled(True)
        self.find.textChanged.connect(lambda _text: self._find())
        layout.addWidget(self.find)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.panel)
        layout.addWidget(self.problems)
        for keys, step in (("Ctrl+Up", -1), ("Ctrl+Down", 1)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda step=step: self.nudge(step))
        self._batch = False                    # rows moved as one: saved once
        self._planned = ""                     # the digest the plan shown answers
        self._planning_digest = ""

    # ----------------------------------------------------------- planning
    def start(self, game: str, chosen: list[Key], labels: dict) -> None:
        """Plan `chosen` for `game`, in a worker thread - unless the plan shown
        already answers it: nothing it reads has changed (item 35)."""
        if (self.result and self._planning is None
                and self._planned == selection_digest(game, chosen, labels,
                                                      self.project_dir)):
            self.completeChanged.emit(self.is_complete())
            self.planned.emit()
            return
        self.wanted = (game, list(chosen), dict(labels))
        self._generation += 1
        self.result = {}
        self.completeChanged.emit(False)
        self._plan()

    def _plan(self) -> None:
        if self.wanted is None:
            return
        if self._planning is not None:
            self._again = True
            return
        self._again = False
        self.summary.setText("Planning the install order...")
        self.split.setEnabled(False)
        self.join.setEnabled(False)
        self.fix.setEnabled(False)
        self.ignore.setEnabled(False)
        self.completeChanged.emit(False)        # Next waits for this plan
        plan, (game, chosen, labels) = self.plan, self.wanted
        generation, folder = self._generation, self.project_dir
        self._planning_digest = selection_digest(game, chosen, labels, folder)

        def run():
            try:
                return generation, plan(game, chosen, labels, folder), ""
            except Exception as exc:        # shown on the page, never a crash
                return generation, None, str(exc)
        self._planning = _in_thread(run, self._done, self._failed, self._finished)

    def _failed(self, message: str) -> None:
        self.summary.setText(f"The install order could not be planned: {message}")

    def _done(self, outcome: tuple) -> None:
        generation, result, problem = outcome
        if generation != self._generation:
            return                          # planned a selection no longer wanted
        if result is None:
            self.result = {}
            self._planned = ""
            self.tabs.clear()
            self._failed(problem)
            self.completeChanged.emit(False)
            return
        self._planned = self._planning_digest
        self.show_result(result)

    def _finished(self) -> None:
        self._planning = None
        self._can_split()
        if self._again:
            self._plan()
            return
        self.completeChanged.emit(self.is_complete())   # the window refreshes Next
        self.planned.emit()

    def show_result(self, result: dict) -> None:
        self.result = result
        self.split.setEnabled(False)            # the rows it would split are gone
        self.join.setEnabled(False)
        self.fix.setEnabled(False)
        self.ignore.setEnabled(False)
        self.panel.setText("")
        current = self.tabs.currentIndex()
        self.tabs.clear()
        if not result.get("planned"):
            self.summary.setText("No install order to plan against: krion64's data is "
                                 "not here yet. The run will keep the order chosen.")
            self.problems.setText("")
            self.completeChanged.emit(True)
            return
        for phase in result["phases"]:
            self.tabs.addTab(self._list(phase), f"{phase['title']} "
                                                f"({len(phase['units'])})")
        self.tabs.setCurrentIndex(max(0, min(current, self.tabs.count() - 1)))
        units = [u for p in result["phases"] for u in p["units"]]
        parts = [f"{len({u['key'] for u in units})} mod(s) in order",
                 f"{sum(u['constrained'] for u in units)} placed by a rule",
                 f"{sum(u['moved'] for u in units)} moved from where they were chosen"]
        # a split mod is one mod placed by its kind, not one per part
        placed = {u["key"]: u.get("placed_from") for u in units if u.get("placed_by")}
        by_bws = sum(source == "BWS-NG" for source in placed.values())
        if result.get("custom"):
            parts.append("your own order applies")    # over every kind's place
        else:
            if len(placed) - by_bws:
                parts.insert(2, f"{len(placed) - by_bws} placed by kind")
            if by_bws:
                parts.insert(2, f"{by_bws} placed by BWS-NG's sequence")
        self.summary.setText("; ".join(parts) + ".")
        self.reset.setEnabled(bool(result.get("custom")))
        # a rule every row it names ignores says so, as those rows do (item 33)
        whys: dict[str, list[str]] = {}
        for unit in units:
            for broken in unit.get("broken") or ():
                whys.setdefault(broken, []).append(
                    unit["ignored"]["why"] if unit.get("ignored") else "")
        lines = [f"{line} (ignored: {whys[line][0]})"
                 if whys.get(line) and all(whys[line]) else line
                 for line in result.get("violations") or []]
        lines += ["These rules contradict each other, one was set aside: "
                  + " -> ".join(cycle) for cycle in result.get("cycles") or []]
        self.problems.setText("\n".join(lines))
        self.completeChanged.emit(True)

    def _list(self, phase: dict) -> QListWidget:
        widget = QListWidget()
        widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        widget.setDefaultDropAction(Qt.DropAction.MoveAction)
        widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for unit in phase["units"]:
            widget.addItem(self._item(unit))
        before = {unit["node"]: list(unit.get("after") or ()) for unit in phase["units"]}
        followers = api.order_followers(before)
        breaks = api.order_breaks([unit["node"] for unit in phase["units"]], before)
        widget.setProperty("breaks", breaks)

        def dropped(_parent, start, end, _dest, row) -> None:
            # a block of rows lands where the row Qt names was, less itself
            # when it came from above (item 35)
            count = end - start + 1
            first = row - count if row > start else row
            for at in range(first, first + count):
                self._dropped(widget, at, before, followers)
                unit = widget.item(at).data(ROLE) if 0 <= at < widget.count() else None
                if isinstance(unit, dict) and unit.get("ignored"):
                    self._unignore(unit["node"])  # a row moved is shown again (item 33)
            if not self._batch:
                self._reordered()
        widget.model().rowsMoved.connect(dropped)
        widget.currentItemChanged.connect(lambda *_args: self._can_split())
        return widget

    def _item(self, unit: dict) -> QListWidgetItem:
        custom = bool(self.result and self.result.get("custom"))
        text = unit["name"] + (f"  -  {unit['category']}" if unit["category"] else "")
        if unit.get("placed_by") and not custom:
            text += ("  (by BWS-NG)" if unit.get("placed_from") == "BWS-NG"
                     else "  (by kind)")
        item = QListWidgetItem(text)
        item.setData(ROLE, unit)
        item.setData(NODE, unit["node"])      # read on every drop: a string, not the dict
        components = ", ".join(f"#{c[1]}" for c in unit["components"][:12])
        tips = [f"Components: {components}"]
        if unit["constrained"]:
            font = QFont(item.font())
            font.setBold(True)
            item.setFont(font)
            tips.append("A rule places it relative to another mod.")
        if unit.get("placed_by") and custom:
            tips.append("krion64 does not place it; its kind would ("
                        + unit["placed_by"] + "), but your own order applies.")
        elif unit.get("placed_by"):
            tips.append("krion64 does not place it: " + unit["placed_by"] + ".")
        elif unit.get("no_place"):
            tips.append("krion64 does not place it, and it stays where it was "
                        "chosen - " + unit["no_place"] + ".")
        if unit["moved"]:
            tips.append("Moved from where it was chosen, by the rules.")
        if unit["flagged"] and unit.get("ignored"):
            item.setForeground(QBrush(GREY))
            item.setText(text + "  (ignored)")
            tips.append("A rule says it is in the wrong place; you ignore it: "
                        + unit["ignored"]["why"])
        elif unit["flagged"]:
            item.setForeground(QBrush(RED))
            tips.append("An order rule says it is in the wrong place (see below).")
        item.setToolTip(qtext.plain_tip("\n".join(tips)))
        return item

    # ---------------------------------------------------------- reordering
    def phases(self) -> list[list[dict]]:
        """Each tab's units, in the order shown."""
        out = []
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            out.append([widget.item(row).data(ROLE) for row in range(widget.count())])
        return out

    def _dropped(self, widget: QListWidget, row: int, before: dict, followers: dict) -> None:
        """
        The marks right after a drop, before the plan comes back: only the
        rules the moved row is in are checked again (M5b item 31; the full
        plan still follows, in the background, and replaces them).
        """
        started = time.perf_counter()
        items = [widget.item(r) for r in range(widget.count())]
        order = [item.data(NODE) for item in items]
        if len(set(order)) < len(order):
            # A split or a join not yet planned: its parts still share the
            # mod's node and the rules are the old plan's, so which row moved
            # and what it breaks cannot be told - the plan's marks follow
            # (review of #75).
            self.problems.setText("Checked when the plan comes back.")
            return
        moved = order[row] if 0 <= row < len(order) else ""
        previous = set(widget.property("breaks") or ())
        breaks = api.order_breaks_after_move(previous, order, before, moved, followers)
        widget.setProperty("breaks", breaks)
        wrong = {node for pair in breaks for node in pair}
        # only the rows whose mark changes are painted again
        changed = wrong ^ {node for pair in previous for node in pair}
        for item, node in zip(items, order, strict=True):
            if node in changed:
                item.setForeground(QBrush(RED) if node in wrong
                                   else widget.palette().text())
        self.last_check_ms = (time.perf_counter() - started) * 1000
        self.problems.setText(f"{len(breaks)} rule(s) broken by this order, checked "
                              "at once; the full plan follows." if breaks else "")

    def _reordered(self) -> None:
        try:
            api.save_install_order(self.project_dir, self.phases())
        except Exception as exc:
            qtext.critical(self, "Cannot save the install order", str(exc))
        # Planned again either way: the list must show what is saved, not
        # the drag that could not be.
        self._generation += 1
        self._plan()

    def _selected(self) -> tuple[QListWidget | None, int]:
        widget = self.tabs.currentWidget()
        if not isinstance(widget, QListWidget) or widget.currentRow() < 0:
            return None, -1
        return widget, widget.currentRow()

    def _can_split(self) -> None:
        """Split and Join act on the rows shown, and only once they are the
        plan's: while a plan is under way they wait (review of #74)."""
        widget, row = self._selected()
        unit = widget.item(row).data(ROLE) if widget is not None else None
        self._show_rules(widget, unit if isinstance(unit, dict) else None)
        if widget is None or self._planning is not None or not isinstance(unit, dict):
            self.split.setEnabled(False)
            self.join.setEnabled(False)
            self.fix.setEnabled(False)
            self.ignore.setEnabled(False)
            return
        self.fix.setEnabled(bool(unit["flagged"]))
        self.ignore.setText("Stop ignoring" if unit.get("ignored") else "Ignore...")
        self.ignore.setEnabled(bool(unit.get("ignored") or unit.get("broken")))
        self.split.setEnabled(len(unit["components"]) > 1)
        self.join.setEnabled(bool(unit.get("split"))
                             and len(self._parts(widget, unit["key"])) > 1)

    @staticmethod
    def _parts(widget: QListWidget, key: str) -> list[int]:
        """The rows of `widget` that are split parts of the mod `key`."""
        return [row for row in range(widget.count())
                if widget.item(row).data(ROLE)["key"] == key
                and widget.item(row).data(ROLE).get("split")]

    def _split(self) -> None:
        """The selected mod as one row per component, in its order - put in
        the list first and saved from it, as a drag is, so a drag or another
        split before the plan comes back keeps it (review of #74)."""
        widget, row = self._selected()
        if widget is None:
            return
        unit = widget.item(row).data(ROLE)
        if len(unit["components"]) < 2:
            return
        widget.takeItem(row)
        for offset, component in enumerate(unit["components"]):
            widget.insertItem(row + offset,
                              self._item(dict(unit, components=[component], split=True)))
        self._reordered()

    def _join(self) -> None:
        """The selected mod's parts in this tab as one row again, where its
        first part is, components in the order shown; the other mods stay."""
        widget, row = self._selected()
        if widget is None:
            return
        unit = widget.item(row).data(ROLE)
        rows = self._parts(widget, unit["key"])
        if len(rows) < 2:
            return
        parts = [widget.item(r).data(ROLE) for r in rows]
        for r in reversed(rows):
            widget.takeItem(r)
        whole = dict(parts[0], split=False,
                     components=[c for part in parts for c in part["components"]])
        widget.insertItem(rows[0], self._item(whole))
        self._reordered()

    # ---------------------------------------------------------------- fixes
    def _fix(self) -> None:
        """The fixes of the selected red row, in a dialog, each previewed."""
        widget, row = self._selected()
        if widget is None or self.wanted is None:
            return
        units = [widget.item(r).data(ROLE) for r in range(widget.count())]
        unit = units[row]
        names = {u["node"]: u["name"] for u in units}
        before = {u["node"]: list(u.get("after") or ()) for u in units}
        fixes = []
        for fix in api.order_fixes([u["node"] for u in units], before, unit["node"]):
            where = "after" if fix["kind"] == "after" else "before"
            still = (f" {len(fix['left'])} other rule(s) on it stay broken."
                     if fix["left"] else "")
            fixes.append(dict(fix, label=f"Move it just {where} {names[fix['anchor']]}",
                              ok=True, preview=(
                                  f"{unit['name']} goes just {where} "
                                  f"{names[fix['anchor']]}: {len(fix['fixed'])} rule(s) "
                                  f"mended, none broken.{still}")))
        game, chosen, labels = self.wanted
        index = self.tabs.indexOf(widget)
        phases = self.phases()
        without = [tab if n != index else tab[:row] + tab[row + 1:]
                   for n, tab in enumerate(phases)]
        mine = _same_component(unit)
        keys = [key for key in chosen if mine(key)]
        custom = bool(self.result.get("custom"))
        waiting = "Previewing with the planner..."
        if custom:
            fixes.append({"kind": "replan", "ok": False, "preview": waiting,
                          "label": "Plan it again by the rules, keeping your other moves",
                          "phases": without})
        if keys:
            fixes.append({"kind": "off", "ok": False, "preview": waiting, "keys": keys,
                          "label": f"Turn it off ({len(keys)} component(s))",
                          "phases": without if custom else None})
        dialog = FixDialog(self, unit, fixes)
        self.fixing = dialog
        dialog.accepted.connect(lambda: self._apply_fix(widget, dialog.chosen()))
        preview, folder = self.preview, self.project_dir
        now = phases if custom else None
        left = [key for key in chosen if not mine(key)]

        def run():
            out = {"base": preview(game, chosen, labels, folder, now)}
            if custom:
                out["replan"] = preview(game, chosen, labels, folder, without)
            if keys:
                out["off"] = preview(game, left, labels, folder, without if custom else None)
            return out
        if custom or keys:
            _in_thread(run, dialog.planner_done, dialog.planner_failed,
                       dialog.planner_finished)
        dialog.open()

    def _apply_fix(self, widget: QListWidget, fix: dict | None) -> None:
        if fix is None or not fix["ok"]:
            return
        if fix["kind"] in ("after", "before"):
            items = {widget.item(r).data(NODE): widget.item(r) for r in range(widget.count())}
            while widget.count():
                widget.takeItem(0)
            for node in fix["order"]:
                widget.addItem(items[node])
            self._reordered()
            return
        if fix["phases"] is not None:
            try:
                api.save_install_order(self.project_dir, fix["phases"])
            except Exception as exc:
                qtext.critical(self, "Cannot save the install order", str(exc))
                return
        if fix["kind"] == "off":
            self.turn_off.emit(fix["keys"])         # the window unticks them and plans
            return
        self._generation += 1
        self._plan()

    # ------------------------------------------------- the row's panel
    def _show_rules(self, widget: QListWidget | None, unit: dict | None) -> None:
        """The order rules on the selected row (M5b item 33)."""
        if widget is None or unit is None:
            self.panel.setText("")
            return
        breaks = set(widget.property("breaks") or ())
        lines = [f"<b>{html.escape(unit['name'])}</b>"]
        for rule in unit.get("rules") or ():
            pair = ((unit["node"], rule["node"]) if rule["must"] == "after"
                    else (rule["node"], unit["node"]))
            text = (f"Must come {rule['must']} {html.escape(rule['name'])}: "
                    f"{html.escape(rule['rule'])} ({html.escape(rule['source'])}, "
                    f"{html.escape(rule['severity'])})")
            if pair in breaks:
                text = f'<span style="color: {RED.name()}">{text} - broken</span>'
            elif rule["whole"]:
                text = (f'<span style="color: {GREY.name()}">{text} - names the whole '
                        "mod</span>")
            lines.append(text)
        if not unit.get("rules"):
            lines.append("No order rule names it.")
        for broken in unit.get("broken") or ():
            lines.append(f'<span style="color: {RED.name()}">Broken: '
                         f"{html.escape(broken)}</span>")
        if unit.get("ignored"):
            lines.append(f"Ignored, while it stays where it is: "
                         f"{html.escape(unit['ignored']['why'])}")
        self.panel.setText("<br>".join(lines))

    def _ignore(self) -> None:
        """Ignore the selected row's broken rules, with why - or stop."""
        widget, row = self._selected()
        if widget is None:
            return
        unit = widget.item(row).data(ROLE)
        if unit.get("ignored"):
            self._unignore(unit["node"])
        else:
            why, ok = QInputDialog.getText(
                self, f"Ignore {unit['name']}",
                "Why it stays here although a rule says otherwise "
                "(kept in decisions.json):")
            if not ok or not why.strip():
                return
            above = widget.item(row - 1).data(NODE) if row else ""
            try:
                api.ignore_order(self.project_dir, unit["node"], above,
                                 unit["broken"], why.strip())
            except Exception as exc:
                qtext.critical(self, "Cannot save the decision", str(exc))
                return
        self._generation += 1
        self._plan()

    def _unignore(self, node: str) -> None:
        try:
            api.unignore_order(self.project_dir, node)
        except Exception as exc:
            qtext.critical(self, "Cannot save the decision", str(exc))

    # ---------------------------------------- moving and finding (item 35)
    def _rows(self, widget: QListWidget) -> list[int]:
        rows = sorted({index.row() for index in widget.selectedIndexes()})
        return rows or ([widget.currentRow()] if widget.currentRow() >= 0 else [])

    def nudge(self, step: int) -> None:
        """Move the selected rows of the tab shown one place up (-1) or down
        (1), as one move: checked at once, saved once, planned once."""
        widget = self.tabs.currentWidget()
        if not isinstance(widget, QListWidget):
            return
        rows = self._rows(widget)
        if not rows or (step < 0 and rows[0] == 0) or (
                step > 0 and rows[-1] == widget.count() - 1):
            return
        model = widget.model()
        self._batch = True
        try:
            for row in (rows if step < 0 else reversed(rows)):
                model.moveRow(QModelIndex(), row, QModelIndex(),
                              row - 1 if step < 0 else row + 2)
        finally:
            self._batch = False
        self._reordered()

    def _find(self) -> None:
        """Select the rows of the tab shown whose text has every word typed."""
        widget = self.tabs.currentWidget()
        if not isinstance(widget, QListWidget):
            return
        words = self.find.text().lower().split()
        widget.clearSelection()
        if not words:
            return
        found = [widget.item(r) for r in range(widget.count())
                 if all(word in widget.item(r).text().lower() for word in words)]
        for item in found:
            item.setSelected(True)
        if found:
            widget.setCurrentItem(found[0], QItemSelectionModel.SelectionFlag.NoUpdate)
            widget.scrollToItem(found[0])

    def _reset(self) -> None:
        try:
            api.reset_install_order(self.project_dir)
        except Exception as exc:
            qtext.critical(self, "Cannot reset the install order", str(exc))
        self._generation += 1
        self._plan()

    def is_complete(self) -> bool:
        return bool(self.result) and self._planning is None

    def order_file(self) -> str | None:
        path = os.path.join(self.project_dir, api.INSTALL_ORDER_FILE)
        return path if os.path.isfile(path) else None
