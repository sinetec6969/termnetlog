from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Static, Input

from termnetlog.tui import format as fmt
from termnetlog.tui.widgets.modals import ConfirmModal

if TYPE_CHECKING:
    from termnetlog.tui.app import NetLogApp


class HistoryScreen(Screen):
    app: NetLogApp

    BINDINGS = [
        Binding("ctrl+n", "page(1)", "Next page", priority=True),
        Binding("ctrl+p", "page(-1)", "Previous page", priority=True),
        Binding("slash", "search", "Search"),
        Binding("enter", "open", "Open"),
        Binding("x", "export", "Export"),
        Binding("delete", "delete", "Delete"),
        Binding("escape,ctrl+b", "app.pop_screen", "Back"),
    ]

    PAGE_SIZE = 50

    def __init__(self):
        super().__init__()
        self.page = 0
        self.search = ""
        self.total = 0

    def compose(self) -> ComposeResult:
        yield Static(Text(" Past nets ", style="bold reverse"), id="net-header")
        yield Input(placeholder="Search net name or UTC date (YYYY-MM-DD)", id="history-search")
        yield Static(id="history-page")
        yield DataTable(id="nets", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        for label in ("ID", "Date", "Time", "Length", "Net", "Freq", "NCS", "Role", "Check-ins", ""):
            table.add_column(label, key=label)
        self.reload()
        table.focus()

    def on_screen_resume(self) -> None:
        self.reload()

    def reload(self) -> None:
        table = self.query_one(DataTable)
        selected = self.selected_net_id()
        current = table.cursor_row
        self.total = self.app.repo.count_nets(self.search)
        self.page = min(self.page, max(0, (self.total - 1) // self.PAGE_SIZE))
        table.clear()
        table.columns["Time"].label = Text(fmt.zone_label())
        records = self.app.repo.list_nets(limit=self.PAGE_SIZE, offset=self.page * self.PAGE_SIZE, search=self.search)
        for net, count in records:
            table.add_row(
                Text(str(net.id), justify="right"),
                fmt.date(net.started_utc),
                fmt.hhmm(net.started_utc),
                fmt.elapsed(net.started_utc, net.ended_utc) if net.ended_utc else "",
                Text(net.name, style="bold"),
                net.frequency,
                net.ncs_callsign,
                "NCS" if net.is_ncs else "",
                Text(str(count), justify="right"),
                Text("open", style="green") if net.is_open else "",
                key=str(net.id),
            )
        if table.row_count:
            index = next((i for i, (net, _) in enumerate(records) if net.id == selected), min(current, table.row_count - 1))
            table.move_cursor(row=index, animate=False)
        start = self.page * self.PAGE_SIZE + 1 if self.total else 0
        end = self.page * self.PAGE_SIZE + len(records)
        self.query_one('#history-page', Static).update(
            f" {start}–{end} of {self.total} nets · Page {self.page + 1}/{max(1, (self.total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)}"
            if self.total else " No matching nets" if self.search else " No nets yet"
        )

    def action_page(self, delta: int) -> None:
        page = max(0, min(self.page + delta, max(0, (self.total - 1) // self.PAGE_SIZE)))
        if page != self.page:
            self.page = page
            self.query_one(DataTable).move_cursor(row=0, animate=False)
            self.reload()

    def action_search(self) -> None:
        self.query_one(Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.search = event.value.strip()
        self.page = 0
        self.reload()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.query_one(DataTable).focus()

    def selected_net_id(self) -> int | None:
        table = self.query_one(DataTable)
        if not table.row_count:
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        return int(key.value) if key.value else None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_open()

    def action_open(self) -> None:
        net_id = self.selected_net_id()
        if net_id is not None:
            self.app.open_net(net_id)

    def action_export(self) -> None:
        net_id = self.selected_net_id()
        net = self.app.repo.get_net(net_id) if net_id is not None else None
        if net is None:
            return
        rows = self.app.repo.list_checkins(net.id)
        self.app.export_net(net, rows)

    def action_delete(self) -> None:
        net_id = self.selected_net_id()
        net = self.app.repo.get_net(net_id) if net_id is not None else None
        if net is None:
            return

        def done(yes: bool | None) -> None:
            if yes:
                self.app.repo.delete_net(net.id)
                self.app.removed_checkins.pop(net.id, None)
                self.reload()

        self.app.push_screen(
            ConfirmModal(f"Delete net #{net.id} {net.name} ({fmt.date(net.started_utc)}) and all its check-ins?"),
            done,
        )
