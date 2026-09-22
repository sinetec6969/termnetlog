from __future__ import annotations

import re
import sqlite3
from typing import TYPE_CHECKING

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.suggester import Suggester
from textual.widgets import DataTable, Footer, Input, Label, Static
from textual.worker import Worker

from termnetlog import callsign, entry as entry_mod
from termnetlog.config import NetDefaults
from termnetlog.models import CheckInRow, Net, utcnow
from termnetlog.repo import DuplicateCheckIn, Repo
from termnetlog.tui import format as fmt
from termnetlog.tui.widgets.checkin_table import CallInput, CheckinTable
from termnetlog.tui.widgets.modals import ConfirmModal, HelpModal, InputModal, NoteModal, OperatorEditModal, NewNetModal
from termnetlog.tui.widgets.operator_card import OperatorCard

if TYPE_CHECKING:
    from termnetlog.tui.app import NetLogApp


class CallSuggester(Suggester):
    def __init__(self, repo: Repo):
        super().__init__(use_cache=False, case_sensitive=False)
        self.repo = repo

    async def get_suggestion(self, value: str) -> str | None:
        if not value or " " in value:
            return None
        matches = self.repo.suggest_callsigns(value.upper(), limit=1)
        return matches[0].operator.callsign if matches else None


class NetScreen(Screen):
    app: NetLogApp

    BINDINGS = [
        Binding("up", "cursor(-1)", "Up", show=False),
        Binding("down", "cursor(1)", "Down", show=False),
        # priority: the call entry Input binds ctrl+e (end) and ctrl+x (cut) itself.
        Binding("ctrl+e", "export", "Export", priority=True),
        Binding("ctrl+g", "edit_net_notes", "Net notes", priority=True),
        Binding("ctrl+x", "end_net", "End net", priority=True),
        Binding("ctrl+b", "back", "Menu", priority=True),
        Binding("f1", "help", "Help", priority=True),
        Binding("f2", "toggle_card", "Operator card", priority=True),
        Binding("f3", "correct_call", "Correct call", priority=True),
        Binding("ctrl+d", "edit_metadata", "Net details", priority=True),
        Binding("ctrl+o", "reopen", "Reopen", priority=True),
        Binding("ctrl+z", "undo_remove", "Undo removal", priority=True),
    ]

    def __init__(self, net_id: int):
        super().__init__()
        self.net_id = net_id
        self.rows: list[CheckInRow] = []
        self.pending: set[str] = set()
        self.preview_call: str | None = None
        self.card_requested = False

    @property
    def repo(self) -> Repo:
        return self.app.repo

    @property
    def net(self) -> Net:
        net = self.repo.get_net(self.net_id)
        assert net is not None
        return net

    # ---- layout ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(id="net-header")
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield CheckinTable(id="checkins")
                yield Static(id="ragchew")
            yield OperatorCard(id="card")
        with Horizontal(id="entry-bar"):
            yield Label("Call ›", id="entry-label")
            yield CallInput(
                placeholder="callsign [t s r c m p] [via RELAY] [note]   (f1 help)",
                suggester=CallSuggester(self.repo),
                id="call-input",
            )
        yield Static(id="suggest")
        yield Footer()

    def on_mount(self) -> None:
        self.update_layout()
        self.refresh_all()
        self.set_interval(1, self.update_header)
        self.query_one(CallInput).focus()
        # Resuming a net: fill in anyone who was logged while offline.
        for row in self.rows:
            if not self.app.lookup.is_fresh(row.operator):
                self.start_lookup(row.operator.callsign)

    def on_screen_resume(self) -> None:
        self.refresh_all()

    def on_resize(self, event: events.Resize) -> None:
        if self.is_mounted:
            self.update_layout()

    def update_layout(self) -> None:
        narrow = self.size.width < 120
        table = self.query_one(CheckinTable)
        selected = table.selected_id()
        if table.compact != narrow:
            table.compact = narrow
            table.clear(columns=True)
            table.build_columns()
            table.load(self.rows, selected)
        self.query_one('#card').display = self.card_requested if narrow else not self.card_requested
        self.query_one('#left').display = not (narrow and self.card_requested)

    def action_toggle_card(self) -> None:
        self.card_requested = not self.card_requested
        self.update_layout()
        if self.size.width < 120 and self.card_requested:
            self.query_one(CallInput).focus()

    # ---- rendering ---------------------------------------------------------

    def refresh_all(self, select_id: int | None = None) -> None:
        self.rows = self.repo.list_checkins(self.net_id)
        self.query_one(CheckinTable).load(self.rows, select_id)
        self.update_header()
        self.update_ragchew()
        self.update_card()

    def update_header(self) -> None:
        net = self.net
        now = utcnow()
        t = Text()
        t.append(f" {net.name} ", style="bold reverse")
        t.append(f"  {net.frequency} {net.mode}")
        if net.ncs_callsign:
            t.append(f"  NCS {net.ncs_callsign}")
        t.append(f"  [{'net control' if net.is_ncs else 'participant'}]", style="dim")
        t.append(f"   {fmt.local(now):%H:%M:%S}{fmt.zone(now)}", style="bold cyan")
        if net.is_open:
            t.append(f"   ⏱ {fmt.elapsed(net.started_utc)}")
        else:
            ended = fmt.local(net.ended_utc)
            t.append(f"   {fmt.date(net.started_utc)} ended {ended:%H:%M}{fmt.zone(ended)} ({fmt.elapsed(net.started_utc, net.ended_utc)})", style="yellow")
        n = len(self.rows)
        t.append(f"   {n} check-in{'s' if n != 1 else ''}", style="bold")
        new = sum(1 for r in self.rows if r.is_new)
        if new:
            t.append(f" · {new} new", style="yellow")
        traffic = sum(1 for r in self.rows if r.checkin.has_traffic)
        if traffic:
            t.append(f" · {traffic} traffic", style="red")
        self.query_one("#net-header", Static).update(t)

    def update_ragchew(self) -> None:
        stayers = [r for r in self.rows if r.checkin.ragchew]
        t = Text("☕ Ragchew", style="bold yellow")
        if stayers:
            t.append(f" ({len(stayers)}): ")
            for i, r in enumerate(stayers):
                if i:
                    t.append(" · ")
                t.append(r.checkin.logged_as, style="bold")
                if r.operator.display_name:
                    t.append(f" {r.operator.display_name}")
        else:
            t.append(": nobody yet — select a check-in and press r", style="dim")
        self.query_one("#ragchew", Static).update(t)

    def selected_row(self) -> CheckInRow | None:
        cid = self.query_one(CheckinTable).selected_id()
        return next((r for r in self.rows if r.checkin.id == cid), None)

    def update_card(self) -> None:
        card = self.query_one(OperatorCard)
        row = None
        call = self.preview_call
        if call is None:
            row = self.selected_row()
            call = row.operator.callsign if row else None
        if call is None:
            card.clear()
            return
        summary = self.repo.operator_summary(call)
        if summary is None:
            card.clear()
            return
        card.show(summary, self.repo.operator_history(call), row, lookup_pending=call in self.pending)

    # ---- events ------------------------------------------------------------

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self.preview_call is None:
            self.update_card()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "call-input":
            return
        first = event.value.split()[0] if event.value.split() else ""
        parsed = callsign.parse(first) if first else None
        prefix = parsed.base if parsed else re.sub(r"[^A-Z0-9]", "", first.upper())
        suggest = self.query_one("#suggest", Static)
        matches = self.repo.suggest_callsigns(prefix, limit=6) if prefix else []
        if matches:
            t = Text(" known: ", style="dim")
            for i, m in enumerate(matches):
                if i:
                    t.append("  ")
                t.append(m.operator.callsign, style="bold")
                if m.operator.display_name:
                    t.append(f" {m.operator.display_name}")
                t.append(f" ({m.checkin_count})", style="dim")
            suggest.update(t)
        else:
            suggest.update("")
        exact = parsed is not None and any(m.operator.callsign == parsed.base for m in matches)
        new_preview = parsed.base if exact and parsed else None
        if new_preview != self.preview_call:
            self.preview_call = new_preview
            self.update_card()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "call-input":
            return
        text = event.value.strip()
        if not text:
            return
        if not self.net.is_open:
            self.notify('Net has ended. Press ctrl+o to reopen before adding check-ins.', severity='warning')
            return
        entry = entry_mod.parse(text)
        if entry is None:
            self.notify(f"Not a callsign: {text.split()[0]}", severity="error")
            return
        table = self.query_one(CheckinTable)
        try:
            ci = self.repo.record_entry(self.net_id, entry)
        except DuplicateCheckIn as e:
            self.notify(str(e), severity="warning")
            event.input.value = ""
            self.preview_call = None
            table.select_id(e.existing.id)
            return
        except (sqlite3.Error, OSError):
            self.notify(
                "Check-in not saved. Check disk space and database access, then press Enter to retry. "
                "Your entry is still in the input box.",
                title="Save failed", severity="error", timeout=10,
            )
            return
        event.input.value = ""
        self.preview_call = None
        self.refresh_all(select_id=ci.id)
        self.start_lookup(ci.callsign)

    # ---- lookups -----------------------------------------------------------

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        self.app.report_lookup_worker_state(event)

    def start_lookup(self, call: str, force: bool = False) -> None:
        if not self.app.lookup.providers:
            return
        if call in self.pending:
            return
        self.pending.add(call)
        self.update_card()
        self.run_worker(self._lookup(call, force), group="lookup", exit_on_error=False)

    async def _lookup(self, call: str, force: bool) -> None:
        try:
            outcome = await self.app.lookup.resolve(call, force=force)
        finally:
            self.pending.discard(call)
        for err in outcome.errors:
            self.app.lookup_error(err)
        if force:
            if outcome.updated:
                self.notify(f"{call}: updated from {outcome.operator.lookup_source}")
            elif not outcome.found and not outcome.errors:
                self.notify(f"{call}: not found", severity="warning")
        if self.is_mounted:
            self.refresh_all()

    # ---- actions -----------------------------------------------------------

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "end_net":
            return self.net.is_open
        if action == 'reopen':
            return not self.net.is_open
        if action == "toggle_flag" and parameters == ("recognized",):
            return self.net.is_ncs
        return True

    def action_cursor(self, delta: int) -> None:
        table = self.query_one(CheckinTable)
        if table.row_count:
            table.move_cursor(row=max(0, min(table.row_count - 1, table.cursor_row + delta)))

    def action_focus_table(self) -> None:
        self.query_one(CheckinTable).focus()

    def action_focus_entry(self) -> None:
        self.query_one(CallInput).focus()

    def _require_row(self) -> CheckInRow | None:
        row = self.selected_row()
        if row is None:
            self.notify("No check-in selected", severity="warning")
        return row

    def action_toggle_flag(self, flag: str) -> None:
        row = self._require_row()
        if row:
            self.repo.toggle_flag(row.checkin.id, flag)
            self.refresh_all(select_id=row.checkin.id)

    def action_edit_note(self) -> None:
        row = self._require_row()
        if not row:
            return

        def done(text: str | None) -> None:
            if text is not None:
                self.repo.set_checkin_notes(row.checkin.id, text)
                self.refresh_all(select_id=row.checkin.id)

        self.app.push_screen(NoteModal(f"Check-in note — {row.checkin.logged_as}", row.checkin.notes), done)

    def action_correct_call(self) -> None:
        row = self._require_row()
        if row is None:
            return

        def entered(value: str | None) -> None:
            if value is None:
                return
            call = callsign.parse(value.strip())
            if call is None:
                self.notify('Enter a valid callsign.', severity='error')
                return
            if any(r.checkin.id != row.checkin.id and r.operator.callsign == call.base for r in self.rows):
                self.notify('That operator is already checked in; no records were changed.', severity='warning')
                return

            def confirmed(yes: bool | None) -> None:
                if not yes:
                    return
                try:
                    self.repo.correct_callsign(row.checkin.id, call)
                except (sqlite3.Error, OSError, ValueError, DuplicateCheckIn):
                    self.notify('Correction failed; reload and retry. No correction was saved.', severity='error')
                    return
                self.refresh_all(select_id=row.checkin.id)
                self.start_lookup(call.base)

            self.app.push_screen(ConfirmModal(
                f'Change {row.checkin.logged_as} to {call.raw} for this check-in only? '
                'Time, order, flags and entry note stay. Operator profiles and private notes stay with their original callsigns.'
            ), confirmed)

        self.app.push_screen(InputModal('Correct selected check-in callsign', row.checkin.logged_as), entered)

    def action_edit_metadata(self) -> None:
        net = self.net
        defaults = NetDefaults(net.name, net.frequency, net.mode, net.band, net.my_role, net.ncs_callsign, net.notes)

        def done(values: dict | None) -> None:
            if values is not None:
                try:
                    self.repo.update_net(net.id, **values)
                except (sqlite3.Error, OSError):
                    self.notify('Net details could not be saved.', severity='error')
                    return
                self.refresh_all()
                self.refresh_bindings()

        self.app.push_screen(NewNetModal(defaults, 'Edit net details', 'Save (ctrl+s)'), done)

    def action_reopen(self) -> None:
        def done(yes: bool | None) -> None:
            if yes:
                try:
                    self.repo.reopen_net(self.net_id)
                except (sqlite3.Error, OSError):
                    self.notify('Net could not be reopened.', severity='error')
                    return
                self.refresh_all()
                self.refresh_bindings()
        self.app.push_screen(ConfirmModal('Reopen this ended net to accept new check-ins?'), done)

    def action_edit_operator_notes(self) -> None:
        row = self._require_row()
        if not row:
            return
        op = row.operator

        def done(text: str | None) -> None:
            if text is not None:
                self.repo.set_operator_notes(op.callsign, text)
                self.refresh_all(select_id=row.checkin.id)

        self.app.push_screen(
            NoteModal(f"Operator notes — {op.callsign} (kept across nets)", op.operator_notes), done
        )

    def action_edit_operator(self) -> None:
        row = self._require_row()
        if not row:
            return

        def done(changed: dict | None) -> None:
            if changed:
                self.repo.update_operator(row.operator.callsign, **changed)
                self.refresh_all(select_id=row.checkin.id)

        self.app.push_screen(OperatorEditModal(row.operator), done)

    def action_relookup(self) -> None:
        row = self._require_row()
        if not row:
            return
        if row.operator.lookup_source == "manual":
            self.notify(f"{row.operator.callsign} was edited by hand; lookup skipped", severity="warning")
            return
        self.start_lookup(row.operator.callsign, force=True)

    def action_set_relay(self) -> None:
        row = self._require_row()
        if not row:
            return

        def done(value: str | None) -> None:
            if value is not None:
                self.repo.set_relayed_by(row.checkin.id, value)
                self.refresh_all(select_id=row.checkin.id)

        self.app.push_screen(
            InputModal(f"{row.checkin.logged_as} relayed via (blank to clear)", row.checkin.relayed_by), done
        )

    def action_delete_checkin(self) -> None:
        row = self._require_row()
        if not row:
            return

        def done(yes: bool | None) -> None:
            if yes:
                try:
                    removed = self.repo.delete_checkin(row.checkin.id)
                except (sqlite3.Error, OSError):
                    self.notify('Removal failed; no entry was removed.', severity='error')
                    return
                if removed is not None:
                    stack = self.app.removed_checkins.setdefault(self.net_id, [])
                    stack.append(removed)
                    del stack[:-50]
                    self.notify('Check-in removed. Ctrl+Z restores it during this application session.')
                self.refresh_all()

        self.app.push_screen(ConfirmModal(f"Remove check-in #{row.checkin.seq} {row.checkin.logged_as}?"), done)

    def action_undo_remove(self) -> None:
        stack = self.app.removed_checkins.get(self.net_id, [])
        if not stack:
            self.notify('No removal to undo in this application session.')
            return
        try:
            restored = self.repo.restore_checkin(stack[-1])
        except DuplicateCheckIn:
            self.notify('Undo blocked: that callsign is already checked in. No records changed.', severity='warning')
            return
        except (sqlite3.Error, OSError):
            self.notify('Undo failed; the removal remains available to retry.', severity='error')
            return
        stack.pop()
        self.refresh_all(select_id=restored.id)
        self.notify(f'Restored {restored.logged_as}.')

    def action_move(self, delta: int) -> None:
        row = self._require_row()
        if row:
            self.repo.move_checkin(row.checkin.id, delta)
            self.refresh_all(select_id=row.checkin.id)

    def action_edit_net_notes(self) -> None:
        net = self.net

        def done(text: str | None) -> None:
            if text is not None:
                self.repo.update_net(net.id, notes=text)

        self.app.push_screen(NoteModal(f"Net notes — {net.name}", net.notes), done)

    def action_end_net(self) -> None:
        def done(yes: bool | None) -> None:
            if yes:
                self.repo.end_net(self.net_id)
                self.refresh_bindings()
                self.update_header()
                self.notify(
                    f"Net ended with {len(self.rows)} check-ins. You can keep editing notes; ctrl+e to export.",
                    timeout=8,
                )

        self.app.push_screen(ConfirmModal("End the net now?"), done)

    def action_export(self) -> None:
        net = self.net
        rows = self.repo.list_checkins(net.id)
        self.app.export_net(net, rows)

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_help(self) -> None:
        self.app.push_screen(HelpModal())
