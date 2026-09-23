from __future__ import annotations

from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.widgets import DataTable, Input

from termnetlog.models import CheckInRow
from termnetlog.tui import format as fmt

FLAG_BADGES = [
    ("has_traffic", "T", "bold white on red"),
    ("recognized", "✓", "bold green"),
    ("short_time", "S", "yellow"),
    ("mobile", "M", "cyan"),
    ("portable", "P", "cyan"),
    ("echolink", "E", "cyan"),
    ("ragchew", "☕", "bold yellow"),
]


def flag_cell(row: CheckInRow) -> Text:
    text = Text()
    for flag, badge, style in FLAG_BADGES:
        if getattr(row.checkin, flag):
            text.append(badge, style=style)
            text.append(" ")
    if row.checkin.relayed_by:
        text.append(f"via {row.checkin.relayed_by}", style="dim")
    return text


class CallInput(Input):
    BINDINGS = [
        Binding("escape", "screen.focus_table", "List", show=False),
    ]


class CheckinTable(DataTable):
    BINDINGS = [
        Binding("t", "screen.toggle_flag('has_traffic')", "Traffic"),
        Binding("c", "screen.toggle_flag('recognized')", "Recognized"),
        Binding("r", "screen.toggle_flag('ragchew')", "Ragchew"),
        Binding("s", "screen.toggle_flag('short_time')", "Short"),
        Binding("m", "screen.toggle_flag('mobile')", "Mobile", show=False),
        Binding("p", "screen.toggle_flag('portable')", "Portable", show=False),
        Binding("enter", "screen.edit_note", "Note"),
        Binding("o", "screen.edit_operator_notes", "Op notes"),
        Binding("e", "screen.toggle_flag('echolink')", "EchoLink", show=False),
        Binding("E", "screen.edit_operator", "Edit op", show=False),
        Binding("l", "screen.relookup", "Lookup", show=False),
        Binding("v", "screen.set_relay", "Via", show=False),
        Binding("delete", "screen.delete_checkin", "Remove", show=False),
        Binding("shift+up", "screen.move(-1)", "Move up", show=False),
        Binding("shift+down", "screen.move(1)", "Move down", show=False),
        Binding("escape", "screen.focus_entry", "Entry", show=False),
    ]
    BOUND_CHARS = set("tcrsmpoelv")
    compact = False

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.zebra_stripes = True
        self.build_columns()

    def build_columns(self) -> None:
        self.add_column("#", key="seq", width=3)
        self.add_column(fmt.zone_label(), key="time", width=5)
        self.add_column("Call", key="call", width=10)
        self.add_column("Name", key="name", width=12)
        if not self.compact:
            self.add_column("Location", key="location", width=18)
        self.add_column("Flags", key="flags", width=10)
        self.add_column("Nets", key="nth", width=4)
        self.add_column("Last", key="last", width=6)

    def on_key(self, event: events.Key) -> None:
        # Typing a callsign character while the list is focused jumps to the entry box.
        char = event.character
        if char and (char.isalnum() or char == "/") and char.lower() not in self.BOUND_CHARS:
            event.stop()
            event.prevent_default()
            entry = self.screen.query_one(CallInput)
            entry.focus()
            entry.insert_text_at_cursor(char)

    def load(self, rows: list[CheckInRow], select_id: int | None = None) -> None:
        current = self.selected_id()
        existing = [key.value for key in self.rows]
        incoming = [str(row.checkin.id) for row in rows]
        # Appending a check-in or enriching a profile need not rebuild every row.
        if existing != incoming[:len(existing)]:
            self.clear()
        self.columns["time"].label = Text(fmt.zone_label())
        for row in rows:
            ci, op = row.checkin, row.operator
            if row.is_new:
                last = Text("NEW★", style="bold black on yellow")
            else:
                last = Text(fmt.ago(row.prev_seen))
            cells = (
                Text(str(ci.seq), justify="right"),
                fmt.hhmm(ci.time_utc),
                Text(ci.logged_as, style="bold"),
                op.display_name,
                *([] if self.compact else [op.location]),
                flag_cell(row),
                Text(str(row.nth), justify="right"),
                last,
            )
            key = str(ci.id)
            if key in self.rows:
                for column, value in zip(self.columns, cells):
                    if self.get_cell(key, column) != value:
                        self.update_cell(key, column, value)
            else:
                self.add_row(*cells, key=key)
        target = select_id if select_id is not None else current
        if target is not None:
            self.select_id(target)

    def selected_id(self) -> int | None:
        if self.row_count == 0:
            return None
        try:
            key = self.coordinate_to_cell_key(self.cursor_coordinate).row_key
        except Exception:
            return None
        return int(key.value) if key.value is not None else None

    def select_id(self, checkin_id: int) -> None:
        try:
            index = self.get_row_index(str(checkin_id))
        except Exception:
            return
        self.move_cursor(row=index, animate=False)
