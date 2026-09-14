from __future__ import annotations

from rich.console import Group
from rich.rule import Rule
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from termnetlog.export import flag_words
from termnetlog.models import CheckIn, CheckInRow, Net
from termnetlog.repo import OperatorSummary
from termnetlog.tui import format as fmt


class OperatorCard(VerticalScroll):
    """Lookup data, history and notes for one operator."""

    def compose(self):
        yield Static(Text("No operator selected", style="dim"), id="card-body")

    def clear(self) -> None:
        self.query_one("#card-body", Static).update(Text("No operator selected", style="dim"))

    def show(
        self,
        summary: OperatorSummary,
        history: list[tuple[CheckIn, Net]],
        row: CheckInRow | None = None,
        lookup_pending: bool = False,
    ) -> None:
        op = summary.operator
        parts: list = []

        title = Text()
        title.append(op.callsign, style="bold cyan")
        if row and row.checkin.logged_as != op.callsign:
            title.append(f"  (as {row.checkin.logged_as})", style="dim")
        if row and row.is_new:
            title.append("  ★ FIRST CHECK-IN", style="bold black on yellow")
        parts.append(title)

        if op.full_name:
            name = Text(op.full_name, style="bold")
            if op.nickname:
                name.append(f'  "{op.nickname}"', style="italic")
            parts.append(name)
        loc = op.location
        if op.county:
            loc += f" · {op.county} Co."
        if loc:
            parts.append(Text(loc))
        extra = " · ".join(p for p in (op.country if op.state else None, op.grid, op.license_class) if p)
        if extra:
            parts.append(Text(extra))
        if lookup_pending:
            parts.append(Text("looking up…", style="italic yellow"))
        elif op.lookup_source == "none":
            parts.append(Text("not found in QRZ/HamDB", style="italic red"))
        elif op.lookup_source:
            parts.append(Text(f"source: {op.lookup_source} {fmt.date(op.lookup_at)}", style="dim"))
        elif not op.full_name:
            parts.append(Text("no lookup data", style="dim"))

        parts.append(Rule(style="dim"))
        count = summary.checkin_count
        stats = Text()
        stats.append(f"{count} check-in{'s' if count != 1 else ''}", style="bold")
        if summary.first_seen:
            stats.append(f" · first {fmt.date(summary.first_seen)}")
        if row and row.prev_seen:
            stats.append(f" · prev {fmt.ago(row.prev_seen)} ago")
        elif not row and summary.last_seen:
            stats.append(f" · last {fmt.ago(summary.last_seen)}")
        parts.append(stats)

        parts.append(Text("Operator notes (o):", style="bold magenta"))
        parts.append(Text(op.operator_notes or "—", style="" if op.operator_notes else "dim"))

        if row:
            parts.append(Rule("this check-in", style="dim"))
            ci = row.checkin
            line = Text(f"#{ci.seq} at {fmt.hhmm(ci.time_utc)}{fmt.zone(ci.time_utc)}")
            words = flag_words(row)
            if words:
                line.append(" · " + ", ".join(words), style="green")
            parts.append(line)
            parts.append(Text("Note (enter):", style="bold magenta"))
            parts.append(Text(ci.notes or "—", style="" if ci.notes else "dim"))

        past = [(c, n) for c, n in history if not row or c.id != row.checkin.id]
        if past:
            parts.append(Rule("history", style="dim"))
            for c, n in past[:15]:
                h = Text()
                h.append(fmt.date(c.time_utc), style="cyan")
                h.append(f" {n.name}")
                if c.ragchew:
                    h.append(" ☕", style="yellow")
                if c.notes:
                    h.append(f" — {c.notes}", style="italic")
                parts.append(h)
            if len(past) > 15:
                parts.append(Text(f"… {len(past) - 15} more", style="dim"))

        self.query_one("#card-body", Static).update(Group(*parts))
