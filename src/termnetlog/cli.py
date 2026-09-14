from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from termnetlog import __version__, callsign, config as config_mod, db, export
from termnetlog.lookup.service import LookupService
from termnetlog.models import from_iso
from termnetlog.repo import Repo


def _open(cfg: config_mod.Config) -> Repo:
    return Repo(db.connect(cfg.db_path))


def cmd_run(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    from termnetlog.tui.app import NetLogApp

    NetLogApp(cfg, _open(cfg)).run()
    return 0


def cmd_lookup(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    parsed = callsign.parse(args.callsign)
    if parsed is None:
        print(f"not a callsign: {args.callsign}", file=sys.stderr)
        return 2
    repo = _open(cfg)
    service = LookupService.from_config(repo, cfg)
    if not service.providers:
        print("no lookup providers configured", file=sys.stderr)

    async def go():
        try:
            return await service.resolve(parsed.base, force=True)
        finally:
            await service.aclose()

    outcome = asyncio.run(go())
    for err in outcome.errors:
        print(f"warning: {err}", file=sys.stderr)
    op = outcome.operator
    if not outcome.found:
        print(f"{parsed.base}: not found")
        return 1
    rows = [
        ("Call", op.callsign),
        ("Name", op.full_name),
        ("Location", op.location),
        ("County", op.county),
        ("Country", op.country),
        ("Grid", op.grid),
        ("Class", op.license_class),
        ("Source", op.lookup_source),
    ]
    for label, value in rows:
        if value:
            print(f"{label:>9}: {value}")
    return 0


def cmd_nets(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    repo = _open(cfg)
    for net, count in repo.list_nets(limit=args.limit):
        started = from_iso(net.started_utc)
        status = "open" if net.is_open else ""
        print(f"{net.id:>5}  {started:%Y-%m-%d %H:%MZ}  {count:>3} check-ins  {net.name}  {status}".rstrip())
    return 0


def cmd_export(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    repo = _open(cfg)
    net = repo.get_net(args.net_id)
    if net is None:
        print(f"no net with id {args.net_id}", file=sys.stderr)
        return 1
    rows = repo.list_checkins(net.id)
    if args.format == "adif":
        out = export.to_adif(net, rows, cfg.my_callsign)
    else:
        out = export.to_text(net, rows)
    if args.output:
        Path(args.output).write_text(out)
        print(f"wrote {args.output}")
    else:
        sys.stdout.write(out)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="termnetlog", description="Terminal net logger")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--db", help="database path (default: $TERMNETLOG_DB or XDG data dir)")
    parser.add_argument("--config", help="config path (default: $TERMNETLOG_CONFIG or XDG config dir)")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="start the TUI (default)")

    p = sub.add_parser("lookup", help="look up a callsign and cache it")
    p.add_argument("callsign")

    p = sub.add_parser("nets", help="list logged nets")
    p.add_argument("-n", "--limit", type=int, default=50)

    p = sub.add_parser("export", help="export a net")
    p.add_argument("net_id", type=int)
    p.add_argument("-f", "--format", choices=["adif", "text"], default="text")
    p.add_argument("-o", "--output", help="write to file instead of stdout")

    args = parser.parse_args(argv)
    cfg = config_mod.load(Path(args.config) if args.config else None)
    if args.db:
        cfg.db_path = Path(args.db)

    handlers = {None: cmd_run, "run": cmd_run, "lookup": cmd_lookup, "nets": cmd_nets, "export": cmd_export}
    return handlers[args.command](cfg, args)
