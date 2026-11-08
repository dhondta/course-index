# -*- coding: UTF-8 -*-
"""Virtual list of the lines of the index: only the visible rows are rendered, so that refreshing it is instant
whatever the size of the index."""
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.geometry import Size
from textual.message import Message
from textual.reactive import reactive
from textual.scroll_view import ScrollView
from textual.strip import Strip

__all__ = ["EntryList"]

COLUMNS = [("Line", 6, "right"), ("Term", 0, "left"), ("Book", 5, "left"), ("Pages", 10, "left"), ("", 2, "left")]


class EntryList(ScrollView, can_focus=True):
    """Rows of cells (Rich Texts) with a cursor, rendered on demand."""
    COMPONENT_CLASSES = {"entry-list--cursor", "entry-list--zebra", "entry-list--header"}
    DEFAULT_CSS = """
    EntryList {
        background: $surface;
    }
    EntryList > .entry-list--cursor {
        background: $accent 40%;
        text-style: bold;
    }
    EntryList:focus > .entry-list--cursor {
        background: $accent;
    }
    EntryList > .entry-list--zebra {
        background: $boost;
    }
    EntryList > .entry-list--header {
        text-style: bold;
        color: $text-muted;
        background: $panel;
    }
    """
    BINDINGS = [
        Binding("up", "cursor(-1)", show=False),
        Binding("down", "cursor(1)", show=False),
        Binding("pageup", "page(-1)", show=False),
        Binding("pagedown", "page(1)", show=False),
        Binding("home", "jump(0)", show=False),
        Binding("end", "jump(-1)", show=False),
        Binding("enter", "select", show=False),
    ]
    cursor_row = reactive(0, always_update=True)

    class Selected(Message):
        def __init__(self, entry_list, row):
            super().__init__()
            self.entry_list, self.row = entry_list, row

        @property
        def control(self):
            return self.entry_list

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.rows, self._center = [], False

    # ---------------------------------------------------------- data ------------------------------------------------
    @property
    def row_count(self):
        return len(self.rows)

    def set_rows(self, rows):
        self.rows = rows
        self.virtual_size = Size(self.size.width, len(rows) + 1)
        if self.cursor_row >= len(rows):
            self.cursor_row = max(0, len(rows) - 1)
        self.refresh()

    def move_cursor(self, row, animate=False, center=False):
        self._center = center
        self.cursor_row = max(0, min(row, len(self.rows) - 1))

    def scroll_to_cursor(self, center=False):
        """Scroll so that the cursor is visible (row 0 of the content is the header)."""
        height = self.scrollable_content_region.height - 1
        if height <= 0:
            return
        row, y = self.cursor_row, self.scroll_offset.y
        if center and not y <= row < y + height:
            self.scroll_to(y=max(0, row - height // 2), animate=False)
        elif row < y:
            self.scroll_to(y=row, animate=False)
        elif row >= y + height:
            self.scroll_to(y=row - height + 1, animate=False)

    def watch_cursor_row(self, old, new):
        self.refresh()
        self.scroll_to_cursor(self._center)
        self._center = False

    # --------------------------------------------------------- actions ----------------------------------------------
    def action_cursor(self, step):
        self.move_cursor(self.cursor_row + step)

    def action_page(self, step):
        self.move_cursor(self.cursor_row + step * max(1, self.scrollable_content_region.height - 2))

    def action_jump(self, row):
        self.move_cursor(row if row >= 0 else len(self.rows) - 1)

    def action_select(self):
        if self.rows:
            self.post_message(self.Selected(self, self.cursor_row))

    def on_click(self, event):
        row = event.y + self.scroll_offset.y - 1
        if 0 <= row < len(self.rows):
            self.move_cursor(row)
            if event.chain == 2:
                self.action_select()

    # --------------------------------------------------------- render -----------------------------------------------
    def _widths(self, width):
        fixed = sum(w for _, w, _ in COLUMNS)
        return [w or max(10, width - fixed - 1) for _, w, _ in COLUMNS]

    def _line(self, cells, width, style):
        widths = self._widths(width)
        line = Text(end="", no_wrap=True)
        for cell, w, (_, _, justify) in zip(cells, widths, COLUMNS):
            cell = cell.copy() if isinstance(cell, Text) else Text(str(cell))
            cell.truncate(w - 1, overflow="ellipsis")
            if justify == "right":
                cell.pad_left(w - 1 - cell.cell_len)
                cell.append(" ")
            else:
                cell.pad_right(w - cell.cell_len)
            line.append_text(cell)
        line.truncate(width, pad=True)
        segments = list(line.render(self.app.console))
        return Strip(segments, width).apply_style(style) if style else Strip(segments, width)

    def render_line(self, y):
        width = self.scrollable_content_region.width
        if y == 0:
            style = self.get_component_rich_style("entry-list--header")
            return self._line([Text(n) for n, _, _ in COLUMNS], width, style)
        row = self.scroll_offset.y + y - 1
        if row >= len(self.rows):
            return Strip([Segment(" " * width)], width)
        if row == self.cursor_row:
            style = self.get_component_rich_style("entry-list--cursor")
        elif row % 2:
            style = self.get_component_rich_style("entry-list--zebra")
        else:
            style = Style()
        return self._line(self.rows[row], width, style)

    def on_resize(self, event):
        self.virtual_size = Size(event.size.width, len(self.rows) + 1)
        self.call_after_refresh(self.scroll_to_cursor)
