# -*- coding: UTF-8 -*-
"""Lossless model of a course index `.idx` file.

The file is parsed into a list of items, each being either an :class:`Entry` (one `\\indexentry{...}{...}` line,
possibly commented out with `%`) or a :class:`Raw` block (comments, section headers, blank lines, anything else).
Unchanged items are written back exactly as they were read, so that opening and saving a file never alters it.

On top of this, :class:`Document` implements the conventions of the LaTeX course index template:

- `|book{N}` on the first page of a reference in book N, later pages of the same book without it;
- a blank sub-level (`term! `, `term!  `, ...) for each additional book of the same reference;
- `\\blankline` spacers and `\\newpage` page breaks with a sort key placing them after a group;
- cross-references (`\\goto`) in the CROSS-KEYS section.
"""
import re
from dataclasses import dataclass, field, replace

__all__ = ["Document", "Entry", "Level", "Problem", "Raw", "book_sort_key", "book_title", "normalize_title",
           "page_error", "page_sort_key", "sort_group"]

LEVEL, ACTUAL, ENCAP, QUOTE, ESCAPE = "!", "@", "|", '"', "\\"
ORDINALS = ["FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "SIXTH", "SEVENTH", "EIGHTH", "NINTH", "TENTH"]
SECTION_RULE = "*" * 101
_BOOK_ENCAP = re.compile(r"^book\{([^{}]*)\}(.*)$", re.S)
_ENTRY_START = re.compile(r"^(\s*)(%\s*)?\\indexentry\s*(?=\{)")
_PAGE = re.compile(r"^(\d+)(?:-(\d+))?$")


# --------------------------------------------------------------------------------------------------------------------
# Low-level helpers
# --------------------------------------------------------------------------------------------------------------------
def _group(s, i):
    """Return the end index (exclusive) of the brace group starting at s[i] == '{', or -1 when unbalanced."""
    depth, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n and s[i + 1] in "{}":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _split(s, sep, maxsplit=-1):
    """Split on an unquoted makeindex special character (`"x` quotes x, `\\"` is not a quote)."""
    parts, buf, i, n = [], [], 0, len(s)
    while i < n:
        c = s[i]
        if c == ESCAPE and i + 1 < n and s[i + 1] == QUOTE or c == QUOTE and i + 1 < n:
            buf.append(s[i:i+2])
            i += 2
            continue
        if c == sep and maxsplit != 0:
            parts.append("".join(buf))
            buf, maxsplit = [], maxsplit - 1
        else:
            buf.append(c)
        i += 1
    parts.append("".join(buf))
    return parts


def page_error(page):
    """Reason why a page (or page range) of a reference is invalid, or None if it is valid."""
    m = _PAGE.match((page or "").strip())
    if not m:
        return "the page must be a number or a range (e.g. 45 or 45-47)"
    first = int(m.group(1))
    if first == 0:
        return "the page cannot be 0"
    if m.group(2) is not None and int(m.group(2)) <= first:
        return f"the end of the range must be greater than {first}"


def book_title(book):
    """Standard title of the section of a book (e.g. 'SECOND BOOK SECTION')."""
    b = str(book)
    if b == "W":
        return "WORKBOOK SECTION"
    if b.isdigit() and 1 <= int(b) <= len(ORDINALS):
        return f"{ORDINALS[int(b) - 1]} BOOK SECTION"
    return f"BOOK {b} SECTION"


def normalize_title(title):
    """Section title as the template writes it: uppercase, ending with SECTION."""
    t = " ".join((title or "").upper().split())
    if any(c in t for c in "*{}\\%"):
        raise ValueError("a section title cannot contain * { } \\ or %")
    if not t.endswith("SECTION"):
        t = f"{t} SECTION".strip()
    if t == "SECTION":
        raise ValueError("the section title cannot be empty")
    return t


def _header(title):
    return Raw("\\comment{" + "*" * 92 + "\n" + title.center(101).rstrip() + "\n" + SECTION_RULE + "}")


def book_sort_key(book):
    """Sort books numerically first (1, 2, ..., 10), then alphabetically (W, ...)."""
    book = str(book)
    return (0, int(book), "") if book.isdigit() else (1, 0, book.lower())


def page_sort_key(page):
    """Sort pages like makeindex does with composite page numbers (e.g. '18-46' -> (18, 46))."""
    nums = re.findall(r"\d+", page or "")
    return tuple(int(x) for x in nums) if nums else (float("inf"), )


def sort_group(key):
    """Return the makeindex group of a sort key: 0 = symbols (Topics), 1 = numbers (Categories), 2 = letters."""
    key = key.lstrip()
    if key.isdigit():
        return 1
    if key[:1].isalpha():
        return 2
    return 0


def sort_tuple(key):
    """Sort tuple approximating makeindex's ordering of sort keys."""
    g = sort_group(key)
    if g == 1:
        return (g, int(key.strip()), "", key)
    return (g, 0, key.lower(), key)


# --------------------------------------------------------------------------------------------------------------------
# Items
# --------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Level:
    """One level of an index key: `key@text` or just `text`."""
    text: str
    key: str | None = None

    def __str__(self):
        return self.text if self.key is None else f"{self.key}{ACTUAL}{self.text}"

    @property
    def is_blank(self):
        return self.key is None and self.text.strip() == ""

    @property
    def sort(self):
        return self.text if self.key is None else self.key

    @classmethod
    def parse(cls, s):
        parts = _split(s, ACTUAL, 1)
        return cls(parts[0]) if len(parts) == 1 else cls(parts[1], parts[0])


@dataclass(frozen=True)
class Raw:
    """Anything that is not an index entry, kept verbatim (may span several lines)."""
    text: str

    @property
    def is_blank(self):
        return self.text.strip() == ""

    @property
    def is_comment_block(self):
        return self.text.lstrip().startswith("\\comment{")

    @property
    def is_malformed_entry(self):
        """Whether this line is an `\\indexentry` that could not be parsed (e.g. unbalanced braces)."""
        return not self.is_comment_block and "\n" not in self.text and _ENTRY_START.match(self.text) is not None

    @property
    def section(self):
        """Title of the section this block opens (e.g. 'FIRST BOOK SECTION'), if any."""
        if not self.is_comment_block:
            return
        for line in self.text.splitlines():
            line = line.strip().strip("{}").strip()
            if line.endswith("SECTION") and "*" not in line and line == line.upper():
                return line


@dataclass(frozen=True)
class Entry:
    """An `\\indexentry{levels|encap}{page}` line."""
    levels: tuple
    page: str
    encap: str | None = None
    disabled: bool = False
    raw: str | None = field(default=None, compare=False)

    def __post_init__(self):
        if not isinstance(self.levels, tuple):
            object.__setattr__(self, "levels", tuple(self.levels))

    def evolve(self, **kwargs):
        """Return a modified copy (which is then serialized from its fields instead of its raw text)."""
        return replace(self, raw=None, **kwargs)

    @classmethod
    def make(cls, path, page, encap=None, disabled=False):
        """Build an entry from a key path such as `30@\\textbf{Tools}!Nmap` (or a sequence of levels)."""
        if isinstance(path, str):
            path = _split(path, LEVEL)
        return cls(tuple(lv if isinstance(lv, Level) else Level.parse(lv) for lv in path), str(page), encap, disabled)

    @classmethod
    def salvage(cls, line):
        """Best-effort reading of a malformed `\\indexentry` line (to correct it) ; the result may not be valid."""
        m = _ENTRY_START.match(line)
        rest = line[m.end():].strip() if m else line.strip()
        # the last `}{page` of the line separates the key from the page (a missing `}` or trailing text is dropped)
        p = re.match(r"^\{(.*)\}\s*\{([^{}]*)\}?", rest, re.S)
        if p:
            key, page = p.groups()
        else:
            key, page = (rest[1:] if rest.startswith("{") else rest).rstrip("}"), ""
        parts = _split(key, ENCAP, 1)
        levels = tuple(Level.parse(x) for x in _split(parts[0], LEVEL))
        return cls(levels, page, parts[1] if len(parts) == 2 else None, bool(m and m.group(2)))

    @property
    def is_valid(self):
        """Whether the line of this entry is well-formed (it parses back to the same entry)."""
        return Entry.parse(self.to_line()) == self

    @classmethod
    def parse(cls, line):
        """Parse one line ; return None when it is not exactly one (possibly commented out) index entry."""
        m = _ENTRY_START.match(line)
        if not m:
            return
        i = m.end()
        j = _group(line, i)
        if j < 0 or j >= len(line) or line[j] != "{":
            return
        k = _group(line, j)
        if k < 0 or line[k:].strip() != "":
            return
        key, page = line[i+1:j-1], line[j+1:k-1]
        parts = _split(key, ENCAP, 1)
        encap = parts[1] if len(parts) == 2 else None
        levels = tuple(Level.parse(p) for p in _split(parts[0], LEVEL))
        return cls(levels, page, encap, m.group(2) is not None, line)

    # ---------------------------------------------------- properties ------------------------------------------------
    @property
    def book(self):
        """Book set by the encapsulator (`|book{N}...`), if any."""
        m = _BOOK_ENCAP.match(self.encap or "")
        return m.group(1) if m else None

    @property
    def encap_rest(self):
        """What follows `book{N}` in the encapsulator (e.g. `\\lab`), or the whole encapsulator otherwise."""
        m = _BOOK_ENCAP.match(self.encap or "")
        return m.group(2) if m else self.encap

    @property
    def kind(self):
        """One of: 'pagebreak', 'spacer', 'xref', 'hidden' (other `|comment` entries) or 'ref'."""
        enc = (self.encap or "").strip()
        if "newpage" in enc:
            return "pagebreak"
        if self.levels[-1].text.strip() == "\\blankline":
            return "spacer"
        if enc.startswith("comment") or enc.startswith("\\comment"):
            return "xref" if any("\\goto" in lv.text for lv in self.levels) else "hidden"
        return "ref"

    @property
    def path(self):
        """Key path identifying the line of the index this entry contributes to."""
        return tuple(str(lv) for lv in self.levels)

    @property
    def base_path(self):
        """Key path without the trailing blank levels used for references in additional books."""
        lv = list(self.levels)
        while len(lv) > 1 and lv[-1].is_blank:
            lv.pop()
        if lv[-1].key is not None and lv[-1].text.strip() == "":
            # `Term@ ` (sort key, blank text) is another way of adding a line for an additional book
            lv[-1] = Level(lv[-1].key)
        return tuple(str(x) for x in lv)

    @property
    def key(self):
        """The key argument (levels and encapsulator)."""
        k = LEVEL.join(self.path)
        return k if self.encap is None else f"{k}{ENCAP}{self.encap}"

    @property
    def top(self):
        return self.levels[0]

    def to_line(self):
        if self.raw is not None:
            return self.raw
        return ("%" if self.disabled else "") + f"\\indexentry{{{self.key}}}{{{self.page}}}"


@dataclass
class Problem:
    """A problem found by :meth:`Document.check`."""
    index: int
    severity: str
    message: str


# --------------------------------------------------------------------------------------------------------------------
# Document
# --------------------------------------------------------------------------------------------------------------------
class Document:
    """An `.idx` file as a list of items, with the operations of the course index template."""
    def __init__(self, items=None, newline="\n", final_newline=True):
        self.items = list(items or [])
        self.newline, self.final_newline = newline, final_newline

    # ------------------------------------------------- input/output -------------------------------------------------
    @classmethod
    def parse(cls, text):
        newline = "\r\n" if "\r\n" in text else "\n"
        final = text.endswith("\n")
        lines = text.replace("\r\n", "\n").split("\n")
        if final:
            lines.pop()
        items, i = [], 0
        while i < len(lines):
            line = lines[i]
            if line.lstrip().startswith("\\comment{"):
                # a comment block may span several lines ; it ends when its braces are balanced
                block, j = line, i
                start = line.index("\\comment{") + len("\\comment")
                while _group(block, start) < 0 and j + 1 < len(lines):
                    j += 1
                    block += "\n" + lines[j]
                items.append(Raw(block))
                i = j + 1
                continue
            items.append(Entry.parse(line) or Raw(line))
            i += 1
        return cls(items, newline, final)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8", newline="") as f:
            return cls.parse(f.read())

    def dumps(self):
        lines = [it.to_line() if isinstance(it, Entry) else it.text for it in self.items]
        text = self.newline.join(x.replace("\n", self.newline) for x in lines)
        return text + self.newline if self.final_newline and lines else text

    def copy(self):
        return Document(self.items, self.newline, self.final_newline)

    # ---------------------------------------------------- queries ---------------------------------------------------
    def line_numbers(self):
        """List of the (1-based) file line number of each item."""
        nums, n = [], 1
        for it in self.items:
            nums.append(n)
            n += it.text.count("\n") + 1 if isinstance(it, Raw) else 1
        return nums

    def entries(self, enabled=True):
        """Yield (index, entry), only the enabled ones by default."""
        for i, it in enumerate(self.items):
            if isinstance(it, Entry) and (not enabled or not it.disabled):
                yield i, it

    def sections(self):
        """List of (index, title) of the section headers."""
        return [(i, it.section) for i, it in enumerate(self.items) if isinstance(it, Raw) and it.section]

    def section_of(self, index):
        """Title of the section containing the item at the given index (None before the first section)."""
        title = None
        for i, t in self.sections():
            if i > index:
                break
            title = t
        return title

    @staticmethod
    def section_book(title):
        """Book a section is dedicated to, guessed from its title (e.g. 'SECOND BOOK SECTION' -> '2')."""
        t = (title or "").upper()
        m = re.search(r"\(BOOK\s+(\w+)\)", t)
        if m:
            return m.group(1)
        if "WORKBOOK" in t or "WORKSHOP" in t or "LAB BOOK" in t:
            return "W"
        m = re.match(r"^(\w+) BOOK SECTION$", t)
        if m and m.group(1) in ORDINALS:
            return str(ORDINALS.index(m.group(1)) + 1)
        m = re.search(r"\bBOOK\s+(\w+)\b", t) or re.search(r"\.(\d+)\s+SECTION$", t)
        if m and m.group(1) != "SECTION":
            return m.group(1)

    @staticmethod
    def section_kind(title):
        t = (title or "").upper()
        for kw, kind in [("TOPIC", "topics"), ("CATEGOR", "categories"), ("CROSS", "xrefs")]:
            if kw in t:
                return kind
        return "book" if Document.section_book(t) else "other"

    def books(self):
        """Sorted list of the books used in the index or having a section."""
        books = {e.book for _, e in self.entries(False) if e.book}
        books |= {b for _, t in self.sections() if (b := self.section_book(t))}
        return sorted(books, key=book_sort_key)

    def effective_books(self):
        """Map index -> book of each entry, inheriting the book of the same line for pages without `|book{N}`."""
        books, result = {}, {}
        for i, e in self.entries():
            if e.book:
                books.setdefault(e.path, e.book)
        for i, e in self.entries(False):
            result[i] = e.book or books.get(e.path)
        return result

    def paths(self):
        """Ordered dict of the base key paths of the references (and of their parents) -> set of books."""
        paths, eff = {}, self.effective_books()
        for i, e in self.entries():
            if e.kind != "ref":
                continue
            p = e.base_path
            for n in range(1, len(p) + 1):
                paths.setdefault(p[:n], set())
            if eff.get(i):
                paths[p].add(eff[i])
        return paths

    def chapters(self):
        """Map book -> top level (e.g. `2a@\\textbf{Recon}`) of its chapter, i.e. the group of the Topics section
        holding the parts of the book: it has sub-entries and all its references belong to this book (single lines
        such as `1a@\\textbf{Learning Objectives}` are not chapters ; with several candidates, the largest wins)."""
        eff, groups, parts, sizes = self.effective_books(), {}, set(), {}
        for i, e in self.entries():
            if e.kind == "ref" and sort_group(e.top.sort) == 0 and self.section_kind(self.section_of(i)) == "topics":
                top = e.path[0]
                groups.setdefault(top, set()).add(eff.get(i))
                sizes[top] = sizes.get(top, 0) + 1
                if len(e.base_path) > 1:
                    parts.add(top)
        result = {}
        for top, books in groups.items():
            if top in parts and len(books) == 1 and None not in books:
                b = books.pop()
                if b not in result or sizes[top] > sizes[result[b]]:
                    result[b] = top
        return result

    @staticmethod
    def chapter_title(top):
        """Title of a chapter: the content of the first `\\textbf{...}` of its top level (else the whole text)."""
        text = Level.parse(top).text
        i = text.find("\\textbf{")
        if i >= 0 and (j := _group(text, i + 7)) > 0:
            return text[i+8:j-1]
        return text

    def rename_chapter(self, top, title):
        """Change the title of a chapter (the bold part of its top level) in all its entries ; return their number."""
        title = " ".join((title or "").split())
        if not title:
            raise ValueError("the chapter title cannot be empty")
        if _group("{" + title + "}", 0) != len(title) + 2:
            raise ValueError("unbalanced braces in the chapter title")
        for c in LEVEL + ACTUAL + ENCAP:
            if len(_split(title, c)) > 1:
                raise ValueError(f'quote {c} as "{c} in the chapter title')
        old = Level.parse(top)
        i = old.text.find("\\textbf{")
        j = _group(old.text, i + 7) if i >= 0 else -1
        text = old.text[:i+8] + title + old.text[j-1:] if j > 0 else title
        new, n = str(Level(text, old.key)), 0
        for k, e in self.entries(False):
            if e.path[0] == top:
                self.items[k] = e.evolve(levels=(Level.parse(new), ) + e.levels[1:])
                n += 1
        return n

    def find_path(self, path):
        """Return the indices of the entries contributing to a base path (and its additional books' variants)."""
        path = tuple(path)
        return [i for i, e in self.entries(False) if e.base_path == path]

    # ------------------------------------------------- modifications ------------------------------------------------
    def insert(self, index, item):
        self.items.insert(index, item)
        return index

    def _section_end(self, start):
        """Index right after the last non-blank item of the section whose header is at `start`."""
        end = len(self.items)
        for i, _ in self.sections():
            if i > start:
                end = i
                break
        while end - 1 > start and isinstance(self.items[end - 1], Raw) and self.items[end - 1].is_blank:
            end -= 1
        return end

    def ensure_section(self, title, before_kinds=("xrefs", )):
        """Return the index of the header of the given section, creating it (before the cross-keys) if missing."""
        for i, t in self.sections():
            if t == title:
                return i
        pos = len(self.items)
        for i, t in self.sections():
            if self.section_kind(t) in before_kinds:
                pos = i
                break
        header = _header(title)
        new = [header]
        if pos > 0 and not (isinstance(self.items[pos - 1], Raw) and self.items[pos - 1].is_blank):
            new.insert(0, Raw(""))
        new += [Raw(""), Raw("")] if pos < len(self.items) else []
        self.items[pos:pos] = new
        return pos + new.index(header)

    def add_book(self, book):
        """Create the section of a new book ; return the index of its header."""
        book = str(book).strip()
        if not re.fullmatch(r"[0-9A-Za-z]+", book):
            raise ValueError("a book is a number or letters (e.g. 3 or W)")
        if book in self.books():
            raise ValueError(f"book {book} already exists")
        return self.book_section(book)

    def book_section(self, book):
        """Index of the header of the section of a book, created if needed."""
        for i, t in self.sections():
            if self.section_book(t) == str(book):
                return i
        b = str(book)
        title = book_title(b)
        # keep book sections in order: insert before the first section of a later book
        later = [i for i, t in self.sections() if (sb := self.section_book(t)) and book_sort_key(sb) > book_sort_key(b)]
        if later:
            pos = later[0]
            header = _header(title)
            self.items[pos:pos] = [header, Raw(""), Raw("")]
            return pos
        return self.ensure_section(title)

    # ---------------------------------------------------- sections --------------------------------------------------
    @staticmethod
    def retitle(title, old, new):
        """Adapt a section title to another book (e.g. 'SANS 504.1 SECTION' -> 'SANS 504.2 SECTION')."""
        title = normalize_title(title)
        new = str(new)
        candidates = []
        if old:
            if title == book_title(old):
                candidates.append(book_title(new))
            m = re.search(r"\.(\w+)(\s+SECTION)$", title)
            if m and m.group(1) == old:
                candidates.append(title[:m.start(1)] + new + title[m.end(1):])
            if re.search(rf"\bBOOK\s+{re.escape(old)}\b", title):
                candidates.append(re.sub(rf"\bBOOK(\s+){re.escape(old)}\b", rf"BOOK\g<1>{new}", title, count=1))
        candidates.append(title)
        for c in candidates:
            if Document.section_book(c) == new:
                return c
        base = re.sub(r"\s*\(BOOK\s+\w+\)", "", title[:-len("SECTION")]).strip()
        return f"{base} (BOOK {new}) SECTION" if base else book_title(new)

    def section_bounds(self, index):
        """(start, end) of the block of the section whose header is at index (end: next header or end of file)."""
        end = next((i for i, _ in self.sections() if i > index), len(self.items))
        return index, end

    def section_entries(self, index):
        start, end = self.section_bounds(index)
        return sum(1 for i in range(start, end) if isinstance(self.items[i], Entry))

    def book_usage(self, book):
        """Number of entries with `|book{book}`."""
        return sum(1 for _, e in self.entries(False) if e.book == str(book))

    def _check_section(self, index, title, book):
        """Return the title adapted to the book, after checking that the section can have it."""
        title = normalize_title(title)
        if book:
            book = str(book).strip()
            if not re.fullmatch(r"[0-9A-Za-z]+", book):
                raise ValueError("a book is a number or letters (e.g. 3 or W)")
            if self.section_kind(title) in ("topics", "categories", "xrefs"):
                raise ValueError("the Topics, Categories and Cross-keys sections cannot be dedicated to a book")
            title = self.retitle(title, self.section_book(title), book)
        b = self.section_book(title)
        for i, t in self.sections():
            if i == index:
                continue
            if t == title:
                raise ValueError(f"there is already a section {title}")
            if b and self.section_book(t) == b and self.section_kind(title) == "book":
                raise ValueError(f"book {b} already has a section ({t})")
        return title

    def set_section(self, index, title, book=None, renumber=False):
        """Rename the section whose header is at index, possibly dedicating it to (another) book.

        :param book:     book of the section (its title is adapted when needed), None/'' to keep what the title says
        :param renumber: also change the book of the entries using the previous book of the section
        :return:         number of entries renumbered
        """
        header = self.items[index]
        old_title = header.section
        old_book = self.section_book(old_title) if self.section_kind(old_title) == "book" else None
        title = self._check_section(index, title, book)
        lines = header.text.split("\n")
        for k, line in enumerate(lines):
            if line.strip().strip("{}").strip() == old_title:
                if line.strip() == old_title:
                    lines[k] = title.center(101).rstrip()
                else:
                    lines[k] = line.replace(old_title, title)
                break
        self.items[index] = Raw("\n".join(lines))
        new_book = self.section_book(title) if self.section_kind(title) == "book" else None
        n = 0
        if renumber and old_book and new_book and old_book != new_book:
            for i, e in self.entries(False):
                if e.book == old_book:
                    self.items[i] = e.evolve(encap=f"book{{{new_book}}}{e.encap_rest or ''}")
                    n += 1
        return n

    def add_section(self, title, book=None, after=None):
        """Add a section after the block of the section whose header is at `after` (at the end by default) ; return
        the index of its header."""
        title = self._check_section(None, title, book)
        pos = self.section_bounds(after)[1] if after is not None else len(self.items)
        new = [_header(title), Raw(""), Raw("")] if pos < len(self.items) else [_header(title)]
        if pos == len(self.items) and pos > 0 and not (isinstance(self.items[pos - 1], Raw) and
                                                       self.items[pos - 1].is_blank):
            new.insert(0, Raw(""))
        self.items[pos:pos] = new
        return pos + (1 if isinstance(new[0], Raw) and new[0].is_blank else 0)

    def delete_section(self, index):
        """Remove the header of a section (its entries then belong to the previous section)."""
        header = self.items[index]
        rest = [x for x in header.text.split("\n") if x.strip().strip("{}").strip() != header.section
                and not re.fullmatch(r"\s*(\\comment\{)?\**\}?\s*", x)]
        if rest:
            raise ValueError("this header also holds comments: rename the section instead")
        del self.items[index]
        while 0 < index < len(self.items) and isinstance(self.items[index], Raw) and self.items[index].is_blank and \
                isinstance(self.items[index - 1], Raw) and self.items[index - 1].is_blank:
            del self.items[index]

    def move_section(self, index, step):
        """Move the block of a section before the previous one (step -1) or after the next one (step 1) ; return the
        new index of its header."""
        heads = [i for i, _ in self.sections()]
        k = heads.index(index)
        if not 0 <= k + step < len(heads):
            return index
        a, b = sorted([k, k + step])
        a0, a1 = self.section_bounds(heads[a])
        b0, b1 = self.section_bounds(heads[b])

        def split(block):
            n = len(block)
            while n > 1 and isinstance(block[n - 1], Raw) and block[n - 1].is_blank:
                n -= 1
            return block[:n], block[n:]

        a_body, a_sep = split(self.items[a0:a1])
        b_body, b_sep = split(self.items[b0:b1])
        a_sep = a_sep or [Raw(""), Raw("")]
        self.items[a0:b1] = b_body + a_sep + a_body + b_sep
        return a0 if step < 0 else a0 + len(b_body) + len(a_sep)

    def add_reference(self, path, book, page):
        """Add a reference to the index, applying the template's conventions ; return the index of the new entry.

        :param path: key path, as a string (`Term!Subterm`) or a sequence of levels
        :param book: book identifier (e.g. '2' or 'W')
        :param page: page or page range (e.g. '45' or '45-47')
        """
        new = Entry.make(path, page)
        base, book, page = new.path, str(book), str(page).strip()
        variants, encapped = {}, {}
        for i, e in self.entries():
            if e.kind == "ref" and e.base_path == base and e.book:
                variants.setdefault(e.book, e.path)
                encapped.setdefault((e.book, e.path), i)
        if book in variants:
            vpath = variants[book]
            j = encapped[(book, vpath)]
            other, encap = self.items[j], None
            if other.encap_rest:
                # e.g. `book{4}\lab`: every page needs the full encapsulator
                encap = other.encap
            elif page_sort_key(page) < page_sort_key(other.page):
                # the book must be shown on the first page of the line: move it to the new entry
                encap = other.encap
                self.items[j] = other.evolve(encap=None)
        elif variants:
            longer = [p for p in variants.values() if len(p) > len(base)]
            same = [p for p in variants.values() if len(p) == len(base) and p != base]
            if same and not longer:
                # continue the `Term@ ` idiom used by this reference
                n = max(len(Level.parse(p[-1]).text) for p in same) + 1
                vpath = base[:-1] + (f"{Level.parse(base[-1]).sort}{ACTUAL}{' ' * n}", )
            else:
                vpath = base + (" " * (max([len(p[-1]) for p in longer] + [0]) + 1), )
            encap = f"book{{{book}}}"
        else:
            vpath, encap = base, f"book{{{book}}}"
        entry = Entry.make(list(vpath), page, encap)
        return self.insert(self._position_for(entry, book), entry)

    def _position_for(self, entry, book):
        """Where a new reference goes: after its group in Topics/Categories, else at the end of its book's section."""
        top = entry.path[0]
        last = None
        for i, e in self.entries(False):
            if e.path[0] == top and self.section_kind(self.section_of(i)) in ("topics", "categories"):
                last = i
        if last is not None:
            return last + 1
        group = sort_group(entry.top.sort)
        if group in (0, 1):
            # new topic (symbol sort key) or category (number sort key): after the last one of its section
            kind = ("topics", "categories")[group]
            for start, t in self.sections():
                if self.section_kind(t) == kind:
                    same = [i for i, e in self.entries() if i > start and e.kind in ("ref", "spacer") and
                            sort_group(e.top.sort) == group and self.section_of(i) == t]
                    if same:
                        return same[-1] + 1
                    end = self._section_end(start)
                    while end - 1 > start and isinstance(self.items[end - 1], Entry):
                        end -= 1
                    return end
        return self._section_end(self.book_section(book))

    def fits(self, index, entry):
        """Whether a reference may stand at the given position: in the Topics/Categories section for a topic or a
        category, else in the section of its book (when it has `|book{N}`)."""
        if entry.kind != "ref":
            return True
        title = self.section_of(index)
        top = entry.path[0]
        in_group = any(e.path[0] == top and self.section_kind(self.section_of(i)) in ("topics", "categories")
                       for i, e in self.entries(False) if i != index)
        group = sort_group(entry.top.sort)
        if in_group or group in (0, 1):
            return self.section_kind(title) in ("topics", "categories")
        return entry.book is None or self.section_book(title) == entry.book

    def place(self, entry, after=None):
        """Insert an entry right after the given index if it belongs there (see `fits`), else at its position in the
        block of its book (or of the Topics/Categories) ; return its index."""
        if after is not None and self.fits(after, entry):
            return self.insert(after + 1, entry)
        if entry.kind != "ref" or (entry.book is None and sort_group(entry.top.sort) not in (0, 1)):
            return self.insert(len(self.items) if after is None else after + 1, entry)
        return self.insert(self._position_for(entry, entry.book), entry)

    def relocate(self, index):
        """Move the entry at the given index to the block of its book if it is not in it ; return its new index."""
        entry = self.items[index]
        if not isinstance(entry, Entry) or self.fits(index, entry):
            return index
        del self.items[index]
        return self.place(entry)

    def add_xref(self, source, target):
        """Add a cross-reference `source -> target` in the CROSS-KEYS section ; return its index."""
        e = Entry.make(f"{source} \\goto {target}", "0", "comment")
        start = None
        for i, t in self.sections():
            if self.section_kind(t) == "xrefs":
                start = i
        if start is None:
            start = self.ensure_section("CROSS-KEYS SECTION", ())
        return self.insert(self._section_end(start), e)

    def spacer_key(self, entry):
        """Sort key for a spacer (or page break) placed right after the group of the given entry."""
        top = entry.top.sort.strip()
        used = {e.top.sort.strip() for _, e in self.entries(False) if e.kind not in ("spacer", "pagebreak")}
        if top.isdigit():
            n = int(top) + 1
            if str(n) in used:
                raise ValueError(f"no free category number after {top}, renumber the next category first")
            return str(n)
        if sort_group(top) == 0:
            m = re.match(r"^(\d+)", top)
            return (m.group(1) if m and not top.endswith("z") else top) + "z"
        return top[:1].upper() + "zzzzzz"

    def add_spacer(self, index, pagebreak=False):
        """Insert a blank line (or a page break) after the group of the entry at the given index."""
        e = self.items[index]
        key = self.spacer_key(e) if isinstance(e, Entry) else ("999" if pagebreak else "1z")
        new = Entry((Level("\\blankline", key), ), "0", "newpage \\comment" if pagebreak else "comment")
        return self.insert(index + 1, new)

    # ---------------------------------------------------- checks ----------------------------------------------------
    def check(self, commands=None):
        """Return the list of :class:`Problem`'s of the index.

        :param commands: set of the LaTeX commands known by the template (unknown ones are reported if given)
        """
        problems, eff, seen, first = [], self.effective_books(), {}, {}
        ln = self.line_numbers()
        comment_lines = set()
        for i, it in enumerate(self.items):
            if isinstance(it, Raw) and not it.is_comment_block and "\\indexentry" in it.text \
               and not it.text.lstrip().startswith("%"):
                problems.append(Problem(i, "error", "malformed \\indexentry (unbalanced braces?)"))
            elif isinstance(it, Raw) and it.is_comment_block:
                comment_lines.add(i)
        for i, e in self.entries():
            text = e.key
            if e.kind == "ref":
                if not eff.get(i):
                    problems.append(Problem(i, "warning", "no book for this page: add |book{N} or a line with it"))
                if (err := page_error(e.page)):
                    problems.append(Problem(i, "warning", f"page '{e.page}': {err}"))
                k = (e.path, eff.get(i), e.page.strip())
                if k in seen:
                    problems.append(Problem(i, "warning", f"duplicate of line {ln[seen[k]]}"))
                seen.setdefault(k, i)
                if e.top.key is None and e.top.text.startswith("\\") and len(e.levels) >= 1:
                    problems.append(Problem(i, "warning", "starts with a command but has no sort key: it will be "
                                                          "sorted in Topics (use key@text)"))
                b = eff.get(i)
                if b:
                    first.setdefault((e.path, b), []).append(i)
            if commands is not None:
                for cmd in sorted(set(re.findall(r"\\([A-Za-z]+)", text))):
                    if cmd not in commands:
                        problems.append(Problem(i, "warning", f"unknown command \\{cmd}"))
        for (path, b), idxs in first.items():
            book_idx = [i for i in idxs if self.items[i].book]
            if not book_idx:
                continue
            low = min(idxs, key=lambda i: page_sort_key(self.items[i].page))
            if not self.items[low].book:
                problems.append(Problem(book_idx[0], "warning", f"book number not on the first page: page "
                                        f"{self.items[low].page} (line {ln[low]}) comes first"))
        return sorted(problems, key=lambda p: p.index)
