# -*- coding: UTF-8 -*-
"""Textual application for editing a course index."""
import os
import re
import shutil
from pathlib import Path

from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Input, Label, OptionList, Static, TabbedContent, TabPane, Tree
from textual.widgets.option_list import Option

from ..common import KIND_MARKS, SKELETON  # noqa: F401
from ..compiler import compile_pdf, open_file, template_dir
from ..course import CourseInfo, data_file_for
from ..idx import Document, Entry, Level, Raw, _split, page_error, page_sort_key
from ..latex import auto_sort_key, expand_shortcuts, known_commands, plain, render
from ..preview import build, format_pages
from .screens import BookValidator, CompileReport, ConfirmQuit, CourseDialog, EntryDialog, HelpScreen, \
                     NewBookDialog, PageValidator, SectionDialog, SectionsPane, XrefDialog
from .widgets import EntryList

__all__ = ["IndexApp"]

MAX_UNDO = 300


class EntryTable(EntryList):
    """Table of the lines of the index file."""
    BINDINGS = [
        Binding("e", "app.edit", "Edit"),
        Binding("n", "app.new", "New"),
        Binding("a", "app.focus_add", "Add"),
        Binding("c", "app.duplicate", "Copy", show=False),
        Binding("d,delete", "app.delete", "Delete"),
        Binding("space", "app.toggle", "Comment", show=False),
        Binding("b", "app.spacer", "Blank", show=False),
        Binding("p", "app.pagebreak", "Page break", show=False),
        Binding("x", "app.xref", "Xref"),
        Binding("s", "app.show_section", "Section", show=False),
        Binding("alt+up,ctrl+shift+up", "app.move(-1)", "Move up", show=False),
        Binding("alt+down,ctrl+shift+down", "app.move(1)", "Move down", show=False),
        Binding("slash", "app.filter", "Filter"),
        Binding("right", "app.fold(True)", "Expand", show=False),
        Binding("left", "app.fold(False)", "Collapse", show=False),
        Binding("plus", "app.fold_all(True)", "Expand all", show=False),
        Binding("minus", "app.fold_all(False)", "Collapse all", show=False),
        Binding("question_mark", "app.help", "Help", show=False),
    ]

    def on_click(self, event):
        # a click on the caret of a section header expands or collapses it ; otherwise, Textual calls the handler of
        # EntryList by itself (calling it here too would handle a double click twice, opening two editors)
        row = event.y + self.scroll_offset.y - 1
        if 0 <= row < len(self.rows) and event.x < CARET_X and self.app.is_header_row(row):
            self.move_cursor(row)
            self.app.action_fold(None)
            event.prevent_default()
            event.stop()


CARET_X = 10  # the Line column and the caret of a section header


class TermInput(Input):
    """Input of the quick-add bar, driving the suggestions list."""
    BINDINGS = [
        Binding("tab", "app.accept_suggestion", "Complete", show=False, priority=True),
        Binding("down", "app.suggestion(1)", show=False),
        Binding("up", "app.suggestion(-1)", show=False),
        Binding("escape", "app.close_suggestions", show=False),
    ]


class SectionList(OptionList):
    """Sections of the sidebar."""
    BINDINGS = [Binding("e", "app.edit_section", "Edit section")]


class QuickAdd(Horizontal):
    BINDINGS = [
        Binding("ctrl+up,pageup", "app.page(1)", "Page +1"),
        Binding("ctrl+down,pagedown", "app.page(-1)", "Page −1"),
        Binding("escape", "app.focus_table", "Back", show=False),
    ]


class IndexApp(App):
    """Editor of an `.idx` file of the LaTeX course index template."""
    CSS_PATH = "app.tcss"
    TITLE = "Course Index"
    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("f5", "compile", "PDF"),
        Binding("f2", "course", "Course"),
        Binding("f3", "new_book", "New book"),
        Binding("f4", "sections", "Sections"),
        Binding("ctrl+z", "undo", "Undo"),
        Binding("ctrl+y", "redo", "Redo", show=False),
        Binding("ctrl+f", "filter", "Filter", show=False),
        Binding("f1", "help", "Help"),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

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
        books = self.doc.books()
        self.default_book = books[0] if books else ""

    # ------------------------------------------------------ layout --------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield Label(Text.assemble("Course", (" · F2 to edit", "dim not bold")), id="course-title",
                            classes="sidebar-title")
                yield Static("", id="course-info")
                yield Label("Sections", classes="sidebar-title")
                yield SectionList(id="sections")
            with TabbedContent(id="tabs"):
                with TabPane("Entries", id="tab-entries"):
                    with QuickAdd(id="quickadd"):
                        yield Label("Add", id="qa-label")
                        yield Input(self.default_book, placeholder="F3: new", id="qa-book", restrict=r"[0-9A-Za-z]*",
                                    tooltip="Book (e.g. 1, 2, W); F3 creates a new book",
                                    validators=[BookValidator(self.doc.books, allow_empty=True)])
                        yield Input("", placeholder="page", id="qa-page", restrict=r"[0-9\-]*",
                                    tooltip="Page or range (e.g. 45 or 45-47)", validators=[PageValidator()])
                        yield TermInput(placeholder="Term!Sub-term, then Enter  ·  shortcuts: `code` **bold** "
                                                    ":linux:", id="qa-term")
                    yield OptionList(id="suggestions", classes="hidden")
                    yield Input(placeholder="Filter: text, book:2, page:45 (Esc to clear)", id="filter",
                                classes="hidden")
                    yield EntryTable(id="table")
                with TabPane("Sections", id="tab-sections"):
                    yield SectionsPane(id="sections-pane")
                with TabPane("Preview", id="tab-preview"):
                    yield Tree("Index", id="preview")
                with TabPane("Problems", id="tab-problems"):
                    yield DataTable(id="problems", cursor_type="row", zebra_stripes=True)
        yield Footer()

    @property
    def main(self):
        """The main screen (dialogs may be open on top of it while the document changes)."""
        return self.screen_stack[0]

    def on_mount(self):
        table = self.main.query_one("#table", EntryTable)
        for wid, title in [("#qa-book", "Book"), ("#qa-page", "Page"), ("#qa-term", "Term (Tab: complete)")]:
            self.main.query_one(wid).border_title = title
        problems = self.main.query_one("#problems", DataTable)
        problems.add_columns("Line", "Level", "Problem")
        self.refresh_all()
        table.focus()
        if self.is_new:
            self.notify(f"New index: {self.path.name} will be created when saving (Ctrl+S)")
        if not self.doc.books():
            self.notify("No book yet: press F3 to create the first one", timeout=6)

    # ------------------------------------------------------ helpers -------------------------------------------------
    def check_action(self, action, parameters):
        # the actions on the document are disabled while a dialog is open
        if action in ("save", "compile", "course", "new_book", "sections", "edit_section", "undo", "redo", "filter",
                      "help") and \
           len(self.screen_stack) > 1:
            return False
        return True

    @property
    def table(self):
        return self.main.query_one("#table", EntryTable)

    def current_index(self):
        """Index of the item under the cursor of the table, if any."""
        t = self.table
        if not self.row_items or t.cursor_row is None or t.cursor_row >= len(self.row_items):
            return None
        return self.row_items[t.cursor_row]

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
        self.title = f"Course Index — {self.course.display_title}"
        self.sub_title = f"{self.path}{' ●' if self.modified else ''}"
        # read-only summary of the course metadata (edited with F2)
        grid = Table.grid(padding=(0, 1))
        grid.add_column(style="dim", no_wrap=True)
        grid.add_column(overflow="fold")
        c = self.course
        for label, value, style in [("Code", c.code, "bold"), ("Title", c.display_title, "bold"), ("Date", c.date, ""),
                                    ("Version", c.version, ""), ("Author", c.author, "")]:
            value = plain(value)
            grid.add_row(label, Text(value, style) if value else Text("—", "dim"))
        self.main.query_one("#course-info", Static).update(grid)

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
        table = self.table
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
        table.set_rows(rows)
        self.refresh_sections()
        self.main.query_one("#sections-pane", SectionsPane).refresh_table()
        self.update_title()
        if keep is not None:
            self.select_item(keep)
        if self.main.query_one("#tabs", TabbedContent).active == "tab-preview":
            self.refresh_preview()
        if check:
            self.run_check(list(self.doc.items))

    @work(thread=True, exclusive=True, group="check")
    def run_check(self, items):
        doc = Document(items)
        problems = doc.check(self.commands)
        self.call_from_thread(self.checked, items, problems)

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
        self.table.move_cursor(row=row, animate=False, center=True)

    def refresh_sections(self):
        ol = self.main.query_one("#sections", OptionList)
        hl = ol.highlighted
        ol.clear_options()
        secs = self.doc.sections()
        bounds = [i for i, _ in secs] + [len(self.doc.items)]
        counts = []
        for n, (i, title) in enumerate(secs):
            counts.append(sum(1 for j in range(i, bounds[n + 1]) if isinstance(self.doc.items[j], Entry)))
        ol.add_options([Option(Text.assemble((t.replace(" SECTION", "").title(), ""), (f"  {c}", "dim")), id=str(i))
                        for (i, t), c in zip(secs, counts)])
        if hl is not None and hl < len(secs):
            ol.highlighted = hl

    def refresh_problems(self, lines):
        pt = self.main.query_one("#problems", DataTable)
        pt.clear()
        pt.add_rows([(Text(str(lines[p.index]), "dim"), Text(p.severity, "red" if p.severity == "error" else "yellow"),
                      p.message) for p in self.problems])
        n = len(self.problems)
        self.main.query_one("#tabs", TabbedContent).get_tab("tab-problems").label = f"Problems ({n})" if n else "Problems"

    def refresh_preview(self):
        if not self._preview_dirty:
            return
        self._preview_dirty = False
        tree = self.main.query_one("#preview", Tree)
        tree.clear()
        tree.root.set_label(Text(self.course.display_title, "bold"))
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
            first = node.items[0] if node.items else None
            if node.children:
                branch = parent.add(label, data=first, expand=True)
                for child in node.sorted_children():
                    add(branch, child)
            else:
                parent.add_leaf(label, data=first)

        for title, nodes in build(self.doc):
            group = tree.root.add(Text(title, "bold magenta"), expand=True)
            for node in nodes:
                add(group, node)
        tree.root.expand()

    # ------------------------------------------------------ events --------------------------------------------------
    @on(TabbedContent.TabActivated)
    def tab_activated(self, event):
        if event.pane.id == "tab-preview":
            self.refresh_preview()

    @on(EntryList.Selected, "#table")
    def row_selected(self, event):
        self.action_edit()

    @on(DataTable.RowSelected, "#problems")
    def problem_selected(self, event):
        if event.cursor_row < len(self.problems):
            self.goto_item(self.problems[event.cursor_row].index)

    @on(Tree.NodeSelected, "#preview")
    def preview_selected(self, event):
        if event.node.data is not None:
            self.goto_item(event.node.data)

    @on(OptionList.OptionSelected, "#sections")
    def section_selected(self, event):
        i = int(event.option.id)
        self.goto_item(i)
        book = Document.section_book(self.doc.items[i].section)
        if book:
            self.main.query_one("#qa-book", Input).value = book

    def goto_item(self, index):
        if self.filter_text:
            self.filter_text = ""
            self.main.query_one("#filter", Input).value = ""
            self.main.query_one("#filter").add_class("hidden")
            self.refresh_all(index)
        self.main.query_one("#tabs", TabbedContent).active = "tab-entries"
        it = self.doc.items[index] if 0 <= index < len(self.doc.items) else None
        if isinstance(it, Raw) and it.section:
            self.expanded.add(it.section)
            self.refresh_all(index, check=False)
        self.select_item(index)
        self.table.focus()

    @on(Input.Changed, "#filter")
    def filter_changed(self, event):
        self.filter_text = event.value
        self.refresh_all()

    @on(Input.Submitted, "#filter")
    def filter_submitted(self, event):
        self.table.focus()

    def on_key(self, event):
        f = self.main.query_one("#filter", Input)
        if event.key == "escape" and f.has_focus:
            f.value = ""
            f.add_class("hidden")
            self.table.focus()
            event.stop()

    # ------------------------------------------------------ quick add -----------------------------------------------
    def candidates(self):
        """Existing terms (base paths and their parents) for the suggestions: (raw, display, books)."""
        if self._candidates is None:
            self._candidates = []
            for path, books in self.doc.paths().items():
                display = " › ".join(plain(Level.parse(x).text) or Level.parse(x).sort for x in path)
                self._candidates.append(("!".join(path), display, sorted(books)))
        return self._candidates

    @on(Input.Changed, "#qa-term")
    def term_changed(self, event):
        self._navigated = False
        q = event.value.strip().lower()
        ol = self.main.query_one("#suggestions", OptionList)
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
        ol.clear_options()
        for _, _, raw, display, books in self._suggestions:
            t = Text(display)
            t.append("   " + (f"books {', '.join(books)}" if books else "group"), "dim")
            ol.add_option(Option(t))
        ol.highlighted = None
        ol.remove_class("hidden")

    def action_suggestion(self, step):
        ol = self.main.query_one("#suggestions", OptionList)
        if ol.has_class("hidden") or not self._suggestions:
            return
        n = len(self._suggestions)
        ol.highlighted = (0 if step > 0 else n - 1) if ol.highlighted is None else (ol.highlighted + step) % n
        self._navigated = True

    def action_close_suggestions(self, back=True):
        ol = self.main.query_one("#suggestions", OptionList)
        if back and ol.has_class("hidden") and self.main.query_one("#qa-term", TermInput).has_focus:
            # Escape without suggestions: back to the table
            self.table.focus()
        ol.add_class("hidden")
        self._suggestions, self._navigated = [], False

    def action_accept_suggestion(self):
        ol = self.main.query_one("#suggestions", OptionList)
        term = self.main.query_one("#qa-term", TermInput)
        if not term.has_focus:
            self.screen.focus_next()
            return
        if ol.has_class("hidden") or not self._suggestions:
            self.screen.focus_next()
            return
        raw = self._suggestions[ol.highlighted or 0][2]
        term.value = raw
        term.cursor_position = len(raw)
        self.action_close_suggestions(False)

    @on(OptionList.OptionSelected, "#suggestions")
    def suggestion_clicked(self, event):
        term = self.main.query_one("#qa-term", TermInput)
        term.value = self._suggestions[event.option_index][2]
        term.focus()
        term.cursor_position = len(term.value)
        self.action_close_suggestions(False)

    def action_focus_add(self):
        self.main.query_one("#tabs", TabbedContent).active = "tab-entries"
        self.main.query_one("#qa-term", TermInput).focus()

    def action_focus_table(self):
        self.action_close_suggestions(False)
        self.table.focus()

    def action_page(self, step):
        page = self.main.query_one("#qa-page", Input)
        nums = [int(x) for x in re.findall(r"\d+", page.value)]
        if not nums:
            page.value = "1"
            return
        page.value = str(max(1, (nums[-1] + 1) if step > 0 else (nums[0] - 1)))

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

    @on(Input.Submitted, "#qa-term")
    def term_submitted(self, event):
        if self._navigated and self._suggestions:
            self.action_accept_suggestion()
            return
        self.add_from_bar()

    @on(Input.Submitted, "#qa-book")
    def book_submitted(self, event):
        self.main.query_one("#qa-page", Input).focus()

    @on(Input.Submitted, "#qa-page")
    def page_submitted(self, event):
        self.main.query_one("#qa-term", TermInput).focus()

    def add_from_bar(self):
        term_w = self.main.query_one("#qa-term", TermInput)
        book = self.main.query_one("#qa-book", Input).value.strip()
        page = self.main.query_one("#qa-page", Input).value.strip()
        term = term_w.value.strip()
        if not term:
            return
        if not book:
            self.notify("Set the book first" + ("" if self.doc.books() else " (F3 creates a new book)"),
                        severity="warning")
            self.main.query_one("#qa-book", Input).focus()
            return
        if book not in self.doc.books():
            self.notify(f"Book {book} does not exist yet: press F3 to create it", severity="error")
            self.main.query_one("#qa-book", Input).focus()
            return
        if not page:
            self.notify("Set the page first", severity="warning")
            self.main.query_one("#qa-page", Input).focus()
            return
        if (err := page_error(page)):
            self.notify(f"Page {page}: {err}", severity="error")
            self.main.query_one("#qa-page", Input).focus()
            return
        levels = self.make_levels(term)
        self.snapshot()
        i = self.doc.add_reference(levels, book, page)
        self.action_close_suggestions(False)
        term_w.value = ""
        self.changed(i)
        e = self.doc.items[i]
        self.notify(Text.assemble("Added ", render(" › ".join(lv.text for lv in levels)),
                                  (f"  {self.course.code}.{book}–{page}", "green"),
                                  (f"  (line {self.doc.line_numbers()[i]}, {self.doc.section_of(i) or 'top'})", "dim")),
                    timeout=4)
        if e.path != tuple(str(x) for x in levels):
            self.notify("Added on a new line for this book", severity="information", timeout=3)

    # ------------------------------------------------------ actions -------------------------------------------------
    def action_edit(self):
        if len(self.screen_stack) > 1:
            return                                     # a dialog is already open (e.g. a fast triple click)
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

        def done(new):
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
        title_of = next((b for b, top in self.doc.chapters().items() if e.path[0] == top), None)
        self.push_screen(EntryDialog(e, "Edit entry", self.course.code, self.commands, self.doc.books(),
                                     title_of=title_of), done)

    def edit_malformed(self, i, raw):
        """Correct a malformed `\\indexentry` line: it becomes a normal entry once saved."""
        def done(new):
            if new is not None:
                if i >= len(self.doc.items) or self.doc.items[i] is not raw:
                    self.notify("The line changed meanwhile: not saved", severity="error")
                    return
                self.snapshot()
                self.doc.items[i] = new
                j = self.doc.relocate(i)
                self.changed(j)
                self.notify("Line corrected" + (f", moved to {self.doc.section_of(j)}" if j != i else ""), timeout=3)
        self.push_screen(EntryDialog(Entry.salvage(raw.text), "Correct a malformed entry", self.course.code,
                                     self.commands, self.doc.books(), raw=raw.text), done)

    def action_new(self):
        i = self.current_index()
        book = self.main.query_one("#qa-book", Input).value.strip()
        book = book if book in self.doc.books() else ""
        page = self.main.query_one("#qa-page", Input).value.strip()
        e = Entry((Level(""), ), page, f"book{{{book}}}" if book else None)

        def done(new):
            if new is not None:
                self.snapshot()
                pos = self.doc.place(new, i)
                self.changed(pos)
                if i is not None and pos != i + 1:
                    self.notify(f"Added to {self.doc.section_of(pos)}", timeout=3)
        self.push_screen(EntryDialog(e, "New entry", self.course.code, self.commands, self.doc.books(), new=True),
                         done)

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

        def done(res):
            if res:
                self.snapshot()
                j = self.doc.add_xref(*res)
                self.changed(j)
        self.push_screen(XrefDialog("", source), done)

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
        items.insert(j if step < 0 else j, it)
        self.changed(j)

    def action_filter(self):
        f = self.main.query_one("#filter", Input)
        f.remove_class("hidden")
        self.main.query_one("#tabs", TabbedContent).active = "tab-entries"
        f.focus()

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
        def done(book):
            if book:
                self.snapshot()
                i = self.doc.add_book(book)
                self.main.query_one("#qa-book", Input).value = book
                self.changed(i)
                self.notify(f"Book {book} created ({self.doc.items[i].section})", timeout=3)
        self.push_screen(NewBookDialog(self.doc.books()), done)

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
        self.main.query_one("#tabs", TabbedContent).active = "tab-sections"
        self.main.query_one("#sections-table", DataTable).focus()

    def action_edit_section(self):
        ol = self.main.query_one("#sections", OptionList)
        if ol.highlighted is None:
            return
        i = int(ol.get_option_at_index(ol.highlighted).id)

        def done(res):
            if res:
                self.apply(SectionDialog.operation(i, res, self.notify))
        self.push_screen(SectionDialog(self.doc, i), done)

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
        self.main.query_one("#sections-pane", SectionsPane).refresh_table(target)

    def action_course(self):
        def done(info):
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
        self.push_screen(CourseDialog(self.course, self.data_path), done)

    def action_compile(self):
        try:
            self.save()
        except OSError as e:
            self.notify(f"Could not save: {e}", severity="error")
            return
        self.notify("Compiling the PDF…", timeout=2)
        self.run_compile()

    @work(thread=True, exclusive=True)
    def run_compile(self):
        result = compile_pdf(self.path, document=self.doc.copy(), course=self.course)
        self.call_from_thread(self.compiled, result)

    def compiled(self, result):
        if result.ok and not result.warnings:
            self.notify(result.summary, timeout=4)
            if self.open_pdf:
                open_file(result.pdf)
            return

        def done(choice):
            if choice == "open":
                open_file(result.pdf)
        self.push_screen(CompileReport(result), done)

    def action_help(self):
        self.push_screen(HelpScreen())

    async def action_quit(self):
        if not self.modified:
            self.exit()
            return

        def done(choice):
            if choice == "save":
                self.save()
                self.exit()
            elif choice == "discard":
                self.exit()
        self.push_screen(ConfirmQuit(), done)
