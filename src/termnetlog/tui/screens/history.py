from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Static

from termnetlog import export
from termnetlog.tui import format as fmt
from termnetlog.tui.widgets.modals import ConfirmModal

if TYPE_CHECKING:
    from termnetlog.tui.app import NetLogApp


class HistoryScreen(Screen):
    app: NetLogApp

    BINDINGS = [
        Binding("enter", "open", "Open"),
        Binding("x", "export", "Export"),
        Binding("delete", "delete", "Delete"),
        Binding("escape,ctrl+b", "app.pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Static(Text(" Past nets ", style="bold reverse"), id="net-header")
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
        current = table.cursor_row
        table.clear()
        table.columns["Time"].label = Text(fmt.zone_label())
        for net, count in self.app.repo.list_nets():
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
            table.move_cursor(row=min(current, table.row_count - 1), animate=False)

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
        paths = self.app.write_exports(net, rows)
        self.app.copy_to_clipboard(export.to_text(net, rows))
        self.notify("Roster copied to clipboard\n" + "\n".join(str(p) for p in paths), title="Exported", timeout=10)

    def action_delete(self) -> None:
        net_id = self.selected_net_id()
        net = self.app.repo.get_net(net_id) if net_id is not None else None
        if net is None:
            return

        def done(yes: bool | None) -> None:
            if yes:
                self.app.repo.delete_net(net.id)
                self.reload()

        self.app.push_screen(
            ConfirmModal(f"Delete net #{net.id} {net.name} ({fmt.date(net.started_utc)}) and all its check-ins?"),
            done,
        )
