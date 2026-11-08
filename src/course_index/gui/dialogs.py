# -*- coding: UTF-8 -*-
"""Dialogs of the GUI: entry editor, new book, section, cross-reference, course metadata, build report, help ; and the
Sections pane."""
import re

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QColor, QKeySequence, QRegularExpressionValidator, QShortcut
from PySide6.QtWidgets import QAbstractItemView, QCheckBox, QComboBox, QDialog, QGridLayout, QHBoxLayout, \
                              QHeaderView, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, \
                              QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget
from rich.text import Text

from ..common import HELP, MAX_LEVELS, join_decorations, split_decorations
from ..course import CourseInfo
from ..idx import Document, Entry, Level, book_sort_key, normalize_title, page_error
from ..latex import ICONS, expand_shortcuts, plain, render
from .widgets import KeyLineEdit, colors, to_html

__all__ = ["CompileReport", "CourseDialog", "EntryDialog", "HelpDialog", "NewBookDialog", "SectionDialog",
           "SectionsPane", "XrefDialog", "book_error", "restrict"]

BOOK_CHARS, PAGE_CHARS = r"[0-9A-Za-z]*", r"[0-9\-]*"


def restrict(edit, pattern):
    """Accept only the characters matching the pattern in a line edit."""
    edit.setValidator(QRegularExpressionValidator(QRegularExpression(pattern), edit))
    return edit


def book_error(value, books, allow_empty=True):
    """Error of the book of a reference (None when valid): one of the books of the index (or empty when allowed)."""
    v = value.strip()
    if not v:
        return None if allow_empty else "the book is required"
    if v not in books:
        return f"book {v} does not exist yet (F3 creates a new book)"
    return None


class Dialog(QDialog):
    """Base dialog: a title, a body, an error line and buttons ; closed with Escape. Enter in a line edit validates
    (as the default button would), unless the dialog handles it."""
    def __init__(self, title, parent=None, width=720):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.layout_ = QVBoxLayout(self)
        head = QLabel(title)
        head.setObjectName("dialog-title")
        self.layout_.addWidget(head)
        self.body = QVBoxLayout()
        self.layout_.addLayout(self.body)
        self.error = QLabel()
        self.error.setObjectName("dialog-error")
        self.error.setWordWrap(True)
        self.error.hide()
        self.layout_.addWidget(self.error)
        self.buttons = QHBoxLayout()
        self.buttons.addStretch(1)
        self.layout_.addLayout(self.buttons)
        self.result_value = None

    def add_button(self, label, callback, primary=False, danger=False):
        b = QPushButton(label, self)
        b.setAutoDefault(False)
        b.setDefault(False)
        if primary:
            b.setObjectName("primary")
        elif danger:
            b.setObjectName("danger")
        b.clicked.connect(callback)
        self.buttons.addWidget(b)
        return b

    def notify(self, message, severity="error", **kwargs):
        c = colors()
        color = c["red"] if severity == "error" else c["yellow"] if severity == "warning" else c["green"]
        self.error.setText(f'<span style="color:{color}">{to_html(message, pre=False)}</span>')
        self.error.show()

    def finish(self, value):
        self.result_value = value
        self.accept()

    def ask(self):
        """Show the dialog and return its result (None when cancelled)."""
        return self.result_value if self.exec() == QDialog.DialogCode.Accepted else None

    def edit(self, value="", placeholder="", tip=None):
        e = KeyLineEdit(value, self)
        e.setPlaceholderText(placeholder)
        if tip:
            e.setToolTip(tip)
            e.setProperty("help", tip)
        e.returnPressed.connect(self.ok)
        return e

    def ok(self):
        raise NotImplementedError


# --------------------------------------------------------------------------------------------------------------------
class EntryDialog(Dialog):
    """Structured editor of an index entry, synchronized with its raw `\\indexentry` line."""
    def __init__(self, entry, title="Edit entry", code="", known=None, books=(), new=False, title_of=None, raw=None,
                 parent=None):
        """:param title_of: book whose title is the first level of the entry (then locked, edited in the Sections tab)
        :param raw:      malformed line to correct (the entry is then a best-effort reading of it)"""
        super().__init__(title, parent, 860)
        self.raw_text, self.raw_error = raw, None
        self.entry, self.original, self.code = entry, entry, code
        self.known = known or set()
        self.books, self.new = list(books), new
        self.title_of = title_of
        self.locked = (entry.path[0] if entry.levels else None) if title_of else None
        self._syncing = False
        e = entry
        base, icons, rating = split_decorations(e.levels[-1].text if e.levels else "")
        # levels: sort key and text
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        for col, head in enumerate(("Sort key", "Text (LaTeX; shortcuts: `code` **bold** *italic* :linux:)")):
            lab = QLabel(head)
            lab.setObjectName("muted")
            grid.addWidget(lab, 0, col)
        self.keys, self.texts = [], []
        visible = max(len(e.levels) + 1, 2)
        for i in range(MAX_LEVELS):
            lv = e.levels[i] if i < len(e.levels) else Level("")
            text = base if i == len(e.levels) - 1 else lv.text
            k = self.edit(lv.key or "", "auto")
            k.setFixedWidth(160)
            t = self.edit(text, ["Term", "Sub-term", "Sub-sub-term", "Level 4"][i])
            if i == 0 and self.locked:
                for w in (k, t):
                    w.setEnabled(False)
                    w.setToolTip(self.lock_message[0].upper() + self.lock_message[1:])
            k.setVisible(i < visible)
            t.setVisible(i < visible)
            k.textChanged.connect(self._fields_changed)
            t.textChanged.connect(lambda value, i=i: self._text_changed(i, value))
            grid.addWidget(k, i + 1, 0)
            grid.addWidget(t, i + 1, 1)
            self.keys.append(k)
            self.texts.append(t)
        self.body.addLayout(grid)
        # book, pages and other encapsulation
        row = QHBoxLayout()
        row.addWidget(QLabel("Book"))
        tip = "Existing books: " + (", ".join(self.books) or "none (F3 creates one)")
        self.book = restrict(self.edit(e.book or "", tip=tip), BOOK_CHARS)
        self.book.setFixedWidth(90)
        row.addWidget(self.book)
        row.addWidget(QLabel("Pages"))
        self.page = restrict(self.edit(e.page), PAGE_CHARS)
        self.page.setFixedWidth(90)
        row.addWidget(self.page)
        row.addWidget(QLabel("Other encap."))
        self.rest = self.edit(e.encap_rest or "", "e.g. comment, \\lab")
        row.addWidget(self.rest, 1)
        self.body.addLayout(row)
        for w in (self.book, self.page, self.rest):
            w.textChanged.connect(self._fields_changed)
        # rating and commented out
        row = QHBoxLayout()
        row.addWidget(QLabel("Rating"))
        self.rating = QComboBox(self)
        for i in range(6):
            self.rating.addItem(("★" * i) if i else "none", i)
        self.rating.setCurrentIndex(rating)
        self.rating.currentIndexChanged.connect(self._fields_changed)
        row.addWidget(self.rating)
        self.disabled = QCheckBox("Commented out (%)", self)
        self.disabled.setChecked(e.disabled)
        self.disabled.toggled.connect(self._fields_changed)
        row.addSpacing(16)
        row.addWidget(self.disabled)
        row.addStretch(1)
        self.body.addLayout(row)
        # icons
        self.icons = QListWidget(self)
        self.icons.setFlow(QListWidget.Flow.LeftToRight)
        self.icons.setWrapping(True)
        self.icons.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.icons.setFixedHeight(7 * self.fontMetrics().height())
        for k, emoji in ICONS.items():
            it = QListWidgetItem(f"{emoji} \\{k}")
            it.setData(Qt.ItemDataRole.UserRole, k)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if k in icons else Qt.CheckState.Unchecked)
            self.icons.addItem(it)
        self.icons.itemChanged.connect(self._fields_changed)
        self.body.addWidget(self.icons)
        # preview and raw line
        self.preview = QLabel(self)
        self.preview.setWordWrap(True)
        self.preview.setTextFormat(Qt.TextFormat.RichText)
        self.preview.setMinimumHeight(2 * self.fontMetrics().height())
        self.body.addWidget(self.preview)
        self.raw = self.edit(self.raw_text if self.raw_text is not None else e.to_line(), "\\indexentry{...}{...}")
        self.raw.setObjectName("raw")
        self.raw.textEdited.connect(self._raw_changed)
        self.body.addWidget(self.raw)
        self.add_button("Save (Ctrl+S)", self.ok, primary=True)
        self.add_button("Cancel (Esc)", self.reject)
        QShortcut(QKeySequence("Ctrl+S"), self, self.ok)
        (self.texts[1] if self.locked else self.texts[0]).setFocus()
        if self.raw_text is not None and Entry.parse(self.raw_text) is None:
            self.raw_error = "malformed line (unbalanced braces?): correct it here or in the fields"
        self._update_preview(self.raw_error)

    @property
    def lock_message(self):
        return f"the first level is the title of book {self.title_of}: edit it in the Sections tab (F4, e)"

    def _selected_icons(self):
        return [self.icons.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.icons.count())
                if self.icons.item(i).checkState() == Qt.CheckState.Checked]

    # ------------------------------------------------- synchronization ----------------------------------------------
    def _from_fields(self):
        levels = []
        icons, rating = self._selected_icons(), self.rating.currentData() or 0
        texts = [t.text() for t in self.texts]
        last = max([i for i, t in enumerate(texts) if t != ""] + [0])
        for i in range(last + 1):
            key, text = self.keys[i].text(), texts[i]
            if i == last:
                text = join_decorations(text, icons, rating)
            levels.append(Level(text, key if key != "" else None))
        book, rest = self.book.text().strip(), self.rest.text()
        encap = (f"book{{{book}}}" + rest) if book else (rest if rest != "" else None)
        return Entry(tuple(levels), self.page.text(), encap, self.disabled.isChecked())

    def _to_fields(self, e):
        self._syncing = True
        try:
            base, icons, rating = split_decorations(e.levels[-1].text)
            for i in range(MAX_LEVELS):
                lv = e.levels[i] if i < len(e.levels) else Level("")
                self.keys[i].setText(lv.key or "")
                self.texts[i].setText(base if i == len(e.levels) - 1 else lv.text)
                if i <= len(e.levels):
                    self.keys[i].show()
                    self.texts[i].show()
            self.book.setText(e.book or "")
            self.page.setText(e.page)
            self.rest.setText(e.encap_rest or "")
            self.disabled.setChecked(e.disabled)
            self.rating.setCurrentIndex(rating)
            for i in range(self.icons.count()):
                it = self.icons.item(i)
                it.setCheckState(Qt.CheckState.Checked if it.data(Qt.ItemDataRole.UserRole) in icons else
                                 Qt.CheckState.Unchecked)
        finally:
            self._syncing = False

    def _update_preview(self, error=None):
        e = self.entry
        t = Text()
        if error is None and not e.is_valid:
            error = "malformed line: unbalanced braces in a field?"
        if error:
            t.append(f"⚠ {error}", "bold red")
        else:
            t.append_text(Text(" › ").join(render(lv.text) for lv in e.levels))
            if e.kind == "ref":
                t.append("  …  ", "dim")
                t.append(f"{self.code}.{e.book}–{e.page}" if e.book else e.page, "green")
            else:
                t.append(f"   ({e.kind})", "dim italic")
            cmds = set(re.findall(r"\\([A-Za-z]+)", e.key)) - self.known if self.known else set()
            if cmds:
                t.append("   unknown: " + " ".join("\\" + c for c in sorted(cmds)), "yellow")
            if self.locked:
                t.append(f"\n🔒 first level = title of book {self.title_of}, edited in the Sections tab (F4, e)", "dim")
        self.preview.setText(to_html(t, pre=False))
        # validation of the book and page (as typed)
        if e.kind == "ref":
            self.book.set_invalid(book_error(self.book.text(), self._allowed_books()))
            orig = None if self.new else self.original.page
            page = self.page.text()
            self.page.set_invalid(None if orig is not None and page.strip() == orig.strip() else page_error(page))
        else:
            self.book.set_invalid(None)
            self.page.set_invalid(None)

    def _text_changed(self, i, value):
        # reveal the next level when this one is filled
        if value and i + 1 < MAX_LEVELS:
            self.keys[i + 1].show()
            self.texts[i + 1].show()
        self._fields_changed()

    def _fields_changed(self, *args):
        if self._syncing:
            return
        new = self._from_fields()
        if new != self.entry:
            self.entry = new
            if not self.raw.hasFocus():
                self.raw.setText(new.to_line())
                self.raw_error = None
            self._update_preview(self.raw_error)

    def _raw_changed(self, value):
        parsed = Entry.parse(value.strip())
        if parsed is None:
            self.raw_error = "not a valid \\indexentry{...}{...} line (unbalanced braces?)"
            self._update_preview(self.raw_error)
            return
        self.raw_error = None
        parsed = parsed.evolve()
        if self.locked and parsed.path[0] != self.locked:
            self._update_preview(self.lock_message)
            return
        if parsed != self.entry:
            self.entry = parsed
            self._to_fields(parsed)
        self._update_preview()

    def _allowed_books(self):
        # the book of the entry being edited exists (it comes from the file)
        return self.books + ([self.original.book] if self.original.book and not self.new else [])

    def ok(self):
        e = self.entry
        if self.raw_error or not e.is_valid:
            self.notify("The line is still malformed: " + (self.raw_error or "unbalanced braces in a field?"))
            return
        if not e.levels or e.levels[0].text.strip() == "":
            self.notify("The term cannot be empty")
            return
        if self.locked and e.path[0] != self.locked:
            self.notify(self.lock_message[0].upper() + self.lock_message[1:])
            return
        if e.page.strip() == "":
            self.notify("The page cannot be empty (use 0 for entries without page)")
            return
        if e.kind == "ref":
            orig = None if self.new else self.original.page
            page = self.page.text()
            for name, w, err in (("Book", self.book, book_error(self.book.text(), self._allowed_books())),
                                 ("Page", self.page, None if orig is not None and page.strip() == orig.strip() else
                                  page_error(page))):
                if err:
                    self.notify(f"{name}: {err}")
                    w.setFocus()
                    return
        orig = self.original.levels
        # expand the shortcuts only in the levels that were changed (existing LaTeX is kept as is)
        levels = tuple(lv if lv.text.strip() == "" or i < len(orig) and lv.text == orig[i].text else
                       Level(expand_shortcuts(lv.text), lv.key) for i, lv in enumerate(e.levels))
        self.finish(e.evolve(levels=levels))


# --------------------------------------------------------------------------------------------------------------------
class NewBookDialog(Dialog):
    """Create a new book (and its section in the file)."""
    def __init__(self, books, parent=None):
        super().__init__("New book", parent, 480)
        self.books = list(books)
        nums = [int(b) for b in self.books if b.isdigit()]
        suggestion = str(max(nums) + 1) if nums else ("1" if not self.books else "")
        self.body.addWidget(QLabel("Existing books: " + (", ".join(sorted(self.books, key=book_sort_key)) or "none")))
        self.body.addWidget(QLabel("Book (a number, or letters such as W for a workbook)"))
        self.book = restrict(self.edit(suggestion), BOOK_CHARS)
        self.book.textChanged.connect(lambda v: self.book.set_invalid(self._error(v) if v.strip() else None))
        self.body.addWidget(self.book)
        self.add_button("Create", self.ok, primary=True)
        self.add_button("Cancel (Esc)", self.reject)
        self.book.setFocus()
        self.book.selectAll()

    def _error(self, value):
        v = value.strip()
        if not v:
            return "the book is required"
        if v in self.books:
            return f"book {v} already exists"

    def ok(self):
        err = self._error(self.book.text())
        if err:
            self.notify(err)
            return
        self.finish(self.book.text().strip())


# --------------------------------------------------------------------------------------------------------------------
class SectionDialog(Dialog):
    """Title, book and chapter of a section (new one when index is None)."""
    def __init__(self, doc, index=None, after=None, parent=None):
        super().__init__("Edit section" if index is not None else "New section", parent, 760)
        self.doc, self.index, self.after = doc, index, after
        title = doc.items[index].section if index is not None else ""
        self.old_title = title
        self.old_book = Document.section_book(title) if Document.section_kind(title) == "book" else None
        self._prev_book = self.old_book or ""
        # the chapter of the book: its group of parts in the Topics section, whose bold title is the book's title
        self.chapter = doc.chapters().get(self.old_book) if self.old_book else None
        self.old_chapter = Document.chapter_title(self.chapter) if self.chapter else None
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        self.title = self.edit(self.old_title, "e.g. FIRST BOOK SECTION, SANS 504.1 SECTION, TOOLS")
        self.book = restrict(self.edit(self.old_book or "", "empty: not a book section (e.g. tools, labs)"),
                             BOOK_CHARS)
        grid.addWidget(QLabel("Index section title"), 0, 0)
        grid.addWidget(self.title, 0, 1)
        grid.addWidget(QLabel("Book"), 1, 0)
        grid.addWidget(self.book, 1, 1)
        self.chapter_edit = None
        if self.old_chapter is not None:
            self.chapter_edit = self.edit(self.old_chapter, tip="Title of the book: the bold first level of its parts "
                                          "in the Topics section (LaTeX, e.g. Recon \\& Mapping)")
            grid.addWidget(QLabel("Title"), 2, 0)
            grid.addWidget(self.chapter_edit, 2, 1)
            self.chapter_edit.textChanged.connect(self._update)
        self.body.addLayout(grid)
        n = self.doc.book_usage(self.old_book) if self.old_book else 0
        self.renumber = QCheckBox(f"Also change the book of the {n} entries using book {self.old_book}", self)
        self.renumber.setChecked(True)
        self.renumber.setVisible(bool(self.old_book and n))
        self.renumber.toggled.connect(self._update)
        self.body.addWidget(self.renumber)
        self.preview = QLabel(self)
        self.preview.setWordWrap(True)
        self.preview.setMinimumHeight(2 * self.fontMetrics().height())
        self.body.addWidget(self.preview)
        self.title.textChanged.connect(self._update)
        self.book.textChanged.connect(self._book_changed)
        self.add_button("Save", self.ok, primary=True)
        self.add_button("Cancel (Esc)", self.reject)
        # the title of the book is what is usually edited ; the index section title otherwise
        (self.chapter_edit or self.title).setFocus()
        self._update()

    @staticmethod
    def operation(index, result, notify):
        """Operation applying the result of the dialog to the section whose header is at index."""
        title, book, renumber, chapter = result

        def op(doc):
            if chapter is not None:
                doc.rename_chapter(doc.chapters()[Document.section_book(doc.items[index].section)], chapter)
            n = doc.set_section(index, title, book, renumber)
            if n:
                notify(f"{n} entries renumbered", timeout=3)
            return index
        return op

    def _values(self):
        return self.title.text(), self.book.text().strip()

    def _chapter(self):
        """New title of the book's chapter, None when it is unchanged (or the book has no chapter)."""
        if self.old_chapter is None:
            return None
        value = " ".join(self.chapter_edit.text().split())
        return None if value == self.old_chapter else value

    def _check_chapter(self, chapter):
        if chapter is not None:
            self.doc.copy().rename_chapter(self.chapter, chapter)

    def _update(self, *args):
        title, book = self._values()
        t = Text()
        try:
            final = self.doc._check_section(self.index, title, book)
        except ValueError as e:
            t.append(f"⚠ {e}", "bold red")
        else:
            kind = Document.section_kind(final)
            t.append(final, "bold magenta")
            t.append(f"   {kind}" + (f" · book {Document.section_book(final)}" if kind == "book" else ""), "dim")
            if self.old_book and kind == "book" and Document.section_book(final) != self.old_book and \
               self.renumber.isChecked() and self.doc.book_usage(self.old_book):
                t.append(f"\n|book{{{self.old_book}}} → |book{{{Document.section_book(final)}}} in "
                         f"{self.doc.book_usage(self.old_book)} entries", "yellow")
        chapter = self._chapter()
        try:
            self._check_chapter(chapter)
        except ValueError as e:
            t.append(f"\n⚠ {e}", "bold red")
        else:
            if chapter is not None:
                n = len([1 for _, e in self.doc.entries(False) if e.path[0] == self.chapter])
                t.append("\ntitle: ", "yellow")
                t.append(render(f"\\textbf{{{chapter}}}"))
                t.append(f" in {n} entries of the Topics", "yellow")
        if self.index is not None:
            t.append(f"\n{self.doc.section_entries(self.index)} entries in this section", "dim")
        self.preview.setText(to_html(t, pre=False))

    def _book_changed(self, value):
        if value.strip():
            # adapt the title to the book (e.g. FIRST BOOK SECTION -> SECOND BOOK SECTION)
            try:
                retitled = Document.retitle(self.title.text() or "BOOK", self._prev_book or None, value.strip())
            except ValueError:
                pass
            else:
                if retitled != self.title.text():
                    self.title.setText(retitled)
            self._prev_book = value.strip()
        self._update()

    def ok(self):
        title, book = self._values()
        try:
            self.doc._check_section(self.index, title, book)
            normalize_title(title)
            self._check_chapter(self._chapter())
        except ValueError as e:
            self.notify(str(e))
            return
        self.finish((title, book or None, self.renumber.isChecked(), self._chapter()))


# --------------------------------------------------------------------------------------------------------------------
class SectionsPane(QWidget):
    """Manager of the sections of the file (the books are sections too), shown in the Sections tab."""
    COLUMNS = ("Index Section Title", "Kind", "Book", "Title", "Entries", "Book used by")
    KEYS = [("e", "Edit", "edit"), ("n", "New", "new"), ("d", "Delete", "delete"), ("Alt+↑", "Move up", "up"),
            ("Alt+↓", "Move down", "down"), ("g", "Go to", "goto"), ("t", "Go to title", "chapter")]

    def __init__(self, window):
        super().__init__(window)
        self.window_ = window
        self.heads = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        help_ = QLabel("A book section gives its book to new references (F3 also creates one). e/Enter: edit (section "
                       "title, book, title) · n: new · d: delete the header · Alt+↑/↓: move · g: go to the entries · t: "
                       "go to the book's title (its parts in the Topics)")
        help_.setObjectName("muted")
        help_.setWordWrap(True)
        lay.addWidget(help_)
        self.table = QTableWidget(0, len(self.COLUMNS), self)
        self.table.setObjectName("sections-table")
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setTabKeyNavigation(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 6)
        h = self.table.horizontalHeader()
        h.setHighlightSections(False)
        for k in range(len(self.COLUMNS)):
            h.setSectionResizeMode(k, QHeaderView.ResizeMode.Stretch if k == 3 else
                                   QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemActivated.connect(lambda *_: self.edit())
        self.table.keyPressEvent = self._key
        lay.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        for label, action, danger in (("New (n)", self.new, False), ("Edit (e)", self.edit, False),
                                      ("Up", lambda: self.move(-1), False), ("Down", lambda: self.move(1), False),
                                      ("Delete (d)", self.delete, True), ("Go to (g)", self.goto, False)):
            b = QPushButton(label, self)
            b.setAutoDefault(False)
            if danger:
                b.setObjectName("danger")
            b.clicked.connect(lambda checked=False, a=action: (a(), self.table.setFocus()))
            buttons.addWidget(b)
        buttons.addStretch(1)
        lay.addLayout(buttons)

    def action(self, name):
        return {"up": lambda: self.move(-1), "down": lambda: self.move(1)}.get(name) or getattr(self, name)

    def _key(self, event):
        key, mods, text = event.key(), event.modifiers(), event.text()
        alt = mods & Qt.KeyboardModifier.AltModifier or \
            mods & Qt.KeyboardModifier.ControlModifier and mods & Qt.KeyboardModifier.ShiftModifier
        if alt and key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.move(-1 if key == Qt.Key.Key_Up else 1)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) or text == "e":
            self.edit()
        elif text == "n":
            self.new()
        elif text == "d" or key == Qt.Key.Key_Delete:
            self.delete()
        elif text == "g":
            self.goto()
        elif text == "t":
            self.chapter()
        else:
            QTableWidget.keyPressEvent(self.table, event)

    @property
    def doc(self):
        return self.window_.doc

    def refresh_table(self, select=None):
        """Rebuild the list (after any change of the document), keeping the cursor or moving it to a header."""
        t = self.table
        row = t.currentRow()
        self.heads = []
        chapters = self.doc.chapters()
        c = colors()
        t.setRowCount(0)
        for i, title in self.doc.sections():
            kind = Document.section_kind(title)
            book = Document.section_book(title) if kind == "book" else None
            chapter = plain(Document.chapter_title(chapters[book])) if book in chapters else ""
            cells = [title, kind, book or "", chapter, str(self.doc.section_entries(i)),
                     f"{self.doc.book_usage(book)} entries" if book else ""]
            r = t.rowCount()
            t.insertRow(r)
            for k, value in enumerate(cells):
                it = QTableWidgetItem(value)
                if k == 0 and kind == "book":
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                    it.setForeground(QColor(c["magenta"]))
                if k == 4:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                t.setItem(r, k, it)
            self.heads.append(i)
        if select is not None and select in self.heads:
            row = self.heads.index(select)
        if self.heads:
            t.setCurrentCell(min(max(row, 0), len(self.heads) - 1), 0)

    def current(self):
        if not self.heads:
            return None
        return self.heads[min(max(self.table.currentRow(), 0), len(self.heads) - 1)]

    def apply(self, op):
        """Apply an operation on the document through the window (undoable) ; op returns the index to select."""
        res = self.window_.apply(op)
        if res is not None:
            self.refresh_table(res)

    def edit(self):
        i = self.current()
        if i is None:
            return
        res = SectionDialog(self.doc, i, parent=self.window_).ask()
        if res:
            self.apply(SectionDialog.operation(i, res, self.window_.notify))

    def new(self):
        after = self.current()
        res = SectionDialog(self.doc, None, after, parent=self.window_).ask()
        if res:
            title, book, _, _ = res
            self.apply(lambda doc: doc.add_section(title, book, after))

    def delete(self):
        i = self.current()
        if i is not None:
            self.apply(lambda doc: (doc.delete_section(i), max(0, i - 1))[1])

    def move(self, step):
        i = self.current()
        if i is not None:
            self.apply(lambda doc: doc.move_section(i, step))

    def goto(self):
        i = self.current()
        if i is not None:
            self.window_.goto_item(i)

    def chapter(self):
        i = self.current()
        if i is None:
            return
        book = Document.section_book(self.doc.items[i].section)
        top = self.doc.chapters().get(book) if Document.section_kind(self.doc.items[i].section) == "book" else None
        if not top:
            self.window_.notify("This section has no title: no group of the Topics section holds the parts of its book "
                                "only", severity="warning")
            return
        self.window_.goto_item(next(k for k, e in self.doc.entries() if e.path[0] == top))


# --------------------------------------------------------------------------------------------------------------------
class XrefDialog(Dialog):
    """Cross-reference: `source -> target`."""
    def __init__(self, source="", target="", parent=None):
        super().__init__("Add a cross-reference", parent, 600)
        self.body.addWidget(QLabel("See (alias, e.g. K8s or IaaS!Testing Policies)"))
        self.source = KeyLineEdit(source, self)
        self.source.returnPressed.connect(lambda: self.target.setFocus())
        self.body.addWidget(self.source)
        self.body.addWidget(QLabel("→ refers to (e.g. Kubernetes)"))
        self.target = self.edit(target)
        self.body.addWidget(self.target)
        self.add_button("Add", self.ok, primary=True)
        self.add_button("Cancel (Esc)", self.reject)
        self.source.setFocus()

    def ok(self):
        s, t = self.source.text().strip(), self.target.text().strip()
        if not s or not t:
            self.notify("Both terms are required")
            return
        self.finish((expand_shortcuts(s), expand_shortcuts(t)))


class CourseDialog(Dialog):
    """Course metadata (written to the data file of the index)."""
    FIELDS = [("code", "Code", "e.g. SEC504 or 504 (prefix of the page numbers)"),
              ("title", "Title", "\\coursecode may be used"), ("date", "Date", "e.g. 05/2025"),
              ("version", "Version", "e.g. v1.2"), ("author", "Author", "optional")]

    def __init__(self, info, path, parent=None):
        super().__init__("Course", parent, 680)
        saved = QLabel(f"Saved to {path}")
        saved.setObjectName("muted")
        self.body.addWidget(saved)
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        self.fields = {}
        for row, (attr, label, ph) in enumerate(self.FIELDS):
            grid.addWidget(QLabel(label), row, 0)
            self.fields[attr] = self.edit(getattr(info, attr), ph)
            grid.addWidget(self.fields[attr], row, 1)
        self.body.addLayout(grid)
        self.add_button("Save", self.ok, primary=True)
        self.add_button("Cancel (Esc)", self.reject)
        self.fields["code"].setFocus()

    def ok(self):
        self.finish(CourseInfo(**{a: w.text() for a, w in self.fields.items()}))


class CompileReport(Dialog):
    """Report of a compilation (errors, warnings and log) ; returns "open" to open the PDF."""
    def __init__(self, result, parent=None):
        super().__init__("PDF compiled" if result.ok else "Compilation failed", parent, 900)
        self.result_ = result
        self.resize(1000, 640)
        t = Text()
        t.append(result.summary + "\n", "green" if result.ok else "bold red")
        for e in result.errors:
            t.append(f"✖ {e}\n", "red")
        for w in result.warnings:
            t.append(f"⚠ {w}\n", "yellow")
        report = QLabel(to_html(t, pre=False))
        report.setWordWrap(True)
        report.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.addWidget(report)
        log = QPlainTextEdit(result.log or "(no log)", self)
        log.setReadOnly(True)
        log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.body.addWidget(log, 1)
        if result.ok:
            self.add_button("Open PDF (o)", lambda: self.finish("open"), primary=True)
            QShortcut(QKeySequence("O"), self, lambda: self.finish("open"))
        self.add_button("Close (Esc)", self.reject)


class HelpDialog(Dialog):
    """Help (Markdown)."""
    def __init__(self, parent=None):
        super().__init__("Help", parent, 900)
        self.resize(960, 760)
        view = QTextBrowser(self)
        view.setOpenExternalLinks(True)
        view.setMarkdown(HELP.strip())
        self.body.addWidget(view, 1)
        self.add_button("Close (Esc)", self.reject)
        for key in ("F1", "Q"):
            QShortcut(QKeySequence(key), self, self.reject)
