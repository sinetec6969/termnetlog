"""All SQL lives here."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from termnetlog.callsign import ParsedCall
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
        cols = ", ".join(f"{f} = ?" for f in OPERATOR_DATA_FIELDS)
        values = [getattr(result, f) for f in OPERATOR_DATA_FIELDS]
        with self.conn:
            self.conn.execute(
                f"UPDATE operators SET {cols}, lookup_source = ?, lookup_at = ? WHERE callsign = ?",
                (*values, result.source, to_iso(utcnow()), result.callsign),
            )
        return self.get_operator(result.callsign)  # type: ignore[return-value]

    def mark_looked_up(self, callsign: str, source: str) -> None:
        """Record a lookup attempt that found nothing, so we don't retry every time."""
        with self.conn:
            self.conn.execute(
                "UPDATE operators SET lookup_at = ?, lookup_source = COALESCE(lookup_source, ?)"
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
            WHERE c.callsign = ? ORDER BY c.time_utc DESC LIMIT ?
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
        self, name: str, frequency: str, mode: str, band: str, ncs_callsign: str, my_role: str
    ) -> Net:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO nets (name, frequency, mode, band, started_utc, ncs_callsign, my_role)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, frequency, mode, band, to_iso(utcnow()), ncs_callsign.upper(), my_role),
            )
        return self.get_net(cur.lastrowid)  # type: ignore[arg-type,return-value]

    def get_net(self, net_id: int) -> Net | None:
        row = self.conn.execute("SELECT * FROM nets WHERE id = ?", (net_id,)).fetchone()
        return Net.from_row(row) if row else None

    def list_nets(self, limit: int = 200) -> list[tuple[Net, int]]:
        rows = self.conn.execute(
            """
            SELECT n.*, COUNT(c.id) AS checkin_count FROM nets n
            LEFT JOIN checkins c ON c.net_id = n.id
            GROUP BY n.id ORDER BY n.started_utc DESC, n.id DESC LIMIT ?
            """,
            (limit,),
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
        existing = self.conn.execute(
            "SELECT * FROM checkins WHERE net_id = ? AND callsign = ?", (net_id, call.base)
        ).fetchone()
        if existing:
            raise DuplicateCheckIn(CheckIn.from_row(existing))
        self.ensure_operator(call.base)
        with self.conn:
            seq = self.conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM checkins WHERE net_id = ?", (net_id,)
            ).fetchone()[0]
            cur = self.conn.execute(
                "INSERT INTO checkins (net_id, callsign, logged_as, seq, time_utc, mobile, portable, relayed_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (net_id, call.base, call.raw, seq, to_iso(utcnow()), int(call.mobile), int(call.portable), relayed_by),
            )
        return self.get_checkin(cur.lastrowid)  # type: ignore[arg-type,return-value]

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
                       AND (c2.time_utc < c.time_utc OR c2.id = c.id)) AS nth,
                   (SELECT MAX(c2.time_utc) FROM checkins c2
                     WHERE c2.callsign = c.callsign AND c2.net_id != c.net_id
                       AND c2.time_utc < c.time_utc) AS prev_seen
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

    def delete_checkin(self, checkin_id: int) -> None:
        ci = self.get_checkin(checkin_id)
        if ci is None:
            return
        with self.conn:
            self.conn.execute("DELETE FROM checkins WHERE id = ?", (checkin_id,))
            self.conn.execute(
                "UPDATE checkins SET seq = seq - 1 WHERE net_id = ? AND seq > ?", (ci.net_id, ci.seq)
            )

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
