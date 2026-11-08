# -*- coding: UTF-8 -*-
import shutil
from pathlib import Path

import pytest

from course_index.__main__ import main
from course_index.compiler import BuildResult, TEMPLATE, _parse_ilg, _parse_latex_log, compile_pdf, init_project, \
                                 missing_tools, template_dir
from course_index.course import CourseInfo, data_file_for
from course_index.idx import Document
from course_index.latex import auto_sort_key, expand_shortcuts, known_commands, plain, render
from course_index.preview import build, format_pages

DATA = Path(__file__).parent / "data"
needs_tex = pytest.mark.skipif(bool(missing_tools()), reason="makeindex/pdflatex not installed")


# ---------------------------------------------------------------- latex
def test_render():
    assert plain(r"\textbf{Commands \linux}") == "Commands 🐧"
    assert plain(r"\texttt{nc} \rate{3}") == "nc ★★★"
    assert plain(r"A \goto B") == "A → B"
    assert plain(r"Cain \& Abel -- x~y") == "Cain & Abel – x y"
    assert plain(r"\icon{go} \icon{unknown} \hskip10pt z \hspace{5pt}") == "🐹 [unknown] z"
    assert plain(r"\textcolor{red}{R} $\star$ \foo") == r"R ★ \foo"
    assert plain(r"\linux", icons=False) == ""
    t = render(r"\textbf{B}\texttt{t}")
    assert t.plain == "Bt" and {str(s.style) for s in t.spans} == {"bold", "cyan"}


def test_shortcuts_and_keys():
    assert expand_shortcuts("`nc` -l :linux: a_b & **bold** *it* :nope:") == \
        r"\texttt{nc} -l \linux a\_b \& \textbf{bold} \textit{it} :nope:"
    assert expand_shortcuts(r"already \_ escaped") == r"already \_ escaped"
    assert auto_sort_key(r"\texttt{.htaccess}") == "Htaccess"
    assert auto_sort_key("plain") is None and auto_sort_key(r"\blankline") is None and auto_sort_key(r"\linux") is None
    cmds = known_commands((TEMPLATE / "main.tex").read_text())
    assert {"linux", "book", "rate", "goto", "textbf"} <= cmds and "ukey" not in cmds


# ---------------------------------------------------------------- course
def test_course(tmp_path):
    info = CourseInfo.load(TEMPLATE / "data.tex")
    assert info.code == "123" and info.display_title == "C123 – Course Title" and info.author == ""
    info.author, info.version = "Me", "v2"
    text = info.dumps((TEMPLATE / "data.tex").read_text())
    assert r"\def\indexauthor{Me}" in text and r"\def\courseversion{v2}" in text
    info.author = ""
    assert "indexauthor" not in info.dumps(text)
    p = tmp_path / "data.tex"
    info.save(p)
    assert CourseInfo.load(p) == info
    assert CourseInfo.guess("x/sec504.idx").code == "504" and CourseInfo.guess("main.idx").code == "123"
    assert data_file_for(tmp_path / "main.idx") == p
    assert data_file_for(tmp_path / "sec1.idx") == p
    p.unlink()
    assert data_file_for(tmp_path / "sec1.idx").name == "sec1.data.tex"


# ---------------------------------------------------------------- preview
def test_preview():
    doc = Document.load(DATA / "main.idx")
    groups = build(doc)
    assert [g for g, _ in groups][:2] == ["Topics", "Categories"]
    assert format_pages([("61", "book{2}"), ("5", None), ("1", "book{4}\\lab")], "123") == "123.4–L1, 5, 123.2–61"
    chapters = next(n for n in groups[0][1] if n.level.text == r"\textbf{Chapters}")
    assert [c.level.text for c in chapters.sorted_children()][0] == "1) First chapter"
    assert any(n.kind == "spacer" for n in groups[0][1])


# ---------------------------------------------------------------- compiler
def test_compiler_helpers(tmp_path):
    assert template_dir(tmp_path / "x.idx") == TEMPLATE
    init_project(tmp_path)
    assert (tmp_path / "lib" / "std.ist").exists() and template_dir(tmp_path / "x.idx") == tmp_path.resolve()
    ilg = ("!! Input index error (file = main.idx, line = 3):\n   -- Extra `}'.\n"
           "## Warning (input = main.idx, line = 9; output = main.ind, line = 2):\n   -- Conflicting entries.\n")
    assert _parse_ilg(ilg, {3}) == ([], ["line 9: Conflicting entries."])
    assert _parse_latex_log("! Undefined control sequence.\nl.12 \\item x \\ukey\n") == \
        ["Undefined control sequence. (l.12 \\item x \\ukey)"]
    assert BuildResult(False).summary == "compilation failed"


@needs_tex
def test_compile(tmp_path):
    idx = tmp_path / "sec504.idx"
    shutil.copy(DATA / "sec504.idx", idx)
    r = compile_pdf(idx)
    assert r.ok and r.pdf.exists() and r.pdf.stat().st_size > 10000
    # sec504 uses \ukey, which the current template does not define: reported, but the PDF is produced
    assert any("ukey" in w for w in r.warnings)
    assert "warning" in r.summary
    doc = Document.load(DATA / "main.idx")
    r = compile_pdf(idx, tmp_path / "out" / "main.pdf", document=doc, course=CourseInfo(code="999"))
    assert r.ok and not r.warnings and r.summary.startswith("PDF written")


# ---------------------------------------------------------------- cli
def test_cli(tmp_path, capsys):
    idx = tmp_path / "sec504.idx"
    shutil.copy(DATA / "sec504.idx", idx)
    assert main([str(idx), "--check"]) == 0
    out = capsys.readouterr()
    assert "unknown command \\ukey" in out.out
    assert main([str(tmp_path / "nope.idx"), "--pdf"]) == 2
    (tmp_path / "bad.idx").write_text("\\indexentry{a{|book{1}}{1}\n")
    assert main([str(tmp_path / "bad.idx"), "--check"]) == 1
    with pytest.raises(SystemExit):
        main(["--version"])


@needs_tex
def test_cli_init_pdf(tmp_path):
    folder = tmp_path / "course"
    # a new index has no references yet
    assert main([str(folder), "--init", "--pdf"]) == 1
    assert (folder / "main.idx").exists() and (folder / "main.tex").exists() and not (folder / "main.pdf").exists()
    doc = Document.load(folder / "main.idx")
    doc.add_reference("First term", "1", "3")
    (folder / "main.idx").write_text(doc.dumps())
    assert main([str(folder) + "/", "--pdf"]) == 0
    assert (folder / "main.pdf").exists()


@pytest.mark.skipif(missing_tools(), reason="TeX not installed")
def test_compile_relative_image(tmp_path):
    (tmp_path / "img").mkdir()
    shutil.copy(TEMPLATE / "lib" / "linux.png", tmp_path / "img" / "pic.png")
    idx = tmp_path / "main.idx"
    idx.write_text("\\indexentry{Pic \\protect\\includegraphics[height=8pt]{img/pic}|book{1}}{3}\n")
    r = compile_pdf(idx)
    assert r.ok and not r.warnings
    assert r.log.splitlines()[2] == "$ makeindex -s lib/std.ist main.idx"
    assert "$ pdflatex -interaction=nonstopmode main.tex" in r.log
