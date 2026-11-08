# Python API

The modules used by the GUI and the TUI can be used from Python, e.g. to generate or fix an index with a script.

## Reading and writing an index

```python
from course_index import Document

doc = Document.load("sec504.idx")
for i, entry in doc.entries():
    print(entry.path, entry.book, entry.page, entry.kind)

with open("sec504.idx", "w", newline="") as f:
    f.write(doc.dumps())  # unchanged lines are written back as they were read
```

`Document.items` is the list of the lines of the file: `Entry` objects (one `\indexentry`) and `Raw` objects
(comments, section headers, blank lines). Both are immutable: replace an item to change it.

```python
from course_index import Entry, Level

e = doc.items[42]
doc.items[42] = e.evolve(page="43")                  # same entry, another page
doc.items.insert(43, Entry.make("Netcat!Relays", "50", "book{3}"))
```

### `Entry`

| Attribute | Description |
|---|---|
| `levels` | tuple of `Level(text, key=None)` |
| `page`, `encap`, `disabled` | page(s), encapsulator (after `\|`), commented out with `%` |
| `book`, `encap_rest` | book of `\|book{N}...` and what follows it |
| `kind` | `ref`, `spacer`, `pagebreak`, `xref` or `hidden` |
| `path`, `base_path` | key path, and without the blank levels of additional books |
| `to_line()` | the `\indexentry` line |

## Adding references with the template's conventions

```python
i = doc.add_reference("Netcat!Relays", "3", "50")   # returns the index of the new entry
doc.add_reference(["Htaccess@\\texttt{.htaccess}"], "2", "17")
doc.add_xref("nc", "Netcat")
doc.add_spacer(i)                                   # blank line after the group of entry i
doc.add_spacer(i, pagebreak=True)
doc.place(Entry.make("Nmap", "12", "book{2}"), after=i)  # after i if in book 2's section, else in that section
doc.relocate(i)                                     # move entry i to the section of its book if needed
```

## Sections

```python
i = doc.sections()[2][0]                             # index of the header of the 3rd section
doc.set_section(i, "SANS 504.1 SECTION", "7", renumber=True)  # -> SANS 504.7, |book{1} -> |book{7}
doc.add_section("Labs", after=i)                     # LABS SECTION, after the block of section i
top = doc.chapters()["2"]                            # Topics group of the parts of book 2, e.g. '2a@\textbf{Recon}'
doc.rename_chapter(top, r"Recon \& Mapping")         # -> 2a@\textbf{Recon \& Mapping} in all its entries
doc.move_section(i, -1)                              # before the previous section
doc.delete_section(i)                                # the header only
Document.retitle("FIRST BOOK SECTION", "1", "2")     # 'SECOND BOOK SECTION'
```

## Queries and checks

```python
doc.sections()            # [(index, "TOPICS SECTION"), ...]
doc.books()               # ["1", "2", ..., "W"]
doc.effective_books()     # {index: book}, including pages written without |book{N}
doc.paths()               # {base path: {books}}
doc.line_numbers()        # file line number of each item
for p in doc.check():     # Problem(index, severity, message)
    print(p)
```

## Course metadata and compilation

```python
from course_index import CourseInfo, compile_pdf, data_file_for

info = CourseInfo.load(data_file_for("sec504.idx"))
info.code = "504"
info.save(data_file_for("sec504.idx"))

result = compile_pdf("sec504.idx")      # BuildResult(ok, pdf, errors, warnings, log)
print(result.summary)
```

`compile_pdf(idx_path, output=None, document=None, course=None)` can also compile a `Document` and a `CourseInfo`
held in memory.
