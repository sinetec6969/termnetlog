"""ADIF and plain-text roster export."""

from __future__ import annotations

from termnetlog import __version__, adif
from termnetlog.models import CheckInRow, Net, from_iso

FLAG_LABELS = {
    "has_traffic": "traffic",
    "mobile": "mobile",
    "portable": "portable",
    "echolink": "EchoLink",
    "short_time": "short time",
    "recognized": "recognized",
    "ragchew": "ragchew",
}


def flag_words(row: CheckInRow) -> list[str]:
    ci = row.checkin
    words = [label for flag, label in FLAG_LABELS.items() if getattr(ci, flag)]
    if ci.relayed_by:
        words.append(f"via {ci.relayed_by}")
    return words


def _adif_field(name: str, value: str | None, warnings: list[str] | None = None) -> str:
    if value is None or value == "":
        return ""
    value = adif.ascii_text(str(value), name, warnings)
    if not value:
        return ""
    return f"<{name}:{len(value)}>{value} "


def to_adif(net: Net, rows: list[CheckInRow], station_callsign: str = "", *,
            warnings: list[str] | None = None) -> str:
    """Render validated ADI; report lossy free-text conversion in warnings."""
    started = adif.timestamp(net.started_utc, 'Net start')
    band, frequency, mode, submode = adif.radio_fields(net.band, net.frequency, net.mode)
    station_callsign = adif.call(station_callsign, 'STATION_CALLSIGN', optional=True)
    def field(name: str, value: str | None) -> str:
        return _adif_field(name, value, warnings)

    header = (
        f"termnetlog export: net {net.id} {started:%Y-%m-%d %H:%MZ}\n"
        f"{_adif_field('ADIF_VER', '3.1.4')}{_adif_field('PROGRAMID', 'termnetlog')}"
        f"{_adif_field('PROGRAMVERSION', __version__)}\n<EOH>\n"
    )
    records = []
    for row in rows:
        ci, op = row.checkin, row.operator
        t = adif.timestamp(ci.time_utc, f'Check-in #{ci.seq} time')
        call = adif.call(ci.logged_as, f'Check-in #{ci.seq} CALL')
        grid, grid_ext = adif.grid(op.grid, f'{call} GRIDSQUARE')
        comment_parts = [f"{net.name}"] + flag_words(row)
        if ci.notes:
            comment_parts.append(ci.notes.replace("\n", " "))
        rec = "".join(
            [
                field("CALL", call),
                field("QSO_DATE", f"{t:%Y%m%d}"),
                field("TIME_ON", f"{t:%H%M%S}"),
                field("BAND", band),
                field("FREQ", frequency),
                field("MODE", mode),
                field("SUBMODE", submode),
                field("NAME", op.full_name),
                field("QTH", op.city),
                field("STATE", op.state),
                field("CNTY", f"{op.state},{op.county}" if op.state and op.county else None),
                field("COUNTRY", op.country),
                field("GRIDSQUARE", grid),
                field("GRIDSQUARE_EXT", grid_ext),
                field("STATION_CALLSIGN", station_callsign or None),
                field("COMMENT", "; ".join(comment_parts)),
            ]
        )
        records.append(rec + "<EOR>")
    return header + "\n".join(records) + "\n"


def to_text(net: Net, rows: list[CheckInRow]) -> str:
    started = from_iso(net.started_utc)
    ended = from_iso(net.ended_utc)
    when = f"{started:%Y-%m-%d %H:%M}"
    when += f"–{ended:%H:%M} UTC" if ended else " UTC (in progress)"
    lines = [
        f"{net.name} — {when}",
        f"{net.frequency} MHz {net.mode}" + (f" · NCS: {net.ncs_callsign}" if net.ncs_callsign else ""),
        f"{len(rows)} check-in{'s' if len(rows) != 1 else ''}",
        "",
    ]
    call_w = max([len(r.checkin.logged_as) for r in rows] + [4])
    name_w = max([len(r.operator.display_name) for r in rows] + [4])
    loc_w = max([len(r.operator.location) for r in rows] + [4])
    for r in rows:
        t = from_iso(r.checkin.time_utc)
        flags = flag_words(r)
        line = (
            f"{r.checkin.seq:>3}  {t:%H:%M}Z  {r.checkin.logged_as:<{call_w}}  "
            f"{r.operator.display_name:<{name_w}}  {r.operator.location:<{loc_w}}"
        )
        if flags:
            line += f"  [{', '.join(flags)}]"
        lines.append(line.rstrip())
        if r.checkin.notes:
            lines.append(f"{'':>{call_w + 15}}{r.checkin.notes}")

    def calls(pred) -> str:
        return ", ".join(r.checkin.logged_as for r in rows if pred(r))

    extras = [
        ("Traffic", calls(lambda r: r.checkin.has_traffic)),
        ("Stayed for ragchew", calls(lambda r: r.checkin.ragchew)),
        ("First-time check-ins", calls(lambda r: r.is_new)),
    ]
    extra_lines = [f"{label}: {value}" for label, value in extras if value]
    if extra_lines:
        lines += [""] + extra_lines
    if net.notes:
        lines += ["", "Notes:", net.notes]
    return "\n".join(lines) + "\n"
