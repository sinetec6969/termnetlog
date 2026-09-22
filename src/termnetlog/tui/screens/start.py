from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Footer, OptionList, Static
from textual.widgets.option_list import Option

from termnetlog.tui import format as fmt
from termnetlog.tui.widgets.modals import NewNetModal

if TYPE_CHECKING:
    from termnetlog.tui.app import NetLogApp

BANNER = "📻  t e r m n e t l o g"
TAGLINE = "net logging for the nightly net"


class StartScreen(Screen):
    app: NetLogApp

    BINDINGS = [
        Binding("n", "new_net", "New net"),
        Binding("h", "history", "Past nets"),
        Binding("o", "operators", "Operators"),
        Binding("q", "app.quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical(id="start-box"):
                yield Static(Text(BANNER, style="bold cyan", justify="center"), id="banner")
                yield Static(Text(TAGLINE, style="dim", justify="center"))
                yield Static(id="start-status")
                yield OptionList(id="start-menu")
        yield Footer()

    def on_mount(self) -> None:
        self.rebuild()

    def on_screen_resume(self) -> None:
        self.rebuild()

    def rebuild(self) -> None:
        repo = self.app.repo
        menu = self.query_one(OptionList)
        menu.clear_options()
        for net in repo.open_nets():
            count = len(repo.list_checkins(net.id))
            label = Text()
            label.append("▶ Resume ", style="bold green")
            label.append(f"{net.name} — started {fmt.date(net.started_utc)} {fmt.hhmm(net.started_utc)}{fmt.zone(net.started_utc)}, {count} check-ins")
            menu.add_option(Option(label, id=f"resume:{net.id}"))
        menu.add_option(Option(Text("＋ New net  (n)", style="bold"), id="new"))
        for name in self.app.config.templates:
            menu.add_option(Option(Text(f'＋ Template: {name}'), id=f'template:{name}'))
        menu.add_option(Option("📜 Past nets  (h)", id="history"))
        menu.add_option(Option("👥 Operators  (o)", id="operators"))
        menu.add_option(Option("⏻ Quit  (q)", id="quit"))
        menu.highlighted = 0
        menu.focus()

        cfg = self.app.config
        nets, ops = repo.counts()
        status = Text(justify="center")
        status.append(f"{cfg.my_callsign or 'run termnetlog config to set up'}", style="bold")
        status.append(f"  ·  {nets} nets  ·  {ops} operators  ·  lookups: ")
        status.append("offline" if cfg.offline else ", ".join(p.name for p in self.app.lookup.providers) or "none", style="cyan")
        self.query_one("#start-status", Static).update(status)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        oid = event.option.id or ""
        if oid.startswith("resume:"):
            self.app.open_net(int(oid.split(":", 1)[1]))
        elif oid == "new":
            self.action_new_net()
        elif oid.startswith('template:'):
            self.start_with_defaults(self.app.config.templates[oid[len('template:'):]])
        elif oid == "history":
            self.action_history()
        elif oid == "operators":
            self.action_operators()
        elif oid == "quit":
            self.app.exit()

    def action_new_net(self) -> None:
        self.start_with_defaults(self.app.config.net)

    def start_with_defaults(self, defaults) -> None:
        def done(values: dict | None) -> None:
            if values:
                net = self.app.repo.create_net(**values)
                self.app.open_net(net.id)

        self.app.push_screen(NewNetModal(defaults), done)

    def action_history(self) -> None:
        from termnetlog.tui.screens.history import HistoryScreen

        self.app.push_screen(HistoryScreen())

    def action_operators(self) -> None:
        from termnetlog.tui.screens.operators import OperatorsScreen

        self.app.push_screen(OperatorsScreen())
