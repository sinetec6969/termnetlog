from __future__ import annotations

from pathlib import Path

from platformdirs import user_data_path
from textual.app import App
from textual.binding import Binding
from textual.worker import Worker, WorkerState

from termnetlog import export, export_files
from termnetlog.config import APP, Config
from termnetlog.lookup.service import LookupService
from termnetlog.models import CheckInRow, Net
from termnetlog.repo import Repo
from termnetlog.tui.screens.net import NetScreen
from termnetlog.tui import format as fmt
from termnetlog.tui.screens.start import StartScreen


class NetLogApp(App):
    TITLE = "termnetlog"
    CSS_PATH = "app.tcss"
    # priority: works from the call entry box and the check-in list too.
    BINDINGS = [Binding("ctrl+t", "toggle_tz", "UTC/local", priority=True)]

    def __init__(self, config: Config, repo: Repo, lookup: LookupService | None = None, export_dir: Path | None = None):
        super().__init__()
        self.config = config
        self.repo = repo
        self.lookup = lookup or LookupService.from_config(repo, config)
        self.export_dir = export_dir or user_data_path(APP) / "exports"
        self._reported_errors: set[str] = set()
        self.removed_checkins = {}  # per-net, process-local undo stacks
        fmt.set_display_tz(config.local_tz, config.local_time)

    def on_mount(self) -> None:
        self.push_screen(StartScreen())

    async def on_unmount(self) -> None:
        await self.lookup.aclose()

    def report_lookup_worker_state(self, event: Worker.StateChanged) -> None:
        if event.worker.group == "lookup" and event.state == WorkerState.ERROR:
            kind = type(event.worker.error).__name__
            self.lookup_error(f"Lookup could not finish ({kind}); retry or check the database")

    def action_toggle_tz(self) -> None:
        fmt.toggle_local()
        # Screens that show times re-render fully on resume; lower screens catch up when they're resumed.
        if hasattr(self.screen, "on_screen_resume"):
            self.screen.on_screen_resume()
        self.notify(f"Showing times in {fmt.zone_name()}", timeout=2)

    def open_net(self, net_id: int) -> None:
        # Keep the stack shallow: menu -> net.
        while len(self.screen_stack) > 2:
            self.pop_screen()
        self.push_screen(NetScreen(net_id))

    def lookup_error(self, message: str) -> None:
        """Show each distinct lookup error once per session, so a dead network doesn't spam."""
        if message in self._reported_errors:
            return
        self._reported_errors.add(message)
        self.notify(message, title="Lookup failed", severity="warning", timeout=6)

    def write_exports(self, net: Net, rows: list[CheckInRow], *,
                      warnings: list[str] | None = None) -> list[Path]:
        return export_files.write_bundle(self.export_dir, net, rows, self.config.my_callsign, warnings=warnings)

    def export_net(self, net: Net, rows: list[CheckInRow]) -> None:
        warnings: list[str] = []
        try:
            paths = self.write_exports(net, rows, warnings=warnings)
        except (OSError, ValueError) as error:
            self.notify(str(error), title="Export failed", severity="error", timeout=10)
            return
        self.notify("\n".join(str(path) for path in paths), title="Exported", timeout=10)
        for warning in warnings:
            self.notify(warning, title="ADIF text conversion", severity="warning", timeout=10)
        try:
            self.copy_to_clipboard(export.to_text(net, rows))
        except Exception:
            self.notify("Files saved; clipboard copy failed", severity="warning")
