"""All SQL lives here."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, asdict

from termnetlog.callsign import ParsedCall
from termnetlog.entry import Entry
from termnetlog.lookup.base import LookupResult
from termnetlog.models import FLAGS, CheckIn, CheckInRow, Net, Operator, to_iso, utcnow


class DuplicateCheckIn(Exception):
    def __init__(self, existing: CheckIn):
        super().__init__(f"{existing.callsign} already checked in (#{existing.seq})")
        self.existing = existing


OPERATOR_DATA_FIELDS = LookupResult.DATA_FIELDS


class Repo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def counts(self) -> tuple[int, int]:
        """(nets, operators)"""
        nets = self.conn.execute("SELECT COUNT(*) FROM nets").fetchone()[0]
        ops = self.conn.execute("SELECT COUNT(*) FROM operators").fetchone()[0]
        return nets, ops

    # ---- operators ---------------------------------------------------------

    def get_operator(self, callsign: str) -> Operator | None:
        row = self.conn.execute("SELECT * FROM operators WHERE callsign = ?", (callsign,)).fetchone()
        return Operator.from_row(row) if row else None

    def ensure_operator(self, callsign: str) -> Operator:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO operators (callsign, created_at) VALUES (?, ?)",
                (callsign, to_iso(utcnow())),
            )
        op = self.get_operator(callsign)
        assert op is not None
        return op

    def apply_lookup(self, result: LookupResult) -> Operator:
        """Store lookup data. Operators edited by hand are never overwritten."""
        op = self.ensure_operator(result.callsign)
        if op.lookup_source == "manual":
            return op
        # Missing provider fields are not instructions to erase known data.
        cols = ", ".join(f"{f} = COALESCE(NULLIF(?, ''), {f})" for f in OPERATOR_DATA_FIELDS)
        values = [getattr(result, f) for f in OPERATOR_DATA_FIELDS]
        with self.conn:
            self.conn.execute(
                f"UPDATE operators SET {cols}, lookup_source = ?, lookup_at = ? WHERE callsign = ?",
                (*values, result.source, to_iso(utcnow()), result.callsign),
            )
        return self.get_operator(result.callsign)  # type: ignore[return-value]

    def lookup_attempt(self, callsign: str) -> tuple[str, str] | None:
        row = self.conn.execute(
            "SELECT attempted_at, status FROM lookup_attempts WHERE callsign = ?", (callsign,)
        ).fetchone()
        return (row["attempted_at"], row["status"]) if row else None

    def record_lookup_attempt(self, callsign: str, status: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO lookup_attempts (callsign, attempted_at, status) VALUES (?, ?, ?)"
                " ON CONFLICT(callsign) DO UPDATE SET attempted_at = excluded.attempted_at,"
                " status = excluded.status",
                (callsign, to_iso(utcnow()), status),
            )

    def mark_looked_up(self, callsign: str, source: str) -> None:
        """Record a lookup attempt that found nothing, so we don't retry every time."""
        with self.conn:
            self.conn.execute(
                "UPDATE operators SET lookup_at = CASE WHEN lookup_source IS NULL OR lookup_source = 'none'"
                " THEN ? ELSE lookup_at END, lookup_source = COALESCE(lookup_source, ?)"
                " WHERE callsign = ? AND COALESCE(lookup_source, '') != 'manual'",
                (to_iso(utcnow()), source, callsign),
            )

    def update_operator(self, callsign: str, **values: str | None) -> Operator:
        """Manual edit of operator data fields; marks the record as manual."""
        bad = set(values) - set(OPERATOR_DATA_FIELDS)
        if bad:
            raise ValueError(f"unknown operator fields: {bad}")
        self.ensure_operator(callsign)
        if values:
            cols = ", ".join(f"{k} = ?" for k in values)
            with self.conn:
                self.conn.execute(
                    f"UPDATE operators SET {cols}, lookup_source = 'manual' WHERE callsign = ?",
                    (*[v or None for v in values.values()], callsign),
                )
        return self.get_operator(callsign)  # type: ignore[return-value]

    def set_operator_notes(self, callsign: str, notes: str) -> None:
        self.ensure_operator(callsign)
        with self.conn:
            self.conn.execute("UPDATE operators SET operator_notes = ? WHERE callsign = ?", (notes, callsign))

    def search_operators(self, query: str = "", limit: int = 200) -> list[OperatorSummary]:
        like = f"%{query.strip()}%"
        rows = self.conn.execute(
            """
            SELECT o.*, COUNT(c.id) AS checkin_count, MAX(c.time_utc) AS last_seen, MIN(c.time_utc) AS first_seen
            FROM operators o LEFT JOIN checkins c ON c.callsign = o.callsign
            WHERE o.callsign LIKE :q OR o.name LIKE :q OR o.nickname LIKE :q
               OR o.city LIKE :q OR o.operator_notes LIKE :q
            GROUP BY o.callsign
            ORDER BY (o.callsign LIKE :prefix) DESC, checkin_count DESC, o.callsign
            LIMIT :limit
            """,
            {"q": like, "prefix": f"{query.strip().upper()}%", "limit": limit},
        ).fetchall()
        return [self._summary(r) for r in rows]

    def suggest_callsigns(self, prefix: str, limit: int = 5) -> list[OperatorSummary]:
        if not prefix:
            return []
        rows = self.conn.execute(
            """
            SELECT o.*, COUNT(c.id) AS checkin_count, MAX(c.time_utc) AS last_seen, MIN(c.time_utc) AS first_seen
            FROM operators o LEFT JOIN checkins c ON c.callsign = o.callsign
            WHERE o.callsign LIKE ?
            GROUP BY o.callsign
            ORDER BY checkin_count DESC, o.callsign
            LIMIT ?
            """,
            (prefix.upper() + "%", limit),
        ).fetchall()
        return [self._summary(r) for r in rows]

    def operator_summary(self, callsign: str) -> OperatorSummary | None:
        row = self.conn.execute(
            """
            SELECT o.*, COUNT(c.id) AS checkin_count, MAX(c.time_utc) AS last_seen, MIN(c.time_utc) AS first_seen
            FROM operators o LEFT JOIN checkins c ON c.callsign = o.callsign
            WHERE o.callsign = ? GROUP BY o.callsign
            """,
            (callsign,),
        ).fetchone()
        return self._summary(row) if row else None

    @staticmethod
    def _summary(row: sqlite3.Row) -> OperatorSummary:
        return OperatorSummary(
            operator=Operator.from_row(row),
            checkin_count=row["checkin_count"],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
        )

    def operator_history(self, callsign: str, limit: int = 100) -> list[tuple[CheckIn, Net]]:
        rows = self.conn.execute(
            """
            SELECT c.*, n.id AS n_id, n.name AS n_name, n.frequency AS n_frequency, n.mode AS n_mode,
                   n.band AS n_band, n.started_utc AS n_started_utc, n.ended_utc AS n_ended_utc,
                   n.ncs_callsign AS n_ncs_callsign, n.my_role AS n_my_role, n.notes AS n_notes
            FROM checkins c JOIN nets n ON n.id = c.net_id
            WHERE c.callsign = ? ORDER BY c.time_utc DESC, c.id DESC LIMIT ?
            """,
            (callsign, limit),
        ).fetchall()
        out = []
        for r in rows:
            net = Net(**{k[2:]: r[k] for k in r.keys() if k.startswith("n_")})
            out.append((CheckIn.from_row(r), net))
        return out

    # ---- nets --------------------------------------------------------------

    def create_net(
        self, name: str, frequency: str, mode: str, band: str, ncs_callsign: str, my_role: str, notes: str = ""
    ) -> Net:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO nets (name, frequency, mode, band, started_utc, ncs_callsign, my_role, notes)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, frequency, mode, band, to_iso(utcnow()), ncs_callsign.upper(), my_role, notes),
            )
        return self.get_net(cur.lastrowid)  # type: ignore[arg-type,return-value]

    def get_net(self, net_id: int) -> Net | None:
        row = self.conn.execute("SELECT * FROM nets WHERE id = ?", (net_id,)).fetchone()
        return Net.from_row(row) if row else None

    def count_nets(self, search: str = "") -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM nets WHERE instr(lower(name), lower(?)) > 0 OR instr(substr(started_utc, 1, 10), ?) > 0",
            (search, search),
        ).fetchone()[0]

    def list_nets(self, limit: int = 200, *, offset: int = 0, search: str = "") -> list[tuple[Net, int]]:
        rows = self.conn.execute(
            """
            SELECT n.*, COUNT(c.id) AS checkin_count FROM nets n
            LEFT JOIN checkins c ON c.net_id = n.id
            WHERE instr(lower(n.name), lower(?)) > 0 OR instr(substr(n.started_utc, 1, 10), ?) > 0
            GROUP BY n.id ORDER BY n.started_utc DESC, n.id DESC LIMIT ? OFFSET ?
            """,
            (search, search, limit, offset),
        ).fetchall()
        return [(Net.from_row(r), r["checkin_count"]) for r in rows]

    def open_nets(self) -> list[Net]:
        rows = self.conn.execute(
            "SELECT * FROM nets WHERE ended_utc IS NULL ORDER BY started_utc DESC"
        ).fetchall()
        return [Net.from_row(r) for r in rows]

    def end_net(self, net_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE nets SET ended_utc = ? WHERE id = ? AND ended_utc IS NULL", (to_iso(utcnow()), net_id)
            )

    def reopen_net(self, net_id: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE nets SET ended_utc = NULL WHERE id = ?", (net_id,))

    def update_net(self, net_id: int, **values: str) -> None:
        allowed = {"name", "frequency", "mode", "band", "ncs_callsign", "my_role", "notes"}
        if set(values) - allowed:
            raise ValueError(f"unknown net fields: {set(values) - allowed}")
        if not values:
            return
        cols = ", ".join(f"{k} = ?" for k in values)
        with self.conn:
            self.conn.execute(f"UPDATE nets SET {cols} WHERE id = ?", (*values.values(), net_id))

    def delete_net(self, net_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM nets WHERE id = ?", (net_id,))

    # ---- check-ins ---------------------------------------------------------

    def add_checkin(self, net_id: int, call: ParsedCall, relayed_by: str = "") -> CheckIn:
        return self.record_entry(net_id, Entry(call=call, relayed_by=relayed_by))

    def record_entry(self, net_id: int, entry: Entry) -> CheckIn:
        """Save an entire entry, without committing any enclosing transaction."""
        flags = set(entry.flags)
        if flags - set(FLAGS):
            raise ValueError("Unknown check-in flag")
        call = entry.call
        flags.update(flag for flag in ('mobile', 'portable') if getattr(call, flag))
        self.conn.execute("SAVEPOINT record_entry")
        try:
            # This write acquires the writer lock before sequence allocation.
            # Do not call helpers that commit independently inside this savepoint.
            self.conn.execute(
                "INSERT OR IGNORE INTO operators (callsign, created_at) VALUES (?, ?)",
                (call.base, to_iso(utcnow())),
            )
            existing = self.conn.execute(
                "SELECT * FROM checkins WHERE net_id = ? AND callsign = ?", (net_id, call.base)
            ).fetchone()
            if existing:
                raise DuplicateCheckIn(CheckIn.from_row(existing))
            seq = self.conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM checkins WHERE net_id = ?", (net_id,)
            ).fetchone()[0]
            cur = self.conn.execute(
                "INSERT INTO checkins (net_id, callsign, logged_as, seq, time_utc,"
                " mobile, portable, has_traffic, short_time, recognized, ragchew, relayed_by, notes)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (net_id, call.base, call.raw, seq, to_iso(utcnow()),
                 *(int(flag in flags) for flag in FLAGS), entry.relayed_by, entry.note),
            )
            result = self.get_checkin(cur.lastrowid)
            assert result is not None
            self.conn.execute("RELEASE SAVEPOINT record_entry")
            return result
        except BaseException:
            # Some SQLite failures roll back the entire transaction themselves.
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK TO SAVEPOINT record_entry")
                self.conn.execute("RELEASE SAVEPOINT record_entry")
            raise

    def correct_callsign(self, checkin_id: int, call: ParsedCall) -> CheckIn:
        """Change only one check-in's identity; never move operator profiles/notes."""
        self.conn.execute('SAVEPOINT correct_callsign')
        try:
            self.conn.execute('INSERT OR IGNORE INTO operators (callsign, created_at) VALUES (?, ?)',
                              (call.base, to_iso(utcnow())))
            current = self.get_checkin(checkin_id)
            if current is None:
                raise ValueError('Check-in no longer exists')
            duplicate = self.conn.execute(
                'SELECT * FROM checkins WHERE net_id=? AND callsign=? AND id!=?',
                (current.net_id, call.base, checkin_id),
            ).fetchone()
            if duplicate:
                raise DuplicateCheckIn(CheckIn.from_row(duplicate))
            self.conn.execute('UPDATE checkins SET callsign=?, logged_as=? WHERE id=?',
                              (call.base, call.raw, checkin_id))
            result = self.get_checkin(checkin_id)
            assert result is not None
            self.conn.execute('RELEASE SAVEPOINT correct_callsign')
            return result
        except BaseException:
            if self.conn.in_transaction:
                self.conn.execute('ROLLBACK TO SAVEPOINT correct_callsign')
                self.conn.execute('RELEASE SAVEPOINT correct_callsign')
            raise

    def get_checkin(self, checkin_id: int) -> CheckIn | None:
        row = self.conn.execute("SELECT * FROM checkins WHERE id = ?", (checkin_id,)).fetchone()
        return CheckIn.from_row(row) if row else None

    def list_checkins(self, net_id: int) -> list[CheckInRow]:
        rows = self.conn.execute(
            """
            SELECT c.*,
                   o.callsign AS o_callsign, o.first_name AS o_first_name, o.name AS o_name,
                   o.nickname AS o_nickname, o.city AS o_city, o.state AS o_state, o.county AS o_county,
                   o.country AS o_country, o.grid AS o_grid, o.license_class AS o_license_class,
                   o.lookup_source AS o_lookup_source, o.lookup_at AS o_lookup_at,
                   o.operator_notes AS o_operator_notes, o.created_at AS o_created_at,
                   (SELECT COUNT(*) FROM checkins c2
                     WHERE c2.callsign = c.callsign
                       AND (c2.time_utc < c.time_utc
                            OR (c2.time_utc = c.time_utc AND c2.id <= c.id))) AS nth,
                   (SELECT MAX(c2.time_utc) FROM checkins c2
                     WHERE c2.callsign = c.callsign AND c2.net_id != c.net_id
                       AND (c2.time_utc < c.time_utc
                            OR (c2.time_utc = c.time_utc AND c2.id < c.id))) AS prev_seen
            FROM checkins c JOIN operators o ON o.callsign = c.callsign
            WHERE c.net_id = ? ORDER BY c.seq
            """,
            (net_id,),
        ).fetchall()
        return [
            CheckInRow(
                checkin=CheckIn.from_row(r),
                operator=Operator.from_row(r, prefix="o_"),
                nth=r["nth"],
                prev_seen=r["prev_seen"],
            )
            for r in rows
        ]

    def toggle_flag(self, checkin_id: int, flag: str) -> CheckIn:
        if flag not in FLAGS:
            raise ValueError(f"unknown flag {flag!r}")
        with self.conn:
            self.conn.execute(f"UPDATE checkins SET {flag} = 1 - {flag} WHERE id = ?", (checkin_id,))
        return self.get_checkin(checkin_id)  # type: ignore[return-value]

    def set_flag(self, checkin_id: int, flag: str, value: bool = True) -> None:
        if flag not in FLAGS:
            raise ValueError(f"unknown flag {flag!r}")
        with self.conn:
            self.conn.execute(f"UPDATE checkins SET {flag} = ? WHERE id = ?", (int(value), checkin_id))

    def set_checkin_notes(self, checkin_id: int, notes: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE checkins SET notes = ? WHERE id = ?", (notes, checkin_id))

    def set_relayed_by(self, checkin_id: int, relayed_by: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE checkins SET relayed_by = ? WHERE id = ?", (relayed_by.strip().upper(), checkin_id)
            )

    def delete_checkin(self, checkin_id: int) -> CheckIn | None:
        self.conn.execute('SAVEPOINT remove_checkin')
        try:
            # Acquire the writer lock before capturing the undo record.
            self.conn.execute('UPDATE checkins SET id=id WHERE id=?', (checkin_id,))
            ci = self.get_checkin(checkin_id)
            if ci is None:
                self.conn.execute('RELEASE SAVEPOINT remove_checkin')
                return None
            self.conn.execute("DELETE FROM checkins WHERE id = ?", (checkin_id,))
            self.conn.execute(
                "UPDATE checkins SET seq = seq - 1 WHERE net_id = ? AND seq > ?", (ci.net_id, ci.seq)
            )
            self.conn.execute('RELEASE SAVEPOINT remove_checkin')
            return ci
        except BaseException:
            if self.conn.in_transaction:
                self.conn.execute('ROLLBACK TO SAVEPOINT remove_checkin')
                self.conn.execute('RELEASE SAVEPOINT remove_checkin')
            raise

    def restore_checkin(self, removed: CheckIn) -> CheckIn:
        """Restore a removed entry at its old position without replacing any record."""
        self.conn.execute('SAVEPOINT restore_checkin')
        try:
            self.conn.execute('UPDATE nets SET id=id WHERE id=?', (removed.net_id,))
            duplicate = self.conn.execute('SELECT * FROM checkins WHERE net_id=? AND callsign=?',
                                          (removed.net_id, removed.callsign)).fetchone()
            if duplicate:
                raise DuplicateCheckIn(CheckIn.from_row(duplicate))
            count = self.conn.execute('SELECT COUNT(*) FROM checkins WHERE net_id=?', (removed.net_id,)).fetchone()[0]
            values = asdict(removed)
            values['seq'] = min(max(1, removed.seq), count + 1)
            # SQLite may reuse the last deleted row ID for a later check-in.
            if self.get_checkin(removed.id) is not None:
                del values['id']
            self.conn.execute('UPDATE checkins SET seq=seq+1 WHERE net_id=? AND seq>=?',
                              (removed.net_id, values['seq']))
            cur = self.conn.execute(
                f"INSERT INTO checkins ({', '.join(values)}) VALUES ({', '.join('?' for _ in values)})",
                tuple(values.values()),
            )
            result = self.get_checkin(cur.lastrowid)
            assert result is not None
            self.conn.execute('RELEASE SAVEPOINT restore_checkin')
            return result
        except BaseException:
            if self.conn.in_transaction:
                self.conn.execute('ROLLBACK TO SAVEPOINT restore_checkin')
                self.conn.execute('RELEASE SAVEPOINT restore_checkin')
            raise

    def move_checkin(self, checkin_id: int, delta: int) -> None:
        """Swap a check-in with its neighbour (delta -1 = up, +1 = down)."""
        ci = self.get_checkin(checkin_id)
        if ci is None:
            return
        other = self.conn.execute(
            "SELECT id FROM checkins WHERE net_id = ? AND seq = ?", (ci.net_id, ci.seq + delta)
        ).fetchone()
        if other is None:
            return
        with self.conn:
            self.conn.execute("UPDATE checkins SET seq = ? WHERE id = ?", (ci.seq, other["id"]))
            self.conn.execute("UPDATE checkins SET seq = ? WHERE id = ?", (ci.seq + delta, ci.id))


@dataclass
class OperatorSummary:
    operator: Operator
    checkin_count: int
    first_seen: str | None
    last_seen: str | None
