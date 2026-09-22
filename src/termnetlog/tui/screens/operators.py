from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Input, Static
from textual.worker import Worker

from termnetlog.repo import OperatorSummary
from termnetlog.tui import format as fmt
from termnetlog.tui.widgets.modals import NoteModal, OperatorEditModal
from termnetlog.tui.widgets.operator_card import OperatorCard

if TYPE_CHECKING:
    from termnetlog.tui.app import NetLogApp


class OperatorTable(DataTable):
    BINDINGS = [
        Binding("o", "screen.edit_notes", "Op notes"),
        Binding("e,enter", "screen.edit", "Edit"),
        Binding("l", "screen.relookup", "Lookup"),
        Binding("slash", "screen.focus_search", "Search"),
    ]


class OperatorsScreen(Screen):
    app: NetLogApp

    BINDINGS = [
        Binding("escape,ctrl+b", "back", "Back"),
        Binding("down", "focus_table", "List", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.summaries: list[OperatorSummary] = []

    def compose(self) -> ComposeResult:
        yield Static(Text(" Operators ", style="bold reverse"), id="net-header")
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Input(placeholder="search call, name, city or notes…", id="search")
                yield OperatorTable(id="operators", cursor_type="row", zebra_stripes=True)
            yield OperatorCard(id="card")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(OperatorTable)
        table.add_column("Call", key="call", width=10)
        table.add_column("Name", key="name", width=22)
        table.add_column("Location", key="location", width=22)
        table.add_column("Nets", key="count", width=5)
        table.add_column("Last", key="last", width=6)
        table.add_column("Notes", key="notes", width=24)
        self.reload()
        table.focus()

    def on_screen_resume(self) -> None:
        self.reload()

    def reload(self) -> None:
        table = self.query_one(OperatorTable)
        current = self.selected()
        self.summaries = self.app.repo.search_operators(self.query_one("#search", Input).value)
        table.clear()
        for s in self.summaries:
            op = s.operator
            table.add_row(
                Text(op.callsign, style="bold"),
                op.full_name,
                op.location,
                Text(str(s.checkin_count), justify="right"),
                fmt.ago(s.last_seen),
                (op.operator_notes or "").replace("\n", " ")[:60],
                key=op.callsign,
            )
        if current:
            try:
                table.move_cursor(row=table.get_row_index(current.operator.callsign), animate=False)
            except Exception:
                pass
        self.update_card()

    def selected(self) -> OperatorSummary | None:
        table = self.query_one(OperatorTable)
        if not table.row_count:
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return next((s for s in self.summaries if s.operator.callsign == key), None)

    def update_card(self) -> None:
        s = self.selected()
        card = self.query_one(OperatorCard)
        if s is None:
            card.clear()
        else:
            card.show(s, self.app.repo.operator_history(s.operator.callsign))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.update_card()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.reload()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.query_one(OperatorTable).focus()

    def action_focus_table(self) -> None:
        self.query_one(OperatorTable).focus()

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_back(self) -> None:
        search = self.query_one("#search", Input)
        if search.has_focus and search.value:
            search.value = ""
            return
        self.app.pop_screen()

    def action_edit_notes(self) -> None:
        s = self.selected()
        if not s:
            return

        def done(text: str | None) -> None:
            if text is not None:
                self.app.repo.set_operator_notes(s.operator.callsign, text)
                self.reload()

        self.app.push_screen(NoteModal(f"Operator notes — {s.operator.callsign}", s.operator.operator_notes), done)

    def action_edit(self) -> None:
        s = self.selected()
        if not s:
            return

        def done(changed: dict | None) -> None:
            if changed:
                self.app.repo.update_operator(s.operator.callsign, **changed)
                self.reload()

        self.app.push_screen(OperatorEditModal(s.operator), done)

    def action_relookup(self) -> None:
        s = self.selected()
        if not s:
            return
        call = s.operator.callsign
        if s.operator.lookup_source == "manual":
            self.notify(f"{call} was edited by hand; lookup skipped", severity="warning")
            return
        self.run_worker(self._relookup(call), group="lookup", exit_on_error=False)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        self.app.report_lookup_worker_state(event)

    async def _relookup(self, call: str) -> None:
        outcome = await self.app.lookup.resolve(call, force=True)
        for err in outcome.errors:
            self.app.lookup_error(err)
        if outcome.updated:
            self.notify(f"{call}: updated from {outcome.operator.lookup_source}")
        elif not outcome.found and not outcome.errors:
            self.notify(f"{call}: not found", severity="warning")
        if self.is_mounted:
            self.reload()
