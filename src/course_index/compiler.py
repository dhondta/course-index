# -*- coding: UTF-8 -*-
"""Compilation of a course index to PDF with makeindex and pdflatex."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .course import CourseInfo, data_file_for
from .idx import Document, Raw

__all__ = ["BuildResult", "TEMPLATE", "compile_pdf", "init_project", "missing_tools", "open_file", "template_dir"]

TEMPLATE = Path(__file__).parent / "template"
TIMEOUT = 300


@dataclass
class BuildResult:
    """Outcome of a compilation."""
    ok: bool
    pdf: Path | None = None
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    log: str = ""

    @property
    def summary(self):
        if self.ok:
            w = f" ({len(self.warnings)} warning{'s'[:len(self.warnings) != 1]})" if self.warnings else ""
            return f"PDF written to {self.pdf}{w}"
        return self.errors[0] if self.errors else "compilation failed"


def missing_tools():
    """List of the required programs that are not installed."""
    return [t for t in ("makeindex", "pdflatex") if shutil.which(t) is None]


def template_dir(idx_path):
    """Folder holding main.tex and lib/ for an index: its own folder if it is a template project, else the bundled
    template."""
    folder = Path(idx_path).resolve().parent
    if (folder / "main.tex").is_file() and (folder / "lib" / "std.ist").is_file():
        return folder
    return TEMPLATE


def init_project(folder, force=False):
    """Copy the template (main.tex, data.tex, lib/) into a folder, keeping existing files unless forced."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    copied = []
    for src in sorted(TEMPLATE.rglob("*")):
        if src.is_dir() or "__pycache__" in src.parts:
            continue
        dst = folder / src.relative_to(TEMPLATE)
        if dst.exists() and not force:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(dst)
    return copied


def _comment_lines(doc):
    """File line numbers belonging to comment blocks (makeindex parses their examples of \\indexentry too)."""
    lines, n = set(), 1
    for it in doc.items:
        count = it.text.count("\n") + 1 if isinstance(it, Raw) else 1
        if isinstance(it, Raw) and (it.is_comment_block or it.text.lstrip().startswith("%")):
            lines.update(range(n, n + count))
        n += count
    return lines


def _parse_ilg(ilg, ignored):
    """Extract the errors and warnings of a makeindex log, skipping those located in comment blocks."""
    errors, warnings = [], []
    for m in re.finditer(r"^(!! Input index error|## Warning) \((?:file|input) = [^,]*, line = (\d+)[^)]*\):\s*\n"
                         r"\s*-- (.*)$", ilg, re.M):
        line = int(m.group(2))
        if line in ignored:
            continue
        msg = f"line {line}: {m.group(3).strip()}"
        (errors if m.group(1).startswith("!!") else warnings).append(msg)
    return errors, warnings


def _parse_latex_log(log):
    """Extract the errors of a pdflatex log (lines starting with '!' and the line where they occurred)."""
    errors, lines = [], log.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("! "):
            ctx = next((x.strip() for x in lines[i+1:i+8] if re.match(r"^l\.\d+", x)), "")
            errors.append(line[2:].strip() + (f" ({ctx})" if ctx else ""))
    return errors


def compile_pdf(idx_path, output=None, document=None, course=None):
    """Compile an index to PDF.

    :param idx_path: path to the .idx file
    :param output:   PDF path (default: the .idx path with the .pdf extension)
    :param document: Document to compile instead of the content of the file (e.g. unsaved changes)
    :param course:   CourseInfo to use instead of the index's data file
    :return:         BuildResult
    """
    idx_path = Path(idx_path)
    output = Path(output) if output else idx_path.with_suffix(".pdf")
    missing = missing_tools()
    if missing:
        return BuildResult(False, errors=[f"{', '.join(missing)} not found: install a TeX distribution (e.g. "
                                          f"TeX Live with texlive-latex-extra)"])
    doc = document if document is not None else Document.load(idx_path)
    if not any(e.kind == "ref" for _, e in doc.entries()):
        # nothing to typeset (and makeindex 2.17 crashes on such an index)
        return BuildResult(False, errors=["the index has no references yet: add some before compiling"])
    if course is None:
        data = data_file_for(idx_path)
        course = CourseInfo.load(data) if data.exists() else CourseInfo.guess(idx_path)
    tpl = template_dir(idx_path)
    with tempfile.TemporaryDirectory(prefix="course-index-") as tmp:
        tmp = Path(tmp)
        shutil.copy2(tpl / "main.tex", tmp / "main.tex")
        shutil.copytree(tpl / "lib", tmp / "lib")
        original = (tpl / "data.tex").read_text(encoding="utf-8") if (tpl / "data.tex").exists() else None
        (tmp / "data.tex").write_text(course.dumps(original), encoding="utf-8")
        text = doc.dumps()
        # makeindex 2.17 segfaults on a file ending with non-entry text without a final newline
        (tmp / "main.idx").write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8", newline="")
        # files referenced with a relative path (images, \input, ...) are searched in the build folder, then in the
        # folder of the index and in the template's folder (the trailing separator keeps TeX's default path)
        folders = list(dict.fromkeys([str(idx_path.resolve().parent), str(tpl)]))
        env = {**os.environ, 'TEXINPUTS': os.pathsep.join([".", *folders, os.environ.get("TEXINPUTS", "")])}
        trace = [f"# build folder: {tmp}", f"# TEXINPUTS={env['TEXINPUTS']}"]
        try:
            cmd = ["makeindex", "-s", "lib/std.ist", "main.idx"]
            trace.append(f"$ {' '.join(cmd)}")
            mi = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, timeout=TIMEOUT, errors="replace",
                                env=env)
            ilg = (tmp / "main.ilg").read_text(errors="replace") if (tmp / "main.ilg").exists() else mi.stderr
            errors, warnings = _parse_ilg(ilg, _comment_lines(doc))
            if mi.returncode != 0 or not (tmp / "main.ind").exists():
                msg = f"makeindex crashed (exit code {mi.returncode})" if mi.returncode < 0 or mi.returncode > 128 \
                      else "makeindex failed"
                return BuildResult(False, errors=errors or [msg], warnings=warnings,
                                   log="\n".join(trace + [ilg.rstrip()]))
            trace.append(ilg.rstrip())
            # like Texmaker's quick build: do not halt on errors, a PDF is produced whenever possible
            cmd = ["pdflatex", "-interaction=nonstopmode", "main.tex"]
            trace += ["", f"$ {' '.join(cmd)}"]
            tex = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, timeout=TIMEOUT, errors="replace",
                                 env=env)
        except subprocess.TimeoutExpired as e:
            return BuildResult(False, errors=[f"{e.cmd[0]} timed out after {TIMEOUT} seconds"], log="\n".join(trace))
        log = (tmp / "main.log").read_text(errors="replace") if (tmp / "main.log").exists() else tex.stdout
        log = "\n".join(trace + [log])
        pdf = tmp / "main.pdf"
        latex_errors = _parse_latex_log(log)
        if not pdf.exists():
            return BuildResult(False, errors=latex_errors or ["pdflatex failed"], warnings=warnings, log=log)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pdf, output)
    return BuildResult(True, output, warnings=warnings + [f"LaTeX: {e}" for e in latex_errors], log=log)


def open_file(path):  # pragma: no cover
    """Open a file with the default application of the system (e.g. the PDF viewer)."""
    path = str(path)
    if sys.platform.startswith("win"):
        os.startfile(path)
        return
    cmd = ["open", path] if sys.platform == "darwin" else ["xdg-open", path]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
