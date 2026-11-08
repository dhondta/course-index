# -*- coding: UTF-8 -*-
"""Course Index: a TUI for editing the index of the LaTeX course index template and compiling it to PDF."""
from .__info__ import __author__, __copyright__, __email__, __license__, __source__, __version__  # noqa: F401
from .compiler import BuildResult, compile_pdf, init_project  # noqa: F401
from .course import CourseInfo, data_file_for  # noqa: F401
from .idx import Document, Entry, Level, Problem, Raw  # noqa: F401
