"""Validated SQLite snapshots and explicit recovery, without configuration secrets."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from termnetlog import __version__, db


class BackupError(ValueError):
    pass


def _read(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)


def _copy(source: sqlite3.Connection, destination: sqlite3.Connection) -> None:
    deadline = time.monotonic() + 30

    def progress(status: int, remaining: int, total: int) -> None:
        if time.monotonic() > deadline:
            raise BackupError('Database copy timed out; close other termnetlog processes and retry.')

    source.backup(destination, pages=256, progress=progress, sleep=0.05)


def validate(conn: sqlite3.Connection) -> int:
    version = conn.execute('PRAGMA user_version').fetchone()[0]
    if not 1 <= version <= len(db.MIGRATIONS):
        raise BackupError('Unsupported backup schema; use a compatible termnetlog version.')
    if conn.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise BackupError('Database integrity check failed.')
    if conn.execute('PRAGMA foreign_key_check').fetchone():
        raise BackupError('Database contains broken record references.')
    with closing(sqlite3.connect(':memory:')) as expected:
        for script in db.MIGRATIONS[:version]:
            expected.executescript(script)
        query = "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        if conn.execute(query).fetchall() != expected.execute(query).fetchall():
            raise BackupError('Database schema does not match termnetlog.')
    return version


def _snapshot(source: sqlite3.Connection, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    name = 'backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='.pending-', dir=directory) as stage:
        stage = Path(stage)
        database = stage / 'netlog.db'
        database.touch(mode=0o600)
        with closing(sqlite3.connect(database)) as dest:
            _copy(source, dest)
            dest.execute('PRAGMA journal_mode=DELETE')
            version = validate(dest)
        metadata = {'format': 1, 'app_version': __version__, 'schema_version': version,
                    'created_utc': datetime.now(timezone.utc).isoformat()}
        (stage / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
        for path in stage.iterdir():
            with path.open('rb') as handle:
                os.fsync(handle.fileno())
        result = directory / name
        stage.rename(result)
    return result


def backup(database: Path, directory: Path) -> Path:
    with closing(_read(database)) as source:
        return _snapshot(source, directory)


def restore(snapshot: Path, database: Path, *, replace: bool = False) -> Path | None:
    """Restore a validated private copy; existing targets require explicit replacement."""
    candidate = snapshot / 'netlog.db' if snapshot.is_dir() else snapshot
    if candidate.resolve() == database.resolve():
        raise BackupError('Restore source and destination must differ.')
    if database.exists() and not replace:
        raise BackupError('Destination exists; pass --replace to create a safety backup and replace it.')
    # Freeze and validate the candidate before touching the destination.
    with tempfile.TemporaryDirectory(prefix='termnetlog-restore-') as stage:
        frozen = Path(stage) / 'candidate.db'
        with closing(_read(candidate)) as source, closing(sqlite3.connect(frozen)) as copy:
            _copy(source, copy)
            validate(copy)
            db.migrate(copy)
            validate(copy)
            database.parent.mkdir(parents=True, exist_ok=True)
            created = False
            try:
                fd = os.open(database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                created = True
            except FileExistsError:
                if not replace:
                    raise BackupError('Destination exists; pass --replace to replace it.') from None
            try:
                with closing(sqlite3.connect(database, timeout=2)) as target:
                    # Retain an exclusive lock through safety snapshot and replacement.
                    # SQLite backup replaces pages transactionally, including WAL databases.
                    target.execute('PRAGMA locking_mode=EXCLUSIVE')
                    target.execute('BEGIN EXCLUSIVE')
                    target.commit()
                    safety = None if created else _snapshot(target, database.parent / 'backups')
                    _copy(copy, target)
                    return safety
            except BaseException:
                if created:
                    database.unlink(missing_ok=True)
                raise
