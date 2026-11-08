# -*- coding: UTF-8 -*-
"""Helpers shared by the user interfaces (GUI and TUI): decorations of a level, kinds of lines, help text."""
import re
from pathlib import Path

from .latex import ICONS

__all__ = ["HELP", "KIND_MARKS", "MAX_LEVELS", "SKELETON", "join_decorations", "split_decorations"]

SKELETON = Path(__file__).parent / "skeleton.idx"
KIND_MARKS = {"spacer": ("␣", "blank line"), "pagebreak": ("⤓", "page break"), "xref": ("↪", None),
              "hidden": ("◌", None)}
MAX_LEVELS = 4
_ICON_RE = re.compile(r"\s*\\(" + "|".join(sorted(ICONS, key=len, reverse=True)) + r")(?![A-Za-z])")
_RATE_RE = re.compile(r"\s*\\rate\{(\d+)\}")


def split_decorations(text):
    """Split a level text into (text without icons and rating, [icons], rating)."""
    icons = _ICON_RE.findall(text)
    m = _RATE_RE.search(text)
    rating = int(m.group(1)) if m else 0
    base = _RATE_RE.sub("", _ICON_RE.sub("", text)).rstrip()
    return base, icons, rating


def join_decorations(base, icons, rating):
    text = base.rstrip()
    if icons:
        text += " " + "".join(f"\\{i}" for i in icons)
    if rating:
        text += f" \\rate{{{rating}}}"
    return text


HELP = r"""
# Course Index — help

## Adding references (the quick-add bar)

1. Set the **book** (e.g. `1`, `2` or `W` for the workbook; it must exist, **F3** creates a new one) and the
   **page** (`45` or a range `45-47`; not 0, and a range must end after it starts).
2. Type the **term** and press **Enter**. The book and page stay, ready for the next term.

- `Term!Sub-term` adds a sub-level (up to 3 levels).
- Suggestions of existing terms show while typing: **↑/↓** to choose, **Tab** to complete.
  Completing an existing term keeps its exact key, so the pages merge on the same line.
- **Ctrl+↑ / Ctrl+↓** (or PageUp/PageDown) increment/decrement the page.
- Shortcuts: `` `nc` `` → `\texttt{nc}`, `**x**` → `\textbf{x}`, `*x*` → `\textit{x}`, `:linux:` → `\linux`.
  `_ & % #` are escaped automatically.

The template's conventions are applied for you: `|book{N}` on the first page of a term in a book, a new
`term! ` line for each additional book, a sort key for terms starting with a command (`\texttt{.htaccess}` →
`Htaccess@\texttt{.htaccess}`), and the entry goes to its group (Topics/Categories) or its book's section.

## Entries table

Each section of the file is a block of lines, collapsed by default (▶, with its number of entries and a ⚠/✖ when it
hides a problem). Selecting an entry (after adding it, from the Problems or the Preview, ...) expands its section.

| Key | Action |
|---|---|
| → / ← | expand / collapse the section (also Enter, Space or a click on the caret of its header) |
| + / - | expand / collapse all the sections |
| Enter / e | edit the entry (structured fields synchronized with the raw line), or correct a malformed one |
| n | new entry after the current line (or in its book's section if the book is another one) |
| a | go to the quick-add bar |
| c | duplicate |
| d / Delete | delete |
| Space | comment out / restore (`%`) |
| b | insert a blank line after this group |
| p | insert a page break after this group |
| x | add a cross-reference (`alias \goto term`) |
| Alt+↑ / Alt+↓ | move the line up/down |
| / | filter (text, `book:2`, `page:45`), in all the sections |
| s | show the section in the Sections tab (for the parts of a book in the Topics, the section of this book) |

New entries always go to the section of their book (or to the Topics/Categories), and changing the book of an entry
moves it to the section of its new book.

## Everywhere

| Key | Action |
|---|---|
| Ctrl+S | save (a `.bak` copy of the original file is kept) |
| F5 | save and compile the PDF (then open it) |
| F2 | course metadata (code, title, date, version) |
| F3 | new book (creates its section) |
| F4 | Sections tab: rename, set or change the book (renumbering its entries) or its title, add, delete, move |
| Ctrl+Z / Ctrl+Y | undo / redo |
| F1 | this help |
| Ctrl+Q | quit |

The *title* of a book is the bold first level of the group of the Topics section holding its parts, all in this book
(`2a@\textbf{Recon}!1@...`): it is edited with the book's section (Sections tab, `e`), and `t` there goes to it. The
entry editor locks this first level on the parts of a book.

Tabs: **Entries** (the quick-add bar and the lines of the file), **Sections** (sections and books), **Preview**
(the index as it will be typeset), **Problems** (checks).

## `.idx` syntax reminder

- `\indexentry{text}{page}`; `key@text` sets the sort key; `a!b` makes `b` a sub-level of `a`; `|cmd` formats the page.
- Sort keys made of digits and letters (`2a`) go to *Topics*, digits only (`200`) to *Categories*, the others to the letters.
- `\blankline|comment` is a blank line, `|newpage \comment` a page break, `\rate{n}` stars, `\linux`, `\win`, ... icons.
"""
