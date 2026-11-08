# -*- coding: UTF-8 -*-
import asyncio
import shutil
from pathlib import Path

import pytest

from course_index.idx import Document, Entry

from test_idx import TOPICS_FIRST_BOOK
from course_index.tui.app import IndexApp
from course_index.tui.screens import ConfirmQuit, CourseDialog, EntryDialog, HelpScreen, NewBookDialog, \
                                     SectionDialog, SectionsPane, XrefDialog, join_decorations, split_decorations

DATA = Path(__file__).parent / "data"


def run(path, scenario, size=(150, 45)):
    async def _run():
        app = IndexApp(path, open_pdf=False)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await scenario(app, pilot)
        return app
    return asyncio.run(_run())


async def type_(pilot, text):
    for ch in text:
        await pilot.press({" ": "space", "!": "exclamation_mark", "`": "grave_accent", "*": "asterisk",
                           ":": "colon", "@": "at", "/": "slash", "_": "underscore", "-": "minus"}.get(ch, ch))
    await pilot.pause()


@pytest.fixture
def idx(tmp_path):
    p = tmp_path / "main.idx"
    shutil.copy(DATA / "main.idx", p)
    return p


def test_decorations():
    assert split_decorations(r"John \win\linux \rate{3}") == ("John", ["win", "linux"], 3)
    assert join_decorations("John", ["win"], 2) == r"John \win \rate{2}"


def test_quick_add_and_undo(idx):
    async def scenario(app, pilot):
        n = len(app.doc.items)
        app.query_one("#qa-book").value, app.query_one("#qa-page").value = "2", "45"
        await pilot.press("a")
        assert app.focused.id == "qa-term"
        await type_(pilot, "useful")
        assert any("A useful reference" == s[3] for s in app._suggestions)
        await pilot.press("tab")
        assert app.query_one("#qa-term").value == "A useful reference"
        await pilot.press("enter")
        await pilot.pause()
        e = app.doc.items[app.current_index()]
        # page 45 comes before page 72: the book number moves to the new entry
        assert e.to_line() == r"\indexentry{A useful reference|book{2}}{45}"
        assert r"\indexentry{A useful reference}{72}" in app.doc.dumps()
        assert app.modified and len(app.doc.items) == n + 1
        # new term with shortcuts, sort key and sub-level ; page increment
        await pilot.press("ctrl+up")
        assert app.query_one("#qa-page").value == "46"
        await type_(pilot, "`foo_bar`!Sub")
        await pilot.press("enter")
        await pilot.pause()
        e = app.doc.items[app.current_index()]
        assert e.to_line() == r"\indexentry{Foo_bar@\texttt{foo\_bar}!Sub|book{2}}{46}"
        # navigate the suggestions with the arrows, Enter accepts
        await type_(pilot, "chapters")
        await pilot.press("down")
        await pilot.press("enter")
        assert app.query_one("#qa-term").value.startswith(r"2a@\textbf{Chapters}")
        await pilot.press("escape", "escape")
        assert app.focused.id == "table"
        await pilot.press("ctrl+z", "ctrl+z")
        assert len(app.doc.items) == n
        await pilot.press("ctrl+y")
        assert len(app.doc.items) == n + 1
        await pilot.press("ctrl+z", "ctrl+z", "ctrl+z")
    run(idx, scenario)


def test_quick_add_requires_book_and_page(idx):
    async def scenario(app, pilot):
        app.query_one("#qa-book").value = ""
        await pilot.press("a")
        await type_(pilot, "Thing")
        await pilot.press("enter")
        assert app.focused.id == "qa-book"
        await type_(pilot, "1")
        await pilot.press("enter")
        assert app.focused.id == "qa-page"
        await pilot.press("ctrl+down")
        assert app.query_one("#qa-page").value == "1"
        app.query_one("#qa-page").value = ""
        app.query_one("#qa-term").focus()
        await pilot.press("enter")
        assert app.focused.id == "qa-page"
    run(idx, scenario)


def test_table_actions(idx):
    async def scenario(app, pilot):
        t = app.table
        i = next(i for i, e in app.doc.entries() if e.path == ("My first reference", ))
        app.select_item(i)
        await pilot.press("c")
        assert app.doc.items[i + 1] == app.doc.items[i]
        await pilot.press("d")
        assert app.doc.items[i + 1] != app.doc.items[i]
        app.select_item(i)
        await pilot.press("space")
        assert app.doc.items[i].disabled
        await pilot.press("space")
        assert not app.doc.items[i].disabled
        await pilot.press("b")
        assert app.doc.items[i + 1].kind == "spacer"
        app.select_item(i)
        await pilot.press("p")
        assert app.doc.items[i + 1].kind == "pagebreak"
        app.select_item(i)
        await pilot.press("alt+down")
        assert app.doc.items[app.current_index()].path == ("My first reference", )
        await pilot.press("alt+up")
        # navigation
        await pilot.press("home")
        assert t.cursor_row == 0
        await pilot.press("end", "pageup", "down", "up")
        # section headers cannot be deleted
        app.select_item(app.doc.sections()[1][0])
        n = len(app.doc.items)
        await pilot.press("d")
        assert len(app.doc.items) == n
    run(idx, scenario)


def test_edit_dialog(idx):
    async def scenario(app, pilot):
        i = next(i for i, e in app.doc.entries() if e.path == ("Last reference", ))
        app.select_item(i)
        await pilot.press("enter")
        assert isinstance(app.screen, EntryDialog)
        dlg = app.screen
        dlg.query_one("#text0").value = "Last **reference**"
        dlg.query_one("#icons").select("linux")
        dlg.query_one("#rating").value = 2
        await pilot.pause()
        assert dlg.query_one("#raw").value == r"\indexentry{Last **reference** \linux \rate{2}|book{4}}{89}"
        # editing the raw line updates the fields
        raw = dlg.query_one("#raw")
        raw.focus()
        raw.value = r"\indexentry{Other!Sub \win|book{3}}{12}"
        await pilot.pause()
        assert dlg.query_one("#text1").value == "Sub" and dlg.query_one("#book").value == "3"
        assert list(dlg.query_one("#icons").selected) == ["win"]
        raw.value = r"\indexentry{broken"
        await pilot.pause()
        raw.value = r"\indexentry{Last **reference**|book{4}}{89}"
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.doc.items[i].to_line() == r"\indexentry{Last \textbf{reference}|book{4}}{89}"
        # empty term refused
        await pilot.press("e")
        await pilot.pause()
        app.screen.query_one("#text0").value = ""
        await pilot.pause()
        await pilot.press("ctrl+s")
        assert isinstance(app.screen, EntryDialog)
        await pilot.press("escape")
        # new entry
        await pilot.press("n")
        app.screen.query_one("#text0").value = "Fresh"
        app.screen.query_one("#page").value = ""
        await pilot.pause()
        await pilot.press("ctrl+s")
        assert isinstance(app.screen, EntryDialog)
        app.screen.query_one("#page").value = "7"
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        # book 1 is not the book of the current line's section (book 4): the entry goes to the FIRST BOOK SECTION
        j = app.current_index()
        assert app.doc.items[j].to_line() == r"\indexentry{Fresh|book{1}}{7}"
        assert app.doc.section_of(j) == "FIRST BOOK SECTION" and "FIRST BOOK SECTION" in app.expanded
        # comments cannot be edited
        app.select_item(0)
        await pilot.press("enter")
        assert not isinstance(app.screen, EntryDialog)
    run(idx, scenario)


def test_xref_course_help_filter(idx, tmp_path):
    async def scenario(app, pilot):
        await pilot.press("x")
        assert isinstance(app.screen, XrefDialog)
        await type_(pilot, "K8s")
        await pilot.press("enter")
        await type_(pilot, "Kubernetes")
        await pilot.press("enter")
        await pilot.pause()
        assert app.doc.items[app.current_index()].to_line() == r"\indexentry{K8s \goto Kubernetes|comment}{0}"
        await pilot.press("f2")
        assert isinstance(app.screen, CourseDialog)
        app.screen.query_one("#code").value = "SEC999"
        await pilot.press("enter")
        await pilot.pause()
        assert app.course.code == "SEC999" and (tmp_path / "data.tex").exists()
        await pilot.press("f1")
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.press("slash")
        await type_(pilot, "book:3")
        assert app.table.row_count == 4
        app.query_one("#filter").value = "page:61"
        await pilot.pause()
        assert app.table.row_count == 3
        app.query_one("#filter").value = "book:2 page:61"
        await pilot.pause()
        assert app.table.row_count == 1
        app.query_one("#filter").value = "page:x"
        await pilot.pause()
        assert app.table.row_count == 0
        app.query_one("#filter").value = "useful"
        await pilot.pause()
        assert app.table.row_count == 3
        await pilot.press("escape")
        assert app.filter_text == "" and app.focused.id == "table"
        # sections list jumps and sets the book of the quick-add bar
        sl = app.query_one("#sections")
        sl.focus()
        sl.highlighted = 3
        await pilot.press("enter")
        assert app.query_one("#qa-book").value == "2"
        # preview and problems tabs
        app.query_one("#tabs").active = "tab-preview"
        await pilot.pause()
        tree = app.query_one("#preview")
        assert len(tree.root.children) >= 3
        node = tree.root.children[0].children[0]
        tree.select_node(node)
        await pilot.pause()
        app.query_one("#tabs").active = "tab-problems"
        await pilot.pause()
    run(idx, scenario)


def test_save_and_quit(idx):
    async def scenario(app, pilot):
        await pilot.press("ctrl+s")
        assert idx.with_name("main.idx.bak").exists() and not app.modified
        assert idx.read_text() == (DATA / "main.idx").read_text()
        app.query_one("#qa-page").value = "3"
        await pilot.press("a")
        await type_(pilot, "Saved term")
        await pilot.press("enter", "escape")
        await pilot.press("ctrl+q")
        assert isinstance(app.screen, ConfirmQuit)
        await pilot.press("escape")
        await pilot.press("ctrl+q")
        await pilot.press("s")
    run(idx, scenario)
    assert "Saved term" in idx.read_text()
    assert Document.load(idx).dumps().replace(r"\indexentry{Saved term|book{1}}{3}" + "\n", "") == \
        (DATA / "main.idx").read_text()


def test_new_file(tmp_path):
    p = tmp_path / "new.idx"

    async def scenario(app, pilot):
        assert app.is_new and app.modified
        await pilot.press("ctrl+q", "d")
    run(p, scenario)
    assert not p.exists()


def test_problems_flags(tmp_path):
    p = tmp_path / "bad.idx"
    p.write_text("\\indexentry{Orphan}{3}\n\\indexentry{x{|book{1}}{1}\n")

    async def scenario(app, pilot):
        await pilot.pause(0.3)
        assert len(app.problems) == 2 and isinstance(app.doc.items[0], Entry)
        app.query_one("#tabs").active = "tab-problems"
        await pilot.pause()
        pt = app.query_one("#problems")
        pt.focus()
        await pilot.press("enter")
        assert app.query_one("#tabs").active == "tab-entries"
    run(p, scenario)


def test_quick_add_validation(idx):
    async def scenario(app, pilot):
        n = len(app.doc.items)
        await pilot.press("a")
        await type_(pilot, "Thing")
        for book, page, focus in [("7", "3", "qa-book"), ("1", "0", "qa-page"), ("1", "12-10", "qa-page"),
                                  ("1", "12-12", "qa-page"), ("1", "4-", "qa-page")]:
            app.query_one("#qa-book").value, app.query_one("#qa-page").value = book, page
            app.query_one("#qa-term").focus()
            await pilot.press("enter")
            await pilot.pause()
            assert len(app.doc.items) == n and app.focused.id == focus, (book, page)
        # the fields show the problem while typing
        assert app.query_one("#qa-page").has_class("-invalid")
        app.query_one("#qa-book").value = "9"
        await pilot.pause()
        assert app.query_one("#qa-book").has_class("-invalid")
        app.query_one("#qa-book").value, app.query_one("#qa-page").value = "1", "12-13"
        await pilot.pause()
        assert not app.query_one("#qa-book").has_class("-invalid")
        app.query_one("#qa-term").focus()
        await pilot.press("enter")
        await pilot.pause()
        assert app.doc.items[app.current_index()].to_line() == r"\indexentry{Thing|book{1}}{12-13}"
    run(idx, scenario)


def test_new_book(idx):
    async def scenario(app, pilot):
        await pilot.press("f3")
        assert isinstance(app.screen, NewBookDialog)
        assert app.screen.query_one("#book").value == "5"
        app.screen.query_one("#book").value = "4"
        await pilot.press("enter")
        assert isinstance(app.screen, NewBookDialog)
        app.screen.query_one("#book").value = ""
        await pilot.press("enter")
        assert isinstance(app.screen, NewBookDialog)
        app.screen.query_one("#book").value = "W"
        await pilot.press("enter")
        await pilot.pause()
        assert "W" in app.doc.books() and app.query_one("#qa-book").value == "W"
        assert app.doc.items[app.current_index()].section == "WORKBOOK SECTION"
        app.query_one("#qa-page").value = "3"
        await pilot.press("a")
        await type_(pilot, "Lab")
        await pilot.press("enter")
        await pilot.pause()
        assert app.doc.items[app.current_index()].to_line() == r"\indexentry{Lab|book{W}}{3}"
        await pilot.press("escape", "ctrl+z", "ctrl+z")
        assert "W" not in app.doc.books()
    run(idx, scenario)


def test_new_index_has_no_book(tmp_path):
    async def scenario(app, pilot):
        assert app.doc.books() == [] and app.query_one("#qa-book").value == ""
        await pilot.press("f3")
        assert app.screen.query_one("#book").value == "1"
        await pilot.press("enter")
        await pilot.pause()
        assert app.doc.books() == ["1"]
    run(tmp_path / "new.idx", scenario)


def test_edit_dialog_validation(idx):
    async def scenario(app, pilot):
        i = next(i for i, e in app.doc.entries() if e.path == ("Last reference", ))
        app.select_item(i)
        await pilot.press("enter")
        dlg = app.screen
        for field, value in [("#page", "0"), ("#page", "90-89"), ("#book", "8")]:
            dlg.query_one("#page").value, dlg.query_one("#book").value = "89", "4"
            dlg.query_one(field).value = value
            await pilot.pause()
            assert dlg.query_one(field).has_class("-invalid")
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert app.screen is dlg, (field, value)
        dlg.query_one("#book").value, dlg.query_one("#page").value = "3", "89-90"
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        # moved to the section of book 3
        j = app.current_index()
        assert app.doc.items[j].to_line() == r"\indexentry{Last reference|book{3}}{89-90}"
        assert app.doc.section_of(j) == "THIRD BOOK SECTION"
        # page 0 is fine for a blank line (not a reference)
        j = next(i for i, e in app.doc.entries() if e.kind == "spacer")
        app.select_item(j)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert not isinstance(app.screen, EntryDialog)
    run(idx, scenario)


def test_edit_keeps_existing_invalid_page(tmp_path):
    p = tmp_path / "sec573.idx"
    p.write_text("\\indexentry{Workshop!Lists|book{W}}{2-2}\n")

    async def scenario(app, pilot):
        app.select_item(0)
        await pilot.press("enter")
        dlg = app.screen
        dlg.query_one("#text1").value = "Lists and tuples"
        await pilot.pause()
        assert not dlg.query_one("#page").has_class("-invalid")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.doc.items[0].to_line() == r"\indexentry{Workshop!Lists and tuples|book{W}}{2-2}"
        await pilot.pause(0.3)
        assert any("page '2-2'" in pb.message for pb in app.problems)
    run(p, scenario)


def test_sections_tab(idx):
    async def scenario(app, pilot):
        tabs = app.query_one("#tabs")
        assert [str(t.label) for t in tabs.query("Tab")][:4] == ["Entries", "Sections", "Preview", "Problems"]
        await pilot.press("f4")
        assert tabs.active == "tab-sections"
        pane = app.query_one("#sections-pane", SectionsPane)
        table = pane.table
        assert app.focused is table and table.row_count == 7
        table.move_cursor(row=3)                       # SECOND BOOK SECTION
        await pilot.press("e")
        dlg = app.screen
        assert isinstance(dlg, SectionDialog)
        dlg.query_one("#book").value = "5"
        await pilot.pause()
        assert dlg.query_one("#title").value == "FIFTH BOOK SECTION"
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is app.main and "2" not in app.doc.books() and "5" in app.doc.books()
        assert r"\indexentry{A useful reference|book{5}}{72}" in app.doc.dumps()
        assert "FIFTH BOOK SECTION" in str(table.get_row_at(3)[0])
        # conflicting book refused
        await pilot.press("enter")
        app.screen.query_one("#book").value = "3"
        await pilot.pause()
        await pilot.press("enter")
        assert isinstance(app.screen, SectionDialog)
        await pilot.press("escape")
        # move (key and button), new, delete
        await pilot.press("alt+up")
        assert [t for _, t in app.doc.sections()][2] == "FIFTH BOOK SECTION"
        await pilot.click("#sections-pane #down")
        assert [t for _, t in app.doc.sections()][3] == "FIFTH BOOK SECTION"
        await pilot.press("n")
        app.screen.query_one("#title").value = "Labs"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert "LABS SECTION" in [t for _, t in app.doc.sections()] and table.row_count == 8
        await pilot.press("d")
        assert "LABS SECTION" not in [t for _, t in app.doc.sections()]
        table.move_cursor(row=1)
        await pilot.press("d")                         # CATEGORIES header holds comments
        assert table.row_count == 7
        # undo also updates the tab
        await pilot.press("ctrl+z")
        assert table.row_count == 8
        await pilot.press("g")
        await pilot.pause()
        assert tabs.active == "tab-entries" and app.doc.items[app.current_index()].section == "CATEGORIES SECTION"
        for _ in range(5):
            await pilot.press("ctrl+z")
        assert app.doc.dumps() == (DATA / "main.idx").read_text()
    run(idx, scenario)


def test_quick_add_at_top_of_entries(idx):
    async def scenario(app, pilot):
        bar, table = app.query_one("#quickadd"), app.query_one("#table")
        assert bar.parent.id == "tab-entries" and bar.region.y < table.region.y
        app.query_one("#tabs").active = "tab-preview"
        await pilot.pause()
        app.table.focus()
        await pilot.press("a")
        await pilot.pause()
        assert app.query_one("#tabs").active == "tab-entries" and app.focused.id == "qa-term"
        await type_(pilot, "useful")
        sugg = app.query_one("#suggestions")
        assert sugg.region.y > bar.region.y and sugg.region.y < table.region.y
    run(idx, scenario)


def test_edit_section_from_sidebar(idx):
    async def scenario(app, pilot):
        sl = app.query_one("#sections")
        sl.focus()
        sl.highlighted = 2                             # FIRST BOOK SECTION
        await pilot.press("e")
        dlg = app.screen
        assert isinstance(dlg, SectionDialog)
        dlg.query_one("#renumber").value = False
        dlg.query_one("#title").value = "Introduction"
        dlg.query_one("#book").value = "1"
        await pilot.pause()
        assert "INTRODUCTION (BOOK 1) SECTION" in str(dlg.query_one("#section-preview").render())
        await pilot.press("enter")
        await pilot.pause()
        assert app.doc.items[app.doc.sections()[2][0]].section == "INTRODUCTION (BOOK 1) SECTION"
        assert "Introduction (Book 1)" in str(sl.get_option_at_index(2).prompt)
    run(idx, scenario)


def test_collapsed_sections(idx):
    async def scenario(app, pilot):
        t = app.table
        headers = [i for i, _ in app.doc.sections()]
        # all the sections are collapsed: only the comments before them and the headers are shown
        assert all(app.is_header_row(r) for r, i in enumerate(app.row_items) if i >= headers[0])
        assert "▶" in t.rows[app.item_rows[headers[2]]][1].plain
        app.table.move_cursor(app.item_rows[headers[2]])
        await pilot.press("right")
        assert "FIRST BOOK SECTION" in app.expanded
        assert "▼" in t.rows[app.item_rows[headers[2]]][1].plain
        n = len(app.row_items)
        await pilot.press("down", "left")
        assert len(app.row_items) < n and app.current_index() == headers[2]
        await pilot.press("enter")
        assert "FIRST BOOK SECTION" in app.expanded
        await pilot.press("space")
        assert "FIRST BOOK SECTION" not in app.expanded
        await pilot.press("plus")
        assert app.expanded == {t for _, t in app.doc.sections()}
        await pilot.press("minus")
        assert not app.expanded
        # the filter shows the matching entries of all the sections
        await pilot.press("slash")
        await pilot.press(*"reference")
        await pilot.pause()
        assert any(isinstance(app.doc.items[i], Entry) for i in app.row_items)
        await pilot.press("escape")
        # adding a reference shows it in its (expanded) section
        await pilot.press("a")
        app.main.query_one("#qa-book").value, app.main.query_one("#qa-page").value = "2", "5"
        app.main.query_one("#qa-term").value = "Zebra"
        app.add_from_bar()
        await pilot.pause()
        assert "SECOND BOOK SECTION" in app.expanded
        i = next(i for i, e in app.doc.entries() if e.path == ("Zebra", ))
        assert app.doc.section_of(i) == "SECOND BOOK SECTION" and i in app.item_rows
    run(idx, scenario)


def test_chapters_linked_to_sections(tmp_path):
    p = tmp_path / "sec588.idx"
    shutil.copy(DATA / "sec588.idx", p)

    async def scenario(app, pilot):
        tabs = app.query_one("#tabs")
        await pilot.press("f4")
        table = app.query_one("#sections-pane", SectionsPane).table
        row = [t for _, t in app.doc.sections()].index("SECOND BOOK SECTION")
        assert str(table.get_row_at(row)[3]) == "Attacking Identity Systems"
        table.move_cursor(row=row)
        # the chapter is edited with the section
        await pilot.press("e")
        dlg = app.screen
        assert isinstance(dlg, SectionDialog) and dlg.query_one("#chapter").value == "Attacking Identity Systems"
        dlg.query_one("#chapter").value = "Identity a{"
        await pilot.pause()
        assert "unbalanced" in str(dlg.query_one("#section-preview").render())
        await pilot.press("enter")
        assert app.screen is dlg
        dlg.query_one("#chapter").value = r"Identity \& Access"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is app.main and str(table.get_row_at(row)[3]) == "Identity & Access"
        assert r"\indexentry{1c@\textbf{Identity \& Access}!1@Mapping Process|book{2}}{5-12}" in app.doc.dumps()
        # t: from the section to its title, s: back
        await pilot.press("t")
        await pilot.pause()
        assert tabs.active == "tab-entries"
        assert app.doc.items[app.current_index()].path[0] == r"1c@\textbf{Identity \& Access}"
        await pilot.press("s")
        await pilot.pause()
        assert tabs.active == "tab-sections" and table.cursor_row == row
        await pilot.press("ctrl+z")
        assert app.doc.dumps() == (DATA / "sec588.idx").read_text()
    run(p, scenario)


def test_book_title_after_single_lines(tmp_path):
    p = tmp_path / "main.idx"
    p.write_text(TOPICS_FIRST_BOOK)

    async def scenario(app, pilot):
        await pilot.press("f4")
        table = app.query_one("#sections-pane", SectionsPane).table
        assert [str(c.label) for c in table.columns.values()][:4] == ["Index Section Title", "Kind", "Book", "Title"]
        table.move_cursor(row=1)                       # FIRST BOOK SECTION
        assert str(table.get_row_at(1)[3]) == "Foundations"
        await pilot.press("e")
        dlg = app.screen
        assert dlg.query_one("#chapter").value == "Foundations" and not dlg.query_one("#chapter").disabled
        assert [str(lb.render()) for lb in dlg.query("#section-grid Label")] == ["Index section title", "Book", "Title"]
        dlg.query_one("#chapter").value = "Strategic Foundations"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert r"\indexentry{1a@\textbf{Learning Objectives}|book{1}}{8}" in app.doc.dumps()
        assert r"\indexentry{2a@\textbf{Strategic Foundations}!1@Overview|book{1}}{6-22}" in app.doc.dumps()
    run(p, scenario)


def test_no_book_title(idx):
    async def scenario(app, pilot):
        await pilot.press("f4")
        table = app.query_one("#sections-pane", SectionsPane).table
        table.move_cursor(row=2)                       # FIRST BOOK SECTION: single lines only
        assert str(table.get_row_at(2)[3]) == ""
        await pilot.press("e")
        assert not app.screen.query("#chapter")
        await pilot.press("escape")
        await pilot.press("t")
        assert app.query_one("#tabs").active == "tab-sections"
    run(idx, scenario)


def test_book_title_locked_in_entries(tmp_path):
    p = tmp_path / "main.idx"
    p.write_text(TOPICS_FIRST_BOOK)

    async def scenario(app, pilot):
        part = next(i for i, e in app.doc.entries() if e.path[-1] == "1@Overview")
        app.goto_item(part)
        await pilot.press("e")
        dlg = app.screen
        assert isinstance(dlg, EntryDialog) and dlg.query_one("#text0").disabled and dlg.query_one("#key0").disabled
        assert app.focused is dlg.query_one("#text1")
        # the raw line cannot change the title either
        raw = dlg.query_one("#raw")
        raw.focus()
        raw.value = raw.value.replace("Foundations", "Other")
        await pilot.pause()
        assert "title of book 1" in str(dlg.query_one("#entry-preview").render())
        assert dlg.entry.path[0] == r"2a@\textbf{Foundations}"
        raw.value = raw.value.replace("Other", "Foundations").replace("Overview", "Outline")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert r"\indexentry{2a@\textbf{Foundations}!1@Outline|book{1}}{6-22}" in app.doc.dumps()
        # a single line of the Topics is not a book title: its first level stays editable
        app.goto_item(next(i for i, e in app.doc.entries() if "Learning" in e.key))
        await pilot.press("e")
        assert not app.screen.query_one("#text0").disabled
    run(p, scenario)


def test_course_in_sidebar(idx):
    async def scenario(app, pilot):
        info = app.query_one("#course-info")
        assert not info.query("Input") and not info.can_focus

        def shown():
            grid = info.content
            return {str(a): str(b) for a, b in zip(grid.columns[0]._cells, grid.columns[1]._cells)}
        assert shown()["Code"] == app.course.code and shown()["Author"] == "—"
        await pilot.press("f2")
        dlg = app.screen
        assert isinstance(dlg, CourseDialog)
        dlg.query_one("#version").value = r"V1\_02"
        dlg.query_one("#author").value = "A. Author"
        await pilot.press("enter")
        await pilot.pause()
        assert shown()["Version"] == "V1_02" and shown()["Author"] == "A. Author"
    run(idx, scenario)


def test_correct_malformed_entry(tmp_path):
    p = tmp_path / "main.idx"
    text = (DATA / "main.idx").read_text()
    p.write_text(text.replace(r"\indexentry{A useful reference|book{2}}{72}",
                              r"\indexentry{A useful{ reference|book{2}}{72}"))

    async def scenario(app, pilot):
        i = next(k for k, it in enumerate(app.doc.items) if getattr(it, "is_malformed_entry", False))
        await pilot.pause(0.3)
        assert any(pb.index == i and pb.severity == "error" for pb in app.problems)
        app.goto_item(i)
        await pilot.press("e")
        dlg = app.screen
        assert isinstance(dlg, EntryDialog)
        assert dlg.query_one("#raw").value == r"\indexentry{A useful{ reference|book{2}}{72}"
        assert dlg.query_one("#text0").value == "A useful{ reference" and dlg.query_one("#book").value == "2"
        assert "malformed" in str(dlg.query_one("#entry-preview").render())
        await pilot.press("ctrl+s")
        assert app.screen is dlg                       # still malformed: refused
        dlg.query_one("#text0").value = "A useful reference"
        await pilot.pause()
        assert dlg.query_one("#raw").value == r"\indexentry{A useful reference|book{2}}{72}"
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.screen is app.main and app.doc.dumps() == text
        await pilot.pause(0.3)
        assert not any(pb.severity == "error" for pb in app.problems)
    run(p, scenario)


def test_double_click_opens_one_editor(idx):
    async def scenario(app, pilot):
        i = next(k for k, e in app.doc.entries() if "A useful" in e.key)
        app.goto_item(i)
        await pilot.pause()
        offset = (20, app.row_items.index(i) - app.table.scroll_offset.y + 1)
        await pilot.click("#table", offset=offset, times=3)
        await pilot.pause()
        assert [type(s).__name__ for s in app.screen_stack] == ["Screen", "EntryDialog"]
        await pilot.click("#book")
        await pilot.press("end", "backspace", "3")
        await pilot.click("#ok")
        await pilot.pause()
        # saved at once, the entry moved to the section of book 3, and no other editor left behind
        assert app.screen is app.main and r"\indexentry{A useful reference|book{3}}{72}" in app.doc.dumps()
        # a click on the caret of a header still toggles its section once
        app.goto_item(app.doc.sections()[0][0])
        await pilot.pause()
        head = app.table.cursor_row
        opened = app.doc.sections()[0][1] in app.expanded
        await pilot.click("#table", offset=(7, head - app.table.scroll_offset.y + 1))
        await pilot.pause()
        assert (app.doc.sections()[0][1] in app.expanded) != opened
    run(idx, scenario)


def test_sections_table_fills_the_pane(tmp_path):
    p = tmp_path / "sec588.idx"
    shutil.copy(DATA / "sec588.idx", p)

    async def scenario(app, pilot):
        await pilot.press("f4")
        await pilot.pause(0.3)
        table = app.query_one("#sections-pane", SectionsPane).table

        def total():
            return sum(c.get_render_width(table) for c in table.columns.values())
        assert total() == table.scrollable_content_region.width
        # the editor of a book section starts on the title of the book
        table.move_cursor(row=3)
        await pilot.press("e")
        assert app.focused.id == "chapter"
        await pilot.press("escape")
        # and of another section on its title
        table.move_cursor(row=0)
        await pilot.press("e")
        assert app.focused.id == "title"
        await pilot.press("escape")
        for width in (180, 120):                       # wider, then too narrow: the titles are cut
            await pilot.resize_terminal(width, 45)
            await pilot.pause(0.3)
            assert total() == table.scrollable_content_region.width
        assert any(str(table.get_row_at(r)[3]).endswith("…") for r in range(table.row_count))
    run(p, scenario)
