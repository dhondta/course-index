# Installation

Course Index requires Python 3.10 or later.

```console
$ pip install course-index
```

This installs the `course-index` command and its dependencies: [Qt for Python](https://doc.qt.io/qtforpython-6/)
(PySide6) for the window, [Textual](https://textual.textualize.io) and [Rich](https://github.com/Textualize/rich) for
the terminal user interface (`--tui`).

## Compiling to PDF

Compiling the index requires a TeX distribution providing `makeindex` and `pdflatex`, with the LaTeX packages used by
the template (`fancyhdr`, `multicol`, `makeidx`, `vmargin`, `pdfescape`, `forloop`, `graphicx`, `ragged2e` and
`hyperref`):

| System | Installation |
|---|---|
| Debian/Ubuntu | `sudo apt-get update && sudo apt-get install -y texlive-latex-extra` |
| Fedora | `sudo dnf install texlive-scheme-medium` |
| macOS | [MacTeX](https://www.tug.org/mactex/) (or BasicTeX, then `sudo tlmgr install vmargin forloop ragged2e pdfescape`) |
| Windows | [MiKTeX](https://miktex.org/) (installs missing packages on the fly) or [TeX Live](https://www.tug.org/texlive/) |

Editing an index does not require TeX: only `F5` (and `--pdf`) does.

!!! note "Window or terminal"

    `course-index` opens a window. On Linux, this requires a graphical session (X11 or Wayland): without one (e.g. over
    SSH), the terminal user interface starts instead, as with `--tui`, where any modern terminal works. Icons are
    displayed as emojis (🐧 for `\linux`, 🪟 for `\win`, ...), so a font with emoji support gives the best result.
