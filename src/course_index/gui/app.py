# -*- coding: UTF-8 -*-
"""Qt application for editing a course index, with the layout of the TUI: the course and its sections in a sidebar,
the Entries, Sections, Preview and Problems tabs, and the keys of the focused widget in a footer."""
import os
import re
import shutil
import sys
import threading
from html import escape
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPalette
from PySide6.QtWidgets import QAbstractItemView, QApplication, QFrame, QHBoxLayout, QHeaderView, QLabel, \
                              QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QSplitter, QStyleFactory, \
                              QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, \
                              QWidget
from rich.text import Text

from ..common import KIND_MARKS, SKELETON
from ..compiler import compile_pdf, open_file, template_dir
from ..course import CourseInfo, data_file_for
from ..idx import Document, Entry, Level, Raw, _split, page_error, page_sort_key
from ..latex import auto_sort_key, expand_shortcuts, known_commands, plain, render
from ..preview import build, format_pages
from .dialogs import BOOK_CHARS, PAGE_CHARS, CompileReport, CourseDialog, EntryDialog, HelpDialog, NewBookDialog, \
                     SectionDialog, SectionsPane, XrefDialog, book_error, restrict
from .widgets import HTML_ROLE, EntryView, Field, Footer, HtmlDelegate, KeyLineEdit, Toasts, colors, is_dark, to_html

__all__ = ["IndexWindow", "run"]

MAX_UNDO = 300
TAB_ENTRIES, TAB_SECTIONS, TAB_PREVIEW, TAB_PROBLEMS = range(4)
CTRL, ALT, SHIFT = Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.AltModifier, \
    Qt.KeyboardModifier.ShiftModifier
NOMOD = Qt.KeyboardModifier.NoModifier
K = Qt.Key


class _Bridge(QObject):
    """Results of the worker threads, delivered in the GUI thread."""
    checked = Signal(object, object)
    compiled = Signal(object)


class IndexWindow(QMainWindow):
    """Editor of an `.idx` file of the LaTeX course index template."""
    # keys of the window, in the footer: (key, label, action)
    KEYS = [("^s", "Save", "save"), ("F5", "PDF", "compile"), ("F2", "Course", "course"),
            ("F3", "New book", "new_book"), ("F4", "Sections", "sections"), ("^z", "Undo", "undo"),
            ("F1", "Help", "help"), ("^q", "Quit", "quit")]
    TABLE_KEYS = [("e", "Edit", "edit"), ("n", "New", "new"), ("a", "Add", "focus_add"), ("d", "Delete", "delete"),
                  ("x", "Xref", "xref"), ("/", "Filter", "filter")]
    QUICKADD_KEYS = [("^↑", "Page +1", lambda w: w.action_page(1)), ("^↓", "Page −1", lambda w: w.action_page(-1))]

    def __init__(self, path, open_pdf=True):
        super().__init__()
        self.path = Path(path)
        self.open_pdf = open_pdf
        if self.path.exists():
            self.doc = Document.load(self.path)
            self.is_new = False
        else:
            self.doc = Document.parse(SKELETON.read_text(encoding="utf-8"))
            self.is_new = True
        self.data_path = data_file_for(self.path)
        self.course = CourseInfo.load(self.data_path) if self.data_path.exists() else CourseInfo.guess(self.path)
        tex = template_dir(self.path) / "main.tex"
        self.commands = known_commands(tex.read_text(encoding="utf-8", errors="replace")) if tex.exists() else None
        self.undo_stack, self.redo_stack = [], []
        self.modified, self.backup_done = self.is_new, False
        self.row_items, self.item_rows = [], {}
        self.expanded = set()  # titles of the expanded sections (all are collapsed by default)
        self.filter_text = ""
        self.problems = []
        self._candidates = None
        self._suggestions = []
        self._navigated = False
        self._preview_dirty = True
        self._cells = {}
        self._flagged = {}
        self._compiling = False
        books = self.doc.books()
        self.default_book = books[0] if books else ""
        self.bridge = _Bridge()
        self.bridge.checked.connect(self.checked)
        self.bridge.compiled.connect(self.compiled)
        self._check_timer = QTimer(self, singleShot=True, interval=120)
        self._check_timer.timeout.connect(self._start_check)
        self.compose()
        self.refresh_all()
        self.table.setFocus()
        QApplication.instance().focusChanged.connect(self.update_footer)
        self.update_footer()
        if self.is_new:
            self.notify(f"New index: {self.path.name} will be created when saving (Ctrl+S)")
        if not self.doc.books():
            self.notify("No book yet: press F3 to create the first one", timeout=6)

    # ------------------------------------------------------ layout --------------------------------------------------
    def compose(self):
        self.resize(1400, 860)
        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        split = QSplitter(Qt.Orientation.Horizontal, central)
        split.setChildrenCollapsible(False)
        outer.addWidget(split, 1)
        # sidebar: course metadata and sections
        sidebar = QFrame(split)
        sidebar.setObjectName("sidebar")
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(10, 8, 10, 8)
        title = QLabel(f'<b>Course</b> <span style="color:{colors()["dim"]}">· F2 to edit</span>')
        title.setObjectName("sidebar-title")
        title.setCursor(Qt.CursorShape.PointingHandCursor)
        title.mousePressEvent = lambda e: self.action_course()
        side.addWidget(title)
        self.course_info = QLabel()
        self.course_info.setObjectName("course-info")
        self.course_info.setWordWrap(True)
        self.course_info.setTextFormat(Qt.TextFormat.RichText)
        self.course_info.setAlignment(Qt.AlignmentFlag.AlignTop)
        side.addWidget(self.course_info)
        sec = QLabel("<b>Sections</b>")
        sec.setObjectName("sidebar-title")
        side.addSpacing(8)
        side.addWidget(sec)
        self.sections = QListWidget(sidebar)
        self.sections.setObjectName("sections")
        self.sections.setItemDelegate(HtmlDelegate(self.sections))
        self.sections.itemClicked.connect(self.section_selected)
        self.sections.keyPressEvent = self._sections_key
        side.addWidget(self.sections, 1)
        sidebar.setMinimumWidth(220)
        # tabs
        self.tabs = QTabWidget(split)
        self.tabs.setObjectName("tabs")
        self.tabs.setDocumentMode(True)
        entries = QWidget()
        lay = QVBoxLayout(entries)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(6)
        # quick-add bar
        qa = QFrame(entries)
        qa.setObjectName("quickadd")
        qal = QHBoxLayout(qa)
        qal.setContentsMargins(10, 6, 10, 6)
        label = QLabel("Add")
        label.setObjectName("qa-label")
        qal.addWidget(label, 0, Qt.AlignmentFlag.AlignBottom)
        self.qa_book = restrict(KeyLineEdit(self.default_book), BOOK_CHARS)
        self.qa_book.setPlaceholderText("F3: new")
        self.qa_book.setProperty("help", "Book (e.g. 1, 2, W); F3 creates a new book")
        self.qa_book.setToolTip(self.qa_book.property("help"))
        self.qa_page = restrict(KeyLineEdit(""), PAGE_CHARS)
        self.qa_page.setPlaceholderText("page")
        self.qa_page.setProperty("help", "Page or range (e.g. 45 or 45-47)")
        self.qa_page.setToolTip(self.qa_page.property("help"))
        self.qa_term = KeyLineEdit("")
        self.qa_term.setPlaceholderText("Term!Sub-term, then Enter  ·  shortcuts: `code` **bold** :linux:")
        for name, w in (("qa-book", self.qa_book), ("qa-page", self.qa_page), ("qa-term", self.qa_term)):
            w.setObjectName(name)
        fb, fp = Field("Book", self.qa_book), Field("Page", self.qa_page)
        fb.setFixedWidth(90)
        fp.setFixedWidth(100)
        qal.addWidget(fb)
        qal.addWidget(fp)
        qal.addWidget(Field("Term (Tab: complete)", self.qa_term), 1)
        self.quickadd = qa
        lay.addWidget(qa)
        # suggestions
        self.suggestions = QListWidget(entries)
        self.suggestions.setObjectName("suggestions")
        self.suggestions.setItemDelegate(HtmlDelegate(self.suggestions))
        self.suggestions.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.suggestions.itemClicked.connect(self.suggestion_clicked)
        self.suggestions.hide()
        lay.addWidget(self.suggestions)
        # filter
        self.filter = KeyLineEdit("")
        self.filter.setObjectName("filter")
        self.filter.setPlaceholderText("Filter: text, book:2, page:45 (Esc to clear)")
        self.filter.textChanged.connect(self.filter_changed)
        self.filter.returnPressed.connect(lambda: self.table.setFocus())
        self.filter.handlers[(K.Key_Escape, NOMOD)] = self.close_filter
        self.filter.hide()
        lay.addWidget(self.filter)
        # lines of the index
        self.table = EntryView(entries)
        self.table.setObjectName("table")
        self.table.is_header_row = self.is_header_row
        self.table.keyPressed.connect(self.table_key)
        self.table.caretClicked.connect(lambda row: self.action_fold(None))
        self.table.doubleClicked.connect(lambda index: self.action_edit())
        lay.addWidget(self.table, 1)
        self.tabs.addTab(entries, "Entries")
        # sections, preview, problems
        self.sections_pane = SectionsPane(self)
        self.sections_pane.setObjectName("sections-pane")
        self.tabs.addTab(self.sections_pane, "Sections")
        self.preview = QTreeWidget()
        self.preview.setObjectName("preview")
        self.preview.setHeaderHidden(True)
        self.preview.setItemDelegate(HtmlDelegate(self.preview))
        self.preview.itemActivated.connect(self.preview_selected)
        self.tabs.addTab(self.preview, "Preview")
        self.problems_table = QTableWidget(0, 3)
        self.problems_table.setObjectName("problems")
        self.problems_table.setHorizontalHeaderLabels(["Line", "Level", "Problem"])
        self.problems_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.problems_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.problems_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.problems_table.setAlternatingRowColors(True)
        self.problems_table.setShowGrid(False)
        self.problems_table.verticalHeader().hide()
        self.problems_table.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 6)
        h = self.problems_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.problems_table.itemActivated.connect(self.problem_selected)
        self.tabs.addTab(self.problems_table, "Problems")
        self.tabs.currentChanged.connect(self.tab_activated)
        split.addWidget(sidebar)
        split.addWidget(self.tabs)
        split.setStretchFactor(1, 1)
        split.setSizes([330, 1070])
        # footer
        self.footer = Footer(central)
        outer.addWidget(self.footer)
        self.setCentralWidget(central)
        self.toasts = Toasts(central)
        # quick-add keys
        for w in (self.qa_book, self.qa_page, self.qa_term):
            for key in ((K.Key_Up, CTRL), (K.Key_PageUp, NOMOD)):
                w.handlers[key] = lambda: self.action_page(1)
            for key in ((K.Key_Down, CTRL), (K.Key_PageDown, NOMOD)):
                w.handlers[key] = lambda: self.action_page(-1)
            w.handlers[(K.Key_Escape, NOMOD)] = self.action_focus_table
        t = self.qa_term.handlers
        t[(K.Key_Tab, NOMOD)] = self.action_accept_suggestion
        t[(K.Key_Down, NOMOD)] = lambda: self.action_suggestion(1)
        t[(K.Key_Up, NOMOD)] = lambda: self.action_suggestion(-1)
        t[(K.Key_Escape, NOMOD)] = self.action_close_suggestions
        self.qa_term.textChanged.connect(self.term_changed)
        self.qa_term.returnPressed.connect(self.term_submitted)
        self.qa_book.returnPressed.connect(self.qa_page.setFocus)
        self.qa_page.returnPressed.connect(self.qa_term.setFocus)
        self.qa_book.textChanged.connect(self.validate_bar)
        self.qa_page.textChanged.connect(self.validate_bar)
        # window keys
        for keys, action in ((("Ctrl+S", ), "save"), (("F5", ), "compile"), (("F2", ), "course"),
                             (("F3", ), "new_book"), (("F4", ), "sections"), (("Ctrl+Z", ), "undo"),
                             (("Ctrl+Y", "Ctrl+Shift+Z"), "redo"), (("Ctrl+F", ), "filter"), (("F1", ), "help"),
                             (("Ctrl+Q", ), "quit")):
            a = QAction(self)
            a.setShortcuts([QKeySequence(k) for k in keys])
            a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            a.triggered.connect(getattr(self, f"action_{action}"))
            self.addAction(a)

    def update_footer(self, *args):
        """Keys of the focused widget, then the keys of the window."""
        if not hasattr(self, "footer"):
            return
        w = QApplication.focusWidget()
        keys = []
        if w is self.table:
            keys = [(k, label, getattr(self, f"action_{a}")) for k, label, a in self.TABLE_KEYS]
        elif w in (self.qa_book, self.qa_page, self.qa_term):
            keys = [(k, label, (lambda f=f: f(self))) for k, label, f in self.QUICKADD_KEYS]
        elif w is self.sections:
            keys = [("e", "Edit section", self.action_edit_section)]
        elif w is self.sections_pane.table:
            keys = [(k, label, self.sections_pane.action(a)) for k, label, a in SectionsPane.KEYS]
        keys += [(k, label, getattr(self, f"action_{a}")) for k, label, a in self.KEYS]
        self.footer.set_keys(keys)

    # ------------------------------------------------------ helpers -------------------------------------------------
    def notify(self, message, severity="information", timeout=5):
        return self.toasts.notify(message, severity, timeout)

    def current_index(self):
        """Index of the item under the cursor of the table, if any."""
        row = self.table.cursor_row
        if not self.row_items or row >= len(self.row_items):
            return None
        return self.row_items[row]

    def current_entry(self):
        i = self.current_index()
        if i is not None and isinstance(self.doc.items[i], Entry):
            return i, self.doc.items[i]
        return None, None

    def snapshot(self):
        self.undo_stack.append(list(self.doc.items))
        del self.undo_stack[:-MAX_UNDO]
        self.redo_stack.clear()

    def changed(self, select=None):
        self.modified = True
        self._candidates = None
        self._preview_dirty = True
        self.refresh_all(select)

    def update_title(self):
        self.setWindowTitle(f"Course Index — {self.course.display_title} — {self.path}{' ●' if self.modified else ''}")
        # read-only summary of the course metadata (edited with F2)
        c, dim = self.course, colors()["dim"]
        rows = []
        for label, value, bold in [("Code", c.code, True), ("Title", c.display_title, True), ("Date", c.date, False),
                                   ("Version", c.version, False), ("Author", c.author, False)]:
            value = escape(plain(value))
            value = (f"<b>{value}</b>" if bold else value) if value else f'<span style="color:{dim}">—</span>'
            rows.append(f'<tr><td style="color:{dim}; padding-right:10px">{label}</td><td>{value}</td></tr>')
        self.course_info.setText(f"<table>{''.join(rows)}</table>")

    def book_label(self, b):
        return f"{self.course.code}.{b}" if b else ""

    # ------------------------------------------------------ rendering -----------------------------------------------
    def _matches(self, i, it, eff):
        f = self.filter_text.strip().lower()
        if not f:
            return True
        if not isinstance(it, Entry):
            return False
        for tok in f.split():
            if tok.startswith("book:"):
                if (eff.get(i) or "").lower() != tok[5:]:
                    return False
            elif tok.startswith("page:"):
                try:
                    p = int(tok[5:])
                except ValueError:
                    return False
                nums = page_sort_key(it.page)
                if not (len(nums) and nums[0] != float("inf") and nums[0] <= p <= nums[-1]):
                    return False
            elif tok not in it.to_line().lower() and tok not in plain(it.key).lower():
                return False
        return True

    def _term_cell(self, it):
        if isinstance(it, Raw):
            if it.section:
                return Text(f"━━ {it.section} ━━", "bold magenta")
            first = next((x.strip() for x in it.text.splitlines() if x.strip().strip("{}*\\comment")), "")
            n = it.text.count("\n") + 1
            return Text(f"💬 {first[:80]}" + (f"  (+{n - 1} lines)" if n > 1 else ""), "dim italic")
        kind = it.kind
        t = Text()
        if kind in ("spacer", "pagebreak"):
            mark, label = KIND_MARKS[kind]
            t.append(f"{mark} {label}", "dim italic")
            t.append(f"  [{it.top.sort}]", "dim")
        else:
            if kind in KIND_MARKS:
                t.append(KIND_MARKS[kind][0] + " ", "yellow")
            for n, lv in enumerate(it.levels):
                if n:
                    t.append(" › ", "dim")
                if lv.key is not None and (n == 0 or lv.key != plain(lv.text)):
                    t.append(f"{lv.key}@" if lv.text.strip() else lv.key, "dim")
                if lv.is_blank:
                    t.append("⎵" * len(lv.text), "dim")
                else:
                    t.append_text(render(lv.text))
        if it.disabled:
            t.stylize("dim strike")
        return t

    def _cell(self, it):
        """Rendered term cell of an item (cached: items are immutable)."""
        try:
            return self._cells[it]
        except KeyError:
            if len(self._cells) > 20000:
                self._cells.clear()
            c = self._cells[it] = self._term_cell(it)
            return c

    def refresh_all(self, select=None, check=True):
        """Rebuild the rows of the table and the sections list (keeping or moving the cursor), then check the index
        in the background."""
        keep = select if select is not None else self.current_index()
        eff = self.doc.effective_books()
        flagged = self._flagged
        lines = self.doc.line_numbers()
        if select is not None:
            self.reveal(select)
        self.row_items, self.item_rows = [], {}
        rows, header, counts, flags = [], None, {}, {}
        for i, it in enumerate(self.doc.items):
            if isinstance(it, Raw) and it.section:
                header = i
            elif header is not None and isinstance(it, Entry):
                counts[header] = counts.get(header, 0) + 1
                if (p := flagged.get(it)):
                    flags[header] = "error" if p == "error" or flags.get(header) == "error" else p
            if isinstance(it, Raw) and it.is_blank:
                continue
            if self.filter_text:
                if not self._matches(i, it, eff):
                    continue
            elif header is not None and header != i and self.doc.items[header].section not in self.expanded:
                continue
            if isinstance(it, Entry):
                b = eff.get(i)
                ref = it.kind == "ref"
                book = Text(b or "", "" if it.book else "dim") if ref else ""
                page = Text(it.page, "dim" if it.disabled else "") if ref else ""
                flag = Text("%", "dim") if it.disabled else ""
                p = flagged.get(it)
                if p:
                    flag = Text("✖", "red") if p == "error" else Text("⚠", "yellow")
            else:
                book = page = flag = ""
            self.item_rows[i] = len(self.row_items)
            self.row_items.append(i)
            rows.append((Text(str(lines[i]), "dim"), self._cell(it), book, page, flag))
        if not self.filter_text:
            # section headers: caret, number of entries and the worst problem of a collapsed section
            for i in self.row_items:
                it = self.doc.items[i]
                if not (isinstance(it, Raw) and it.section):
                    continue
                r, opened = self.item_rows[i], it.section in self.expanded
                n = counts.get(i, 0)
                cell = Text.assemble(("▼ " if opened else "▶ ", "bold"), self._cell(it),
                                     (f"  {n} entr{'ies' if n != 1 else 'y'}", "dim"))
                flag = ""
                if not opened and flags.get(i):
                    flag = Text("✖", "red") if flags[i] == "error" else Text("⚠", "yellow")
                rows[r] = (rows[r][0], cell, "", "", flag)
        self.table.set_rows(rows)
        self.refresh_sections()
        self.sections_pane.refresh_table()
        self.update_title()
        if keep is not None:
            self.select_item(keep)
        if self.tabs.currentIndex() == TAB_PREVIEW:
            self.refresh_preview()
        if check:
            self._check_timer.start()

    def _start_check(self):
        items = list(self.doc.items)
        commands = self.commands

        def work():
            problems = Document(items).check(commands)
            self.bridge.checked.emit(items, problems)
        threading.Thread(target=work, daemon=True).start()

    def checked(self, items, problems):
        if items != self.doc.items:
            return
        self.problems = problems
        # flags are keyed by item (and not by index) so that they stay right while the index is being edited
        flagged = {}
        for p in problems:
            it = items[p.index]
            if flagged.get(it) != "error":
                flagged[it] = p.severity
        changed = flagged != self._flagged
        self._flagged = flagged
        self.refresh_problems(Document(items).line_numbers())
        if changed:
            self.refresh_all(check=False)

    def header_of(self, index):
        """Index of the header of the section holding the given item (None before the first section)."""
        for j in range(min(index, len(self.doc.items) - 1), -1, -1):
            it = self.doc.items[j]
            if isinstance(it, Raw) and it.section:
                return j
        return None

    def is_header_row(self, row):
        if not 0 <= row < len(self.row_items):
            return False
        it = self.doc.items[self.row_items[row]]
        return isinstance(it, Raw) and bool(it.section)

    def reveal(self, index):
        """Expand the section holding the given item."""
        h = self.header_of(index) if 0 <= index < len(self.doc.items) else None
        if h is not None and h != index:
            self.expanded.add(self.doc.items[h].section)

    def action_fold(self, expand=None):
        """Expand (True), collapse (False) or toggle (None) the section under the cursor."""
        i = self.current_index()
        if i is None or self.filter_text:
            return
        h = self.header_of(i)
        if h is None:
            return
        title = self.doc.items[h].section
        if expand is None:
            expand = title not in self.expanded
        if expand == (title in self.expanded):
            return
        (self.expanded.add if expand else self.expanded.discard)(title)
        self.refresh_all(h, check=False) if not expand else self.refresh_all(check=False)

    def action_fold_all(self, expand):
        if self.filter_text:
            return
        i = self.current_index()
        h = self.header_of(i) if i is not None else None
        self.expanded = {t for _, t in self.doc.sections()} if expand else set()
        if expand:
            self.refresh_all(check=False)
        else:
            self.refresh_all(h, check=False)

    def select_item(self, index):
        """Move the cursor of the table to the given item (or the closest visible one)."""
        if not self.row_items:
            return
        row = self.item_rows.get(index)
        if row is None and not self.filter_text and 0 <= index < len(self.doc.items) and \
                not (isinstance(self.doc.items[index], Raw) and self.doc.items[index].is_blank):
            # hidden in a collapsed section: expand it
            h = self.header_of(index)
            if h is not None and self.doc.items[h].section not in self.expanded:
                self.refresh_all(index, check=False)
                return
        if row is None:
            row = next((r for r, i in enumerate(self.row_items) if i >= index), len(self.row_items) - 1)
        self.table.move_cursor(row, center=True)

    def refresh_sections(self):
        ol = self.sections
        hl = ol.currentRow()
        ol.clear()
        secs = self.doc.sections()
        bounds = [i for i, _ in secs] + [len(self.doc.items)]
        for n, (i, t) in enumerate(secs):
            count = sum(1 for j in range(i, bounds[n + 1]) if isinstance(self.doc.items[j], Entry))
            it = QListWidgetItem(t.replace(" SECTION", "").title())
            it.setData(Qt.ItemDataRole.UserRole, i)
            it.setData(HTML_ROLE, to_html(Text.assemble((t.replace(" SECTION", "").title(), ""), (f"  {count}", "dim"))))
            ol.addItem(it)
        if 0 <= hl < len(secs):
            ol.setCurrentRow(hl)

    def refresh_problems(self, lines):
        pt = self.problems_table
        pt.setRowCount(0)
        c = colors()
        for p in self.problems:
            r = pt.rowCount()
            pt.insertRow(r)
            line = QTableWidgetItem(str(lines[p.index]))
            line.setForeground(QColor(c["dim"]))
            line.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            level = QTableWidgetItem(p.severity)
            level.setForeground(QColor(c["red"] if p.severity == "error" else c["yellow"]))
            pt.setItem(r, 0, line)
            pt.setItem(r, 1, level)
            pt.setItem(r, 2, QTableWidgetItem(p.message))
        n = len(self.problems)
        self.tabs.setTabText(TAB_PROBLEMS, f"Problems ({n})" if n else "Problems")

    def refresh_preview(self):
        if not self._preview_dirty:
            return
        self._preview_dirty = False
        tree = self.preview
        tree.clear()
        root = QTreeWidgetItem(tree)
        root.setData(0, HTML_ROLE, to_html(Text(self.course.display_title, "bold")))
        code = self.course.code

        def add(parent, node):
            if node.kind == "spacer":
                label = Text("␣", "dim")
            elif node.kind == "pagebreak":
                label = Text("──── page break ────", "dim")
            else:
                label = render(node.level.text) if not node.level.is_blank else Text("⎵", "dim")
                if node.refs:
                    label.append("  " + format_pages(node.refs, code), "green")
            item = QTreeWidgetItem(parent)
            item.setData(0, HTML_ROLE, to_html(label))
            item.setData(0, Qt.ItemDataRole.UserRole, node.items[0] if node.items else None)
            for child in node.sorted_children():
                add(item, child)
            item.setExpanded(True)

        for title, nodes in build(self.doc):
            group = QTreeWidgetItem(root)
            group.setData(0, HTML_ROLE, to_html(Text(title, "bold magenta")))
            for node in nodes:
                add(group, node)
            group.setExpanded(True)
        root.setExpanded(True)

    # ------------------------------------------------------ events --------------------------------------------------
    def tab_activated(self, index):
        if index == TAB_PREVIEW:
            self.refresh_preview()

    def problem_selected(self, item):
        r = item.row()
        if r < len(self.problems):
            self.goto_item(self.problems[r].index)

    def preview_selected(self, item, column=0):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data is not None:
            self.goto_item(data)

    def section_selected(self, item):
        i = item.data(Qt.ItemDataRole.UserRole)
        self.goto_item(i)
        book = Document.section_book(self.doc.items[i].section)
        if book:
            self.qa_book.setText(book)

    def _sections_key(self, event):
        if event.text() == "e":
            self.action_edit_section()
        elif event.key() in (K.Key_Return, K.Key_Enter) and self.sections.currentItem():
            self.section_selected(self.sections.currentItem())
        else:
            QListWidget.keyPressEvent(self.sections, event)

    def goto_item(self, index):
        if self.filter_text:
            self.filter_text = ""
            self.filter.blockSignals(True)
            self.filter.setText("")
            self.filter.blockSignals(False)
            self.filter.hide()
            self.refresh_all(index)
        self.tabs.setCurrentIndex(TAB_ENTRIES)
        it = self.doc.items[index] if 0 <= index < len(self.doc.items) else None
        if isinstance(it, Raw) and it.section:
            self.expanded.add(it.section)
            self.refresh_all(index, check=False)
        self.select_item(index)
        self.table.setFocus()

    def filter_changed(self, value):
        self.filter_text = value
        self.refresh_all()

    def close_filter(self):
        self.filter.setText("")
        self.filter.hide()
        self.table.setFocus()

    def table_key(self, event):
        """Keys of the table of the lines (the event is accepted when handled)."""
        key, mods, text = event.key(), event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier, event.text()
        moving = mods == ALT or mods == CTRL | SHIFT
        actions = {
            (K.Key_Return, NOMOD): self.action_edit, (K.Key_Enter, NOMOD): self.action_edit,
            (K.Key_Delete, NOMOD): self.action_delete, (K.Key_Space, NOMOD): self.action_toggle,
            (K.Key_Right, NOMOD): lambda: self.action_fold(True), (K.Key_Left, NOMOD): lambda: self.action_fold(False),
            (K.Key_Home, NOMOD): lambda: self.table.move_cursor(0),
            (K.Key_End, NOMOD): lambda: self.table.move_cursor(len(self.row_items) - 1),
        }
        chars = {"e": self.action_edit, "n": self.action_new, "a": self.action_focus_add, "c": self.action_duplicate,
                 "d": self.action_delete, "b": self.action_spacer, "p": self.action_pagebreak, "x": self.action_xref,
                 "s": self.action_show_section, "/": self.action_filter, "+": lambda: self.action_fold_all(True),
                 "=": lambda: self.action_fold_all(True), "-": lambda: self.action_fold_all(False),
                 "?": self.action_help}
        action = None
        if moving and key in (K.Key_Up, K.Key_Down):
            action = lambda: self.action_move(-1 if key == K.Key_Up else 1)  # noqa: E731
        elif (key, mods) in actions:
            action = actions[(key, mods)]
        elif text and not mods & (CTRL | ALT) and text in chars:
            action = chars[text]
        if action:
            event.accept()
            action()

    # ------------------------------------------------------ quick add -----------------------------------------------
    def candidates(self):
        """Existing terms (base paths and their parents) for the suggestions: (raw, display, books)."""
        if self._candidates is None:
            self._candidates = []
            for path, books in self.doc.paths().items():
                display = " › ".join(plain(Level.parse(x).text) or Level.parse(x).sort for x in path)
                self._candidates.append(("!".join(path), display, sorted(books)))
        return self._candidates

    def term_changed(self, value):
        self._navigated = False
        q = value.strip().lower()
        ol = self.suggestions
        if len(q) < 2:
            self.action_close_suggestions(False)
            return
        tokens = [t for t in re.split(r"[\s!›]+", q) if t]
        scored = []
        for raw, display, books in self.candidates():
            hay = display.lower() + " " + raw.lower()
            if raw.lower() == q:
                continue
            if all(t in hay for t in tokens):
                d = display.lower()
                score = 0 if d.startswith(tokens[0]) else 1 if f" {tokens[0]}" in f" {d}" else 2
                scored.append((score, len(display), raw, display, books))
        scored.sort()
        self._suggestions = scored[:8]
        if not self._suggestions:
            self.action_close_suggestions(False)
            return
        ol.clear()
        for _, _, raw, display, books in self._suggestions:
            t = Text(display)
            t.append("   " + (f"books {', '.join(books)}" if books else "group"), "dim")
            it = QListWidgetItem(t.plain)
            it.setData(HTML_ROLE, to_html(t))
            ol.addItem(it)
        ol.setCurrentRow(-1)
        rh = ol.sizeHintForRow(0) if ol.count() else self.fontMetrics().height() + 4
        ol.setFixedHeight(min(10, len(self._suggestions)) * rh + 2 * ol.frameWidth() + 4)
        ol.show()

    def action_suggestion(self, step):
        ol = self.suggestions
        if ol.isHidden() or not self._suggestions:
            return False
        n = len(self._suggestions)
        cur = ol.currentRow()
        ol.setCurrentRow((0 if step > 0 else n - 1) if cur < 0 else (cur + step) % n)
        self._navigated = True

    def action_close_suggestions(self, back=True):
        ol = self.suggestions
        if back and ol.isHidden() and self.qa_term.hasFocus():
            # Escape without suggestions: back to the table
            self.table.setFocus()
        ol.hide()
        self._suggestions, self._navigated = [], False

    def action_accept_suggestion(self):
        if not self.qa_term.hasFocus() or self.suggestions.isHidden() or not self._suggestions:
            return False                               # Tab moves the focus
        raw = self._suggestions[max(self.suggestions.currentRow(), 0)][2]
        self.qa_term.setText(raw)
        self.qa_term.setCursorPosition(len(raw))
        self.action_close_suggestions(False)

    def suggestion_clicked(self, item):
        raw = self._suggestions[self.suggestions.row(item)][2]
        self.qa_term.setText(raw)
        self.qa_term.setFocus()
        self.qa_term.setCursorPosition(len(raw))
        self.action_close_suggestions(False)

    def action_focus_add(self):
        self.tabs.setCurrentIndex(TAB_ENTRIES)
        self.qa_term.setFocus()

    def action_focus_table(self):
        self.action_close_suggestions(False)
        self.table.setFocus()

    def action_page(self, step):
        nums = [int(x) for x in re.findall(r"\d+", self.qa_page.text())]
        if not nums:
            self.qa_page.setText("1")
            return
        self.qa_page.setText(str(max(1, (nums[-1] + 1) if step > 0 else (nums[0] - 1))))

    def validate_bar(self, *args):
        self.qa_book.set_invalid(book_error(self.qa_book.text(), self.doc.books()))
        page = self.qa_page.text().strip()
        self.qa_page.set_invalid(page_error(page) if page else None)

    def make_levels(self, term):
        """Split a typed term into levels, expanding shortcuts and adding sort keys for new terms only."""
        known = {c[0] for c in self.candidates()}
        parts, levels = _split(term, "!"), []
        for n, part in enumerate(parts):
            prefix = "!".join(parts[:n + 1])
            if prefix in known:
                levels.append(Level.parse(part))
                continue
            lv = Level.parse(part)
            text = expand_shortcuts(lv.text)
            key = lv.key if lv.key is not None else auto_sort_key(text)
            levels.append(Level(text, key))
        return levels

    def term_submitted(self):
        if self._navigated and self._suggestions:
            self.action_accept_suggestion()
            return
        self.add_from_bar()

    def add_from_bar(self):
        book, page, term = self.qa_book.text().strip(), self.qa_page.text().strip(), self.qa_term.text().strip()
        if not term:
            return
        if not book:
            self.notify("Set the book first" + ("" if self.doc.books() else " (F3 creates a new book)"),
                        severity="warning")
            self.qa_book.setFocus()
            return
        if book not in self.doc.books():
            self.notify(f"Book {book} does not exist yet: press F3 to create it", severity="error")
            self.qa_book.setFocus()
            return
        if not page:
            self.notify("Set the page first", severity="warning")
            self.qa_page.setFocus()
            return
        if (err := page_error(page)):
            self.notify(f"Page {page}: {err}", severity="error")
            self.qa_page.setFocus()
            return
        levels = self.make_levels(term)
        self.snapshot()
        i = self.doc.add_reference(levels, book, page)
        self.action_close_suggestions(False)
        self.qa_term.blockSignals(True)
        self.qa_term.setText("")
        self.qa_term.blockSignals(False)
        self.changed(i)
        e = self.doc.items[i]
        self.notify(Text.assemble("Added ", render(" › ".join(lv.text for lv in levels)),
                                  (f"  {self.course.code}.{book}–{page}", "green"),
                                  (f"  (line {self.doc.line_numbers()[i]}, {self.doc.section_of(i) or 'top'})", "dim")),
                    timeout=4)
        if e.path != tuple(str(x) for x in levels):
            self.notify("Added on a new line for this book", timeout=3)

    # ------------------------------------------------------ actions -------------------------------------------------
    def action_edit(self):
        if QApplication.activeModalWidget() is not None:
            return                                     # a dialog is already open
        i, e = self.current_entry()
        if e is None and self.is_header_row(self.table.cursor_row) and not self.filter_text:
            self.action_fold(None)
            return
        if e is None:
            k = self.current_index()
            if k is not None and isinstance(self.doc.items[k], Raw) and self.doc.items[k].is_malformed_entry:
                self.edit_malformed(k, self.doc.items[k])
            elif k is not None:
                self.notify("Comments and section headers are kept as they are; edit them in a text editor",
                            severity="warning")
            return
        title_of = next((b for b, top in self.doc.chapters().items() if e.path[0] == top), None)
        new = EntryDialog(e, "Edit entry", self.course.code, self.commands, self.doc.books(), title_of=title_of,
                          parent=self).ask()
        if new is not None and new != e:
            if i >= len(self.doc.items) or self.doc.items[i] is not e:
                self.notify("The entry changed meanwhile: not saved", severity="error")
                return
            self.snapshot()
            self.doc.items[i] = new
            j = self.doc.relocate(i) if new.book != e.book else i
            self.changed(j)
            if j != i:
                self.notify(f"Moved to {self.doc.section_of(j)} (book {new.book})", timeout=3)

    def edit_malformed(self, i, raw):
        """Correct a malformed `\\indexentry` line: it becomes a normal entry once saved."""
        new = EntryDialog(Entry.salvage(raw.text), "Correct a malformed entry", self.course.code, self.commands,
                          self.doc.books(), raw=raw.text, parent=self).ask()
        if new is not None:
            if i >= len(self.doc.items) or self.doc.items[i] is not raw:
                self.notify("The line changed meanwhile: not saved", severity="error")
                return
            self.snapshot()
            self.doc.items[i] = new
            j = self.doc.relocate(i)
            self.changed(j)
            self.notify("Line corrected" + (f", moved to {self.doc.section_of(j)}" if j != i else ""), timeout=3)

    def action_new(self):
        i = self.current_index()
        book = self.qa_book.text().strip()
        book = book if book in self.doc.books() else ""
        e = Entry((Level(""), ), self.qa_page.text().strip(), f"book{{{book}}}" if book else None)
        new = EntryDialog(e, "New entry", self.course.code, self.commands, self.doc.books(), new=True,
                          parent=self).ask()
        if new is not None:
            self.snapshot()
            pos = self.doc.place(new, i)
            self.changed(pos)
            if i is not None and pos != i + 1:
                self.notify(f"Added to {self.doc.section_of(pos)}", timeout=3)

    def action_duplicate(self):
        i, e = self.current_entry()
        if e is not None:
            self.snapshot()
            self.doc.items.insert(i + 1, e.evolve())
            self.changed(i + 1)

    def action_delete(self):
        i = self.current_index()
        if i is None:
            return
        it = self.doc.items[i]
        if isinstance(it, Raw) and it.section:
            self.notify("Section headers cannot be deleted here", severity="warning")
            return
        self.snapshot()
        del self.doc.items[i]
        self.changed(min(i, len(self.doc.items) - 1))
        self.notify("Deleted (Ctrl+Z to undo)", timeout=2)

    def action_toggle(self):
        if self.is_header_row(self.table.cursor_row) and not self.filter_text:
            self.action_fold(None)
            return
        i, e = self.current_entry()
        if e is not None:
            self.snapshot()
            self.doc.items[i] = e.evolve(disabled=not e.disabled)
            self.changed(i)

    def _spacer(self, pagebreak):
        i = self.current_index()
        if i is None:
            return
        try:
            self.snapshot()
            j = self.doc.add_spacer(i, pagebreak)
        except ValueError as err:
            self.undo_stack.pop()
            self.notify(str(err), severity="error")
            return
        self.changed(j)

    def action_spacer(self):
        self._spacer(False)

    def action_pagebreak(self):
        self._spacer(True)

    def action_xref(self):
        i, e = self.current_entry()
        source = "!".join(e.base_path) if e is not None and e.kind == "ref" else ""
        res = XrefDialog("", source, parent=self).ask()
        if res:
            self.snapshot()
            j = self.doc.add_xref(*res)
            self.changed(j)

    def action_move(self, step):
        i = self.current_index()
        if i is None:
            return
        # move over the next visible row (skipping blank lines)
        row = self.item_rows[i] + step
        if not 0 <= row < len(self.row_items):
            return
        j = self.row_items[row]
        self.snapshot()
        items = self.doc.items
        it = items.pop(i)
        items.insert(j, it)
        self.changed(j)

    def action_filter(self):
        self.filter.show()
        self.tabs.setCurrentIndex(TAB_ENTRIES)
        self.filter.setFocus()

    def action_undo(self):
        if not self.undo_stack:
            self.notify("Nothing to undo", timeout=2)
            return
        self.redo_stack.append(list(self.doc.items))
        self.doc.items = self.undo_stack.pop()
        self.changed()

    def action_redo(self):
        if not self.redo_stack:
            self.notify("Nothing to redo", timeout=2)
            return
        self.undo_stack.append(list(self.doc.items))
        self.doc.items = self.redo_stack.pop()
        self.changed()

    def save(self):
        if self.path.exists() and not self.backup_done:
            shutil.copy2(self.path, self.path.with_name(self.path.name + ".bak"))
        self.backup_done = True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(self.doc.dumps())
        os.replace(tmp, self.path)
        self.modified = False
        self.update_title()

    def action_save(self):
        try:
            self.save()
        except OSError as e:
            self.notify(f"Could not save: {e}", severity="error")
            return
        self.notify(f"Saved {self.path.name}", timeout=2)

    def action_new_book(self):
        book = NewBookDialog(self.doc.books(), parent=self).ask()
        if book:
            self.snapshot()
            i = self.doc.add_book(book)
            self.qa_book.setText(book)
            self.changed(i)
            self.validate_bar()
            self.notify(f"Book {book} created ({self.doc.items[i].section})", timeout=3)

    def apply(self, op):
        """Apply an undoable operation `op(doc) -> index to select` ; report a ValueError as an error."""
        self.snapshot()
        try:
            index = op(self.doc)
        except ValueError as e:
            self.doc.items = self.undo_stack.pop()
            self.notify(str(e), severity="error")
            return None
        self.changed(index)
        return index

    def action_sections(self):
        self.tabs.setCurrentIndex(TAB_SECTIONS)
        self.sections_pane.table.setFocus()

    def action_edit_section(self):
        item = self.sections.currentItem()
        if item is None:
            return
        i = item.data(Qt.ItemDataRole.UserRole)
        res = SectionDialog(self.doc, i, parent=self).ask()
        if res:
            self.apply(SectionDialog.operation(i, res, self.notify))

    def action_show_section(self):
        """Show in the Sections tab the section of the book whose parts (in the Topics) hold the current line, else the
        section holding it."""
        i = self.current_index()
        if i is None:
            return
        it, target = self.doc.items[i], None
        if isinstance(it, Entry):
            book = next((b for b, top in self.doc.chapters().items() if it.path[0] == top), None)
            if book is not None:
                target = next((k for k, t in self.doc.sections()
                               if Document.section_kind(t) == "book" and Document.section_book(t) == book), None)
        if target is None:
            target = next((k for k, _ in reversed(self.doc.sections()) if k <= i), None)
        if target is None:
            return
        self.action_sections()
        self.sections_pane.refresh_table(target)

    def action_course(self):
        info = CourseDialog(self.course, self.data_path, parent=self).ask()
        if info is not None:
            self.course = info
            try:
                info.save(self.data_path)
            except OSError as e:
                self.notify(f"Could not save {self.data_path}: {e}", severity="error")
                return
            self._preview_dirty = True
            self.refresh_all()
            self.notify(f"Course saved to {self.data_path.name}", timeout=2)

    def action_compile(self):
        if self._compiling:
            self.notify("Already compiling…", timeout=2)
            return
        try:
            self.save()
        except OSError as e:
            self.notify(f"Could not save: {e}", severity="error")
            return
        self.notify("Compiling the PDF…", timeout=2)
        self._compiling = True
        doc, course = self.doc.copy(), self.course

        def work():
            self.bridge.compiled.emit(compile_pdf(self.path, document=doc, course=course))
        threading.Thread(target=work, daemon=True).start()

    def compiled(self, result):
        self._compiling = False
        if result.ok and not result.warnings:
            self.notify(result.summary, timeout=4)
            if self.open_pdf:
                open_file(result.pdf)
            return
        if CompileReport(result, parent=self).ask() == "open":
            open_file(result.pdf)

    def action_help(self):
        HelpDialog(self).exec()

    def action_quit(self):
        self.close()

    def closeEvent(self, event):
        if not self.modified:
            event.accept()
            return
        box = QMessageBox(QMessageBox.Icon.Question, "Unsaved changes", "Save the index before quitting?",
                          QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                          QMessageBox.StandardButton.Cancel, self)
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        choice = box.exec()
        if choice == QMessageBox.StandardButton.Save:
            try:
                self.save()
            except OSError as e:
                self.notify(f"Could not save: {e}", severity="error")
                event.ignore()
                return
            event.accept()
        elif choice == QMessageBox.StandardButton.Discard:
            event.accept()
        else:
            event.ignore()


# --------------------------------------------------------------------------------------------------------------------
STYLE = """
#sidebar {{ border-right: 1px solid {border}; }}
#sidebar-title {{ color: {muted}; }}
#quickadd {{ background: {boost}; border-radius: 4px; }}
#qa-label {{ color: {accent}; font-weight: bold; padding-bottom: 6px; padding-right: 4px; }}
#caption, #muted {{ color: {muted}; }}
#qa-term:focus, #filter:focus {{ border: 1px solid {blue}; }}
QLineEdit[invalid="true"] {{ border: 1px solid {red}; }}
#suggestions {{ border: 1px solid {accent}; border-radius: 4px; }}
#table {{ selection-background-color: {cursor}; }}
#footer {{ background: {boost}; border-top: 1px solid {border}; }}
#toast {{ background: {toast}; border: 1px solid {border}; border-radius: 4px; padding: 8px 10px; }}
#dialog-title {{ color: {accent}; font-weight: bold; font-size: 14pt; }}
#primary {{ background: {accent}; color: black; font-weight: bold; padding: 4px 14px; }}
#danger {{ color: {red}; }}
"""


def stylesheet():
    c = colors()
    dark = is_dark()
    return STYLE.format(border="#3a3d44" if dark else "#c8cbd0", muted=c["dim"], accent=c["accent"], blue=c["blue"],
                        red=c["red"], boost="#24272d" if dark else "#eceef1",
                        cursor="#7a5520" if dark else "#f6c77d", toast="#2b2e35" if dark else "#ffffff")


def application():
    """The QApplication (created if needed), with the Fusion style and the stylesheet of the editor."""
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Course Index")
    app.setStyle(QStyleFactory.create("Fusion"))
    # the cursor of the lists in the accent color, like the TUI
    pal = app.palette()
    dark = is_dark(pal)
    pal.setColor(QPalette.ColorRole.Highlight, QColor("#7a5520" if dark else "#f6c77d"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff" if dark else "#000000"))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet())
    return app


def run(path, open_pdf=True):
    """Open the editor on the given index file and run the event loop."""
    app = application()
    win = IndexWindow(path, open_pdf=open_pdf)
    win.show()
    return app.exec()
