# The `.idx` format

This page summarizes the format of the
[LaTeX Course Index Template](https://github.com/academic-templates/tex-course-index-template) and the conventions
that Course Index applies.

## Index entries

The raw material of the file is the `\indexentry` command:

```latex
\indexentry{key}{page}
```

The key is made of levels separated by `!`, each optionally with a sort key before `@`, and optionally followed by an
encapsulator after `|` that formats the page number:

```latex
\indexentry{200@\textbf{Tools}!Netcat|book{3}}{17-49}
%           ^^^ ^^^^^^^^^^^^^^ ^^^^^^ ^^^^^^^  ^^^^^
%           sort key  text     level 2 encap.  page(s)
```

`"` quotes a special character (`"!`, `"@`, `"|`). Lines starting with `%` are commented out, and `\comment{...}`
blocks hold comments (and the section headers).

## Where an entry is sorted

The sort key (or the text when there is none) decides the section of the PDF:

| Sort key | Section | Example |
|---|---|---|
| digits and letters | *Topics* (the course outline) | `1a@\textbf{Course Philosophy}` |
| digits only | *Categories* (tools, commands, labs, ...) | `200@\textbf{Tools}!Nmap` |
| starting with a letter | the section of this letter | `Nmap` |

A text starting with a command, such as `\texttt{.htaccess}`, would be sorted with the symbols (in *Topics*): it needs
a sort key, e.g. `Htaccess@\texttt{.htaccess}`. Course Index adds it for new terms.

## Books and pages

`|book{N}` prints the page with the book number, e.g. `504.2–45` for page 45 of book 2 of a course with code 504.
makeindex gathers all the pages of a key on one line, sorted by page number, and formats each page with its own
encapsulator. The conventions of the template are therefore:

- **the book number is only on the first page of a term in a book**:

    ```latex
    \indexentry{Netcat|book{3}}{17-49}
    \indexentry{Netcat}{88}
    ```

    gives *Netcat … 504.3–17-49, 88*;

- **each additional book gets its own line**, through a blank sub-level (one more space for each book) or, in some
  indexes, a blank text with the same sort key:

    ```latex
    \indexentry{Netcat! |book{4}}{12}
    \indexentry{Netcat!  |book{5}}{3}
    \indexentry{Cain@ |book{4}}{25-29}
    ```

Course Index recognizes both idioms and continues the one used by a term.

## Template commands

| Syntax | Effect |
|---|---|
| `\indexentry{1z@\blankline\|comment}{0}` | blank line (after the group sorted before `1z`) |
| `\indexentry{999@\blankline\|newpage \comment}{0}` | page break |
| `\indexentry{K8s \goto Kubernetes\|comment}{0}` | cross-reference (no page number) |
| `\rate{3}` | ★★★ |
| `\linux`, `\win`, `\mac`, `\all`, `\python`, `\web`, `\q`, ... | icons (see `main.tex`) |
| `\icon{name}` | any image of the template's `lib` folder |
| `\book{4}\lab` as encapsulator | lab number instead of page (`L1`) |

The sort key of a blank line or a page break places it: Course Index uses the next number after a category
(`200` → `201`), `<digits>z` after a topic (`2a` → `2z`) and `<Letter>zzzzzz` at the end of a letter.

## Sections of the file

The file is organized in sections whose headers are `\comment{...}` blocks with a title such as `TOPICS SECTION`,
`CATEGORIES SECTION`, `FIRST BOOK SECTION` (or `SANS 504.1 SECTION`, `BOOK 3 SECTION`), `WORKBOOK SECTION` and
`CROSS-KEYS SECTION`; any title can be dedicated to a book with `(BOOK n)`, e.g. `INTRODUCTION (BOOK 1) SECTION`.
They do not change the PDF (makeindex sorts everything) but keep the file readable; Course
Index uses them to place new entries and to navigate.
