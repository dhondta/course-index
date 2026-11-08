# -*- coding: UTF-8 -*-
"""Approximate rendering of the LaTeX used in index entries, for display in the terminal."""
import re

from rich.text import Text

__all__ = ["ICONS", "auto_sort_key", "expand_shortcuts", "known_commands", "plain", "render"]

# commands of the template displaying an icon
ICONS = {
    "all": "💻", "android": "🤖", "app": "📱", "cloud": "🌥", "coin": "💲", "dotnet": "🔷", "executive": "👔",
    "file": "📄", "go": "🐹", "group": "👥", "individual": "👤", "ios": "🍏", "linux": "🐧", "mac": "🍏",
    "malware": "🦠", "note": "📝", "option": "🔘", "perl": "🐪", "portable": "💾", "powershell": "🐚",
    "python": "🐍", "q": "❓", "ruby": "💎", "script": "📜", "solar": "🌞", "tool": "🔧", "toolb": "🔧",
    "toolr": "🛠", "tuto": "🎓", "volume": "📖", "web": "🌐", "win": "🪟",
}
# images of the template's lib folder, for \icon{...}
_IMAGES = {
    "android": "🤖", "app": "📱", "book": "📖", "cloud": "🌥", "cross-platform": "💻", "dollar": "💲", "dotnet": "🔷",
    "executive": "👔", "file": "📄", "go": "🐹", "group": "👥", "individual": "👤", "k8s": "☸", "linux": "🐧",
    "mac": "🍏", "malware": "🦠", "note": "📝", "option": "🔘", "perl": "🐪", "portable": "💾", "powershell": "🐚",
    "python": "🐍", "question": "❓", "ruby": "💎", "script": "📜", "solaris": "🌞", "tool": "🔧", "tool_blue": "🔧",
    "tool_red": "🛠", "tuto": "🎓", "warning": "⚠", "web": "🌐", "windows": "🪟",
}
_STYLES = {
    "textbf": "bold", "texttt": "cyan", "textit": "italic", "emph": "italic", "textsl": "italic", "underline": "underline",
    "cmd": "cyan", "cmds": "cyan", "cmdxs": "cyan", "textsc": "", "text": "", "mbox": "", "textrm": "", "textsf": "",
    "tiny": "", "scriptsize": "", "footnotesize": "", "small": "", "large": "", "Large": "", "LARGE": "",
}
_SYMBOLS = {
    "goto": "→ ", "to": "→", "bs": "\\", "textbackslash": "\\", "textbar": "|", "textellipsis": "…", "ldots": "…",
    "dots": "…", "textgreater": ">", "textless": "<", "textasciitilde": "~", "textasciicircum": "^", "star": "★",
    "linebreak": " ", "newline": " ", "blankline": "", "comment": "", "dotfill": " … ", "quad": " ", "qquad": "  ",
    "rightarrow": "→", "leftarrow": "←", "times": "×", "copyright": "©", "textregistered": "®", "texttrademark": "™",
    "cc": "", "ccby": "", "ccbysa": "", "newpage": "",
}
# standard LaTeX commands that may appear in index entries (for checking unknown commands)
_STANDARD = set(_STYLES) | set(_SYMBOLS) | {
    "hspace", "hskip", "vspace", "includegraphics", "indexentry", "textcolor", "color", "url", "href", "LaTeX", "TeX",
    "textquotesingle", "textquotedbl", "textunderscore", "textendash", "textemdash", "S", "P", "ss", "o", "O",
    "ae", "AE", "oe", "OE", "aa", "AA", "l", "L", "i", "j", "linewidth", "textwidth", "ensuremath", "textsuperscript",
    "textsubscript", "pm", "le", "ge", "neq", "approx", "infty", "cdot", "bullet", "textbullet", "item", "nolinebreak",
    "allowbreak", "hfill", "relax", "string", "verb", "textdollar", "textdegree", "lab",
}
_ESCAPES = {"&": "&", "%": "%", "#": "#", "_": "_", "$": "$", "{": "{", "}": "}", " ": " ", "\\": " ", ",": " ",
            "!": "", ";": " ", ":": " ", "-": "", "/": "", "@": ""}


def _group_end(s, i):
    depth = 0
    for j in range(i, len(s)):
        c = s[j]
        if c == "\\":
            continue
        if c == "{" and (j == 0 or s[j - 1] != "\\"):
            depth += 1
        elif c == "}" and (j == 0 or s[j - 1] != "\\"):
            depth -= 1
            if depth == 0:
                return j
    return len(s)


def _render(s, out, style="", icons=True):
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            m = re.match(r"[A-Za-z]+", s[i+1:])
            if not m:
                out.append(_ESCAPES.get(s[i+1], s[i+1]), style)
                i += 2
                continue
            name, i = m.group(0), i + 1 + len(m.group(0))
            while i < n and s[i] in " \t":
                i += 1
            arg = None
            if name in ("hskip", "vskip", "kern"):
                m = re.match(r"-?[\d.]+\s*[a-z]{2}", s[i:])
                i += len(m.group(0)) if m else 0
                out.append(" ", style)
                continue
            if i < n and s[i] == "[" and name == "includegraphics":
                i = s.find("]", i) + 1 or n
            if i < n and s[i] == "{" and name not in _SYMBOLS and name not in ICONS:
                j = _group_end(s, i)
                arg, i = s[i+1:j], j + 1
            if name in ICONS:
                if icons:
                    out.append(ICONS[name] + " ", style)
            elif name == "icon" and arg is not None:
                if icons:
                    out.append(_IMAGES.get(arg.strip(), f"[{arg.strip()}]") + " ", style)
            elif name == "includegraphics":
                if icons:
                    out.append("🖼 ", style)
            elif name == "rate" and arg is not None:
                n_stars = int(arg) if arg.strip().isdigit() else 0
                out.append(" " + "★" * n_stars + " ", (style + " yellow").strip())
            elif name in ("hspace", "vspace"):
                out.append(" ", style)
            elif name == "lab" and arg is not None:
                out.append("L" + arg, style)
            elif name in ("textcolor", "href") and arg is not None:
                # first argument is the color or URL, the second one is the text
                if i < n and s[i] == "{":
                    j = _group_end(s, i)
                    arg, i = s[i+1:j], j + 1
                _render(arg, out, style, icons)
            elif name in _SYMBOLS:
                out.append(_SYMBOLS[name], style)
            elif name in _STYLES:
                if arg is not None:
                    _render(arg, out, (style + " " + _STYLES[name]).strip(), icons)
            elif arg is not None:
                _render(arg, out, style, icons)
            else:
                out.append("\\" + name + " ", (style + " dim").strip())
        elif c == "{":
            j = _group_end(s, i)
            _render(s[i+1:j], out, style, icons)
            i = j + 1
        elif c == "}":
            i += 1
        elif c == "$":
            j = s.find("$", i + 1)
            j = n if j < 0 else j
            _render(s[i+1:j], out, style, icons)
            i = j + 1
        elif c == "~":
            out.append(" ", style)
            i += 1
        elif s.startswith("---", i):
            out.append("—", style)
            i += 3
        elif s.startswith("--", i):
            out.append("–", style)
            i += 2
        elif c == '"' and i + 1 < n:
            # makeindex quote character
            out.append(s[i+1], style)
            i += 2
        else:
            j = i
            while j < n and s[j] not in "\\{}$~-\"":
                j += 1
            j = max(j, i + 1)
            out.append(s[i:j], style)
            i = j


def render(s, style="", icons=True):
    """Render a LaTeX snippet as a Rich Text (bold, monospace, icons as emojis, stars, ...)."""
    out = _Segments()
    _render(s or "", out, style, icons)
    # collapse whitespace like LaTeX does
    res, prev_space = Text(), True
    for text, st in out:
        text = _WS.sub(" ", text)
        if prev_space:
            text = text.lstrip(" ")
        if text:
            res.append(text, st or None)
            prev_space = text.endswith(" ")
    res.rstrip()
    return res


class _Segments(list):
    """Minimal stand-in for Text.append, collecting (text, style) segments."""
    def append(self, text, style=""):
        super().append((text, style))

    @property
    def plain(self):
        return "".join(t for t, _ in self)


_WS = re.compile(r"\s+")


def plain(s, icons=True):
    """Render a LaTeX snippet as plain text."""
    out = _Segments()
    _render(s or "", out, "", icons)
    return re.sub(r"\s+", " ", out.plain).strip()


def auto_sort_key(text):
    """Sort key for a text starting with markup (e.g. `\\texttt{.htaccess}` -> `Htaccess`), None if not needed."""
    if not text.startswith("\\") or text.strip() == "\\blankline":
        return
    p = re.sub(r"^[^A-Za-z0-9]+", "", plain(text, icons=False).replace("★", "")).strip()
    if not p:
        return
    p = p.replace("!", "").replace("@", "").replace("|", "").replace('"', "")
    return p[:1].upper() + p[1:]


def expand_shortcuts(text):
    """Expand the input shortcuts of the editor: `x` -> \\texttt{x}, **x** -> \\textbf{x}, *x* -> \\textit{x},
    :linux: -> \\linux (any icon command), and escape bare LaTeX special characters (_ & % #)."""
    text = re.sub(r"`([^`]+)`", r"\\texttt{\1}", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\\textbf{\1}", text)
    text = re.sub(r"(?<![\\*])\*([^*\s][^*]*)\*", r"\\textit{\1}", text)
    text = re.sub(r":([a-z]+):\s?", lambda m: f"\\{m.group(1)} " if m.group(1) in ICONS else m.group(0), text)
    text = re.sub(r"(?<!\\)([_&%#])", r"\\\1", text)
    return re.sub(r"\s+$", "", text) if text.strip() else text


def known_commands(main_tex):
    """Set of the commands available in index entries, given the content of the template's main.tex."""
    cmds = set(_STANDARD)
    cmds |= set(re.findall(r"\\(?:re)?newcommand\*?\s*\{?\\([A-Za-z]+)", main_tex))
    cmds |= set(re.findall(r"\\def\\([A-Za-z]+)", main_tex))
    return cmds
