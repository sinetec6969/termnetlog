from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from pathlib import Path

from termnetlog import __version__, callsign, config as config_mod, db, export, export_files
from termnetlog.lookup.service import LookupService
from termnetlog.models import from_iso
from termnetlog.repo import Repo
from termnetlog import backup as recovery


def _open(cfg: config_mod.Config) -> Repo:
    return Repo(db.connect(cfg.db_path))


def cmd_run(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    from termnetlog.tui.app import NetLogApp

    repo = _open(cfg)
    try:
        NetLogApp(cfg, repo).run()
        return 0
    finally:
        repo.conn.close()


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

    try:
        outcome = asyncio.run(go())
    finally:
        repo.conn.close()
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
    try:
        for net, count in repo.list_nets(limit=args.limit):
            started = from_iso(net.started_utc)
            status = "open" if net.is_open else ""
            print(f"{net.id:>5}  {started:%Y-%m-%d %H:%MZ}  {count:>3} check-ins  {net.name}  {status}".rstrip())
        return 0
    finally:
        repo.conn.close()


def cmd_export(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    repo = _open(cfg)
    warnings: list[str] = []
    try:
        net = repo.get_net(args.net_id)
        if net is None:
            print(f"no net with id {args.net_id}", file=sys.stderr)
            return 1
        rows = repo.list_checkins(net.id)
        if args.format == "adif":
            out = export.to_adif(net, rows, cfg.my_callsign, warnings=warnings)
        else:
            out = export.to_text(net, rows)
        if args.output:
            export_files.atomic_write_text(Path(args.output), out,
                                           encoding='ascii' if args.format == 'adif' else 'utf-8')
            print(f"wrote {args.output}")
        else:
            sys.stdout.write(out)
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        return 0
    except (OSError, ValueError) as error:
        print(f"export failed: {error}", file=sys.stderr)
        return 1
    finally:
        repo.conn.close()


def cmd_backup(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    path = recovery.backup(cfg.db_path, Path(args.directory) if args.directory else cfg.db_path.parent / 'backups')
    print(f'Backup saved: {path}')
    return 0


def cmd_restore(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    safety = recovery.restore(Path(args.snapshot), cfg.db_path, replace=args.replace)
    if safety:
        print(f'Previous database saved: {safety}')
    print(f'Restored: {cfg.db_path}')
    return 0


def cmd_config(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    from termnetlog import setup
    path = Path(args.config) if args.config else config_mod.config_path()
    if args.qrz and not sys.stdin.isatty():
        raise config_mod.ConfigError('--qrz requires an interactive terminal; use QRZ_USER/QRZ_PASS otherwise')
    if args.set or args.qrz or args.template is not None:
        setup.edit(path, args.set or [], args.qrz, args.template)
        print(f'Configuration saved: {path}')
    elif args.init:
        config_mod.ensure_config_file(path)
        config_mod.load(path, create=False)
        print(f'Configuration ready: {path}')
    else:
        print(f'Configuration: {path}')
        print('Create defaults: termnetlog config --init')
        print('Set values: termnetlog config --set my_callsign W1AW --set lookup.offline true')
        print('QRZ credentials: termnetlog config --qrz (hidden prompts), or QRZ_USER/QRZ_PASS')
        print('Settings: ' + ', '.join(setup.SETTINGS))
    return 0


def cmd_doctor(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    from termnetlog import setup
    path = Path(args.config) if args.config else config_mod.config_path()
    status = setup.doctor(path, cfg.db_path)
    if args.test_lookup:
        checked = config_mod.load(path, create=False)
        status = max(status, asyncio.run(setup.test_providers(checked, args.test_lookup)))
    return status


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

    p = sub.add_parser('backup', help='save a validated SQLite snapshot without credentials')
    p.add_argument('--directory', help='snapshot parent directory (default: backups beside database)')
    p = sub.add_parser('restore', help='restore a snapshot; close other termnetlog processes first')
    p.add_argument('snapshot', help='snapshot directory or SQLite database file')
    p.add_argument('--replace', action='store_true', help='back up and replace an existing database')

    p = sub.add_parser('config', help='create or safely edit configuration')
    p.add_argument('--init', action='store_true', help='create defaults without overwriting existing configuration')
    p.add_argument('--set', nargs=2, action='append', metavar=('SETTING', 'VALUE'), help='set a non-secret value; repeat for multiple settings')
    p.add_argument('--qrz', action='store_true', help='enter QRZ credentials using hidden terminal prompts')
    p.add_argument('--template', metavar='NAME', help='create/edit a named preset using only net.* settings')
    p = sub.add_parser('doctor', help='inspect configuration and database without migration or network requests')
    p.add_argument('--test-lookup', metavar='CALL', help='explicitly contact each configured provider; does not update your logs')

    args = parser.parse_args(argv)
    handlers = {None: cmd_run, "run": cmd_run, "lookup": cmd_lookup, "nets": cmd_nets, "export": cmd_export,
                'backup': cmd_backup, 'restore': cmd_restore, 'config': cmd_config, 'doctor': cmd_doctor}
    try:
        # Recovery must work even when ordinary configuration is broken.
        cfg = config_mod.Config() if args.command in ('backup', 'restore', 'config', 'doctor') else config_mod.load(Path(args.config) if args.config else None)
        if args.db:
            cfg.db_path = Path(args.db)
        return handlers[args.command](cfg, args)
    except recovery.BackupError as error:
        print(f'recovery failed: {error}', file=sys.stderr)
        return 1
    except config_mod.ConfigError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 2
    except db.SchemaVersionError as error:
        print(str(error), file=sys.stderr)
        return 1
    except sqlite3.Error as error:
        print(f"database error: {error}. Check the database path, permissions, disk space, and other writers.", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"file access error: {error}. Check the path, permissions, and available disk space.", file=sys.stderr)
        return 1
