# -*- coding: UTF-8 -*-
"""Approximation of the index as makeindex typesets it, for previewing it without compiling."""
from dataclasses import dataclass, field

from .idx import Level, page_sort_key, sort_group, sort_tuple

__all__ = ["Node", "build", "format_pages"]

GROUP_TITLES = {0: "Topics", 1: "Categories"}


@dataclass
class Node:
    """One line of the index: a level with its pages and sub-levels."""
    level: Level | None
    kind: str = "ref"
    refs: list = field(default_factory=list)       # (page, encap) tuples
    items: list = field(default_factory=list)      # indices of the contributing entries
    children: dict = field(default_factory=dict)   # str(level) -> Node

    def sorted_children(self):
        return sorted(self.children.values(), key=lambda n: (sort_tuple(n.level.sort), n.level.text))


def format_pages(refs, code):
    """Format the pages of a line like the template (e.g. `504.1–15, 107, 504.2–3`)."""
    out = []
    for page, encap in sorted(refs, key=lambda r: page_sort_key(r[0])):
        book = None
        if encap and encap.startswith("book{"):
            book, rest = encap[5:].split("}", 1)
            page = ("L" + page) if "\\lab" in rest else page
        out.append(f"{code}.{book}–{page}" if book else page)
    return ", ".join(out)


def build(doc):
    """Build the index tree: an ordered list of (group title, [Node]) like the sections of the PDF."""
    groups = {}
    for i, e in doc.entries():
        g = sort_group(e.top.sort)
        title = GROUP_TITLES.get(g) or e.top.sort.lstrip()[:1].upper()
        node, children = None, groups.setdefault((g, title), {})
        for lv in e.levels:
            node = children.setdefault(str(lv), Node(lv))
            children = node.children
        node.items.append(i)
        if e.kind in ("ref", ):
            node.refs.append((e.page, e.encap))
        elif node.kind == "ref" and not node.refs:
            node.kind = e.kind
    result = []
    for (g, title), children in sorted(groups.items(), key=lambda x: (x[0][0], x[0][1])):
        root = Node(None, children=children)
        result.append((title, root.sorted_children()))
    return result
