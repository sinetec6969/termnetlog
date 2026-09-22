from __future__ import annotations

from datetime import datetime, timezone, tzinfo

from termnetlog.config import display_timezone
from termnetlog.models import from_iso, utcnow

# Display timezone for the TUI. Storage and ADIF stay UTC; this only changes what's shown.
_local_tz: tzinfo = timezone.utc
_local_name = 'UTC'
_show_local = False


def set_display_tz(local_tz: str, show_local: bool) -> None:
    global _local_tz, _local_name, _show_local
    _local_tz = display_timezone(local_tz)
    _local_name = local_tz
    _show_local = show_local


def toggle_local() -> bool:
    global _show_local
    _show_local = not _show_local
    return _show_local


def _tz() -> tzinfo:
    return _local_tz if _show_local else timezone.utc


def local(iso: str | datetime | None) -> datetime | None:
    t = from_iso(iso) if isinstance(iso, str) or iso is None else iso
    return t.astimezone(_tz()) if t else None


def zone(iso: str | datetime | None = None) -> str:
    """Suffix for a displayed time: 'Z' for UTC, else the zone abbreviation (EDT/EST) at that moment."""
    if not _show_local:
        return "Z"
    return (local(iso) or datetime.now(_local_tz)).strftime("%Z")


def zone_label() -> str:
    """A stable heading; today's DST abbreviation may be wrong for old rows."""
    return "Local" if _show_local else "UTC"


def zone_name() -> str:
    return _local_name if _show_local else 'UTC'


def ago(iso: str | None, now: datetime | None = None) -> str:
    """Compact 'time since' label: today, 1d, 3w, 5mo, 2y."""
    t = local(iso)
    if t is None:
        return ""
    now = local(now or utcnow())
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
    t = local(iso)
    return f"{t:%H%M}" if t else ""


def date(iso: str | None) -> str:
    t = local(iso)
    return f"{t:%Y-%m-%d}" if t else ""


def elapsed(start_iso: str, end_iso: str | None = None) -> str:
    start = from_iso(start_iso)
    end = from_iso(end_iso) or utcnow()
    if start is None:
        return ""
    mins = max(0, int((end - start).total_seconds() // 60))
    return f"{mins // 60}:{mins % 60:02d}"
