from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _from_row(cls, row: sqlite3.Row, prefix: str = ""):
    keys = row.keys()
    kwargs = {}
    for f in fields(cls):
        key = prefix + f.name
        if key in keys:
            kwargs[f.name] = row[key]
    return cls(**kwargs)


@dataclass
class Operator:
    callsign: str
    first_name: str | None = None
    name: str | None = None
    nickname: str | None = None
    city: str | None = None
    state: str | None = None
    county: str | None = None
    country: str | None = None
    grid: str | None = None
    license_class: str | None = None
    lookup_source: str | None = None
    lookup_at: str | None = None
    operator_notes: str = ""
    created_at: str = ""

    @classmethod
    def from_row(cls, row: sqlite3.Row, prefix: str = "") -> Operator:
        return _from_row(cls, row, prefix)

    @property
    def display_name(self) -> str:
        return self.nickname or self.first_name or self.name or ""

    @property
    def full_name(self) -> str:
        return self.name or self.first_name or ""

    @property
    def location(self) -> str:
        if self.city and self.state:
            return f"{self.city}, {self.state}"
        return self.city or self.state or self.country or ""


@dataclass
class Net:
    id: int
    name: str
    frequency: str
    mode: str
    band: str
    started_utc: str
    ended_utc: str | None
    ncs_callsign: str
    my_role: str
    notes: str = ""

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Net:
        return _from_row(cls, row)

    @property
    def is_open(self) -> bool:
        return self.ended_utc is None

    @property
    def is_ncs(self) -> bool:
        return self.my_role == "ncs"


FLAGS = ("mobile", "portable", "has_traffic", "short_time", "recognized", "ragchew", "echolink")


@dataclass
class CheckIn:
    id: int
    net_id: int
    callsign: str
    logged_as: str
    seq: int
    time_utc: str
    mobile: int = 0
    portable: int = 0
    has_traffic: int = 0
    short_time: int = 0
    recognized: int = 0
    ragchew: int = 0
    echolink: int = 0
    relayed_by: str = ""
    notes: str = ""

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> CheckIn:
        return _from_row(cls, row)


@dataclass
class CheckInRow:
    """A check-in joined with its operator and history stats."""

    checkin: CheckIn
    operator: Operator
    nth: int  # this operator's nth check-in overall (1 == first time)
    prev_seen: str | None  # time of their previous check-in on another net

    @property
    def is_new(self) -> bool:
        return self.nth == 1
