# -*- coding: UTF-8 -*-
"""Modal screens of the TUI: entry editor, cross-reference, course metadata, build report, help, quit."""
import re

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.validation import ValidationResult, Validator
from textual.widgets import Button, Checkbox, DataTable, Input, Label, Markdown, Select, SelectionList, Static, \
                            TextArea

from ..course import CourseInfo
from ..idx import Document, Entry, Level, book_sort_key, normalize_title, page_error
from ..common import HELP, MAX_LEVELS, join_decorations, split_decorations  # noqa: F401
from ..latex import ICONS, expand_shortcuts, plain, render

__all__ = ["BookValidator", "CompileReport", "ConfirmQuit", "CourseDialog", "EntryDialog", "HelpScreen",
           "NewBookDialog", "PageValidator", "SectionDialog", "SectionsPane", "XrefDialog"]


class PageValidator(Validator):
    """Page of a reference: not 0, and a range must end after it starts.

    :param active:   callable telling whether the check applies (e.g. not for blank lines, whose page is 0)
    :param original: page read from the file, accepted as is when unchanged
    """
    def __init__(self, active=None, original=None):
        super().__init__()
        self.active, self.original = active, original

    def validate(self, value) -> ValidationResult:
        if self.active is not None and not self.active() or \
           self.original is not None and value.strip() == self.original.strip():
            return self.success()
        err = page_error(value)
        return self.failure(err) if err else self.success()


class BookValidator(Validator):
    """Book of a reference: one of the books of the index (or empty when allowed).

    :param books: callable returning the existing books
    """
    def __init__(self, books, allow_empty=True):
        super().__init__()
        self.books, self.allow_empty = books, allow_empty

    def validate(self, value) -> ValidationResult:
        v = value.strip()
        if not v:
            return self.success() if self.allow_empty else self.failure("the book is required")
        if v not in self.books():
            return self.failure(f"book {v} does not exist yet (F3 creates a new book)")
        return self.success()


class Dialog(ModalScreen):
    """Base dialog, closed with Escape."""
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def action_cancel(self):
        self.dismiss(None)

    def on_button_pressed(self, event):
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "ok":
            self.action_ok()


class EntryDialog(Dialog):
    """Structured editor of an index entry, synchronized with its raw `\\indexentry` line."""
    BINDINGS = Dialog.BINDINGS + [Binding("ctrl+s", "ok", "Save", priority=True)]

    def __init__(self, entry, title="Edit entry", code="", known=None, books=(), new=False, title_of=None,
                 raw=None):
        """:param title_of: book whose title is the first level of the entry (then locked, edited in the Sections tab)
        :param raw:      malformed line to correct (the entry is then a best-effort reading of it)"""
        super().__init__()
        self.raw_text, self.raw_error = raw, None
        self.entry, self.original, self.title_text, self.code = entry, entry, title, code
        self.known = known or set()
        self.books, self.new = list(books), new
        self.title_of = title_of
        self.locked = (entry.path[0] if entry.levels else None) if title_of else None

    @property
    def lock_message(self):
        return f"the first level is the title of book {self.title_of}: edit it in the Sections tab (F4, e)"

    def compose(self) -> ComposeResult:
        e = self.entry
        base, icons, rating = split_decorations(e.levels[-1].text if e.levels else "")
        with Vertical(id="dialog", classes="entry-dialog"):
            yield Label(self.title_text, classes="dialog-title")
            with Grid(id="levels"):
                yield Label("Sort key", classes="col-head")
                yield Label("Text (LaTeX; shortcuts: `code` **bold** *italic* :linux:)", classes="col-head")
                visible = max(len(e.levels) + 1, 2)
                for i in range(MAX_LEVELS):
                    lv = e.levels[i] if i < len(e.levels) else Level("")
                    text = base if i == len(e.levels) - 1 else lv.text
                    hidden = " hidden" if i >= visible else ""
                    lock = dict(disabled=True, tooltip=self.lock_message[0].upper() + self.lock_message[1:]) \
                        if i == 0 and self.locked else {}
                    yield Input(lv.key or "", placeholder="auto", id=f"key{i}", classes="level-key" + hidden, **lock)
                    yield Input(text, placeholder=["Term", "Sub-term", "Sub-sub-term", "Level 4"][i],
                                id=f"text{i}", classes="level-text" + hidden, **lock)
            with Horizontal(classes="row"):
                yield Label("Book", classes="field-label")
                yield Input(e.book or "", id="book", classes="short", restrict=r"[0-9A-Za-z]*",
                            tooltip="Existing books: " + (", ".join(self.books) or "none (F3 creates one)"),
                            validators=[BookValidator(self._allowed_books)])
                yield Label("Pages", classes="field-label")
                yield Input(e.page, id="page", classes="short", restrict=r"[0-9\-]*",
                            validators=[PageValidator(lambda: self.entry.kind == "ref",
                                                      None if self.new else e.page)])
                yield Label("Other encap.", classes="field-label")
                yield Input(e.encap_rest or "", id="rest", placeholder="e.g. comment, \\lab")
            with Horizontal(classes="row"):
                yield Label("Rating", classes="field-label")
                yield Select([(("★" * i) if i else "none", i) for i in range(6)], value=rating, allow_blank=False,
                             id="rating")
                yield Checkbox("Commented out (%)", e.disabled, id="disabled")
            yield SelectionList(*[(Text(f"{ICONS[k]} \\{k}"), k, k in icons) for k in ICONS], id="icons")
            yield Static(id="entry-preview")
            yield Input(self.raw_text if self.raw_text is not None else e.to_line(), id="raw",
                        placeholder="\\indexentry{...}{...}")
            with Horizontal(classes="buttons"):
                yield Button("Save (Ctrl+S)", variant="primary", id="ok")
                yield Button("Cancel (Esc)", id="cancel")

    def on_mount(self):
        self.query_one("#text1" if self.locked else "#text0", Input).focus()
        if self.raw_text is not None and Entry.parse(self.raw_text) is None:
            self.raw_error = "malformed line (unbalanced braces?): correct it here or in the fields"
        self._update_preview(self.raw_error)

    # ------------------------------------------------- synchronization ----------------------------------------------
    def _from_fields(self):
        levels = []
        icons = list(self.query_one("#icons", SelectionList).selected)
        rating = self.query_one("#rating", Select).value or 0
        texts = [self.query_one(f"#text{i}", Input).value for i in range(MAX_LEVELS)]
        last = max([i for i, t in enumerate(texts) if t != ""] + [0])
        for i in range(last + 1):
            key = self.query_one(f"#key{i}", Input).value
            text = texts[i]
            if i == last:
                text = join_decorations(text, icons, rating)
            levels.append(Level(text, key if key != "" else None))
        book = self.query_one("#book", Input).value.strip()
        rest = self.query_one("#rest", Input).value
        encap = (f"book{{{book}}}" + rest) if book else (rest if rest != "" else None)
        disabled = self.query_one("#disabled", Checkbox).value
        return Entry(tuple(levels), self.query_one("#page", Input).value, encap, disabled)

    def _to_fields(self, e):
        base, icons, rating = split_decorations(e.levels[-1].text)
        for i in range(MAX_LEVELS):
            lv = e.levels[i] if i < len(e.levels) else Level("")
            self.query_one(f"#key{i}", Input).value = lv.key or ""
            self.query_one(f"#text{i}", Input).value = base if i == len(e.levels) - 1 else lv.text
            if i <= len(e.levels):
                self.query_one(f"#key{i}").remove_class("hidden")
                self.query_one(f"#text{i}").remove_class("hidden")
        self.query_one("#book", Input).value = e.book or ""
        self.query_one("#page", Input).value = e.page
        self.query_one("#rest", Input).value = e.encap_rest or ""
        self.query_one("#disabled", Checkbox).value = e.disabled
        self.query_one("#rating", Select).value = rating
        sl = self.query_one("#icons", SelectionList)
        sl.deselect_all()
        for i in icons:
            sl.select(i)

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
        self.query_one("#entry-preview", Static).update(t)

    def _fields_changed(self):
        new = self._from_fields()
        if new != self.entry:
            self.entry = new
            raw = self.query_one("#raw", Input)
            if not raw.has_focus:
                raw.value = new.to_line()
                self.raw_error = None
            self._update_preview(self.raw_error)

    def on_input_changed(self, event):
        if event.input.id == "raw":
            if not event.input.has_focus:
                return
            parsed = Entry.parse(event.value.strip())
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
        else:
            if event.input.id and event.input.id.startswith("text"):
                # reveal the next level when this one is filled
                i = int(event.input.id[4:])
                if event.value and i + 1 < MAX_LEVELS:
                    self.query_one(f"#key{i+1}").remove_class("hidden")
                    self.query_one(f"#text{i+1}").remove_class("hidden")
            self._fields_changed()

    def on_select_changed(self, event):
        self._fields_changed()

    def on_checkbox_changed(self, event):
        self._fields_changed()

    def on_selection_list_selected_changed(self, event):
        self._fields_changed()

    def on_input_submitted(self, event):
        self.action_ok()

    def _allowed_books(self):
        # the book of the entry being edited exists (it comes from the file)
        return self.books + ([self.original.book] if self.original.book and not self.new else [])

    def action_ok(self):
        e = self.entry
        if self.raw_error or not e.is_valid:
            self.notify("The line is still malformed: " + (self.raw_error or "unbalanced braces in a field?"),
                        severity="error")
            return
        if not e.levels or e.levels[0].text.strip() == "":
            self.notify("The term cannot be empty", severity="error")
            return
        if self.locked and e.path[0] != self.locked:
            self.notify(self.lock_message[0].upper() + self.lock_message[1:], severity="error")
            return
        if e.page.strip() == "":
            self.notify("The page cannot be empty (use 0 for entries without page)", severity="error")
            return
        if e.kind == "ref":
            for wid in ("#book", "#page"):
                res = self.query_one(wid, Input).validate(self.query_one(wid, Input).value)
                if res is not None and not res.is_valid:
                    self.notify(f"{wid[1:].title()}: {res.failure_descriptions[0]}", severity="error")
                    self.query_one(wid, Input).focus()
                    return
        orig = self.original.levels
        # expand the shortcuts only in the levels that were changed (existing LaTeX is kept as is)
        levels = tuple(lv if lv.text.strip() == "" or i < len(orig) and lv.text == orig[i].text else
                       Level(expand_shortcuts(lv.text), lv.key) for i, lv in enumerate(e.levels))
        self.dismiss(e.evolve(levels=levels))


class NewBookDialog(Dialog):
    """Create a new book (and its section in the file)."""
    def __init__(self, books):
        super().__init__()
        self.books = list(books)
        nums = [int(b) for b in self.books if b.isdigit()]
        self.suggestion = str(max(nums) + 1) if nums else ("1" if not self.books else "")

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog", classes="small"):
            yield Label("New book", classes="dialog-title")
            yield Label("Existing books: " + (", ".join(sorted(self.books, key=book_sort_key)) or "none"))
            yield Label("Book (a number, or letters such as W for a workbook)")
            yield Input(self.suggestion, id="book", restrict=r"[0-9A-Za-z]*", validators=[_NewBook(self.books)])
            with Horizontal(classes="buttons"):
                yield Button("Create", variant="primary", id="ok")
                yield Button("Cancel (Esc)", id="cancel")

    def on_input_submitted(self, event):
        self.action_ok()

    def action_ok(self):
        inp = self.query_one("#book", Input)
        res = inp.validate(inp.value)
        if res is not None and not res.is_valid:
            self.notify(res.failure_descriptions[0], severity="error")
            return
        self.dismiss(inp.value.strip())


class _NewBook(Validator):
    def __init__(self, books):
        super().__init__()
        self.books = books

    def validate(self, value) -> ValidationResult:
        v = value.strip()
        if not v:
            return self.failure("the book is required")
        if v in self.books:
            return self.failure(f"book {v} already exists")
        return self.success()


class SectionDialog(Dialog):
    """Title, book and chapter of a section (new one when index is None)."""
    def __init__(self, doc, index=None, after=None):
        super().__init__()
        self.doc, self.index, self.after = doc, index, after
        title = doc.items[index].section if index is not None else ""
        self.old_title = title
        self.old_book = Document.section_book(title) if Document.section_kind(title) == "book" else None
        self._prev_book = self.old_book or ""
        # the chapter of the book: its group of parts in the Topics section, whose bold title is the book's title
        self.chapter = doc.chapters().get(self.old_book) if self.old_book else None
        self.old_chapter = Document.chapter_title(self.chapter) if self.chapter else None

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

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Edit section" if self.index is not None else "New section", classes="dialog-title")
            with Grid(id="section-grid"):
                yield Label("Index section title")
                yield Input(self.old_title, id="title", placeholder="e.g. FIRST BOOK SECTION, SANS 504.1 SECTION, TOOLS")
                yield Label("Book")
                yield Input(self.old_book or "", id="book", restrict=r"[0-9A-Za-z]*",
                            placeholder="empty: not a book section (e.g. tools, labs)")
                if self.old_chapter is not None:
                    yield Label("Title")
                    yield Input(self.old_chapter, id="chapter", tooltip="Title of the book: the bold first level of "
                                "its parts in the Topics section (LaTeX, e.g. Recon \\& Mapping)")
            n = self.doc.book_usage(self.old_book) if self.old_book else 0
            yield Checkbox(f"Also change the book of the {n} entries using book {self.old_book}", True,
                           id="renumber", classes="" if self.old_book and n else "hidden")
            yield Static(id="section-preview")
            with Horizontal(classes="buttons"):
                yield Button("Save", variant="primary", id="ok")
                yield Button("Cancel (Esc)", id="cancel")

    def on_mount(self):
        # the title of the book is what is usually edited ; the index section title otherwise
        self.query_one("#chapter" if self.old_chapter is not None else "#title", Input).focus()
        self._update()

    def _values(self):
        return self.query_one("#title", Input).value, self.query_one("#book", Input).value.strip()

    def _chapter(self):
        """New title of the book's chapter, None when it is unchanged (or the book has no chapter)."""
        if self.old_chapter is None:
            return None
        value = " ".join(self.query_one("#chapter", Input).value.split())
        return None if value == self.old_chapter else value

    def _check_chapter(self, chapter):
        if chapter is not None:
            self.doc.copy().rename_chapter(self.chapter, chapter)

    def _update(self):
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
               self.query_one("#renumber", Checkbox).value and self.doc.book_usage(self.old_book):
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
        self.query_one("#section-preview", Static).update(t)

    def on_input_changed(self, event):
        if event.input.id == "book" and event.value.strip():
            # adapt the title to the book (e.g. FIRST BOOK SECTION -> SECOND BOOK SECTION)
            title_w = self.query_one("#title", Input)
            try:
                title_w.value = Document.retitle(title_w.value or "BOOK", self._prev_book or None, event.value.strip())
            except ValueError:
                pass
            self._prev_book = event.value.strip()
        self._update()

    def on_checkbox_changed(self, event):
        self._update()

    def on_input_submitted(self, event):
        self.action_ok()

    def action_ok(self):
        title, book = self._values()
        try:
            self.doc._check_section(self.index, title, book)
            normalize_title(title)
            self._check_chapter(self._chapter())
        except ValueError as e:
            self.notify(str(e), severity="error")
            return
        self.dismiss((title, book or None, self.query_one("#renumber", Checkbox).value, self._chapter()))


class SectionsPane(Vertical):
    """Manager of the sections of the file (the books are sections too), shown in the Sections tab."""
    BINDINGS = [
        Binding("e", "edit", "Edit"),
        Binding("n", "new", "New"),
        Binding("d,delete", "delete", "Delete"),
        Binding("alt+up,ctrl+shift+up", "move(-1)", "Move up"),
        Binding("alt+down,ctrl+shift+down", "move(1)", "Move down"),
        Binding("g", "goto", "Go to"),
        Binding("t", "chapter", "Go to title"),
    ]

    def compose(self) -> ComposeResult:
        yield Static(Text("A book section gives its book to new references (F3 also creates one). "
                          "e/Enter: edit (section title, book, title) · n: new · d: delete the header · Alt+↑/↓: move · "
                          "g: go to the entries · t: go to the book's title (its parts in the Topics)", "dim"),
                     id="sections-help")
        yield DataTable(id="sections-table", cursor_type="row", zebra_stripes=True)
        with Horizontal(classes="buttons"):
            yield Button("New (n)", id="new")
            yield Button("Edit (e)", id="edit")
            yield Button("Up", id="up")
            yield Button("Down", id="down")
            yield Button("Delete (d)", variant="error", id="delete")
            yield Button("Go to (g)", id="goto")

    @property
    def doc(self):
        return self.app.doc

    @property
    def table(self):
        return self.query_one("#sections-table", DataTable)

    COLUMNS = ("Index Section Title", "Kind", "Book", "Title", "Entries", "Book used by")
    EXPAND = 3                                         # the column taking the remaining width (Title)

    def on_mount(self):
        self.heads = []
        self.refresh_table()

    def on_resize(self, event):
        # the widths of the columns depend on the width of the pane (also when the tab is first shown)
        self.call_after_refresh(self.refresh_table)

    def refresh_table(self, select=None):
        """Rebuild the list (after any change of the document), keeping the cursor or moving it to a header ; the
        columns fill the width of the pane."""
        t = self.table
        row = t.cursor_row
        rows, self.heads = [], []
        chapters = self.doc.chapters()
        for i, title in self.doc.sections():
            kind = Document.section_kind(title)
            book = Document.section_book(title) if kind == "book" else None
            chapter = plain(Document.chapter_title(chapters[book])) if book in chapters else ""
            rows.append((Text(title, "bold magenta" if kind == "book" else ""), Text(kind), Text(book or ""),
                         Text(chapter), Text(str(self.doc.section_entries(i)), justify="right"),
                         Text(f"{self.doc.book_usage(book)} entries" if book else "")))
            self.heads.append(i)
        widths = [max([len(label)] + [r[k].cell_len for r in rows]) for k, label in enumerate(self.COLUMNS)]
        avail = t.scrollable_content_region.width
        spare = avail - sum(w + 2 * t.cell_padding for w in widths)
        if avail and spare > 0:
            widths[self.EXPAND] += spare
        elif avail:
            # too narrow: shrink the titles (cut with an ellipsis), the book's first, down to a minimum
            for k, minimum in ((self.EXPAND, 12), (0, 16)):
                cut = min(-spare, max(0, widths[k] - minimum))
                widths[k], spare = widths[k] - cut, spare + cut
                for r in rows:
                    r[k].truncate(widths[k], overflow="ellipsis")
        t.clear(columns=True)
        for label, w in zip(self.COLUMNS, widths):
            t.add_column(label, width=w)
        for r in rows:
            t.add_row(*r)
        if select is not None and select in self.heads:
            row = self.heads.index(select)
        if self.heads:
            t.move_cursor(row=min(row or 0, len(self.heads) - 1))

    def current(self):
        if not self.heads:
            return None
        return self.heads[min(self.table.cursor_row, len(self.heads) - 1)]

    def apply(self, op):
        """Apply an operation on the document through the app (undoable) ; op returns the index to select."""
        res = self.app.apply(op)
        if res is not None:
            self.refresh_table(res)

    def on_data_table_row_selected(self, event):
        event.stop()
        self.action_edit()

    def action_edit(self):
        i = self.current()
        if i is None:
            return

        def done(res):
            if res:
                self.apply(SectionDialog.operation(i, res, self.notify))
        self.app.push_screen(SectionDialog(self.doc, i), done)

    def action_new(self):
        after = self.current()

        def done(res):
            if res:
                title, book, _, _ = res
                self.apply(lambda doc: doc.add_section(title, book, after))
        self.app.push_screen(SectionDialog(self.doc, None, after), done)

    def action_delete(self):
        i = self.current()
        if i is not None:
            self.apply(lambda doc: (doc.delete_section(i), max(0, i - 1))[1])

    def action_move(self, step):
        i = self.current()
        if i is not None:
            self.apply(lambda doc: doc.move_section(i, step))

    def action_goto(self):
        i = self.current()
        if i is not None:
            self.app.goto_item(i)

    def action_chapter(self):
        i = self.current()
        if i is None:
            return
        book = Document.section_book(self.doc.items[i].section)
        top = self.doc.chapters().get(book) if Document.section_kind(self.doc.items[i].section) == "book" else None
        if not top:
            self.notify("This section has no title: no group of the Topics section holds the parts of its book only",
                        severity="warning")
            return
        self.app.goto_item(next(k for k, e in self.doc.entries() if e.path[0] == top))

    def on_button_pressed(self, event):
        event.stop()
        action = {"up": lambda: self.action_move(-1), "down": lambda: self.action_move(1)}.get(event.button.id)
        (action or getattr(self, f"action_{event.button.id}"))()
        self.table.focus()


class XrefDialog(Dialog):
    """Cross-reference: `source -> target`."""
    def __init__(self, source="", target=""):
        super().__init__()
        self.source, self.target = source, target

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Add a cross-reference", classes="dialog-title")
            yield Label("See (alias, e.g. K8s or IaaS!Testing Policies)")
            yield Input(self.source, id="source")
            yield Label("→ refers to (e.g. Kubernetes)")
            yield Input(self.target, id="target")
            with Horizontal(classes="buttons"):
                yield Button("Add", variant="primary", id="ok")
                yield Button("Cancel (Esc)", id="cancel")

    def on_input_submitted(self, event):
        if event.input.id == "source":
            self.query_one("#target", Input).focus()
        else:
            self.action_ok()

    def action_ok(self):
        s, t = self.query_one("#source", Input).value.strip(), self.query_one("#target", Input).value.strip()
        if not s or not t:
            self.notify("Both terms are required", severity="error")
            return
        self.dismiss((expand_shortcuts(s), expand_shortcuts(t)))


class CourseDialog(Dialog):
    """Course metadata (written to the data file of the index)."""
    def __init__(self, info, path):
        super().__init__()
        self.info, self.path = info, path

    def compose(self) -> ComposeResult:
        i = self.info
        with Vertical(id="dialog"):
            yield Label("Course", classes="dialog-title")
            yield Static(Text(f"Saved to {self.path}", "dim"))
            with Grid(id="course-grid"):
                for attr, label, ph in [("code", "Code", "e.g. SEC504 or 504 (prefix of the page numbers)"),
                                        ("title", "Title", "\\coursecode may be used"),
                                        ("date", "Date", "e.g. 05/2025"), ("version", "Version", "e.g. v1.2"),
                                        ("author", "Author", "optional")]:
                    yield Label(label)
                    yield Input(getattr(i, attr), id=attr, placeholder=ph)
            with Horizontal(classes="buttons"):
                yield Button("Save", variant="primary", id="ok")
                yield Button("Cancel (Esc)", id="cancel")

    def on_input_submitted(self, event):
        self.action_ok()

    def action_ok(self):
        values = {a: self.query_one(f"#{a}", Input).value for a in ("code", "title", "date", "version", "author")}
        self.dismiss(CourseInfo(**values))


class CompileReport(Dialog):
    """Report of a compilation (errors, warnings and log)."""
    BINDINGS = Dialog.BINDINGS + [Binding("o", "open", "Open PDF")]

    def __init__(self, result):
        super().__init__()
        self.result = result

    def compose(self) -> ComposeResult:
        r = self.result
        with Vertical(id="dialog", classes="wide"):
            yield Label("PDF compiled" if r.ok else "Compilation failed", classes="dialog-title")
            t = Text()
            t.append(r.summary + "\n", "green" if r.ok else "bold red")
            for e in r.errors:
                t.append(f"✖ {e}\n", "red")
            for w in r.warnings:
                t.append(f"⚠ {w}\n", "yellow")
            yield Static(t, id="report")
            yield TextArea(r.log or "(no log)", read_only=True, id="log")
            with Horizontal(classes="buttons"):
                if r.ok:
                    yield Button("Open PDF (o)", variant="primary", id="open")
                yield Button("Close (Esc)", id="cancel")

    def action_open(self):
        if self.result.ok:
            self.dismiss("open")

    def on_button_pressed(self, event):
        if event.button.id == "open":
            self.dismiss("open")
        else:
            super().on_button_pressed(event)


class ConfirmQuit(Dialog):
    """Ask what to do with unsaved changes."""
    BINDINGS = Dialog.BINDINGS + [Binding("s", "choose('save')", "Save"), Binding("d", "choose('discard')", "Discard")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog", classes="small"):
            yield Label("Unsaved changes", classes="dialog-title")
            yield Label("Save the index before quitting?")
            with Horizontal(classes="buttons"):
                yield Button("Save (s)", variant="primary", id="save")
                yield Button("Discard (d)", variant="error", id="discard")
                yield Button("Cancel (Esc)", id="cancel")

    def action_choose(self, what):
        self.dismiss(what)

    def on_button_pressed(self, event):
        self.dismiss(None if event.button.id == "cancel" else event.button.id)


class HelpScreen(Dialog):
    BINDINGS = Dialog.BINDINGS + [Binding("f1,q", "cancel", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog", classes="wide"):
            with VerticalScroll():
                yield Markdown(HELP)
            with Horizontal(classes="buttons"):
                yield Button("Close (Esc)", id="cancel")
