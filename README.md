# termnetlog

A keyboard-driven terminal logger for amateur radio nets (built for a nightly 2m FM net).
Type a callsign, it's logged and looked up in the background (QRZ.com, falling back to HamDB),
and every operator you've logged before shows their history and your notes about them.

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/termnetlog
```

First run creates `~/.config/termnetlog/config.toml` (mode 0600). Set `my_callsign`, your net
defaults, and optionally your QRZ login. Without a paid QRZ XML subscription QRZ returns partial
records; HamDB (free, US FCC data) fills in name/location.

Data lives in `~/.local/share/termnetlog/netlog.db`; exports go to `~/.local/share/termnetlog/exports/`.
Override with `TERMNETLOG_DB`, `TERMNETLOG_CONFIG`, or `--db` / `--config`.

## Logging a net

Entry line syntax: `CALL [flags] [via RELAY] [note…]`

```
w1aw                       plain check-in
k9xyz/m t r                mobile, has traffic, staying for the ragchew
n0call via w1aw weak       relayed by W1AW, note "weak"
```

Flags: **t** traffic · **s** short time · **r** ragchew · **c** recognized · **m** mobile · **p** portable

`esc` jumps to the check-in list, where those same letters toggle flags on the selected row,
`enter` edits the check-in note, `o` edits persistent operator notes, `e` edits operator details,
`l` re-runs the lookup. Start typing a callsign to jump back to the entry line.
`ctrl+e` export · `ctrl+g` net notes · `ctrl+x` end net · `ctrl+b` menu · `ctrl+t` UTC/Eastern times · `f1` help.

`ctrl+t` only changes what's on screen; the database, text roster, and ADIF exports stay in UTC.
Set `[display] local_tz` (default `America/New_York`) and `local_time = true` in the config to change the zone or start in local time.

## CLI

```sh
termnetlog lookup W1AW              # test lookups / cache an operator
termnetlog nets                     # list nets
termnetlog export 12 -f text        # roster for email/groups.io
termnetlog export 12 -f adif -o net.adi
```

## Tests

```sh
.venv/bin/python -m pytest
```
