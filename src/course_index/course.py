# -*- coding: UTF-8 -*-
"""Course metadata, stored in the template's `data.tex`."""
import re
from dataclasses import dataclass, fields
from pathlib import Path

from .idx import _group

__all__ = ["CourseInfo", "data_file_for"]

_FIELDS = {"code": "coursecode", "title": "coursetitle", "date": "coursedate", "version": "courseversion",
           "author": "indexauthor"}


@dataclass
class CourseInfo:
    """Course attributes used by the template (header, footer and book prefix of the page numbers)."""
    code: str = "123"
    title: str = "C\\coursecode\\ -- Course Title"
    date: str = ""
    version: str = ""
    author: str = ""

    @property
    def display_title(self):
        t = self.title.replace("\\coursecode", self.code).replace("\\ ", " ").replace("--", "–")
        return re.sub(r"\s+", " ", t).strip()

    @classmethod
    def parse(cls, text):
        info, found = cls(), {}
        for attr, macro in _FIELDS.items():
            m = re.search(r"\\def\\" + macro + r"\s*(?=\{)", text)
            if m:
                j = _group(text, m.end())
                if j > 0:
                    found[attr] = text[m.end() + 1:j - 1]
        for attr, value in found.items():
            setattr(info, attr, value)
        if "author" not in found:
            info.author = ""
        return info

    @classmethod
    def guess(cls, idx_path):
        """Default metadata for an index without data file, from its name (e.g. `sec504.idx` -> code 504)."""
        stem = Path(idx_path).stem
        m = re.search(r"\d+", stem)
        info = cls()
        if m and stem != "main":
            info.code, info.title = m.group(0), stem.upper()
        return info

    @classmethod
    def load(cls, path):
        return cls.parse(Path(path).read_text(encoding="utf-8"))

    def dumps(self, original=None):
        """Serialize to `data.tex`, keeping the other lines of the original content if given."""
        text = original or ""
        for attr, macro in _FIELDS.items():
            value = getattr(self, attr)
            line = f"\\def\\{macro}{{{value}}}"
            m = re.search(r"\\def\\" + macro + r"\s*(?=\{)", text)
            if m and (j := _group(text, m.end())) > 0:
                if attr == "author" and not value:
                    # \indexauthor must stay undefined when empty (main.tex tests \ifdefined)
                    end = j + (1 if text[j:j+1] == "\n" else 0)
                    text = text[:m.start()] + text[end:]
                else:
                    text = text[:m.start()] + line + text[j:]
            elif attr != "author" or value:
                text = (text.rstrip("\n") + "\n" if text.strip() else "") + line + "\n"
        return text

    def save(self, path):
        path = Path(path)
        original = path.read_text(encoding="utf-8") if path.exists() else None
        path.write_text(self.dumps(original), encoding="utf-8")

    def as_dict(self):
        return {f.name: getattr(self, f.name) for f in fields(self)}


def data_file_for(idx_path):
    """Course metadata file of an index: `<name>.data.tex` (several indexes in one folder) or `data.tex`."""
    idx_path = Path(idx_path)
    own, shared = idx_path.with_name(idx_path.stem + ".data.tex"), idx_path.with_name("data.tex")
    if own.exists():
        return own
    if shared.exists() or idx_path.stem == "main":
        return shared
    return own
