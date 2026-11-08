# -*- coding: UTF-8 -*-
"""Command-line entry point: `course-index [FILE.idx]`."""
import argparse
import os
import sys
from pathlib import Path

from .__info__ import __source__, __version__
from .compiler import compile_pdf, init_project, open_file, template_dir
from .idx import Document
from .latex import known_commands

EXAMPLES = """examples:
  course-index                      edit main.idx in the current folder (created if missing)
  course-index sec504.idx           edit another index
  course-index sec504.idx --tui     edit it in the terminal instead of a window
  course-index --init mycourse/     copy the template (main.tex, data.tex, lib/) and start a new index there
  course-index sec504.idx --pdf     compile sec504.pdf without opening the editor
  course-index sec504.idx --check   list the problems of the index
"""


def _parser():
    p = argparse.ArgumentParser(prog="course-index", formatter_class=argparse.RawDescriptionHelpFormatter,
                                description="Edit a course index (LaTeX course index template) and compile it to PDF.",
                                epilog=EXAMPLES + f"\nsource: {__source__}")
    p.add_argument("path", nargs="?", default="main.idx",
                   help="index file, or folder holding main.idx (default: ./main.idx)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--pdf", action="store_true", help="compile the PDF and exit")
    g.add_argument("--check", action="store_true", help="check the index and exit (exit code 1 on errors)")
    p.add_argument("--init", action="store_true", help="copy the template files next to the index first")
    p.add_argument("-o", "--output", help="PDF path for --pdf (default: the index path with .pdf)")
    p.add_argument("--open", action="store_true", help="open the PDF after --pdf")
    p.add_argument("--no-viewer", action="store_true", help="do not open the PDF after compiling from the editor")
    p.add_argument("--tui", action="store_true", help="use the terminal user interface instead of the window")
    p.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _resolve(arg):
    """Index file of the given argument: a folder (existing, ending with a separator or without extension) means its
    main.idx."""
    path = Path(arg)
    if path.is_dir() or arg.endswith(("/", "\\")) or path.suffix == "" and not path.exists():
        path = path / "main.idx"
    return path


def has_display():
    """Whether a window can be opened (on Linux and BSD, an X11 or Wayland session is required)."""
    if sys.platform in ("win32", "darwin") or os.environ.get("QT_QPA_PLATFORM"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def check(path):
    doc = Document.load(path)
    tex = template_dir(path) / "main.tex"
    problems = doc.check(known_commands(tex.read_text(encoding="utf-8", errors="replace")))
    lines = doc.line_numbers()
    for p in problems:
        print(f"{path}:{lines[p.index]}: {p.severity}: {p.message}")
    n_err = sum(p.severity == "error" for p in problems)
    print(f"{len(problems)} problem(s), {n_err} error(s)", file=sys.stderr)
    return 1 if n_err else 0


def main(argv=None):
    args = _parser().parse_args(argv)
    path = _resolve(args.path)
    if args.init:
        copied = init_project(path.parent)
        print(f"Template copied to {path.parent.resolve()} ({len(copied)} new files)", file=sys.stderr)
        if not path.exists():
            from .common import SKELETON
            path.write_text(SKELETON.read_text(encoding="utf-8"), encoding="utf-8")
    if args.pdf or args.check:
        if not path.exists():
            print(f"{path}: no such file", file=sys.stderr)
            return 2
        if args.check:
            return check(path)
        result = compile_pdf(path, args.output)
        for w in result.warnings:
            print(f"warning: {w}", file=sys.stderr)
        for e in result.errors:
            print(f"error: {e}", file=sys.stderr)
        print(result.summary, file=sys.stderr if not result.ok else sys.stdout)
        if result.ok and args.open:
            open_file(result.pdf)
        return 0 if result.ok else 1
    if not args.tui:
        if has_display():
            from .gui import run
            return run(path, open_pdf=not args.no_viewer)
        print("No display found: starting the terminal user interface", file=sys.stderr)
    from .tui.app import IndexApp
    IndexApp(path, open_pdf=not args.no_viewer).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
