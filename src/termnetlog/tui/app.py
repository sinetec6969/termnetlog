from __future__ import annotations

import re
from pathlib import Path

from platformdirs import user_data_path
from textual.app import App

from termnetlog import export
from termnetlog.config import APP, Config
from termnetlog.lookup.service import LookupService
from termnetlog.models import CheckInRow, Net, from_iso
from termnetlog.repo import Repo
from termnetlog.tui.screens.net import NetScreen
from termnetlog.tui.screens.start import StartScreen


class NetLogApp(App):
    TITLE = "termnetlog"
    CSS_PATH = "app.tcss"

    def __init__(self, config: Config, repo: Repo, lookup: LookupService | None = None, export_dir: Path | None = None):
        super().__init__()
        self.config = config
        self.repo = repo
        self.lookup = lookup or LookupService.from_config(repo, config)
        self.export_dir = export_dir or user_data_path(APP) / "exports"
        self._reported_errors: set[str] = set()

    def on_mount(self) -> None:
        self.push_screen(StartScreen())

    async def on_unmount(self) -> None:
        await self.lookup.aclose()

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

    def write_exports(self, net: Net, rows: list[CheckInRow]) -> list[Path]:
        self.export_dir.mkdir(parents=True, exist_ok=True)
        started = from_iso(net.started_utc)
        slug = re.sub(r"[^a-z0-9]+", "-", net.name.lower()).strip("-") or "net"
        base = self.export_dir / f"{started:%Y%m%d-%H%M}-{slug}"
        txt = base.with_suffix(".txt")
        adi = base.with_suffix(".adi")
        txt.write_text(export.to_text(net, rows))
        adi.write_text(export.to_adif(net, rows, self.config.my_callsign))
        return [txt, adi]
