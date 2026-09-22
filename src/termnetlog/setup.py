"""Configuration editing and read-only local diagnostics."""
from __future__ import annotations

import asyncio
import getpass
import os
import sqlite3
import warnings
from contextlib import closing
from pathlib import Path

import tomlkit
from platformdirs import user_data_path

from termnetlog import __version__, callsign, config, db
from termnetlog.export_files import atomic_write_text
from termnetlog.lookup.service import LookupService
from termnetlog.repo import Repo

SETTINGS = {
    'my_callsign': str,
    **{f'net.{key}': str for key in ('name', 'frequency', 'band', 'mode', 'role', 'ncs_callsign', 'notes')},
    'display.local_tz': str, 'display.local_time': bool,
    'lookup.offline': bool, 'lookup.hamdb': bool, 'lookup.cache_days': int,
}


def edit(path: Path, changes: list[list[str]], qrz: bool = False, template: str | None = None) -> None:
    try:
        original = path.read_text(encoding='utf-8') if path.exists() else config.DEFAULT_CONFIG
        document = tomlkit.parse(original)
    except (ValueError, UnicodeError):
        raise config.ConfigError('Invalid TOML or UTF-8; repair the configuration before editing.') from None
    target = document
    if template is not None:
        if not template.strip() or qrz or any(not key.startswith('net.') for key, _ in changes):
            raise config.ConfigError('Templates require a nonblank name and only net.* settings')
        if 'templates' not in document:
            document['templates'] = tomlkit.table()
        if not isinstance(document['templates'], dict):
            raise config.ConfigError('templates: expected a TOML table')
        if template not in document['templates']:
            from dataclasses import asdict
            document['templates'][template] = asdict(config._from_data(document.unwrap()).net)
        if not isinstance(document['templates'][template], dict):
            raise config.ConfigError('templates: expected a table of net defaults')
        target = {'net': document['templates'][template]}
    for key, raw in changes:
        kind = SETTINGS.get(key)
        if kind is None:
            raise config.ConfigError('Unknown setting; run termnetlog config for supported settings.')
        value = raw
        if kind is bool:
            if raw not in ('true', 'false'):
                raise config.ConfigError(f'{key}: expected true or false')
            value = raw == 'true'
        elif kind is int:
            try:
                value = int(raw)
            except ValueError:
                raise config.ConfigError(f'{key}: expected an integer') from None
        if key in ('my_callsign', 'net.ncs_callsign') and value and callsign.parse(value) is None:
            raise config.ConfigError(f'{key}: expected a callsign or an empty string')
        if '.' in key:
            section, field = key.split('.')
            if section not in target:
                target[section] = tomlkit.table()
            if not isinstance(target[section], dict):
                raise config.ConfigError(f'{section}: expected a TOML table')
            target[section][field] = value
        else:
            target[key] = value
    if qrz:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                username = getpass.getpass('QRZ username (hidden): ')
                password = getpass.getpass('QRZ password (hidden; blank clears): ')
        except (getpass.GetPassWarning, EOFError):
            raise config.ConfigError('Cannot read hidden credentials; use QRZ_USER/QRZ_PASS instead.') from None
        if 'qrz' not in document:
            document['qrz'] = tomlkit.table()
        if not isinstance(document['qrz'], dict):
            raise config.ConfigError('qrz: expected a TOML table')
        document['qrz']['username'] = username
        document['qrz']['password'] = password
    # Validate file values independently of environmental credential overrides.
    data = document.unwrap()
    for field in ('username', 'password'):
        section = data.get('qrz', {})
        if not isinstance(section, dict) or not isinstance(section.get(field, ''), str):
            raise config.ConfigError('qrz: credentials must be quoted strings')
    config._from_data(data)
    serialized = tomlkit.dumps(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, serialized, encoding='utf-8')


def doctor(path: Path, database: Path) -> int:
    print(f'termnetlog: {__version__}')
    print(f'Configuration: {path}')
    print(f'Database: {database}')
    print(f'Backups: {database.parent / "backups"}')
    print(f'Exports: {user_data_path(config.APP) / "exports"}')
    status = 0
    try:
        cfg = config.load(path, create=False)
        print('Config: valid' if path.exists() else 'Config: missing (defaults; run termnetlog config --init)')
        print('Station callsign: configured' if cfg.my_callsign else 'Station callsign: unset')
        print('Display timezone: valid')
        print(f'Offline: {"yes" if cfg.offline else "no"}')
        print(f'HamDB: {"disabled" if cfg.offline or not cfg.hamdb else "enabled (not tested)"}')
        credentials = bool(cfg.qrz_username and cfg.qrz_password)
        partial = bool(cfg.qrz_username) != bool(cfg.qrz_password)
        print('QRZ: ' + ('disabled (offline)' if cfg.offline else 'configured (not tested)' if credentials else 'incomplete credentials' if partial else 'not configured'))
        if partial and not cfg.offline:
            status = 1
        if 'QRZ_USER' in os.environ or 'QRZ_PASS' in os.environ:
            print('QRZ environment overrides: present (values hidden)')
    except config.ConfigError as error:
        print(f'Config: {error}')
        status = 1
    if not database.exists():
        print('Database: not created yet')
        return status
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as conn:
            version = conn.execute('PRAGMA user_version').fetchone()[0]
            print(f'Schema: {version} (supported: {len(db.MIGRATIONS)})')
            from termnetlog.backup import validate
            validate(conn)
            print('Database integrity and schema: OK')
            if version < len(db.MIGRATIONS):
                print('Upgrade pending: back up before opening with this version')
    except (sqlite3.Error, ValueError):
        print('Database: validation failed; use a compatible version or restore a known-good backup to a fresh path')
        status = 1
    return status


async def test_providers(cfg: config.Config, call: str) -> int:
    """Explicit network probe; transient database, no writes to the user's log."""
    parsed = callsign.parse(call)
    if parsed is None:
        raise config.ConfigError('Provider test requires a valid callsign')
    with closing(db.connect(':memory:')) as conn:
        service = LookupService.from_config(Repo(conn), cfg)
        failed = False
        try:
            if not service.providers:
                print('Provider test skipped: offline mode or no providers configured')
                return 1
            for provider in service.providers:
                try:
                    result = await asyncio.wait_for(provider.lookup(parsed.base), timeout=30)
                    print(f'{provider.name}: ' + ('response received' if result else 'not found (request succeeded)'))
                except Exception:
                    print(f'{provider.name}: request failed; check credentials, subscription, and network')
                    failed = True
        finally:
            await service.aclose()
        return int(failed)
