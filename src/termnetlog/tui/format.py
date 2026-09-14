from __future__ import annotations

from datetime import datetime

from termnetlog.models import from_iso, utcnow


def ago(iso: str | None, now: datetime | None = None) -> str:
    """Compact 'time since' label: today, 1d, 3w, 5mo, 2y."""
    t = from_iso(iso)
    if t is None:
        return ""
    now = now or utcnow()
    days = (now.date() - t.date()).days
    if days <= 0:
        return "today"
    if days < 14:
        return f"{days}d"
    if days < 60:
        return f"{days // 7}w"
    if days < 365:
        return f"{days // 30}mo"
    return f"{days // 365}y"


def hhmm(iso: str | None) -> str:
    t = from_iso(iso)
    return f"{t:%H%M}" if t else ""


def date(iso: str | None) -> str:
    t = from_iso(iso)
    return f"{t:%Y-%m-%d}" if t else ""


def elapsed(start_iso: str, end_iso: str | None = None) -> str:
    start = from_iso(start_iso)
    end = from_iso(end_iso) or utcnow()
    if start is None:
        return ""
    mins = max(0, int((end - start).total_seconds() // 60))
    return f"{mins // 60}:{mins % 60:02d}"
