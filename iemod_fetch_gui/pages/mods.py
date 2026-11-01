"""
Phase 2 - mod selection (GUI-AUDIT item 16, ADR-0031/0035).

BWS-NG's screen as an idea: kinds down the left, a search box and a
filter above a mod -> component tree, details on the right. A mod's kind is
what lcc-docs and BWS-NG say, mapped onto one vocabulary (iemod_fetch/kinds.py,
item 26): the details say which source says what, and where two disagree the
row is marked and "Kinds disagree" lists it - never settled for the player.
A mod's box is tri-state; components that share a SUBCOMPONENT exclude each other (choosing
one clears the others), and choosing a component also chooses the same-mod
components it needs. The catalogue loads in a worker thread, so the window
never waits on the network or the disk. Leaving the phase writes the
project's selection.json, which the CLI reads with --selection.

A mod whose components are not known yet - not staged, and krion64 has no
record of it - cannot be chosen here: a selection names components, and
guessing them is what this tool does not do. It says so in its row.

The conflicts tab checks the selection against the rules a run uses, shortly
after each change and in a worker thread too (api.selection_conflicts, ADR-0033);
its buttons change the tree or write decisions.json. "Conflicts only" shows the
mods in a conflict still to decide.

Unticking a component that chosen ones need - its own mod's components that
require it, and the dependency rules the last check found satisfied - asks
first (GUI-AUDIT M5b item 34): untick those too (and what needs them), keep
it, or untick it alone. A mod unticked whole asks once for all its
components. "Resolve for this component" does what BWS-NG's auto-resolve
does, narrower: it chooses the selected component's missing prerequisites -
one alternative of an "any one of", never every one - then keeps it against
the error incompatibilities that name it, deselecting their other side; a
warning stays the player's. What it would do is shown first.

A mod ticked whole takes one option of each SUBCOMPONENT group - the one
already chosen, else the group's first - rather than Qt's last (M5b item 35);
unticking the only option of a FORCED_SUBCOMPONENT group while the mod keeps
other components puts it back, as WeiDU would ask for one. A check is not run
again when nothing it reads has changed (api.selection_digest).
"""
import html
import os
from typing import Any
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QSplitter, QTabWidget, QTextBrowser, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from iemod_fetch import api

from iemod_fetch_gui import text as qtext

from .conflicts import ConflictsPanel, open_findings

Loader = Callable[[str, dict], list[dict]]
Key = tuple[str, int]                     # (tp2, component number)
Checker = Callable[[str, list[Key], dict, str], dict]
ROLE = Qt.ItemDataRole.UserRole
ALL = "All kinds"
FILTERS = ["All mods", "Chosen only", "Conflicts only", "Updates available",
           "Maybe updated", "Kinds disagree"]
# A date is not a version (ADR-0044): never "update available" from lcc-docs
MAYBE = "maybe updated"
KIND_COLUMN = 3
DISAGREE = "\u26a0 "        # the mark on a row whose sources disagree on its kind
CHECK_DELAY_MS = 700      # a burst of clicks is checked once, after it ends
KRION_NOTE = ("Components from krion64's records: the mod is not downloaded yet. "
              "Its own tp2 decides once it is, and the choice is checked again then.")


def _text(value) -> str:
    """A third party's text (release notes, krion64's notes) for the details:
    escaped whole, newlines kept, never a link or markup (item 51)."""
    return html.escape(str(value)).replace("\n", "<br>")


def _krion_lines(mod: dict) -> list[str]:
    """What krion64 says of the mod and its repository, with the source and
    the day of its data: what it saw then, not a fact now (item 51)."""
    when = mod.get("krion_date")
    said = f"krion64, data of {when}" if when else "krion64, date of its data not known"
    lines = [f"<b>{_text(label)} ({_text(said)}):</b> {_text(text)}"
             for label, text in mod.get("krion_notes") or []]
    release = mod.get("release") or {}
    if release:
        # what the scan saw is as old as its look at that repository, which
        # can be months before the data's day (review of #123)
        if release.get("checked"):
            said = f"krion64's scan of {release['checked']}"
        elif when:
            said = f"krion64, data of {when}, day of its scan not known"
        repo = _text(release.get("repo", ""))
        if release.get("archived"):
            lines.append(f"<b>Archived</b> on GitHub, according to {_text(said)} ({repo})")
        if release.get("pushed"):
            lines.append(f"<b>Last push to {repo}</b> ({_text(said)}): "
                         f"{_text(release['pushed'])}")
        if release.get("notes"):
            title = release.get("name") or release.get("tag") or ""
            lines.append(f"<b>Release notes of {_text(title)}</b> "
                         f"({_text(release.get('date') or 'no date')}, from GitHub through "
                         f"{_text(said)}):<br>{_text(release['notes'])}")
    return lines


def _target(project: dict) -> str:
    """The CLI's --target, resolved as the CLI resolves it when run in the project."""
    folder = os.path.dirname(project["path"])
    return os.path.join(folder, project.get("target") or "Mods")


def _stale(item: QTreeWidgetItem) -> bool:
    """
    Whether `item`'s row still shows its state from before this change: Qt
    ticks a row's components before it changes the row itself, while a
    component ticked alone has its row brought up to date first (measured on
    Qt 6; item 35). A Python subclass of the row caught this before; it gave
    the collector a cycle to walk from worker threads (review of #82).
    """
    row = item.parent()
    if row is None or row.childCount() == 0:
        return False
    states = {row.child(n).checkState(0) for n in range(row.childCount())}
    shown = (Qt.CheckState.Checked if states == {Qt.CheckState.Checked}
             else Qt.CheckState.Unchecked if states == {Qt.CheckState.Unchecked}
             else Qt.CheckState.PartiallyChecked)
    return bool(row.checkState(0) != shown)


def _under(item: QTreeWidgetItem, row: QTreeWidgetItem) -> bool:
    """Whether `item` is `row` or below it."""
    current: QTreeWidgetItem | None = item
    while current is not None:
        if current is row:
            return True
        current = current.parent()
    return False


def selection_digest(game: str, chosen: list[Key], labels: dict, project_dir: str) -> str:
    """What a check or a plan of the project's selection reads (item 35),
    with the mods staged in its target folder."""
    return api.selection_digest(game, chosen, labels, project_dir,
                                target=_target(api.load_project(project_dir)))


def kinds_of(mod: dict) -> list[str]:
    """A mod's kinds; a list from before item 26 has only its catalogue categories."""
    return mod.get("kinds") or mod.get("categories") or ["(none)"]


def _said(mod: dict) -> str:
    """Which source says what: "lcc-docs: quest; BWS-NG: gameplay"."""
    return "; ".join(f"{origin}: {', '.join(found)}"
                     for origin, found in (mod.get("kinds_by_source") or {}).items())


def preset_size(preset: dict) -> int:
    """The components a preset names, each once: a log or an EET code may repeat one."""
    return (len({(tp2.lower(), number) for tp2, number in preset["chosen"]})
            + len({name.lower() for name in preset["unmatched"]}))


def same_folder(a: str, b: str) -> bool:
    """Whether two paths are one folder: on Windows case differs, and links lead there too."""
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def find_conflicts(game: str, chosen: list[Key], labels: dict, project_dir: str) -> dict:
    """The real checker: the selection's conflicts and the project's decisions."""
    project = api.load_project(project_dir)
    # The authors' own install order is fetched for what is chosen (ADR-0037):
    # one small file per mod, once a week at most, kept in the data cache.
    # The order set by hand in phase 3 is part of what the run judges too.
    order = os.path.join(project_dir, api.INSTALL_ORDER_FILE)
    return api.selection_conflicts(game, chosen, labels, folder=project_dir,
                                   target=_target(project), fetch_metadata=True,
                                   sorting_order=order if os.path.isfile(order) else None)


def load_choices(game: str, project: dict) -> list[dict]:
    """The real loader: refresh the community data (offline keeps the last good
    copy), then every mod for `game` with its components."""
    api.update_data(api.Settings(quiet=True))
    return api.mod_choices(game, target=_target(project),
                           preferences=project.get("language_preference") or ())


# Threads outlive the page that started them: closing the window while the
# catalogue loads must not destroy a running QThread (Qt aborts). Each is kept
# here until it has finished; the application waits for them on quit.
_RUNNING: set[QThread] = set()


def wait_for_loaders(timeout_ms: int = 60000) -> None:
    """Let every catalogue load still running end (QApplication.aboutToQuit)."""
    for thread in list(_RUNNING):
        thread.wait(timeout_ms)


class _Worker(QObject):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, call: Callable[[], Any]) -> None:
        super().__init__()
        self.call = call

    def run(self) -> None:
        try:
            self.done.emit(self.call())
        except Exception as exc:          # shown on the page, never a crash
            self.failed.emit(str(exc))


class _Relay(QObject):
    """
    Hands the worker's result and end to `done`/`failed`/`finished` in the
    thread that started it. A signal connected to a plain function runs it in
    the emitting thread (measured with PySide6: the worker's), so a page's widgets would
    be changed from the worker; a QObject's slot living here is queued, and
    its result arrives before the thread's finished signal. A child of the
    page whose callbacks these are: a page closed meanwhile takes its relay
    along, and Qt drops the result instead of handing it to deleted widgets.
    """

    def __init__(self, done: Callable, failed: Callable, finished: Callable,
                 owner: QObject | None) -> None:
        super().__init__(owner)
        self._done, self._failed, self._finished = done, failed, finished

    @Slot(object)
    def on_done(self, result: Any) -> None:
        self._done(result)

    @Slot(str)
    def on_failed(self, message: str) -> None:
        self._failed(message)

    @Slot()
    def on_finished(self) -> None:
        self._finished()


def _in_thread(call: Callable[[], Any], done: Callable, failed: Callable,
               finished: Callable, owner: QObject | None = None) -> QThread:
    """Run `call` in a worker thread kept in _RUNNING until it ends; `done`,
    `failed` and `finished` are called in the thread that called this, while
    `owner` (by default the object `done` is a method of) is alive."""
    thread = QThread()                          # no parent: see _RUNNING
    worker = _Worker(call)
    bound = getattr(done, "__self__", None)
    if owner is None and isinstance(bound, QObject):
        owner = bound
    relay = _Relay(done, failed, finished, owner)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.done.connect(relay.on_done)
    worker.failed.connect(relay.on_failed)
    for signal in (worker.done, worker.failed):
        signal.connect(thread.quit)
    thread.finished.connect(relay.on_finished)
    def ended(held: _Worker = worker, kept: _Relay | None = None if owner else relay) -> None:
        _RUNNING.discard(thread)                   # held to the end; an owned
        held.deleteLater()                         # relay goes with its owner
        if kept is not None:
            kept.deleteLater()

    thread.finished.connect(ended)
    _RUNNING.add(thread)
    thread.start()
    return thread


# The project's own files: a preset saved under one of these names would
# replace it (decisions.json holds the player's answers).
PROJECT_FILES = {name.lower() for name in (api.SELECTION_FILE, api.DECISIONS_FILE,
                                           api.INSTALL_ORDER_FILE, api.PROJECT_FILE)}


class ModsPage(QWidget):
    completeChanged = Signal(bool)
    loaded = Signal()
    checked = Signal()

    def __init__(self, project_dir: str, load: Loader = load_choices,
                 check: Checker = find_conflicts) -> None:
        super().__init__()
        self.project_dir = project_dir
        self.load = load
        self.check = check
        self.conflicts: dict = {}
        self._checking: QThread | None = None
        self._recheck = False
        self._generation = 0      # a check's result is shown only for the list it checked
        self._loading = False     # a list is on its way: the one shown is not checked
        self.game = ""              # the game the shown list is for
        self.wanted = ""            # the game asked for last
        self.mods: list[dict] = []
        self.items: dict[Key, QTreeWidgetItem] = {}
        self.exclusive: dict[tuple[str, str], list[QTreeWidgetItem]] = {}
        self._thread: QThread | None = None
        self._updating = False

        self.categories = QListWidget()
        self.categories.currentTextChanged.connect(lambda _text: self.apply_filter())
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search mods and components")
        self.search.textChanged.connect(lambda _text: self.apply_filter())
        self.filter = QComboBox()
        self.filter.addItems(FILTERS)
        self.filter.currentIndexChanged.connect(lambda _index: self.apply_filter())

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Mod / component", "Version", "Components from", "Kind"])
        self.tree.setColumnWidth(0, 420)
        self.tree.itemChanged.connect(self._changed)
        self.tree.currentItemChanged.connect(lambda item, _old: self._show(item))
        self.tree.currentItemChanged.connect(lambda _item, _old: self._can_resolve())
        self.details = QTextBrowser()
        self.details.setOpenLinks(False)          # catalogue text is third-party
        self.panel = ConflictsPanel()
        self.panel.can_choose = self._can_choose
        self.panel.deselect.connect(self.deselect)
        self.panel.choose.connect(self._choose_in)
        self.panel.decide.connect(self._decide)
        self.panel.undo.connect(self._undo)
        self.panel.forget.connect(self._forget)
        self.panel.check.connect(self.check_conflicts)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.details, "Details")
        self.tabs.addTab(self.panel, "Conflicts")
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(CHECK_DELAY_MS)
        self.timer.timeout.connect(self.check_conflicts)
        self.status = QLabel("Loading the mod list...")
        self.status.setTextFormat(Qt.TextFormat.PlainText)

        self.load_preset = QPushButton("Load preset...")
        self.load_preset.setToolTip("Choose what a saved selection, a WeiDU.log, a BIO "
                                    "share code or a Project Infinity list chooses")
        self.load_preset.clicked.connect(self._load_preset)
        self.save_preset = QPushButton("Save preset...")
        self.save_preset.setToolTip("Save this choice as a selection.json, to load "
                                    "again or give to the command line (--selection)")
        self.save_preset.clicked.connect(self._save_preset)
        self._presets(False)                # until a list is shown
        self.resolve = QPushButton("Resolve for this component")
        self.resolve.setToolTip("Choose what the selected component needs, then keep it "
                                "against the errors that name it - shown before it is done")
        self.resolve.setEnabled(False)
        self.resolve.clicked.connect(self._resolve)
        self._unticked: set[Key] = set()    # unticked by the player, not yet asked about
        self._answered = ""                 # the digest the conflicts shown answer
        # components ticked since the event loop last ran, and what was chosen
        # before them: a mod's row ticking its components (item 35)
        self._burst: list[Key] = []
        self._burst_before: set[Key] = set()
        self.checks = 0                     # checks run, not skipped (item 35)
        bar = QHBoxLayout()
        bar.addWidget(self.search, 1)
        bar.addWidget(self.filter)
        bar.addWidget(self.load_preset)
        bar.addWidget(self.save_preset)
        bar.addWidget(self.resolve)
        middle = QWidget()
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.addLayout(bar)
        middle_layout.addWidget(self.tree, 1)
        split = QSplitter()
        split.addWidget(self.categories)
        split.addWidget(middle)
        split.addWidget(self.tabs)
        split.setSizes([160, 520, 320])
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>2. Mod selection</h2>"))
        layout.addWidget(split, 1)
        layout.addWidget(self.status)

    # ------------------------------------------------------------ loading
    def start(self, game: str) -> None:
        """Load the catalogue for `game` in a worker thread."""
        self.wanted = game
        if self._thread is not None:          # loading: _finished loads again if needed
            return
        if game == self.game and self.mods:
            return
        # What was checked was the old list: no result for it may land on the new one.
        self.timer.stop()
        self._generation += 1
        self._loading = True
        self._presets(False)            # the tree shown is not the new game's yet
        self._set_conflicts({})
        self.game = game
        self.status.setText(f"Loading the mods for {game}...")
        project = api.load_project(self.project_dir)
        load = self.load
        self._thread = _in_thread(lambda: load(game, project), self._fill, self._failed,
                                  self._finished)

    def _finished(self) -> None:
        self._thread = None
        if self.wanted and self.wanted != self.game:
            self.start(self.wanted)     # the game changed while this list loaded
            return
        self.loaded.emit()              # the thread has ended: safe to close the page

    def _failed(self, message: str) -> None:
        self._loading = False
        # The tree shown is the old game's: drop it, so choosing this game again
        # loads its list instead of finding one already there (review of #41).
        self.mods = []
        self.tree.clear()
        self.status.setText(f"The mod list could not be loaded: {message}")

    def _fill(self, mods: list) -> None:
        self._loading = False
        self._presets(True)
        self._generation += 1           # nothing checked before this list applies to it
        self._updating = True
        self.mods = mods
        self.tree.clear()
        self.items.clear()
        self.exclusive.clear()
        saved = self._saved_selection()
        counts: dict[str, int] = {}
        for mod in mods:
            for kind in kinds_of(mod):
                counts[kind] = counts.get(kind, 0) + 1
            self.tree.addTopLevelItem(self._mod_item(mod, saved))
        self.categories.clear()
        self.categories.addItem(QListWidgetItem(f"{ALL} ({len(mods)})"))
        for category in sorted(counts):
            item = QListWidgetItem(f"{category} ({counts[category]})")
            item.setData(ROLE, category)
            self.categories.addItem(item)
        self.categories.setCurrentRow(0)
        self._updating = False
        self.apply_filter()
        self._count()
        self.check_conflicts()

    def _mod_item(self, mod: dict, saved: set[Key]) -> QTreeWidgetItem:
        latest = mod.get("latest") or {}
        version = mod.get("version") or ""
        if mod.get("update_available"):
            version = f"{mod.get('installed') or version} -> {latest.get('version', '?')}"
        if mod.get("maybe_updated"):              # both, as the filters list it
            version = f"{version} ({MAYBE})" if version else MAYBE
        tp2s = mod.get("tp2s") or []
        origin = ", ".join(sorted({t["origin"] for t in tp2s})) or "not known yet"
        kind = ", ".join(kinds_of(mod))
        if mod.get("kind_disagreement"):
            kind = DISAGREE + kind
        item = QTreeWidgetItem([mod.get("name") or mod["key"], version, origin, kind])
        item.setData(0, ROLE, ("mod", mod["key"]))
        item.setToolTip(KIND_COLUMN, qtext.plain_tip(_said(mod) or kind))
        if not any(t["components"] and not t.get("refused") for t in tp2s):
            item.setDisabled(True)
            item.setToolTip(0, "Its components are not known until it is downloaded: "
                               "nothing to choose yet.")
            return item
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                      | Qt.ItemFlag.ItemIsAutoTristate)
        for tp2 in tp2s:
            parent = item
            if len(tp2s) > 1:                       # EET: EET.tp2 and EET_end.tp2
                parent = QTreeWidgetItem([tp2["tp2"].rsplit("/", 1)[-1], "", tp2["origin"]])
                parent.setFlags(parent.flags() | Qt.ItemFlag.ItemIsUserCheckable
                                | Qt.ItemFlag.ItemIsAutoTristate)
                item.addChild(parent)
            for component in tp2["components"]:
                key = (tp2["tp2"], component["number"])
                if key in self.items:               # listed twice: one box, not two
                    continue
                name = component["name"]
                if component["subgroup"]:
                    name = f"{component['subgroup']} -> {name}"
                child = QTreeWidgetItem([f"#{component['number']}  {name}", "", ""])
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setData(0, ROLE, ("component", key, component))
                if tp2.get("refused"):
                    child.setDisabled(True)
                    child.setToolTip(0, qtext.plain_tip(tp2["refused"]))
                    parent.addChild(child)
                    continue
                child.setCheckState(0, Qt.CheckState.Checked if key in saved
                                    else Qt.CheckState.Unchecked)
                parent.addChild(child)
                self.items[key] = child
                if component["exclusive"]:
                    self.exclusive.setdefault((tp2["tp2"], component["exclusive"]),
                                              []).append(child)
        return item

    def _saved_selection(self) -> set[Key]:
        path = os.path.join(self.project_dir, api.SELECTION_FILE)
        if not os.path.isfile(path):
            return set()
        try:
            selection = api.load_selection(path)
        except Exception:        # a hand-edited file the CLI would refuse: start empty
            return set()
        # An EET build is saved as two installs, the BG:EE phase and EET; a
        # BG:EE install alone is a BG:EE build, not EET's first phase.
        saved = {install.game.upper() for install in selection.installs}
        games = ({"EET", "BGEE"} if self.game.upper() == "EET" and "EET" in saved
                 else {self.game.upper()})
        return {(c.tp2, c.component) for install in selection.installs
                if install.game.upper() in games for c in install.components}

    # ---------------------------------------------------------- choosing
    def _changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating or column != 0:
            return
        data = item.data(0, ROLE)
        if not data or data[0] != "component":
            # A mod's (or an EET tp2's) row: Qt ticks its components first and
            # changes the row last. More than one ticked meanwhile is the row
            # ticking them all: one option per SUBCOMPONENT group (item 35).
            if len(self._burst) > 1 and item.checkState(0) != Qt.CheckState.Unchecked:
                self._settle(item, self._burst_before)
            self._count()
            return
        if item.checkState(0) == Qt.CheckState.Checked:
            if not self._burst:
                self._burst_before = self._checked() - {data[1]}
                QTimer.singleShot(0, self._burst.clear)
            self._burst.append(data[1])
            if _stale(item):
                return                  # its row is ticking it: settled by the row
            self._updating = True
            try:
                self._choose(item, set())
            finally:
                self._updating = False
        else:
            # a whole mod unticks its components one by one: asked once, after
            if not self._unticked:
                QTimer.singleShot(0, self._guard_untick)
            self._unticked.add(data[1])
        self._count()

    def _choose(self, item: QTreeWidgetItem, seen: set[Key]) -> None:
        """Choose `item`: clear the rest of its SUBCOMPONENT, then choose - the
        same way - every component it needs."""
        _kind, (tp2, number), component = item.data(0, ROLE)
        if (tp2, number) in seen:
            return
        seen.add((tp2, number))
        item.setCheckState(0, Qt.CheckState.Checked)
        for other in self.exclusive.get((tp2, component["exclusive"]), []):
            if other is not item:
                other.setCheckState(0, Qt.CheckState.Unchecked)
        for needed in component["requires"]:
            needed_item = self.items.get((tp2, needed))
            if needed_item is not None and not needed_item.isDisabled():
                self._choose(needed_item, seen)

    def _settle(self, row: QTreeWidgetItem, before: set[Key]) -> None:
        """
        After a mod's row ticked its components: one option per SUBCOMPONENT
        group - the one chosen before, else the group's first, or the one left
        when only one is - and what each chosen component needs (item 35).
        """
        mine = [item for key, item in self.items.items() if _under(item, row)]
        self._updating = True
        try:
            groups: dict[tuple, list[QTreeWidgetItem]] = {}
            for item in mine:
                _kind, (tp2, _number), component = item.data(0, ROLE)
                if component["exclusive"]:
                    groups.setdefault((tp2, component["exclusive"]), []).append(item)
            for options in groups.values():
                ticked = [o for o in options if o.checkState(0) == Qt.CheckState.Checked]
                if not ticked:
                    continue
                kept = next((o for o in options if o.data(0, ROLE)[1] in before),
                            ticked[0] if len(ticked) == 1 else options[0])
                for option in options:
                    option.setCheckState(0, Qt.CheckState.Checked if option is kept
                                         else Qt.CheckState.Unchecked)
            seen: set[Key] = set()
            for item in mine:
                if item.checkState(0) == Qt.CheckState.Checked:
                    self._choose(item, seen)
        finally:
            self._updating = False
        self._count()

    def _forced_back(self, removed: set[Key]) -> list[Key]:
        """
        The options of a FORCED_SUBCOMPONENT group unticked when no other of
        the group stays and the tp2 keeps other components: WeiDU asks for
        one of them, so they go back (M5b item 35).
        """
        chosen = self._checked()
        back: list[Key] = []
        for key in sorted(removed):
            _kind, (tp2, _number), component = self.items[key].data(0, ROLE)
            if not component["forced"] or not component["exclusive"]:
                continue
            group = [other for other in self.items.values()
                     if other.data(0, ROLE)[1][0] == tp2
                     and other.data(0, ROLE)[2]["exclusive"] == component["exclusive"]]
            if any(o.data(0, ROLE)[1] in chosen for o in group):
                continue
            if any(other[0] == tp2 for other in chosen) and not any(
                    b[0] == tp2 and self.items[b].data(0, ROLE)[2]["exclusive"]
                    == component["exclusive"] for b in back):
                back.append(key)
        return back

    # ------------------------------------- who needs it (M5b item 34)
    def _checked(self) -> set[Key]:
        return {key for key, item in self.items.items()
                if item.checkState(0) == Qt.CheckState.Checked}

    def dependents(self, removed: set[Key]) -> list[Key]:
        """
        The chosen components left without what they need once `removed` are
        unticked, and what needs those in turn: the same mod's components that
        require one, and the dependency rules the last check found satisfied
        whose every alternative goes.
        """
        chosen = self._checked() - removed
        gone, found = set(removed), []
        changed = True
        while changed:
            changed = False
            for key in sorted(chosen - gone):
                item = self.items[key]
                _kind, (tp2, _number), component = item.data(0, ROLE)
                lost = any((tp2, needed) in gone for needed in component["requires"])
                for need in (self.conflicts or {}).get("needs") or ():
                    if key not in {tuple(pair) for pair in need["chosen"]}:
                        continue
                    if not any(tuple(pair) not in gone and tuple(pair) in chosen
                               for alternative in need["on"] for pair in alternative):
                        lost = True
                if lost:
                    gone.add(key)
                    found.append(key)
                    changed = True
        return found

    def _guard_untick(self) -> None:
        removed = {key for key in self._unticked
                   if key in self.items
                   and self.items[key].checkState(0) == Qt.CheckState.Unchecked}
        self._unticked.clear()
        if not removed:
            return
        back = self._forced_back(removed)
        if back:
            self._updating = True
            try:
                for key in back:
                    self.items[key].setCheckState(0, Qt.CheckState.Checked)
            finally:
                self._updating = False
            removed -= set(back)
            self._count()
            self.status.setText(f"{self._name(back[0])}: its mod needs one option of "
                                "this group; choose another instead of none.")
            if not removed:
                return
        needing = self.dependents(removed)
        if not needing:
            return
        answer = self.ask_dependents([self._name(k) for k in sorted(removed)],
                                     [self._name(k) for k in needing])
        self._updating = True
        try:
            if answer == "all":
                for key in needing:
                    self.items[key].setCheckState(0, Qt.CheckState.Unchecked)
            elif answer == "keep":
                for key in removed:
                    self.items[key].setCheckState(0, Qt.CheckState.Checked)
        finally:
            self._updating = False
        self._count()

    def ask_dependents(self, removed: list[str], needing: list[str]) -> str:
        """"all" (untick those too), "keep" (tick it again) or "only"."""
        box = QMessageBox(self)
        box.setWindowTitle("Others need it")
        box.setIcon(QMessageBox.Icon.Question)
        box.setTextFormat(Qt.TextFormat.PlainText)                # components' names
        box.setText(f"{', '.join(removed)}: needed by {len(needing)} chosen "
                    f"component(s):\n\n" + "\n".join(needing[:20])
                    + ("\n..." if len(needing) > 20 else ""))
        everything = box.addButton("Untick those too", QMessageBox.ButtonRole.AcceptRole)
        keep = box.addButton("Keep it", QMessageBox.ButtonRole.RejectRole)
        box.addButton("Untick it alone", QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        clicked = box.clickedButton()
        return "all" if clicked is everything else "keep" if clicked is keep else "only"

    def _name(self, key: Key) -> str:
        item = self.items.get(key)
        mod = item.parent() if item is not None else None
        while mod is not None and mod.parent() is not None:
            mod = mod.parent()
        prefix = mod.text(0) if mod is not None else key[0]
        return f"{prefix} {item.text(0) if item is not None else f'#{key[1]}'}"

    def resolution(self, key: Key) -> tuple[list[tuple[str, list]], list[list], list[str]]:
        """
        What "Resolve for this component" would do for `key`: the prerequisites
        to choose (mod key, numbers), the pairs to deselect, and what it leaves
        to the player, with why.
        """
        add: list[tuple[str, list]] = []
        remove: list[list] = []
        left: list[str] = []
        for finding in open_findings(self.conflicts or {}):
            sides = [finding["left"], finding.get("right")]
            mine = [side for side in sides if side
                    and [key[0], key[1]] in [list(p) for p in side.get("chosen") or ()]]
            if not mine:
                continue
            if finding["kind"] == "depends" and mine[0] is finding["left"]:
                install = next((o for o in finding["options"] if o["action"] == "install"),
                               None)
                if install and self._can_choose(install["key"], install["components"]):
                    add.append((install["key"], install["components"]))
                else:
                    left.append(f"{finding['left']['mod']} needs "
                                f"{(finding.get('right') or {}).get('mod', '?')}: "
                                "not in the list to choose")
            elif finding["kind"] == "incompatible" and finding.get("right"):
                other = sides[1] if mine[0] is sides[0] else sides[0]
                if finding["severity"] == "error":
                    remove += [list(p) for p in other.get("chosen") or ()
                               if list(p) not in remove]
                else:
                    left.append(f"{finding['severity']}: {other['mod']} - a warning "
                                "is yours to decide")
        return add, remove, left

    def _can_resolve(self) -> None:
        item = self.tree.currentItem()
        data = item.data(0, ROLE) if item is not None else None
        self.resolve.setEnabled(bool(
            data and data[0] == "component" and item.checkState(0) == Qt.CheckState.Checked
            and any(self.resolution(data[1]))))

    def _resolve(self) -> None:
        item = self.tree.currentItem()
        data = item.data(0, ROLE) if item is not None else None
        if not data or data[0] != "component":
            return
        add, remove, left = self.resolution(data[1])
        lines = [f"Choose {key} #{', #'.join(map(str, numbers))}" for key, numbers in add]
        lines += [f"Deselect {self._name((tp2, number))}" for tp2, number in remove]
        lines += [f"Left to you: {text}" for text in left]
        if not (add or remove) or not self.confirm_resolve("\n".join(lines)):
            return
        for key, numbers in add:
            self._choose_in(key, numbers)
        self._updating = True                 # the player asked for exactly this
        try:
            for tp2, number in remove:
                target = self.items.get((tp2, number))
                if target is not None:
                    target.setCheckState(0, Qt.CheckState.Unchecked)
        finally:
            self._updating = False
        self._count()

    def confirm_resolve(self, text: str) -> bool:
        answer = qtext.question(self, "Resolve for this component", text)
        return bool(answer == QMessageBox.StandardButton.Yes)

    # ------------------------------------------------------------ presets
    def _presets(self, enabled: bool) -> None:
        self.load_preset.setEnabled(enabled)
        self.save_preset.setEnabled(enabled)

    def _load_preset(self) -> None:
        path, _kind = QFileDialog.getOpenFileName(
            self, "Load a preset", self.project_dir,
            "Presets (*.json *.log *.txt *.csv *.bio);;All files (*)")
        if not path:
            return
        try:
            project = api.load_project(self.project_dir)
            preset = api.import_selection(path, self.game, sorted({k[0] for k in self.items}),
                                          target=_target(project))
        except Exception as exc:        # not a preset, unreadable: say so, change nothing
            qtext.critical(self, "Cannot load the preset", str(exc))
            return
        if self.chosen() and qtext.question(
                self, "Load the preset",
                f"Replace the {len(self.chosen())} component(s) chosen now with the "
                f"preset's {preset_size(preset)}?") \
                != QMessageBox.StandardButton.Yes:
            return
        wanted = [tuple(pair) for pair in preset["chosen"]]
        skipped = self.apply_preset(wanted)
        lines = list(preset["notes"])
        missing = preset["unmatched"] + [f"{tp2} #{number}" for tp2, number in skipped]
        if missing:
            lines.append(f"{len(missing)} component(s) are not in the list for "
                         f"{self.game} and were left out: " + ", ".join(missing[:10])
                         + (", ..." if len(missing) > 10 else ""))
        chosen = set(self.chosen())
        lost = [f"{tp2} #{number}" for tp2, number in wanted
                if (tp2, number) not in chosen and (tp2, number) not in skipped]
        if lost:
            lines.append(f"{len(lost)} component(s) were replaced by another option of "
                         f"the same group, which the preset also chose: "
                         + ", ".join(lost[:10]) + (", ..." if len(lost) > 10 else ""))
        if lines:
            qtext.information(self, "Preset loaded", "\n\n".join(lines))

    def apply_preset(self, chosen: list[Key]) -> list[Key]:
        """Choose exactly `chosen` (each as a click would: its SUBCOMPONENT
        cleared, what it needs chosen too); returns what the list cannot."""
        skipped = []
        self._updating = True
        try:
            for item in self.items.values():
                item.setCheckState(0, Qt.CheckState.Unchecked)
            seen: set[Key] = set()
            for key in chosen:
                item = self.items.get(key)
                if item is None or item.isDisabled():
                    skipped.append(key)
                    continue
                self._choose(item, seen)
        finally:
            self._updating = False
        self._count()
        return skipped

    def _save_preset(self) -> None:
        path, _kind = QFileDialog.getSaveFileName(
            self, "Save the choice as a preset", self.project_dir, "Selection (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
            # the dialog asked about the name typed, not this one
            if os.path.exists(path) and qtext.question(
                    self, "Save the preset", f"{path} exists. Replace it?") \
                    != QMessageBox.StandardButton.Yes:
                return
        if same_folder(os.path.dirname(os.path.abspath(path)), self.project_dir) \
                and os.path.basename(path).lower() in PROJECT_FILES:
            qtext.critical(self, "Cannot save the preset",
                                 f"{os.path.basename(path)} is the project's own file; "
                                 f"give the preset another name.")
            return
        if not self.chosen():
            qtext.critical(self, "Cannot save the preset", "Nothing is chosen.")
            return
        try:
            saved = api.export_selection(path, self.game, self.chosen(), self.labels())
        except Exception as exc:
            qtext.critical(self, "Cannot save the preset", str(exc))
            return
        self.status.setText(f"Preset saved: {saved}")

    def chosen(self) -> list[Key]:
        """(tp2, number) of every chosen component, in catalogue order."""
        return [key for key, item in self.items.items()
                if item.checkState(0) == Qt.CheckState.Checked]

    def _count(self) -> None:
        chosen = self.chosen()
        mods = {tp2.split("/")[0].lower() for tp2, _number in chosen}
        self.status.setText(f"{len(chosen)} component(s) chosen in {len(mods)} mod(s), "
                            f"of {len(self.mods)} mods for {self.game}.")
        self.completeChanged.emit(self.is_complete())
        if self.mods:
            self.timer.start()                    # what was checked no longer holds

    def is_complete(self) -> bool:
        return bool(self.chosen())

    def labels(self) -> dict[Key, str]:
        return {key: item.data(0, ROLE)[2]["name"] for key, item in self.items.items()}

    def save(self) -> str:
        return api.save_selection(self.project_dir, self.game, self.chosen(), self.labels())

    # ---------------------------------------------------------- conflicts
    def check_conflicts(self) -> None:
        """Check the selection now, in a worker thread; a check asked for while
        one runs is made once that one ends."""
        self.timer.stop()
        if self._loading:
            return                      # the list arriving is checked when it is shown
        if self._checking is not None:
            self._recheck = True
            return
        self._recheck = False
        check, args = self.check, (self.game, self.chosen(), self.labels(),
                                   self.project_dir)
        generation = self._generation
        # nothing the check reads has changed since the last answer: keep it
        # (M5b item 35) - a tick undone, a filter changed, Next pressed again
        digest = f"{generation}:{selection_digest(*args)}"
        if digest == self._answered and self.conflicts:
            self.checked.emit()
            return
        self.checks += 1
        self.panel.busy()

        def run() -> tuple[int, dict | None, str, str]:
            # The generation travels with the result: the slots below are the
            # page's own methods, so Qt runs them on the window's thread (a
            # lambda slot would run on the worker's).
            try:
                return generation, check(*args), "", digest
            except Exception as exc:      # shown on the panel, never a crash
                return generation, None, str(exc), ""
        self._checking = _in_thread(run, self._check_done, self.panel.failed,
                                    self._check_finished)

    def _check_done(self, outcome: tuple) -> None:
        generation, result, problem, digest = outcome
        if generation != self._generation:
            return                      # checked a list this page no longer shows
        if result is None:
            self._answered = ""
            self._set_conflicts({})
            self.panel.failed(problem)
            return
        self._answered = digest
        self._set_conflicts(result)

    def _set_conflicts(self, result: dict) -> None:
        """Show `result` ({} for none): the panel, the tab's count, the filter."""
        self.conflicts = result
        if result:
            self.panel.show_result(result)
        else:
            self.panel.clear()
        waiting = len(open_findings(result))
        self.tabs.setTabText(1, f"Conflicts ({waiting})" if waiting else "Conflicts")
        if self.filter.currentText() == "Conflicts only":
            self.apply_filter()
        self._can_resolve()

    def _check_finished(self) -> None:
        self._checking = None
        if self._recheck and not self._loading:
            self.check_conflicts()
            return
        self.checked.emit()

    def deselect(self, pairs: list) -> None:
        """Untick the chosen (tp2, number) `pairs` (a conflict option, a fix
        on the order page): asked for by the player, so not asked about again;
        a dependency it breaks is the next check's finding."""
        self._updating = True
        try:
            for tp2, number in pairs:
                item = self.items.get((tp2, number))
                if item is not None:
                    item.setCheckState(0, Qt.CheckState.Unchecked)
        finally:
            self._updating = False
        self._count()

    def _mod_items(self, key: str, numbers: list[int]) -> dict[int, QTreeWidgetItem]:
        """
        The choosable components `numbers` of the tp2 an option's key names,
        as the plan names it: `eet` is EET.tp2, not EET_end.tp2 in the same
        folder; a mod's own key only when no tp2 has that key.
        """
        tp2s = [t for m in self.mods for t in m.get("tp2s") or [] if t.get("key") == key]
        if not tp2s:
            mod = next((m for m in self.mods if m["key"] == key), None)
            tp2s = (mod or {}).get("tp2s") or []
            if len(tp2s) != 1:
                return {}               # which of its tp2s is meant is not known
        found: dict[int, QTreeWidgetItem] = {}
        for tp2 in tp2s:
            for number in numbers:
                item = self.items.get((tp2["tp2"], number))
                if item is not None and not item.isDisabled():
                    found.setdefault(number, item)
        return found

    def _can_choose(self, key: str, numbers: list[int]) -> bool:
        return bool(numbers) and set(numbers) <= set(self._mod_items(key, numbers))

    def _choose_in(self, key: str, numbers: list) -> None:
        for item in self._mod_items(key, numbers).values():
            item.setCheckState(0, Qt.CheckState.Checked)

    def _decide(self, finding: str, option: str, why: str) -> None:
        self._write_decisions(lambda choose, accept: (
            choose.__setitem__(finding, option) if option else accept.__setitem__(finding, why)))

    def _undo(self, finding: str) -> None:
        self._write_decisions(lambda choose, accept: (choose.pop(finding, None),
                                                      accept.pop(finding, None)))

    def _forget(self, findings: list) -> None:
        # Only what the current, settled check calls stale: the selection may
        # have changed since the row was shown, or while the question was
        # open, and a decision it names may be live again.
        if self.timer.isActive() or self._checking is not None:
            return                      # the check under way shows the row again if it holds
        stale = set(self.conflicts.get("stale") or []) if \
            self.conflicts.get("rules_checked") else set()
        findings = [finding for finding in findings if finding in stale]
        if not findings:
            return

        def change(choose: dict, accept: dict) -> None:
            for finding in findings:
                choose.pop(finding, None)
                accept.pop(finding, None)
        self._write_decisions(change)

    def _write_decisions(self, change: Callable[[dict, dict], Any]) -> None:
        current = api.load_decisions(self.project_dir)
        if current["problem"]:
            # Never overwrite a file that could not be read: it may hold answers.
            qtext.critical(self, "decisions.json cannot be read",
                                 f"{current['problem']}\n\nFix or remove it first.")
            return
        change(current["choose"], current["accept"])
        try:
            api.save_decisions(self.project_dir, current["choose"], current["accept"])
        except Exception as exc:
            qtext.critical(self, "Cannot save the decision", str(exc))
            return
        self.check_conflicts()

    def _in_conflict(self) -> set[str]:
        """Keys of the mods in a conflict still to decide."""
        tp2s = {tp2 for finding in open_findings(self.conflicts)
                for side in (finding["left"], finding.get("right")) if side
                for tp2, _number in side.get("chosen") or []}
        return {mod["key"] for mod in self.mods
                if any(t["tp2"] in tp2s for t in mod.get("tp2s") or [])}

    # ---------------------------------------------------------- filtering
    def apply_filter(self) -> None:
        current = self.categories.currentItem()
        category = current.data(ROLE) if current is not None else None
        words = self.search.text().strip().lower().split()
        mode = self.filter.currentText()
        by_key = {m["key"]: m for m in self.mods}
        in_conflict = self._in_conflict() if mode == "Conflicts only" else set()
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            mod = by_key.get(item.data(0, ROLE)[1], {})
            text = " ".join([item.text(0), *(item.child(i).text(0)
                                              for i in range(item.childCount()))]).lower()
            visible = not category or category in kinds_of(mod)
            visible = visible and all(word in text for word in words)
            if mode == "Chosen only":
                visible = visible and item.checkState(0) != Qt.CheckState.Unchecked
            elif mode == "Conflicts only":
                visible = visible and mod.get("key") in in_conflict
            elif mode == "Updates available":
                visible = visible and bool(mod.get("update_available"))
            elif mode == "Maybe updated":
                visible = visible and bool(mod.get("maybe_updated"))
            elif mode == "Kinds disagree":
                visible = visible and bool(mod.get("kind_disagreement"))
            item.setHidden(not visible)

    def _show(self, item: QTreeWidgetItem | None) -> None:
        if item is None:
            return
        while item.parent() is not None:
            item = item.parent()
        mod = next((m for m in self.mods if m["key"] == item.data(0, ROLE)[1]), None)
        if mod is None:
            return
        e = html.escape                       # every value here is catalogue text
        lines = [f"<h3>{e(str(mod.get('name') or mod['key']))}</h3>",
                 f"<b>Games:</b> {e(', '.join(mod.get('games') or []) or 'not stated')}",
                 f"<b>Kind:</b> {e(_said(mod) or ', '.join(mod.get('categories') or []) or '-')}"]
        if mod.get("kind_disagreement"):
            lines.append("<b>The sources disagree on its kind:</b> each is shown, "
                         "none is chosen for you.")
        if mod.get("install_category"):
            tags = ", ".join(mod.get("tags") or [])
            lines.append(f"<b>krion64 install category:</b> {e(mod['install_category'])}"
                         + (f" (tags: {e(tags)})" if tags else ""))
        lines.append(f"<b>Status:</b> {e(', '.join(mod.get('status') or []) or '-')}")
        latest = mod.get("latest") or {}
        if latest:
            lines.append(f"<b>Newest version:</b> {e(str(latest.get('version')))} "
                         f"({e(str(latest.get('origin')))}, "
                         f"{e(str(latest.get('date') or 'no date'))})")
        if mod.get("last_update"):
            lines.append(f"<b>lcc-docs last update:</b> {e(str(mod['last_update']))}")
        if mod.get("maybe_updated"):
            page = str(mod.get("page") or "")
            # an https page is a link; any other address is shown, not followed
            link = (f' - <a href="{e(page, quote=True)}">{e(page)}</a>'
                    if page.startswith("https://") else f" - {e(page)}" if page else "")
            lines.append(f"<b>Maybe updated:</b> lcc-docs lists a change on "
                         f"{e(str(mod.get('last_update')))}, after your copy was fetched "
                         f"on {e(str(mod.get('fetched')))}. A date, not a version: the "
                         f"page may only have been edited{link}")
        lines += _krion_lines(mod)
        lines += [f"<b>Warning:</b> {e(str(text))}" for text in mod.get("advisories") or []]
        lines += [f"<b>Cannot be chosen:</b> {e(t['refused'])}"
                  for t in mod.get("tp2s") or [] if t.get("refused")]
        if any(t["origin"] == "krion64" for t in mod.get("tp2s") or []):
            lines.append(f"<i>{KRION_NOTE}</i>")
        self.details.setHtml("<br>".join(lines))
