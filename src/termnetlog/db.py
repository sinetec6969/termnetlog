"""SQLite connection and schema migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class SchemaVersionError(ValueError):
    """The database was created by a newer application version."""


MIGRATIONS: list[str] = [
    # 1: initial schema
    """
    CREATE TABLE operators (
        callsign       TEXT PRIMARY KEY,
        first_name     TEXT,
        name           TEXT,
        nickname       TEXT,
        city           TEXT,
        state          TEXT,
        county         TEXT,
        country        TEXT,
        grid           TEXT,
        license_class  TEXT,
        lookup_source  TEXT,
        lookup_at      TEXT,
        operator_notes TEXT NOT NULL DEFAULT '',
        created_at     TEXT NOT NULL
    );

    CREATE TABLE nets (
        id           INTEGER PRIMARY KEY,
        name         TEXT NOT NULL,
        frequency    TEXT NOT NULL DEFAULT '',
        mode         TEXT NOT NULL DEFAULT 'FM',
        band         TEXT NOT NULL DEFAULT '2m',
        started_utc  TEXT NOT NULL,
        ended_utc    TEXT,
        ncs_callsign TEXT NOT NULL DEFAULT '',
        my_role      TEXT NOT NULL DEFAULT 'ncs',
        notes        TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE checkins (
        id          INTEGER PRIMARY KEY,
        net_id      INTEGER NOT NULL REFERENCES nets(id) ON DELETE CASCADE,
        callsign    TEXT NOT NULL REFERENCES operators(callsign),
        logged_as   TEXT NOT NULL,
        seq         INTEGER NOT NULL,
        time_utc    TEXT NOT NULL,
        mobile      INTEGER NOT NULL DEFAULT 0,
        portable    INTEGER NOT NULL DEFAULT 0,
        has_traffic INTEGER NOT NULL DEFAULT 0,
        short_time  INTEGER NOT NULL DEFAULT 0,
        recognized  INTEGER NOT NULL DEFAULT 0,
        ragchew     INTEGER NOT NULL DEFAULT 0,
        relayed_by  TEXT NOT NULL DEFAULT '',
        notes       TEXT NOT NULL DEFAULT '',
        UNIQUE (net_id, callsign)
    );

    CREATE INDEX checkins_callsign_time ON checkins (callsign, time_utc);
    CREATE INDEX nets_started ON nets (started_utc);
    """,
    # 2: refresh attempts are distinct from the last stored operator data.
    """
    CREATE TABLE lookup_attempts (
        callsign TEXT PRIMARY KEY REFERENCES operators(callsign) ON DELETE CASCADE,
        attempted_at TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('complete', 'partial', 'not_found', 'error'))
    );
    """,
    # 3: EchoLink check-in flag.
    """
    ALTER TABLE checkins ADD COLUMN echolink INTEGER NOT NULL DEFAULT 0;
    """,
]


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > len(MIGRATIONS):
        raise SchemaVersionError(f"Database schema {version} requires a newer termnetlog version")
    for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
        with conn:
            conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {i};\nCOMMIT;")


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        migrate(conn)
        if str(path) != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
    except Exception:
        conn.close()
        raise
    return conn
