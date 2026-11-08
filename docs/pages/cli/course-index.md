# `course-index`

```console
$ course-index --help
usage: course-index [-h] [--pdf | --check] [--init] [-o OUTPUT] [--open] [--no-viewer] [--tui] [-V] [path]

Edit a course index (LaTeX course index template) and compile it to PDF.

positional arguments:
  path                  index file, or folder holding main.idx (default: ./main.idx)

options:
  -h, --help            show this help message and exit
  --pdf                 compile the PDF and exit
  --check               check the index and exit (exit code 1 on errors)
  --init                copy the template files next to the index first
  -o, --output OUTPUT   PDF path for --pdf (default: the index path with .pdf)
  --open                open the PDF after --pdf
  --no-viewer           do not open the PDF after compiling from the editor
  --tui                 use the terminal user interface instead of the window
  -V, --version         show program's version number and exit
```

A `path` that is an existing folder, ends with `/` or has no extension means `main.idx` in that folder.

## Examples

Edit an index (created when saving if it does not exist):

```console
$ course-index sec504.idx
```

Start a new course in a new folder, with a copy of the template (`main.tex`, `data.tex`, `lib/`) that you can
customize:

```console
$ course-index --init sec504/
```

Edit it in the terminal (e.g. over SSH):

```console
$ course-index sec504.idx --tui
```

Compile without opening the editor (e.g. in a script or CI):

```console
$ course-index sec504.idx --pdf
PDF written to sec504.pdf
$ course-index sec504.idx --pdf -o build/index.pdf --open
```

Check an index:

```console
$ course-index sec504.idx --check
sec504.idx:565: warning: unknown command \ukey
sec504.idx:920: warning: no book for this page: add |book{N} or a line with it
...
15 problem(s), 0 error(s)
```

| Exit code | Meaning |
|---|---|
| 0 | success (warnings may have been printed) |
| 1 | compilation failed, or `--check` found errors |
| 2 | the index does not exist (`--pdf`, `--check`) |
