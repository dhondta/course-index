# How it works

```
src/course_index/
├── idx.py         # lossless model of the .idx file and the template's conventions
├── latex.py       # rendering of the LaTeX of the entries (Rich text), input shortcuts
├── preview.py     # makeindex-like grouping and sorting, for the Preview tab
├── course.py      # course metadata (data.tex)
├── compiler.py    # makeindex + pdflatex in a temporary folder
├── common.py      # helpers shared by the GUI and the TUI (decorations of a level, help text)
├── skeleton.idx   # new index (the template's main.idx without its sample entries)
├── template/      # the LaTeX template: main.tex, data.tex, lib/ (images and std.ist)
├── gui/           # Qt application (default): app.py (window), dialogs.py, widgets.py
└── tui/           # Textual application (--tui): app.py, screens.py (dialogs), widgets.py, app.tcss
```

## Lossless parsing

The file is split into items:

- a `\comment{` block, possibly spanning several lines, is read until its braces are balanced (`Raw`);
- a line made of exactly one `\indexentry{...}{...}` (possibly behind `%`) is an `Entry`, whose key is split on the
  unquoted `|`, `!` and `@` like makeindex does;
- anything else is a `Raw` line.

Each `Entry` keeps its original text and is written back as is unless it was modified; the newline style (LF or
CRLF) and the final newline of the file are preserved. The test suite checks that the 15 SANS examples of the
template are written back byte for byte, and that each of their entries serializes from its fields to the original
line.

## Adding a reference

`Document.add_reference(path, book, page)`:

1. collects the lines of the same term (its base path, ignoring the blank levels of additional books) and the book
   of each;
2. if the term already has a line for this book, adds the page to it without `|book{N}`, unless the new page is
   lower: then the book number moves to the new page (makeindex sorts pages, the book number must be on the first);
3. if the term has lines for other books only, adds a line for this book with one more blank level (or one more space
   of blank text for the `Term@ ` idiom);
4. places the entry after its group in *Topics*/*Categories*, or at the end of its book's section, created if needed.

## Rendering

`latex.render()` is a small LaTeX interpreter producing Rich text: `\textbf` → bold, `\texttt` → cyan, icons →
emojis, `\rate{n}` → stars, `\goto` → `→`, escaped characters, `--`, `~`, and spaces collapsed like TeX does. Unknown
commands are shown dimmed.

The GUI converts this Rich text to HTML (`gui/widgets.py`), painted in the cells of the tables and trees by an item
delegate, with colors following the light or dark theme of the system.

The entries table is a virtual list (`tui/widgets.py`, and a Qt table model in `gui/widgets.py`): only the visible rows
are rendered and the rendered cells are cached by item, so that refreshing it after an edit takes a few milliseconds
whatever the size of the index. The checks run in a background thread after each change.

## Compiling

`compile_pdf()` copies `main.tex` and `lib/` (from the folder of the index when it is a template project, else the
bundled template) to a temporary folder, writes `data.tex` from the course metadata and `main.idx` from the document,
then runs:

```console
$ makeindex -s lib/std.ist main.idx
$ pdflatex -interaction=nonstopmode main.tex
```

The errors and warnings of the makeindex log are reported with their line numbers, except those located in comment
blocks: makeindex also parses the `\indexentry` examples of the header comment, which is harmless. The errors of the
LaTeX log are reported with the line where they occurred. A final newline is always written, because makeindex 2.17
crashes on a file ending with a comment block without one.
