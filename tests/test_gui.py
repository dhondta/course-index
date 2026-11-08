# -*- coding: UTF-8 -*-
import os
import shutil
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from course_index.gui.app import IndexWindow, application  # noqa: E402
from course_index.gui.dialogs import CompileReport, CourseDialog, EntryDialog, HelpDialog, NewBookDialog, \
                                     SectionDialog, XrefDialog  # noqa: E402
from course_index.gui.widgets import to_html  # noqa: E402
from course_index.idx import Document, Entry  # noqa: E402
from course_index.latex import render  # noqa: E402

DATA = Path(__file__).parent / "data"
K = Qt.Key


@pytest.fixture(scope="module")
def qapp():
    return application()


@pytest.fixture
def idx(tmp_path):
    p = tmp_path / "main.idx"
    shutil.copy(DATA / "main.idx", p)
    return p


@pytest.fixture
def win(qapp, idx):
    w = IndexWindow(idx, open_pdf=False)
    w.show()
    QApplication.processEvents()
    yield w
    w.modified = False
    w.close()
    w.deleteLater()
    QApplication.processEvents()


def wait(cond=None, timeout=3.0):
    """Process the events until the condition holds (or for a short while without condition)."""
    end = time.monotonic() + (timeout if cond else 0.05)
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond and cond():
            return True
        time.sleep(0.005)
    return cond() if cond else True


def key(widget, k, mods=Qt.KeyboardModifier.NoModifier, text=None):
    # the shortcuts of the window need it to be active (the offscreen platform does not reactivate it after a dialog)
    if QApplication.activeModalWidget() is None and not widget.window().isActiveWindow():
        widget.window().activateWindow()
        wait(widget.window().isActiveWindow, 1)
    if text is not None:
        QTest.keyClick(widget, text[0], mods)
    else:
        QTest.keyClick(widget, k, mods)
    wait()


def type_(widget, text):
    QTest.keyClicks(widget, text)
    wait()


class in_dialog:
    """Context manager running `callback(dialog)` once a modal dialog of the given class is open (the dialogs run
    their own event loop): an exception of the callback closes the dialog and is raised again when leaving."""
    def __init__(self, cls, callback):
        self.cls, self.callback, self.seen, self.error = cls, callback, None, None

    def _poll(self):
        dlg = QApplication.activeModalWidget()
        if not isinstance(dlg, self.cls):
            QTimer.singleShot(10, self._poll)
            return
        self.seen = dlg
        dlg.activateWindow()
        wait(dlg.isActiveWindow, 1)
        try:
            self.callback(dlg)
        except BaseException as e:  # noqa: B036
            self.error = e
        if dlg.isVisible():
            dlg.reject()

    def __enter__(self):
        QTimer.singleShot(0, self._poll)
        return self

    def __exit__(self, *exc):
        if self.error is not None:
            raise self.error
        assert self.seen is not None, f"no {self.cls.__name__} opened"


def test_to_html():
    html = to_html(render(r"\textbf{Bold} \texttt{nc} <x>"))
    assert "<b>Bold</b>" in html and "&lt;x&gt;" in html and "white-space:pre" in html
    assert to_html("a\nb", pre=False) == "a<br>b"


def test_layout(win):
    assert win.tabs.count() == 4 and [win.tabs.tabText(i) for i in range(3)] == ["Entries", "Sections", "Preview"]
    assert "Course Index — " in win.windowTitle()
    assert win.sections.count() == len(win.doc.sections())
    assert win.table.hasFocus()
    keys = [k.text() for k in win.footer.findChildren(type(win.footer.lay.itemAt(0).widget()))]
    assert any("Edit" in k for k in keys) and any("Quit" in k for k in keys)


def test_quick_add_and_undo(win):
    n = len(win.doc.items)
    win.qa_book.setText("2")
    win.qa_page.setText("45")
    key(win.table, None, text="a")
    assert win.qa_term.hasFocus()
    type_(win.qa_term, "useful")
    assert any("A useful reference" == s[3] for s in win._suggestions) and win.suggestions.isVisible()
    key(win.qa_term, K.Key_Tab)
    assert win.qa_term.text() == "A useful reference"
    key(win.qa_term, K.Key_Return)
    e = win.doc.items[win.current_index()]
    assert e.to_line() == r"\indexentry{A useful reference|book{2}}{45}"
    assert r"\indexentry{A useful reference}{72}" in win.doc.dumps()
    assert win.modified and len(win.doc.items) == n + 1 and win.qa_term.text() == ""
    key(win.qa_term, K.Key_Up, Qt.KeyboardModifier.ControlModifier)
    assert win.qa_page.text() == "46"
    type_(win.qa_term, "`foo_bar`!Sub")
    key(win.qa_term, K.Key_Return)
    assert win.doc.items[win.current_index()].to_line() == r"\indexentry{Foo_bar@\texttt{foo\_bar}!Sub|book{2}}{46}"
    # navigate the suggestions with the arrows, Enter accepts
    type_(win.qa_term, "chapters")
    key(win.qa_term, K.Key_Down)
    key(win.qa_term, K.Key_Return)
    assert win.qa_term.text().startswith(r"2a@\textbf{Chapters}")
    key(win.qa_term, K.Key_Escape)
    key(win.qa_term, K.Key_Escape)
    assert win.table.hasFocus()
    key(win.table, K.Key_Z, Qt.KeyboardModifier.ControlModifier)
    key(win.table, K.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert len(win.doc.items) == n
    key(win.table, K.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert len(win.doc.items) == n + 1


def test_quick_add_validation(win):
    n = len(win.doc.items)
    win.qa_term.setText("Thing")
    for book, page, focus in [("", "3", win.qa_book), ("7", "3", win.qa_book), ("1", "", win.qa_page),
                              ("1", "0", win.qa_page), ("1", "12-10", win.qa_page)]:
        win.qa_book.setText(book)
        win.qa_page.setText(page)
        win.qa_term.setFocus()
        key(win.qa_term, K.Key_Return)
        assert len(win.doc.items) == n and focus.hasFocus(), (book, page)
    assert win.qa_page.property("invalid")
    win.qa_book.setText("9")
    assert win.qa_book.property("invalid")
    win.qa_book.setText("1")
    win.qa_page.setText("12-13")
    assert not win.qa_book.property("invalid") and not win.qa_page.property("invalid")
    key(win.qa_page, K.Key_Down, Qt.KeyboardModifier.ControlModifier)
    assert win.qa_page.text() == "11"
    win.qa_page.setText("12-13")
    win.qa_term.setFocus()
    key(win.qa_term, K.Key_Return)
    assert win.doc.items[win.current_index()].to_line() == r"\indexentry{Thing|book{1}}{12-13}"
    assert any("Added" in m for m in win.toasts.messages())


def test_table_actions(win):
    i = next(i for i, e in win.doc.entries() if e.path == ("My first reference", ))
    win.select_item(i)
    t = win.table
    key(t, None, text="c")
    assert win.doc.items[i + 1] == win.doc.items[i]
    key(t, None, text="d")
    assert win.doc.items[i + 1] != win.doc.items[i]
    win.select_item(i)
    key(t, K.Key_Space)
    assert win.doc.items[i].disabled
    key(t, K.Key_Space)
    assert not win.doc.items[i].disabled
    key(t, None, text="b")
    assert win.doc.items[i + 1].kind == "spacer"
    win.select_item(i)
    key(t, None, text="p")
    assert win.doc.items[i + 1].kind == "pagebreak"
    win.select_item(i)
    key(t, K.Key_Down, Qt.KeyboardModifier.AltModifier)
    assert win.doc.items[win.current_index()].path == ("My first reference", ) and win.current_index() != i
    key(t, K.Key_Up, Qt.KeyboardModifier.AltModifier)
    key(t, K.Key_Home)
    assert t.cursor_row == 0
    # folding
    win.select_item(win.doc.sections()[1][0])
    title = win.doc.sections()[1][1]
    key(t, K.Key_Left)
    assert title not in win.expanded
    key(t, K.Key_Right)
    assert title in win.expanded
    key(t, None, text="-")
    assert not win.expanded
    key(t, None, text="+")
    assert len(win.expanded) == len(win.doc.sections())
    # section headers cannot be deleted
    win.select_item(win.doc.sections()[1][0])
    n = len(win.doc.items)
    key(t, None, text="d")
    assert len(win.doc.items) == n


def test_edit_dialog(win):
    i = next(i for i, e in win.doc.entries() if e.path == ("Last reference", ))
    win.select_item(i)

    def edit(dlg):
        dlg.texts[0].setText("Last **reference**")
        next(dlg.icons.item(k) for k in range(dlg.icons.count())
             if dlg.icons.item(k).data(Qt.ItemDataRole.UserRole) == "linux").setCheckState(Qt.CheckState.Checked)
        dlg.rating.setCurrentIndex(2)
        assert dlg.raw.text() == r"\indexentry{Last **reference** \linux \rate{2}|book{4}}{89}"
        # editing the raw line updates the fields
        dlg.raw.setFocus()
        dlg.raw.selectAll()
        QTest.keyClicks(dlg.raw, r"\indexentry{Other!Sub \win|book{3}}{12}")
        assert dlg.texts[1].text() == "Sub" and dlg.book.text() == "3" and dlg._selected_icons() == ["win"]
        dlg.raw.selectAll()
        QTest.keyClicks(dlg.raw, r"\indexentry{broken")
        assert dlg.raw_error
        dlg.raw.selectAll()
        QTest.keyClicks(dlg.raw, r"\indexentry{Last **reference**|book{4}}{89}")
        QTest.keyClick(dlg, K.Key_S, Qt.KeyboardModifier.ControlModifier)
    with in_dialog(EntryDialog, edit):
        key(win.table, K.Key_Return)
    assert win.doc.items[i].to_line() == r"\indexentry{Last \textbf{reference}|book{4}}{89}"

    # empty term refused, then cancelled
    def empty(dlg):
        dlg.texts[0].setText("")
        dlg.ok()
        assert dlg.isVisible() and "empty" in dlg.error.text()
        dlg.reject()
    with in_dialog(EntryDialog, empty):
        key(win.table, None, text="e")

    # new entry: page required ; goes to the section of its book
    def new(dlg):
        dlg.texts[0].setText("Fresh")
        dlg.page.setText("")
        dlg.ok()
        assert dlg.isVisible()
        dlg.page.setText("7")
        dlg.ok()
    win.qa_book.setText("1")
    with in_dialog(EntryDialog, new):
        key(win.table, None, text="n")
    j = win.current_index()
    assert win.doc.items[j].to_line() == r"\indexentry{Fresh|book{1}}{7}"
    assert win.doc.section_of(j) == "FIRST BOOK SECTION" and "FIRST BOOK SECTION" in win.expanded

    # changing the book moves the entry to the section of its new book
    def move(dlg):
        dlg.page.setText("0")
        assert dlg.page.property("invalid")
        dlg.ok()
        assert dlg.isVisible()
        dlg.book.setText("3")
        dlg.page.setText("89-90")
        dlg.ok()
    # undo the new entry and the first edit
    key(win.table, K.Key_Z, Qt.KeyboardModifier.ControlModifier)
    key(win.table, K.Key_Z, Qt.KeyboardModifier.ControlModifier)
    win.select_item(next(i for i, e in win.doc.entries() if e.path == ("Last reference", )))
    with in_dialog(EntryDialog, move):
        key(win.table, None, text="e")
    j = win.current_index()
    assert win.doc.items[j].to_line() == r"\indexentry{Last reference|book{3}}{89-90}"
    assert win.doc.section_of(j) == "THIRD BOOK SECTION"
    # comments cannot be edited
    win.select_item(0)
    key(win.table, K.Key_Return)
    assert QApplication.activeModalWidget() is None


def test_xref_course_help_filter(win, tmp_path):
    def xref(dlg):
        QTest.keyClicks(dlg.source, "K8s")
        QTest.keyClick(dlg.source, K.Key_Return)
        assert dlg.target.hasFocus()
        QTest.keyClicks(dlg.target, "Kubernetes")
        QTest.keyClick(dlg.target, K.Key_Return)
    with in_dialog(XrefDialog, xref):
        key(win.table, None, text="x")
    assert win.doc.items[win.current_index()].to_line() == r"\indexentry{K8s \goto Kubernetes|comment}{0}"

    def course(dlg):
        dlg.fields["code"].setText("SEC999")
        QTest.keyClick(dlg.fields["code"], K.Key_Return)
    with in_dialog(CourseDialog, course):
        key(win.table, K.Key_F2)
    assert win.course.code == "SEC999" and (tmp_path / "data.tex").exists()
    assert "SEC999" in win.course_info.text()
    with in_dialog(HelpDialog, lambda dlg: dlg.reject()):
        key(win.table, K.Key_F1)
    # filter
    key(win.table, None, text="/")
    assert win.filter.isVisible() and win.filter.hasFocus()
    type_(win.filter, "book:3")
    assert len(win.table.rows) == 4
    for text, n in (("page:61", 3), ("book:2 page:61", 1), ("page:x", 0), ("useful", 3)):
        win.filter.setText(text)
        assert len(win.table.rows) == n, text
    key(win.filter, K.Key_Escape)
    assert win.filter_text == "" and win.table.hasFocus() and win.filter.isHidden()
    # sections list jumps and sets the book of the quick-add bar
    win.sections.setCurrentRow(3)
    win.sections.setFocus()
    key(win.sections, K.Key_Return)
    assert win.qa_book.text() == "2" and win.table.hasFocus()
    # preview
    win.tabs.setCurrentIndex(2)
    root = win.preview.topLevelItem(0)
    assert root.childCount() >= 3
    win.preview_selected(root.child(0).child(0))
    assert win.tabs.currentIndex() == 0


def test_sections_tab(win):
    key(win.table, K.Key_F4)
    pane = win.sections_pane
    assert win.tabs.currentIndex() == 1 and pane.table.hasFocus()
    assert pane.table.rowCount() == len(win.doc.sections())
    row = next(r for r, i in enumerate(pane.heads) if win.doc.items[i].section == "SECOND BOOK SECTION")
    pane.table.setCurrentCell(row, 0)

    def rename(dlg):
        dlg.book.setText("6")
        assert dlg.title.text() == "SIXTH BOOK SECTION"
        dlg.ok()
    with in_dialog(SectionDialog, rename):
        key(pane.table, None, text="e")
    assert "6" in win.doc.books() and "2" not in win.doc.books()
    key(pane.table, K.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert "2" in win.doc.books()
    n = len(win.doc.sections())
    key(pane.table, K.Key_Down, Qt.KeyboardModifier.AltModifier)
    key(pane.table, None, text="g")
    assert win.tabs.currentIndex() == 0
    key(win.table, K.Key_F4)
    pane.table.setCurrentCell(0, 0)

    def new(dlg):
        dlg.title.setText("TOOLS")
        dlg.ok()
    with in_dialog(SectionDialog, new):
        key(pane.table, None, text="n")
    assert len(win.doc.sections()) == n + 1


def test_new_book(win):
    def bad(dlg):
        assert dlg.book.text() == "5"
        dlg.book.setText("4")
        dlg.ok()
        assert dlg.isVisible() and "already exists" in dlg.error.text()
        dlg.book.setText("W")
        QTest.keyClick(dlg.book, K.Key_Return)
    with in_dialog(NewBookDialog, bad):
        key(win.table, K.Key_F3)
    assert "W" in win.doc.books() and win.qa_book.text() == "W"
    assert win.doc.items[win.current_index()].section == "WORKBOOK SECTION"


def test_problems_and_compile_report(qapp, tmp_path):
    p = tmp_path / "bad.idx"
    p.write_text("\\indexentry{Orphan}{3}\n\\indexentry{x{|book{1}}{1}\n")
    w = IndexWindow(p, open_pdf=False)
    w.show()
    try:
        assert wait(lambda: len(w.problems) == 2)
        assert isinstance(w.doc.items[0], Entry) and w.tabs.tabText(3) == "Problems (2)"
        w.tabs.setCurrentIndex(3)
        w.problem_selected(w.problems_table.item(0, 2))
        assert w.tabs.currentIndex() == 0
        from course_index.compiler import BuildResult
        with in_dialog(CompileReport, lambda dlg: dlg.reject()):
            w.compiled(BuildResult(False, errors=["boom"], log="log"))
    finally:
        w.modified = False
        w.close()


def test_save_and_quit(qapp, idx, monkeypatch):
    w = IndexWindow(idx, open_pdf=False)
    w.show()
    key(w.table, K.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert idx.with_name("main.idx.bak").exists() and not w.modified
    assert idx.read_text() == (DATA / "main.idx").read_text()
    w.qa_page.setText("3")
    w.qa_term.setText("Saved term")
    w.add_from_bar()
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Cancel)
    assert not w.close() and w.isVisible()
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Save)
    assert w.close()
    assert Document.load(idx).dumps().replace(r"\indexentry{Saved term|book{1}}{3}" + "\n", "") == \
        (DATA / "main.idx").read_text()


def test_new_file(qapp, tmp_path, monkeypatch):
    p = tmp_path / "new.idx"
    w = IndexWindow(p, open_pdf=False)
    assert w.is_new and w.modified and w.doc.books() == [] and w.qa_book.text() == ""
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Discard)
    assert w.close()
    assert not p.exists()


def test_main_opens_gui(monkeypatch, idx):
    from course_index import __main__ as m
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(m.sys, "platform", "linux")
    assert not m.has_display()
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert m.has_display()
    calls = []
    monkeypatch.setattr("course_index.gui.run", lambda path, open_pdf=True: calls.append((path, open_pdf)) or 0)
    assert m.main([str(idx), "--no-viewer"]) == 0 and calls == [(idx, False)]
