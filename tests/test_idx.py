# -*- coding: UTF-8 -*-
from pathlib import Path

import pytest

from course_index.idx import Document, Entry, Level, book_sort_key, page_error, page_sort_key, sort_group

DATA = Path(__file__).parent / "data"
EXAMPLES = sorted(DATA.glob("*.idx"))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_roundtrip(path):
    text = path.read_text(encoding="utf-8")
    doc = Document.parse(text)
    assert doc.dumps() == text
    for _, e in doc.entries(False):
        # serializing from the parsed fields gives the original line back
        assert e.evolve().to_line() == e.raw


def test_crlf_and_no_final_newline():
    text = "\\indexentry{A|book{1}}{2}\r\n\\indexentry{B|book{1}}{3}"
    doc = Document.parse(text)
    assert doc.newline == "\r\n" and not doc.final_newline
    doc.add_reference("C", "1", "4")
    assert doc.dumps().count("\r\n") == doc.dumps().count("\n")
    assert Document.parse("").dumps() == ""


def test_parse_entry():
    e = Entry.parse(r'\indexentry{30@\textbf{Commands \linux}!\texttt{a"!b}|book{2}\lab}{12-14}')
    assert [str(lv) for lv in e.levels] == [r"30@\textbf{Commands \linux}", r'\texttt{a"!b}']
    assert e.book == "2" and e.encap_rest == r"\lab" and e.page == "12-14" and e.kind == "ref"
    assert Entry.parse(r"%\indexentry{A}{1}").disabled
    assert Entry.parse(r"\indexentry{A}{1} trailing") is None
    assert Entry.parse(r"\indexentry{A{}{1}") is None
    assert Entry.parse("text") is None
    assert Entry.parse(r"\indexentry{x@\blankline|comment}{0}").kind == "spacer"
    assert Entry.parse(r"\indexentry{999@\blankline|newpage \comment}{0}").kind == "pagebreak"
    assert Entry.parse(r"\indexentry{K8s \goto Kubernetes|comment}{0}").kind == "xref"
    assert Entry.parse(r"\indexentry{Something|comment}{0}").kind == "hidden"
    e = Entry.parse(r"\indexentry{A!B!  |book{3}}{4}")
    assert e.base_path == ("A", "B") and e.path == ("A", "B", "  ")
    assert Entry.parse(r"\indexentry{Cain@ |book{4}}{25}").base_path == ("Cain", )
    assert Entry.make("A!b@B", 3, "comment").to_line() == r"\indexentry{A!b@B|comment}{3}"
    assert str(Level.parse("k@t")) == "k@t" and Level.parse("k@t").sort == "k" and Level("t").sort == "t"


def test_helpers():
    assert sorted(["W", "10", "2", "1"], key=book_sort_key) == ["1", "2", "10", "W"]
    assert page_sort_key("18-46") == (18, 46) and page_sort_key("x") == (float("inf"), )
    assert [sort_group(k) for k in ("2a", "200", "Abc", "\\x")] == [0, 1, 2, 0]


def test_sections():
    doc = Document.load(DATA / "sec504.idx")
    titles = [t for _, t in doc.sections()]
    assert titles[:3] == ["TOPICS SECTION", "CATEGORIES SECTION", "SANS 504.1 SECTION"]
    assert [Document.section_book(t) for t in titles[2:7]] == ["1", "2", "3", "4", "5"]
    assert Document.section_book("THIRD BOOK SECTION") == "3"
    assert Document.section_book("WORKBOOK SECTION") == "W"
    assert Document.section_book("BOOK 7 SECTION") == "7"
    assert Document.section_book("TOOLS SECTION") is None
    assert Document.section_kind("CROSS-KEYS SECTION") == "xrefs"
    assert Document.section_kind("TOOLS SECTION") == "other"
    i = doc.sections()[3][0]
    assert doc.section_of(i + 1) == "SANS 504.2 SECTION" and doc.section_of(0) == "TOPICS SECTION"
    assert doc.books() == ["1", "2", "3", "4", "5", "6"]


@pytest.fixture
def doc():
    return Document.load(DATA / "main.idx")


def test_add_reference_new_term(doc):
    i = doc.add_reference("Brand new", "2", "17")
    assert doc.items[i].to_line() == r"\indexentry{Brand new|book{2}}{17}"
    assert doc.section_of(i) == "SECOND BOOK SECTION"
    # same book, later page: no book number
    j = doc.add_reference("Brand new", "2", "30")
    assert doc.items[j].to_line() == r"\indexentry{Brand new}{30}"
    # same book, earlier page: the book number moves to the first page
    k = doc.add_reference("Brand new", "2", "5")
    assert doc.items[k].to_line() == r"\indexentry{Brand new|book{2}}{5}"
    assert doc.items[i].to_line() == r"\indexentry{Brand new}{17}"
    # other books: one new line each
    m = doc.add_reference("Brand new", "3", "8")
    assert doc.items[m].to_line() == r"\indexentry{Brand new! |book{3}}{8}"
    n = doc.add_reference("Brand new", "4", "9")
    assert doc.items[n].to_line() == r"\indexentry{Brand new!  |book{4}}{9}"
    o = doc.add_reference("Brand new", "3", "10")
    assert doc.items[o].to_line() == r"\indexentry{Brand new! }{10}"
    assert doc.check() == []


def test_add_reference_idioms():
    doc = Document.parse("\\indexentry{Cain|book{1}}{53}\n\\indexentry{Cain@ |book{4}}{25}\n")
    i = doc.add_reference("Cain", "5", "7")
    assert doc.items[i].to_line() == r"\indexentry{Cain@  |book{5}}{7}"
    doc = Document.parse("\\indexentry{Lab|book{4}\\lab}{1}\n")
    i = doc.add_reference("Lab", "4", "2")
    assert doc.items[i].to_line() == r"\indexentry{Lab|book{4}\lab}{2}"


def test_add_reference_placement(doc):
    # existing category: right after its group
    i = doc.add_reference(r"200@\textbf{Tools}!Yet another tool", "4", "3")
    assert doc.items[i - 1].path[0] == r"200@\textbf{Tools}"
    assert doc.section_of(i) == "CATEGORIES SECTION"
    # new category: end of the categories section, before the page break
    j = doc.add_reference(r"300@\textbf{Standards}!ISO 27001", "1", "3")
    assert doc.section_of(j) == "CATEGORIES SECTION"
    assert next(e for e in doc.items[j + 1:] if isinstance(e, Entry)).kind == "pagebreak"
    # new topic
    k = doc.add_reference(r"3a@\textbf{Conclusion}", "4", "90")
    assert doc.section_of(k) == "TOPICS SECTION"
    # new book: new section, in order, before the cross-keys
    m = doc.add_reference("Workbook thing", "W", "3")
    assert doc.section_of(m) == "WORKBOOK SECTION"
    n = doc.add_reference("Fifth book thing", "5", "3")
    assert doc.section_of(n) == "FIFTH BOOK SECTION"
    titles = [t for _, t in doc.sections()]
    assert titles.index("FIFTH BOOK SECTION") < titles.index("WORKBOOK SECTION") < titles.index("CROSS-KEYS SECTION")
    o = doc.add_reference("Book zero", "0", "1")
    assert doc.section_of(o) == "BOOK 0 SECTION"
    assert titles.index("FIRST BOOK SECTION") > [t for _, t in doc.sections()].index("BOOK 0 SECTION") - 1
    assert Document.parse(doc.dumps()).dumps() == doc.dumps()


def test_add_reference_without_sections():
    doc = Document()
    i = doc.add_reference("A", "1", "1")
    assert doc.section_of(i) == "FIRST BOOK SECTION"
    j = doc.add_xref("B", "A")
    assert doc.section_of(j) == "CROSS-KEYS SECTION"
    assert doc.items[j].to_line() == r"\indexentry{B \goto A|comment}{0}"


def test_spacers(doc):
    i = [i for i, e in doc.entries() if e.path[0] == r"200@\textbf{Tools}"][-1]
    j = doc.add_spacer(i)
    assert doc.items[j].to_line() == r"\indexentry{201@\blankline|comment}{0}"
    i = [i for i, e in doc.entries() if e.path[0] == r"2a@\textbf{Chapters}"][-1]
    j = doc.add_spacer(i, pagebreak=True)
    assert doc.items[j].to_line() == r"\indexentry{2z@\blankline|newpage \comment}{0}"
    i = [i for i, e in doc.entries() if e.path[0] == "Last reference"][0]
    assert doc.items[doc.add_spacer(i)].top.key == "Lzzzzzz"
    assert doc.items[doc.add_spacer(1)].top.key in ("1z", "1bz")
    doc.items.insert(0, Entry.make(r"21@\textbf{Taken}", "1", "book{1}"))
    with pytest.raises(ValueError):
        doc.add_spacer([i for i, e in doc.entries() if e.path[0] == r"20@\textbf{Basic Principles}"][0])


def test_check():
    doc = Document.parse("\n".join([
        r"\indexentry{Orphan}{3}",
        r"\indexentry{A|book{1}}{10}",
        r"\indexentry{A}{5}",
        r"\indexentry{B|book{1}}{1}",
        r"\indexentry{B|book{1}}{1}",
        r"\indexentry{\texttt{x}|book{1}}{x}",
        r"\indexentry{C \unknowncmd|book{1}}{1}",
        r"\indexentry{broken{|book{1}}{1}",
    ]))
    msgs = [(p.index, p.severity, p.message.split(" ")[0]) for p in doc.check({"texttt"})]
    assert (0, "warning", "no") in msgs
    assert (1, "warning", "book") in msgs
    assert (4, "warning", "duplicate") in msgs
    assert (5, "warning", "page") in msgs and (5, "warning", "starts") in msgs
    assert (6, "warning", "unknown") in msgs
    assert (7, "error", "malformed") in msgs
    assert doc.line_numbers() == list(range(1, 9))


def test_page_error():
    assert page_error("45") is None and page_error("45-47") is None and page_error(" 1 ") is None
    assert page_error("0") == "the page cannot be 0"
    assert page_error("0-3") == "the page cannot be 0"
    assert page_error("47-45") == "the end of the range must be greater than 47"
    assert page_error("45-45") == "the end of the range must be greater than 45"
    for bad in ("", "x", "4-", "-4", "1-2-3", "4 5"):
        assert page_error(bad).startswith("the page must be")
    doc = Document.parse("\\indexentry{A|book{1}}{75-58}\n\\indexentry{B|book{1}}{0}\n"
                         "\\indexentry{1z@\\blankline|comment}{0}\n")
    assert [(p.index, p.message) for p in doc.check()] == [
        (0, "page '75-58': the end of the range must be greater than 75"), (1, "page '0': the page cannot be 0")]


def test_add_book():
    doc = Document.parse((DATA / "main.idx").read_text())
    i = doc.add_book("5")
    assert doc.items[i].section == "FIFTH BOOK SECTION" and "5" in doc.books()
    with pytest.raises(ValueError):
        doc.add_book("5")
    with pytest.raises(ValueError):
        doc.add_book("5!")
    doc = Document()
    assert doc.books() == [] and doc.items[doc.add_book("W")].section == "WORKBOOK SECTION"


def test_retitle():
    rt = Document.retitle
    assert rt("SANS 504.1 SECTION", "1", "2") == "SANS 504.2 SECTION"
    assert rt("FIRST BOOK SECTION", "1", "3") == "THIRD BOOK SECTION"
    assert rt("WORKBOOK SECTION", "W", "6") == "SIXTH BOOK SECTION"
    assert rt("BOOK 3 SECTION", "3", "12") == "BOOK 12 SECTION"
    assert rt("introduction", None, "1") == "INTRODUCTION (BOOK 1) SECTION"
    assert rt("INTRO (BOOK 4) SECTION", "4", "2") == "INTRO (BOOK 2) SECTION"
    assert rt("SECOND BOOK SECTION", "2", "2") == "SECOND BOOK SECTION"
    assert Document.section_book("WORKBOOK (BOOK 7) SECTION") == "7"


def test_sections_management():
    doc = Document.load(DATA / "sec504.idx")
    titles = lambda: [t for _, t in doc.sections()]  # noqa: E731
    first = doc.sections()[2][0]
    n = doc.book_usage("1")
    assert doc.set_section(first, "SANS 504.1 SECTION", "7", renumber=True) == n > 200
    assert doc.items[first].section == "SANS 504.7 SECTION" and "1" not in doc.books() and doc.book_usage("7") == n
    # renaming keeps the book ; a book without renumbering keeps the entries
    assert doc.set_section(first, "Introduction", None) == 0
    assert doc.items[first].section == "INTRODUCTION SECTION" and "7" in doc.books()
    doc.set_section(first, "Introduction", "1")
    assert doc.items[first].section == "INTRODUCTION (BOOK 1) SECTION" and doc.book_usage("7") == n
    with pytest.raises(ValueError, match="already has a section"):
        doc.set_section(first, "x", "2")
    with pytest.raises(ValueError, match="cannot be dedicated"):
        doc.set_section(doc.sections()[1][0], "CATEGORIES", "9")
    with pytest.raises(ValueError, match="already a section"):
        doc.set_section(first, "TOOLS")
    with pytest.raises(ValueError, match="cannot contain"):
        doc.set_section(first, "a*b")
    with pytest.raises(ValueError, match="empty"):
        doc.set_section(first, "  ")
    # move
    j = doc.move_section(first, 1)
    assert titles()[2:4] == ["SANS 504.2 SECTION", "INTRODUCTION (BOOK 1) SECTION"] and doc.items[j].section == titles()[3]
    j = doc.move_section(j, -1)
    assert titles()[2] == "INTRODUCTION (BOOK 1) SECTION" and doc.items[j].section == titles()[2]
    last = doc.sections()[-1][0]
    assert doc.move_section(last, 1) == last
    j = doc.move_section(last, -1)
    assert titles()[-2:] == ["TOOLS SECTION", "SANS 504.5 SECTION"]
    # add and delete
    k = doc.add_section("Labs", None, first)
    assert doc.items[k].section == "LABS SECTION" and titles()[3] == "LABS SECTION"
    k2 = doc.add_section("Workbook", "W")
    assert doc.items[k2].section == "WORKBOOK SECTION" and titles()[-1] == "WORKBOOK SECTION"
    doc.delete_section(k)
    assert "LABS SECTION" not in titles()
    with pytest.raises(ValueError, match="comments"):
        doc.delete_section(doc.sections()[1][0])
    assert doc.section_entries(doc.sections()[2][0]) > 100
    assert Document.parse(doc.dumps()).dumps() == doc.dumps()


def test_place_in_book_block():
    doc = Document.load(DATA / "main.idx")
    first = next(i for i, e in doc.entries() if doc.section_of(i) == "FIRST BOOK SECTION")
    # after a line of book 1: an entry of book 1 stays there, one of book 2 goes to the block of book 2
    assert doc.place(Entry.make("Alpha", "3", "book{1}"), first) == first + 1
    j = doc.place(Entry.make("Beta", "3", "book{2}"), first)
    assert doc.section_of(j) == "SECOND BOOK SECTION"
    # a category goes to the Categories, wherever it is added
    k = doc.place(Entry.make("200@\\textbf{Tools}!Gamma", "4", "book{2}"), first)
    assert doc.section_of(k) == "CATEGORIES SECTION"
    # changing the book of an entry moves it to the block of its new book
    a = next(i for i, e in doc.entries() if e.path == ("Alpha", ))
    doc.items[a] = doc.items[a].evolve(encap="book{3}")
    m = doc.relocate(a)
    assert doc.section_of(m) == "THIRD BOOK SECTION" and doc.items[m].path == ("Alpha", )
    assert doc.relocate(m) == m


def test_chapters():
    doc = Document.load(DATA / "sec588.idx")
    chapters = doc.chapters()
    assert sorted(chapters) == ["1", "2", "3", "4", "5"]
    assert Document.chapter_title(chapters["3"]) == r"Attacking \& Abusing Cloud Services"
    assert Document.chapter_title("Plain") == "Plain" and Document.chapter_title(r"1a@\textbf{A} \linux") == "A"
    # single lines (no parts) and groups spanning several books are not chapters
    assert Document.load(DATA / "main.idx").chapters() == {}
    assert Document.chapter_title(Document.load(DATA / "sec504.idx").chapters()["1"]) == \
        "6-step Incident Handling Process"
    top = chapters["2"]
    n = len([1 for _, e in doc.entries(False) if e.path[0] == top])
    assert doc.rename_chapter(top, r"Identity  \& Access ") == n
    assert Document.chapter_title(doc.chapters()["2"]) == r"Identity \& Access"
    assert r"\indexentry{1c@\textbf{Identity \& Access}!1@Mapping Process|book{2}}{5-12}" in doc.dumps()
    for bad in ("", "a{b", "a!b", "a@b", "a|b"):
        with pytest.raises(ValueError):
            doc.rename_chapter(doc.chapters()["2"], bad)
    assert doc.rename_chapter(doc.chapters()["2"], 'Who"!') == n


def test_chapter_after_single_lines():
    doc = Document.parse(TOPICS_FIRST_BOOK)
    assert {b: Document.chapter_title(t) for b, t in doc.chapters().items()} == {"1": "Foundations"}


TOPICS_FIRST_BOOK = r"""\comment{****
                                          TOPICS SECTION
****}
\indexentry{0b@\textbf{Process}\hfill|comment}{0}
\indexentry{1a@\textbf{Learning Objectives}|book{1}}{8}
\indexentry{1b@\blankline|comment}{0}
\indexentry{2a@\textbf{Foundations}!1@Overview|book{1}}{6-22}
\indexentry{2a@\textbf{Foundations}!2@Business|book{1}}{36-37}
\indexentry{2z@\blankline|comment}{0}

\comment{****
                                       FIRST BOOK SECTION
****}
"""


def test_salvage_malformed():
    from course_index.idx import Raw
    doc = Document.parse("\\indexentry{broken{|book{1}}{1}\n%\\indexentry{A{}{1}\n\\comment{x}\n")
    assert doc.items[0].is_malformed_entry and doc.items[1].is_malformed_entry and not doc.items[2].is_malformed_entry
    e = Entry.salvage(doc.items[0].text)
    assert e.levels[0].text == "broken{" and e.book == "1" and e.page == "1" and not e.is_valid
    assert Entry.salvage(r"%\indexentry{A{}{1}").disabled
    assert Entry.salvage(r"\indexentry{A}{1} trailing").to_line() == r"\indexentry{A}{1}"
    assert Entry.salvage(r"\indexentry{A!B|book{2}}{3").to_line() == r"\indexentry{A!B|book{2}}{3}"
    assert not Raw(r"\indexentry{A}{1} x").is_comment_block and Raw(r"\indexentry{A}{1} x").is_malformed_entry
