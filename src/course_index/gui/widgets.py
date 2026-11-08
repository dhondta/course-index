# -*- coding: UTF-8 -*-
"""Building blocks of the GUI: theme colors, rendering of Rich Texts as HTML, the virtual table of the lines of the
index, line edits with key handlers, the footer of shortcuts and the notifications."""
import io
from html import escape

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAbstractTextDocumentLayout, QPalette, QTextDocument
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QStyle, QStyledItemDelegate, \
                              QStyleOptionViewItem, QTableView, QVBoxLayout, QWidget
from rich.console import Console
from rich.text import Text

__all__ = ["COLUMNS", "EntryModel", "EntryView", "Field", "Footer", "HTML_ROLE", "HtmlDelegate", "KeyLineEdit",
           "Toasts", "colors", "is_dark", "to_html"]

HTML_ROLE = Qt.ItemDataRole.UserRole + 1
COLUMNS = [("Line", Qt.AlignmentFlag.AlignRight), ("Term", Qt.AlignmentFlag.AlignLeft),
           ("Book", Qt.AlignmentFlag.AlignLeft), ("Pages", Qt.AlignmentFlag.AlignLeft),
           ("", Qt.AlignmentFlag.AlignCenter)]

# colors of the Rich styles used by the rendering of the LaTeX and by the tables (dark theme, light theme)
_COLORS = {
    "accent": ("#ffa62b", "#b45309"),
    "cyan": ("#56c8d8", "#00838f"),
    "yellow": ("#e5c07b", "#9a6700"),
    "magenta": ("#ff4f8b", "#c2185b"),
    "red": ("#ff5f6d", "#c62828"),
    "green": ("#98c379", "#2e7d32"),
    "blue": ("#61afef", "#1565c0"),
    "dim": ("#8b8f98", "#80848c"),
}
_console = Console(file=io.StringIO(), width=100000, color_system="truecolor", force_terminal=False)


def is_dark(palette=None):
    palette = palette or QApplication.palette()
    return palette.color(QPalette.ColorRole.Window).lightness() < 128


def colors():
    """Colors of the current theme, by Rich color name (plus `accent` and `dim`)."""
    k = 0 if is_dark() else 1
    return {name: values[k] for name, values in _COLORS.items()}


def to_html(text, pre=True):
    """HTML rendering of a Rich Text (or of a string) for Qt's rich text."""
    if text is None:
        return ""
    if isinstance(text, str):
        text = Text(text)
    c = colors()
    out = []
    # Text.render leaves out the base style of the text
    base = _console.get_style(text.style) if text.style else None
    for seg in text.render(_console, end=""):
        if not seg.text:
            continue
        s = escape(seg.text)
        st = (base + seg.style if seg.style else base) if base else seg.style
        if st:
            if st.bold:
                s = f"<b>{s}</b>"
            if st.italic:
                s = f"<i>{s}</i>"
            if st.underline:
                s = f"<u>{s}</u>"
            if st.strike:
                s = f"<s>{s}</s>"
            color = c.get(st.color.name.replace("bright_", "")) if st.color else None
            if st.dim and color is None:
                color = c["dim"]
            if color:
                s = f'<span style="color:{color}">{s}</span>'
        out.append(s)
    html = "".join(out)
    return f'<span style="white-space:pre">{html}</span>' if pre else html.replace("\n", "<br>")


# --------------------------------------------------------------------------------------------------------------------
class HtmlDelegate(QStyledItemDelegate):
    """Paint the cells holding HTML (HTML_ROLE) as rich text on one line, clipped to the cell."""
    def _doc(self, html, font):
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(font)
        doc.setHtml(html)
        return doc

    def paint(self, painter, option, index):
        html = index.data(HTML_ROLE)
        if html is None:
            return super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        doc = self._doc(html, opt.font)
        ctx = QAbstractTextDocumentLayout.PaintContext()
        selected = opt.state & QStyle.StateFlag.State_Selected
        ctx.palette.setColor(QPalette.ColorRole.Text, opt.palette.color(
            QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text))
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, widget)
        x = rect.left() + 2
        if opt.displayAlignment & Qt.AlignmentFlag.AlignRight:
            x = rect.right() - 4 - doc.idealWidth()
        elif opt.displayAlignment & Qt.AlignmentFlag.AlignHCenter:
            x = rect.left() + (rect.width() - doc.idealWidth()) / 2
        painter.save()
        painter.translate(x, rect.top() + (rect.height() - doc.size().height()) / 2)
        painter.setClipRect(QRectF(rect.left() - x, 0, rect.width() - 2, rect.height()))
        doc.documentLayout().draw(painter, ctx)
        painter.restore()

    def sizeHint(self, option, index):
        html = index.data(HTML_ROLE)
        if html is None:
            return super().sizeHint(option, index)
        doc = self._doc(html, option.font)
        return QSize(int(doc.idealWidth()) + 8, int(doc.size().height()) + 4)


# --------------------------------------------------------------------------------------------------------------------
class EntryModel(QAbstractTableModel):
    """Rows of cells (Rich Texts or strings): Line, Term, Book, Pages, flag. The HTML of the cells is computed when
    they are shown only, so that refreshing the model is instant whatever the size of the index."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows, self._html = [], {}

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows, self._html = rows, {}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                return COLUMNS[section][0]
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int(COLUMNS[section][1] | Qt.AlignmentFlag.AlignVCenter)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        cell = self.rows[index.row()][index.column()]
        if role == HTML_ROLE:
            key = (index.row(), index.column())
            if key not in self._html:
                self._html[key] = to_html(cell)
            return self._html[key]
        if role == Qt.ItemDataRole.DisplayRole:
            return cell.plain if isinstance(cell, Text) else str(cell)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(COLUMNS[index.column()][1] | Qt.AlignmentFlag.AlignVCenter)
        return None


class EntryView(QTableView):
    """Table of the lines of the index: one row per line, with a row cursor ; the keys are handled by the window."""
    keyPressed = Signal(object)                        # QKeyEvent, accepted when the window handled it
    caretClicked = Signal(int)                         # row whose section caret was clicked

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModel(EntryModel(self))
        self.setItemDelegate(HtmlDelegate(self))
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setTabKeyNavigation(False)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 6)
        self.verticalHeader().setMinimumSectionSize(self.fontMetrics().height() + 2)
        h = self.horizontalHeader()
        h.setHighlightSections(False)
        h.setSectionResizeMode(h.ResizeMode.Interactive)
        h.setStretchLastSection(False)
        w = self.fontMetrics().horizontalAdvance("0")
        for col, width in ((0, 7), (2, 6), (3, 10), (4, 3)):
            self.setColumnWidth(col, width * w + 12)
        h.setSectionResizeMode(1, h.ResizeMode.Stretch)
        self.is_header_row = lambda row: False

    @property
    def rows(self):
        return self.model().rows

    def set_rows(self, rows):
        self.model().set_rows(rows)

    @property
    def cursor_row(self):
        i = self.currentIndex()
        return i.row() if i.isValid() else 0

    def move_cursor(self, row, center=False):
        n = len(self.rows)
        if not n:
            return
        row = max(0, min(row, n - 1))
        index = self.model().index(row, 1)
        self.setCurrentIndex(index)
        self.scrollTo(index, QTableView.ScrollHint.PositionAtCenter if center else QTableView.ScrollHint.EnsureVisible)

    def keyPressEvent(self, event):
        event.ignore()
        self.keyPressed.emit(event)
        if not event.isAccepted():
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        # a click on the line number or on the caret of a section header expands or collapses it
        if index.isValid() and event.button() == Qt.MouseButton.LeftButton and self.is_header_row(index.row()):
            x = event.position().x()
            caret_end = self.columnViewportPosition(1) + 3 * self.fontMetrics().horizontalAdvance("▶")
            if x < caret_end:
                self.move_cursor(index.row())
                self.caretClicked.emit(index.row())
                return
        super().mousePressEvent(event)


# --------------------------------------------------------------------------------------------------------------------
class KeyLineEdit(QLineEdit):
    """Line edit whose keys can be handled by callables: `handlers[(key, modifiers)] = callable`, which returns False
    to let the key through. Tab and Backtab are handled too (before the focus moves)."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.handlers = {}

    def _handle(self, event):
        mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        handler = self.handlers.get((event.key(), mods))
        return handler is not None and handler() is not False

    def event(self, event):
        if event.type() == event.Type.KeyPress and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) and \
           self._handle(event):
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if not self._handle(event):
            super().keyPressEvent(event)

    def set_invalid(self, message=None):
        """Show a validation error (red border and tooltip), or clear it."""
        self.setProperty("invalid", bool(message))
        self.setToolTip(message or self.property("help") or "")
        self.style().unpolish(self)
        self.style().polish(self)


class Field(QWidget):
    """Line edit with its caption above it (like a border title)."""
    def __init__(self, caption, edit, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        self.caption = QLabel(caption)
        self.caption.setObjectName("caption")
        self.edit = edit
        lay.addWidget(self.caption)
        lay.addWidget(edit)


# --------------------------------------------------------------------------------------------------------------------
class _Key(QLabel):
    def __init__(self, key, label, callback, parent=None):
        super().__init__(parent)
        self.callback = callback
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setText(f'<b style="color:{colors()["accent"]}">{escape(key)}</b>&nbsp;{escape(label)}')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContentsMargins(6, 2, 6, 2)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.callback()


class Footer(QFrame):
    """Keys of the focused widget, then the keys of the window, each one clickable."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("footer")
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(4, 0, 4, 0)
        self.lay.setSpacing(4)
        self._keys = None

    def set_keys(self, keys):
        """:param keys: list of (key, label, callback)"""
        sig = [(k, label) for k, label, _ in keys]
        if sig == self._keys:
            return
        self._keys = sig
        while self.lay.count():
            w = self.lay.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        for key, label, cb in keys:
            self.lay.addWidget(_Key(key, label, cb, self))
        self.lay.addStretch(1)


class Toasts(QWidget):
    """Notifications stacked in the bottom right corner of the window, hidden after a timeout."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(6)
        self.lay.addStretch(1)
        self.hide()
        parent.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.parent() and event.type() == event.Type.Resize:
            self._place()
        return False

    def _place(self):
        p = self.parent()
        width = min(460, p.width() - 32)
        self.adjustSize()
        h = self.sizeHint().height()
        self.setGeometry(p.width() - width - 16, p.height() - h - 44, width, h)
        self.raise_()

    def notify(self, message, severity="information", timeout=5):
        c = colors()
        border = {"error": c["red"], "warning": c["yellow"]}.get(severity, c["green"])
        label = QLabel(self)
        label.setObjectName("toast")
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        title = {"error": "Error", "warning": "Warning"}.get(severity)
        html = to_html(message, pre=False)
        label.setText((f'<b style="color:{border}">{title}</b><br>' if title else "") + html)
        label.setStyleSheet(f"#toast {{ border-left: 4px solid {border}; }}")
        label.setToolTip("Click to close")
        label.mousePressEvent = lambda e, w=label: self._close(w)
        self.lay.addWidget(label)
        self.show()
        self._place()
        QTimer.singleShot(int(timeout * 1000), lambda w=label: self._close(w))
        return label

    def _close(self, label):
        try:
            label.hide()
            self.lay.removeWidget(label)
            label.deleteLater()
        except RuntimeError:                           # already deleted
            return
        if self.lay.count() <= 1:
            self.hide()
        else:
            self._place()

    def messages(self):
        """Texts of the notifications shown (for the tests)."""
        return [self.lay.itemAt(i).widget().text() for i in range(self.lay.count())
                if self.lay.itemAt(i).widget() is not None]
